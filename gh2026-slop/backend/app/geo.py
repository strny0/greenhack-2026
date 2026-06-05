"""Per-region linear projection of schematic x/y -> WGS84 over California.

Each IEEE-118 region (r1/r2/r3) gets its OWN bbox-to-bbox map (the targets
live in ``config.REGION_TARGETS``) so the three groups land in roughly the
right real-world utility footprints:
  r1 (Bay Area / PG&E)        → NW California
  r2 (Sacramento / SMUD)      → Central / NE California
  r3 (San Diego / SDG&E)      → Southern California

This is a display projection — it does not claim true substation locations.
"""
from __future__ import annotations

from . import config


class _SubProjector:
    """One region's schematic bbox → California sub-bbox linear map.

    - The target box is inset by ``INSET`` (20 %) so the cluster gets a margin
      around the region's edge rather than crowding right up to the boundary.
    - Within that inset target, the source bbox is scaled uniformly so its
      natural aspect ratio is preserved (no horizontal squish / vertical
      stretch) and centered.
    """

    INSET = 0.10

    def __init__(
        self,
        xs: list[float],
        ys: list[float],
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
    ) -> None:
        self.x_min, self.x_max = min(xs), max(xs)
        self.y_min, self.y_max = min(ys), max(ys)
        if self.x_max == self.x_min:
            self.x_max += 1
        if self.y_max == self.y_min:
            self.y_max += 1

        # Inset the target box so the cluster doesn't crowd the boundary.
        lon_c = (lon_min + lon_max) / 2
        lat_c = (lat_min + lat_max) / 2
        keep = 1.0 - self.INSET
        avail_lon = (lon_max - lon_min) * keep
        avail_lat = (lat_max - lat_min) * keep

        # Fit the source bbox into the inset target uniformly (smaller scale
        # wins on whichever axis is the binding constraint) so the natural
        # cluster shape is preserved.
        src_w = self.x_max - self.x_min
        src_h = self.y_max - self.y_min
        scale = min(avail_lon / src_w, avail_lat / src_h)
        fit_w = src_w * scale
        fit_h = src_h * scale

        # Center the fitted span inside the original (uninset) target.
        self.lon_min = lon_c - fit_w / 2
        self.lon_max = lon_c + fit_w / 2
        self.lat_min = lat_c - fit_h / 2
        self.lat_max = lat_c + fit_h / 2

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        fx = (x - self.x_min) / (self.x_max - self.x_min)
        # y_max (least-negative) = top of schematic = North; no inversion.
        fy = (y - self.y_min) / (self.y_max - self.y_min)
        lon = self.lon_min + fx * (self.lon_max - self.lon_min)
        lat = self.lat_min + fy * (self.lat_max - self.lat_min)
        return lon, lat


class GeoProjector:
    """Region-aware projector. Each region has its own sub-projection.

    Also exposes the aggregate schematic bbox (``x_min/x_max/y_min/y_max``)
    so the SLD view, which is region-agnostic, can still read it.
    """

    def __init__(self, per_region_xy: dict[str, list[tuple[float, float]]]) -> None:
        self._sub: dict[str, _SubProjector] = {}
        for region, pts in per_region_xy.items():
            target = config.REGION_TARGETS.get(region)
            if target is None or not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            self._sub[region] = _SubProjector(xs, ys, *target)

        if not self._sub:
            raise ValueError(
                "GeoProjector got no usable region points. "
                "Check that bus.zone matches config.REGION_TARGETS keys."
            )

        # Aggregate schematic bbox across all points (used by SLD view).
        all_xs = [p[0] for pts in per_region_xy.values() for p in pts]
        all_ys = [p[1] for pts in per_region_xy.values() for p in pts]
        self.x_min, self.x_max = min(all_xs), max(all_xs)
        self.y_min, self.y_max = min(all_ys), max(all_ys)
        if self.x_max == self.x_min:
            self.x_max += 1
        if self.y_max == self.y_min:
            self.y_max += 1

    def to_lonlat(self, region: str, x: float, y: float) -> tuple[float, float]:
        sub = self._sub.get(region)
        if sub is None:
            # bus with an unknown / missing region — fall back deterministically
            sub = next(iter(self._sub.values()))
        return sub.to_lonlat(x, y)
