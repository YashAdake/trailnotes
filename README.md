# Trailnotes

Turn a folder of walk photos into a field journal. A vision model running on **your own computer** looks at each photo, and Trailnotes adds the time and GPS from the photo's own metadata. You get a map, a timeline, walk stats and a journal you can read offline. No photo, location or description leaves the machine.

Built for the Hacktoberfest 2026 "Touch Grass" challenge: open-weight AI that gets you out of the house and then helps you remember what you saw.

## Why local matters here

Your walk photos carry your exact GPS position, your routine and often your home. Sending those to a hosted vision API means handing that over. With an open-weight model on your own GPU, the photos never go anywhere, it works without a signal after the model is downloaded, it costs nothing per photo, and you can swap the model for any other vision model Ollama supports with one flag.

## Run it

Requirements: Python 3.10+, [Ollama](https://ollama.com), a GPU with about 6 GB free VRAM (CPU works, but slowly).

```powershell
ollama pull gemma3:4b
git clone <this repo> ; cd trailnotes
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

trailnotes C:\path\to\walk-photos -o journal --title "Sunday walk"
```

Then open `journal\index.html`. The folder also contains `journal.md` and `journal.json`.

Try the pipeline with no model at all: `trailnotes C:\path\to\photos --mock`. The mock journal is labelled as mock.

No photos of your own yet? `python scripts/fetch_sample.py` downloads a few free-licensed, geotagged photos from Wikimedia Commons into `samples/` (git-ignored) with a `CREDITS.md` of authors and licences. These are for testing and demos only: they are not one walk, the GPS is written in from Commons coordinates rather than a camera, and the journal says "not one walk" when the photos span more than a day. Do not present a sample journal as a walk you took.

Options: `--model` (any Ollama vision model), `--host` (Ollama URL), `--title`, `-o`.

## What it does, and what it does not claim

- **Time and place** come from each photo's EXIF data. If a photo has no camera timestamp, the file time is used and the journal says so. Photos with no GPS simply have no pin. A (0, 0) GPS fix is treated as missing.
- **Distance** is the straight-line total between consecutive geotagged photos, shown as "≥ x km", a lower bound on what you walked.
- **Identifications are the model's guesses.** Each living thing carries the model's own confidence, and "low" is drawn with a dashed outline. Trailnotes does not turn a guess into a fact.
- **Failures are visible.** If the model returns junk for a photo, that entry appears as failed with the reason, and the footer counts them. A photo that cannot be opened at all is listed as unreadable. If every photo fails, the command exits non-zero. A folder with no photos is an error, not an empty journal.
- **Model output is treated as untrusted.** Everything is HTML-escaped and the map data cannot break out of its script tag. The tests prove this by deliberately injecting markup.

## Tests

```powershell
python -m pytest
```

20 tests, including an end-to-end run through the real CLI and checks that were confirmed to fail when the escaping was removed. The Ollama backend itself can only be checked against a real model, so that is a manual step: see `docs/OMEN-RUNBOOK.md`.

## Layout

```
src/trailnotes/
  photos.py    EXIF time/GPS, resized JPEGs
  geo.py       haversine distance, walk stats
  model.py     Ollama backend, mock backend, output parser
  pipeline.py  folder -> Journal
  render.py    HTML / Markdown / JSON
  cli.py       command line
tests/
```

## License

MIT
