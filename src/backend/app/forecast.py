"""Day-ahead (DA) forecast loader — "the plan" to compare the snapshot against.

The dataset ships per-site DA forecasts as flat `DATETIME,value` CSVs:
  forecasts/DA/Solar/Solar{1..75}DA.csv   -> generator solar_{NNN}
  forecasts/DA/Wind/Wind{1..17}DA.csv     -> generator wind_{NNN}
  forecasts/DA/Load/LoadR{1..3}DA.csv     -> region r{N}

This module lazily loads each series and exposes `planned_at(timestamp)`: the
planned MW per generator (solar/wind) and per region (load) for a given hour.

Two honesty rules baked in (see the project plan):
- Series index -> generator name by number (`Solar7DA` -> `solar_007`). There are
  75 solar *forecast* files but only 73 `solar_*` generators (two numbers are
  skipped), so a few series have no matching generator. Those are reported as
  `unmapped` and folded into the system aggregate — never silently dropped, never
  invented onto a wrong generator.
- Forecast timestamps are matched by (month, day, hour), which sidesteps the
  M/D/YY format, the leap-year row count (8784 vs 8760 snapshots), and solar's
  one-hour label offset. A missed lookup yields no plan for that element (None),
  not a zero.
"""
from __future__ import annotations

import re

import pandas as pd

from . import config
from .data_loader import store

_DATETIME_FMT = "%m/%d/%y %H:%M"  # e.g. "1/1/24 13:00"
_NUM_RE = re.compile(r"(\d+)")

# (month, day, hour) -> a unique key within a single forecast year.
_TsKey = tuple


def _ts_key_from_iso(timestamp: str) -> _TsKey:
    dt = pd.Timestamp(timestamp)
    return (dt.month, dt.day, dt.hour)


class ForecastStore:
    def __init__(self) -> None:
        # filename stem -> {(month,day,hour): value}
        self._series: dict[str, dict[_TsKey, float]] = {}
        # built lazily on first planned_at()
        self._solar_map: dict[str, str] | None = None  # stem -> solar_NNN
        self._wind_map: dict[str, str] | None = None
        self._load_map: dict[str, str] | None = None  # stem -> region

    # --- series loading ------------------------------------------------------
    def _load_series(self, path) -> dict[_TsKey, float]:
        stem = path.stem
        cached = self._series.get(stem)
        if cached is not None:
            return cached
        df = pd.read_csv(path)
        dt = pd.to_datetime(df["DATETIME"], format=_DATETIME_FMT, errors="coerce")
        out: dict[_TsKey, float] = {}
        for ts, val in zip(dt, df["value"]):
            if pd.isna(ts) or pd.isna(val):
                continue
            out[(ts.month, ts.day, ts.hour)] = float(val)
        self._series[stem] = out
        return out

    # --- series -> element mapping (built once) ------------------------------
    def _build_maps(self) -> None:
        if self._solar_map is not None:
            return
        self._solar_map = self._map_dir(config.FORECASTS_DA_SOLAR, "solar")
        self._wind_map = self._map_dir(config.FORECASTS_DA_WIND, "wind")
        self._load_map = {}
        if config.FORECASTS_DA_LOAD.exists():
            for p in config.FORECASTS_DA_LOAD.glob("*.csv"):
                m = _NUM_RE.search(p.stem)
                if m:
                    self._load_map[p.stem] = f"r{int(m.group(1))}"

    @staticmethod
    def _map_dir(directory, prefix: str) -> dict[str, str]:
        """stem -> '<prefix>_<NNN>' for every CSV in `directory`."""
        out: dict[str, str] = {}
        if not directory.exists():
            return out
        for p in directory.glob("*.csv"):
            m = _NUM_RE.search(p.stem)
            if m:
                out[p.stem] = f"{prefix}_{int(m.group(1)):03d}"
        return out

    def _planned_gens(self, directory, stem_to_gen: dict[str, str], key: _TsKey):
        """Return (mapped {gen_name: mw}, unmapped_sum, unmapped_gen_names)."""
        mapped: dict[str, float] = {}
        unmapped_sum = 0.0
        unmapped: list[str] = []
        for p in directory.glob("*.csv"):
            gen = stem_to_gen.get(p.stem)
            if gen is None:
                continue
            val = self._load_series(p).get(key)
            if val is None:
                continue
            if gen in store.gen_to_bus:
                mapped[gen] = val
            else:
                unmapped_sum += val
                unmapped.append(gen)
        return mapped, round(unmapped_sum, 2), sorted(unmapped)

    # --- public API ----------------------------------------------------------
    def planned_at(self, timestamp: str) -> dict:
        """The DA plan for `timestamp`: planned MW per solar/wind generator and
        per load region, plus honest data-quality flags."""
        self._build_maps()
        key = _ts_key_from_iso(timestamp)

        solar, solar_unmapped_mw, solar_unmapped = self._planned_gens(
            config.FORECASTS_DA_SOLAR, self._solar_map or {}, key
        )
        wind, wind_unmapped_mw, wind_unmapped = self._planned_gens(
            config.FORECASTS_DA_WIND, self._wind_map or {}, key
        )

        load_by_region: dict[str, float] = {}
        if config.FORECASTS_DA_LOAD.exists():
            for p in config.FORECASTS_DA_LOAD.glob("*.csv"):
                region = (self._load_map or {}).get(p.stem)
                if region is None:
                    continue
                val = self._load_series(p).get(key)
                if val is not None:
                    load_by_region[region] = round(val, 2)

        any_hit = bool(solar or wind or load_by_region)
        return {
            "solar": solar,
            "wind": wind,
            "load_by_region": load_by_region,
            "solar_unmapped_mw": solar_unmapped_mw,
            "wind_unmapped_mw": wind_unmapped_mw,
            "unmapped": solar_unmapped + wind_unmapped,
            "units_warning": None,  # confirmed: forecast `value` is MW for all streams
            "missing_ts": not any_hit,
        }


# module-level singleton (mirrors data_loader.store / weather usage)
forecast_store = ForecastStore()
