"""
학습(Train) 관련 API 라우터.

이 모듈에 정의된 엔드포인트:
  POST /train  — data/train/good/ 의 정상 이미지로 PaDiM 모델 학습
  GET  /model  — 현재 서버에 로드된 모델의 메타정보 조회
"""

from __future__ import annotations

import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import TrainRequest, TrainResponse
from api.state import AppState, get_state

# 이 라우터를 api/main.py 에서 app.include_router() 로 등록합니다.
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# POST /train
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/train", response_model=TrainResponse, summary="PaDiM 모델 학습")
async def train(
    state: Annotated[AppState, Depends(get_state)],
    request: TrainRequest = TrainRequest(),
) -> TrainResponse:
    """
    정상 이미지 폴더를 기반으로 PaDiM 이상 탐지 모델을 학습합니다.

    학습 흐름:
      1. 학습 데이터 경로 확인 (data/train/good/ 가 비어있으면 오류)
      2. anomalib Folder 데이터모듈 구성
      3. PaDiM 모델 생성 (ResNet18 백본, pre-trained ImageNet 가중치 사용)
      4. Engine.fit() 으로 특징 추출 → 가우시안 분포 피팅
      5. 체크포인트(.ckpt) 로컬 저장
      6. MinIO 업로드 (no_upload=False 일 때)
      7. 학습된 모델을 메모리에 즉시 로드 → 추론 가능 상태

    학습 중 오류가 발생하면 status='error' 와 오류 메시지를 반환합니다.
    학습이 성공하면 이후 즉시 /predict 를 호출할 수 있습니다.
    """
    # config 섹션 단축 참조
    cfg = state.config
    data_cfg = cfg["data"]
    model_cfg = cfg["model"]
    output_cfg = cfg["output"]

    # 학습 데이터 디렉터리 결정 (요청에 data_root 가 있으면 우선 사용)
    data_root = request.data_root or data_cfg["root"]
    train_dir = os.path.join(data_root, data_cfg["normal_dir"])  # 예: data/train/good

    # 학습 이미지가 없으면 즉시 400 오류 반환
    if not os.path.isdir(train_dir) or not os.listdir(train_dir):
        raise HTTPException(
            status_code=400,
            detail=(
                f"학습용 이미지 없음: {train_dir}. "
                "먼저 scripts/generate_normal_images.py 를 실행하세요."
            ),
        )

    # 체크포인트 저장 디렉터리 생성
    weights_dir = output_cfg["weights_dir"]
    os.makedirs(weights_dir, exist_ok=True)

    t0 = time.time()               # 학습 시작 시각 기록
    ckpt_path: str | None = None   # 저장된 체크포인트 경로
    minio_uri: str | None = None   # MinIO 업로드 결과 URI

    try:
        from anomalib.data import Folder
        from anomalib.engine import Engine
        from anomalib.models import Padim

        # ── 데이터모듈 구성 ────────────────────────────────────────────────────
        # anomalib Folder 데이터모듈은 폴더 구조(train/good, test/good, test/defect)를
        # 자동으로 인식해 학습/검증 데이터셋을 만들어 줍니다.
        datamodule = Folder(
            name="semiconductor",
            root=os.path.abspath(data_root),
            normal_dir=data_cfg["normal_dir"],                             # train/good
            abnormal_dir=data_cfg.get("abnormal_dir", "test/defect"),      # test/defect
            normal_test_dir=data_cfg.get("test_normal_dir", "test/good"), # test/good
            image_size=(data_cfg["image_size"], data_cfg["image_size"]),   # 예: (256, 256)
            train_batch_size=32,
            eval_batch_size=32,
            num_workers=0,          # 멀티프로세스 로딩 비활성화 (MacBook 호환)
            task="classification",  # 픽셀 레벨 마스크 없이 이미지 분류 모드
        )

        # ── PaDiM 모델 생성 ────────────────────────────────────────────────────
        # pre_trained=True : ImageNet 으로 사전 학습된 ResNet18 가중치 사용
        # n_features       : 각 공간 위치에서 유지할 특징 차원 수 (무작위 차원 선택)
        model = Padim(
            backbone=model_cfg["backbone"],       # 예: "resnet18"
            layers=model_cfg["layers"],           # 예: ["layer1", "layer2", "layer3"]
            pre_trained=True,
            n_features=model_cfg.get("n_features", 100),
        )

        # ── 학습 엔진 구성 ─────────────────────────────────────────────────────
        # PaDiM 은 실제 역전파(backprop) 없이 특징 통계를 피팅하므로 1 epoch 만 실행합니다.
        engine = Engine(
            accelerator=model_cfg["accelerator"],  # "cpu" 또는 "gpu"
            devices=1,
            default_root_dir=weights_dir,           # 체크포인트 저장 위치
        )

        # 학습 실행 (특징 추출 → 가우시안 평균/공분산 피팅 → 임계값 최적화)
        engine.fit(model=model, datamodule=datamodule)

        # ── 최신 체크포인트 파일 탐색 ──────────────────────────────────────────
        for root_d, _, files in os.walk(weights_dir):
            for f in files:
                if f.endswith(".ckpt"):
                    candidate = os.path.join(root_d, f)
                    # 더 최근에 만들어진 파일로 교체
                    if ckpt_path is None or os.path.getmtime(candidate) > os.path.getmtime(ckpt_path):
                        ckpt_path = candidate

        # ── MinIO 업로드 ───────────────────────────────────────────────────────
        # no_upload=False 이고 체크포인트가 있으면 MinIO 에 올립니다.
        if not request.no_upload and ckpt_path and state.storage:
            obj_name = f"weights/{os.path.basename(ckpt_path)}"
            minio_uri = state.storage.upload_file(ckpt_path, obj_name)

        # ── 학습된 모델을 메모리에 즉시 로드 ─────────────────────────────────
        # 이후 /predict 호출 시 재시작 없이 바로 추론 가능합니다.
        state.load_model(ckpt_path)

    except Exception as e:
        # 학습 중 예외 발생 — 오류 상태로 응답 반환
        elapsed = time.time() - t0
        return TrainResponse(
            status="error",
            checkpoint_path=ckpt_path,
            minio_uri=minio_uri,
            duration_seconds=round(elapsed, 2),
            message=str(e),
        )

    elapsed = time.time() - t0
    return TrainResponse(
        status="success",
        checkpoint_path=ckpt_path,
        minio_uri=minio_uri,
        duration_seconds=round(elapsed, 2),
        message="학습 완료. 모델이 메모리에 로드되었습니다.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /model
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/model", summary="현재 모델 정보 조회")
async def model_info(state: Annotated[AppState, Depends(get_state)]) -> dict:
    """
    현재 서버에 로드된 모델의 메타정보를 반환합니다.

    반환 항목:
      - model_loaded  : 모델이 메모리에 올라왔는지 여부
      - model_version : 로드된 체크포인트 파일명
      - backbone      : 특징 추출에 사용하는 CNN 백본 (예: resnet18)
      - n_features    : PaDiM 특징 차원 수
      - threshold     : 결함 판정 임계값
    """
    return {
        "model_loaded": state.model_loaded,
        "model_version": state.model_version,
        "backbone": state.config["model"]["backbone"],
        "n_features": state.config["model"].get("n_features", 100),
        "threshold": state.config["inference"]["threshold"],
    }
