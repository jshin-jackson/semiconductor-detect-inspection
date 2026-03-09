"""
공통 유틸리티 함수 모듈.

API 서버 전반에서 사용되는 헬퍼 함수들을 모아놓습니다:
  - 히트맵 PNG 생성
  - 추론 결과 JSON 파일 저장
  - YAML 설정 파일 로드
  - 현재 시각 ISO 8601 문자열 반환
  - 이미지 bytes → numpy 배열 변환
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def generate_heatmap_bytes(
    original_image: np.ndarray,
    anomaly_map: np.ndarray,
    score: float,
    is_anomaly: bool,
    alpha: float = 0.5,
) -> bytes:
    """
    원본 이미지 + 이상 점수 맵 + 오버레이 3종 히트맵을 PNG bytes 로 생성합니다.

    matplotlib 로 (1×3) 격자 그림을 그린 뒤 메모리 버퍼에 PNG 로 저장합니다.
    생성된 bytes 는 MinIO 업로드와 로컬 저장에 모두 사용됩니다.

    구성:
      [왼쪽] 원본 이미지
      [중간] 이상 점수 맵 (jet 컬러맵, 0~1 스케일)
      [오른쪽] 원본 위에 이상 맵을 반투명하게 오버레이 + 판정 결과 표시

    Args:
        original_image : (H, W, 3) uint8 RGB numpy 배열
        anomaly_map    : (H, W) float32 이상 점수 맵 (0~1 범위로 정규화됨)
        score          : 전체 이상 점수 (0~1 실수)
        is_anomaly     : 결함 판정 결과 (True=결함, False=정상)
        alpha          : 오버레이 시 히트맵 불투명도 (0=완전 투명, 1=완전 불투명)

    Returns:
        PNG 형식으로 인코딩된 bytes
    """
    h, w = original_image.shape[:2]

    # anomaly_map 크기가 원본과 다르면 원본 크기로 리사이즈
    # (모델 출력 해상도가 입력보다 작은 경우)
    if anomaly_map.shape != (h, w):
        pil_map = Image.fromarray((anomaly_map * 255).astype(np.uint8)).resize(
            (w, h), Image.Resampling.BILINEAR
        )
        anomaly_map_resized = np.array(pil_map).astype(np.float32) / 255.0
    else:
        anomaly_map_resized = anomaly_map

    # 3칸 가로 레이아웃 생성
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    # ── 왼쪽: 원본 이미지 ──────────────────────────────────────────────────────
    axes[0].imshow(original_image)
    axes[0].set_title("원본 이미지")
    axes[0].axis("off")  # 축 눈금 숨기기

    # ── 중간: 이상 점수 맵 ─────────────────────────────────────────────────────
    # jet 컬러맵: 낮은 점수(정상)는 파란색, 높은 점수(이상)는 빨간색
    im = axes[1].imshow(anomaly_map_resized, cmap="jet", vmin=0, vmax=1)
    axes[1].set_title("이상 점수 맵")
    axes[1].axis("off")
    plt.colorbar(im, ax=axes[1], fraction=0.046, pad=0.04)  # 색상 범례 추가

    # ── 오른쪽: 오버레이 + 판정 결과 ──────────────────────────────────────────
    axes[2].imshow(original_image)
    axes[2].imshow(anomaly_map_resized, cmap="jet", alpha=alpha, vmin=0, vmax=1)

    # 결함 여부에 따라 제목 색상 결정 (결함: 빨간색, 정상: 초록색)
    label = "이상(Anomaly)" if is_anomaly else "정상(Normal)"
    color = "red" if is_anomaly else "green"
    axes[2].set_title(f"오버레이 — {label}\n점수: {score:.4f}", color=color)
    axes[2].axis("off")

    # 여백 자동 조정 후 PNG bytes 로 직렬화
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)  # 메모리 해제 (matplotlib 백엔드가 그림을 캐시하므로 명시 필요)
    buf.seek(0)
    return buf.read()


def save_result_json(
    result: dict[str, Any],
    output_dir: str,
    filename: str,
) -> str:
    """
    추론 결과 딕셔너리를 JSON 파일로 로컬에 저장합니다.

    결과 파일은 data/results/{uuid}_result.json 형태로 저장됩니다.
    datetime 등 JSON 직렬화 불가 타입은 str() 로 자동 변환합니다.

    Args:
        result    : 저장할 결과 딕셔너리 (id, filename, score, is_anomaly 등)
        output_dir: 저장할 디렉터리 경로 (없으면 자동 생성)
        filename  : JSON 파일명 (예: "abc123_result.json")

    Returns:
        저장된 파일의 절대 경로
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,  # 한글 등 유니코드 그대로 출력
            indent=2,            # 사람이 읽기 좋게 들여쓰기
            default=str,         # datetime 등 직렬화 불가 타입은 str 로 변환
        )
    return os.path.abspath(path)


def load_config(config_path: str) -> dict[str, Any]:
    """
    YAML 형식의 설정 파일을 로드해 딕셔너리로 반환합니다.

    configs/config.yaml 에서 모델·데이터·MinIO·Iceberg·StarRocks
    설정값을 읽어옵니다.

    Args:
        config_path: 설정 파일 경로 (예: configs/config.yaml)

    Returns:
        YAML 내용을 파싱한 중첩 딕셔너리
    """
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_iso() -> str:
    """
    현재 UTC 시각을 ISO 8601 형식 문자열로 반환합니다.

    예시: "2025-03-09T12:34:56Z"

    Iceberg 타임스탬프 컬럼과 결과 JSON 의 timestamp 필드에 사용합니다.
    """
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def image_to_array(image_bytes: bytes) -> np.ndarray:
    """
    이미지 bytes 데이터를 (H, W, 3) uint8 RGB numpy 배열로 변환합니다.

    FastAPI 가 파일 업로드로 받은 raw bytes 를 모델 추론에 사용할 수 있도록
    PIL → numpy 변환을 수행합니다.
    RGBA 이미지나 그레이스케일 이미지도 RGB 3채널로 자동 변환됩니다.

    Args:
        image_bytes: PNG / JPEG / BMP 등 이미지 파일의 원시 bytes

    Returns:
        (H, W, 3) uint8 numpy 배열 (RGB 채널 순서)

    Raises:
        UnidentifiedImageError: 이미지 형식을 인식할 수 없는 경우
    """
    buf = io.BytesIO(image_bytes)  # bytes → 파일 유사 객체
    return np.array(Image.open(buf).convert("RGB"))
