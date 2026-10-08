"""Folder of photos in, journal directory out."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .geo import WalkStats, haversine_km, walk_stats
from .model import Backend, BackendError, Observation
from .photos import PhotoMeta, find_photos, read_meta, resized_jpeg

MODEL_SIDE = 1024
THUMB_SIDE = 640


@dataclass
class Entry:
    meta: PhotoMeta
    thumb: str  # relative path inside the journal directory
    observation: Observation | None
    error: str | None  # set when the model failed; the entry is kept and shown as failed


@dataclass
class Journal:
    entries: list[Entry]
    stats: WalkStats | None
    backend: str
    unreadable: list[tuple[str, str]]  # (file, reason): photos we could not open at all


class NoPhotosFound(RuntimeError):
    pass


# (latitude, longitude, radius in metres)
PrivacyZone = tuple[float, float, float]


def apply_privacy_zone(meta: PhotoMeta, zone: PrivacyZone | None) -> PhotoMeta:
    """Drop the location of a photo taken inside the zone. The photo and its
    description stay; only where it was taken is removed from the journal."""
    if zone is None or meta.lat is None or meta.lon is None:
        return meta
    lat, lon, radius_m = zone
    if haversine_km(meta.lat, meta.lon, lat, lon) * 1000 <= radius_m:
        return replace(meta, lat=None, lon=None, location_hidden=True)
    return meta


def build_journal(
    source: Path,
    out: Path,
    backend: Backend,
    progress: Callable[[int, int, Path], None] | None = None,
    privacy_zone: PrivacyZone | None = None,
) -> Journal:
    photos = find_photos(source)
    if not photos:
        raise NoPhotosFound(f"No .jpg/.jpeg/.png/.webp photos found under {source}")
    backend.preflight()
    (out / "thumbs").mkdir(parents=True, exist_ok=True)

    metas: list[PhotoMeta] = []
    unreadable: list[tuple[str, str]] = []
    for p in photos:
        try:
            metas.append(apply_privacy_zone(read_meta(p), privacy_zone))
        except Exception as exc:  # corrupt or unsupported file: report it, keep going
            unreadable.append((p.name, f"{exc.__class__.__name__}: {exc}"))
    metas.sort(key=lambda m: m.taken)

    entries: list[Entry] = []
    for i, meta in enumerate(metas, 1):
        if progress:
            progress(i, len(metas), meta.path)
        thumb_rel = f"thumbs/{i:03d}.jpg"
        (out / thumb_rel).write_bytes(resized_jpeg(meta.path, THUMB_SIDE))
        obs, err = None, None
        try:
            obs = backend.observe(resized_jpeg(meta.path, MODEL_SIDE))
        except (BackendError, ValueError) as exc:
            err = str(exc)
        entries.append(Entry(meta, thumb_rel, obs, err))
    return Journal(entries, walk_stats(metas), backend.name, unreadable)
