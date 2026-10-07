"""Walk statistics from geotagged photos."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .photos import PhotoMeta

EARTH_RADIUS_KM = 6371.0088
# Two photos further apart in time than this are not the same outing: no distance or route line joins them.
MAX_OUTING_GAP_SECONDS = 3 * 3600


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
    # Only photos with a real camera timestamp count toward the time span. A file's
    # modified time is when it was copied, not when it was taken, so it must not
    # stretch (or shrink) the span.
    timed: int
    started: datetime | None
    ended: datetime | None
    # Straight lines between consecutive geotagged photos taken within
    # MAX_OUTING_GAP_SECONDS of each other. A lower bound on the distance
    # actually covered, and the report says so.
    min_distance_km: float
    linked_pairs: int

    @property
    def duration_minutes(self) -> int | None:
        if self.started is None or self.ended is None:
            return None
        return int((self.ended - self.started).total_seconds() // 60)


def walk_stats(metas: list[PhotoMeta]) -> WalkStats | None:
    if not metas:
        return None
    ordered = sorted(metas, key=lambda m: m.taken)
    geo = [m for m in ordered if m.lat is not None and m.lon is not None]
    dist, pairs = 0.0, 0
    for a, b in zip(geo, geo[1:]):
        if (
            a.time_source == "exif"
            and b.time_source == "exif"
            and (b.taken - a.taken).total_seconds() <= MAX_OUTING_GAP_SECONDS
        ):
            dist += haversine_km(a.lat, a.lon, b.lat, b.lon)
            pairs += 1
    times = [m.taken for m in ordered if m.time_source == "exif"]
    return WalkStats(
        photos=len(ordered),
        geotagged=len(geo),
        timed=len(times),
        started=times[0] if len(times) >= 2 else None,
        ended=times[-1] if len(times) >= 2 else None,
        min_distance_km=dist,
        linked_pairs=pairs,
    )
