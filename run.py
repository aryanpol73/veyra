"""One command to start Veyra:  python run.py
Starts FastAPI on :8000 and the Vite dashboard on :5173. Ctrl+C stops both.
First run: creates backend/.venv, installs deps, seeds the DB, runs npm install.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
NPM = shutil.which("npm") or "npm"


def sh(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(map(str, cmd)))
    subprocess.check_call(cmd, cwd=cwd)


def setup() -> None:
    if not VENV_PY.exists():
        sh([sys.executable, "-m", "venv", ".venv"], BACKEND)
        sh([str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("Created .env from .env.example. Add your Groq/Ollama key to LLM_API_KEY.")
    sh([str(VENV_PY), "-m", "app.db.seed"], BACKEND)
    if not (FRONTEND / "node_modules").exists():
        sh([NPM, "install"], FRONTEND)


def main() -> None:
    setup()
    procs = [
        subprocess.Popen([str(VENV_PY), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], cwd=BACKEND),
        subprocess.Popen([NPM, "run", "dev"], cwd=FRONTEND, shell=os.name == "nt"),
    ]
    print("\nVeyra  API http://127.0.0.1:8000/docs   Dashboard http://localhost:5173\n")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
