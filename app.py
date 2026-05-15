"""
CML Application launcher for Semiconductor Defect Inspection.

Cloudera AI sets CDSW_APP_PORT to the port this application must listen on.
CML PBJ Workbench runs scripts inside a Jupyter kernel that already has a
running asyncio event loop, so uvicorn.run() (which calls asyncio.run())
cannot be used directly. Instead, uvicorn is launched as a subprocess so
that it runs outside the existing event loop.

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
