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


# ---- Ollama backend (HTTP faked: no GPU needed) ---------------------------

class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._c}}


GOOD = '{"title":"Tree","living_things":[{"name":"fig","confidence":"high"}],"terrain":"path","description":"A fig tree."}'
RUNAWAY = '{"title":"x","living_things":[' + ",".join(['{"name":"bird","confidence":"low"}'] * 400)  # cut off, no closing


def _backend_with(monkeypatch, replies):
    from trailnotes import model

    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return _Resp(replies[len(calls) - 1])

    monkeypatch.setattr(model.requests, "post", fake_post)
    return model.OllamaBackend("m"), calls


def test_runaway_output_is_retried_once_then_succeeds(monkeypatch):
    b, calls = _backend_with(monkeypatch, [RUNAWAY, GOOD])
    assert b.observe(b"img").title == "Tree"
    assert len(calls) == 2


def test_two_unusable_outputs_become_a_failure_not_garbage(monkeypatch):
    b, calls = _backend_with(monkeypatch, [RUNAWAY, RUNAWAY])
    with pytest.raises(ValueError, match="after 2 attempts"):
        b.observe(b"img")
    assert len(calls) == 2


def test_request_bounds_output_length_and_list_size(monkeypatch):
    b, calls = _backend_with(monkeypatch, [GOOD])
    b.observe(b"img")
    sent = calls[0]
    assert sent["options"]["num_predict"] <= 1000
    assert sent["format"]["properties"]["living_things"]["maxItems"] <= 12


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
    # the only </script> tags are the four we wrote ourselves (points, tiles, leaflet, map code)
    assert html.count("</script>") == 4


def test_photos_months_and_cities_apart_report_no_distance(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2026:04:14 13:24:00", gps=(16.78, 74.55))  # Kolhapur
    make_photo(d / "b.jpg", taken="2026:10:06 21:00:00", gps=(18.58, 73.81))  # Pune, 6 months later
    s = walk_stats([read_meta(p) for p in find_photos(d)])
    assert s.min_distance_km == 0 and s.linked_pairs == 0
    html = render_html(build_journal(d, tmp_path / "o", Fake()), "T")
    assert "straight-line" not in html


def test_distance_counts_only_pairs_within_three_hours(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2026:10:11 07:00:00", gps=(18.52, 73.85))
    make_photo(d / "b.jpg", taken="2026:10:11 07:30:00", gps=(18.53, 73.85))  # ~1.1 km, linked
    make_photo(d / "c.jpg", taken="2026:10:11 20:00:00", gps=(19.00, 73.85))  # 12 h later: not linked
    s = walk_stats([read_meta(p) for p in find_photos(d)])
    assert s.linked_pairs == 1
    assert s.min_distance_km == pytest.approx(1.11, abs=0.05)


def test_map_points_carry_time_so_route_lines_can_break(walk_dir, tmp_path):
    html = render_html(build_journal(walk_dir, tmp_path / "o", Fake()), "T")
    assert '"t": ' in html and "10800" in html


def test_file_time_photos_do_not_stretch_the_walk_span(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2026:10:11 07:00:00", gps=(18.5, 73.8))
    make_photo(d / "b.jpg", taken="2026:10:11 07:30:00", gps=(18.5, 73.8))
    make_photo(d / "c.jpg", taken=None, gps=None)  # file time = now, years later
    s = walk_stats([read_meta(p) for p in find_photos(d)])
    assert s.duration_minutes == 30
    assert (s.photos, s.timed) == (3, 2)
    html = render_html(build_journal(d, tmp_path / "o", Fake()), "T")
    assert "30 min" in html and "without a camera timestamp" in html


def test_no_span_claimed_with_fewer_than_two_timestamps(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2026:10:11 07:00:00", gps=None)
    make_photo(d / "b.jpg", taken=None, gps=None)
    s = walk_stats([read_meta(p) for p in find_photos(d)])
    assert s.duration_minutes is None
    assert "min</b>" not in render_html(build_journal(d, tmp_path / "o", Fake()), "T")


def test_leaked_confidence_note_is_removed_and_truncation_is_marked():
    o = parse_observation(
        '{"title":"t","description":"Pigeons on a tree (confidence: medium).","terrain":"%s","living_things":[]}'
        % ("x" * 300)
    )
    assert "confidence" not in o.description and o.description == "Pigeons on a tree."
    assert o.terrain.endswith("…") and len(o.terrain) == 120


def test_photos_years_apart_are_not_called_a_walk(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2013:02:05 22:58:28", gps=(18.5, 73.8))
    make_photo(d / "b.jpg", taken="2026:09:24 10:00:00", gps=(18.6, 73.9))
    html = render_html(build_journal(d, tmp_path / "o", Fake()), "T")
    assert "not one walk" in html and "first to last photo" not in html


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


def test_check_mode_lists_gps_and_time_without_any_model(walk_dir, capsys):
    make_photo(walk_dir / "nogps.jpg", taken="2026:10:11 09:00:00", gps=None)
    make_photo(walk_dir / "notime.jpg", taken=None, gps=None)
    assert main([str(walk_dir), "--check"]) == 0
    out = capsys.readouterr().out
    assert "5 photos: 2 with GPS, 4 with a camera timestamp" in out
    notime = next(line for line in out.splitlines() if line.startswith("notime.jpg"))
    assert "no camera time" in notime and "no GPS" in notime


def test_heic_files_are_reported_not_silently_dropped(walk_dir, capsys):
    (walk_dir / "IMG_0001.HEIC").write_bytes(b"x")
    assert main([str(walk_dir), "--check"]) == 0
    err = capsys.readouterr().err
    assert "IMG_0001.HEIC" in err and "JPEG" in err


def test_folder_of_only_heic_is_an_error_that_says_why(tmp_path, capsys):
    (tmp_path / "a.heic").write_bytes(b"x")
    assert main([str(tmp_path), "-o", str(tmp_path / "o"), "--mock"]) == 2
    assert "a.heic" in capsys.readouterr().err


def test_mixed_gps_journal_renders_pins_only_for_geotagged(walk_dir, tmp_path):
    out = tmp_path / "j"
    assert main([str(walk_dir), "-o", str(out), "--mock"]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert html.count("no GPS in this photo") == 1  # c.jpg only
    assert html.count('"lat": 18.5') == 2


HOME = (18.58104, 73.81828)


def _zone_walk(tmp_path):
    d = tmp_path / "zw"
    d.mkdir()
    make_photo(d / "a.jpg", taken="2026:10:08 18:06:00", gps=(18.58126, 73.81979))  # ~160 m from HOME
    make_photo(d / "b.jpg", taken="2026:10:08 18:15:00", gps=(18.58296, 73.82484))  # ~720 m away
    make_photo(d / "c.jpg", taken="2026:10:08 18:20:00", gps=(18.58271, 73.82355))  # ~590 m away
    return d


def test_privacy_zone_removes_location_everywhere_it_could_leak(tmp_path):
    d = _zone_walk(tmp_path)
    out = tmp_path / "j"
    assert main([str(d), "-o", str(out), "--mock", "--privacy-zone", f"{HOME[0]},{HOME[1]},400"]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    data = json.loads((out / "journal.json").read_text(encoding="utf-8"))
    # the hidden photo's coordinates appear nowhere: not in text, not in map data, not in JSON
    for needle in ("18.58126", "73.81979", "18.5812", "73.8197"):
        assert needle not in html
        assert needle not in json.dumps(data)
    assert "location hidden (inside privacy zone)" in html
    assert [e["location_hidden"] for e in data["entries"]] == [True, False, False]
    # the photos outside the zone still get pins
    assert html.count('"lat": 18.58') == 2


def test_privacy_zone_does_not_hide_photos_outside_it(tmp_path):
    d = _zone_walk(tmp_path)
    j = build_journal(d, tmp_path / "o", Fake(), privacy_zone=(HOME[0], HOME[1], 50))
    assert not any(e.meta.location_hidden for e in j.entries)


def test_hidden_photo_is_not_counted_in_distance(tmp_path):
    d = _zone_walk(tmp_path)
    j = build_journal(d, tmp_path / "o", Fake(), privacy_zone=(HOME[0], HOME[1], 400))
    assert j.stats.geotagged == 2 and j.stats.linked_pairs == 1


def test_thumbnails_carry_no_gps(walk_dir, tmp_path):
    from PIL import Image

    out = tmp_path / "j"
    build_journal(walk_dir, out, Fake())
    for thumb in (out / "thumbs").glob("*.jpg"):
        with Image.open(thumb) as im:
            assert not im.getexif().get_ifd(0x8825), f"{thumb.name} still has GPS"


@pytest.mark.parametrize("bad", ["18.5,73.8", "a,b,c", "95,73.8,100", "18.5,73.8,0"])
def test_bad_privacy_zone_is_rejected(walk_dir, bad):
    with pytest.raises(SystemExit) as exc:
        main([str(walk_dir), "--mock", "--privacy-zone", bad])
    assert exc.value.code == 2


def test_map_does_not_use_the_blocked_osm_tile_server(walk_dir, tmp_path):
    # tile.openstreetmap.org returns an "Access blocked" image to pages opened from a file
    html = render_html(build_journal(walk_dir, tmp_path / "o", Fake()), "T")
    assert "tile.openstreetmap.org" not in html
    assert "opentopomap.org" in html and "OpenStreetMap contributors" in html


def test_custom_tiles_flag_reaches_the_page(walk_dir, tmp_path):
    out = tmp_path / "j"
    url = "https://example.test/{z}/{x}/{y}.png"
    assert main([str(walk_dir), "-o", str(out), "--mock", "--tiles", url]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert url in html and "opentopomap" not in html


def test_cli_exit_codes(tmp_path):
    assert main([str(tmp_path / "nope"), "--mock"]) == 2
    assert main([str(tmp_path), "-o", str(tmp_path / "o"), "--mock"]) == 2  # no photos


def test_cli_fails_loudly_when_ollama_is_unreachable(walk_dir, tmp_path, capsys):
    rc = main([str(walk_dir), "-o", str(tmp_path / "o"), "--host", "http://127.0.0.1:9"])
    assert rc == 3
    assert "Cannot reach Ollama" in capsys.readouterr().err
