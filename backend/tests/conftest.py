import os
import tempfile
from pathlib import Path

# Isolate tests from data/argus.db. A file DB (not :memory:) so every pooled connection sees the same tables.
_tmp = Path(tempfile.mkdtemp(prefix="argus-test-")) / "test.db"
os.environ["DB_URL"] = f"sqlite:///{_tmp.as_posix()}"
