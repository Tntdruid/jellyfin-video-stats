"""Polls Jellyfin's /Sessions and turns what it sees into play records.

Jellyfin keeps no viewing history of its own, so every poll we compare the
sessions against what was playing last time. Watch time is measured as
wall-clock time while not paused, which stays correct when people seek.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

import db
import images
import progress
from config import Settings
from jellyfin import (TICKS_PER_SECOND, VIDEO_TYPES, JellyfinClient, as_video, merge_series, set_channel, tech_of,
                      to_item)

log = logging.getLogger("collector")

COUNT_CAP = 30 * 60  # half an hour of a long film always counts as having watched it
MIN_KEEP = 60  # anything shorter is a trailer, a misclick or a peek, and isn't stored at all
COMPLETED_AT = 0.9  # past this point the credits are usually rolling


@dataclass
class ActivePlay:
    item_id: str
    user_id: Optional[str]
    user_name: Optional[str]
    client: Optional[str]
    device: Optional[str]
    item: dict
    started_at: float
    last_seen: float
    position: float = 0.0
    max_position: float = 0.0
    paused: bool = False
    watched: float = 0.0
    tech: dict = field(default_factory=dict)

    @property
    def duration(self) -> Optional[float]:
        return self.item.get("duration")


def describe_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code in (401, 403):
            return "Jellyfin afviste API-nøglen – tjek api_key i add-on'ets konfiguration"
        return f"Jellyfin svarede {e.response.status_code}"
    if isinstance(e, httpx.ConnectError):
        return f"Kan ikke forbinde til Jellyfin – tjek jellyfin_url ({e})"
    if isinstance(e, httpx.TimeoutException):
        return "Jellyfin svarer ikke (timeout)"
    return str(e)


@dataclass
class CollectorState:
    active: Dict[str, ActivePlay] = field(default_factory=dict)
    last_poll: Optional[float] = None
    last_error: Optional[str] = None
    plays_recorded: int = 0


class Collector:
    def __init__(self, settings: Settings, client: JellyfinClient):
        self.settings = settings
        self.client = client
        self.state = CollectorState()
        self._last_sessions: Optional[list] = None
        self._series_cache: Dict[str, dict] = {}  # series and channel folders, by id
        self._tasks: set = set()
        self.known_items = {r["item_id"] for r in db.query("SELECT item_id FROM items")}

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
                self.state.last_error = None
            except Exception as e:  # keep polling; Jellyfin may just be restarting
                self.state.last_error = describe_error(e)
                log.warning("poll failed: %s", self.state.last_error)
            await asyncio.sleep(self.settings.poll_interval)

    async def poll(self) -> None:
        now = time.time()
        sessions = await self.client.sessions()
        self.state.last_poll = now
        self._log_sessions(sessions)
        seen = set()

        for s in sessions:
            item = s.get("NowPlayingItem")
            if not item or item.get("Type") not in VIDEO_TYPES:
                continue
            sid = s["Id"]
            seen.add(sid)
            play_state = s.get("PlayState") or {}
            position = (play_state.get("PositionTicks") or 0) / TICKS_PER_SECOND
            paused = bool(play_state.get("IsPaused"))
            tech = tech_of(s, item)

            current = self.state.active.get(sid)
            if current and current.item_id == item["Id"] and not self._restarted(current, position):
                if not current.paused:
                    current.watched += min(now - current.last_seen, self.settings.poll_interval * 3)
                current.position, current.paused, current.last_seen = position, paused, now
                current.max_position = max(current.max_position, position)
                # a play that had to transcode at any point is remembered as transcoded
                if current.tech.get("play_method") == "Transcode":
                    tech["play_method"] = "Transcode"
                    tech["transcode_reasons"] = tech["transcode_reasons"] or current.tech.get("transcode_reasons", [])
                current.tech = {**current.tech, **{k: v for k, v in tech.items() if v}}
                continue

            if current:
                self._finish(current, now)
            self.state.active[sid] = ActivePlay(
                item_id=item["Id"],
                user_id=s.get("UserId"),
                user_name=s.get("UserName"),
                client=s.get("Client"),
                device=s.get("DeviceName"),
                item=as_video(to_item(item), item, self.settings.video_folders),
                started_at=now - min(position, self.settings.poll_interval),
                last_seen=now,
                position=position,
                max_position=position,
                paused=paused,
                watched=0.0 if paused else min(position, self.settings.poll_interval),
                tech=tech,
            )
            if item["Id"] not in self.known_items:
                await self._fetch_item(item["Id"], s.get("UserId"), fallback=self.state.active[sid].item)

        for sid in list(self.state.active):
            if sid not in seen:
                self._finish(self.state.active.pop(sid), now)

    def flush(self) -> None:
        now = time.time()
        for play in self.state.active.values():
            self._finish(play, now)
        self.state.active.clear()

    def _log_sessions(self, sessions: list) -> None:
        """One log line whenever what Jellyfin reports changes, so 'nothing gets recorded' can be diagnosed."""
        lines = []
        for s in sessions:
            item = s.get("NowPlayingItem")
            what = f"{item.get('Type')} '{item.get('Name')}'" if item else "intet"
            lines.append(f"{s.get('Client')} på {s.get('DeviceName')} ({s.get('UserName') or 'ingen bruger'}): {what}")
        summary = sorted(lines)
        if summary != self._last_sessions:
            self._last_sessions = summary
            log.info("Jellyfin rapporterer %d session(er)%s", len(summary),
                     "".join(f"\n  - {line}" for line in summary))

    @staticmethod
    def _restarted(play: ActivePlay, position: float) -> bool:
        """Same item started over: position jumped back to the start after nearly finishing."""
        return bool(play.duration) and position < 60 and play.max_position > play.duration * COMPLETED_AT

    def _finish(self, play: ActivePlay, now: float) -> None:
        if not play.paused:
            play.watched += min(now - play.last_seen, self.settings.poll_interval)
        watched = min(play.watched, play.duration) if play.duration else play.watched
        if watched < MIN_KEEP:
            return
        needed = COUNT_CAP
        if play.duration:
            needed = min(play.duration * self.settings.min_watch_percent / 100, COUNT_CAP)
        progress = min(play.max_position / play.duration, 1.0) if play.duration else None
        db.insert_play({
            "item_id": play.item_id,
            "user_id": play.user_id,
            "user_name": play.user_name,
            "client": play.client,
            "device": play.device,
            "started_at": int(play.started_at),
            "ended_at": int(now),
            "watched": round(watched, 1),
            "duration": play.duration,
            "progress": round(progress, 3) if progress is not None else None,
            "counted": int(watched >= needed),
            "completed": int(progress is not None and progress >= COMPLETED_AT),
            **play.tech,
        })
        self.state.plays_recorded += 1
        if play.item.get("type") == "Episode":
            progress.mark_stale(play.item.get("series_id"))  # new episodes may have arrived too
        log.info("gemt: '%s' (%s) – %d min set, %s", play.item.get("name"), play.user_name, watched // 60,
                 "talt som set" if watched >= needed else "kun kigget")

    async def _parent(self, parent_id: Optional[str], user_id: Optional[str]) -> dict:
        if not parent_id:
            return {}
        if parent_id not in self._series_cache:
            self._series_cache[parent_id] = await self.client.item(parent_id, user_id) or {}
        return self._series_cache[parent_id]

    async def _fetch_item(self, item_id: str, user_id: Optional[str], fallback: dict) -> None:
        try:
            raw = await self.client.item(item_id, user_id)
            it = as_video(to_item(raw), raw, self.settings.video_folders) if raw else fallback
            if it["type"] == "Episode" and it["series_id"]:
                it = merge_series(it, await self._parent(it["series_id"], user_id))
            elif it["type"] == "Video" and raw:
                it = set_channel(it, raw, await self._parent(raw.get("ParentId"), user_id))
        except Exception as e:
            log.warning("could not fetch item %s: %s", item_id, e)
            it = fallback
        db.upsert_item(it)
        self.known_items.add(item_id)
        actors = [p.get("id") for p in it["people"] if p.get("type") == "Actor"][:8]
        task = asyncio.create_task(images.prefetch(self.client, [item_id, it["series_id"], *actors]))
        self._tasks.add(task)  # keep a reference until it is done
        task.add_done_callback(self._tasks.discard)

    def now_playing(self) -> list:
        return [
            {
                "item_id": p.item_id,
                "name": p.item.get("name"),
                "type": p.item.get("type"),
                "series_id": p.item.get("series_id"),
                "series_name": p.item.get("series_name"),
                "season_number": p.item.get("season_number"),
                "episode_number": p.item.get("episode_number"),
                "user_name": p.user_name,
                "device": p.device,
                "client": p.client,
                "position": p.position,
                "duration": p.duration,
                "paused": p.paused,
                "play_method": p.tech.get("play_method"),
                "height": p.tech.get("height"),
            }
            for p in self.state.active.values()
        ]
