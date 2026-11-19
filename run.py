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
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
NPM = shutil.which("npm")
WINDOWS = os.name == "nt"


def sh(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.check_call(cmd, cwd=cwd, shell=WINDOWS and cmd[0] == NPM)


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def preflight() -> None:
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11+ is required (this is {sys.version.split()[0]}). On Windows try: py -3.11 run.py")
    if NPM is None:
        sys.exit("npm was not found. Install Node.js 20+ from https://nodejs.org and re-run.")
    if WINDOWS and len(str(ROOT)) > 110:
        print(f"WARNING: this folder path is {len(str(ROOT))} characters long. A LangGraph dependency ships a DLL that fails "
              "to load past Windows' 260-character limit; if you see 'filename or extension is too long', move the repo "
              "to a shorter path (e.g. C:\\Users\\you\\veyra).", flush=True)
    for port in (8000, 5173):
        if not port_free(port):
            sys.exit(f"Port {port} is already in use (an old Veyra server?). Stop it and re-run.")


def setup() -> None:
    if not VENV_PY.exists():
        sh([sys.executable, "-m", "venv", ".venv"], BACKEND)
        sh([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"], BACKEND)
        sh([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("Created .env from .env.example. Add your Groq key to LLM_API_KEY (the dashboard works without one, "
              "but agents and chat need it).", flush=True)
    sh([str(VENV_PY), "-m", "app.db.seed"], BACKEND)
    if not (FRONTEND / "node_modules").exists():
        sh([NPM, "install", "--no-fund", "--no-audit"], FRONTEND)


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
    setup()
    group = {} if WINDOWS else {"start_new_session": True}
    procs = [
        subprocess.Popen([str(VENV_PY), "-m", "uvicorn", "app.main:app", "--port", "8000"], cwd=BACKEND, **group),
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
