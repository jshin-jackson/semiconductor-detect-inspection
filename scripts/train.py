"""
PaDiM 이상 탐지 모델 학습 스크립트.

anomalib 의 Folder 데이터모듈과 Engine 을 사용해
data/train/good/ 의 정상 이미지만으로 PaDiM 모델을 학습합니다.

PaDiM 학습 원리:
  1. 사전 학습된 ResNet18 으로 각 정상 이미지의 특징 벡터를 추출합니다.
  2. 각 공간 위치(patch)에서 특징 벡터의 가우시안 분포(평균, 공분산)를 추정합니다.
  3. 추론 시 새 이미지의 특징이 이 분포에서 얼마나 벗어났는지
     Mahalanobis 거리로 계산해 이상 점수로 사용합니다.
  4. 실제 역전파(backprop) 없이 통계만 피팅하므로 학습이 매우 빠릅니다.

학습 완료 후:
  - 체크포인트를 weights/ 에 저장
  - MinIO 에도 업로드 (--no-upload 미지정 시)

사용 예:
  python scripts/train.py
  python scripts/train.py --config configs/config.yaml --no-upload
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# 프로젝트 루트를 sys.path 에 추가 (src, configs 모듈 임포트용)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def find_checkpoint(weights_dir: str) -> str | None:
    """
    weights_dir 아래에서 가장 최근에 저장된 .ckpt 파일을 찾아 반환합니다.

    anomalib Engine 은 체크포인트를 하위 디렉터리에 저장하므로
    os.walk 로 재귀 탐색합니다.

    Args:
        weights_dir: 체크포인트 루트 디렉터리

    Returns:
        가장 최근 .ckpt 파일의 전체 경로. 없으면 None.
    """
    ckpts = []
    for root, _, files in os.walk(weights_dir):
        for f in files:
            if f.endswith(".ckpt"):
                ckpts.append(os.path.join(root, f))
    return max(ckpts, key=os.path.getmtime) if ckpts else None


def main() -> None:
    """학습 메인 함수 — argparse 로 설정 파일 경로와 옵션을 받습니다."""
    parser = argparse.ArgumentParser(description="PaDiM 모델 학습")
    parser.add_argument(
        "--config",
        type=str,
        default=os.path.join(ROOT, "configs", "config.yaml"),
        help="설정 파일 경로 (기본: configs/config.yaml)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="이 플래그를 지정하면 학습 후 MinIO 업로드를 건너뜁니다.",
    )
    args = parser.parse_args()

    from src.utils import load_config  # noqa: E402

    # 설정 파일 로드
    cfg = load_config(args.config)

    # 자주 참조할 설정 섹션 단축 참조
    data_cfg = cfg["data"]
    model_cfg = cfg["model"]
    output_cfg = cfg["output"]

    train_dir = os.path.join(data_cfg["root"], data_cfg["normal_dir"])
    weights_dir = output_cfg["weights_dir"]

    # ── 사전 조건 확인 ─────────────────────────────────────────────────────────
    # 학습 이미지 없이 실행하면 의미 없으므로 바로 오류 처리
    if not os.path.isdir(train_dir) or not os.listdir(train_dir):
        print(f"[오류] 학습용 이미지 없음: {train_dir}")
        print("먼저 python scripts/generate_normal_images.py 를 실행하세요.")
        sys.exit(1)

    print(f"학습 시작: {train_dir}")
    print(f"모델: PaDiM / 백본: {model_cfg['backbone']} / n_features: {model_cfg['n_features']}")
    print(f"accelerator: {model_cfg['accelerator']}")

    from anomalib.data import Folder    # noqa: E402
    from anomalib.engine import Engine  # noqa: E402
    from anomalib.models import Padim   # noqa: E402

    # ── 데이터모듈 구성 ────────────────────────────────────────────────────────
    # anomalib Folder 데이터모듈이 다음 디렉터리 구조를 자동 인식합니다:
    #   data/
    #     train/good/      ← 학습용 정상 이미지
    #     test/good/       ← 평가용 정상 이미지
    #     test/defect/     ← 평가용 결함 이미지
    datamodule = Folder(
        name="semiconductor",
        root=os.path.abspath(data_cfg["root"]),
        normal_dir=data_cfg["normal_dir"],                            # "train/good"
        abnormal_dir=data_cfg.get("abnormal_dir", "test/defect"),     # "test/defect"
        normal_test_dir=data_cfg.get("test_normal_dir", "test/good"), # "test/good"
        image_size=(data_cfg["image_size"], data_cfg["image_size"]),  # 예: (256, 256)
        train_batch_size=32,
        eval_batch_size=32,
        num_workers=0,          # MacBook M2 에서 멀티프로세스 워커 비활성화
        task="classification",  # 픽셀 마스크 없이 이미지 수준 분류
    )

    # ── PaDiM 모델 생성 ────────────────────────────────────────────────────────
    # pre_trained=True: ImageNet 으로 학습된 ResNet18 을 특징 추출기로 사용
    # n_features: 각 공간 위치에서 무작위로 선택할 특징 차원 수
    #             작을수록 빠르고 메모리 효율적이지만 정확도가 약간 낮아질 수 있음
    model = Padim(
        backbone=model_cfg["backbone"],       # "resnet18"
        layers=model_cfg["layers"],           # ["layer1", "layer2", "layer3"]
        pre_trained=True,
        n_features=model_cfg.get("n_features", 100),
    )

    os.makedirs(weights_dir, exist_ok=True)

    # ── 학습 엔진 생성 ─────────────────────────────────────────────────────────
    # PaDiM 은 gradient 학습이 없으므로 1 epoch 에 해당하는 피팅만 수행
    engine = Engine(
        accelerator=model_cfg["accelerator"],  # "cpu" (M2 Mac 는 CPU 추론)
        devices=1,
        default_root_dir=weights_dir,           # 체크포인트 저장 경로
    )

    # ── 학습 실행 ──────────────────────────────────────────────────────────────
    t0 = time.time()
    engine.fit(model=model, datamodule=datamodule)  # 특징 통계 피팅 + 임계값 최적화
    elapsed = time.time() - t0

    print(f"학습 완료 ({elapsed:.1f}초)")

    # ── 체크포인트 경로 확인 ───────────────────────────────────────────────────
    ckpt_path = find_checkpoint(weights_dir)
    if ckpt_path:
        print(f"체크포인트 저장: {ckpt_path}")
    else:
        print("[경고] 체크포인트 파일을 찾을 수 없습니다.")

    # ── MinIO 업로드 ───────────────────────────────────────────────────────────
    # --no-upload 플래그가 없고 체크포인트가 있으면 MinIO 에 업로드합니다.
    # MinIO 업로드 실패 시에도 로컬 파일은 안전하게 유지됩니다.
    if not args.no_upload and ckpt_path:
        try:
            from src.storage import StorageClient  # noqa: E402

            storage = StorageClient(cfg["minio"])
            obj_name = f"weights/{os.path.basename(ckpt_path)}"
            minio_uri = storage.upload_file(ckpt_path, obj_name)
            print(f"MinIO 업로드 완료: {minio_uri}")
        except Exception as e:
            print(f"[경고] MinIO 업로드 실패 (로컬 파일은 유지됨): {e}")


if __name__ == "__main__":
    main()
