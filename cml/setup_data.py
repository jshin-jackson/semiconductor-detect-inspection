"""
AMP bootstrap: Generate synthetic wafer images for training and testing.

This script is run as a CML Job during AMP setup (task: setup-data).
It creates:
  - data/train/good/    200 normal wafer images for PaDiM training
  - data/test/good/      30 normal wafer images for evaluation
  - data/test/defect/    30 synthetic defect images (scratch/spot/contamination)

No real equipment images are required.
"""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def generate_normal_images() -> None:
    print("=== Generating normal wafer images ===")
    subprocess.run(
        [sys.executable, "scripts/generate_normal_images.py"],
        cwd=ROOT,
        check=True,
    )
    print("Normal images generated.\n")


def generate_defect_images() -> None:
    print("=== Generating defect wafer images ===")
    subprocess.run(
        [sys.executable, "scripts/generate_defects.py"],
        cwd=ROOT,
        check=True,
    )
    print("Defect images generated.\n")


if __name__ == "__main__":
    generate_normal_images()
    generate_defect_images()
    print("=== Generate Synthetic Data complete ===")
