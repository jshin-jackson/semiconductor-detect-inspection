"""
Database client with automatic SQLite fallback.

When StarRocks is reachable, uses StarRocks (MySQL-compatible) via pymysql.
When StarRocks is NOT reachable (e.g. CML sandbox without K8s services),
automatically falls back to SQLite stored at data/local_storage/inspection.db.

This makes the AMP fully self-contained without any external dependencies.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("api.database")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class StarRocksClient:
    """
    Unified SQL client.

    Tries StarRocks first; if unreachable, automatically switches to
    SQLiteClient which stores data in data/local_storage/inspection.db.
    """

    def __new__(cls, config: dict[str, Any]) -> "StarRocksClient":
        client = _StarRocksBackend(config)
        if client.ping():
            logger.info("Database: StarRocks connected  host=%s port=%s",
                        config["host"], config["port"])
            return client          # type: ignore[return-value]
        logger.warning(
            "Database: StarRocks NOT available — using SQLite fallback."
        )
        return _SQLiteBackend()    # type: ignore[return-value]


# ---------------------------------------------------------------------------
# StarRocks backend (pymysql)
# ---------------------------------------------------------------------------

class _StarRocksBackend:

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def _connect(self):
        import pymysql
        import pymysql.cursors
        db = self.config.get("database") or None
        return pymysql.connect(
            host=self.config["host"],
            port=int(self.config["port"]),
            user=self.config["user"],
            password=self.config.get("password", ""),
            database=db,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=180,
        )

    def execute(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() or []
        finally:
            conn.close()

    def create_iceberg_catalog(self, catalog_name, rest_uri, warehouse,
                               minio_endpoint, access_key, secret_key) -> None:
        try:
            existing = self.execute("SHOW CATALOGS")
            for row in existing:
                if catalog_name in row.values():
                    return
        except Exception:
            pass
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
            "aws.s3.enable_path_style_access" = "true",
            "aws.s3.region" = "us-east-1"
        )
        """
        self.execute(sql)

    def query_recent(self, catalog_name="iceberg_catalog", namespace="default",
                     table="inspection_results", n=50) -> list[dict[str, Any]]:
        sql = f"""
        SELECT * FROM `{catalog_name}`.`{namespace}`.`{table}`
        ORDER BY timestamp DESC LIMIT {n}
        """
        return self.execute(sql)

    def query_anomaly_stats(self, catalog_name="iceberg_catalog",
                            namespace="default",
                            table="inspection_results") -> list[dict[str, Any]]:
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
        try:
            self.execute("SELECT 1")
            return True
        except Exception:
            return False

    def append_result(self, row: dict[str, Any]) -> None:
        """No-op for StarRocks — results are written via IcebergWriter."""
        pass


# ---------------------------------------------------------------------------
# SQLite fallback backend
# ---------------------------------------------------------------------------

class _SQLiteBackend:
    """
    SQLite fallback — stores inspection results locally.
    DB file: data/local_storage/inspection.db
    """

    def __init__(self) -> None:
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            _here = os.getcwd()
        storage_dir = os.path.join(os.path.dirname(_here), "data", "local_storage")
        os.makedirs(storage_dir, exist_ok=True)
        self._db_path = os.path.join(storage_dir, "inspection.db")
        self._init_db()
        logger.info("Database: SQLite at %s", self._db_path)

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inspection_results (
                    id                  TEXT PRIMARY KEY,
                    filename            TEXT NOT NULL,
                    timestamp           TEXT NOT NULL,
                    anomaly_score       REAL NOT NULL,
                    is_anomaly          INTEGER NOT NULL,
                    heatmap_minio_path  TEXT,
                    model_version       TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def append_result(self, row: dict[str, Any]) -> None:
        """Insert a new inspection result row."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO inspection_results
                (id, filename, timestamp, anomaly_score, is_anomaly,
                 heatmap_minio_path, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"],
                row["filename"],
                str(row["timestamp"]),
                float(row["anomaly_score"]),
                int(row["is_anomaly"]),
                row.get("heatmap_minio_path", ""),
                row.get("model_version", ""),
            ))
            conn.commit()
        finally:
            conn.close()

    def query_recent(self, catalog_name="", namespace="", table="",
                     n=50) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM inspection_results ORDER BY timestamp DESC LIMIT ?", (n,)
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def query_anomaly_stats(self, catalog_name="", namespace="",
                            table="") -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.execute("""
                SELECT
                    DATE(timestamp)         AS inspection_date,
                    COUNT(*)                AS total_count,
                    SUM(is_anomaly)         AS anomaly_count,
                    AVG(anomaly_score)      AS avg_score
                FROM inspection_results
                GROUP BY DATE(timestamp)
                ORDER BY inspection_date DESC
                LIMIT 30
            """)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            conn = self._connect()
            conn.execute("SELECT 1")
            conn.close()
            return True
        except Exception:
            return False

    # Stub — not needed for SQLite
    def create_iceberg_catalog(self, *args, **kwargs) -> None:  # noqa: ANN001
        pass

    def execute(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.execute(sql, params or ())
            return [dict(r) for r in (cur.fetchall() or [])]
        finally:
            conn.close()
