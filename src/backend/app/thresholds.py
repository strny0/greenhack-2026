"""Alert threshold defaults — the single source of truth for the numeric
defaults shared by the runtime app and the offline gridstats library.

Like app.paths, this is a tiny, stdlib-only, side-effect-free leaf so
app.gridstats.* can share it without pulling in app.config's heavier setup.
app.config layers GRID_* environment overrides on top of these defaults for the
running service; gridstats uses the defaults directly (its bundle is built
offline, before any per-deployment tuning).
"""
from __future__ import annotations

# Line loading (% of thermal rating).
LINE_LOADING_WARN = 75.0
LINE_LOADING_ALERT = 90.0

# Bus voltage is judged against each bus's OWN rated band (min_vm_pu/max_vm_pu
# from the dataset); coming within this per-unit margin of either limit is a
# warning.
VOLTAGE_WARN_MARGIN = 0.01
