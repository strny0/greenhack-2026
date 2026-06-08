"""Make ``app.gridstats`` importable regardless of pytest's rootdir.

These tests are meant to run from the ``backend`` dir
(``python -m pytest app/gridstats/tests``), but to be robust to whatever
rootdir pytest infers, we prepend the backend directory (the parent of the
``app`` package) to ``sys.path`` here.
"""
from __future__ import annotations

import sys
from pathlib import Path

# tests/ -> gridstats/ -> app/ -> backend/
_BACKEND = Path(__file__).resolve().parents[3]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
