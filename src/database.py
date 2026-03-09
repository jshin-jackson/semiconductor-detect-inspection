"""
StarRocks MySQL 호환 클라이언트 모듈.

StarRocks 는 MySQL 프로토콜을 지원하므로 pymysql 로 연결합니다.
주요 역할:
  1. Iceberg External Catalog 를 StarRocks 에 등록 (setup_infra.py 에서 호출)
  2. Iceberg 테이블 데이터를 SQL 로 조회 (/history, /stats 엔드포인트)

StarRocks 의 External Catalog 기능을 통해 MinIO 위의 Iceberg 테이블을
SQL 로 직접 쿼리할 수 있습니다.
"""

from __future__ import annotations

from typing import Any

import pymysql
import pymysql.cursors


class StarRocksClient:
    """StarRocks 에 연결해 SQL 을 실행하는 클라이언트 클래스."""

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Args:
            config: config.yaml 의 starrocks 섹션 딕셔너리
                - host    : StarRocks FE 호스트 (예: localhost)
                - port    : MySQL 포트 (예: 9030)
                - user    : 계정명 (예: root)
                - password: 비밀번호
                - database: 기본 데이터베이스 (빈 문자열이면 지정 안 함)
        """
        self.config = config

    def _connect(self) -> pymysql.Connection:
        """
        새 StarRocks 연결을 생성해 반환합니다.

        database 파라미터를 비워두면 StarRocks 기본 상태로 연결됩니다.
        (CREATE CATALOG, SHOW CATALOGS 같은 DDL 은 특정 DB 컨텍스트 불필요)

        read_timeout=180 으로 설정한 이유:
          Iceberg External Catalog 를 처음 조회할 때 Parquet 파일을
          MinIO 에서 읽는 데 최대 60~90초 걸릴 수 있기 때문입니다.
        """
        db = self.config.get("database") or None  # 빈 문자열이면 None 으로 처리
        return pymysql.connect(
            host=self.config["host"],
            port=int(self.config["port"]),
            user=self.config["user"],
            password=self.config.get("password", ""),
            database=db,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,  # 결과를 dict 로 반환
            connect_timeout=10,    # 연결 수립 제한 시간 (초)
            read_timeout=180,      # 쿼리 응답 제한 시간 (초) — Iceberg 첫 조회 고려
        )

    def execute(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """
        SQL 을 실행하고 결과를 딕셔너리 리스트로 반환합니다.

        매 호출마다 새 연결을 맺고 쿼리 후 연결을 닫습니다.
        (커넥션 풀 없이 단순하게 유지 — PoC 수준에서 충분)

        Args:
            sql: 실행할 SQL 문 (SELECT / DDL 모두 가능)
            params: pymysql 바인딩 파라미터 (SQL 인젝션 방지용)

        Returns:
            각 행이 {컬럼명: 값} 형태인 딕셔너리 리스트.
            결과가 없으면 빈 리스트 반환.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)  # SQL 실행
                return cur.fetchall() or []  # 결과 전체 반환 (없으면 빈 리스트)
        finally:
            conn.close()  # 항상 연결 닫기

    def create_iceberg_catalog(
        self,
        catalog_name: str,
        rest_uri: str,
        warehouse: str,
        minio_endpoint: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        """
        StarRocks 에 Iceberg External Catalog 를 등록합니다.
        이미 동일한 이름의 카탈로그가 있으면 건너뜁니다.

        등록된 카탈로그를 통해 StarRocks 는 Iceberg REST 서버로
        테이블 메타데이터를 조회하고 MinIO 에서 Parquet 파일을 직접 읽습니다.

        주의: StarRocks 파드는 Kubernetes 내부에서 실행되므로
              rest_uri 와 minio_endpoint 는 K8s 내부 DNS 주소여야 합니다.
              (예: http://iceberg-rest:8181, http://minio:9000)

        Args:
            catalog_name    : StarRocks 에 등록할 카탈로그 이름 (예: iceberg_catalog)
            rest_uri        : Iceberg REST 서버 주소 (K8s 내부)
            warehouse       : Iceberg warehouse S3 경로 (예: s3://warehouse/)
            minio_endpoint  : MinIO S3 엔드포인트 (K8s 내부)
            access_key      : MinIO 액세스 키
            secret_key      : MinIO 시크릿 키
        """
        # 기존 카탈로그 목록 확인 — 이미 있으면 등록 생략
        try:
            existing = self.execute("SHOW CATALOGS")
            found = False
            for row in existing:
                # SHOW CATALOGS 의 컬럼명은 버전마다 다를 수 있어 모든 값 검색
                for v in row.values():
                    if str(v) == catalog_name:
                        found = True
                        break
            if found:
                print(f"[StarRocks] 카탈로그 이미 존재: {catalog_name}")
                return
        except Exception:
            pass  # SHOW CATALOGS 실패 시 CREATE 를 재시도

        # Iceberg External Catalog 생성 SQL
        sql = f"""
        CREATE EXTERNAL CATALOG {catalog_name}
        PROPERTIES (
            "type" = "iceberg",
            "iceberg.catalog.type" = "rest",
            "iceberg.catalog.uri" = "{rest_uri}",
            "iceberg.catalog.warehouse" = "{warehouse}",
            "aws.s3.access_key" = "{access_key}",
            "aws.s3.secret_key" = "{secret_key}",
            "aws.s3.endpoint" = "{minio_endpoint}",
            "aws.s3.enable_path_style_access" = "true",  -- MinIO 는 path-style 필수
            "aws.s3.region" = "us-east-1"                -- MinIO 가상 리전
        )
        """
        self.execute(sql)
        print(f"[StarRocks] Iceberg 카탈로그 등록 완료: {catalog_name}")

    def query_recent(
        self,
        catalog_name: str = "iceberg_catalog",
        namespace: str = "default",
        table: str = "inspection_results",
        n: int = 50,
    ) -> list[dict[str, Any]]:
        """
        최근 검사 결과를 최신순으로 n 건 조회합니다.

        'default' 는 StarRocks SQL 예약어이므로 역따옴표(`)로 감쌉니다.

        Args:
            catalog_name: StarRocks 카탈로그 이름
            namespace   : Iceberg 네임스페이스 (Iceberg database)
            table       : Iceberg 테이블 이름
            n           : 최대 반환 건수

        Returns:
            각 행이 딕셔너리인 리스트 (최신순 정렬)
        """
        sql = f"""
        SELECT *
        FROM `{catalog_name}`.`{namespace}`.`{table}`
        ORDER BY timestamp DESC
        LIMIT {n}
        """
        return self.execute(sql)

    def query_anomaly_stats(
        self,
        catalog_name: str = "iceberg_catalog",
        namespace: str = "default",
        table: str = "inspection_results",
    ) -> list[dict[str, Any]]:
        """
        날짜별 검사 통계를 집계해 반환합니다.

        집계 항목:
          - inspection_date : 검사 날짜 (UTC 기준)
          - total_count     : 해당 날짜 총 검사 건수
          - anomaly_count   : 결함(is_anomaly=True) 건수
          - avg_score       : 평균 이상 점수

        Args:
            catalog_name: StarRocks 카탈로그 이름
            namespace   : Iceberg 네임스페이스
            table       : Iceberg 테이블 이름

        Returns:
            날짜별 집계 결과 리스트 (최신 날짜 우선, 최대 30일치)
        """
        sql = f"""
        SELECT
            DATE(timestamp)     AS inspection_date,
            COUNT(*)            AS total_count,
            SUM(is_anomaly)     AS anomaly_count,
            AVG(anomaly_score)  AS avg_score
        FROM `{catalog_name}`.`{namespace}`.`{table}`
        GROUP BY DATE(timestamp)
        ORDER BY inspection_date DESC
        LIMIT 30
        """
        return self.execute(sql)

    def ping(self) -> bool:
        """
        StarRocks 에 연결 가능한지 확인합니다.

        SELECT 1 쿼리를 실행해 응답이 오면 True 를 반환합니다.
        연결 오류나 쿼리 실패 시 False 를 반환합니다.
        """
        try:
            self.execute("SELECT 1")
            return True
        except Exception:
            return False
