import os
import sys

# Same approach as the other tests: put researchAgent/ on the path so `research` imports.
# tests/security/ -> tests/ -> researchAgent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


import importlib.util

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def recorded_dir(tmp_path_factory):
    """Real flight and hotel recordings, built from the committed HTTP cache (no network), in a temp dir."""
    out = tmp_path_factory.mktemp("sandbox_data")
    spec = importlib.util.spec_from_file_location("build_sandbox_index", os.path.join(ROOT, "scripts", "build_sandbox_index.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUT = str(out)
    assert mod.main() == 0
    return out


@pytest.fixture
def with_recordings(recorded_dir, monkeypatch):
    """Point the sandbox at the recordings for one test (the store is cached per process, so reset it)."""
    from research import sandbox
    monkeypatch.setattr(sandbox, "DATA_DIR", str(recorded_dir))
    monkeypatch.setattr(sandbox, "_default", None)
    monkeypatch.delenv("TRAVAI_SANDBOX_DATA", raising=False)
    yield
    sandbox._default = None
