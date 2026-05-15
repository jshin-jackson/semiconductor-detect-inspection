"""
CML Application launcher for Semiconductor Defect Inspection.

Key insight (from Container Log analysis):
  CML's EngineInit.BrowserSvcs binds the EXTERNAL container IP
  (e.g. 100.100.233.242:8100), NOT 0.0.0.0.

  CML then routes Application URL traffic to localhost (127.0.0.1:8100).

  Therefore 127.0.0.1:8100 is FREE — binding to 127.0.0.1 instead of
  0.0.0.0 avoids the "address already in use" conflict entirely.

  This is the same pattern used by Cloudera's own AMPs:
    streamlit run app.py --server.port $CDSW_APP_PORT --server.address 127.0.0.1

Usage (CML Application task or local):
    python app.py
"""

import os
import subprocess
import sys

port = int(os.environ.get("CDSW_APP_PORT", "8000"))

print(f"[app] Starting Semiconductor Defect Inspection on 127.0.0.1:{port} ...")

subprocess.run(
    [
        sys.executable, "-m", "uvicorn", "api.main:app",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
)
