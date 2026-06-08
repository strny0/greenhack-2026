"""Snapshot file index — discovery and deserialization of the hourly pandapower
snapshot files.

This is the one place that knows how to find the ``*.json`` snapshots in a data
directory, map them to/from ISO timestamps (via app.paths), and read one into a
fresh pandapower net. It is shared by the runtime loader (app.data_loader, which
layers the canonical Node/Line model on top) and the offline scanner
(app.gridstats.loader, which aggregates statistics) so the discovery/IO logic
lives in exactly one place.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

import pandapower as pp  # noqa: E402

from . import paths  # noqa: E402


class SnapshotIndex:
    """Indexes the hourly snapshot files under ``snapshots_dir`` by ISO timestamp."""

    def __init__(self, snapshots_dir: Path | str) -> None:
        self.snapshots_dir = Path(snapshots_dir)
        self.timestamps: list[str] = []          # sorted ISO timestamps
        self.file_by_ts: dict[str, str] = {}     # ISO timestamp -> filename
        self._discover()

    def _discover(self) -> None:
        if not self.snapshots_dir.exists():
            raise FileNotFoundError(
                f"Snapshots dir not found: {self.snapshots_dir}. "
                "Set GRID_DATA_DIR or extract the dataset."
            )
        for f in sorted(p.name for p in self.snapshots_dir.glob("*.json")):
            try:
                ts = paths.parse_snapshot_ts(f)
            except ValueError:
                continue
            self.timestamps.append(ts)
            self.file_by_ts[ts] = f
        if not self.timestamps:
            raise RuntimeError(f"No snapshot files discovered in {self.snapshots_dir}.")

    # --- queries -------------------------------------------------------------

    def has(self, timestamp: str) -> bool:
        return timestamp in self.file_by_ts

    def bounds(self) -> tuple[str, str]:
        """First and last available snapshot timestamps (ISO)."""
        return self.timestamps[0], self.timestamps[-1]

    def nearest_timestamp(self, timestamp: str) -> str:
        """The available snapshot closest to ``timestamp`` (clamps to an edge)."""
        if timestamp in self.file_by_ts:
            return timestamp
        target = datetime.fromisoformat(timestamp)
        return min(
            self.timestamps,
            key=lambda t: abs((datetime.fromisoformat(t) - target).total_seconds()),
        )

    def in_range(self, timestamp: str) -> bool:
        """True if ``timestamp`` falls within the available snapshot range.

        ``nearest_timestamp`` silently clamps out-of-range requests to an edge
        frame; callers that must NOT clamp should gate on this first.
        """
        t = datetime.fromisoformat(timestamp)
        lo = datetime.fromisoformat(self.timestamps[0])
        hi = datetime.fromisoformat(self.timestamps[-1])
        return lo <= t <= hi

    def shift(self, timestamp: str, hours: int) -> str | None:
        """Snapshot ``hours`` away from ``timestamp`` (negative = earlier), or
        None if that lands outside the dataset (no silent clamping)."""
        base = datetime.fromisoformat(self.nearest_timestamp(timestamp))
        target = (base + timedelta(hours=hours)).isoformat()
        return self.nearest_timestamp(target) if self.in_range(target) else None

    def read_net(self, timestamp: str):
        """Deserialize a snapshot into a FRESH pandapower net.

        Always returns a new object (``pp.from_json`` per call) so callers (N-1,
        what-if) can mutate it freely without corrupting any shared state.
        """
        filename = self.file_by_ts.get(timestamp)
        if filename is None:
            raise KeyError(f"Unknown timestamp: {timestamp}")
        return pp.from_json(str(self.snapshots_dir / filename))
