"""Make ``app`` importable regardless of pytest's rootdir.

Mirrors app/gridstats/tests/conftest.py: prepend the backend dir (the parent of
the ``app`` package) to sys.path. tests/ -> app/ -> backend/.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
