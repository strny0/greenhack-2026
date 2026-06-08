"""Linear projection of schematic x/y coordinates onto WGS84 over California.

The NREL-118 dataset ships abstract layout coordinates (e.g. x=626, y=-324).
We compute the bounding box of all 118 bus coordinates once and linearly map
it into a California lon/lat box.  The three regions land roughly correctly:
  r1 (Bay Area / PG&E) → NW California
  r2 (Sacramento / SMUD) → Central/NE California
  r3 (San Diego / SDG&E) → Southern California

This is a display projection — it does not claim true substation locations.
"""
from __future__ import annotations

from . import config


class GeoProjector:
    def __init__(self, xs: list[float], ys: list[float]):
        self.x_min, self.x_max = min(xs), max(xs)
        self.y_min, self.y_max = min(ys), max(ys)
        if self.x_max == self.x_min:
            self.x_max += 1
        if self.y_max == self.y_min:
            self.y_max += 1

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        fx = (x - self.x_min) / (self.x_max - self.x_min)
        # y_max (least-negative) = top of schematic = Bay Area = North; no inversion.
        fy = (y - self.y_min) / (self.y_max - self.y_min)
        lon = config.LON_MIN + fx * (config.LON_MAX - config.LON_MIN)
        lat = config.LAT_MIN + fy * (config.LAT_MAX - config.LAT_MIN)
        return lon, lat
