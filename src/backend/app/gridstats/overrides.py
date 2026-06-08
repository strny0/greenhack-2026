"""Current-hour actuals override for scoring a hypothetical (simulated) hour
against the precomputed normal baseline.

When a failure simulation is active, the insight functions score the SCENARIO
hour's actuals against the REAL normal bands (percentiles, residual std). This
dataclass carries those scenario actuals; it is built from a scenario StateFrame
by the agent layer and substituted for the recorded actuals at one hour. The
baseline bundle is never rebuilt.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HourActualsOverride:
    timestamp: str  # ISO hour this override applies to
    total_load_mw: float
    total_gen_mw: float
    max_line_loading_pct: float
    slack_mw: float
    branch_loadings: dict[str, float] = field(default_factory=dict)  # branch id -> loading %
