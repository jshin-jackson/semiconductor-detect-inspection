"""
PyIceberg 를 이용해 MinIO 위의 Apache Iceberg 테이블에 검사 결과를 기록합니다.

Iceberg 는 Parquet 파일 기반의 테이블 포맷으로, 데이터 레이크에 ACID 트랜잭션과
스키마 진화(schema evolution) 기능을 제공합니다.

아키텍처:
  FastAPI → IcebergWriter → Iceberg REST 카탈로그(K8s) → MinIO(K8s)
                                     ↑
                          테이블 메타데이터 관리

테이블 스키마 (inspection_results):
  id                  string        — 추론 고유 UUID
  filename            string        — 검사한 이미지 파일명
  timestamp           timestamptz   — UTC 기준 검사 시각
  anomaly_score       double        — 이상 점수 (0~1)
  is_anomaly          boolean       — 결함 여부
  heatmap_minio_path  string        — 히트맵 MinIO 경로 (nullable)
  model_version       string        — 사용된 모델 버전 (nullable)
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError
from pyiceberg.schema import Schema
from pyiceberg.types import (
    BooleanType,
    DoubleType,
    NestedField,
    StringType,
    TimestamptzType,
)

# ──────────────────────────────────────────────────────────────────────────────
# 스키마 정의
# Iceberg 네이티브 스키마와 PyArrow 스키마를 별도로 정의합니다.
# PyIceberg 는 테이블 생성 시 ICEBERG_SCHEMA 를,
# 데이터 쓰기 시 PYARROW_SCHEMA 를 사용합니다.
# ──────────────────────────────────────────────────────────────────────────────

# Iceberg 네이티브 스키마 — 테이블 생성에 사용
ICEBERG_SCHEMA = Schema(
    NestedField(field_id=1, name="id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="filename", field_type=StringType(), required=True),
    NestedField(field_id=3, name="timestamp", field_type=TimestamptzType(), required=True),
    NestedField(field_id=4, name="anomaly_score", field_type=DoubleType(), required=True),
    NestedField(field_id=5, name="is_anomaly", field_type=BooleanType(), required=True),
    NestedField(field_id=6, name="heatmap_minio_path", field_type=StringType(), required=False),
    NestedField(field_id=7, name="model_version", field_type=StringType(), required=False),
)

# PyArrow 스키마 — pandas DataFrame → Arrow Table 변환 시 사용
# Iceberg 스키마와 컬럼 순서·타입이 정확히 일치해야 합니다.
PYARROW_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("filename", pa.string(), nullable=False),
        pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),  # 마이크로초, UTC
        pa.field("anomaly_score", pa.float64(), nullable=False),
        pa.field("is_anomaly", pa.bool_(), nullable=False),
        pa.field("heatmap_minio_path", pa.string(), nullable=True),
        pa.field("model_version", pa.string(), nullable=True),
    ]
)


class IcebergWriter:
    """
    Iceberg 검사 결과 테이블을 생성·관리하고 데이터를 append 하는 클래스.

    PyIceberg RestCatalog 를 통해 Iceberg REST 서버(K8s)와 통신하며,
    실제 Parquet 파일은 MinIO(S3 호환) 에 저장됩니다.
    """

    def __init__(self, config: dict[str, Any], minio_config: dict[str, Any] | None = None) -> None:
        """
        Iceberg RestCatalog 클라이언트를 초기화합니다.

        config 와 minio_config 를 조합해 카탈로그 연결 속성을 구성합니다.
        minio_config 가 없으면 카탈로그는 파일 읽기에 실패할 수 있습니다.

        Args:
            config: config.yaml 의 iceberg 섹션
                - rest_uri   : Iceberg REST 서버 주소 (예: http://localhost:8181)
                - warehouse  : S3 warehouse 경로 (예: s3://warehouse/)
                - namespace  : Iceberg 네임스페이스 (예: default)
                - table      : 테이블 이름 (예: inspection_results)
            minio_config: config.yaml 의 minio 섹션 (S3 접근 자격증명 제공)
                - endpoint   : "host:port" 형식 (예: localhost:9000)
                - access_key : MinIO 액세스 키
                - secret_key : MinIO 시크릿 키
        """
        self.namespace = config["namespace"]
        self.table_name = config["table"]
        # 카탈로그에서 테이블을 식별하는 전체 경로 (예: default.inspection_results)
        self.full_table_id = f"{self.namespace}.{self.table_name}"

        # RestCatalog 기본 연결 속성
        catalog_props: dict[str, Any] = {
            "uri": config["rest_uri"],          # Iceberg REST 서버 URL
            "warehouse": config["warehouse"],   # MinIO S3 warehouse 경로
        }

        # MinIO(S3) 접근 자격증명 추가 — 없으면 Parquet 읽기/쓰기 실패
        if minio_config:
            # config.yaml 의 minio.endpoint 는 "host:port" 형식이므로 http:// 접두사 추가
            raw_endpoint = minio_config.get("endpoint", "localhost:9000")
            s3_endpoint = (
                f"http://{raw_endpoint}"
                if not raw_endpoint.startswith("http")
                else raw_endpoint
            )
            catalog_props["s3.endpoint"] = s3_endpoint
            catalog_props["s3.access-key-id"] = minio_config.get("access_key", "admin")
            catalog_props["s3.secret-access-key"] = minio_config.get("secret_key", "password")
            # MinIO 는 가상 호스팅 스타일(bucket.host) 대신 path-style(host/bucket) 필수
            catalog_props["s3.path-style-access"] = "true"

        # PyIceberg RestCatalog 인스턴스 생성
        self.catalog = RestCatalog(
            name="default",
            **catalog_props,
        )

    def init_table(self) -> None:
        """
        Iceberg 네임스페이스와 inspection_results 테이블을 초기화합니다.

        이미 존재하면 조용히 건너뜁니다.
        setup_infra.py 에서 인프라 초기화 시 최초 1회 호출됩니다.
        """
        # ── 네임스페이스 생성 ──────────────────────────────────────────────────
        try:
            self.catalog.create_namespace(self.namespace)
            print(f"[Iceberg] 네임스페이스 생성: {self.namespace}")
        except NamespaceAlreadyExistsError:
            pass  # 이미 있으면 정상 — 넘어감

        # ── 테이블 생성 ────────────────────────────────────────────────────────
        try:
            self.catalog.load_table(self.full_table_id)  # 존재 여부 확인
            print(f"[Iceberg] 테이블 이미 존재: {self.full_table_id}")
        except NoSuchTableError:
            # 테이블이 없으면 ICEBERG_SCHEMA 로 새로 생성
            self.catalog.create_table(
                identifier=self.full_table_id,
                schema=ICEBERG_SCHEMA,
            )
            print(f"[Iceberg] 테이블 생성: {self.full_table_id}")

    def append_result(self, row: dict[str, Any]) -> None:
        """
        단일 검사 결과 행을 Iceberg 테이블에 append 합니다.

        처리 흐름:
          1. row 딕셔너리 → pandas DataFrame
          2. timestamp 컬럼을 UTC datetime 으로 변환
          3. DataFrame → PyArrow Table (스키마 명시적 지정)
          4. Iceberg 테이블에 append (새 Parquet 파일 생성)

        Iceberg 의 append 는 기존 파일을 수정하지 않고 새 파일을 추가합니다.
        이 방식은 동시 쓰기에 안전하고 충돌이 없습니다.

        Args:
            row: 다음 키를 포함하는 딕셔너리
                - id                 (str)        : 추론 고유 UUID
                - filename           (str)        : 이미지 파일명
                - timestamp          (str|datetime): UTC ISO 8601 시각
                - anomaly_score      (float)      : 이상 점수
                - is_anomaly         (bool)       : 결함 여부
                - heatmap_minio_path (str|None)   : 히트맵 MinIO 경로
                - model_version      (str|None)   : 모델 버전
        """
        import pandas as pd

        # Iceberg 테이블 핸들 로드
        table = self.catalog.load_table(self.full_table_id)

        # 딕셔너리 → DataFrame (1행)
        df = pd.DataFrame([row])

        # timestamp 컬럼 타입 강제 변환: 문자열·datetime 모두 UTC timestamp 로 통일
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # 타입 명시적 변환 (PyArrow 스키마와 불일치 방지)
        df["anomaly_score"] = df["anomaly_score"].astype(float)
        df["is_anomaly"] = df["is_anomaly"].astype(bool)

        # pandas DataFrame → PyArrow Table (스키마 엄격 적용)
        arrow_table = pa.Table.from_pandas(df, schema=PYARROW_SCHEMA, preserve_index=False)

        # Iceberg 테이블에 append — MinIO 에 새 Parquet 파일로 저장됨
        table.append(arrow_table)

    def query_all(self) -> list[dict[str, Any]]:
        """
        테이블의 모든 행을 딕셔너리 리스트로 반환합니다.

        주의: 대용량 데이터에는 적합하지 않습니다.
              대용량 조회는 StarRocks SQL(/history, /stats) 을 사용하세요.
        """
        table = self.catalog.load_table(self.full_table_id)
        scan = table.scan()                 # 전체 스캔 플랜 생성
        arrow_table = scan.to_arrow()       # Parquet → PyArrow Table
        return arrow_table.to_pydict()      # {컬럼명: [값, ...]} dict 반환
