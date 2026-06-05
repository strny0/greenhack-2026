"""Project the dataset's schematic x/y coordinates onto WGS84 over Czechia.

The ČEPS dataset ships abstract layout coordinates (e.g. x=626, y=-324), not
geography. We compute the bounding box of all bus coordinates once and linearly
map it into a Czech lon/lat box so the grid renders as a real map. This is a
display projection only — it does not claim true substation locations.
"""
from __future__ import annotations

from . import config


class GeoProjector:
    def __init__(self, xs: list[float], ys: list[float]):
        self.x_min, self.x_max = min(xs), max(xs)
        self.y_min, self.y_max = min(ys), max(ys)
        # guard against degenerate ranges
        if self.x_max == self.x_min:
            self.x_max += 1
        if self.y_max == self.y_min:
            self.y_max += 1

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        fx = (x - self.x_min) / (self.x_max - self.x_min)
        # y grows downward in screen space -> invert so larger y = further south
        fy = (y - self.y_min) / (self.y_max - self.y_min)
        lon = config.CZ_LON_MIN + fx * (config.CZ_LON_MAX - config.CZ_LON_MIN)
        lat = config.CZ_LAT_MAX - fy * (config.CZ_LAT_MAX - config.CZ_LAT_MIN)
        return lon, lat
