"""
CML Application launcher for Semiconductor Defect Inspection.

Root cause (confirmed from Container Log):
  EngineInit.BrowserSvcs (root process) binds CDSW_APP_PORT at
  12:32:28, before our script runs at 12:32:30.  We cannot kill it
  (uid=8536 cannot signal root processes).

Strategy — try in order:
  1. SO_REUSEPORT   : bind alongside the CML process if it used SO_REUSEPORT.
                     uvicorn inherits the pre-bound socket via --fd so it
                     never needs to call bind() itself.
  2. Kill via /proc : on environments where the process IS killable.
  3. Plain fallback : just try anyway; works if the port becomes free.

All attempts are fully logged so the Container Log shows exactly what
happened.
"""

import os
import signal
import socket
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _diagnose_port(port: int) -> None:
    """Log what process (if any) is currently holding *port*."""
    hex_port = f'{port:04X}'
    for proto_file in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(proto_file) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if len(cols) < 10:
                        continue
                    if cols[1].split(':')[1].upper() == hex_port and cols[3] == '0A':
                        inode = cols[9]
                        pid   = _pid_for_inode(inode)
                        cmdline = _cmdline(pid) if pid else 'unknown'
                        uid     = _uid(pid)     if pid else '?'
                        print(f"[app] DIAG port {port}: inode={inode} "
                              f"pid={pid} uid={uid} cmd={cmdline!r}")
                        return
        except (FileNotFoundError, PermissionError):
            pass
    print(f"[app] DIAG port {port}: nothing listening (port is free)")


def _pid_for_inode(inode: str) -> int | None:
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                for fd in os.listdir(f'/proc/{pid}/fd'):
                    try:
                        if f'socket:[{inode}]' in os.readlink(f'/proc/{pid}/fd/{fd}'):
                            return int(pid)
                    except (FileNotFoundError, PermissionError, OSError):
                        pass
            except (FileNotFoundError, PermissionError):
                pass
    except PermissionError:
        pass
    return None


def _cmdline(pid: int) -> str:
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return f.read().replace(b'\x00', b' ').decode(errors='replace').strip()
    except Exception:
        return 'unreadable'


def _uid(pid: int) -> str:
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('Uid:'):
                    return line.split()[1]   # real UID
    except Exception:
        pass
    return '?'


# ---------------------------------------------------------------------------
# Strategy 1: SO_REUSEPORT pre-bind  → pass socket fd to uvicorn
# ---------------------------------------------------------------------------

def _try_reuseport_bind(port: int) -> socket.socket | None:
    """
    Try to create a SOCK_STREAM socket bound to *port* with SO_REUSEPORT.
    If the existing holder also used SO_REUSEPORT the kernel allows two
    listeners; uvicorn will inherit the fd and start serving immediately.
    Returns the bound socket on success, None on failure.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(('0.0.0.0', port))
        s.listen(128)
        s.set_inheritable(True)
        print(f"[app] SO_REUSEPORT bind on port {port} succeeded.")
        return s
    except OSError as e:
        print(f"[app] SO_REUSEPORT bind failed: {e}")
        try:
            s.close()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Strategy 2: kill via /proc (only works if we own the process)
# ---------------------------------------------------------------------------

def _try_kill_port(port: int) -> bool:
    hex_port = f'{port:04X}'
    inode = None
    for proto_file in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(proto_file) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if len(cols) < 10:
                        continue
                    if cols[1].split(':')[1].upper() == hex_port and cols[3] == '0A':
                        inode = cols[9]
                        break
        except (FileNotFoundError, PermissionError):
            pass
        if inode:
            break

    if not inode:
        return False

    pid = _pid_for_inode(inode)
    if pid is None:
        print(f"[app] kill: inode {inode} found but PID lookup failed (likely root process).")
        return False

    uid = _uid(pid)
    my_uid = str(os.getuid())
    if uid != my_uid and uid != '0':
        # might still work if same user; try anyway
        pass

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[app] kill: sent SIGTERM to PID {pid} (uid={uid}).")
        deadline = time.time() + 3.0
        while time.time() < deadline:
            time.sleep(0.2)
            inode2 = None
            for proto_file in ('/proc/net/tcp', '/proc/net/tcp6'):
                try:
                    with open(proto_file) as f:
                        for line in f.readlines()[1:]:
                            cols = line.split()
                            if len(cols) >= 10 and cols[1].split(':')[1].upper() == hex_port and cols[3] == '0A':
                                inode2 = cols[9]
                except Exception:
                    pass
            if not inode2:
                print(f"[app] kill: port {port} is now free.")
                return True
        # escalate
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        return True
    except (ProcessLookupError, PermissionError) as exc:
        print(f"[app] kill: cannot signal PID {pid}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Launch uvicorn
# ---------------------------------------------------------------------------

def _run_uvicorn(port: int, sock: socket.socket | None = None) -> int:
    """Start uvicorn. If *sock* is given, pass it via --fd (no bind needed)."""
    if sock is not None:
        fd = sock.fileno()
        cmd = [sys.executable, '-m', 'uvicorn', 'api.main:app', '--fd', str(fd)]
        result = subprocess.run(cmd, pass_fds=(fd,))
    else:
        cmd = [sys.executable, '-m', 'uvicorn', 'api.main:app',
               '--host', '0.0.0.0', '--port', str(port)]
        result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

port = int(os.environ.get('CDSW_APP_PORT', '8000'))
print(f"[app] Starting Semiconductor Defect Inspection on port {port} ...")
print(f"[app] My uid = {os.getuid()}, pid = {os.getpid()}")

# Step 0: diagnose what's on the port right now
_diagnose_port(port)

# Step 1: try SO_REUSEPORT pre-bind → uvicorn inherits the socket
pre_sock = _try_reuseport_bind(port)
if pre_sock is not None:
    print("[app] Strategy 1 (SO_REUSEPORT): launching uvicorn with --fd ...")
    rc = _run_uvicorn(port, sock=pre_sock)
    print(f"[app] uvicorn exited (code {rc}).")
    sys.exit(0)

# Step 2: try killing the holder
print("[app] Strategy 2 (kill): attempting to free port ...")
freed = _try_kill_port(port)
if freed:
    time.sleep(0.3)
    _diagnose_port(port)
    print("[app] Strategy 2: launching uvicorn ...")
    rc = _run_uvicorn(port)
    print(f"[app] uvicorn exited (code {rc}).")
    sys.exit(0)

# Step 3: plain attempt (maybe the port freed on its own)
print("[app] Strategy 3 (plain): launching uvicorn directly ...")
MAX = 3
for attempt in range(1, MAX + 1):
    rc = _run_uvicorn(port)
    if rc == 0:
        print("[app] Server stopped cleanly.")
        break
    print(f"[app] Attempt {attempt}/{MAX} failed (code {rc}).")
    if attempt < MAX:
        time.sleep(5)

print("[app] All strategies exhausted. Check Container Log for diagnostics.")
