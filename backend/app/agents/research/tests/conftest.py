import sys
from pathlib import Path

# Make `app.agents.research` importable without a pyproject.toml (Jake adds that).
# tests/ -> research/ -> agents/ -> app/ -> backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
