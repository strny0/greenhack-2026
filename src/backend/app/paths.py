"""Single source of truth for dataset filesystem paths.

Deliberately tiny and side-effect free — only stdlib, no ``load_dotenv``, no
other ``app.*`` imports — so both ``app.config`` and the standalone
``app.gridstats.*`` (which must run without pulling in the full app config) can
share one definition of where the data lives.

Two independent concerns:
  * the large, downloaded/mounted dataset **payload** — ``GRID_DATA_DIR``;
  * the small, version-controlled operator **overrides** that ship with the
    app — ``GRID_OVERRIDES_DIR``.
Both default under the repo-root ``dataset/`` that
``scripts/download_dataset.{sh,ps1}`` populate.
"""
from __future__ import annotations

import os
from pathlib import Path

# app/paths.py -> parents[3] is the repo root (app, backend, src, <repo>).
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "dataset" / "data"
DEFAULT_OVERRIDES_DIR = REPO_ROOT / "dataset" / "overrides"


def data_dir(*extra_env_vars: str) -> Path:
    """Resolve the dataset payload dir (the inner ``data/`` directory).

    Checks ``extra_env_vars`` in order first (callers pass e.g.
    ``"GRIDSTATS_DATA_DIR"`` for a component-specific override), then the shared
    ``GRID_DATA_DIR``, then falls back to the repo-root default.
    """
    for var in (*extra_env_vars, "GRID_DATA_DIR"):
        value = os.environ.get(var)
        if value:
            return Path(value)
    return DEFAULT_DATA_DIR


def overrides_dir() -> Path:
    """Resolve the operator overrides dir (``GRID_OVERRIDES_DIR`` or default)."""
    value = os.environ.get("GRID_OVERRIDES_DIR")
    return Path(value) if value else DEFAULT_OVERRIDES_DIR
