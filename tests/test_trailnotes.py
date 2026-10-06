import json

import pytest

from conftest import make_photo
from trailnotes.cli import main
from trailnotes.geo import haversine_km, walk_stats
from trailnotes.model import BackendError, Observation, parse_observation
from trailnotes.photos import find_photos, read_meta
from trailnotes.pipeline import NoPhotosFound, build_journal
from trailnotes.render import render_html


# ---- metadata -------------------------------------------------------------

def test_reads_exif_time_and_gps(tmp_path):
    p = make_photo(tmp_path / "x.jpg", taken="2026:10:11 07:10:00", gps=(18.52, 73.85))
    m = read_meta(p)
    assert m.time_source == "exif"
    assert m.taken.hour == 7 and m.taken.minute == 10
    assert m.lat == pytest.approx(18.52, abs=1e-4)
    assert m.lon == pytest.approx(73.85, abs=1e-4)


def test_southern_and_western_hemispheres_are_negative(tmp_path):
    p = make_photo(tmp_path / "x.jpg", taken="2026:10:11 07:10:00", gps=(-33.86, -151.2))
    m = read_meta(p)
    assert m.lat < 0 and m.lon < 0


def test_missing_exif_falls_back_to_file_time_and_says_so(tmp_path):
    p = make_photo(tmp_path / "x.jpg", taken=None, gps=None)
    m = read_meta(p)
    assert m.time_source == "file-modified" and m.lat is None


def test_null_island_gps_is_treated_as_missing(tmp_path):
    p = make_photo(tmp_path / "x.jpg", taken="2026:10:11 07:10:00", gps=(0.0, 0.0))
    assert read_meta(p).lat is None


# ---- geo ------------------------------------------------------------------

def test_haversine_known_distance():
    # Pune to Mumbai is ~120 km by air.
    assert 115 < haversine_km(18.5204, 73.8567, 19.0760, 72.8777) < 125


def test_walk_stats_orders_by_time_not_filename(walk_dir):
    metas = [read_meta(p) for p in find_photos(walk_dir)]
    s = walk_stats(metas)
    assert s.photos == 3 and s.geotagged == 2
    assert s.duration_minutes == 55
    assert s.min_distance_km == pytest.approx(1.11, abs=0.05)


# ---- model output parsing -------------------------------------------------

def test_parse_clean_and_fenced_json():
    raw = '{"title":"Fig tree","description":"A fig.","terrain":"path","living_things":[{"name":"fig","confidence":"high"}]}'
    assert parse_observation(raw).living_things[0]["confidence"] == "high"
    assert parse_observation(f"```json\n{raw}\n```").title == "Fig tree"


def test_parse_unknown_confidence_degrades_to_low():
    o = parse_observation('{"title":"t","description":"d","living_things":[{"name":"owl","confidence":"certain"}]}')
    assert o.living_things == [{"name": "owl", "confidence": "low"}]


@pytest.mark.parametrize("bad", ["", "I cannot help with that.", "[1,2]", '{"title":"","description":""}'])
def test_parse_rejects_unusable_output(bad):
    with pytest.raises(ValueError):
        parse_observation(bad)


# ---- pipeline + rendering -------------------------------------------------

class Fake:
    name = "fake"

    def __init__(self, fail_on=()):
        self.calls = 0
        self.fail_on = set(fail_on)

    def preflight(self):
        pass

    def observe(self, jpeg):
        self.calls += 1
        if self.calls in self.fail_on:
            raise ValueError("model returned junk")
        return Observation("Entry %d" % self.calls, "desc", "path", [{"name": "tree", "confidence": "low"}])


def test_empty_folder_is_an_error_not_an_empty_journal(tmp_path):
    with pytest.raises(NoPhotosFound):
        build_journal(tmp_path, tmp_path / "out", Fake())


def test_failed_photo_is_kept_and_shown_as_failed(walk_dir, tmp_path):
    j = build_journal(walk_dir, tmp_path / "out", Fake(fail_on={2}))
    assert [e.observation is None for e in j.entries] == [False, True, False]
    html = render_html(j, "T")
    assert "Model could not describe this photo" in html
    assert "1 of 3 photos could not be described" in html


def test_corrupt_file_is_reported_not_swallowed(walk_dir, tmp_path):
    (walk_dir / "broken.jpg").write_bytes(b"not an image")
    j = build_journal(walk_dir, tmp_path / "out", Fake())
    assert [name for name, _ in j.unreadable] == ["broken.jpg"]
    assert len(j.entries) == 3
    assert "could not be opened" in render_html(j, "T")


def test_model_output_cannot_inject_html_or_close_the_data_script(walk_dir, tmp_path):
    class Evil(Fake):
        def observe(self, jpeg):
            return Observation(
                '</script><script>alert(2)</script><img src=x onerror=alert(1)>',
                '</script><script>alert(2)</script>',
                '"><b>',
                [{"name": "<svg onload=alert(3)>", "confidence": "low"}],
            )

    j = build_journal(walk_dir, tmp_path / "out", Evil())
    html = render_html(j, "<b>title</b>")
    for needle in ("<img src=x", "<svg onload", "<script>alert", "<b>title"):
        assert needle not in html
    # the only </script> tags are the three we wrote ourselves
    assert html.count("</script>") == 3


# ---- CLI, end to end through the real interface ---------------------------

def test_cli_mock_end_to_end(walk_dir, tmp_path, capsys):
    out = tmp_path / "journal"
    assert main([str(walk_dir), "-o", str(out), "--mock", "--title", "Sunday walk"]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Sunday walk" in html and "Mock entry" in html
    data = json.loads((out / "journal.json").read_text(encoding="utf-8"))
    assert len(data["entries"]) == 3
    assert [e["photo"] for e in data["entries"]] == ["a.jpg", "b.jpg", "c.jpg"]
    assert len(list((out / "thumbs").glob("*.jpg"))) == 3
    assert (out / "journal.md").exists()


def test_cli_exit_codes(tmp_path):
    assert main([str(tmp_path / "nope"), "--mock"]) == 2
    assert main([str(tmp_path), "-o", str(tmp_path / "o"), "--mock"]) == 2  # no photos


def test_cli_fails_loudly_when_ollama_is_unreachable(walk_dir, tmp_path, capsys):
    rc = main([str(walk_dir), "-o", str(tmp_path / "o"), "--host", "http://127.0.0.1:9"])
    assert rc == 3
    assert "Cannot reach Ollama" in capsys.readouterr().err
