# Trailnotes

Turn a folder of walk photos into a field journal. A vision model running on **your own computer** looks at each photo, and Trailnotes adds the time and GPS from the photo's own metadata. You get a map, a timeline, walk stats and a journal. Your photos and the model's descriptions never leave the machine. One exception: opening the page loads the map library and map tiles from the internet, which tells those servers roughly which area you are looking at.

Built for the Hacktoberfest 2026 "Touch Grass" challenge: open-weight AI that gets you out of the house and then helps you remember what you saw.

## Why local matters here

Your walk photos carry your exact GPS position, your routine and often your home. Sending those to a hosted vision API means handing that over. With an open-weight model on your own GPU, the photos never go anywhere, it works without a signal after the model is downloaded, it costs nothing per photo, and you can swap the model for any other vision model Ollama supports with one flag.

## Run it

Requirements: Python 3.10+, [Ollama](https://ollama.com), a GPU with about 6 GB free VRAM (CPU works, but slowly).

```powershell
ollama pull qwen2.5vl:7b
git clone <this repo> ; cd trailnotes
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

trailnotes C:\path\to\walk-photos -o journal --title "Sunday walk"
```

Then open `journal\index.html`. The folder also contains `journal.md` and `journal.json`.

Check your photos first, with no model: `trailnotes C:\path	o\photos --check` lists each photo's camera time and GPS, so you can see which ones will get a map pin before spending minutes on the model. Formats: JPEG, PNG and WebP. iPhone HEIC files are not read: the tool warns and ignores them, so switch the camera to "Most Compatible" or export as JPEG. Photos sent through WhatsApp usually lose their GPS and time, so copy the originals over USB, Drive or Nearby Share instead.

Try the pipeline with no model at all: `trailnotes C:\path\to\photos --mock`. The mock journal is labelled as mock.

No photos of your own yet? `python scripts/fetch_sample.py` downloads a few free-licensed, geotagged photos from Wikimedia Commons into `samples/` (git-ignored) with a `CREDITS.md` of authors and licences. These are for testing and demos only: they are not one walk, the GPS is written in from Commons coordinates rather than a camera, and the journal says "not one walk" when the photos span more than a day. Do not present a sample journal as a walk you took.

Options: `--model` (any Ollama vision model), `--host` (Ollama URL), `--title`, `-o`.

## What it does, and what it does not claim

- **Time and place** come from each photo's EXIF data. If a photo has no camera timestamp, the file time is used and the journal says so. Photos with no GPS simply have no pin. A (0, 0) GPS fix is treated as missing.
- **Distance** is the straight-line total between consecutive geotagged photos, shown as "≥ x km", a lower bound on what you walked.
- **Identifications are the model's guesses.** Each living thing carries the model's own confidence, and "low" is drawn with a dashed outline. Trailnotes does not turn a guess into a fact.
- **Failures are visible.** If the model returns junk for a photo, that entry appears as failed with the reason, and the footer counts them. A photo that cannot be opened at all is listed as unreadable. If every photo fails, the command exits non-zero. A folder with no photos is an error, not an empty journal.
- **Model output is treated as untrusted.** Everything is HTML-escaped and the map data cannot break out of its script tag. The tests prove this by deliberately injecting markup.

## Known limits (seen in real runs)

Run on 12 geotagged Wikimedia Commons photos, on an RTX 5060 laptop GPU through Ollama. Several rounds of prompt changes are summarised here, not hidden.

| | `gemma3:4b`, first prompt | `qwen2.5vl:7b` (default), final prompt |
|---|---|---|
| Speed | about 4.8 s per photo | about 5.6 s per photo (67 s for 12) |
| Described | 12 of 12 | 12 of 12 on the latest run |
| Wrong guesses | Called an Indian cormorant and painted stork "Corvids" and "Grey Heron"; reported a "Squirrel" at *high* confidence on a gate covered in signs | None confirmed. A few high-confidence tree and species claims are unchecked against the photos |
| Misses | Listed food as living things; put sentences in the terrain field | Recall of plants is better but inconsistent (a tree mentioned in one run was absent in the next) |

How it got there: one earlier qwen run listed "water" and "mist" as living things and missed a dandelion. Reordering the schema fixed the misses but caused one runaway response (about 9,400 characters of repeated items, unparseable) for one photo. The schema now bounds list and string length, the response is capped, and unusable output is retried once. That failure has not been seen since, but only one clean run has been checked, so treat it as fixed on that evidence only.

The gemma column used an earlier prompt, so this is a rough comparison, not a benchmark. With 12 photos and a handful of runs, "none confirmed" means exactly that and no more. Output is not identical between runs.

- The model's confidence is its own opinion, not a measurement. Do not treat "high" as verified, especially species-level names.
- Text on signs in other scripts may be misread. Check it before quoting it.
- Sample-photo pins can sit on one city-center coordinate, because Commons only has that for some photos.

## Tests

```powershell
python -m pytest
```

30 tests, including an end-to-end run through the real CLI and checks that were confirmed to fail when the escaping was removed. The Ollama backend itself can only be checked against a real model, so that is a manual step: see `docs/OMEN-RUNBOOK.md`.

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
