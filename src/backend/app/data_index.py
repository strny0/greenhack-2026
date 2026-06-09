"""Catalog of every data file the ``run_python`` sandbox (and the agent) can reach.

Single source of truth for *where the data lives and what is in it*, so:

* the sandbox parent (:mod:`app.sandbox`) hands the child one path map instead of
  hard-coding paths in two places, and
* the ``run_python`` tool can tell the model what is available — "so it knows
  where to find stuff" — via a compact, self-describing catalog passed into the
  script namespace as ``catalog``.

Three tiers are indexed:

* **raw dataset payload** — static topology tables, the realtime time-series, the
  day-ahead forecast series, fuel prices, and the hourly snapshot files
  (resolved from :mod:`app.config`);
* **precomputed gridstats bundle** — the seasonal/statistical parquets under
  ``app.gridstats.config.TARGET_DIR`` (system metrics, per-branch loadings,
  stratified normal bands, STL residuals, the interesting-days ranking, …).

Each entry is a :class:`DataSource`. ``paths_map`` returns the flat
``name -> path`` map the child loads its convenience tables from;
``catalog_records`` returns the json-able catalog handed to the sandbox child;
``catalog_text`` renders the same thing for a prompt / tool docstring.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import config
from .gridstats import config as gs_config


@dataclass(frozen=True)
class DataSource:
    """One catalogued data location.

    ``fmt`` is one of ``csv`` | ``parquet`` | ``json`` | ``csv-dir`` | ``json-dir``.
    ``lazy`` flags a file too large to load whole (filter it first). ``helper``
    names the in-sandbox convenience accessor, when one exists.
    """

    key: str
    path: str
    fmt: str
    description: str
    columns: list[str] = field(default_factory=list)
    lazy: bool = False
    helper: str = ""


def catalog() -> list[DataSource]:
    """Every data source available to the sandbox, in a sensible reading order."""
    static = config.STATIC_DIR
    realtime = config.REALTIME_DIR
    target = gs_config.TARGET_DIR
    return [
        # --- static topology (small, load eagerly) --------------------------
        DataSource(
            "buses", str(static / "buses.csv"), "csv",
            "Static bus/substation table.",
            ["bus_name", "region", "in_service", "v_rated_kv", "is_slack",
             "min_v_pu", "max_v_pu", "x_coordinate", "y_coordinate"],
            helper="buses",
        ),
        DataSource(
            "branches", str(static / "branches.csv"), "csv",
            "Static branch (line/transformer) table.",
            ["branch_name", "from_bus", "to_bus", "parallel", "in_service",
             "r_ohm", "x_ohm", "b_µs", "trafo_ratio_rel", "max_i_ka"],
            helper="branches",
        ),
        DataSource(
            "gens", str(static / "gens.csv"), "csv",
            "Static generator table (one row per generating unit).",
            ["gen_name", "bus_name", "opt_category", "max_p_mw", "min_p_mw"],
            helper="gens",
        ),
        DataSource(
            "loads", str(static / "loads.csv"), "csv",
            "Static load table (load -> bus mapping).",
            ["load_name", "bus_name"],
            helper="loads",
        ),
        DataSource(
            "bus_coordinates", str(static / "bus_coordinates.csv"), "csv",
            "Schematic x/y and lat/lon per bus.",
            ["bus_name", "x_coordinate", "y_coordinate", "de_lat", "de_lon",
             "real_lat", "real_lon"],
        ),
        # --- realtime time-series (huge — filter before loading) ------------
        DataSource(
            "gens_ts", str(realtime / "gens_ts.csv"), "csv",
            "Per-generator hourly realtime dispatch for all of 2024 (~244 MB).",
            ["datetime", "gen_name", "in_service", "p_mw", "max_q_mvar",
             "min_q_mvar", "max_p_mw", "min_p_mw"],
            lazy=True, helper="gen_dispatch(gen_name, start, end)",
        ),
        DataSource(
            "loads_ts", str(realtime / "loads_ts.csv"), "csv",
            "Per-load hourly realtime demand for all of 2024 (large).",
            ["datetime", "load_name", "in_service", "p_mw", "q_mvar"],
            lazy=True, helper="load_demand(load_name, start, end)",
        ),
        DataSource(
            "fuel_prices", str(config.DATA_DIR / "other" / "Fuel prices 2024.csv"),
            "csv", "Daily 2024 fuel prices by region (coal/gas/biomass/oil/geo).",
            ["Datetime", "Coal R1", "Natural Gas R1", "..."],
            helper="fuel_prices()",
        ),
        # --- day-ahead forecast series ("the plan") -------------------------
        DataSource(
            "da_solar", str(config.FORECASTS_DA_SOLAR), "csv-dir",
            "Day-ahead solar forecast, one SolarNN DA.csv per unit "
            "(columns DATETIME, value in MW).",
        ),
        DataSource(
            "da_wind", str(config.FORECASTS_DA_WIND), "csv-dir",
            "Day-ahead wind forecast, one WindNN DA.csv per unit.",
        ),
        DataSource(
            "da_load", str(config.FORECASTS_DA_LOAD), "csv-dir",
            "Day-ahead load forecast, one LoadRn DA.csv per region (r1/r2/r3).",
        ),
        DataSource(
            "snapshots", str(config.SNAPSHOTS_DIR), "json-dir",
            "Hourly solved-grid snapshot JSON files (8760 of them). Prefer the "
            "preloaded `nodes`/`lines` for the viewed hour over re-reading these.",
        ),
        # --- precomputed gridstats bundle (read via gridstats('name')) ------
        DataSource(
            "gs_metrics", str(target / "metrics.parquet"), "parquet",
            "Per-hour system metrics (datetime index) — the statistical backbone.",
            ["total_load_mw", "total_gen_mw", "slack_mw", "max_line_loading_pct",
             "n_overloaded_lines", "converged"],
            helper="gridstats('metrics')",
        ),
        DataSource(
            "gs_branch_loadings", str(target / "branch_loadings.parquet"), "parquet",
            "Per-hour loading_percent for every branch (datetime index, branch_* "
            "columns). The full year of loadings without re-solving any hour.",
            helper="gridstats('branch_loadings')",
        ),
        DataSource(
            "gs_forecast", str(target / "forecast.parquet"), "parquet",
            "Day-ahead plan aligned to the metrics index.",
            ["load_r1_mw", "load_r2_mw", "load_r3_mw", "load_total_mw",
             "solar_mw", "wind_mw"],
            helper="gridstats('forecast')",
        ),
        DataSource(
            "gs_realtime", str(target / "realtime.parquet"), "parquet",
            "Actuals aligned to the metrics index (plan-vs-actual pairs with forecast).",
            ["load_mw", "solar_mw", "wind_mw", "other_gen_mw", "gen_total_mw"],
            helper="gridstats('realtime')",
        ),
        DataSource(
            "gs_residuals", str(target / "residuals.parquet"), "parquet",
            "STL seasonal-trend residuals (deviation from seasonal norm).",
            ["load", "max_loading", "solar", "wind", "slack"],
            helper="gridstats('residuals')",
        ),
        DataSource(
            "gs_branch_pct90", str(target / "branch_pct90.parquet"), "parquet",
            "Per-branch p90 normal loading band, stratified by (hour, is_workday).",
            helper="gridstats('branch_pct90')",
        ),
        DataSource(
            "gs_branch_pct95", str(target / "branch_pct95.parquet"), "parquet",
            "Per-branch p95 normal loading band, stratified by (hour, is_workday).",
            helper="gridstats('branch_pct95')",
        ),
        DataSource(
            "gs_branch_pct99", str(target / "branch_pct99.parquet"), "parquet",
            "Per-branch p99 normal loading band, stratified by (hour, is_workday).",
            helper="gridstats('branch_pct99')",
        ),
        DataSource(
            "gs_interesting_days", str(target / "interesting_days.csv"), "csv",
            "Precomputed ranking of the most anomalous days.",
            ["score", "driver", "load_surprise_z", "solar_surprise_z",
             "wind_surprise_z", "loading_z", "peak_loading_pct", "peak_load_mw"],
            helper="gridstats('interesting_days')",
        ),
        DataSource(
            "gs_baselines", str(target / "baselines.json"), "json",
            "Bundle baselines: forecast_error, residual_std, dataset bounds, build ts.",
            helper="gridstats('baselines')",
        ),
    ]


# Legacy keys the sandbox child loads as named tables / lazy helpers. Kept stable
# so app.sandbox_child can keep referencing paths[...] by these exact names.
_LEGACY_PATH_KEYS = (
    "buses", "branches", "gens", "loads", "gens_ts", "loads_ts", "fuel_prices",
)


def paths_map() -> dict[str, str]:
    """Flat ``name -> path`` for the convenience tables/helpers the child wires up."""
    by_key = {s.key: s.path for s in catalog()}
    return {k: by_key[k] for k in _LEGACY_PATH_KEYS}


def catalog_records() -> list[dict]:
    """Json-able catalog handed to the sandbox child (becomes the ``catalog`` global)."""
    return [asdict(s) for s in catalog()]


def catalog_text() -> str:
    """Compact, human/agent-readable rendering of the catalog (for a tool docstring)."""
    lines = []
    for s in catalog():
        access = f" — via {s.helper}" if s.helper else ""
        cols = f" [{', '.join(s.columns)}]" if s.columns else ""
        lines.append(f"  {s.key} ({s.fmt}): {s.description}{cols}{access}")
    return "\n".join(lines)
