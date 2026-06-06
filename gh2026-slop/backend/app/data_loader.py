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

import re
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


def _gen_fuel_type(gen_name: str) -> str:
    """Fuel type from a gen name like `combined_cycle_gas_007` -> `combined_cycle_gas`.

    Generators are named `<fuel_type>_<NNN>`; strip the trailing numeric suffix.
    """
    return re.sub(r"_\d+$", "", gen_name).strip()


class DataStore:
    def __init__(self) -> None:
        self._timestamps: list[str] = []
        self._file_by_ts: dict[str, str] = {}
        self._projector: GeoProjector | None = None
        self.bus_lonlat: dict[str, tuple[float, float]] = {}
        self.bus_sld: dict[str, tuple[float, float]] = {}
        self.bus_renewable: dict[str, dict] = {}  # bus_name -> {solar_mw, wind_mw}
        # bus_name -> generator fuel types present, ordered by installed capacity desc
        self.bus_gen_types: dict[str, list[str]] = {}
        self.gen_to_bus: dict[str, str] = {}  # gen_name -> bus_name (deviation join)
        self.bus_to_region: dict[str, str] = {}  # bus_name -> region (load join)
        self.bus_labels: dict[str, str] = {}
        self.branch_labels: dict[str, str] = {}
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
        bus = net.bus

        # Load coordinates from bus_coordinates.csv:
        # - real_lat/real_lon: matched to real California power plants (EIA/CEC data) — generator buses only
        # - de_lat/de_lon: RWTH Aachen IEEE-118 georeferencing projected into California regions — all buses
        bus_real_coords: dict[str, tuple[float, float]] = {}  # lon, lat
        bus_de_coords: dict[str, tuple[float, float]] = {}
        coords_csv = config.OVERRIDES_DIR / "bus_coordinates.csv"
        if coords_csv.exists():
            df_coords = pd.read_csv(coords_csv)
            for _, r in df_coords.iterrows():
                name = str(r["bus_name"])
                if "real_lat" in df_coords.columns and pd.notna(r.get("real_lat")):
                    bus_real_coords[name] = (float(r["real_lon"]), float(r["real_lat"]))
                if "de_lat" in df_coords.columns and pd.notna(r.get("de_lat")):
                    # Treat (de_lon, de_lat) as (x, y) so East=right, North=up
                    bus_de_coords[name] = (float(r["de_lon"]), float(r["de_lat"]))

        # Group bus geodata by region (pandapower stores it on net.bus.zone).
        per_region_xy: dict[str, list[tuple[float, float]]] = {}
        per_region_de: dict[str, list[tuple[float, float]]] = {}
        bus_region: dict[str, str] = {}
        for idx, row in bus.iterrows():
            x = float(geo.at[idx, "x"])
            y = float(geo.at[idx, "y"])
            name = str(row["name"])
            region = str(row.get("zone", "")) or "r1"
            bus_region[name] = region
            per_region_xy.setdefault(region, []).append((x, y))
            if name in bus_de_coords:
                per_region_de.setdefault(region, []).append(bus_de_coords[name])

        # SLD projector always uses schematic x/y so the SLD bbox is correct.
        self._projector = GeoProjector(per_region_xy)

        # Fallback projector for non-generator buses: German topology projection.
        geo_projector = GeoProjector(per_region_de) if per_region_de else self._projector

        # Cache bus_name -> (lon, lat) for map view and (x, y) for SLD view.
        # Priority: real CEC/EIA plant location > German projection > schematic projection.
        for idx, row in bus.iterrows():
            name = str(row["name"])
            region = bus_region[name]
            x = float(geo.at[idx, "x"])
            y = float(geo.at[idx, "y"])
            if name in bus_real_coords:
                lon, lat = bus_real_coords[name]
            elif name in bus_de_coords:
                lon, lat = geo_projector.to_lonlat(region, *bus_de_coords[name])
            else:
                lon, lat = self._projector.to_lonlat(region, x, y)
            self.bus_lonlat[name] = (round(lon, 5), round(lat, 5))
            self.bus_sld[name] = (round(x, 2), round(y, 2))

    def _init_static(self) -> None:
        """Aggregate solar/wind capacity per bus; build gen->bus / bus->region join
        tables for forecast attribution; load display labels from overrides."""
        gens_csv = config.STATIC_DIR / "gens.csv"
        if gens_csv.exists():
            df = pd.read_csv(gens_csv)
            # accumulate installed capacity per fuel type per bus, then rank
            cap_by_bus_type: dict[str, dict[str, float]] = {}
            for _, r in df.iterrows():
                name = str(r.get("gen_name", ""))
                bus = str(r.get("bus_name", ""))
                cap = float(r.get("max_p_mw", 0.0) or 0.0)
                if not bus:
                    continue
                self.gen_to_bus[name] = bus
                entry = self.bus_renewable.setdefault(bus, {"solar_mw": 0.0, "wind_mw": 0.0})
                if name.startswith("solar"):
                    entry["solar_mw"] += cap
                elif name.startswith("wind"):
                    entry["wind_mw"] += cap
                fuel = _gen_fuel_type(name)
                if fuel:
                    bt = cap_by_bus_type.setdefault(bus, {})
                    bt[fuel] = bt.get(fuel, 0.0) + cap
            for bus, by_type in cap_by_bus_type.items():
                self.bus_gen_types[bus] = [
                    t for t, _ in sorted(by_type.items(), key=lambda kv: -kv[1])
                ]

        buses_csv = config.STATIC_DIR / "buses.csv"
        if buses_csv.exists():
            bdf = pd.read_csv(buses_csv)
            for _, r in bdf.iterrows():
                bus = str(r.get("bus_name", ""))
                region = str(r.get("region", ""))
                if bus and region:
                    self.bus_to_region[bus] = region

        bus_labels_csv = config.OVERRIDES_DIR / "bus_labels.csv"
        if bus_labels_csv.exists():
            df_bl = pd.read_csv(bus_labels_csv)
            for _, r in df_bl.iterrows():
                self.bus_labels[str(r["bus_name"])] = str(r["display_name"])

        branch_labels_csv = config.OVERRIDES_DIR / "branch_labels.csv"
        if branch_labels_csv.exists():
            df_brl = pd.read_csv(branch_labels_csv)
            for _, r in df_brl.iterrows():
                self.branch_labels[str(r["branch_name"])] = str(r["display_name"])

    # --- accessors -----------------------------------------------------------
    @property
    def timestamps(self) -> list[str]:
        return self._timestamps

    @property
    def projector(self) -> GeoProjector:
        assert self._projector is not None
        return self._projector

    @property
    def sld_bbox(self) -> dict[str, float]:
        p = self.projector
        return {
            "x_min": p.x_min,
            "x_max": p.x_max,
            "y_min": p.y_min,
            "y_max": p.y_max,
        }

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
