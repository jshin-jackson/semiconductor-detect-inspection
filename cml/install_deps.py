"""
AMP bootstrap: Install Python dependencies and build the React frontend.

This script is run as a CML Job during AMP setup (task: install-deps).
It installs all Python packages from requirements.txt and produces the
production frontend bundle at frontend/dist/.
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


def build_frontend() -> None:
    print("=== Building React frontend ===")
    frontend_dir = os.path.join(ROOT, "frontend")

    subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)
    subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)

    dist_dir = os.path.join(frontend_dir, "dist")
    if os.path.isdir(dist_dir):
        print(f"Frontend build complete: {dist_dir}\n")
    else:
        raise RuntimeError(
            "Frontend build failed: frontend/dist directory not found."
        )


if __name__ == "__main__":
    install_python_deps()
    build_frontend()
    print("=== Install Dependencies complete ===")
