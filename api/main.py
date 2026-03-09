"""
반도체 결함 검사 FastAPI 애플리케이션 진입점.

서버를 시작하면 config.yaml 을 읽어 모델·MinIO·Iceberg·StarRocks 를
자동으로 초기화합니다.

엔드포인트 목록:
  GET  /health       — 서버/모델/MinIO/StarRocks 상태 확인
  POST /train        — PaDiM 모델 학습
  GET  /model        — 현재 모델 정보
  POST /predict      — 이미지 이상 탐지 추론
  GET  /history      — 최근 검사 이력 조회
  GET  /stats        — 일별 이상 탐지 통계
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 프로젝트 루트 디렉터리와 기본 설정 파일 경로 계산
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "configs", "config.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 서버의 시작/종료 생명 주기를 관리합니다.

    - 서버 시작 시: config.yaml 을 읽고 모델·외부 서비스를 초기화합니다.
    - 서버 종료 시: (필요 시 정리 코드 추가 가능)
    """
    from api.state import get_state  # 순환 임포트 방지를 위해 함수 안에서 import

    state = get_state()          # 전역 싱글턴 AppState 가져오기
    state.initialize(CONFIG_PATH)  # 모델, MinIO, Iceberg, StarRocks 초기화
    yield
    # 서버 종료 시 정리 작업 (현재는 없음)


# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="반도체 결함 검사 PoC API",
    description=(
        "PaDiM 기반 이상 탐지 API.\n\n"
        "정상 이미지로 학습한 모델로 반도체 웨이퍼 결함을 탐지하고 "
        "결과를 MinIO와 Apache Iceberg에 저장합니다."
    ),
    version="1.0.0",
    lifespan=lifespan,  # 시작/종료 핸들러 등록
)

# CORS 미들웨어: 모든 출처에서의 API 호출 허용 (개발/PoC 환경용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 실운영 시에는 허용할 도메인을 명시적으로 지정하세요
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록: 추론 엔드포인트와 학습 엔드포인트를 앱에 연결
from api.routes.predict import router as predict_router  # noqa: E402
from api.routes.train import router as train_router      # noqa: E402

app.include_router(predict_router, tags=["추론"])  # /health, /predict, /history, /stats
app.include_router(train_router, tags=["학습"])    # /train, /model


@app.get("/", include_in_schema=False)
async def root():
    """루트 경로 — API 문서 링크를 안내합니다."""
    return {
        "message": "반도체 결함 검사 PoC API",
        "docs": "/docs",    # Swagger UI
        "redoc": "/redoc",  # ReDoc UI
    }
