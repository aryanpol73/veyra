import os
import tempfile
from pathlib import Path

# Isolate tests from data/veyra.db. A file DB (not :memory:) so every pooled connection sees the same tables.
_tmp = Path(tempfile.mkdtemp(prefix="veyra-test-")) / "test.db"
os.environ["DB_URL"] = f"sqlite:///{_tmp.as_posix()}"
# Tests must never call a real LLM (a key in .env would otherwise be picked up): rules-only classification.
os.environ["LLM_API_KEY"] = ""
