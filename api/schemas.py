"""
FastAPI 요청(Request) / 응답(Response) 스키마 정의 모듈.

Pydantic v2 BaseModel 을 사용합니다.
각 스키마는 API 엔드포인트가 주고받는 JSON 의 구조와 타입을 명시합니다.
FastAPI 가 이 스키마를 바탕으로 자동 검증·직렬화·Swagger 문서를 생성합니다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# GET /health 응답 스키마
# ──────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """서버 건강 상태를 나타내는 응답 모델."""

    status: str = Field(
        ...,
        description="전체 상태 — 모델·MinIO 모두 정상이면 'ok', 아니면 'degraded'",
    )
    model_loaded: bool = Field(..., description="PaDiM 모델이 메모리에 로드됐는지 여부")
    minio_connected: bool = Field(..., description="MinIO 오브젝트 스토리지 연결 여부")
    starrocks_connected: bool = Field(..., description="StarRocks DB 연결 여부")
    version: str = Field(default="1.0.0", description="API 서버 버전")


# ──────────────────────────────────────────────────────────────────────────────
# POST /train 요청·응답 스키마
# ──────────────────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    """학습 요청 파라미터."""

    data_root: str | None = Field(
        None,
        description="학습 데이터 루트 경로. 미입력 시 config.yaml 의 data.root 를 사용합니다.",
    )
    no_upload: bool = Field(
        False,
        description="True 이면 학습 후 체크포인트를 MinIO 에 업로드하지 않습니다.",
    )


class TrainResponse(BaseModel):
    """학습 완료 후 반환되는 결과 모델."""

    status: str = Field(..., description="학습 결과 — 'success' 또는 'error'")
    checkpoint_path: str | None = Field(None, description="로컬에 저장된 .ckpt 파일 경로")
    minio_uri: str | None = Field(None, description="MinIO 에 업로드된 체크포인트 URI (s3://...)")
    duration_seconds: float = Field(..., description="학습에 걸린 시간(초)")
    message: str = Field("", description="오류 발생 시 오류 내용, 성공 시 완료 메시지")


# ──────────────────────────────────────────────────────────────────────────────
# POST /predict 응답 스키마
# ──────────────────────────────────────────────────────────────────────────────

class PredictResponse(BaseModel):
    """단일 이미지 추론 결과를 담는 응답 모델."""

    filename: str = Field(..., description="업로드된 이미지 파일명")
    anomaly_score: float = Field(
        ...,
        description=(
            "0~1 사이의 이상 점수. "
            "정상 이미지는 0.05~0.15, 결함 이미지는 0.5~1.0 범위를 가집니다."
        ),
    )
    is_anomaly: bool = Field(..., description="이상 판정 결과 — score >= threshold 이면 True")
    threshold: float = Field(..., description="판정에 사용된 임계값 (config.yaml 에서 설정)")
    heatmap_minio_path: str | None = Field(
        None,
        description="히트맵 PNG 가 저장된 MinIO 경로 (s3://warehouse/heatmaps/...)",
    )
    result_json_path: str | None = Field(
        None,
        description="추론 결과 JSON 이 저장된 로컬 파일 경로",
    )
    inference_id: str = Field(..., description="이번 추론을 식별하는 고유 UUID")
    message: str = Field("", description="추가 메시지 (오류 시 상세 내용)")


# ──────────────────────────────────────────────────────────────────────────────
# GET /history 응답 스키마
# ──────────────────────────────────────────────────────────────────────────────

class InspectionRecord(BaseModel):
    """
    Iceberg 테이블의 단일 검사 이력 레코드.

    StarRocks(pymysql) 로 조회할 때 timestamp 가 datetime 객체로 반환되므로
    arbitrary_types_allowed=True 설정과 Any 타입을 사용합니다.
    JSON 직렬화 시 str 으로 자동 변환됩니다.
    """

    model_config = {"arbitrary_types_allowed": True}  # datetime 등 임의 타입 허용

    id: str                         # 추론 고유 ID (UUID)
    filename: str                   # 검사한 이미지 파일명
    timestamp: Any                  # 검사 시각 (UTC ISO 8601 문자열 또는 datetime)
    anomaly_score: float            # 이상 점수 (0~1)
    is_anomaly: bool                # 이상 여부
    heatmap_minio_path: str | None  # 히트맵 MinIO 경로
    model_version: str | None       # 추론에 사용된 모델 버전 (체크포인트 파일명)


class HistoryResponse(BaseModel):
    """최근 검사 이력 목록을 반환하는 응답 모델."""

    total: int = Field(..., description="반환된 레코드의 총 개수")
    records: list[InspectionRecord] = Field(
        default_factory=list,
        description="최신순으로 정렬된 검사 이력 레코드 목록",
    )


# ──────────────────────────────────────────────────────────────────────────────
# GET /stats 응답 스키마
# ──────────────────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    """일별 이상 탐지 통계 응답 모델."""

    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "날짜별 집계 결과 목록. "
            "각 항목에는 inspection_date, total_count, anomaly_count, avg_score 가 포함됩니다."
        ),
    )
