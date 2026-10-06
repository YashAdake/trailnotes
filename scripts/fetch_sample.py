"""Download a small sample set of free-licensed, geotagged photos from Wikimedia Commons.

This is for testing and demos only. The photos are NOT one walk: they were taken by
different people on different days. Do not present the result as a walk you took.
Images are written to samples/ (git-ignored) with a CREDITS.md listing author and licence.

    python scripts/fetch_sample.py --lat 18.5204 --lon 73.8567 --count 12
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "trailnotes-sample-fetcher/0.1 (https://github.com/YashAdake/trailnotes)"}
# Only licences that allow reuse with credit. Anything else is skipped, not guessed at.
OK_LICENCES = re.compile(r"^(CC0|CC BY(-SA)? \d\.\d|Public domain)", re.I)
ISO_TIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$")


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _dms(v: float):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    return (d, m, round((v - d - m / 60) * 3600, 4))


def fetch(lat: float, lon: float, count: int, radius: int, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        resp = requests.get(
            API, headers=HEADERS, timeout=30,
            params={"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}",
                    "gsradius": radius, "gsnamespace": 6, "gslimit": 50, "format": "json"},
        ).json()
        if "query" in resp or resp.get("error", {}).get("code") != "cirrussearch-too-busy-error":
            break
        time.sleep(3 * (attempt + 1))  # Commons search is sometimes briefly overloaded
    if "query" not in resp:
        print(f"Commons API error: {resp.get('error', resp)}", file=sys.stderr)
        return 0
    hits = resp["query"]["geosearch"]
    if not hits:
        print("No geotagged Commons files in that radius.", file=sys.stderr)
        return 0
    coords = {h["title"]: (h["lat"], h["lon"]) for h in hits}
    credits, saved = [], 0
    titles = list(coords)
    for i in range(0, len(titles), 40):
        batch = titles[i : i + 40]
        pages = requests.get(
            API, headers=HEADERS, timeout=30,
            params={"action": "query", "titles": "|".join(batch), "prop": "imageinfo",
                    "iiprop": "url|extmetadata|mime", "iiurlwidth": 1280, "format": "json"},
        ).json()["query"]["pages"]
        for page in pages.values():
            if saved >= count:
                break
            info = (page.get("imageinfo") or [None])[0]
            if not info or info["mime"] != "image/jpeg":
                continue
            md = info["extmetadata"]
            licence = md.get("LicenseShortName", {}).get("value", "")
            if not OK_LICENCES.match(licence):
                continue
            img = requests.get(info.get("thumburl") or info["url"], headers=HEADERS, timeout=60)
            if img.status_code != 200:
                continue
            title = page["title"]
            glat, glon = coords[title]
            with Image.open(io.BytesIO(img.content)) as im:
                exif = Image.Exif()
                g = exif.get_ifd(0x8825)
                g[1], g[2] = ("N" if glat >= 0 else "S"), _dms(glat)
                g[3], g[4] = ("E" if glon >= 0 else "W"), _dms(glon)
                m = ISO_TIME.match(md.get("DateTimeOriginal", {}).get("value", ""))
                if m:
                    exif.get_ifd(0x8769)[36867] = "{}:{}:{} {}:{}:{}".format(*m.groups())
                saved += 1
                im.convert("RGB").save(out / f"{saved:02d}.jpg", "JPEG", exif=exif, quality=90)
            credits.append(
                f"- `{saved:02d}.jpg`: {title.removeprefix('File:')} by "
                f"{_strip_html(md.get('Artist', {}).get('value', 'unknown'))}, {licence}, "
                f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}"
            )
    (out / "CREDITS.md").write_text(
        "# Sample photo credits\n\nGPS written into each file from Wikimedia Commons coordinates, "
        "not from a camera. Timestamps only where Commons had an exact one.\n\n" + "\n".join(credits) + "\n",
        encoding="utf-8",
    )
    return saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=18.5204)
    ap.add_argument("--lon", type=float, default=73.8567)
    ap.add_argument("--radius", type=int, default=10000, help="metres, max 10000")
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--out", type=Path, default=Path("samples"))
    a = ap.parse_args()
    n = fetch(a.lat, a.lon, a.count, a.radius, a.out)
    print(f"Saved {n} photos to {a.out}/ (see CREDITS.md)")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
