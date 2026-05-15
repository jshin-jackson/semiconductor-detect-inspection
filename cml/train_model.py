"""
AMP bootstrap: Train the PaDiM anomaly detection model.

This script is run as a CML Job during AMP setup (task: train-model).
It trains PaDiM (ResNet18 backbone) on the normal wafer images generated
in the previous setup-data step.

The trained checkpoint is saved to weights/ and uploaded to MinIO if
MINIO_ENDPOINT is reachable. Pass --no-upload to skip the MinIO upload.

Expected runtime: ~1-2 minutes on CPU (200 normal images, n_features=100).
"""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


if __name__ == "__main__":
    print("=== Training PaDiM model ===")
    subprocess.run(
        [sys.executable, "scripts/train.py"],
        cwd=ROOT,
        check=True,
    )
    print("=== Train PaDiM Model complete ===")
