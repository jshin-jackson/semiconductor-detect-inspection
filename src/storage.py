"""
MinIO 객체 스토리지 클라이언트 래퍼 모듈.

MinIO 는 S3 호환 오브젝트 스토리지 서버입니다.
이 프로젝트에서는 다음 데이터를 MinIO 에 저장합니다:
  - weights/   : 학습된 PaDiM 모델 체크포인트 (.ckpt)
  - heatmaps/  : 추론 결과 히트맵 이미지 (.png)

MinIO 는 Kubernetes 클러스터 내부에서 실행되며,
로컬(MacBook) 에서는 kubectl port-forward 로 접근합니다.
"""

from __future__ import annotations

import io
import os
from typing import Any

from minio import Minio
from minio.error import S3Error


class StorageClient:
    """
    MinIO(S3 호환) 스토리지에 파일을 업로드·다운로드하는 클라이언트.

    minio 파이썬 SDK 를 얇게 감싸서 프로젝트에서 필요한 기능만 제공합니다.
    인스턴스 생성 시 버킷이 없으면 자동으로 생성합니다.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        MinIO 클라이언트를 초기화하고 버킷 존재 여부를 확인합니다.

        Args:
            config: config.yaml 의 minio 섹션 딕셔너리
                - endpoint  : "host:port" 형식 (예: localhost:9000)
                - access_key: MinIO 액세스 키 (예: admin)
                - secret_key: MinIO 시크릿 키 (예: password)
                - bucket    : 사용할 버킷 이름 (예: warehouse)
                - secure    : HTTPS 사용 여부 (로컬 개발 시 False)
        """
        self.bucket = config["bucket"]

        # MinIO Python SDK 클라이언트 생성
        self.client = Minio(
            endpoint=config["endpoint"],      # host:port (http:// 접두사 없음)
            access_key=config["access_key"],
            secret_key=config["secret_key"],
            secure=config.get("secure", False),  # 로컬/개발: False, 운영: True
        )

        # 버킷이 없으면 자동 생성
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """
        설정된 버킷이 존재하는지 확인하고, 없으면 생성합니다.

        이미 존재하는 경우(BucketAlreadyOwnedByYou)는 정상 상태이므로 무시합니다.
        """
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            if e.code != "BucketAlreadyOwnedByYou":
                raise  # 예상치 못한 S3 오류는 그대로 전파

    def upload_file(self, local_path: str, object_name: str) -> str:
        """
        로컬 파일을 MinIO 에 업로드합니다.

        주로 모델 체크포인트(.ckpt) 업로드에 사용합니다.

        Args:
            local_path  : 업로드할 로컬 파일 경로 (예: weights/best.ckpt)
            object_name : MinIO 에 저장될 오브젝트 이름 (예: weights/best.ckpt)

        Returns:
            MinIO URI (예: s3://warehouse/weights/best.ckpt)
        """
        self.client.fput_object(self.bucket, object_name, local_path)
        return f"s3://{self.bucket}/{object_name}"

    def upload_bytes(self, data: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        """
        메모리의 bytes 데이터를 MinIO 에 업로드합니다.

        주로 히트맵 PNG 를 디스크에 저장하지 않고 바로 업로드할 때 사용합니다.

        Args:
            data        : 업로드할 bytes 데이터 (예: PNG 이미지 bytes)
            object_name : MinIO 에 저장될 오브젝트 이름 (예: heatmaps/{uuid}.png)
            content_type: HTTP Content-Type 헤더 값 (예: "image/png")

        Returns:
            MinIO URI (예: s3://warehouse/heatmaps/{uuid}.png)
        """
        buf = io.BytesIO(data)  # bytes → 파일 유사 객체
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=buf,
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{object_name}"

    def download_file(self, object_name: str, local_path: str) -> None:
        """
        MinIO 오브젝트를 로컬 경로에 다운로드합니다.

        저장 디렉터리가 없으면 자동으로 생성합니다.

        Args:
            object_name : 다운로드할 MinIO 오브젝트 이름
            local_path  : 저장할 로컬 파일 경로
        """
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        self.client.fget_object(self.bucket, object_name, local_path)

    def object_exists(self, object_name: str) -> bool:
        """
        지정된 오브젝트가 MinIO 버킷에 존재하는지 확인합니다.

        Args:
            object_name: 확인할 오브젝트 이름

        Returns:
            존재하면 True, 없으면 False
        """
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False  # NoSuchKey 등 S3 오류는 "없음"으로 처리

    def list_objects(self, prefix: str = "") -> list[str]:
        """
        지정된 prefix 아래의 모든 오브젝트 이름을 반환합니다.

        하위 디렉터리까지 재귀 탐색합니다.
        /health 엔드포인트에서 MinIO 연결 확인용으로도 사용됩니다.

        Args:
            prefix: 검색할 경로 접두사 (예: "heatmaps/", "weights/")
                    빈 문자열이면 버킷 전체를 조회합니다.

        Returns:
            오브젝트 이름 문자열 리스트
        """
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]
