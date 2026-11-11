"""Home Assistant integration: sensors with live numbers, and a heads-up when a followed series gets new episodes.

Everything goes through Home Assistant's REST API, reached via the Supervisor (`homeassistant_api: true` in
config.yaml), so no MQTT broker is needed. Sensors set this way are plain states: they are re-sent regularly,
because Home Assistant forgets them when it restarts, and they can't be renamed in the UI (use them as they are,
or wrap them in a template sensor).
"""
import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

import db
import progress
import stats
from stats import episode_label

log = logging.getLogger("ha")

PREFIX = "sensor.jellyfin_video_stats"
EVENT = "jellyfin_video_stats_new_episode"
SENSOR_EVERY = 30
RESEND_ALL_EVERY = 10 * 60
EPISODES_EVERY = 30 * 60
FOLLOW_DAYS = 60  # a series counts as followed if you're caught up, or watched it within this many days

status = {"enabled": False, "last_error": None, "last_update": None, "sensors": 0, "entities": [], "notified": 0}


def slug(name: str) -> str:
    name = name.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "user"


class HomeAssistant:
    def __init__(self, url: str, token: str):
        self.client = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=15)

    async def close(self) -> None:
        await self.client.aclose()

    async def _post(self, path: str, payload: dict) -> None:
        r = await self.client.post(path, json=payload)
        if r.status_code in (401, 403):
            raise PermissionError("Home Assistant afviste forbindelsen – kræver homeassistant_api i add-on'et")
        r.raise_for_status()

    async def set_state(self, entity_id: str, state, attributes: dict) -> None:
        await self._post(f"/states/{entity_id}", {"state": str(state)[:255], "attributes": attributes})

    async def call_service(self, service: str, data: dict) -> None:
        domain, _, name = service.partition(".")
        await self._post(f"/services/{domain}/{name}", data)

    async def fire_event(self, event_type: str, data: dict) -> None:
        await self._post(f"/events/{event_type}", data)


# --- sensors ----------------------------------------------------------------

def _minutes_since(t: float, collector) -> dict:
    """Watch time per user since t, including what is playing right now (so limits can be enforced live)."""
    out = {}
    for r in db.query("SELECT user_id, MAX(user_name) AS name, SUM(watched) AS s FROM plays WHERE started_at >= ? "
                      "GROUP BY user_id", [int(t)]):
        out[r["user_id"]] = {"name": r["name"] or r["user_id"], "minutes": (r["s"] or 0) / 60}
    for p in (collector.state.active.values() if collector else []):
        u = out.setdefault(p.user_id, {"name": p.user_name or p.user_id, "minutes": 0})
        u["minutes"] += p.watched / 60
    return out


def build_sensors(collector) -> dict:
    """entity_id -> (state, attributes)."""
    now = datetime.now()
    midnight = datetime(now.year, now.month, now.day).timestamp()
    week_start = (datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())).timestamp()
    today, week = _minutes_since(midnight, collector), _minutes_since(week_start, collector)

    def duration(name: str, minutes: float, extra: Optional[dict] = None) -> tuple:
        return (round(minutes), {"friendly_name": name, "unit_of_measurement": "min", "device_class": "duration",
                                 "state_class": "measurement", "icon": "mdi:television-play", **(extra or {})})

    sensors = {
        f"{PREFIX}_watch_time_today": duration(
            "Seetid i dag", sum(u["minutes"] for u in today.values()),
            {"per_user": {u["name"]: round(u["minutes"]) for u in today.values()}}),
        f"{PREFIX}_watch_time_week": duration(
            "Seetid denne uge", sum(u["minutes"] for u in week.values()),
            {"per_user": {u["name"]: round(u["minutes"]) for u in week.values()}}),
    }
    for u in stats.users():  # one sensor per person, also on days they haven't watched anything
        name = u["name"] or u["id"]
        sensors[f"{PREFIX}_watch_time_today_{slug(name)}"] = duration(
            f"Seetid i dag – {name}", (today.get(u["id"]) or {}).get("minutes", 0), {"jellyfin_user": name})

    playing = collector.now_playing() if collector else []
    sessions = [{
        "user": n["user_name"], "device": n["device"], "client": n["client"],
        "title": f"{n['series_name']} {episode_label(n)} · {n['name']}" if n["type"] == "Episode"
        else f"{n['name']} · {n['series_name']}" if n["type"] == "Video" and n.get("series_name") else n["name"],
        "type": {"Episode": "Afsnit", "Movie": "Film", "Video": "Video"}.get(n["type"], n["type"]),
        "paused": n["paused"], "transcoding": n["play_method"] == "Transcode",
        "progress": round(n["position"] / n["duration"] * 100) if n.get("duration") else None,
    } for n in playing]
    sensors[f"{PREFIX}_now_playing"] = (len(sessions), {
        "friendly_name": "Afspilles nu", "icon": "mdi:play-circle", "unit_of_measurement": "afspilninger",
        "sessions": sessions, "titles": [s["title"] for s in sessions]})
    transcoding = [s for s in sessions if s["transcoding"]]
    sensors[f"{PREFIX}_transcoding"] = (len(transcoding), {
        "friendly_name": "Transcodinger nu", "icon": "mdi:cpu-64-bit", "unit_of_measurement": "afspilninger",
        "sessions": transcoding})

    ongoing = progress.overview(None)["continue"]
    sensors[f"{PREFIX}_continue_watching"] = (len(ongoing), {
        "friendly_name": "Serier i gang", "icon": "mdi:playlist-play", "unit_of_measurement": "serier",
        "series": [{"series": r["name"], "next": f"{r['next']['episode']} · {r['next']['name']}" if r["next"] else None,
                    "seen": r["seen"], "total": r["total"], "remaining_minutes": round(r["remaining_minutes"])}
                   for r in ongoing[:10]]})

    last = stats.recent(stats.Scope(0, int(time.time()) + 60), 1)
    if last:
        r = last[0]
        title = f"{r['title']} {r['episode']}".strip() if r["kind"] == "series" else r["name"]
        sensors[f"{PREFIX}_last_watched"] = (title, {
            "friendly_name": "Senest set", "icon": "mdi:history", "user": r["user_name"],
            "watched_at": datetime.fromtimestamp(r["started_at"]).isoformat(timespec="minutes")})
    return sensors


class SensorPublisher:
    def __init__(self, ha: HomeAssistant, collector):
        self.ha = ha
        self.collector = collector
        self._sent: dict = {}
        self._last_full = 0.0

    async def run(self) -> None:
        status["enabled"] = True
        while True:
            try:
                await self.publish()
                status["last_error"] = None
            except Exception as e:
                if status["last_error"] != str(e):
                    log.warning("could not update Home Assistant sensors: %s", e)
                status["last_error"] = str(e)
            await asyncio.sleep(SENSOR_EVERY)

    async def publish(self) -> int:
        full = time.time() - self._last_full > RESEND_ALL_EVERY  # Home Assistant forgets them on restart
        sent = 0
        for entity_id, (state, attrs) in build_sensors(self.collector).items():
            if full or self._sent.get(entity_id) != (state, attrs):
                await self.ha.set_state(entity_id, state, attrs)
                self._sent[entity_id] = (state, attrs)
                sent += 1
        if full:
            self._last_full = time.time()
        status.update(last_update=time.time(), sensors=len(self._sent), entities=sorted(self._sent))
        return sent


# --- new episodes -------------------------------------------------------------

def _created(value: Optional[str]) -> float:
    """Jellyfin's DateCreated, always UTC, e.g. 2026-11-11T18:02:33.1234567Z."""
    try:
        return datetime.fromisoformat(value[:19]).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def followers(series_id: str, new_ids: set) -> list:
    """Names of the people following a series: caught up apart from the new episodes, or watched it recently."""
    library = {r["item_id"] for r in db.query("SELECT item_id FROM series_episodes WHERE series_id = ?", [series_id])}
    out = []
    for u in stats.users():
        p = (progress.series_progress(u["id"], series_id) or [None])[0]
        if not p:
            continue
        caught_up = not (library - set(p["seen_ids"]) - new_ids)
        recent = p["last"] and time.time() - p["last"] < FOLLOW_DAYS * 86400
        if caught_up or recent:
            out.append(u["name"] or u["id"])
    return out


class EpisodeWatcher:
    def __init__(self, ha: HomeAssistant, client, notify_service: str):
        self.ha = ha
        self.client = client
        self.notify_service = notify_service

    async def run(self) -> None:
        while True:
            try:
                await self.check()
            except Exception as e:
                log.warning("checking for new episodes failed: %s", e)
            await asyncio.sleep(EPISODES_EVERY)

    async def check(self) -> int:
        since = db.get_meta("new_episodes_since")
        episodes = await self.client.recent_episodes()
        newest = max((_created(e.get("DateCreated")) for e in episodes), default=time.time())
        if since is None:  # first run: start from now instead of announcing the whole library
            db.set_meta("new_episodes_since", str(int(max(newest, time.time()))))
            return 0
        known = {r["item_id"] for r in db.query("SELECT item_id FROM notified_episodes")}
        fresh = [e for e in episodes if _created(e.get("DateCreated")) > float(since) and e["Id"] not in known
                 and e.get("SeriesId")]
        by_series: dict = {}
        for e in fresh:
            by_series.setdefault(e["SeriesId"], []).append(e)

        told = 0
        for series_id, eps in by_series.items():
            progress.mark_stale(series_id)  # pick the new episodes up in "continue watching" too
            eps.sort(key=lambda e: (e.get("ParentIndexNumber") or 0, e.get("IndexNumber") or 0))
            names = followers(series_id, {e["Id"] for e in eps})
            if names:
                await self._announce(series_id, eps, names)
                told += 1
        for e in fresh:
            db.execute("INSERT OR IGNORE INTO notified_episodes (item_id, at) VALUES (?, ?)", [e["Id"], int(time.time())])
        if fresh:
            db.set_meta("new_episodes_since", str(int(max(_created(e.get("DateCreated")) for e in fresh))))
        status["notified"] += told
        return told

    async def _announce(self, series_id: str, eps: list, names: list) -> None:
        series = eps[0].get("SeriesName") or "en serie"
        labels = [{"item_id": e["Id"], "name": e.get("Name"),
                   "episode": episode_label({"season_number": e.get("ParentIndexNumber"),
                                             "episode_number": e.get("IndexNumber")})} for e in eps]
        title = f"Nyt afsnit af {series}" if len(eps) == 1 else f"{len(eps)} nye afsnit af {series}"
        shown = ", ".join(f"{x['episode']} · {x['name']}".strip(" ·") for x in labels[:3]) + (" …" if len(eps) > 3 else "")
        message = f"{shown} er kommet i Jellyfin. Følges af {' og '.join(names) if len(names) <= 2 else ', '.join(names)}."
        await self.ha.fire_event(EVENT, {"series": series, "series_id": series_id, "episodes": labels, "users": names})
        if self.notify_service:
            service = self.notify_service if "." in self.notify_service else f"notify.{self.notify_service}"
            await self.ha.call_service(service, {"title": title, "message": message})
        else:
            await self.ha.call_service("persistent_notification.create",
                                       {"title": title, "message": message, "notification_id": f"jvs_new_{series_id}"})
        log.info("told Home Assistant: %s (%s)", title, ", ".join(names))
