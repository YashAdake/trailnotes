from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import BackendError, MockBackend, OllamaBackend
from .pipeline import NoPhotosFound, build_journal
from .render import write_all


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trailnotes", description=__doc__)
    p.add_argument("photos", type=Path, help="folder of walk photos (searched recursively)")
    p.add_argument("-o", "--out", type=Path, default=Path("journal"), help="output folder")
    p.add_argument("--title", default="Field notes", help="journal title")
    p.add_argument("--model", default="qwen2.5vl:7b", help="Ollama vision model")
    p.add_argument("--host", default="http://localhost:11434", help="Ollama URL")
    p.add_argument("--mock", action="store_true", help="no model: test the pipeline without a GPU")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.photos.is_dir():
        print(f"error: {args.photos} is not a folder", file=sys.stderr)
        return 2
    backend = MockBackend() if args.mock else OllamaBackend(args.model, args.host)

    def progress(i: int, total: int, path: Path) -> None:
        print(f"[{i}/{total}] {path.name}", flush=True)

    try:
        journal = build_journal(args.photos, args.out, backend, progress)
    except NoPhotosFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    page = write_all(journal, args.out, args.title)
    failed = sum(1 for e in journal.entries if e.observation is None)
    print(f"\n{len(journal.entries) - failed} described, {failed} failed, {len(journal.unreadable)} unreadable")
    print(f"Open: {page.resolve()}")
    # Every photo failing means the journal says nothing: do not report success.
    return 1 if journal.entries and failed == len(journal.entries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
