"""Load the ČEPS pandapower snapshots and static metadata.

Responsibilities:
- discover the 8760 hourly snapshot files and expose their timestamps
- deserialize a snapshot into a pandapower net (cached)
- build a single GeoProjector from the bus coordinates
- expose static per-bus metadata (zone, coordinates)

This is the *only* module that knows the on-disk layout. Swapping in a different
dataset means changing paths/parsing here and nothing else.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402
import pandapower as pp  # noqa: E402

from . import config  # noqa: E402
from .geo import GeoProjector  # noqa: E402

_SNAP_FMT = "%Y_%m_%d_%H_%M_%S"


def _parse_ts(filename: str) -> str:
    """`2024_01_01_12_00_00.json` -> ISO `2024-01-01T12:00:00`."""
    stem = filename.removesuffix(".json")
    return datetime.strptime(stem, _SNAP_FMT).isoformat()


def _ts_to_filename(timestamp: str) -> str:
    dt = datetime.fromisoformat(timestamp)
    return dt.strftime(_SNAP_FMT) + ".json"


class DataStore:
    def __init__(self) -> None:
        self._timestamps: list[str] = []
        self._file_by_ts: dict[str, str] = {}
        self._projector: GeoProjector | None = None
        self.bus_lonlat: dict[str, tuple[float, float]] = {}
        self.bus_renewable: dict[str, dict] = {}  # bus_name -> {solar_mw, wind_mw}
        self._discover()
        self._init_projector()
        self._init_static()

    # --- discovery -----------------------------------------------------------
    def _discover(self) -> None:
        if not config.SNAPSHOTS_DIR.exists():
            raise FileNotFoundError(
                f"Snapshots dir not found: {config.SNAPSHOTS_DIR}. "
                "Set GRID_DATA_DIR or extract the dataset."
            )
        files = sorted(p.name for p in config.SNAPSHOTS_DIR.glob("*.json"))
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
        # cache bus_name -> (lon, lat)
        for idx, row in net.bus.iterrows():
            lon, lat = self._projector.to_lonlat(
                float(geo.at[idx, "x"]), float(geo.at[idx, "y"])
            )
            self.bus_lonlat[str(row["name"])] = (round(lon, 5), round(lat, 5))

    def _init_static(self) -> None:
        """Aggregate solar/wind capacity per bus from static/gens.csv."""
        gens_csv = config.STATIC_DIR / "gens.csv"
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

    def has(self, timestamp: str) -> bool:
        return timestamp in self._file_by_ts

    def nearest_timestamp(self, timestamp: str) -> str:
        if timestamp in self._file_by_ts:
            return timestamp
        # fall back to the closest available frame
        target = datetime.fromisoformat(timestamp)
        return min(
            self._timestamps,
            key=lambda t: abs((datetime.fromisoformat(t) - target).total_seconds()),
        )

    def bounds(self) -> tuple[str, str]:
        """First and last available snapshot timestamps (ISO)."""
        return self._timestamps[0], self._timestamps[-1]

    def in_range(self, timestamp: str) -> bool:
        """True if `timestamp` falls within the available snapshot range.

        `nearest_timestamp` silently clamps out-of-range requests to an edge
        frame; callers that must NOT clamp (e.g. "yesterday" before the dataset
        start) should gate on this first.
        """
        t = datetime.fromisoformat(timestamp)
        lo = datetime.fromisoformat(self._timestamps[0])
        hi = datetime.fromisoformat(self._timestamps[-1])
        return lo <= t <= hi

    def shift(self, timestamp: str, hours: int) -> str | None:
        """Snapshot `hours` away from `timestamp` (negative = earlier), or None
        if that lands outside the dataset (no silent clamping)."""
        base = datetime.fromisoformat(self.nearest_timestamp(timestamp))
        target = (base + timedelta(hours=hours)).isoformat()
        return self.nearest_timestamp(target) if self.in_range(target) else None

    def read_net(self, timestamp: str):
        """Deserialize a snapshot into a FRESH pandapower net.

        Always returns a new object so callers (N-1, what-if) can freely mutate
        in_service flags / loads without corrupting any shared state. Frame-level
        caching of the solved canonical result happens in engine.py.
        """
        filename = self._file_by_ts.get(timestamp)
        if filename is None:
            raise KeyError(f"Unknown timestamp: {timestamp}")
        return pp.from_json(str(config.SNAPSHOTS_DIR / filename))


# module-level singleton
store = DataStore()
