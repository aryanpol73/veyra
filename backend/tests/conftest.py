import os
import tempfile
from pathlib import Path

# Isolate tests from data/veyra.db. A file DB (not :memory:) so every pooled connection sees the same tables.
_tmp = Path(tempfile.mkdtemp(prefix="veyra-test-")) / "test.db"
os.environ["DB_URL"] = f"sqlite:///{_tmp.as_posix()}"
# Tests must never call a real LLM (a key in .env would otherwise be picked up): rules-only classification.
os.environ["LLM_API_KEY"] = ""
# ...and never inherit the developer's real secrets/keys from .env (env vars beat the .env file).
for _k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_API_KEY",
           "VEYRA_ADMIN_PASSWORD", "VEYRA_SECRET_KEY", "LLM_STRONG_CHAIN", "LLM_FAST_CHAIN", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY"):
    os.environ[_k] = ""
os.environ["OLLAMA_LOCAL"] = "false"
os.environ["VEYRA_ENV"] = "development"
os.environ["SCHEDULER_ENABLED"] = "false"
