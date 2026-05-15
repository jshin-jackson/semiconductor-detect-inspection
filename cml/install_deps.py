"""
AMP bootstrap: Install Python dependencies.

This script is run as a CML Job during AMP setup (task: install-deps).
It installs all Python packages from requirements.txt.

The React frontend is pre-built and committed to the repository at
frontend/dist/, so no Node.js or npm is required in the CML runtime.
"""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_python_deps() -> None:
    print("=== Installing Python dependencies ===")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=ROOT,
        check=True,
    )
    print("Python dependencies installed.\n")


def verify_frontend() -> None:
    """Confirm the pre-built frontend is present in the repository."""
    dist_dir = os.path.join(ROOT, "frontend", "dist")
    index = os.path.join(dist_dir, "index.html")
    if os.path.isfile(index):
        print(f"Frontend bundle found: {dist_dir}\n")
    else:
        print(
            "WARNING: frontend/dist/index.html not found. "
            "The web UI will not be available until the frontend is built.\n"
        )


if __name__ == "__main__":
    install_python_deps()
    verify_frontend()
    print("=== Install Dependencies complete ===")
