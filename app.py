"""
CML Application launcher for Semiconductor Defect Inspection.

Cloudera AI sets CDSW_APP_PORT to the port this application must listen on.
This script starts the FastAPI server (which also serves the pre-built React
frontend as static files) bound to 0.0.0.0:CDSW_APP_PORT.

Usage (CML Application task or local):
    python app.py
"""

import os
import subprocess
import sys

port = int(os.environ.get("CDSW_APP_PORT", "8000"))

print(f"Starting Semiconductor Defect Inspection on port {port} ...")

subprocess.run(
    [
        sys.executable, "-m", "uvicorn", "api.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ],
    check=True,
)
