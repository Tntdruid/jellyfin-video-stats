"""Checks that run on every push, so a broken version never reaches Home Assistant's store.

Jellyfin is replaced by small fakes that answer like the real API.
"""
import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import collector
import db
import images
import importer
import main
import progress
from config import Settings
from jellyfin import in_video_folder, set_channel, to_item

T = 10_000_000


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


ENDPOINTS = [
    "meta", "now", "latest", "summary", "timeline?bucket=day", "timeline?bucket=week", "timeline?bucket=month",
    "top?kind=series", "top?kind=movies", "top?kind=people", "top?kind=channels", "top?kind=videos",
    "genres", "heatmap", "tech", "recent", "insights", "progress", "progress?user=u2", "compare", "wrapped",
    "detail?kind=series&key=ser0&start=0", "detail?kind=movie&key=mov2&start=0",
    "detail?kind=person&key=Ida%20Lund&start=0", "detail?kind=channel&key=chan0&start=0", "export.csv",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_endpoint_answers(client, path):
    r = client.get(f"/api/{path}")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("rng", [0, 7, 30, 365])
def test_every_range_works_for_every_user(client, rng):
    start = 0 if not rng else int(datetime.now().timestamp()) - rng * 86400
    for user in ("", "u1", "u2"):
        for path in ("summary", "insights", "top?kind=series", "tech"):
            sep = "&" if "?" in path else "?"
            assert client.get(f"/api/{path}{sep}start={start}&user={user}").status_code == 200


def test_page_and_assets(client):
    assert "Videostatistik" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_summary_has_all_kinds(client):
    s = client.get("/api/summary?start=0").json()
    assert s["movies"] and s["episodes"] and s["videos"] and s["channels"]


def test_progress_lists_unseen_episodes(client):
    d = client.get("/api/detail?kind=series&key=ser0&start=0").json()
    assert d["progress"]["seen"] < d["progress"]["total"]
    assert any(not e["seen"] for e in d["list"])


# --- collector --------------------------------------------------------------

class FakeSessions:
    def __init__(self, playing, extra=None):
        self.playing, self.extra, self.pos, self.on, self.method = playing, extra or {}, 0, True, "DirectPlay"

    async def sessions(self):
        if not self.on:
            return []
        s = {"Id": "s", "UserId": "tu", "UserName": "Test", "Client": "Web", "DeviceName": "PC", "NowPlayingItem": self.playing,
             "PlayState": {"PositionTicks": int(self.pos * T), "PlayMethod": self.method}}
        if self.method == "Transcode":
            s["TranscodingInfo"] = {"IsVideoDirect": False, "TranscodeReasons": ["VideoCodecNotSupported"]}
        return [s]

    async def item(self, item_id, user_id):
        return self.extra.get(item_id, self.playing if item_id == self.playing["Id"] else None)

    async def image(self, item_id):
        return None


def run_play(fake, polls, transcode_at=None):
    c = collector.Collector(Settings(poll_interval=10), fake)
    now = [1_700_000_000.0]
    real = collector.time.time
    collector.time.time = lambda: now[0]
    try:
        async def go():
            for i in range(polls):
                fake.pos = i * 10
                if i == transcode_at:
                    fake.method = "Transcode"
                await c.poll()
                now[0] += 10
            fake.on = False
            await c.poll()
            await asyncio.sleep(0.05)
        asyncio.run(go())
    finally:
        collector.time.time = real


def test_collector_records_episode_with_series_data():
    ep = {"Id": "tep1", "Type": "Episode", "Name": "Pilot", "SeriesId": "tser1", "SeriesName": "Testserien",
          "ParentIndexNumber": 1, "IndexNumber": 1, "RunTimeTicks": 300 * T}
    series = {"Id": "tser1", "Genres": ["Drama"], "People": [{"Id": "a1", "Name": "Hovedrolle", "Type": "Actor"}]}
    run_play(FakeSessions(ep, {"tser1": series}), 31, transcode_at=10)
    play = db.query("SELECT * FROM plays WHERE item_id = 'tep1'")[0]
    assert play["counted"] and play["completed"] and play["play_method"] == "Transcode"
    item = db.query("SELECT * FROM items WHERE item_id = 'tep1'")[0]
    assert "Drama" in item["genres"] and "Hovedrolle" in item["people"]


def test_short_peek_is_not_stored():
    movie = {"Id": "tpeek", "Type": "Movie", "Name": "Trailer-agtig", "RunTimeTicks": 6000 * T}
    run_play(FakeSessions(movie), 4)
    assert not db.query("SELECT 1 FROM plays WHERE item_id = 'tpeek'")


def test_youtube_movie_becomes_channel_video():
    yt = {"Id": "tyt1", "Type": "Movie", "Name": "Repair", "RunTimeTicks": 300 * T, "ParentId": "tf1",
          "Path": "/mnt/Youtube/Buy it Fix it/Repair [FWFSQx4Q1Mo].webm", "Studios": [{"Name": "Buy it Fix it"}]}
    run_play(FakeSessions(yt, {"tf1": {"Id": "tf1", "Type": "Folder", "Name": "Buy it Fix it"}}), 31)
    item = db.query("SELECT * FROM items WHERE item_id = 'tyt1'")[0]
    assert item["type"] == "Video" and item["series_name"] == "Buy it Fix it"


def test_channel_sources_in_order():
    base = {"Id": "v", "Type": "Video", "Name": "x", "RunTimeTicks": 1}
    folder = {"Id": "f", "Type": "Folder", "Name": "Mappe"}
    library = {"Id": "l", "Type": "CollectionFolder", "Name": "YouTube"}

    def channel(raw, parent):
        return set_channel(to_item(raw), raw, parent)["series_name"]

    assert channel({**base, "ChannelId": "c", "ChannelName": "Plugin", "Studios": [{"Name": "S"}]}, folder) == "Plugin"
    assert channel({**base, "Studios": [{"Name": "Studio"}]}, folder) == "Studio"
    assert channel(base, folder) == "Mappe"
    assert channel(base, library) == "YouTube"


def test_video_folder_matching():
    assert in_video_folder(r"\\Nas\video\Youtube\Kanal\x.mkv", ["youtube"])
    assert not in_video_folder("/mnt/Film/YouTube Story/x.mkv", ["Youtube"])
    assert not in_video_folder("/mnt/Film/Youtube.mkv", ["Youtube"])
    assert in_video_folder("/data/media/yt/a/x.mkv", ["media/yt"])


# --- images -----------------------------------------------------------------

class FakeImages:
    def __init__(self):
        self.gone = False

    async def image(self, item_id):
        if self.gone:
            return None
        return type("R", (), {"content": b"img-" + item_id.encode(), "headers": {"content-type": "image/webp"}})()


def test_image_survives_deletion():
    fake = FakeImages()
    assert asyncio.run(images.get(fake, "timg1")).read_bytes() == b"img-timg1"
    fake.gone = True
    assert asyncio.run(images.get(fake, "timg1")).name == "timg1.webp"
    assert asyncio.run(images.get(None, "timg1")) is not None  # Jellyfin not configured at all


# --- import from Playback Reporting ---------------------------------------

class FakeReporting:
    rows = [
        {"DateCreated": "2024-03-01 20:15:33.1234567", "UserId": "tu", "ItemId": "timp1", "ItemType": "Movie",
         "ItemName": "Gammel film", "PlaybackMethod": "Transcode (v:h264 a:direct)", "ClientName": "Web",
         "DeviceName": "PC", "PlayDuration": "5000"},
        {"DateCreated": "2024-03-02T21:00:00.0000000Z", "UserId": "tu", "ItemId": "tgone", "ItemType": "Episode",
         "ItemName": "Slettet Serie - s02e05 - Finalen", "PlaybackMethod": "DirectPlay", "ClientName": "TV",
         "DeviceName": "TV", "PlayDuration": "2400"},
        {"DateCreated": "2024-03-03 20:00:00", "UserId": "tu", "ItemId": "timp1", "ItemType": "Movie",
         "ItemName": "Gammel film", "PlaybackMethod": "DirectPlay", "ClientName": "Web", "DeviceName": "PC",
         "PlayDuration": "15"},
    ]

    async def playback_reporting(self, sql):
        return self.rows

    async def users(self):
        return [{"Id": "tu", "Name": "Test"}]

    async def items(self, ids):
        known = {"timp1": {"Id": "timp1", "Type": "Movie", "Name": "Gammel film", "RunTimeTicks": 5400 * T}}
        return [known[i] for i in ids if i in known]

    async def image(self, item_id):
        return None


def test_import_is_idempotent_and_keeps_deleted_items():
    imp = importer.Importer(Settings(), FakeReporting())
    asyncio.run(imp.run())
    assert importer.status["error"] is None
    assert importer.status["imported"] == 2 and importer.status["skipped"] == 1  # the 15 s play is too short
    asyncio.run(imp.run())
    assert importer.status["imported"] == 0
    gone = db.query("SELECT * FROM items WHERE item_id = 'tgone'")[0]
    assert (gone["series_name"], gone["season_number"], gone["episode_number"]) == ("Slettet Serie", 2, 5)
    movie = db.query("SELECT * FROM plays WHERE item_id = 'timp1' AND source = 'playback_reporting'")[0]
    assert movie["play_method"] == "Transcode" and movie["video_codec"] == "h264"


def test_import_without_plugin():
    class NoPlugin(FakeReporting):
        async def playback_reporting(self, sql):
            return None
    asyncio.run(importer.Importer(Settings(), NoPlugin()).run())
    assert importer.status["available"] is False and importer.status["error"] is None


# --- series progress ------------------------------------------------------

class FakeEpisodes:
    async def episodes(self, series_id, user):
        if series_id != "tprog":
            return None
        ep = lambda i, s, e, **kw: {"Id": i, "ParentIndexNumber": s, "IndexNumber": e, "Name": f"E{e}",
                                    "RunTimeTicks": 1800 * T, "UserData": {"Played": False}, **kw}
        return [ep("tp0", 0, 1), ep("tp1", 1, 1), ep("tp2", 1, 2, UserData={"Played": user == "tu"}),
                ep("tp3", 1, 3), ep("tp4", 1, 4, LocationType="Virtual")]

    async def items(self, ids):
        return [{"Id": "tprog", "Name": "Fremdrift", "Status": "Continuing"}]


def test_progress_counts_jellyfin_marks_and_skips_specials():
    db.upsert_item({"item_id": "tp1", "type": "Episode", "name": "E1", "series_id": "tprog", "series_name": "Fremdrift",
                    "genres": [], "studios": [], "people": []})
    db.insert_play({"item_id": "tp1", "user_id": "tu", "user_name": "Test", "started_at": 1000, "ended_at": 2000,
                    "watched": 1800, "counted": 1, "completed": 1})
    asyncio.run(progress.Refresher(FakeEpisodes()).refresh_stale())
    p = progress.series_progress("tu", "tprog")[0]
    assert (p["seen"], p["total"]) == (2, 3)  # own play + Jellyfin mark; special and virtual left out
    assert p["next"]["key"] == "tp3"


# --- Home Assistant -----------------------------------------------------------

import ha  # noqa: E402


class FakeHA:
    def __init__(self):
        self.states, self.services, self.events = {}, [], []

    async def set_state(self, entity_id, state, attributes):
        self.states[entity_id] = (str(state), attributes)

    async def call_service(self, service, data):
        self.services.append((service, data))

    async def fire_event(self, event_type, data):
        self.events.append((event_type, data))


def test_sensors_are_published_and_only_resent_when_changed():
    fake = FakeHA()
    pub = ha.SensorPublisher(fake, None)
    assert asyncio.run(pub.publish()) == len(fake.states)
    for name in ("watch_time_today", "watch_time_week", "now_playing", "transcoding", "continue_watching", "last_watched"):
        assert f"{ha.PREFIX}_{name}" in fake.states, name
    assert f"{ha.PREFIX}_watch_time_today_christian" in fake.states  # one per user
    assert int(fake.states[f"{ha.PREFIX}_continue_watching"][0]) >= 1
    assert asyncio.run(pub.publish()) == 0  # nothing changed


def test_slug_handles_danish_letters():
    assert ha.slug("Gæst Øster Ål") == "gaest_oester_aal"


def _series(series_id, episodes, seen, when):
    db.execute("DELETE FROM series_episodes WHERE series_id = ?", [series_id])
    for i, item_id in enumerate(episodes, 1):
        db.execute("INSERT INTO series_episodes VALUES (?,?,?,?,?,?)", [item_id, series_id, 1, i, f"E{i}", 1800])
    for item_id in seen:
        db.insert_play({"item_id": item_id, "user_id": "tu", "user_name": "Test", "started_at": when, "ended_at": when + 1800,
                        "watched": 1800, "counted": 1, "completed": 1})


class FakeNewEpisodes:
    def __init__(self):
        self.items = []

    async def recent_episodes(self, limit=100):
        return self.items


def test_new_episode_of_followed_series_is_announced_once():
    long_ago = int(time.time()) - 400 * 86400
    _series("tfol", ["tf1", "tf2"], ["tf1", "tf2"], long_ago)          # caught up, a year ago
    _series("tnofol", ["tn1", "tn2", "tn3"], ["tn1"], long_ago)       # gave up after one episode
    db.execute("DELETE FROM meta WHERE key = 'new_episodes_since'")
    fake, jf = FakeHA(), FakeNewEpisodes()
    watcher = ha.EpisodeWatcher(fake, jf, "")
    jf.items = [{"Id": "told-before", "SeriesId": "tfol", "DateCreated": "2020-01-01T00:00:00.0000000Z"}]
    assert asyncio.run(watcher.check()) == 0  # first run only sets the starting point
    added = datetime.fromtimestamp(time.time() + 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    jf.items = [
        {"Id": "tf3", "SeriesId": "tfol", "SeriesName": "Fulgt", "Name": "Ny", "ParentIndexNumber": 1, "IndexNumber": 3,
         "DateCreated": added},
        {"Id": "tn4", "SeriesId": "tnofol", "SeriesName": "Opgivet", "Name": "Ny", "ParentIndexNumber": 1,
         "IndexNumber": 4, "DateCreated": added},
    ]
    assert asyncio.run(watcher.check()) == 1
    (event, data), = fake.events
    assert event == ha.EVENT and data["series"] == "Fulgt" and data["users"] == ["Test"]
    assert data["episodes"][0]["episode"] == "S01E03"
    (service, payload), = fake.services
    assert service == "persistent_notification.create" and "Nyt afsnit af Fulgt" in payload["title"]
    assert asyncio.run(watcher.check()) == 0 and len(fake.events) == 1  # not twice


def test_notify_service_is_used_when_set():
    fake = FakeHA()
    asyncio.run(ha.EpisodeWatcher(fake, None, "mobile_app_telefon")._announce(
        "s", [{"Id": "x", "SeriesName": "Serie", "Name": "A", "ParentIndexNumber": 2, "IndexNumber": 1}], ["Test"]))
    assert fake.services[0][0] == "notify.mobile_app_telefon"


def test_boolean_options_can_be_turned_off(tmp_path, monkeypatch):
    import config
    (tmp_path / "options.json").write_text('{"ha_sensors": false, "notify_new_episodes": false}', encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    s = config.load_settings()
    assert s.ha_sensors is False and s.notify_new_episodes is False


def test_home_assistant_api_calls():
    import httpx
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers["Authorization"], request.content))
        return httpx.Response(401 if request.url.path.endswith("/forbidden") else 200, json={})

    client = ha.HomeAssistant("http://supervisor/core/api", "tok")
    client.client = httpx.AsyncClient(base_url="http://supervisor/core/api", transport=httpx.MockTransport(handler),
                                      headers={"Authorization": "Bearer tok"})

    async def go():
        await client.set_state("sensor.x", 5, {"unit_of_measurement": "min"})
        await client.call_service("notify.mobile_app_phone", {"message": "hej"})
        await client.fire_event(ha.EVENT, {"series": "S"})
        with pytest.raises(PermissionError):
            await client.call_service("notify.forbidden", {})
    asyncio.run(go())
    assert [s[1] for s in seen[:3]] == ["/core/api/states/sensor.x", "/core/api/services/notify/mobile_app_phone",
                                        f"/core/api/events/{ha.EVENT}"]
    assert all(s[2] == "Bearer tok" for s in seen)
    assert b'"state":"5"' in seen[0][3].replace(b" ", b"")
