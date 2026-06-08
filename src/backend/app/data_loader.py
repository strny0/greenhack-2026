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

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from . import config  # noqa: E402
from .geo import GeoProjector  # noqa: E402
from .snapshots import SnapshotIndex  # noqa: E402


def _gen_fuel_type(gen_name: str) -> str:
    """Fuel type from a gen name like `combined_cycle_gas_007` -> `combined_cycle_gas`.

    Generators are named `<fuel_type>_<NNN>`; strip the trailing numeric suffix.
    """
    return re.sub(r"_\d+$", "", gen_name).strip()


class DataStore:
    def __init__(self) -> None:
        # Snapshot discovery + deserialization is shared with gridstats.
        self._index = SnapshotIndex(config.SNAPSHOTS_DIR)
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
        self._init_projector()
        self._init_static()

    def _init_projector(self) -> None:
        net = self.read_net(self._index.timestamps[0])
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
    # Snapshot discovery / lookup / IO all delegate to the shared SnapshotIndex;
    # this class adds the canonical geo + static model on top.
    @property
    def timestamps(self) -> list[str]:
        return self._index.timestamps

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
        return self._index.has(timestamp)

    def nearest_timestamp(self, timestamp: str) -> str:
        return self._index.nearest_timestamp(timestamp)

    def bounds(self) -> tuple[str, str]:
        """First and last available snapshot timestamps (ISO)."""
        return self._index.bounds()

    def in_range(self, timestamp: str) -> bool:
        """True if `timestamp` falls within the available snapshot range.

        `nearest_timestamp` silently clamps out-of-range requests to an edge
        frame; callers that must NOT clamp (e.g. "yesterday" before the dataset
        start) should gate on this first.
        """
        return self._index.in_range(timestamp)

    def shift(self, timestamp: str, hours: int) -> str | None:
        """Snapshot `hours` away from `timestamp` (negative = earlier), or None
        if that lands outside the dataset (no silent clamping)."""
        return self._index.shift(timestamp, hours)

    def read_net(self, timestamp: str):
        """Deserialize a snapshot into a FRESH pandapower net (always a new
        object, so callers like N-1 / what-if can mutate it freely). Frame-level
        caching of the solved canonical result happens in engine.py."""
        return self._index.read_net(timestamp)


# module-level singleton
store = DataStore()
