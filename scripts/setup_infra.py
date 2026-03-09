"""
인프라 초기화 스크립트.

Kubernetes 배포(./scripts/k8s-deploy.sh) 완료 후 최초 1회 실행합니다.
다음 세 가지 초기화 작업을 순서대로 수행합니다:

  1. MinIO 버킷 서브 경로 초기화
     - heatmaps/  : 추론 히트맵 PNG 저장 위치
     - weights/   : 모델 체크포인트 저장 위치
     - placeholder 오브젝트(.keep) 생성으로 폴더 구조 확보

  2. Iceberg inspection_results 테이블 초기화
     - Iceberg 네임스페이스(default) 생성
     - inspection_results 테이블 생성 (이미 있으면 건너뜀)

  3. StarRocks Iceberg External Catalog 등록
     - StarRocks 파드(K8s 내부)가 Iceberg REST 와 MinIO 를 바라보도록 설정
     - K8s 내부 DNS 주소(k8s_internal 섹션) 사용 필수
     - 이미 등록된 카탈로그면 건너뜀

주의: StarRocks 는 K8s 클러스터 내부에서 실행되므로
      Iceberg REST 와 MinIO 의 주소로 K8s 내부 서비스 DNS 를 사용해야 합니다.
      (config.yaml 의 k8s_internal 섹션 참고)

사용 예:
  python scripts/setup_infra.py
  python scripts/setup_infra.py --config configs/config.yaml
  python scripts/setup_infra.py --skip-starrocks  # StarRocks 만 건너뜀
"""

import argparse
import os
import sys
import time

# 프로젝트 루트를 sys.path 에 추가 (src 모듈 임포트용)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.database import StarRocksClient  # noqa: E402
from src.iceberg_writer import IcebergWriter  # noqa: E402
from src.storage import StorageClient  # noqa: E402
from src.utils import load_config  # noqa: E402


def wait_for_service(name: str, check_fn, retries: int = 20, delay: float = 5.0) -> None:
    """
    외부 서비스가 준비될 때까지 반복 대기합니다.

    Kubernetes 에서 파드가 Ready 상태가 되는 데 수십 초가 걸릴 수 있으므로
    서비스가 응답할 때까지 지정된 횟수만큼 재시도합니다.

    Args:
        name    : 로그에 표시할 서비스 이름 (예: "MinIO")
        check_fn: 서비스 상태를 확인하는 함수. True 반환 시 준비 완료.
        retries : 최대 재시도 횟수 (기본: 20)
        delay   : 재시도 간격 (초, 기본: 5.0)
    """
    for i in range(retries):
        try:
            if check_fn():
                print(f"[{name}] 연결 성공.")
                return
        except Exception:
            pass  # 연결 실패는 예상된 상황 — 재시도
        print(f"[{name}] 대기 중... ({i + 1}/{retries})")
        time.sleep(delay)
    # 최대 재시도 초과 — 오류로 중단하지 않고 계속 진행
    print(f"[경고] {name} 에 연결하지 못했습니다. 계속 진행합니다.")


def setup_minio(cfg: dict) -> None:
    """
    MinIO 버킷과 서브 디렉터리를 초기화합니다.

    StorageClient 생성 시 버킷이 없으면 자동으로 만들어집니다.
    이후 heatmaps/ 와 weights/ 경로에 placeholder(.keep) 오브젝트를 생성해
    빈 "폴더" 구조를 확보합니다.
    """
    print("\n--- MinIO 초기화 ---")

    # MinIO 연결 확인 함수 (StorageClient 생성이 성공하면 연결된 것)
    def check():
        StorageClient(cfg["minio"])
        return True

    wait_for_service("MinIO", check)
    client = StorageClient(cfg["minio"])
    print(f"[MinIO] 버킷 준비 완료: {cfg['minio']['bucket']}")

    # 서브 디렉터리 placeholder 생성 (빈 bytes 를 .keep 파일로 업로드)
    # MinIO 는 실제로 "폴더" 개념이 없으므로 prefix 경로만 존재하면 충분
    for prefix in ["heatmaps/.keep", "weights/.keep"]:
        if not client.object_exists(prefix):
            client.upload_bytes(b"", prefix)
    print("[MinIO] 서브 디렉터리 초기화 완료 (heatmaps/, weights/)")


def setup_iceberg(cfg: dict) -> None:
    """
    Iceberg REST 카탈로그에 네임스페이스와 테이블을 초기화합니다.

    IcebergWriter.init_table() 을 호출해 default 네임스페이스와
    inspection_results 테이블이 없으면 생성합니다.
    """
    print("\n--- Iceberg 테이블 초기화 ---")

    # Iceberg REST 연결 확인 함수 (list_namespaces 가 성공하면 연결된 것)
    def check():
        writer = IcebergWriter(cfg["iceberg"])
        writer.catalog.list_namespaces()
        return True

    wait_for_service("Iceberg REST", check)
    writer = IcebergWriter(cfg["iceberg"])
    writer.init_table()  # 네임스페이스 + 테이블 생성 (이미 있으면 건너뜀)
    print(f"[Iceberg] 테이블 준비 완료: {cfg['iceberg']['namespace']}.{cfg['iceberg']['table']}")


def setup_starrocks(cfg: dict) -> None:
    """
    StarRocks 에 Iceberg External Catalog 를 등록합니다.

    StarRocks 파드는 Kubernetes 클러스터 내부에서 실행됩니다.
    따라서 Iceberg REST 와 MinIO 의 주소로 K8s 내부 DNS 를 사용해야 합니다:
      - iceberg-rest.semiconductor-poc.svc.cluster.local:8181
      - minio.semiconductor-poc.svc.cluster.local:9000

    이 주소들은 config.yaml 의 k8s_internal 섹션에서 읽습니다.
    외부에서 접근하는 로컬 주소(localhost)와 구분해 반드시 내부 주소를 사용하세요.
    """
    print("\n--- StarRocks 카탈로그 등록 ---")
    sr = StarRocksClient(cfg["starrocks"])

    # StarRocks FE 파드가 준비될 때까지 최대 150초 대기 (최초 기동 시 느릴 수 있음)
    def check():
        return sr.ping()

    wait_for_service("StarRocks", check, retries=30, delay=5.0)

    # K8s 내부 서비스 주소 읽기 (없으면 외부 주소로 폴백)
    k8s = cfg.get("k8s_internal", {})
    internal_iceberg_uri = k8s.get("iceberg_rest_uri", cfg["iceberg"]["rest_uri"])
    internal_minio_endpoint = k8s.get(
        "minio_endpoint", f"http://{cfg['minio']['endpoint']}"
    )

    print(f"  Iceberg REST (내부): {internal_iceberg_uri}")
    print(f"  MinIO (내부):        {internal_minio_endpoint}")

    # StarRocks 에 Iceberg External Catalog 등록
    # 이미 등록된 경우 StarRocksClient.create_iceberg_catalog 가 자동으로 건너뜜
    sr.create_iceberg_catalog(
        catalog_name="iceberg_catalog",
        rest_uri=internal_iceberg_uri,
        warehouse=cfg["iceberg"]["warehouse"],
        minio_endpoint=internal_minio_endpoint,
        access_key=cfg["minio"]["access_key"],
        secret_key=cfg["minio"]["secret_key"],
    )


def main() -> None:
    """커맨드라인 인터페이스 — 각 초기화 단계를 선택적으로 건너뛸 수 있습니다."""
    parser = argparse.ArgumentParser(description="인프라 초기화 (MinIO / Iceberg / StarRocks)")
    parser.add_argument(
        "--config",
        type=str,
        default=os.path.join(ROOT, "configs", "config.yaml"),
        help="설정 파일 경로 (기본: configs/config.yaml)",
    )
    parser.add_argument(
        "--skip-minio",
        action="store_true",
        help="MinIO 초기화를 건너뜁니다 (이미 초기화된 경우 사용)",
    )
    parser.add_argument(
        "--skip-iceberg",
        action="store_true",
        help="Iceberg 테이블 초기화를 건너뜁니다",
    )
    parser.add_argument(
        "--skip-starrocks",
        action="store_true",
        help="StarRocks 카탈로그 등록을 건너뜁니다",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    print("=" * 50)
    print("반도체 검사 PoC 인프라 초기화 시작")
    print("=" * 50)

    # 각 단계를 순서대로 실행 (--skip-* 플래그로 개별 건너뜀 가능)
    if not args.skip_minio:
        setup_minio(cfg)

    if not args.skip_iceberg:
        setup_iceberg(cfg)

    if not args.skip_starrocks:
        setup_starrocks(cfg)

    # 초기화 완료 요약 및 접근 정보 출력
    print("\n" + "=" * 50)
    print("인프라 초기화 완료!")
    print("=" * 50)
    print(f"\nMinIO 콘솔: http://localhost:9001  (admin / password)")
    print(f"StarRocks: mysql -h 127.0.0.1 -P 9030 -u root")
    print(f"Iceberg REST: http://localhost:8181/v1/namespaces")


if __name__ == "__main__":
    main()
