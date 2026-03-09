"""
정상 웨이퍼 이미지에 합성(Synthetic) 결함을 삽입하는 모듈.

실제 결함 이미지 없이도 모델 평가를 할 수 있도록
정상 이미지를 변형해 결함처럼 보이게 만듭니다.

지원 결함 종류:
  scratch      — cv2.line 으로 그은 얇은 스크래치 선
  spot         — cv2.circle 로 만든 밝거나 어두운 점 결함
  contamination— 불규칙한 다각형 형태의 오염 영역 (노이즈 텍스처 포함)

generate_defects.py 스크립트에서 이 모듈을 사용해
test/defect/ 디렉터리를 자동 생성합니다.
"""

from __future__ import annotations

import random

import cv2
import numpy as np
from PIL import Image


def apply_scratch(
    img: np.ndarray,
    rng: random.Random | None = None,
) -> np.ndarray:
    """
    이미지에 랜덤 스크래치 선을 1~3개 추가합니다.

    실제 반도체 제조 공정에서 발생하는 선형 스크래치를 모사합니다.
    어두운 색(회색 20~60) 의 얇은 선을 임의 방향으로 그립니다.

    Args:
        img: 원본 이미지 (H, W, 3) uint8 RGB numpy 배열
        rng: 재현성 제어용 Python 표준 random 인스턴스
             None 이면 시드 없는 임의 인스턴스 생성

    Returns:
        스크래치가 그려진 (H, W, 3) uint8 numpy 배열 (원본 복사본)
    """
    if rng is None:
        rng = random.Random()

    result = img.copy()  # 원본 손상 방지를 위해 복사
    h, w = result.shape[:2]

    num_lines = rng.randint(1, 3)  # 선 개수 (1~3개)
    for _ in range(num_lines):
        # 선의 시작점을 이미지 내 임의 위치로 결정
        x1 = rng.randint(0, w - 1)
        y1 = rng.randint(0, h - 1)

        # 임의 방향(각도)으로 선 길이만큼 끝점 계산
        angle = rng.uniform(0, np.pi)         # 0~180도 임의 방향
        length = rng.randint(w // 4, w // 2)  # 이미지 너비의 25%~50% 길이
        x2 = int(x1 + length * np.cos(angle))
        y2 = int(y1 + length * np.sin(angle))

        # 스크래치 색상: 어두운 회색 (20~60)
        color_val = rng.randint(20, 60)
        thickness = rng.randint(1, 3)  # 선 굵기 (1~3 픽셀)

        cv2.line(result, (x1, y1), (x2, y2), (color_val, color_val, color_val), thickness)

    return result


def apply_spot(
    img: np.ndarray,
    rng: random.Random | None = None,
) -> np.ndarray:
    """
    이미지에 원형 점 결함을 1~4개 추가합니다.

    파티클 오염이나 에칭 불량으로 발생하는 점 형태 결함을 모사합니다.
    밝은 점(200~255) 또는 어두운 점(0~50) 을 무작위로 생성합니다.

    Args:
        img: 원본 이미지 (H, W, 3) uint8 RGB numpy 배열
        rng: 재현성 제어용 Python 표준 random 인스턴스

    Returns:
        점 결함이 추가된 (H, W, 3) uint8 numpy 배열
    """
    if rng is None:
        rng = random.Random()

    result = img.copy()
    h, w = result.shape[:2]

    num_spots = rng.randint(1, 4)  # 점 개수 (1~4개)
    for _ in range(num_spots):
        # 이미지 가장자리를 피해 중앙 영역에 점 위치 결정
        cx = rng.randint(w // 6, 5 * w // 6)
        cy = rng.randint(h // 6, 5 * h // 6)
        radius = rng.randint(5, 20)  # 반경 5~20 픽셀

        # 밝은 점 vs 어두운 점을 50% 확률로 결정
        bright = rng.choice([True, False])
        color_val = rng.randint(200, 255) if bright else rng.randint(0, 50)

        # 채워진 원(-1 = 내부 채우기) 그리기
        cv2.circle(result, (cx, cy), radius, (color_val, color_val, color_val), -1)

    return result


def apply_contamination(
    img: np.ndarray,
    rng: random.Random | None = None,
) -> np.ndarray:
    """
    이미지에 불규칙한 다각형 형태의 오염 영역을 추가합니다.

    실제 공정 오염물(파티클, 이물질)처럼 보이도록
    5~9각형에 노이즈 텍스처를 오버레이합니다.

    처리 흐름:
      1. 중앙 근처에 5~9각형 꼭짓점 생성 (약간의 랜덤 편차 추가)
      2. cv2.fillPoly 로 다각형 내부를 회색으로 채우기
      3. 동일 영역에 ±25 픽셀 노이즈를 추가해 텍스처감 부여

    Args:
        img: 원본 이미지 (H, W, 3) uint8 RGB numpy 배열
        rng: 재현성 제어용 Python 표준 random 인스턴스

    Returns:
        오염 영역이 추가된 (H, W, 3) uint8 numpy 배열
    """
    if rng is None:
        rng = random.Random()

    result = img.copy()
    h, w = result.shape[:2]

    # 오염 영역 중심점 (이미지 중앙 절반 영역 내)
    cx = rng.randint(w // 4, 3 * w // 4)
    cy = rng.randint(h // 4, 3 * h // 4)

    # 다각형 꼭짓점 생성 (5~9각형)
    num_pts = rng.randint(5, 9)
    pts = []
    for i in range(num_pts):
        # 균등 분할 각도에 약간의 랜덤 오차(±0.3 rad) 추가 → 불규칙한 형태
        angle = 2 * np.pi * i / num_pts + rng.uniform(-0.3, 0.3)
        r = rng.randint(15, 45)  # 중심에서의 반경 15~45 픽셀
        px = int(cx + r * np.cos(angle))
        py = int(cy + r * np.sin(angle))
        pts.append([px, py])

    pts_arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
    color_val = rng.randint(80, 130)  # 중간 회색 계열

    # 다각형 내부를 단색으로 채우기
    cv2.fillPoly(result, [pts_arr], (color_val, color_val, color_val))

    # 노이즈 텍스처 오버레이: 오염 영역만 선택적으로 노이즈 추가
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [pts_arr], 255)               # 오염 영역 마스크 생성

    noise = np.random.randint(-25, 25, (h, w), dtype=np.int16)  # ±25 노이즈
    for c in range(3):  # R, G, B 채널 각각에 적용
        ch = result[:, :, c].astype(np.int16)
        ch[mask > 0] += noise[mask > 0]              # 마스크 영역에만 노이즈 추가
        result[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)  # 0~255 클리핑

    return result


# 결함 종류 이름 → 함수 매핑 딕셔너리
# 새 결함 유형을 추가할 때 이 딕셔너리에만 등록하면 됩니다.
DEFECT_FUNCS = {
    "scratch": apply_scratch,
    "spot": apply_spot,
    "contamination": apply_contamination,
}


def apply_random_defect(
    img: np.ndarray,
    defect_type: str | None = None,
    seed: int | None = None,
) -> tuple[np.ndarray, str]:
    """
    이미지에 랜덤(또는 지정) 결함을 적용해 반환합니다.

    defect_type 을 지정하지 않으면 DEFECT_FUNCS 에서 무작위로 선택합니다.
    seed 를 지정하면 동일한 입력에 대해 항상 같은 결함이 생성됩니다 (재현성).

    Args:
        img        : 원본 이미지 (H, W, 3) uint8 RGB numpy 배열
        defect_type: 적용할 결함 종류
                     "scratch" | "spot" | "contamination" | None(랜덤)
        seed       : 난수 시드 (None 이면 매번 다른 결함)

    Returns:
        (결함이 적용된 이미지, 적용된 결함 종류 이름) 튜플
    """
    rng = random.Random(seed)  # seed 가 None 이면 매번 다른 결과

    # 결함 종류 미지정 시 무작위 선택
    if defect_type is None:
        defect_type = rng.choice(list(DEFECT_FUNCS.keys()))

    func = DEFECT_FUNCS[defect_type]
    return func(img, rng=rng), defect_type


def load_image_as_array(path: str) -> np.ndarray:
    """
    이미지 파일을 읽어 RGB numpy 배열로 반환합니다.

    PIL 을 사용해 PNG, JPEG, BMP 등 다양한 포맷을 지원하며
    항상 3채널 RGB 배열로 통일합니다.

    Args:
        path: 읽을 이미지 파일 경로

    Returns:
        (H, W, 3) uint8 RGB numpy 배열
    """
    return np.array(Image.open(path).convert("RGB"))


def save_array_as_image(arr: np.ndarray, path: str) -> None:
    """
    numpy 배열을 PNG 이미지 파일로 저장합니다.

    uint8 로 자동 변환한 뒤 저장합니다.

    Args:
        arr : (H, W, 3) uint8 RGB numpy 배열
        path: 저장할 파일 경로 (확장자 .png 권장)
    """
    Image.fromarray(arr.astype(np.uint8)).save(path)
