#!/usr/bin/env bash
# Kubernetes 인프라 배포 스크립트
# Docker Desktop Kubernetes (semiconductor-poc 네임스페이스)
#
# 사용법:
#   ./scripts/k8s-deploy.sh           # 전체 배포
#   ./scripts/k8s-deploy.sh --delete  # 모든 리소스 삭제
#   ./scripts/k8s-deploy.sh --status  # 파드 상태 확인

set -euo pipefail

NAMESPACE="semiconductor-poc"
K8S_DIR="$(cd "$(dirname "$0")/../k8s" && pwd)"

# ─── 색상 출력 ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── kubectl 확인 ────────────────────────────────────────────────────────────
command -v kubectl >/dev/null 2>&1 || error "kubectl 이 설치되어 있지 않습니다."

# ─── 컨텍스트 확인 (Docker Desktop) ─────────────────────────────────────────
CURRENT_CTX=$(kubectl config current-context 2>/dev/null || echo "none")
info "현재 kubectl 컨텍스트: $CURRENT_CTX"
if [[ "$CURRENT_CTX" != "docker-desktop" && "$CURRENT_CTX" != *"docker"* ]]; then
  warn "현재 컨텍스트가 docker-desktop 이 아닙니다: $CURRENT_CTX"
  warn "계속 진행하려면 Enter 를 누르세요 (Ctrl-C 로 중단)."
  read -r
fi

# ─── 삭제 모드 ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--delete" ]]; then
  warn "모든 리소스를 삭제합니다: 네임스페이스 $NAMESPACE"
  kubectl delete namespace "$NAMESPACE" --ignore-not-found
  info "삭제 완료."
  exit 0
fi

# ─── 상태 확인 모드 ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--status" ]]; then
  echo ""
  info "=== 파드 상태 ==="
  kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || echo "네임스페이스 없음"
  echo ""
  info "=== 서비스 ==="
  kubectl get svc -n "$NAMESPACE" 2>/dev/null || echo "서비스 없음"
  echo ""
  info "=== 잡 ==="
  kubectl get jobs -n "$NAMESPACE" 2>/dev/null || echo "잡 없음"
  exit 0
fi

# ─── 배포 시작 ────────────────────────────────────────────────────────────────
echo ""
info "============================================================"
info "  반도체 결함 검사 PoC — Kubernetes 인프라 배포"
info "  네임스페이스: $NAMESPACE"
info "============================================================"
echo ""

# 1. 네임스페이스
info "1/6  네임스페이스 생성..."
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

# 2. MinIO
info "2/6  MinIO 배포..."
kubectl apply -f "$K8S_DIR/01-minio.yaml"

# 3. MinIO 준비 대기
info "     MinIO 파드 준비 대기 중 (최대 120초)..."
kubectl rollout status deployment/minio -n "$NAMESPACE" --timeout=120s

# 4. MinIO 버킷 초기화 Job
info "3/6  MinIO 버킷 초기화 Job 실행..."
# 기존 완료된 Job 삭제 후 재생성
kubectl delete job minio-init -n "$NAMESPACE" --ignore-not-found
kubectl apply -f "$K8S_DIR/05-minio-init-job.yaml"
info "     Job 완료 대기 중 (최대 120초)..."
kubectl wait --for=condition=complete job/minio-init -n "$NAMESPACE" --timeout=120s \
  && info "     MinIO 버킷 초기화 완료." \
  || warn "     Job 완료 확인 실패. kubectl logs job/minio-init -n $NAMESPACE 로 확인하세요."

# 5. Iceberg REST
info "4/6  Iceberg REST 카탈로그 배포..."
kubectl apply -f "$K8S_DIR/02-iceberg-rest.yaml"

# 6. StarRocks FE
info "5/6  StarRocks FE 배포..."
kubectl apply -f "$K8S_DIR/03-starrocks-fe.yaml"
info "     StarRocks FE 준비 대기 중 (최대 180초)..."
kubectl rollout status deployment/starrocks-fe -n "$NAMESPACE" --timeout=180s

# 7. StarRocks BE
info "6/6  StarRocks BE 배포..."
kubectl apply -f "$K8S_DIR/04-starrocks-be.yaml"

echo ""
info "============================================================"
info "  배포 완료! 서비스가 모두 준비되는 데 1~2분 소요됩니다."
info "============================================================"
echo ""
info "파드 상태 확인:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo ""
info "로컬 호스트 접근 포트 (Docker Desktop LoadBalancer):"
echo "  MinIO API    : http://localhost:9000"
echo "  MinIO 콘솔  : http://localhost:9001  (admin / password)"
echo "  Iceberg REST : http://localhost:8181"
echo "  StarRocks FE : localhost:9030  (mysql -h 127.0.0.1 -P 9030 -u root)"
echo "  StarRocks BE : http://localhost:8040"
echo ""
info "다음 단계:"
echo "  python scripts/setup_infra.py      # Iceberg 테이블 + StarRocks 카탈로그 초기화"
echo "  python scripts/train.py            # PaDiM 모델 학습"
echo "  uvicorn api.main:app --reload      # FastAPI 서버 시작"
echo ""
info "전체 삭제:"
echo "  ./scripts/k8s-deploy.sh --delete"
