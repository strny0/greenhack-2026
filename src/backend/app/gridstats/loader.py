"""Data loading for the case-study: snapshots, forecasts, realtime CSVs.

Three classes:
  DataStore     — pandapower snapshot discovery + pre-solved metrics extraction
  ForecastStore — DA solar/wind/load forecast CSVs
  RealtimeStore — realtime gens_ts.csv / loads_ts.csv

No module-level singletons; all constructors default to config.DATA_DIR.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import pandapower as pp

from . import config
from .geo import GeoProjector

_SNAP_FMT = "%Y_%m_%d_%H_%M_%S"


def _parse_ts(filename: str) -> str:
    stem = filename.removesuffix(".json")
    return datetime.strptime(stem, _SNAP_FMT).isoformat()


def _ts_to_filename(ts: str) -> str:
    return datetime.fromisoformat(ts).strftime(_SNAP_FMT) + ".json"


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL checkpoint, skipping any blank/partial trailing line."""
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # truncated last line from a cancelled run — ignore
                continue
    return rows


def _dedupe_by_ts(rows: list[dict]) -> list[dict]:
    """Collapse rows to one per ``timestamp`` (keep last write)."""
    by_ts = {r["timestamp"]: r for r in rows if "timestamp" in r}
    return list(by_ts.values())


# ---------------------------------------------------------------------------
# snapshot extraction (module-level so it is picklable for multiprocessing)
# ---------------------------------------------------------------------------

def _extract_rows(net, ts: str) -> tuple[dict, dict]:
    """Pull (metric_row, branch_row) out of an already-deserialized net.

    No load-flow re-run — reads the embedded res_* result tables.  Shared by the
    serial path (DataStore._scan_one) and the worker path (_scan_file_worker).
    """
    converged = bool(getattr(net, "converged", False))

    total_load = float(net.load["p_mw"].sum()) if len(net.load) else 0.0

    if converged and len(net.res_gen):
        total_gen = float(net.res_gen["p_mw"].sum())
    elif len(net.gen):
        total_gen = float(net.gen["p_mw"].sum())
    else:
        total_gen = 0.0

    slack_mw = float(net.res_ext_grid["p_mw"].sum()) if (converged and len(net.res_ext_grid)) else 0.0

    max_loading = 0.0
    n_overloaded = 0
    b_row: dict = {"timestamp": ts}

    if converged and len(net.res_line):
        loadings = net.res_line["loading_percent"].dropna()
        if len(loadings):
            max_loading = float(loadings.max())
            n_overloaded = int((loadings >= config.LINE_LOADING_ALERT).sum())
        for idx, r in net.line.iterrows():
            val = net.res_line.at[idx, "loading_percent"] if idx in net.res_line.index else float("nan")
            b_row[str(r["name"])] = None if (val != val) else round(float(val), 2)

    m_row = {
        "timestamp": ts,
        "total_load_mw": round(total_load, 2),
        "total_gen_mw": round(total_gen, 2),
        "slack_mw": round(slack_mw, 2),
        "max_line_loading_pct": round(max_loading, 2),
        "n_overloaded_lines": n_overloaded,
        "converged": converged,
    }
    return m_row, b_row


def _scan_file_worker(task: tuple[str, str, str]) -> tuple[dict, dict]:
    """ProcessPool worker: deserialize one snapshot file and extract its rows.

    Takes (snapshots_dir, filename, timestamp) so nothing but plain strings cross
    the process boundary; returns the two plain-dict rows (picklable).
    """
    snapshots_dir, filename, ts = task
    net = pp.from_json(str(Path(snapshots_dir) / filename))
    return _extract_rows(net, ts)


def _worker_init() -> None:
    """Silence pandapower's import-time warnings inside each spawned worker."""
    import warnings as _w
    _w.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# DataStore
# ---------------------------------------------------------------------------

class DataStore:
    """Discovers and reads pandapower snapshot files; exposes pre-solved metrics."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else config.DATA_DIR
        self._snapshots_dir = self._data_dir / "snapshots"
        self._static_dir = self._data_dir / "static"

        self._timestamps: list[str] = []
        self._file_by_ts: dict[str, str] = {}
        self._projector: GeoProjector | None = None
        self.bus_lonlat: dict[str, tuple[float, float]] = {}
        self.bus_renewable: dict[str, dict] = {}

        self._discover()
        self._init_projector()
        self._init_static()
        self._metrics_cache: pd.DataFrame | None = None
        self._branch_cache: pd.DataFrame | None = None

    # --- discovery -----------------------------------------------------------

    def _discover(self) -> None:
        if not self._snapshots_dir.exists():
            raise FileNotFoundError(f"Snapshots dir not found: {self._snapshots_dir}")
        files = sorted(p.name for p in self._snapshots_dir.glob("*.json"))
        for f in files:
            try:
                ts = _parse_ts(f)
            except ValueError:
                continue
            self._timestamps.append(ts)
            self._file_by_ts[ts] = f
        if not self._timestamps:
            raise RuntimeError("No snapshot files discovered.")

    def _init_projector(self) -> None:
        net = self.read_net(self._timestamps[0])
        geo = net.bus_geodata
        self._projector = GeoProjector(list(geo.x), list(geo.y))
        for idx, row in net.bus.iterrows():
            lon, lat = self._projector.to_lonlat(
                float(geo.at[idx, "x"]), float(geo.at[idx, "y"])
            )
            self.bus_lonlat[str(row["name"])] = (round(lon, 5), round(lat, 5))

    def _init_static(self) -> None:
        gens_csv = self._static_dir / "gens.csv"
        if not gens_csv.exists():
            return
        df = pd.read_csv(gens_csv)
        for _, r in df.iterrows():
            name = str(r.get("gen_name", ""))
            bus = str(r.get("bus_name", ""))
            cap = float(r.get("max_p_mw", 0.0) or 0.0)
            if not bus:
                continue
            entry = self.bus_renewable.setdefault(bus, {"solar_mw": 0.0, "wind_mw": 0.0})
            if name.startswith("solar"):
                entry["solar_mw"] += cap
            elif name.startswith("wind"):
                entry["wind_mw"] += cap

    # --- accessors -----------------------------------------------------------

    @property
    def timestamps(self) -> list[str]:
        return self._timestamps

    @property
    def projector(self) -> GeoProjector:
        assert self._projector is not None
        return self._projector

    def nearest_timestamp(self, ts: str) -> str:
        if ts in self._file_by_ts:
            return ts
        target = datetime.fromisoformat(ts)
        return min(self._timestamps, key=lambda t: abs((datetime.fromisoformat(t) - target).total_seconds()))

    def read_net(self, timestamp: str):
        """Deserialize snapshot into a fresh pandapower net (no load-flow re-run)."""
        filename = self._file_by_ts.get(timestamp)
        if filename is None:
            raise KeyError(f"Unknown timestamp: {timestamp}")
        return pp.from_json(str(self._snapshots_dir / filename))

    # --- pre-solved metrics (no re-run) --------------------------------------

    def snapshot_metrics(self, timestamp: str) -> dict:
        """Extract system-level metrics from the pre-solved pandapower result tables.

        Reads the embedded res_bus / res_line without re-running any load flow.
        Returns NaN-safe numeric values so the result is always safe to aggregate.
        """
        net = self.read_net(timestamp)
        converged = bool(getattr(net, "converged", False))

        # total load from load table (setpoints, always present)
        total_load = float(net.load["p_mw"].sum()) if len(net.load) else 0.0

        # total generation and slack from result tables if converged
        if converged and len(net.res_gen):
            total_gen = float(net.res_gen["p_mw"].sum())
        elif len(net.gen):
            total_gen = float(net.gen["p_mw"].sum())
        else:
            total_gen = 0.0

        if converged and len(net.res_ext_grid):
            slack_mw = float(net.res_ext_grid["p_mw"].sum())
        else:
            slack_mw = 0.0

        # line loadings from result table
        max_loading = 0.0
        n_overloaded = 0
        if converged and len(net.res_line):
            loadings = net.res_line["loading_percent"].dropna()
            if len(loadings):
                max_loading = float(loadings.max())
                n_overloaded = int((loadings >= config.LINE_LOADING_ALERT).sum())

        return {
            "timestamp": timestamp,
            "total_load_mw": round(total_load, 2),
            "total_gen_mw": round(total_gen, 2),
            "slack_mw": round(slack_mw, 2),
            "max_line_loading_pct": round(max_loading, 2),
            "n_overloaded_lines": n_overloaded,
            "converged": converged,
        }

    def _scan_one(self, ts: str) -> tuple[dict, dict]:
        """Read one snapshot; return its (metric_row, branch_row) dicts.

        Serial per-snapshot work shared by scan_all().  Both dicts carry the
        ``timestamp`` key so they can be checkpointed and re-aligned on resume.
        """
        return _extract_rows(self.read_net(ts), ts)

    def scan_all(
        self, progress: bool = False, resume: bool = True, workers: int = 1
    ) -> tuple["pd.DataFrame", "pd.DataFrame"]:
        """Single pass over all snapshots; returns (metrics_df, branch_df).

        metrics_df — system-level metrics per timestamp (total_load, max_loading, …)
        branch_df  — per-branch loading_percent per timestamp (cols = branch names)

        Both DataFrames share the same datetime index.  Cached in memory after the
        first call.

        Resumable: each snapshot is appended to JSONL checkpoints under
        ``config.CACHE_DIR`` as it is scanned.  If the process is cancelled, calling
        scan_all() again skips the already-scanned snapshots (``resume=True``).  Pass
        ``resume=False`` (or delete CACHE_DIR) to force a clean rescan.  Set
        ``progress=True`` for a tqdm bar over the remaining snapshots.

        ``workers > 1`` deserializes snapshots in a ProcessPoolExecutor (the scan is
        CPU-bound in pp.from_json, so processes — not threads — give the speedup).
        The main process stays the *single writer* of the checkpoints, so resume and
        on-disk consistency are identical to the serial path; only the order in which
        snapshots are scanned differs (rebuild sorts by timestamp anyway).  NOTE:
        with workers>1 the caller must be under an ``if __name__ == "__main__":``
        guard (Windows spawn) — the package's ``python -m app.gridstats.build``
        entrypoint already is.
        """
        if self._metrics_cache is not None:
            return self._metrics_cache, self._branch_cache  # type: ignore[return-value]

        cache_dir = config.CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        m_path = cache_dir / "scan_metrics.jsonl"
        b_path = cache_dir / "scan_branch.jsonl"

        if not resume:
            m_path.unlink(missing_ok=True)
            b_path.unlink(missing_ok=True)

        done: set[str] = set()
        if resume and m_path.exists():
            done = {row["timestamp"] for row in _read_jsonl(m_path) if "timestamp" in row}

        todo = [ts for ts in self._timestamps if ts not in done]

        if todo:
            workers = max(1, int(workers))
            bar = None
            if progress:
                from tqdm import tqdm
                bar = tqdm(
                    total=len(self._timestamps),
                    initial=len(done),
                    desc="Scanning snapshots",
                    unit="snap",
                )
            mf = m_path.open("a", encoding="utf-8")
            bf = b_path.open("a", encoding="utf-8")
            try:
                if workers > 1:
                    from concurrent.futures import ProcessPoolExecutor
                    tasks = [
                        (str(self._snapshots_dir), self._file_by_ts[ts], ts)
                        for ts in todo
                    ]
                    chunksize = max(1, min(64, len(tasks) // (workers * 8) or 1))
                    with ProcessPoolExecutor(
                        max_workers=workers, initializer=_worker_init
                    ) as ex:
                        results = ex.map(_scan_file_worker, tasks, chunksize=chunksize)
                        for i, (m_row, b_row) in enumerate(results):
                            bf.write(json.dumps(b_row) + "\n")
                            mf.write(json.dumps(m_row) + "\n")
                            if i % 50 == 0:
                                bf.flush()
                                mf.flush()
                            if bar is not None:
                                bar.update(1)
                else:
                    for i, ts in enumerate(todo):
                        m_row, b_row = self._scan_one(ts)
                        bf.write(json.dumps(b_row) + "\n")
                        mf.write(json.dumps(m_row) + "\n")
                        if i % 50 == 0:
                            bf.flush()
                            mf.flush()
                        if bar is not None:
                            bar.update(1)
            finally:
                bf.flush()
                mf.flush()
                bf.close()
                mf.close()
                if bar is not None:
                    bar.close()

        # rebuild from the full checkpoint files (dedupe absorbs any partial write)
        metric_rows = _dedupe_by_ts(_read_jsonl(m_path))
        branch_rows = _dedupe_by_ts(_read_jsonl(b_path))

        def _to_df(rows: list[dict], ts_col: str = "timestamp") -> pd.DataFrame:
            df = pd.DataFrame(rows)
            df["datetime"] = pd.to_datetime(df[ts_col])
            return df.drop(columns=[ts_col]).set_index("datetime").sort_index()

        self._metrics_cache = _to_df(metric_rows)
        self._branch_cache = _to_df(branch_rows)
        return self._metrics_cache, self._branch_cache

    def all_metrics_df(self, progress: bool = False, workers: int = 1) -> pd.DataFrame:
        """Convenience wrapper — returns only the system metrics DataFrame."""
        metrics, _ = self.scan_all(progress=progress, workers=workers)
        return metrics


# ---------------------------------------------------------------------------
# ForecastStore
# ---------------------------------------------------------------------------

class ForecastStore:
    """Loads day-ahead forecast CSVs for solar, wind, and regional load."""

    _DA_FMT = "%m/%d/%y %H:%M"

    def __init__(self, data_dir: Path | None = None) -> None:
        self._forecasts_dir = (Path(data_dir) if data_dir else config.DATA_DIR) / "forecasts" / "DA"
        self._df: pd.DataFrame | None = None

    def system_forecast(self) -> pd.DataFrame:
        """Return hourly DA forecast with columns:
        [load_r1_mw, load_r2_mw, load_r3_mw, load_total_mw, solar_mw, wind_mw]
        indexed by datetime.
        """
        if self._df is not None:
            return self._df

        # --- load forecasts (3 regional files) ---
        load_parts = {}
        for region in (1, 2, 3):
            path = self._forecasts_dir / "Load" / f"LoadR{region}DA.csv"
            df = pd.read_csv(path)
            df["datetime"] = pd.to_datetime(df["DATETIME"], format=self._DA_FMT)
            load_parts[f"load_r{region}_mw"] = df.set_index("datetime")["value"]

        load_df = pd.DataFrame(load_parts)
        load_df["load_total_mw"] = load_df.sum(axis=1)

        # --- solar forecast (sum across all Solar*DA.csv) ---
        solar_series = self._sum_glob("Solar", "Solar*DA.csv")

        # --- wind forecast (sum across all Wind*DA.csv) ---
        wind_series = self._sum_glob("Wind", "Wind*DA.csv")

        result = load_df.copy()
        result["solar_mw"] = solar_series
        result["wind_mw"] = wind_series
        result = result.sort_index()

        self._df = result
        return result

    def _sum_glob(self, subdir: str, pattern: str) -> pd.Series:
        total: pd.Series | None = None
        for path in sorted((self._forecasts_dir / subdir).glob(pattern)):
            df = pd.read_csv(path)
            df["datetime"] = pd.to_datetime(df["DATETIME"], format=self._DA_FMT)
            s = df.set_index("datetime")["value"]
            total = s if total is None else total.add(s, fill_value=0)
        if total is None:
            raise RuntimeError(f"No files matched {self._forecasts_dir / subdir / pattern}")
        return total


# ---------------------------------------------------------------------------
# RealtimeStore
# ---------------------------------------------------------------------------

class RealtimeStore:
    """Loads realtime generator and load time series CSVs."""

    def __init__(self, data_dir: Path | None = None) -> None:
        rt_dir = (Path(data_dir) if data_dir else config.DATA_DIR) / "realtime"
        self._gens_path = rt_dir / "gens_ts.csv"
        self._loads_path = rt_dir / "loads_ts.csv"
        self._totals_cache: pd.DataFrame | None = None

    def system_totals(self) -> pd.DataFrame:
        """Return hourly aggregated actuals with columns:
        [load_mw, solar_mw, wind_mw, other_gen_mw, gen_total_mw]
        indexed by datetime.
        """
        if self._totals_cache is not None:
            return self._totals_cache

        # loads: sum p_mw per datetime
        loads = pd.read_csv(self._loads_path, parse_dates=["datetime"])
        loads_agg = (
            loads[loads["in_service"] == True]
            .groupby("datetime")["p_mw"]
            .sum()
            .rename("load_mw")
        )

        # gens: split by technology prefix
        gens = pd.read_csv(self._gens_path, parse_dates=["datetime"])
        gens = gens[gens["in_service"] == True].copy()
        gens["tech"] = gens["gen_name"].str.extract(r"^([a-z_]+?)_\d+$")[0]

        solar = (
            gens[gens["gen_name"].str.startswith("solar")]
            .groupby("datetime")["p_mw"].sum()
            .rename("solar_mw")
        )
        wind = (
            gens[gens["gen_name"].str.startswith("wind")]
            .groupby("datetime")["p_mw"].sum()
            .rename("wind_mw")
        )
        other = (
            gens[~gens["gen_name"].str.startswith(("solar", "wind"))]
            .groupby("datetime")["p_mw"].sum()
            .rename("other_gen_mw")
        )

        df = pd.concat([loads_agg, solar, wind, other], axis=1).sort_index()
        df["gen_total_mw"] = df[["solar_mw", "wind_mw", "other_gen_mw"]].sum(axis=1)
        df = df.fillna(0.0)

        self._totals_cache = df
        return df


# ---------------------------------------------------------------------------
# smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Loading DataStore …")
    ds = DataStore()
    print(f"  {len(ds.timestamps)} snapshots: {ds.timestamps[0]} → {ds.timestamps[-1]}")
    lon, lat = ds.bus_lonlat["bus_001"]
    print(f"  bus_001  lon={lon:.3f}  lat={lat:.3f}  (expect ~37-38°N, ~121-122°W)")

    print("Loading ForecastStore …")
    fs = ForecastStore()
    fc = fs.system_forecast()
    print(f"  {len(fc)} forecast hours, columns: {list(fc.columns)}")
    print(f"  date range: {fc.index[0]} → {fc.index[-1]}")

    print("Loading RealtimeStore …")
    rs = RealtimeStore()
    rt = rs.system_totals()
    print(f"  {len(rt)} realtime hours, columns: {list(rt.columns)}")
    print(f"  date range: {rt.index[0]} → {rt.index[-1]}")
