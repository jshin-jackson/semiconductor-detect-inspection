"""
AMP bootstrap: Initialize Iceberg table and StarRocks external catalog.

This script is run as a CML Job during AMP setup (task: setup-infra).
It connects to the MinIO / Iceberg REST / StarRocks services configured via
environment variables (or configs/config.yaml defaults) and creates:
  - default.inspection_results  Iceberg table in MinIO warehouse
  - iceberg_catalog              StarRocks external catalog (for SQL queries)

Requires MinIO and Iceberg REST to be reachable. If services are unavailable,
a warning is printed and the script exits with code 0 so the AMP can still
proceed (the FastAPI server handles missing services gracefully at runtime).
"""

import subprocess
import sys
import os

try:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    ROOT = os.getcwd()


if __name__ == "__main__":
    print("=== Setting up Iceberg table and StarRocks catalog ===")
    try:
        subprocess.run(
            [sys.executable, "scripts/setup_infra.py"],
            cwd=ROOT,
            check=True,
        )
        print("Infrastructure setup complete.\n")
    except subprocess.CalledProcessError as e:
        print(
            f"WARNING: Infrastructure setup returned non-zero exit code ({e.returncode}).\n"
            "This may happen if MinIO or Iceberg REST is not yet reachable.\n"
            "The API server will still start; retry POST /train or manual setup later.\n"
        )
    print("=== Setup Infrastructure step complete ===")
