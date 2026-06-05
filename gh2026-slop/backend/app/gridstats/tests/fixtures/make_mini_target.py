"""Regenerate the tiny committed test bundle ``mini_target/`` from the full bundle.

The full ``target/`` bundle (year of hours, gitignored) is trimmed to a ~2-week
window so the tests stay hermetic and fast (pandas + pyarrow only — no dataset,
no pandapower). The window is chosen to include the two notable days the tests
narrate:

    2024-09-08  year-peak line loading
    2024-09-13  wind-surprise day (driver=wind, large de-biased sigma)

Run from the ``backend`` dir with the analysis venv python::

    python -m app.gridstats.tests.fixtures.make_mini_target

or directly::

    python app/gridstats/tests/fixtures/make_mini_target.py

What gets trimmed vs copied
---------------------------
* Time-series files (metrics, branch_loadings, residuals, forecast, realtime)
  are sliced to the window [WINDOW_START, WINDOW_END] and rewritten as parquet.
* Stratified band tables (branch_pct90/95/99) are YEAR-derived constants — they
  are copied byte-for-byte so de-biasing / normal-band lookups still work, and so
  the exact MultiIndex parquet encoding is preserved.
* baselines.json is copied with its ``forecast_error``/``residual_std`` (year
  constants) intact. The dataset bounds (``first_ts``/``last_ts``) are KEPT AS-IS
  (the real full-year window). insights._bounds() reads the servable range from
  these baseline fields, NOT from the metrics index, so keeping the real bounds
  makes the fixture self-consistent: in-window Sept timestamps validate, a 2030
  timestamp is out-of-range, and an in-bounds-but-untrimmed day (e.g. 2024-01-01)
  falls through to plan_adherence's "no data in dataset window" error branch.
  Both out-of-range paths therefore return an {"error": ...} dict as the tests
  expect.
* interesting_days.csv is filtered to the window (header kept). load_bundle does
  not read it, but it is part of the bundle schema, so the fixture carries it.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

# Source full bundle (gitignored) and destination fixture dir.
SRC = Path(__file__).resolve().parents[2] / "target"
DST = Path(__file__).resolve().parent / "mini_target"

# Inclusive ~2-week window: includes 2024-09-08 (peak loading) and 2024-09-13 (wind).
WINDOW_START = "2024-09-08T00:00:00"
WINDOW_END = "2024-09-22T23:00:00"

# Sliced to the window.
TIME_SERIES = ["metrics", "branch_loadings", "residuals", "forecast", "realtime"]
# Copied verbatim (year-derived constants; preserve exact MultiIndex parquet form).
COPY_AS_IS = ["branch_pct90.parquet", "branch_pct95.parquet", "branch_pct99.parquet"]


def main() -> None:
    if not (SRC / "metrics.parquet").exists():
        raise SystemExit(
            f"Full bundle not found at {SRC}. Build it first:\n"
            f"    python -m app.gridstats.build"
        )

    DST.mkdir(parents=True, exist_ok=True)

    lo = pd.Timestamp(WINDOW_START)
    hi = pd.Timestamp(WINDOW_END)

    # --- time-series files: slice the datetime index to the window ---
    for name in TIME_SERIES:
        df = pd.read_parquet(SRC / f"{name}.parquet")
        sliced = df.loc[(df.index >= lo) & (df.index <= hi)]
        sliced.to_parquet(DST / f"{name}.parquet")
        print(f"{name}: {df.shape[0]} -> {sliced.shape[0]} rows")

    # --- stratified band tables + baselines.json: copy as-is ---
    for fname in COPY_AS_IS:
        shutil.copy2(SRC / fname, DST / fname)
        print(f"copied {fname}")
    shutil.copy2(SRC / "baselines.json", DST / "baselines.json")
    print("copied baselines.json (year bounds kept as-is)")

    # --- interesting_days.csv: filter rows to the window, keep header ---
    days = pd.read_csv(SRC / "interesting_days.csv", index_col=0, parse_dates=True)
    days_win = days.loc[(days.index >= lo.normalize()) & (days.index <= hi.normalize())]
    days_win.to_csv(DST / "interesting_days.csv")
    print(f"interesting_days.csv: {len(days)} -> {len(days_win)} rows")

    total = sum(p.stat().st_size for p in DST.iterdir() if p.is_file())
    print(f"\nmini_target written to: {DST}")
    print(f"total size: {total / 1024:.1f} KiB ({total} bytes)")


if __name__ == "__main__":
    main()
