"""
Semiconductor Defect Inspection FastAPI application entry point.

On startup the server reads config.yaml (with environment variable overrides)
and initialises the model, MinIO, Iceberg, and StarRocks clients.

Endpoints:
  GET  /health       — server / model / MinIO / StarRocks status
  POST /train        — train the PaDiM model
  GET  /model        — loaded model info
  POST /predict      — anomaly detection inference
  GET  /history      — recent inspection history
  GET  /stats        — daily anomaly detection statistics

In production (CML Application) the server also serves the pre-built React
frontend from frontend/dist/ as static files.
"""

from __future__ import annotations

import logging
import logging.config
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "configs", "config.yaml")
FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")

# ---------------------------------------------------------------------------
# Logging configuration
# Structured format: timestamp | level | logger | message
# Applied once at module import so all loggers (api.*, uvicorn.*) share it.
# ---------------------------------------------------------------------------
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "api":       {"level": "DEBUG", "propagate": True},
        "uvicorn":   {"level": "INFO",  "propagate": True},
        "uvicorn.access": {"level": "INFO", "propagate": True},
    },
})

logger = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 서버의 시작/종료 생명 주기를 관리합니다.

    - 서버 시작 시: config.yaml 을 읽고 모델·외부 서비스를 초기화합니다.
    - 서버 종료 시: (필요 시 정리 코드 추가 가능)
    """
    from api.state import get_state

    logger.info("=== Semiconductor Defect Inspection API starting ===")
    state = get_state()
    state.initialize(CONFIG_PATH)

    # Startup summary — one place to see what's available
    logger.info("--- Startup summary ---")
    logger.info("  Model loaded   : %s  (version=%s)", state.model_loaded, state.model_version)
    logger.info("  MinIO          : %s", "connected" if state.storage       else "NOT connected")
    logger.info("  Iceberg        : %s", "connected" if state.iceberg_writer else "NOT connected")
    logger.info("  StarRocks      : %s", "connected" if state.starrocks      else "NOT connected")
    logger.info("-----------------------")
    if not state.model_loaded:
        logger.warning("Model not loaded — POST /train to train before using /predict")
    logger.info("=== API ready ===")
    yield
    logger.info("=== API shutting down ===")


app = FastAPI(
    title="Semiconductor Defect Inspection API",
    description=(
        "PaDiM-based anomaly detection API.\n\n"
        "Detects semiconductor wafer defects using a model trained on normal images "
        "and stores results in MinIO and Apache Iceberg."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes.predict import router as predict_router  # noqa: E402
from api.routes.train import router as train_router      # noqa: E402

app.include_router(predict_router, tags=["Inference"])
app.include_router(train_router, tags=["Training"])


@app.get("/docs-info", include_in_schema=False)
async def root():
    return {
        "message": "Semiconductor Defect Inspection API",
        "docs": "/docs",
        "redoc": "/redoc",
    }


# ---------------------------------------------------------------------------
# Serve pre-built React frontend (production / CML Application mode).
# This must come AFTER all API routes so that API paths take priority.
# ---------------------------------------------------------------------------
if os.path.isdir(FRONTEND_DIST):
    # Serve /assets/* and other static assets directly
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Catch-all: serve the React SPA index.html for client-side routing."""
        index = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index)
