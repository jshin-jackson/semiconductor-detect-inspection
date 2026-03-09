"""
반도체 웨이퍼를 모사한 정상(Normal) 이미지를 절차적으로 자동 생성합니다.

실제 반도체 촬영 이미지가 없어도 바로 학습 데이터를 구성할 수 있도록,
컴퓨터 그래픽스 기법으로 웨이퍼 표면처럼 보이는 이미지를 만듭니다.

생성 알고리즘 (4단계):
  1. 균일한 회색 베이스 (160~190 범위) — 실리콘 표면의 기본 밝기
  2. 저주파 노이즈 오버레이 — 웨이퍼 표면의 완만한 명암 굴곡 모사
  3. 주기적 격자(그리드) 오버레이 — 웨이퍼 위의 다이(die) 경계선 표현
  4. 가우시안 미세 노이즈 — 이미지 센서의 자연스러운 노이즈 추가

출력 디렉터리:
  data/train/good/   — PaDiM 학습용 정상 이미지 (기본 200장)
  data/test/good/    — 추론 성능 평가용 정상 이미지 (기본 30장)

사용 예:
  python scripts/generate_normal_images.py
  python scripts/generate_normal_images.py --train-count 300 --size 224
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import zoom

# 프로젝트 루트를 sys.path 에 추가 (src 모듈 임포트용)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _low_freq_noise(size: int, scale: int = 32) -> np.ndarray:
    """
    저주파 텍스처 노이즈를 생성합니다.

    작은 해상도의 균일 랜덤 노이즈를 scipy.ndimage.zoom 으로 업스케일해
    부드럽게 변화하는 저주파 패턴을 만듭니다.
    웨이퍼 표면의 완만한 곡률에 의한 명암 변화를 모사합니다.

    Args:
        size : 출력 이미지 한 변의 픽셀 크기 (정사각형)
        scale: 업스케일 배율 — 값이 클수록 더 완만하고 넓은 패턴 (기본: 32)

    Returns:
        (size, size) float32 배열, 값 범위 0.0~1.0
    """
    # 작은 해상도에서 균일 분포 랜덤 노이즈 생성 (예: 8×8)
    small = np.random.rand(size // scale, size // scale).astype(np.float32)

    # bilinear 보간으로 원본 크기까지 부드럽게 업스케일
    factor = size / small.shape[0]
    upscaled = zoom(small, factor, order=1)  # order=1: bilinear 보간

    # zoom 결과가 size 보다 클 수 있으므로 크롭
    return upscaled[:size, :size]


def generate_wafer_image(size: int = 256, rng: np.random.Generator | None = None) -> np.ndarray:
    """
    단일 정상 웨이퍼 이미지를 절차적으로 생성합니다.

    같은 시드를 주면 항상 동일한 이미지가 생성됩니다 (재현성).
    rng 를 None 으로 두면 매번 다른 이미지가 생성됩니다.

    Args:
        size: 출력 이미지 크기 (정사각형, 기본: 256)
        rng : numpy 난수 생성기 (재현성 제어용)

    Returns:
        (size, size, 3) uint8 RGB numpy 배열
    """
    if rng is None:
        rng = np.random.default_rng()

    # ── 1단계: 실리콘 표면 기본 밝기 ──────────────────────────────────────────
    # 실제 반도체 웨이퍼 표면은 회색 계열이며 이미지마다 약간의 밝기 차이 존재
    base_gray = rng.integers(160, 190)  # 160~189 범위의 임의 회색 값
    canvas = np.full((size, size), base_gray, dtype=np.float32)

    # ── 2단계: 저주파 명암 변화 ───────────────────────────────────────────────
    # 웨이퍼가 구면(spherical) 형태이므로 조명에 의해 완만한 밝기 그라디언트 발생
    lf = _low_freq_noise(size, scale=16)
    canvas += (lf - 0.5) * 30.0  # ±15 범위의 완만한 명암 변화

    # ── 3단계: 다이 그리드 오버레이 ──────────────────────────────────────────
    # 웨이퍼를 격자 형태로 분할한 다이(chip) 경계선을 표현
    # 실제 사진에서도 회로 패턴의 주기적인 경계가 보임
    grid_spacing = size // 8      # 이미지를 8등분하는 간격
    grid_intensity = -20.0        # 경계선은 배경보다 20 어둡게
    for i in range(0, size, grid_spacing):
        canvas[i: i + 1, :] += grid_intensity   # 가로 경계선
        canvas[:, i: i + 1] += grid_intensity   # 세로 경계선

    # ── 4단계: 가우시안 미세 노이즈 ──────────────────────────────────────────
    # 카메라 센서의 열 노이즈(thermal noise) 및 양자화 노이즈 모사
    noise = rng.normal(0, 4, (size, size)).astype(np.float32)  # 표준편차 4
    canvas += noise

    # ── 최종 변환: 클리핑 + uint8 + RGB 변환 ──────────────────────────────────
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)  # 0~255 범위로 제한

    # 그레이스케일(1채널) → RGB(3채널): 모든 채널에 동일 값 복사
    rgb = np.stack([canvas, canvas, canvas], axis=-1)
    return rgb


def generate_dataset(
    train_count: int,
    test_good_count: int,
    output_root: str,
    image_size: int = 256,
    seed: int = 42,
) -> None:
    """
    학습용·테스트용 정상 이미지 데이터셋을 생성합니다.

    생성된 이미지는 anomalib Folder 데이터모듈이 인식하는 디렉터리 구조로 저장됩니다:
      output_root/
        train/good/   → PaDiM 학습에 사용 (정상 이미지만 필요)
        test/good/    → 추론 정확도 평가용 정상 이미지

    Args:
        train_count     : 학습용 정상 이미지 생성 수
        test_good_count : 테스트용 정상 이미지 생성 수
        output_root     : data/ 디렉터리 루트 경로
        image_size      : 생성할 이미지 크기 (정사각형, 기본: 256)
        seed            : 재현성 난수 시드 (기본: 42)
    """
    rng = np.random.default_rng(seed)  # 동일 seed → 항상 같은 데이터셋

    # 생성할 (디렉터리, 이미지 수) 목록
    splits = [
        ("train/good", train_count),
        ("test/good", test_good_count),
    ]

    for split_dir, count in splits:
        out_dir = os.path.join(output_root, split_dir)
        os.makedirs(out_dir, exist_ok=True)

        for idx in range(count):
            img_array = generate_wafer_image(size=image_size, rng=rng)
            img = Image.fromarray(img_array, mode="RGB")

            # 파일명: normal_0000.png, normal_0001.png, ... (4자리 0-패딩)
            filename = f"normal_{idx:04d}.png"
            img.save(os.path.join(out_dir, filename))

        print(f"[완료] {split_dir}: {count}장 생성 → {out_dir}")


def main() -> None:
    """커맨드라인 인터페이스 — argparse 로 파라미터를 받아 generate_dataset 호출."""
    parser = argparse.ArgumentParser(description="정상 웨이퍼 이미지 자동 생성")
    parser.add_argument(
        "--train-count", type=int, default=200,
        help="학습용 이미지 수 (기본: 200)",
    )
    parser.add_argument(
        "--test-count", type=int, default=30,
        help="테스트용 정상 이미지 수 (기본: 30)",
    )
    parser.add_argument(
        "--size", type=int, default=256,
        help="이미지 한 변 크기 — 픽셀 (기본: 256)",
    )
    parser.add_argument(
        "--data-root", type=str, default=os.path.join(ROOT, "data"),
        help="data/ 디렉터리 루트 경로 (기본: 프로젝트 루트/data)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="재현성 난수 시드 (기본: 42)",
    )
    args = parser.parse_args()

    print(f"정상 이미지 생성 시작 (train={args.train_count}, test_good={args.test_count}, size={args.size})")
    generate_dataset(
        train_count=args.train_count,
        test_good_count=args.test_count,
        output_root=args.data_root,
        image_size=args.size,
        seed=args.seed,
    )
    print("정상 이미지 생성 완료.")


if __name__ == "__main__":
    main()
