from pathlib import Path

import pytest
from PIL import Image


def make_photo(path: Path, *, taken: str | None, gps: tuple[float, float] | None, color=(60, 140, 70)):
    """Write a JPEG with real EXIF bytes, the way a phone would."""
    im = Image.new("RGB", (400, 300), color)
    exif = Image.Exif()
    if taken:
        exif_ifd = exif.get_ifd(0x8769)
        exif_ifd[36867] = taken
    if gps:
        lat, lon = gps
        g = exif.get_ifd(0x8825)

        def dms(v: float):
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round((v - d - m / 60) * 3600, 4)
            return (d, m, s)

        g[1] = "N" if lat >= 0 else "S"
        g[2] = dms(lat)
        g[3] = "E" if lon >= 0 else "W"
        g[4] = dms(lon)
    im.save(path, "JPEG", exif=exif)
    return path


@pytest.fixture
def walk_dir(tmp_path: Path) -> Path:
    d = tmp_path / "walk"
    d.mkdir()
    # Pune area, ~1.1 km apart north-south; written out of order on purpose.
    make_photo(d / "b.jpg", taken="2026:10:11 07:40:00", gps=(18.5300, 73.8500))
    make_photo(d / "a.jpg", taken="2026:10:11 07:10:00", gps=(18.5200, 73.8500))
    make_photo(d / "c.jpg", taken="2026:10:11 08:05:00", gps=None)
    return d
