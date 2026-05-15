"""
AMP bootstrap: Deploy K8s infrastructure (MinIO, Iceberg REST, StarRocks).

Attempts to deploy ./scripts/k8s-deploy.sh if kubectl is available.
If kubectl is unavailable (e.g. CML sandbox), skips gracefully — the
FastAPI app will fall back to local storage and SQLite automatically.

NOTE: sys.exit() is intentionally NOT used here because calling it inside
a CML/IPython kernel raises SystemExit which is displayed as an error even
when exit code is 0.  Instead the script simply returns after printing.
"""

import os
import subprocess

ROOT = None
try:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    ROOT = os.getcwd()


def kubectl_available() -> bool:
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


print("=== Deploy K8s Infrastructure (MinIO / Iceberg REST / StarRocks) ===")

if not kubectl_available():
    print("INFO: kubectl not available in this environment.")
    print("The app will use local storage (filesystem) and SQLite as fallbacks.")
    print("MinIO / Iceberg / StarRocks features will be disabled.")
else:
    print("kubectl found. Deploying to semiconductor-poc namespace ...")
    deploy_script = os.path.join(ROOT, "scripts", "k8s-deploy.sh")
    result = subprocess.run(["bash", deploy_script], cwd=ROOT)
    if result.returncode != 0:
        print(f"WARNING: k8s-deploy.sh exited with code {result.returncode}.")
        print("The API server will start in degraded mode.")
    else:
        print("K8s infrastructure deployed successfully.")

print("=== Deploy K8s Infrastructure complete ===")
