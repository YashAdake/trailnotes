from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import BackendError, MockBackend, OllamaBackend
from .photos import find_photos, find_unsupported, read_meta
from .pipeline import NoPhotosFound, build_journal
from .render import write_all


def _zone(text: str) -> tuple[float, float, float]:
    try:
        lat, lon, radius = (float(x) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("use LAT,LON,METRES, e.g. 18.5204,73.8567,400") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not 0 < radius <= 50_000:
        raise argparse.ArgumentTypeError("latitude, longitude or radius out of range")
    return lat, lon, radius


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trailnotes", description=__doc__)
    p.add_argument("photos", type=Path, help="folder of walk photos (searched recursively)")
    p.add_argument("-o", "--out", type=Path, default=Path("journal"), help="output folder")
    p.add_argument("--title", default="Field notes", help="journal title")
    p.add_argument("--model", default="qwen2.5vl:7b", help="Ollama vision model")
    p.add_argument("--host", default="http://localhost:11434", help="Ollama URL")
    p.add_argument("--mock", action="store_true", help="no model: test the pipeline without a GPU")
    p.add_argument("--check", action="store_true", help="only list each photo's time and GPS; no model, no journal")
    p.add_argument(
        "--privacy-zone",
        type=_zone,
        metavar="LAT,LON,METRES",
        help="remove the location of photos taken within this radius (e.g. around home)",
    )
    return p


def _check(folder: Path) -> int:
    photos = find_photos(folder)
    if not photos:
        print(f"error: no readable photos under {folder}", file=sys.stderr)
        return 2
    with_gps = timed = 0
    for path in photos:
        try:
            m = read_meta(path)
        except Exception as exc:  # report, do not hide, a file we cannot open
            print(f"{path.name:32} UNREADABLE  {exc.__class__.__name__}")
            continue
        with_gps += m.lat is not None
        timed += m.time_source == "exif"
        gps = f"{m.lat:.5f}, {m.lon:.5f}" if m.lat is not None else "no GPS"
        when = m.taken.strftime("%d %b %H:%M") if m.time_source == "exif" else "no camera time"
        print(f"{path.name:32} {when:16} {gps}")
    print(f"\n{len(photos)} photos: {with_gps} with GPS, {timed} with a camera timestamp")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.photos.is_dir():
        print(f"error: {args.photos} is not a folder", file=sys.stderr)
        return 2
    unsupported = find_unsupported(args.photos)
    if unsupported:
        names = ", ".join(p.name for p in unsupported[:5]) + (" ..." if len(unsupported) > 5 else "")
        print(
            f"warning: {len(unsupported)} file(s) in formats trailnotes cannot read were ignored "
            f"({names}). Export them as JPEG first.",
            file=sys.stderr,
        )
    if args.check:
        return _check(args.photos)
    backend = MockBackend() if args.mock else OllamaBackend(args.model, args.host)

    def progress(i: int, total: int, path: Path) -> None:
        print(f"[{i}/{total}] {path.name}", flush=True)

    try:
        journal = build_journal(args.photos, args.out, backend, progress, args.privacy_zone)
    except NoPhotosFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    page = write_all(journal, args.out, args.title)
    failed = sum(1 for e in journal.entries if e.observation is None)
    print(f"\n{len(journal.entries) - failed} described, {failed} failed, {len(journal.unreadable)} unreadable")
    hidden = sum(1 for e in journal.entries if e.meta.location_hidden)
    if args.privacy_zone is not None:
        print(f"{hidden} photo(s) inside the privacy zone: location removed")
    print(f"Open: {page.resolve()}")
    # Every photo failing means the journal says nothing: do not report success.
    return 1 if journal.entries and failed == len(journal.entries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
