"""
CML Application launcher for Semiconductor Defect Inspection.

Cloudera AI sets CDSW_APP_PORT to the port this application must listen on.
This script starts uvicorn in-process (not as a subprocess) so that CML's
process monitor tracks the actual server, and SIGTERM is handled cleanly.

Usage (CML Application task or local):
    python app.py
"""

import os
import uvicorn

port = int(os.environ.get("CDSW_APP_PORT", "8000"))

print(f"Starting Semiconductor Defect Inspection on port {port} ...")

uvicorn.run(
    "api.main:app",
    host="0.0.0.0",
    port=port,
    log_level="info",
)
