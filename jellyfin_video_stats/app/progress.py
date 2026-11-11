"""How far people are in each series: episodes seen out of the episodes in the library, and what's next.

Jellyfin is asked for each watched series' full episode list, plus every user's "played" marks, so progress also
counts episodes watched before the add-on existed or marked as watched by hand. An episode counts as seen when
the user has a counted play of it here, or Jellyfin has it marked as played. Specials (season 0) and episodes
that are only known from metadata but not in the library are left out.

Progress is the current state, so it does not depend on the selected period.
"""
import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import db
from stats import episode_label

log = logging.getLogger("progress")

REFRESH = 12 * 3600
CHECK_EVERY = 10 * 60


def mark_stale(series_id: Optional[str]) -> None:
    """Ask for a refresh soon, e.g. after a new episode of the series was watched."""
    if series_id:
        db.execute("""INSERT INTO series_info (series_id, refreshed_at) VALUES (?, 0)
                      ON CONFLICT(series_id) DO UPDATE SET refreshed_at = 0""", [series_id])


def _parse_time(value: Optional[str]) -> Optional[int]:
    """Jellyfin dates look like 2024-03-01T20:15:33.1234567Z (always UTC); the fraction is dropped."""
    if not value or len(value) < 19:
        return None
    try:
        return int(datetime.fromisoformat(value[:19]).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


class Refresher:
    def __init__(self, client):
        self.client = client

    async def run(self) -> None:
        while True:
            try:
                await self.refresh_stale()
            except Exception as e:
                log.warning("progress refresh failed: %s", e)
            await asyncio.sleep(CHECK_EVERY)

    async def refresh_stale(self) -> int:
        watched = db.query(
            """SELECT DISTINCT i.series_id, MAX(i.series_name) AS name FROM items i
               WHERE i.type = 'Episode' AND i.series_id IS NOT NULL AND i.series_id NOT LIKE 'deleted%'
               GROUP BY i.series_id"""
        )
        info = {r["series_id"]: r for r in db.query("SELECT series_id, refreshed_at FROM series_info")}
        due = [r for r in watched if (info.get(r["series_id"]) or {}).get("refreshed_at") is None
               or time.time() - info[r["series_id"]]["refreshed_at"] > REFRESH]
        users = [r["user_id"] for r in db.query("SELECT DISTINCT user_id FROM plays WHERE user_id IS NOT NULL")]
        for r in due:
            await self.refresh_series(r["series_id"], r["name"], users)
            await asyncio.sleep(0)
        if due:
            log.info("refreshed episode lists for %d series", len(due))
        return len(due)

    async def refresh_series(self, series_id: str, name: Optional[str], users: list) -> None:
        episodes, played = None, []
        for user in users or [None]:
            items = await self.client.episodes(series_id, user)
            if items is None:  # deleted from Jellyfin: keep the last known list, and ask again in REFRESH
                db.execute("""INSERT INTO series_info (series_id, name, refreshed_at) VALUES (?,?,?)
                              ON CONFLICT(series_id) DO UPDATE SET refreshed_at = excluded.refreshed_at""",
                           [series_id, name, int(time.time())])
                return
            episodes = episodes or items
            for e in items:
                ud = e.get("UserData") or {}
                if user and ud.get("Played"):
                    played.append((user, e["Id"], _parse_time(ud.get("LastPlayedDate"))))
        series = (await self.client.items([series_id]) or [{}])[0]

        kept = [e for e in episodes or [] if e.get("LocationType") != "Virtual" and not e.get("IsMissing")
                and (e.get("ParentIndexNumber") or 0) > 0]
        with db._lock:
            conn = db.connect()
            conn.execute("DELETE FROM series_episodes WHERE series_id = ?", [series_id])
            conn.executemany(
                """INSERT OR REPLACE INTO series_episodes (item_id, series_id, season_number, episode_number, name, duration)
                   VALUES (?,?,?,?,?,?)""",
                [(e["Id"], series_id, e.get("ParentIndexNumber"), e.get("IndexNumber"), e.get("Name"),
                  (e.get("RunTimeTicks") or 0) / 10_000_000 or None) for e in kept],
            )
            if users:
                conn.executemany(f"DELETE FROM episode_played WHERE user_id = ? AND item_id IN "
                                 f"(SELECT item_id FROM series_episodes WHERE series_id = ?)",
                                 [(u, series_id) for u in users])
            conn.executemany("INSERT OR REPLACE INTO episode_played (user_id, item_id, last_played) VALUES (?,?,?)", played)
            conn.execute(
                """INSERT INTO series_info (series_id, name, status, refreshed_at) VALUES (?,?,?,?)
                   ON CONFLICT(series_id) DO UPDATE SET name=excluded.name, status=excluded.status,
                                                        refreshed_at=excluded.refreshed_at""",
                [series_id, series.get("Name") or name, series.get("Status"), int(time.time())],
            )
            conn.commit()


# --- read side ------------------------------------------------------------

def series_progress(user: Optional[str], series_id: Optional[str] = None) -> list:
    """Progress for every series with at least one episode seen (by `user`, or by anyone when None)."""
    where = "WHERE se.series_id = ?" if series_id else ""
    episodes = db.query(
        f"""SELECT se.*, si.name AS series_name, si.status FROM series_episodes se
            LEFT JOIN series_info si USING(series_id) {where}
            ORDER BY se.series_id, se.season_number, se.episode_number""",
        [series_id] if series_id else [],
    )
    if not episodes:
        return []
    user_sql, params = ("AND user_id = ?", [user]) if user else ("", [])
    seen = {}  # item_id -> last time seen
    for r in db.query(f"SELECT item_id, MAX(started_at) AS t FROM plays WHERE counted = 1 {user_sql} GROUP BY item_id", params):
        seen[r["item_id"]] = r["t"]
    for r in db.query(f"SELECT item_id, MAX(last_played) AS t FROM episode_played WHERE 1=1 {user_sql} GROUP BY item_id", params):
        seen[r["item_id"]] = max(seen.get(r["item_id"]) or 0, r["t"] or 0)  # 0 = played, but no date known

    by_series = defaultdict(list)
    for e in episodes:
        by_series[e["series_id"]].append(e)

    out = []
    for sid, eps in by_series.items():
        done = [e for e in eps if e["item_id"] in seen]
        if not done:
            continue
        last_seen_idx = max(i for i, e in enumerate(eps) if e["item_id"] in seen)
        nxt = next((e for e in eps[last_seen_idx + 1:] if e["item_id"] not in seen), None) or \
            next((e for e in eps if e["item_id"] not in seen), None)
        seasons = defaultdict(lambda: [0, 0])
        for e in eps:
            seasons[e["season_number"]][1] += 1
            seasons[e["season_number"]][0] += e["item_id"] in seen
        remaining = [e for e in eps if e["item_id"] not in seen]
        out.append({
            "key": sid,
            "name": eps[0]["series_name"],
            "status": eps[0]["status"],
            "image_id": sid,
            "seen": len(done),
            "total": len(eps),
            "share": len(done) / len(eps),
            "last": max(seen[e["item_id"]] for e in done) or None,
            "next": {"key": nxt["item_id"], "name": nxt["name"], "episode": episode_label(nxt)} if nxt else None,
            "remaining_minutes": sum(e["duration"] or 0 for e in remaining) / 60,
            "seasons": [{"season": s, "seen": v[0], "total": v[1]} for s, v in sorted(seasons.items())],
            "seen_ids": [e["item_id"] for e in done],
        })
    return out


def overview(user: Optional[str]) -> dict:
    rows = series_progress(user)
    for r in rows:
        r.pop("seen_ids")
    ongoing = sorted((r for r in rows if r["seen"] < r["total"]), key=lambda r: -(r["last"] or 0))
    finished = sorted((r for r in rows if r["seen"] >= r["total"]), key=lambda r: -(r["last"] or 0))
    return {"continue": ongoing, "finished": finished}


def finished_in(user: Optional[str], start: int, end: int) -> list:
    """Series whose last missing episode was seen inside the range (and are fully seen now)."""
    return [r for r in overview(user)["finished"] if r["last"] and start <= r["last"] < end]
