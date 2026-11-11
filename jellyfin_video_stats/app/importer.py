"""One-off import of old plays from Jellyfin's Playback Reporting plugin.

The plugin has logged every playback since it was installed, so this gives the statistics a history from before
the add-on existed. It records start time, user, item, play method, client, device and seconds played (pauses
excluded). It does not know how far into the item people got, so "completed" is estimated from the seconds played.

Plays that the collector already has (same user and item, started within DUPLICATE_WINDOW) are skipped, so the
import can be run again safely, e.g. to pick up plays from while the add-on was stopped.
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import db
import images
from collector import COMPLETED_AT, COUNT_CAP, MIN_KEEP
from config import Settings
from jellyfin import VIDEO_TYPES, JellyfinClient, as_video, merge_series, set_channel, to_item

log = logging.getLogger("import")

SOURCE = "playback_reporting"
DUPLICATE_WINDOW = 15 * 60
BATCH = 100
QUERY = f"""SELECT DateCreated, UserId, ItemId, ItemType, ItemName, PlaybackMethod, ClientName, DeviceName, PlayDuration
            FROM PlaybackActivity WHERE ItemType IN ({",".join(f"'{t}'" for t in VIDEO_TYPES)})
            ORDER BY DateCreated"""
EPISODE_NAME = re.compile(r"^(?P<series>.+) - s(?P<season>\d+)e(?P<episode>\d+) - (?P<name>.*)$", re.I)
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$")
METHOD = re.compile(r"^(DirectPlay|DirectStream|Transcode)\b(?:\s*\(v:(?P<v>[^ )]+))?", re.I)

status = {"running": False, "imported": None, "skipped": None, "finished_at": None, "error": None, "available": None}


def parse_date(value: str) -> Optional[float]:
    """The plugin stores local server time without a zone (or UTC with 'Z'); local is read in this container's
    time zone, which matches as long as Jellyfin and Home Assistant use the same one."""
    m = DATE.match(str(value).strip())
    if not m:
        return None
    dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
    zone = m.group(4)
    if zone == "Z":
        return dt.replace(tzinfo=timezone.utc).timestamp()
    if zone:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{zone if ':' in zone else zone[:3] + ':' + zone[3:]}").timestamp()
    return dt.timestamp()


def parse_method(value: Optional[str]) -> tuple:
    m = METHOD.match(value or "")
    if not m:
        return None, None
    method = {"directplay": "DirectPlay", "directstream": "DirectStream", "transcode": "Transcode"}[m.group(1).lower()]
    codec = m.group("v") if m.group("v") and m.group("v") != "direct" else None
    return method, codec


def item_from_name(row: dict) -> dict:
    """Best effort for items that have since been deleted from Jellyfin: all we have is the logged name."""
    kind = row.get("ItemType")
    name = row.get("ItemName") or "Ukendt"
    it = {"item_id": row["ItemId"], "type": kind, "name": name, "genres": [], "studios": [], "people": [],
          "fetched_at": int(time.time())}
    m = EPISODE_NAME.match(name) if kind == "Episode" else None
    if m:
        series = m.group("series").strip()
        it.update(name=m.group("name").strip() or name, series_name=series, season_number=int(m.group("season")),
                  episode_number=int(m.group("episode")),
                  series_id="deleted" + re.sub(r"[^a-z0-9]", "", series.lower())[:40])
    return it


class Importer:
    def __init__(self, settings: Settings, client: JellyfinClient):
        self.settings = settings
        self.client = client
        self._parents: dict = {}

    async def run(self) -> None:
        if status["running"]:
            return
        status.update(running=True, error=None)
        try:
            rows = await self.client.playback_reporting(QUERY)
            status["available"] = rows is not None
            if rows is None:
                log.info("Playback Reporting is not installed - nothing to import")
                return
            imported, skipped = await self._import(rows)
            status.update(imported=imported, skipped=skipped, finished_at=time.time())
            db.set_meta("import_playback_reporting", str(int(time.time())))
            log.info("imported %d plays from Playback Reporting (%d skipped)", imported, skipped)
        except Exception as e:
            status["error"] = str(e)
            log.warning("import from Playback Reporting failed: %s", e)
        finally:
            status["running"] = False

    async def _import(self, rows: list) -> tuple:
        users = {u["Id"].replace("-", "").lower(): u["Name"] for u in await self.client.users()}
        ids = list(dict.fromkeys(r["ItemId"] for r in rows if r.get("ItemId")))
        items = await self._items(ids)
        rows_by_item = {}
        for r in rows:
            rows_by_item.setdefault(r.get("ItemId"), r)
        for item_id in ids:
            if item_id not in items:
                items[item_id] = item_from_name(rows_by_item[item_id])
                db.upsert_item(items[item_id])

        existing = db.query("SELECT user_id, item_id, started_at FROM plays")
        seen = {}
        for e in existing:
            seen.setdefault((e["user_id"], e["item_id"]), []).append(e["started_at"])

        imported = skipped = 0
        for r in rows:
            started = parse_date(r.get("DateCreated"))
            watched = float(r.get("PlayDuration") or 0)
            user = (r.get("UserId") or "").replace("-", "").lower() or None
            item = items.get(r.get("ItemId"))
            if started is None or item is None or watched < MIN_KEEP:
                skipped += 1
                continue
            key = (user, r["ItemId"])
            if any(abs(t - started) < DUPLICATE_WINDOW for t in seen.get(key, [])):
                skipped += 1
                continue
            duration = item.get("duration")
            if duration:
                watched = min(watched, duration)
            needed = min(duration * self.settings.min_watch_percent / 100, COUNT_CAP) if duration else COUNT_CAP
            progress = min(watched / duration, 1.0) if duration else None
            method, codec = parse_method(r.get("PlaybackMethod"))
            db.insert_play({
                "item_id": r["ItemId"], "user_id": user, "user_name": users.get(user), "client": r.get("ClientName"),
                "device": r.get("DeviceName"), "started_at": int(started), "ended_at": int(started + watched),
                "watched": round(watched, 1), "duration": duration,
                "progress": round(progress, 3) if progress is not None else None,
                "counted": int(watched >= needed), "completed": int(progress is not None and progress >= COMPLETED_AT),
                "play_method": method, "video_codec": codec, "transcode_reasons": [], "source": SOURCE,
            })
            seen.setdefault(key, []).append(started)
            imported += 1
            if imported % 500 == 0:
                await asyncio.sleep(0)  # let the web server answer in between

        art = [i for it in items.values() for i in (it["item_id"], it.get("series_id"))]
        asyncio.create_task(images.prefetch(self.client, art))
        return imported, skipped

    async def _items(self, ids: list) -> dict:
        """Current metadata for everything that still exists, stored the same way the collector would."""
        out = {}
        for i in range(0, len(ids), BATCH):
            for raw in await self.client.items(ids[i:i + BATCH]):
                it = as_video(to_item(raw), raw, self.settings.video_folders)
                if it["type"] == "Episode" and it["series_id"]:
                    it = merge_series(it, await self._parent(it["series_id"]))
                elif it["type"] == "Video":
                    it = set_channel(it, raw, await self._parent(raw.get("ParentId")))
                db.upsert_item(it)
                out[it["item_id"]] = it
        return out

    async def _parent(self, parent_id: Optional[str]) -> dict:
        if not parent_id:
            return {}
        if parent_id not in self._parents:
            found = await self.client.items([parent_id])
            self._parents[parent_id] = found[0] if found else {}
        return self._parents[parent_id]
