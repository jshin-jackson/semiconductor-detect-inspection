"""
애플리케이션 전역 상태 관리 모듈.

FastAPI 서버가 시작될 때 한 번만 생성되는 싱글턴 AppState 를 정의합니다.
모든 API 라우터는 Depends(get_state) 를 통해 동일한 AppState 인스턴스를 주입받습니다.

포함 내용:
  - PyTorch 2.6 호환성 패치 (weights_only=True 기본값 변경 대응)
  - matplotlib 3.8 호환성 패치 (tostring_rgb 제거 대응)
  - AppState 클래스: 모델·MinIO·Iceberg·StarRocks 클라이언트 관리
"""

from __future__ import annotations

import inspect
import os
from typing import Any

import numpy as np

from src.utils import load_config


# ──────────────────────────────────────────────────────────────────────────────
# 호환성 패치 함수들
# PyTorch / matplotlib 의 버전별 API 변경에 대응하는 일회성 패치입니다.
# 모듈 임포트 시 자동으로 실행되며, 서드파티 라이브러리를 직접 수정하지 않습니다.
# ──────────────────────────────────────────────────────────────────────────────

def _register_torchvision_safe_globals() -> None:
    """
    PyTorch 2.6+ 의 체크포인트 로딩 보안 강화에 대응합니다.

    PyTorch 2.6 부터 torch.load() 의 weights_only 기본값이 True 로 바뀌었습니다.
    이 모드에서는 "안전한 클래스 목록(safe globals)"에 없는 클래스를
    체크포인트에서 역직렬화할 수 없습니다.

    anomalib 체크포인트에는 torchvision.transforms.v2 의 다양한 변환 클래스가
    저장되어 있으므로, 이 클래스들을 safe globals 에 미리 등록합니다.
    (로컬에서 직접 생성한 신뢰된 체크포인트 전용)
    """
    try:
        import torch
        import torchvision.transforms.v2 as _T2

        safe_classes: list = []

        # torchvision.transforms.v2 공개 API 의 모든 클래스 수집
        for _, obj in inspect.getmembers(_T2, inspect.isclass):
            safe_classes.append(obj)

        # 내부 서브모듈까지 포함해 빠짐없이 등록
        for _sub in ["_container", "_geometry", "_color", "_misc",
                     "_type_conversion", "_auto_augment", "_meta"]:
            try:
                import importlib
                _m = importlib.import_module(f"torchvision.transforms.v2.{_sub}")
                for _, obj in inspect.getmembers(_m, inspect.isclass):
                    if obj not in safe_classes:
                        safe_classes.append(obj)
            except Exception:
                pass  # 해당 서브모듈이 없는 버전은 건너뜀

        if safe_classes:
            torch.serialization.add_safe_globals(safe_classes)
    except Exception:
        pass  # torch/torchvision 미설치 환경에서는 무시


def _patch_matplotlib_compat() -> None:
    """
    matplotlib 3.8+ 에서 제거된 tostring_rgb() 메서드를 복원합니다.

    anomalib 내부 시각화 코드가 FigureCanvasAgg.tostring_rgb() 를 호출하는데,
    matplotlib 3.8 에서 이 메서드가 삭제됐습니다.
    buffer_rgba() 로 RGBA 버퍼를 읽은 뒤 알파 채널을 제거해 동일한 결과를 반환합니다.
    """
    try:
        import numpy as _np
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        if not hasattr(FigureCanvasAgg, "tostring_rgb"):
            def _tostring_rgb(self: FigureCanvasAgg) -> bytes:
                # RGBA 버퍼를 numpy 배열로 읽어 R·G·B 채널만 추출
                buf = self.buffer_rgba()
                w, h = self.get_width_height()
                arr = _np.frombuffer(buf, dtype=_np.uint8).reshape(h, w, 4)
                return arr[:, :, :3].tobytes()  # 알파(4번째 채널) 제거

            FigureCanvasAgg.tostring_rgb = _tostring_rgb  # type: ignore[attr-defined]
    except Exception:
        pass  # matplotlib 미설치 환경에서는 무시


# 모듈이 처음 임포트될 때 즉시 패치 적용 (API 서버 시작 시 1회 실행)
_register_torchvision_safe_globals()
_patch_matplotlib_compat()


# ──────────────────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────────────────────────────────────

def _find_latest_checkpoint(weights_dir: str) -> str | None:
    """
    weights_dir 아래의 모든 .ckpt 파일 중 가장 최근에 수정된 파일을 반환합니다.
    체크포인트가 없으면 None 을 반환합니다.
    """
    ckpts = []
    if not os.path.isdir(weights_dir):
        return None
    # 하위 디렉터리까지 재귀 탐색
    for root, _, files in os.walk(weights_dir):
        for f in files:
            if f.endswith(".ckpt"):
                ckpts.append(os.path.join(root, f))
    # 수정 시간이 가장 최신인 파일 반환
    return max(ckpts, key=os.path.getmtime) if ckpts else None


# ──────────────────────────────────────────────────────────────────────────────
# 전역 상태 클래스
# ──────────────────────────────────────────────────────────────────────────────

class AppState:
    """
    서버 전체에서 공유되는 싱글턴 상태 객체.

    - config      : config.yaml 내용
    - model       : anomalib PaDiM LightningModule 인스턴스
    - storage     : MinIO 클라이언트
    - iceberg_writer: Iceberg 테이블 쓰기 클라이언트
    - starrocks   : StarRocks SQL 쿼리 클라이언트
    """

    def __init__(self) -> None:
        # 아직 초기화되지 않은 상태 — initialize() 호출 전까지 None
        self.config: dict[str, Any] = {}
        self.engine = None           # anomalib Engine (학습용, 현재 미사용)
        self.model = None            # anomalib PaDiM LightningModule
        self.model_loaded: bool = False   # 모델이 메모리에 올라왔는지 여부
        self.model_version: str | None = None  # 로드된 체크포인트 파일명
        self._ckpt_path: str | None = None     # 체크포인트 전체 경로
        self.storage = None          # StorageClient (MinIO)
        self.iceberg_writer = None   # IcebergWriter (Iceberg 테이블 쓰기)
        self.starrocks = None        # StarRocksClient (SQL 조회)

    def initialize(self, config_path: str) -> None:
        """
        설정 파일을 읽고 외부 서비스 클라이언트를 초기화합니다.
        서버 시작 시 lifespan 핸들러에서 단 한 번 호출됩니다.

        초기화 순서:
          1. config.yaml 로드
          2. MinIO 클라이언트 생성
          3. Iceberg 클라이언트 생성
          4. StarRocks 클라이언트 생성
          5. 기존 체크포인트 자동 로드 (있으면)
        """
        self.config = load_config(config_path)

        # ── 1. MinIO 클라이언트 초기화 ─────────────────────────────────────────
        # 히트맵 PNG·모델 가중치를 MinIO 오브젝트 스토리지에 저장합니다.
        try:
            from src.storage import StorageClient

            self.storage = StorageClient(self.config["minio"])
            print("[AppState] MinIO 연결 성공.")
        except Exception as e:
            print(f"[AppState] MinIO 연결 실패 (기능 제한됨): {e}")

        # ── 2. Iceberg 클라이언트 초기화 ──────────────────────────────────────
        # 추론 결과를 Apache Iceberg 테이블에 Parquet 형식으로 기록합니다.
        # MinIO 설정도 함께 전달해 S3 접근 자격증명을 제공합니다.
        try:
            from src.iceberg_writer import IcebergWriter

            self.iceberg_writer = IcebergWriter(
                self.config["iceberg"],
                minio_config=self.config.get("minio"),  # S3 엔드포인트 및 자격증명
            )
            print("[AppState] Iceberg 클라이언트 초기화 성공.")
        except Exception as e:
            print(f"[AppState] Iceberg 초기화 실패 (기능 제한됨): {e}")

        # ── 3. StarRocks 클라이언트 초기화 ────────────────────────────────────
        # Iceberg External Catalog 를 통해 검사 이력·통계를 SQL 로 조회합니다.
        try:
            from src.database import StarRocksClient

            self.starrocks = StarRocksClient(self.config["starrocks"])
            if self.starrocks.ping():
                print("[AppState] StarRocks 연결 성공.")
            else:
                print("[AppState] StarRocks 연결 실패 (기능 제한됨).")
        except Exception as e:
            print(f"[AppState] StarRocks 초기화 실패 (기능 제한됨): {e}")

        # ── 4. 저장된 체크포인트 자동 로드 ────────────────────────────────────
        # weights/ 디렉터리에 이미 학습된 체크포인트가 있으면 즉시 로드합니다.
        ckpt = _find_latest_checkpoint(self.config["output"]["weights_dir"])
        if ckpt:
            print(f"[AppState] 체크포인트 발견, 모델 로드 중: {ckpt}")
            self.load_model(ckpt)
        else:
            print("[AppState] 저장된 체크포인트 없음. POST /train 으로 학습 후 사용하세요.")

    def load_model(self, ckpt_path: str | None) -> None:
        """
        PaDiM 모델을 체크포인트 파일에서 로드합니다.

        PyTorch Lightning 이 저장한 체크포인트에는 'state_dict' 키 아래에
        'model.*' 접두사가 붙은 가중치가 들어 있습니다.
        접두사를 제거한 뒤 PadimModel(nn.Module) 에 직접 로드합니다.

        또한 체크포인트에 저장된 image_threshold.value 를 읽어
        이상 점수 정규화의 기준점으로 사용합니다.

        Args:
            ckpt_path: 로드할 .ckpt 파일의 전체 경로. None 이면 아무 작업도 하지 않습니다.
        """
        if not ckpt_path or not os.path.isfile(ckpt_path):
            print(f"[AppState] 체크포인트 없음: {ckpt_path}")
            return

        try:
            import torch
            from anomalib.models import Padim

            model_cfg = self.config["model"]
            img_size = self.config["data"]["image_size"]

            # PaDiM LightningModule 인스턴스 생성 (가중치는 아직 없음)
            self.model = Padim(
                backbone=model_cfg["backbone"],       # 특징 추출 백본 (예: resnet18)
                layers=model_cfg["layers"],           # 사용할 레이어 목록
                pre_trained=False,                    # 가중치는 체크포인트에서 직접 로드
                n_features=model_cfg.get("n_features", 100),  # PaDiM 특징 차원
            )

            # PyTorch 2.6 호환: weights_only=False 로 체크포인트 역직렬화
            # (앞서 safe_globals 패치가 적용됐지만 추가 보험으로 False 사용)
            ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
            state_dict = ckpt.get("state_dict", ckpt)

            # Lightning 저장 형식에서 'model.' 접두사 제거
            # 예: 'model.gaussian.mean' → 'gaussian.mean'
            clean_state_dict = {}
            for k, v in state_dict.items():
                new_key = k[len("model."):] if k.startswith("model.") else k
                clean_state_dict[new_key] = v

            # PadimModel(nn.Module) 에 가중치 로드
            # strict=False: 체크포인트에 없는 키는 무시 (일부 메타 키 허용)
            self.model.model.load_state_dict(clean_state_dict, strict=False)
            self.model.model.eval()  # 드롭아웃·배치 정규화 추론 모드 전환

            # 체크포인트에 저장된 최적 임계값 (Mahalanobis distance 단위)
            # 학습 중 F1-score 를 최대화하는 임계값으로 자동 결정됩니다.
            raw_thresh = state_dict.get("image_threshold.value")
            self._raw_threshold = float(raw_thresh.item()) if raw_thresh is not None else 125.0

            self._img_size = img_size
            self._ckpt_path = ckpt_path
            self.model_loaded = True
            self.model_version = os.path.basename(ckpt_path)
            print(f"[AppState] 모델 로드 완료: {ckpt_path}  (임계값={self._raw_threshold:.2f})")

        except Exception as e:
            print(f"[AppState] 모델 로드 실패: {e}")
            self.model_loaded = False

    def run_inference(self, img_array: np.ndarray) -> tuple[float, np.ndarray]:
        """
        단일 이미지에 대해 PaDiM 이상 탐지 추론을 수행합니다.

        처리 흐름:
          1. 이미지를 학습 시와 동일한 전처리(리사이즈 → 정규화)로 변환
          2. PadimModel.forward() 로 Mahalanobis 거리 맵(anomaly_map) 계산
          3. 거리 맵의 최대값을 임계값으로 나눠 0~1 사이 anomaly_score 산출
          4. 히트맵 시각화용으로 anomaly_map 을 per-image min-max 정규화

        anomaly_score 정규화 방식:
          score = min(1.0, raw_max / (2 × threshold))
          → threshold 지점이 0.5 이 되므로 config 의 threshold=0.5 와 자연스럽게 대응
          → 정상 이미지: ~0.05~0.15, 결함 이미지: ~0.5~1.0

        Args:
            img_array: (H, W, 3) uint8 RGB numpy 배열

        Returns:
            (anomaly_score, anomaly_map) 튜플
              - anomaly_score: 0~1 사이 이상 점수
              - anomaly_map: (H, W) float32, 히트맵용 0~1 정규화된 이상 맵
        """
        if not self.model_loaded:
            raise RuntimeError("모델이 로드되지 않았습니다.")

        import torch
        import torchvision.transforms.v2 as T
        from PIL import Image as PILImage

        img_size = self._img_size  # 모델 학습 시 사용한 이미지 크기

        # 학습 시와 동일한 전처리 파이프라인 구성
        # ImageNet 평균/표준편차로 정규화 (ResNet 백본 기본값)
        transform = T.Compose([
            T.Resize((img_size, img_size)),  # 모델 입력 크기로 리사이즈
            T.ToImage(),                     # PIL Image → torch.Tensor (uint8)
            T.ToDtype(torch.float32, scale=True),  # 0~255 → 0.0~1.0 실수 변환
            T.Normalize(mean=[0.485, 0.456, 0.406],  # ImageNet 평균
                        std=[0.229, 0.224, 0.225]),   # ImageNet 표준편차
        ])

        # numpy 배열 → PIL Image → 전처리 → 배치 차원 추가
        pil_img = PILImage.fromarray(img_array).convert("RGB")
        tensor = transform(pil_img).unsqueeze(0)  # (C, H, W) → (1, C, H, W)

        # 그래디언트 계산 없이 추론 (메모리 절약, 속도 향상)
        with torch.no_grad():
            output = self.model.model(tensor)

        # anomaly_map 추출 — PadimModel 은 (1, 1, H, W) 텐서를 직접 반환
        if isinstance(output, torch.Tensor):
            # 가장 일반적인 경우: raw Mahalanobis distance 텐서
            amap = output.squeeze().cpu().numpy().astype(np.float32)
        elif hasattr(output, "anomaly_map") and output.anomaly_map is not None:
            # Batch 객체를 반환하는 anomalib 버전
            amap = output.anomaly_map.squeeze().cpu().numpy().astype(np.float32)
        elif isinstance(output, dict) and "anomaly_map" in output:
            # dict 형태로 반환하는 경우
            amap = output["anomaly_map"].squeeze().cpu().numpy().astype(np.float32)
        else:
            # 예상치 못한 출력 형식 — 0 맵으로 대체
            amap = np.zeros((img_size, img_size), dtype=np.float32)

        # ── 이상 점수 계산 ─────────────────────────────────────────────────────
        # raw 최대값을 임계값의 2배로 나눠 [0, 1] 범위로 압축합니다.
        # 이렇게 하면 임계값(threshold) 지점이 정확히 0.5 가 됩니다.
        raw_threshold = getattr(self, "_raw_threshold", 125.0)
        score = min(1.0, float(amap.max()) / (2.0 * raw_threshold))

        # ── anomaly_map 시각화용 정규화 ────────────────────────────────────────
        # 히트맵을 그릴 때 각 이미지 내에서 최솟값~최댓값을 0~1 로 늘립니다.
        # (score 계산과는 독립적 — 표시 목적으로만 사용)
        amap_min, amap_max = float(amap.min()), float(amap.max())
        if amap_max > amap_min:
            amap = (amap - amap_min) / (amap_max - amap_min)

        return score, amap


# ──────────────────────────────────────────────────────────────────────────────
# 싱글턴 관리
# ──────────────────────────────────────────────────────────────────────────────

# 서버 전체에서 하나만 존재하는 AppState 인스턴스
_app_state = AppState()


def get_state() -> AppState:
    """
    FastAPI Depends() 주입용 함수.
    항상 동일한 싱글턴 _app_state 를 반환합니다.
    """
    return _app_state
