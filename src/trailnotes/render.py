"""Write journal.html, journal.md and journal.json. Model output is untrusted: every string is escaped."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .pipeline import Entry, Journal

_CSS = """
:root{--bg:#f4efe4;--ink:#2b2a26;--muted:#6b665a;--card:#fffdf7;--line:#d9d0bb;--accent:#3f6b4a;--warn:#a4452c}
@media(prefers-color-scheme:dark){:root{--bg:#1b1f1a;--ink:#ece6d6;--muted:#a39d8c;--card:#242a22;--line:#39402f;--accent:#8fc39a;--warn:#e08a6f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 Georgia,'Iowan Old Style',serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:2.2rem;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 24px}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 24px;padding:0;list-style:none}
.stats li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px}
.stats b{display:block;font-size:1.3rem;color:var(--accent)}
#map{height:320px;border:1px solid var(--line);border-radius:12px;margin:0 0 32px}
.entry{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin:0 0 24px}
.entry img{display:block;width:100%;height:auto}
.body{padding:16px 20px 20px}.body h2{margin:0 0 2px;font-size:1.3rem}
.meta{color:var(--muted);font:13px/1.4 ui-monospace,Consolas,monospace;margin:0 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0;padding:0;list-style:none}
.chips li{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:14px}
.chips .low{border-style:dashed;color:var(--muted)}
.failed{color:var(--warn)}
footer{color:var(--muted);font-size:14px;margin-top:32px}
"""

_MAP_JS = """
const points = JSON.parse(document.getElementById('points').textContent);
if (points.length && window.L) {
  const map = L.map('map');
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    {maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
  const latlngs = points.map(p => [p.lat, p.lon]);
  L.polyline(latlngs, {color: '#3f6b4a', weight: 3, opacity: 0.7}).addTo(map);
  points.forEach(p => {
    const el = document.createElement('div');
    const b = document.createElement('b'); b.textContent = p.n + '. ' + p.title;
    el.appendChild(b);
    L.marker([p.lat, p.lon]).addTo(map).bindPopup(el);
  });
  map.fitBounds(latlngs, {padding: [30, 30], maxZoom: 17});
} else {
  document.getElementById('map').hidden = true;
}
"""


def _when(entry: Entry) -> str:
    t = entry.meta.taken.strftime("%d %b %Y, %H:%M")
    return t if entry.meta.time_source == "exif" else f"{t} (file time, no camera timestamp)"


def _where(entry: Entry) -> str:
    m = entry.meta
    return f"{m.lat:.5f}, {m.lon:.5f}" if m.lat is not None else "no GPS in this photo"


def _entry_html(n: int, e: Entry) -> str:
    o = e.observation
    if o is None:
        head = '<h2 class="failed">Model could not describe this photo</h2>'
        text = f'<p class="failed">{escape(e.error or "unknown error")}</p>'
        chips = ""
    else:
        head = f"<h2>{n}. {escape(o.title)}</h2>"
        text = f"<p>{escape(o.description)}</p>"
        terrain = f"<p class='meta'>Terrain: {escape(o.terrain)}</p>" if o.terrain else ""
        items = "".join(
            f'<li class="{escape(t["confidence"])}">{escape(t["name"])} · {escape(t["confidence"])}</li>'
            for t in o.living_things
        )
        chips = terrain + (f'<ul class="chips">{items}</ul>' if items else "")
    return (
        f'<article class="entry"><img src="{escape(e.thumb)}" alt="{escape(o.title if o else "Photo " + str(n))}" loading="lazy">'
        f'<div class="body">{head}<p class="meta">{escape(_when(e))} · {escape(_where(e))}</p>{text}{chips}</div></article>'
    )


def _points(j: Journal) -> list[dict]:
    return [
        {"n": n, "lat": e.meta.lat, "lon": e.meta.lon, "title": e.observation.title if e.observation else "Photo"}
        for n, e in enumerate(j.entries, 1)
        if e.meta.lat is not None
    ]


def render_html(j: Journal, title: str) -> str:
    s = j.stats
    stats = ""
    if s:
        dist = (
            f"<li><b>≥ {s.min_distance_km:.2f} km</b>straight-line between geotagged photos</li>"
            if s.geotagged >= 2
            else ""
        )
        stats = (
            f"<ul class='stats'><li><b>{s.photos}</b>photos</li>"
            f"<li><b>{s.duration_minutes} min</b>first to last photo</li>"
            f"<li><b>{s.geotagged}</b>with GPS</li>{dist}</ul>"
        )
    # "<" is escaped so no photo-derived string can close the script tag.
    points = json.dumps(_points(j)).replace("<", "\\u003c")
    entries = "".join(_entry_html(n, e) for n, e in enumerate(j.entries, 1))
    failed = sum(1 for e in j.entries if e.observation is None)
    note = f" {failed} of {len(j.entries)} photos could not be described." if failed else ""
    skipped = (
        f" {len(j.unreadable)} file(s) could not be opened and are not in this journal."
        if j.unreadable
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>{_CSS}</style></head>
<body><main><h1>{escape(title)}</h1>
<p class="sub">A field journal written by a model running on this computer ({escape(j.backend)}). Identifications are guesses; dashed chips mean the model said it was unsure.</p>
{stats}<div id="map"></div>{entries}
<footer>Photos and descriptions never left this machine.{escape(note)}{escape(skipped)}</footer></main>
<script id="points" type="application/json">{points}</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>{_MAP_JS}</script></body></html>"""


def render_markdown(j: Journal, title: str) -> str:
    lines = [f"# {title}", "", f"_Written locally by {j.backend}. Identifications are guesses._", ""]
    for n, e in enumerate(j.entries, 1):
        o = e.observation
        lines.append(f"## {n}. {o.title if o else 'Could not be described'}")
        lines.append(f"*{_when(e)} · {_where(e)}*")
        lines.append("")
        lines.append(o.description if o else f"Failed: {e.error}")
        if o and o.living_things:
            lines.append("")
            lines.append("Seen: " + ", ".join(f"{t['name']} ({t['confidence']})" for t in o.living_things))
        lines.append("")
    return "\n".join(lines)


def render_json(j: Journal) -> str:
    return json.dumps(
        {
            "backend": j.backend,
            "unreadable": j.unreadable,
            "entries": [
                {
                    "photo": e.meta.path.name,
                    "taken": e.meta.taken.isoformat(),
                    "time_source": e.meta.time_source,
                    "lat": e.meta.lat,
                    "lon": e.meta.lon,
                    "observation": vars(e.observation) if e.observation else None,
                    "error": e.error,
                }
                for e in j.entries
            ],
        },
        indent=2,
    )


def write_all(j: Journal, out: Path, title: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render_html(j, title), encoding="utf-8")
    (out / "journal.md").write_text(render_markdown(j, title), encoding="utf-8")
    (out / "journal.json").write_text(render_json(j), encoding="utf-8")
    return out / "index.html"
