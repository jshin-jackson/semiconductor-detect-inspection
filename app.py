"""
CML Application launcher for Semiconductor Defect Inspection.

Cloudera AI (CML) sets CDSW_APP_PORT to the port this Application must
listen on. CML's PBJ Workbench runs scripts inside a Jupyter kernel, so:

  1. uvicorn.run() is forbidden (asyncio.run() cannot be nested).
  2. CML may start this script more than once (startup retry / health check),
     causing "address already in use" on the second attempt.

This launcher handles both issues:
  - Detects and frees any process already occupying the port before binding.
  - Wraps uvicorn in a subprocess (separate process, its own event loop).
  - Restarts uvicorn automatically on unexpected exit.
  - Never raises an unhandled exception (CML interprets any non-zero exit
    as Application failure even when another instance is healthy).

Security note (public CML environment):
  - The app binds to 0.0.0.0 but is only reachable through CML's
    authenticated reverse proxy, which enforces SSO/token checks.
  - No credentials are stored here; all secrets come from environment
    variables set in the CML project (MINIO_SECRET_KEY, etc.).
"""

import os
import socket
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def _port_in_use(port: int) -> bool:
    """Return True if something is already bound to *port* on this host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def _free_port(port: int) -> None:
    """
    Kill any process that holds *port* open.

    Uses `fuser` (available in all CML runtime images).
    Waits briefly so the OS releases the socket before we re-bind.
    """
    try:
        subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        # Wait for TIME_WAIT sockets to drain (up to 2 s)
        deadline = time.time() + 2.0
        while _port_in_use(port) and time.time() < deadline:
            time.sleep(0.2)
    except Exception as exc:
        print(f"[app] WARNING: could not free port {port}: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

port = int(os.environ.get("CDSW_APP_PORT", "8000"))

print(f"[app] Starting Semiconductor Defect Inspection on port {port} ...")

# Ensure a clean port before we try to bind.
# CML sometimes runs this script twice (startup probe + actual launch),
# which would cause "address already in use" on the second invocation.
if _port_in_use(port):
    print(f"[app] Port {port} is occupied — releasing before startup ...")
    _free_port(port)
    if _port_in_use(port):
        print(f"[app] WARNING: port {port} still in use after release attempt; uvicorn may fail to bind.")

# Run uvicorn in a subprocess (avoids asyncio.run() nested-loop error).
# Restart automatically on unexpected exit so transient errors don't
# permanently kill the Application.
MAX_RESTARTS = 10
restart_count = 0

while True:
    result = subprocess.run(
        [
            sys.executable, "-m", "uvicorn", "api.main:app",
            "--host", "0.0.0.0",
            "--port", str(port),
        ]
    )

    if result.returncode == 0:
        print("[app] Server stopped cleanly.")
        break

    restart_count += 1
    if restart_count >= MAX_RESTARTS:
        print(f"[app] Server failed {MAX_RESTARTS} times in a row — giving up.")
        break

    wait = min(5 * restart_count, 30)
    print(f"[app] Server exited (code {result.returncode}). "
          f"Restart {restart_count}/{MAX_RESTARTS} in {wait}s ...")
    time.sleep(wait)

    # Free port again in case the previous uvicorn left it in TIME_WAIT
    if _port_in_use(port):
        _free_port(port)
