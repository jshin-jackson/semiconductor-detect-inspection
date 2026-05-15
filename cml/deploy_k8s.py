"""
AMP bootstrap: Deploy K8s infrastructure (MinIO, Iceberg REST, StarRocks).

This script runs ./scripts/k8s-deploy.sh from within the CML environment.
It requires that kubectl is available and that the CML service account has
permission to create resources in the semiconductor-poc namespace.

If kubectl is unavailable or permissions are insufficient, the script exits
with code 0 (non-fatal) so the remaining AMP steps continue. The FastAPI
application handles missing services gracefully.
"""

import os
import subprocess
import sys

ROOT = try_root = None
try:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    ROOT = os.getcwd()


def kubectl_available() -> bool:
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client", "--short"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


if __name__ == "__main__":
    print("=== Deploy K8s Infrastructure (MinIO / Iceberg REST / StarRocks) ===")

    if not kubectl_available():
        print("WARNING: kubectl not found or not reachable.")
        print("Skipping K8s deployment — services must be running externally.")
        print("Set MINIO_ENDPOINT / ICEBERG_REST_URI / STARROCKS_HOST env vars")
        print("to point to externally accessible service endpoints.")
        sys.exit(0)

    print("kubectl found. Deploying to semiconductor-poc namespace ...")
    deploy_script = os.path.join(ROOT, "scripts", "k8s-deploy.sh")
    result = subprocess.run(
        ["bash", deploy_script],
        cwd=ROOT,
    )

    if result.returncode != 0:
        print(f"WARNING: k8s-deploy.sh exited with code {result.returncode}.")
        print("The API server will start in degraded mode (no MinIO / StarRocks).")
    else:
        print("K8s infrastructure deployed successfully.")

    print("=== Deploy K8s Infrastructure complete ===")
