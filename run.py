"""One command to start Veyra:  python run.py
Starts FastAPI on :8000 and the Vite dashboard on :5173. Ctrl+C stops both (and their child processes).
First run: creates backend/.venv, installs deps, copies .env, seeds the DB, runs npm install.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"
NPM = shutil.which("npm")
WINDOWS = os.name == "nt"


def venv_python() -> Path | None:
    """Windows CPython uses Scripts/python.exe; MSYS2/MinGW and POSIX Pythons use bin/python(.exe)."""
    for rel in ("Scripts/python.exe", "bin/python.exe", "bin/python"):
        if (VENV / rel).exists():
            return VENV / rel
    return None


def sh(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.check_call(cmd, cwd=cwd, shell=WINDOWS and cmd[0] == NPM)


def port_free(port: int) -> bool:
    """Free on BOTH loopbacks: Vite binds IPv6 [::1] on Windows, uvicorn binds IPv4 127.0.0.1."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return False
        except OSError:  # family unsupported on this machine
            continue
    return True


def preflight() -> None:
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11+ is required (this is {sys.version.split()[0]}). On Windows try: py -3.11 run.py")
    if NPM is None:
        sys.exit("npm was not found. Install Node.js 20+ from https://nodejs.org and re-run.")
    if WINDOWS and ("msys" in sys.executable.lower() or "mingw" in sys.executable.lower()):
        print(f"WARNING: {sys.executable} is an MSYS2/MinGW Python; some packages may fail to install. "
              "The python.org installer (run with: py -3.11 run.py) is the tested setup.", flush=True)
    if WINDOWS and len(str(ROOT)) > 110:
        print(f"WARNING: this folder path is {len(str(ROOT))} characters long. A LangGraph dependency ships a DLL that fails "
              "to load past Windows' 260-character limit; if you see 'filename or extension is too long', move the repo "
              "to a shorter path (e.g. C:\\Users\\you\\veyra).", flush=True)
    for port in (8000, 5173):
        if not port_free(port):
            sys.exit(f"Port {port} is already in use (an old Veyra server?). Stop it and re-run.")


def setup() -> Path:
    py = venv_python()
    if py is None:
        sh([sys.executable, "-m", "venv", ".venv"], BACKEND)
        py = venv_python()
        if py is None:
            sys.exit(f"Created {VENV} but found no python inside it.")
        sh([str(py), "-m", "pip", "install", "--upgrade", "pip"], BACKEND)
        sh([str(py), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("Created .env from .env.example. Add your Groq key to LLM_API_KEY (the dashboard works without one, "
              "but agents and chat need it).", flush=True)
    sh([str(py), "-m", "app.db.seed"], BACKEND)
    if not (FRONTEND / "node_modules").exists():
        sh([NPM, "install", "--no-fund", "--no-audit"], FRONTEND)
    return py


def stop(p: subprocess.Popen) -> None:
    """Kill the whole tree: on Windows npm runs under cmd.exe, and terminate() would orphan node/esbuild."""
    if p.poll() is not None:
        return
    if WINDOWS:
        subprocess.call(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main() -> None:
    preflight()
    py = setup()
    group = {} if WINDOWS else {"start_new_session": True}
    procs = [
        subprocess.Popen([str(py), "-m", "uvicorn", "app.main:app", "--port", "8000"], cwd=BACKEND, **group),
        subprocess.Popen([NPM, "run", "dev", "--", "--strictPort"], cwd=FRONTEND, shell=WINDOWS, **group),
    ]
    print("\nVeyra  dashboard http://localhost:5173   API docs http://127.0.0.1:8000/docs   (Ctrl+C to stop)\n", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            try:
                procs[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        failed = [p for p in procs if p.poll() not in (None, 0)]
        if failed:
            print("A server exited unexpectedly; stopping the other one.", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            stop(p)


if __name__ == "__main__":
    main()
