import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import config, database, rag  # noqa: E402
import make_samples  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own empty database and upload folder."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    rag._cache.update(key=None, vec=None, matrix=None, chunks=[])
    database.init_db()
    yield


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    return make_samples.build(tmp_path_factory.mktemp("samples"))


@pytest.fixture
def upload(samples):
    from core import pipeline

    def _upload(key, actor="tester"):
        p = samples[key]
        return pipeline.process_upload(p.name, p.read_bytes(), actor)

    return _upload
