"""Walk statistics from geotagged photos."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .photos import PhotoMeta

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class WalkStats:
    photos: int
    geotagged: int
    started: datetime
    ended: datetime
    # Straight lines between consecutive geotagged photos. A lower bound on the
    # real distance walked, and the report says so.
    min_distance_km: float

    @property
    def duration_minutes(self) -> int:
        return int((self.ended - self.started).total_seconds() // 60)


def walk_stats(metas: list[PhotoMeta]) -> WalkStats | None:
    if not metas:
        return None
    ordered = sorted(metas, key=lambda m: m.taken)
    pts = [(m.lat, m.lon) for m in ordered if m.lat is not None and m.lon is not None]
    dist = sum(
        haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])
    )
    return WalkStats(
        photos=len(ordered),
        geotagged=len(pts),
        started=ordered[0].taken,
        ended=ordered[-1].taken,
        min_distance_km=dist,
    )
