"""
정상(test/good) 이미지에 합성 결함을 적용해 test/defect 디렉터리를 생성합니다.

PaDiM 모델 평가를 위해서는 결함 이미지가 필요합니다.
이 스크립트는 실제 결함 이미지 없이도 모델 평가가 가능하도록
정상 이미지를 변형해 3종의 합성 결함 이미지를 만들어 줍니다.

결함 종류 (균등하게 생성):
  scratch      — 얇은 선형 스크래치
  spot         — 밝거나 어두운 원형 점 결함
  contamination— 불규칙한 다각형 오염 영역

사용 예:
  python scripts/generate_defects.py                    # 기본값 사용
  python scripts/generate_defects.py --count 50 --seed 99  # 50장, 시드 99
"""

import argparse
import os
import sys

import numpy as np

# 프로젝트 루트를 sys.path 에 추가 (src 모듈 임포트용)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.synthetic_defects import (  # noqa: E402
    DEFECT_FUNCS,
    apply_random_defect,
    load_image_as_array,
    save_array_as_image,
)


def generate_defects(
    source_dir: str,
    output_dir: str,
    count: int,
    seed: int = 0,
) -> None:
    """
    source_dir 의 정상 이미지에 결함을 적용해 output_dir 에 저장합니다.

    생성 방식:
      - 결함 종류를 순환(round-robin) 방식으로 고르게 배분합니다.
        예) count=9 이면: scratch 3장 + spot 3장 + contamination 3장
      - 각 결함 이미지는 서로 다른 시드로 만들어 다양한 패턴이 생성됩니다.
      - source_dir 의 이미지가 count 보다 적으면 순환 반복 사용합니다.

    파일 명명 규칙: {결함종류}_{4자리번호}.png
      예) scratch_0000.png, spot_0001.png, contamination_0002.png

    Args:
        source_dir: 원본 정상 이미지 디렉터리 (test/good)
        output_dir: 결함 이미지를 저장할 디렉터리 (test/defect)
        count     : 생성할 결함 이미지 총 수
        seed      : 재현성 난수 시드
    """
    os.makedirs(output_dir, exist_ok=True)

    # 소스 디렉터리에서 이미지 파일 목록 수집 (정렬해 재현성 보장)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    sources = sorted(
        p for p in os.listdir(source_dir)
        if os.path.splitext(p)[1].lower() in exts
    )

    # 정상 이미지가 없으면 오류 — generate_normal_images.py 를 먼저 실행해야 함
    if not sources:
        print(f"[오류] 소스 이미지를 찾을 수 없습니다: {source_dir}")
        print("먼저 scripts/generate_normal_images.py 를 실행하세요.")
        sys.exit(1)

    rng = np.random.default_rng(seed)  # 결함 시드 생성용
    defect_types = list(DEFECT_FUNCS.keys())  # ["scratch", "spot", "contamination"]
    counts = {d: 0 for d in defect_types}     # 결함 종류별 생성 수 카운터

    for idx in range(count):
        # 소스 이미지 순환 선택 (이미지 수가 부족해도 계속 반복)
        src_name = sources[idx % len(sources)]
        src_path = os.path.join(source_dir, src_name)
        img = load_image_as_array(src_path)

        # 각 이미지마다 고유한 시드 생성 (동일 소스에서도 다양한 결함 패턴)
        defect_seed = int(rng.integers(0, 2**31))

        # 결함 종류를 순환 방식으로 선택 (균등 분배)
        defect_type = defect_types[idx % len(defect_types)]

        # 결함 적용 (defect_type 과 seed 고정 → 재현 가능)
        defect_img, applied_type = apply_random_defect(
            img, defect_type=defect_type, seed=defect_seed
        )

        # 결과 저장: {결함종류}_{인덱스:4자리}.png
        out_name = f"{applied_type}_{idx:04d}.png"
        save_array_as_image(defect_img, os.path.join(output_dir, out_name))
        counts[applied_type] += 1

    # 생성 완료 요약 출력
    print(f"[완료] test/defect: 총 {count}장 생성 → {output_dir}")
    for dtype, cnt in counts.items():
        print(f"       {dtype}: {cnt}장")


def main() -> None:
    """커맨드라인 인터페이스 — argparse 로 파라미터를 받아 generate_defects 호출."""
    parser = argparse.ArgumentParser(description="합성 결함 이미지 생성")
    parser.add_argument(
        "--count", type=int, default=30,
        help="생성할 결함 이미지 수 (기본: 30)",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="재현성 난수 시드 (기본: 0)",
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        default=os.path.join(ROOT, "data", "test", "good"),
        help="정상 이미지 소스 디렉터리 (기본: data/test/good)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.path.join(ROOT, "data", "test", "defect"),
        help="결함 이미지 저장 디렉터리 (기본: data/test/defect)",
    )
    args = parser.parse_args()

    generate_defects(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        count=args.count,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
