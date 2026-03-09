"""
추론(Predict) 관련 API 라우터.

이 모듈에 정의된 엔드포인트:
  GET  /health   — 서버·모델·MinIO·StarRocks 연결 상태 확인
  POST /predict  — 이미지를 업로드해 PaDiM 이상 탐지 수행
  GET  /history  — 최근 검사 이력 조회 (StarRocks → Iceberg)
  GET  /stats    — 일별 이상 탐지 통계 집계
"""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from api.schemas import HealthResponse, HistoryResponse, InspectionRecord, PredictResponse, StatsResponse
from api.state import AppState, get_state

# 이 라우터를 api/main.py 에서 app.include_router() 로 등록합니다.
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# GET /health
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, summary="서버 상태 확인")
async def health(state: Annotated[AppState, Depends(get_state)]) -> HealthResponse:
    """
    서버의 전반적인 건강 상태를 반환합니다.

    확인 항목:
    - 모델 로드 여부
    - MinIO 연결 여부 (weights/ 오브젝트 목록 조회로 확인)
    - StarRocks 연결 여부 (ping 쿼리로 확인)

    model_loaded 와 minio_connected 가 모두 True 이면 status='ok',
    하나라도 False 이면 status='degraded' 를 반환합니다.
    """
    # MinIO 연결 확인 — weights/ 경로를 조회해 실제 연결 가능 여부 검증
    minio_ok = False
    try:
        if state.storage:
            state.storage.list_objects(prefix="weights/")
            minio_ok = True
    except Exception:
        pass  # 연결 실패해도 서버는 계속 동작

    # StarRocks 연결 확인 — SELECT 1 쿼리로 응답 여부만 확인
    sr_ok = False
    try:
        if state.starrocks:
            sr_ok = state.starrocks.ping()
    except Exception:
        pass

    # 핵심 기능(모델+스토리지)이 모두 준비됐으면 'ok', 아니면 'degraded'
    overall = "ok" if (state.model_loaded and minio_ok) else "degraded"
    return HealthResponse(
        status=overall,
        model_loaded=state.model_loaded,
        minio_connected=minio_ok,
        starrocks_connected=sr_ok,
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /predict
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/predict", response_model=PredictResponse, summary="이미지 이상 탐지 추론")
async def predict(
    state: Annotated[AppState, Depends(get_state)],
    file: UploadFile = File(..., description="검사할 이미지 파일 (PNG/JPEG)"),
) -> PredictResponse:
    """
    업로드된 이미지에 PaDiM 이상 탐지를 수행합니다.

    처리 순서:
      1. 모델 로드 여부 확인
      2. 업로드된 이미지 파일을 numpy 배열로 변환
      3. PaDiM 모델로 이상 점수(anomaly_score)와 이상 맵(anomaly_map) 계산
      4. 임계값(threshold) 과 비교해 결함 여부(is_anomaly) 판정
      5. 히트맵 PNG 생성 → MinIO 업로드 + 로컬 저장
      6. 결과 JSON 파일 로컬 저장
      7. Iceberg 테이블에 검사 결과 기록
      8. 응답 반환

    히트맵·JSON 저장이 실패해도 추론 결과(score, is_anomaly)는 정상 반환됩니다.
    Iceberg 기록 실패는 경고 로그만 남기고 계속 진행합니다.
    """
    # 모델이 아직 로드되지 않으면 503 오류 반환
    if not state.model_loaded:
        raise HTTPException(
            status_code=503,
            detail="모델이 로드되지 않았습니다. 먼저 POST /train 을 실행하세요.",
        )

    # 업로드된 파일 전체 내용을 메모리로 읽기
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    from src.utils import image_to_array, now_iso

    # 이미지 bytes → (H, W, 3) uint8 RGB numpy 배열 변환
    try:
        img_array = image_to_array(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"이미지 파싱 실패: {e}") from e

    # 이번 추론을 식별하는 고유 ID 생성 (결과 파일명 등에 사용)
    inference_id = str(uuid.uuid4())
    filename = file.filename or f"{inference_id}.png"

    # ── 추론 실행 ─────────────────────────────────────────────────────────────
    try:
        score, anomaly_map = state.run_inference(img_array)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"추론 중 오류 발생: {e}") from e

    # config.yaml 의 inference.threshold 와 비교해 결함 여부 판정
    threshold = state.config["inference"]["threshold"]
    is_anomaly = bool(score >= threshold)

    # ── 히트맵 생성 및 저장 ───────────────────────────────────────────────────
    heatmap_minio_path: str | None = None
    try:
        from src.utils import generate_heatmap_bytes

        # 원본 이미지 + 이상 맵 + 판정 결과를 시각화한 PNG bytes 생성
        heatmap_bytes = generate_heatmap_bytes(img_array, anomaly_map, score, is_anomaly)

        # MinIO 에 업로드 (heatmaps/{uuid}.png)
        if state.storage:
            obj_name = f"heatmaps/{inference_id}.png"
            heatmap_minio_path = state.storage.upload_bytes(
                heatmap_bytes, obj_name, content_type="image/png"
            )

        # 로컬 results/ 디렉터리에도 동일 파일 저장 (오프라인 확인용)
        results_dir = state.config["output"]["results_dir"]
        os.makedirs(results_dir, exist_ok=True)
        local_heatmap = os.path.join(results_dir, f"{inference_id}_heatmap.png")
        with open(local_heatmap, "wb") as f:
            f.write(heatmap_bytes)
    except Exception:
        pass  # 히트맵 생성/저장 실패해도 추론 결과는 정상 반환

    # ── 결과 JSON 로컬 저장 ────────────────────────────────────────────────────
    result_json_path: str | None = None
    try:
        from src.utils import save_result_json

        # 저장할 딕셔너리 구성 (나중에 Iceberg 에 넣는 내용과 동일)
        result_dict = {
            "id": inference_id,
            "filename": filename,
            "timestamp": now_iso(),           # UTC ISO 8601 형식
            "anomaly_score": float(score),
            "is_anomaly": is_anomaly,
            "threshold": threshold,
            "heatmap_minio_path": heatmap_minio_path,
            "model_version": state.model_version,
        }
        result_json_path = save_result_json(
            result_dict,
            state.config["output"]["results_dir"],
            f"{inference_id}_result.json",
        )
    except Exception:
        pass  # JSON 저장 실패해도 계속

    # ── Iceberg 테이블에 검사 결과 기록 ─────────────────────────────────────
    # 실패해도 추론 결과 반환에는 영향 없지만, 경고 로그로 추적 가능하게 합니다.
    try:
        if state.iceberg_writer:
            state.iceberg_writer.append_result(
                {
                    "id": inference_id,
                    "filename": filename,
                    "timestamp": now_iso(),
                    "anomaly_score": float(score),
                    "is_anomaly": is_anomaly,
                    "heatmap_minio_path": heatmap_minio_path or "",
                    "model_version": state.model_version or "",
                }
            )
    except Exception as e:
        import logging
        logging.getLogger("api").warning("Iceberg 기록 실패 (비치명적): %s", e)

    # ── 최종 응답 반환 ─────────────────────────────────────────────────────────
    return PredictResponse(
        filename=filename,
        anomaly_score=round(float(score), 6),  # 소수점 6자리로 반올림
        is_anomaly=is_anomaly,
        threshold=threshold,
        heatmap_minio_path=heatmap_minio_path,
        result_json_path=result_json_path,
        inference_id=inference_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /history
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/history", response_model=HistoryResponse, summary="최근 검사 이력 조회")
async def history(
    state: Annotated[AppState, Depends(get_state)],
    n: int = Query(default=50, ge=1, le=500, description="조회할 최대 건수 (1~500)"),
) -> HistoryResponse:
    """
    StarRocks 를 통해 Iceberg 테이블의 최근 검사 이력을 조회합니다.

    내부적으로 SELECT * FROM iceberg_catalog.default.inspection_results
    ORDER BY timestamp DESC LIMIT n 쿼리를 실행합니다.

    첫 조회 시 Iceberg 메타데이터와 Parquet 파일을 읽으므로 수십 초 소요될 수 있습니다.
    이후 조회는 StarRocks 캐시 덕분에 빠르게 응답합니다.
    """
    if not state.starrocks:
        raise HTTPException(status_code=503, detail="StarRocks에 연결되어 있지 않습니다.")
    try:
        # StarRocks SQL 쿼리 실행 — 딕셔너리 리스트로 반환
        rows = state.starrocks.query_recent(n=n)
        # 각 딕셔너리를 InspectionRecord Pydantic 모델로 변환
        records = [InspectionRecord(**{k: v for k, v in row.items()}) for row in rows]
        return HistoryResponse(total=len(records), records=records)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"조회 실패: {e}") from e


# ──────────────────────────────────────────────────────────────────────────────
# GET /stats
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse, summary="일별 이상 탐지 통계")
async def stats(state: Annotated[AppState, Depends(get_state)]) -> StatsResponse:
    """
    StarRocks 를 통해 날짜별 검사 통계를 집계해 반환합니다.

    반환 항목:
      - inspection_date : 검사 날짜
      - total_count     : 총 검사 건수
      - anomaly_count   : 결함 판정 건수
      - avg_score       : 평균 이상 점수
    """
    if not state.starrocks:
        raise HTTPException(status_code=503, detail="StarRocks에 연결되어 있지 않습니다.")
    try:
        rows = state.starrocks.query_anomaly_stats()
        # 각 row 를 dict 로 변환해 반환 (날짜, 건수, 평균 점수 등)
        return StatsResponse(rows=[dict(r) for r in rows])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {e}") from e
