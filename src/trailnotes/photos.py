"""Read photo metadata (time, GPS) and produce resized JPEGs."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
# Photo formats phones produce that we do not read. They are reported, never silently dropped.
UNSUPPORTED_SUFFIXES = {".heic", ".heif", ".dng", ".tif", ".tiff", ".bmp", ".gif"}

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 36867


@dataclass(frozen=True)
class PhotoMeta:
    path: Path
    taken: datetime
    time_source: str  # "exif" or "file-modified": the difference is shown to the reader
    lat: float | None
    lon: float | None
    # True when the photo had GPS but it fell inside the user's privacy zone and was removed.
    location_hidden: bool = False


def find_photos(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def find_unsupported(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in UNSUPPORTED_SUFFIXES
    )


def _to_degrees(value, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if str(ref).upper() in ("S", "W"):
        deg = -deg
    return deg


def _valid_coord(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    # (0, 0) is what many cameras write when they have no fix. Treat it as missing.
    return not (lat == 0 and lon == 0)


def read_meta(path: Path) -> PhotoMeta:
    taken: datetime | None = None
    lat = lon = None
    with Image.open(path) as im:
        exif = im.getexif()
        raw = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(306)
        if raw:
            try:
                taken = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                taken = None
        gps = exif.get_ifd(_GPS_IFD)
        if gps:
            lat = _to_degrees(gps.get(2), gps.get(1))
            lon = _to_degrees(gps.get(4), gps.get(3))
    if not _valid_coord(lat, lon):
        lat = lon = None
    if taken is not None:
        return PhotoMeta(path, taken, "exif", lat, lon)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(tzinfo=None)
    return PhotoMeta(path, mtime, "file-modified", lat, lon)


def resized_jpeg(path: Path, max_side: int, quality: int = 85) -> bytes:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()
