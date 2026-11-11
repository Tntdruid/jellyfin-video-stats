"""Read-side queries for the dashboard. All times are bucketed in the container's local time zone.

Every play is one of three kinds: movie, series (an episode) or video (e.g. a YouTube download).
A "title" is what people think of as one thing they watch: a movie, a whole series or a whole channel.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import db

LOCAL = "'unixepoch','localtime'"
BUCKETS = {
    "day": f"date(started_at,{LOCAL})",
    "week": f"date(started_at,{LOCAL},'weekday 0','-6 days')",
    "month": f"strftime('%Y-%m-01',started_at,{LOCAL})",
}
SESSION_GAP = 30 * 60
WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
RESOLUTION = """CASE WHEN height IS NULL THEN 'Ukendt' WHEN height >= 1800 THEN '4K' WHEN height >= 1000 THEN '1080p'
                     WHEN height >= 700 THEN '720p' ELSE 'SD' END"""
METHOD_DA = {"DirectPlay": "Direkte afspilning", "DirectStream": "Direkte stream", "Transcode": "Transcoding"}


@dataclass
class Scope:
    start: int
    end: int
    user: Optional[str] = None

    def where(self, counted: Optional[bool] = True, alias: str = "plays"):
        sql = f"{alias}.started_at >= ? AND {alias}.started_at < ?"
        params = [self.start, self.end]
        if self.user:
            sql += f" AND {alias}.user_id = ?"
            params.append(self.user)
        if counted is not None:
            sql += f" AND {alias}.counted = {int(counted)}"
        return sql, params

    def previous(self) -> "Scope":
        length = self.end - self.start
        return Scope(self.start - length, self.start, self.user)


def _plays_cte(scope: Scope, counted: Optional[bool] = True):
    where, params = scope.where(counted)
    return (
        f"""WITH p AS (
              SELECT plays.*, i.name, i.type, i.series_id, i.series_name, i.season_number, i.episode_number, i.year,
                     COALESCE(i.genres,'[]') AS genres, COALESCE(i.people,'[]') AS people,
                     CASE i.type WHEN 'Episode' THEN 'series' WHEN 'Video' THEN 'video' ELSE 'movie' END AS kind,
                     CASE WHEN i.type IN ('Episode','Video') AND i.series_id IS NOT NULL THEN i.series_id ELSE plays.item_id END AS title_id,
                     CASE WHEN i.type IN ('Episode','Video') AND i.series_name IS NOT NULL THEN i.series_name ELSE i.name END AS title
              FROM plays LEFT JOIN items i USING(item_id)
              WHERE {where})""",
        params,
    )


def user_filter(user: Optional[str], alias: str = "p"):
    return (f"AND {alias}.user_id = ?", [user]) if user else ("", [])


def episode_label(r: dict) -> str:
    if r.get("season_number") is not None and r.get("episode_number") is not None:
        return f"S{r['season_number']:02d}E{r['episode_number']:02d}"
    return ""


# --- meta -----------------------------------------------------------------

def users() -> list:
    return db.query(
        """SELECT user_id AS id, MAX(user_name) AS name, COUNT(*) AS plays
           FROM plays WHERE user_id IS NOT NULL GROUP BY user_id ORDER BY plays DESC"""
    )


def first_play() -> Optional[int]:
    rows = db.query("SELECT MIN(started_at) AS t FROM plays")
    return rows[0]["t"] if rows else None


# --- summary --------------------------------------------------------------

def _totals(scope: Scope) -> dict:
    cte, params = _plays_cte(scope)
    row = db.query(
        f"""{cte} SELECT COUNT(*) AS plays, COALESCE(SUM(watched),0)/60.0 AS minutes,
                  COALESCE(SUM(CASE WHEN kind='movie' THEN watched END),0)/60.0 AS movie_minutes,
                  COALESCE(SUM(CASE WHEN kind='series' THEN watched END),0)/60.0 AS series_minutes,
                  COALESCE(SUM(CASE WHEN kind='video' THEN watched END),0)/60.0 AS video_minutes,
                  COUNT(DISTINCT CASE WHEN kind='movie' THEN item_id END) AS movies,
                  COUNT(DISTINCT CASE WHEN kind='series' THEN item_id END) AS episodes,
                  COUNT(DISTINCT CASE WHEN kind='series' THEN title_id END) AS series,
                  COUNT(DISTINCT CASE WHEN kind='video' THEN item_id END) AS videos,
                  COUNT(DISTINCT CASE WHEN kind='video' THEN title_id END) AS channels,
                  COUNT(DISTINCT title_id) AS titles,
                  COALESCE(AVG(completed),0) AS completion_rate
            FROM p""",
        params,
    )[0]
    where, params = scope.where(counted=None)
    tech = db.query(
        f"""SELECT COUNT(*) AS n, AVG(CASE WHEN play_method='Transcode' THEN 1.0 ELSE 0 END) AS transcode,
                   AVG(CASE WHEN subtitle_lang IS NOT NULL THEN 1.0 ELSE 0 END) AS subtitles
            FROM plays WHERE {where}""",
        params,
    )[0]
    row["transcode_rate"] = tech["transcode"] or 0
    row["subtitle_rate"] = tech["subtitles"] or 0
    return row


def summary(scope: Scope) -> dict:
    current = _totals(scope)
    previous = _totals(scope.previous())

    user_sql, user_params = user_filter(scope.user)
    firsts = db.query(
        f"""SELECT i.series_id, MIN(p.started_at) AS first FROM plays p JOIN items i USING(item_id)
            WHERE p.counted = 1 AND i.type = 'Episode' AND i.series_id IS NOT NULL {user_sql} GROUP BY i.series_id""",
        user_params,
    )
    new_series = sum(1 for r in firsts if scope.start <= r["first"] < scope.end)

    sessions = _sessions(scope)
    lengths = [(s[-1]["ended_at"] - s[0]["started_at"]) / 60 for s in sessions]
    streak_now, streak_best = _streaks(scope.user)
    binge = biggest_binge(scope)

    return {
        **current,
        "previous": previous,
        "new_series": new_series,
        "sessions": len(sessions),
        "avg_session_minutes": sum(lengths) / len(lengths) if lengths else 0,
        "longest_session_minutes": max(lengths) if lengths else 0,
        "streak_current": streak_now,
        "streak_best": streak_best,
        "binge": binge,
    }


def _sessions(scope: Scope) -> list:
    where, params = scope.where(counted=None)
    rows = db.query(
        f"SELECT user_id, item_id, started_at, ended_at FROM plays WHERE {where} ORDER BY user_id, started_at", params
    )
    sessions, current = [], []
    for r in rows:
        if current and (r["user_id"] != current[-1]["user_id"] or r["started_at"] - current[-1]["ended_at"] > SESSION_GAP):
            sessions.append(current)
            current = []
        current.append(r)
    if current:
        sessions.append(current)
    return sessions


def _streaks(user: Optional[str]):
    user_sql, params = user_filter(user, "plays")
    days = [
        date.fromisoformat(r["d"])
        for r in db.query(
            f"SELECT DISTINCT date(started_at,{LOCAL}) AS d FROM plays WHERE counted = 1 {user_sql} ORDER BY d",
            params,
        )
    ]
    best = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    today = date.today()
    current = run if prev and (today - prev).days <= 1 else 0
    return current, best


def biggest_binge(scope: Scope) -> Optional[dict]:
    """Most episodes of one series watched by one person on one day."""
    cte, params = _plays_cte(scope)
    rows = db.query(
        f"""{cte} SELECT title_id AS key, MAX(title) AS name, date(started_at,{LOCAL}) AS d,
                  COUNT(DISTINCT item_id) AS n, SUM(watched)/60.0 AS minutes
            FROM p WHERE kind='series' GROUP BY user_id, title_id, d ORDER BY n DESC, minutes DESC LIMIT 1""",
        params,
    )
    return rows[0] if rows and rows[0]["n"] >= 2 else None


# --- charts ---------------------------------------------------------------

def _bucket_range(scope: Scope, bucket: str) -> list:
    first = first_play() or scope.start
    start = datetime.fromtimestamp(max(scope.start, first)).date()
    end = datetime.fromtimestamp(min(scope.end, datetime.now().timestamp())).date()
    if bucket == "week":
        start -= timedelta(days=start.weekday())
    elif bucket == "month":
        start = start.replace(day=1)
    out, d = [], start
    while d <= end:
        out.append(d.isoformat())
        if bucket == "day":
            d += timedelta(days=1)
        elif bucket == "week":
            d += timedelta(days=7)
        else:
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def timeline(scope: Scope, bucket: str) -> dict:
    cte, params = _plays_cte(scope)
    rows = db.query(
        f"""{cte} SELECT {BUCKETS[bucket]} AS b, COUNT(*) AS plays, SUM(watched)/60.0 AS minutes,
                  SUM(CASE WHEN kind='movie' THEN watched ELSE 0 END)/60.0 AS movie_minutes,
                  SUM(CASE WHEN kind='series' THEN watched ELSE 0 END)/60.0 AS series_minutes,
                  SUM(CASE WHEN kind='video' THEN watched ELSE 0 END)/60.0 AS video_minutes
            FROM p GROUP BY b""",
        params,
    )
    by_bucket = {r["b"]: r for r in rows}
    labels = _bucket_range(scope, bucket)

    def col(name):
        return [round(by_bucket.get(l, {}).get(name) or 0, 1) for l in labels]

    return {
        "labels": labels,
        "plays": [by_bucket.get(l, {}).get("plays", 0) for l in labels],
        "minutes": col("minutes"),
        "movie_minutes": col("movie_minutes"),
        "series_minutes": col("series_minutes"),
        "video_minutes": col("video_minutes"),
    }


def top(scope: Scope, kind: str, limit: int) -> list:
    cte, params = _plays_cte(scope)
    days = f"COUNT(DISTINCT date(started_at,{LOCAL})) AS days"
    if kind == "series":
        sql = f"""{cte} SELECT title_id AS key, MAX(title) AS name,
                         COUNT(DISTINCT item_id) || ' afsnit' AS sub, COUNT(DISTINCT item_id) AS episodes,
                         COUNT(*) AS plays, SUM(watched)/60.0 AS minutes, title_id AS image_id, {days}
                  FROM p WHERE kind='series' GROUP BY title_id"""
    elif kind == "channels":
        sql = f"""{cte} SELECT title_id AS key, MAX(title) AS name,
                         COUNT(DISTINCT item_id) || CASE WHEN COUNT(DISTINCT item_id) = 1 THEN ' video' ELSE ' videoer' END AS sub,
                         COUNT(DISTINCT item_id) AS videos, COUNT(*) AS plays, SUM(watched)/60.0 AS minutes,
                         title_id AS image_id, MAX(item_id) AS fallback_image_id, {days}
                  FROM p WHERE kind='video' GROUP BY title_id"""
    elif kind == "videos":
        sql = f"""{cte} SELECT item_id AS key, MAX(name) AS name, MAX(title) AS sub, MAX(title_id) AS channel_id,
                         COUNT(*) AS plays, SUM(watched)/60.0 AS minutes, item_id AS image_id, {days}
                  FROM p WHERE kind='video' GROUP BY item_id"""
    elif kind == "movies":
        sql = f"""{cte} SELECT item_id AS key, MAX(name) AS name, CAST(MAX(year) AS TEXT) AS sub,
                         COUNT(*) AS plays, SUM(watched)/60.0 AS minutes, item_id AS image_id, {days}
                  FROM p WHERE kind='movie' GROUP BY item_id"""
    elif kind == "people":
        sql = f"""{cte} SELECT json_extract(a.value,'$.name') AS key, json_extract(a.value,'$.name') AS name,
                         COUNT(DISTINCT title_id) || CASE WHEN COUNT(DISTINCT title_id) = 1 THEN ' titel' ELSE ' titler' END AS sub,
                         COUNT(*) AS plays, SUM(watched)/60.0 AS minutes,
                         MAX(json_extract(a.value,'$.id')) AS image_id, {days}
                  FROM p, json_each(p.people) a WHERE json_extract(a.value,'$.type') = 'Actor'
                  GROUP BY json_extract(a.value,'$.name')"""
    else:  # titles: series and movies together, used by compare and wrapped
        sql = f"""{cte} SELECT title_id AS key, MAX(title) AS name, MAX(kind) AS kind, NULL AS sub,
                         COUNT(*) AS plays, SUM(watched)/60.0 AS minutes, title_id AS image_id, {days}
                  FROM p GROUP BY title_id"""
    return db.query(sql + " ORDER BY minutes DESC, plays DESC LIMIT ?", [*params, limit])


def genres(scope: Scope, bucket: str, limit: int = 8) -> dict:
    """Share of watch time per genre and bucket; minor genres are folded into "Andet"."""
    cte, params = _plays_cte(scope)
    rows = db.query(
        f"""{cte} SELECT {BUCKETS[bucket]} AS b, TRIM(g.value) AS k, SUM(watched)/60.0 AS n
            FROM p, json_each(p.genres) g GROUP BY b, k""",
        params,
    )
    totals = Counter()
    for r in rows:
        totals[r["k"]] += r["n"]
    keys = [k for k, _ in totals.most_common(limit)]
    labels = _bucket_range(scope, bucket)
    grid = defaultdict(lambda: defaultdict(float))
    for r in rows:
        key = r["k"] if r["k"] in keys else "Andet"
        grid[key][r["b"]] += r["n"]
    if "Andet" in grid:
        keys.append("Andet")
    return {
        "labels": labels,
        "totals": {k: round(totals.get(k, sum(grid[k].values()))) for k in keys},
        "series": [{"name": k, "data": [round(grid[k].get(l, 0), 1) for l in labels]} for k in keys],
    }


def heatmap(scope: Scope) -> list:
    cte, params = _plays_cte(scope)
    rows = db.query(
        f"""{cte} SELECT (CAST(strftime('%w',started_at,{LOCAL}) AS INTEGER) + 6) % 7 AS wd,
                  CAST(strftime('%H',started_at,{LOCAL}) AS INTEGER) AS h, COUNT(*) AS n
            FROM p GROUP BY wd, h""",
        params,
    )
    return [[r["h"], r["wd"], r["n"]] for r in rows]


def tech(scope: Scope) -> dict:
    """How things get played: direct vs transcode, per client, resolution, subtitles and audio language."""
    where, params = scope.where(counted=None)

    def q(sql):
        return db.query(sql.format(where=where), params)

    methods = q("SELECT COALESCE(play_method,'Ukendt') AS k, COUNT(*) AS n FROM plays WHERE {where} GROUP BY k ORDER BY n DESC")
    for m in methods:
        m["label"] = METHOD_DA.get(m["k"], m["k"])
    return {
        "methods": methods,
        "clients": q("""SELECT COALESCE(client,'Ukendt') AS name, COUNT(*) AS n,
                               AVG(CASE WHEN play_method='Transcode' THEN 1.0 ELSE 0 END) AS transcode
                        FROM plays WHERE {where} GROUP BY name ORDER BY n DESC LIMIT 8"""),
        "resolutions": q(f"SELECT {RESOLUTION} AS k, COUNT(*) AS n FROM plays WHERE {{where}} GROUP BY k ORDER BY n DESC"),
        "reasons": q("""SELECT r.value AS k, COUNT(*) AS n FROM plays, json_each(plays.transcode_reasons) r
                        WHERE {where} GROUP BY k ORDER BY n DESC LIMIT 6"""),
        "subtitles": q("""SELECT COALESCE(subtitle_lang,'Ingen') AS k, COUNT(*) AS n
                          FROM plays WHERE {where} GROUP BY k ORDER BY n DESC LIMIT 6"""),
        "audio": q("""SELECT audio_lang AS k, COUNT(*) AS n FROM plays WHERE {where} AND audio_lang IS NOT NULL
                      GROUP BY k ORDER BY n DESC LIMIT 6"""),
    }


def recent(scope: Scope, limit: int = 15) -> list:
    cte, params = _plays_cte(scope, counted=None)
    rows = db.query(
        f"""{cte} SELECT item_id, name, kind, title_id, title, season_number, episode_number, user_name, device, client,
                  started_at, watched, duration, progress, counted, completed, play_method
            FROM p ORDER BY started_at DESC LIMIT ?""",
        [*params, limit],
    )
    for r in rows:
        r["episode"] = episode_label(r)
    return rows


# --- insights -------------------------------------------------------------

def insights(scope: Scope) -> list:
    """Short observations in Danish, most interesting first."""
    out = []
    cte, params = _plays_cte(scope)
    if not db.query(f"{cte} SELECT 1 FROM p LIMIT 1", params):
        return out

    peak = heatmap(scope)
    if peak:
        h, wd, _ = max(peak, key=lambda x: x[2])
        out.append({"icon": "clock", "text": f"Du ser mest om {WEEKDAYS[wd]}en omkring kl. {h:02d}."})

    fav = top(scope, "series", 1)
    if fav:
        s = fav[0]
        out.append({"icon": "star", "text": f"{s['name']} er din mest sete serie: {s['episodes']} afsnit og {_hours(s['minutes'])} timer."})

    channel = top(scope, "channels", 1)
    if channel:
        c = channel[0]
        out.append({"icon": "play", "text": f"{c['name']} er din mest sete kanal: {c['sub']} og {_hours(c['minutes'])} timer."})

    binge = biggest_binge(scope)
    if binge and binge["n"] >= 3:
        d = date.fromisoformat(binge["d"]).strftime("%d.%m")
        out.append({"icon": "binge", "text": f"Binge: {binge['n']} afsnit af {binge['name']} den {d}."})

    rewatch = db.query(
        f"""{cte} SELECT MAX(name) AS name, COUNT(DISTINCT date(started_at,{LOCAL})) AS n
            FROM p WHERE kind='movie' GROUP BY item_id HAVING n >= 2 ORDER BY n DESC LIMIT 1""",
        params,
    )
    if rewatch:
        out.append({"icon": "repeat", "text": f"Genset: {rewatch[0]['name']} er set {rewatch[0]['n']} gange i perioden."})

    forgotten = _forgotten_series(scope)
    if forgotten:
        import progress  # here, not at the top: progress builds on this module
        p = (progress.series_progress(scope.user, forgotten["key"]) or [None])[0]
        if not p or p["seen"] < p["total"]:  # a series that was simply finished isn't forgotten
            left = f" Der er {p['total'] - p['seen']} afsnit tilbage." if p else ""
            out.append({"icon": "pause", "text": f"Glemt? Du så {forgotten['episodes']} afsnit af {forgotten['name']}, "
                                                  f"men sidst for {forgotten['days']} dage siden.{left}"})

    movies = db.query(f"{cte} SELECT COUNT(*) AS n, AVG(completed) AS r FROM p WHERE kind='movie'", params)[0]
    if movies["n"] >= 5 and movies["r"] is not None and movies["r"] < 0.8:
        out.append({"icon": "stop", "text": f"Du ser {round(movies['r'] * 100)} % af dine film helt færdige."})

    weekend = _weekend_movies(scope)
    if weekend:
        out.append({"icon": "movie", "text": weekend})

    tc = _worst_transcoder(scope)
    if tc:
        out.append({"icon": "cpu", "text": f"{tc['name']} transcoder {round(tc['rate'] * 100)} % af afspilningerne. "
                                            "Det kan betale sig at tjekke klientens codec-understøttelse."})

    night = db.query(
        f"""{cte} SELECT SUM(CASE WHEN CAST(strftime('%H',started_at,{LOCAL}) AS INTEGER) >= 23
                   OR CAST(strftime('%H',started_at,{LOCAL}) AS INTEGER) < 4 THEN watched ELSE 0 END) / SUM(watched) AS r FROM p""",
        params,
    )[0]["r"]
    if night and night > 0.15:
        out.append({"icon": "moon", "text": f"Natteravn: {round(night * 100)} % af din seetid ligger mellem kl. 23 og 04."})
    return out


def _hours(minutes: float) -> str:
    return f"{minutes / 60:.1f}".replace(".", ",")


def _forgotten_series(scope: Scope, min_days: int = 45) -> Optional[dict]:
    """A series someone got into (3+ episodes) but hasn't touched for a while, as of the end of the range."""
    user_sql, user_params = user_filter(scope.user)
    rows = db.query(
        f"""SELECT i.series_id AS key, MAX(i.series_name) AS name, COUNT(DISTINCT p.item_id) AS episodes, MAX(p.started_at) AS last
            FROM plays p JOIN items i USING(item_id)
            WHERE p.counted = 1 AND i.type = 'Episode' AND i.series_id IS NOT NULL AND p.started_at < ? {user_sql}
            GROUP BY i.series_id HAVING episodes >= 3 AND last < ? ORDER BY episodes DESC LIMIT 1""",
        [scope.end, *user_params, min(scope.end, datetime.now().timestamp()) - min_days * 86400],
    )
    if not rows:
        return None
    r = rows[0]
    r["days"] = int((min(scope.end, datetime.now().timestamp()) - r["last"]) / 86400)
    return r


def _weekend_movies(scope: Scope) -> Optional[str]:
    cte, params = _plays_cte(scope)
    rows = db.query(
        f"""{cte} SELECT CAST(strftime('%w',started_at,{LOCAL}) AS INTEGER) IN (0,6) AS weekend,
                  SUM(CASE WHEN kind='movie' THEN watched ELSE 0 END) AS movie, SUM(watched) AS total
            FROM p GROUP BY weekend""",
        params,
    )
    share = {r["weekend"]: r for r in rows}
    if 0 not in share or 1 not in share or share[0]["total"] < 3 * 3600 or share[1]["total"] < 3 * 3600:
        return None
    diff = share[1]["movie"] / share[1]["total"] - share[0]["movie"] / share[0]["total"]
    if abs(diff) < 0.1:
        return None
    if diff > 0:
        return f"I weekenden bliver det til film: filmenes andel af seetiden er {round(diff * 100)} procentpoint højere end på hverdage."
    return f"Film er noget, du ser på hverdage: deres andel af seetiden er {round(-diff * 100)} procentpoint højere end i weekenden."


def _worst_transcoder(scope: Scope) -> Optional[dict]:
    where, params = scope.where(counted=None)
    rows = db.query(
        f"""SELECT client AS name, COUNT(*) AS n, AVG(CASE WHEN play_method='Transcode' THEN 1.0 ELSE 0 END) AS rate
            FROM plays WHERE {where} AND client IS NOT NULL GROUP BY client HAVING n >= 5 ORDER BY rate DESC LIMIT 1""",
        params,
    )
    return rows[0] if rows and rows[0]["rate"] >= 0.3 else None
