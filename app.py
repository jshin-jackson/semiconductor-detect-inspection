"""
CML Application launcher for Semiconductor Defect Inspection.

CML PBJ Workbench Architecture:
  - EngineInit.BrowserSvcs binds CDSW_APP_PORT (e.g. 8100) ~2 seconds
    before the user script runs, as part of the Application routing setup.
  - `fuser` is not available in CML runtime images.
  - This launcher uses /proc/net/tcp (pure Python, no external tools)
    to find and kill the CML infrastructure process holding the port,
    then immediately starts uvicorn before the port can be re-acquired.

Security note (public CML environment):
  - The app runs behind CML's authenticated reverse proxy.
  - No credentials are stored here; all secrets come from project
    environment variables (MINIO_SECRET_KEY, etc.).
"""

import os
import signal
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Port helpers (pure Python, no fuser/lsof required)
# ---------------------------------------------------------------------------

def _find_port_inode(port: int) -> str | None:
    """Return the socket inode (string) for the process LISTEN-ing on *port*."""
    hex_port = f'{port:04X}'
    for proto_file in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(proto_file) as f:
                for line in f.readlines()[1:]:   # skip header row
                    cols = line.split()
                    if len(cols) < 10:
                        continue
                    local_port = cols[1].split(':')[1]
                    state      = cols[3]          # 0A = LISTEN
                    if local_port.upper() == hex_port and state == '0A':
                        return cols[9]            # inode number
        except (FileNotFoundError, PermissionError):
            pass
    return None


def _pid_for_inode(inode: str) -> int | None:
    """Walk /proc/<pid>/fd to find which PID owns *inode*."""
    try:
        pids = [p for p in os.listdir('/proc') if p.isdigit()]
    except PermissionError:
        return None

    for pid in pids:
        try:
            for fd in os.listdir(f'/proc/{pid}/fd'):
                try:
                    link = os.readlink(f'/proc/{pid}/fd/{fd}')
                    if f'socket:[{inode}]' in link:
                        return int(pid)
                except (FileNotFoundError, PermissionError, OSError):
                    pass
        except (FileNotFoundError, PermissionError):
            pass
    return None


def _port_in_use(port: int) -> bool:
    """Return True if something is LISTEN-ing on *port*."""
    return _find_port_inode(port) is not None


def _free_port(port: int) -> bool:
    """
    Kill the process holding *port* via /proc (no fuser needed).
    Returns True if a process was found and signalled.
    """
    inode = _find_port_inode(port)
    if inode is None:
        return False

    pid = _pid_for_inode(inode)
    if pid is None:
        print(f"[app] Found socket on port {port} (inode {inode}) but could not identify PID.")
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[app] Sent SIGTERM to PID {pid} holding port {port}.")
        # Give it a moment to release the socket
        deadline = time.time() + 3.0
        while _port_in_use(port) and time.time() < deadline:
            time.sleep(0.2)
        if not _port_in_use(port):
            print(f"[app] Port {port} is now free.")
            return True
        # If SIGTERM wasn't enough, escalate to SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"[app] Sent SIGKILL to PID {pid}.")
            time.sleep(0.5)
        except ProcessLookupError:
            pass  # already gone
        return not _port_in_use(port)
    except (ProcessLookupError, PermissionError) as exc:
        print(f"[app] Could not kill PID {pid}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

port = int(os.environ.get("CDSW_APP_PORT", "8000"))

print(f"[app] Starting Semiconductor Defect Inspection on port {port} ...")

# CML's EngineInit.BrowserSvcs binds CDSW_APP_PORT a few seconds before the
# user script runs. Free it before uvicorn tries to bind.
if _port_in_use(port):
    print(f"[app] Port {port} is occupied — attempting to free it ...")
    freed = _free_port(port)
    if not freed:
        print(f"[app] WARNING: could not free port {port}; uvicorn may fail to bind.")
else:
    print(f"[app] Port {port} is free.")

# Run uvicorn in a subprocess (avoids asyncio nested-loop error in Jupyter kernel).
# Restart automatically on unexpected exit — up to MAX_RESTARTS times.
MAX_RESTARTS = 5
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
        print(f"[app] Server failed {MAX_RESTARTS} times — giving up.")
        break

    wait = min(5 * restart_count, 20)
    print(f"[app] Server exited (code {result.returncode}). "
          f"Restart {restart_count}/{MAX_RESTARTS} in {wait}s ...")
    time.sleep(wait)

    # Port may have been re-acquired by CML after we freed it; release again.
    if _port_in_use(port):
        print(f"[app] Port {port} re-occupied — freeing again ...")
        _free_port(port)
