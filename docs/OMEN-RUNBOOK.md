# OMEN runbook: real-model checks

Code is written and unit-tested on the build PC (no GPU). Everything that needs the model runs here, on the OMEN. Report results back as pasted output or screenshots.

## 0. One-time setup

```powershell
ollama pull qwen2.5vl:7b
git clone <repo-url> ; cd trailnotes
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest            # expect: 41 passed
```

## 1. Real walk (needed for the challenge's outdoor bonus)

1. Go for a walk. Take 10 to 20 photos on your phone with location turned on for the camera app.
2. Copy them to the OMEN. If your transfer app strips location, the journal will have no map. Check that a photo shows GPS under Properties > Details.
3. Look before you run the model: `trailnotes C:\path\to\photos --check` shows which photos have GPS and a camera time.
4. `trailnotes C:\path\to\photos -o journal --title "Pune walk"`
5. Open `journal\index.html`.

## 2. What to check and report

- Did Ollama answer? (If not, the error says what to run.)
- Seconds per photo (the console prints progress; time the whole run).
- Is the map right (pins where you actually stood)?
- Which model identifications were correct, wrong, or plain made up? Write down at least two of each. The post should include a wrong one.
- Any entry marked failed, and the reason shown.
- A screenshot of the page, and a 30 to 60 second screen recording of it for the DEV post's Demo section.

## 3. If qwen2.5vl:7b is too slow or too weak

`ollama list` to see what you have, then try another vision model with `--model`. Tell me which and what happened.

## Privacy before you publish anything

Photos from a walk near home reveal your location. Before publishing a screenshot or journal, check that the map is not showing your home, and crop it or use photos from elsewhere. Do not push `journal/` or your photos to the repo.
