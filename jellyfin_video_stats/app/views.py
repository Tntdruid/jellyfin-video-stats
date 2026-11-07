"""Queries behind the series/movie/person pages, Wrapped, user comparison and CSV export."""
import csv
import io
import json
import math
from collections import Counter
from datetime import datetime
from typing import Optional

import db
import stats
from stats import LOCAL, METHOD_DA, WEEKDAYS, Scope, episode_label

# {t} is an alias that carries the item columns (series_id, item_id, people)
FILTERS = {
    "series": "{t}.series_id = ?",
    "channel": "{t}.series_id = ?",  # videos keep their channel in series_id
    "movie": "{t}.item_id = ?",
    "person": "EXISTS (SELECT 1 FROM json_each({t}.people) a WHERE json_extract(a.value,'$.name') = ?)",
}
TYPE_DA = {"Movie": "Film", "Episode": "Afsnit", "Video": "Video"}
RANKING = {"series": "series", "channel": "channels", "movie": "movies", "person": "people"}


# --- series / movie / person pages ----------------------------------------

def detail(scope: Scope, kind: str, key: str) -> Optional[dict]:
    cte, params = stats._plays_cte(scope)
    base = f"{cte}, ap AS (SELECT * FROM p WHERE {FILTERS[kind].format(t='p')})"
    params = [*params, key]

    totals = db.query(
        f"""{base} SELECT COUNT(*) AS plays, COALESCE(SUM(watched),0)/60.0 AS minutes,
                  COUNT(DISTINCT item_id) AS items, COUNT(DISTINCT title_id) AS titles,
                  COUNT(DISTINCT season_number) AS seasons, SUM(completed) AS completed,
                  COUNT(DISTINCT date(started_at,{LOCAL})) AS days, MAX(started_at) AS last
            FROM ap""",
        params,
    )[0]
    if not totals["plays"]:
        return None

    user_sql, user_params = stats.user_filter(scope.user)
    first = db.query(
        f"""SELECT MIN(p.started_at) AS t FROM plays p JOIN items i USING(item_id)
            WHERE p.counted = 1 {user_sql} AND {FILTERS[kind].format(t='i')}""",
        [*user_params, key],
    )[0]["t"]

    ranking = stats.top(scope, RANKING[kind], 1000)
    rank = next((i + 1 for i, r in enumerate(ranking) if r["key"] == key), None)
    all_minutes = stats._totals(scope)["minutes"] or 1

    months = db.query(f"{base} SELECT strftime('%Y-%m-01',started_at,{LOCAL}) AS b, SUM(watched)/3600.0 AS n FROM ap GROUP BY b", params)
    hours = db.query(f"{base} SELECT CAST(strftime('%H',started_at,{LOCAL}) AS INTEGER) AS h, COUNT(*) AS n FROM ap GROUP BY h", params)
    weekdays = db.query(
        f"{base} SELECT (CAST(strftime('%w',started_at,{LOCAL}) AS INTEGER) + 6) % 7 AS d, COUNT(*) AS n FROM ap GROUP BY d", params
    )
    genres = db.query(
        # aliased "genre", not "name": ap already has a name column, which GROUP BY would pick instead
        f"""{base} SELECT TRIM(g.value) AS genre, COUNT(*) AS n FROM ap, json_each(ap.genres) g
            GROUP BY genre ORDER BY n DESC LIMIT 6""",
        params,
    )
    genres = [{"name": g["genre"], "n": g["n"]} for g in genres]
    viewers = db.query(
        f"""{base} SELECT user_name AS name, COUNT(*) AS plays, SUM(watched)/60.0 AS minutes
            FROM ap GROUP BY user_id ORDER BY minutes DESC""",
        params,
    )

    if kind == "series":
        items = db.query(
            f"""{base} SELECT item_id AS key, MAX(name) AS name, MAX(season_number) AS season_number,
                      MAX(episode_number) AS episode_number, COUNT(*) AS plays, SUM(watched)/60.0 AS minutes,
                      MAX(completed) AS completed, item_id AS image_id
                FROM ap GROUP BY item_id ORDER BY season_number, episode_number LIMIT 200""",
            params,
        )
        for r in items:
            r["sub"] = episode_label(r)
        latest = db.query(f"{base} SELECT name, season_number, episode_number FROM ap ORDER BY started_at DESC LIMIT 1", params)[0]
        latest["episode"] = episode_label(latest)
    elif kind == "channel":
        items = db.query(
            f"""{base} SELECT item_id AS key, MAX(name) AS name, COUNT(*) AS plays, SUM(watched)/60.0 AS minutes,
                      MAX(completed) AS completed, MAX(started_at) AS last, item_id AS image_id
                FROM ap GROUP BY item_id ORDER BY last DESC LIMIT 100""",
            params,
        )
        for r in items:
            r["sub"] = datetime.fromtimestamp(r["last"]).strftime("set %d.%m.%Y")
        latest = None
    elif kind == "person":
        items = db.query(
            f"""{base} SELECT title_id AS key, MAX(title) AS name, MAX(kind) AS kind,
                      CASE MAX(kind) WHEN 'series' THEN 'Serie' WHEN 'video' THEN 'Kanal' ELSE 'Film' END AS sub,
                      COUNT(*) AS plays, SUM(watched)/60.0 AS minutes, title_id AS image_id
                FROM ap GROUP BY title_id ORDER BY minutes DESC LIMIT 30""",
            params,
        )
        latest = None
    else:
        items = _cast(key)
        latest = None

    month_map = {r["b"]: round(r["n"], 1) for r in months}
    labels = stats._bucket_range(Scope(max(scope.start, first or scope.start), scope.end, scope.user), "month")
    hour_counts = {r["h"]: r["n"] for r in hours}
    day_counts = {r["d"]: r["n"] for r in weekdays}
    return {
        "kind": kind,
        "key": key,
        **_header(kind, key),
        **totals,
        "first": first,
        "rank": rank,
        "share": totals["minutes"] / all_minutes,
        "list": items,
        "latest": latest,
        "viewers": viewers,
        "months": {"labels": labels, "hours": [month_map.get(l, 0) for l in labels]},
        "hours": [hour_counts.get(h, 0) for h in range(24)],
        "weekdays": [day_counts.get(d, 0) for d in range(7)],
        "genres": genres,
    }


def _cast(item_id: str) -> list:
    rows = db.query("SELECT people FROM items WHERE item_id = ?", [item_id])
    people = json.loads(rows[0]["people"]) if rows else []
    return [
        {"key": p["name"], "name": p["name"], "sub": p.get("role") or ("Instruktør" if p.get("type") == "Director" else None),
         "image_id": p.get("id"), "plays": None, "minutes": None}
        for p in sorted(people, key=lambda p: p.get("type") != "Director")
    ][:20]


def _header(kind: str, key: str) -> dict:
    """Title, poster and facts shown at the top of the page."""
    if kind == "person":
        row = db.query(
            """SELECT json_extract(a.value,'$.id') AS id FROM items, json_each(items.people) a
               WHERE json_extract(a.value,'$.name') = ? AND json_extract(a.value,'$.id') IS NOT NULL LIMIT 1""",
            [key],
        )
        return {"name": key, "image_id": row[0]["id"] if row else None}
    if kind == "channel":
        rows = db.query("SELECT MAX(series_name) AS name, MAX(item_id) AS video FROM items WHERE series_id = ?", [key])
        r = rows[0] if rows else {}
        return {"name": r.get("name") or key, "image_id": key, "fallback_image_id": r.get("video")}
    if kind == "series":
        rows = db.query(
            """SELECT MAX(series_name) AS name, MIN(year) AS year, MAX(official_rating) AS official_rating,
                      MAX(studios) AS studios FROM items WHERE series_id = ?""",
            [key],
        )
        r = rows[0] if rows else {}
        return {"name": r.get("name") or key, "image_id": key, "year": r.get("year"),
                "official_rating": r.get("official_rating"), "studios": json.loads(r.get("studios") or "[]")}
    rows = db.query("SELECT * FROM items WHERE item_id = ?", [key])
    if not rows:
        return {"name": key, "image_id": key}
    t = rows[0]
    return {
        "name": t["name"],
        "image_id": key,
        "year": t["year"],
        "duration": t["duration"],
        "official_rating": t["official_rating"],
        "community_rating": t["community_rating"],
        "studios": json.loads(t["studios"] or "[]"),
    }


# --- wrapped ---------------------------------------------------------------

def wrapped_years() -> list:
    rows = db.query(f"SELECT DISTINCT strftime('%Y',started_at,{LOCAL}) AS y FROM plays ORDER BY y DESC")
    return [int(r["y"]) for r in rows]


def wrapped(year: int, user: Optional[str]) -> dict:
    start = int(datetime(year, 1, 1).timestamp())
    end = int(datetime(year + 1, 1, 1).timestamp())
    scope = Scope(start, end, user)
    s = stats.summary(scope)
    if not s["plays"]:
        return {"year": year, "plays": 0}

    cte, params = stats._plays_cte(scope)
    busiest = db.query(
        f"""{cte} SELECT date(started_at,{LOCAL}) AS d, COUNT(*) AS n, SUM(watched)/60.0 AS minutes
            FROM p GROUP BY d ORDER BY minutes DESC LIMIT 1""",
        params,
    )[0]
    first_watch = db.query(
        f"{cte} SELECT name, title, kind, season_number, episode_number, started_at FROM p ORDER BY started_at LIMIT 1",
        params,
    )[0]
    first_watch["episode"] = episode_label(first_watch)
    rewatch = db.query(
        f"""{cte} SELECT MAX(name) AS name, item_id AS key, COUNT(DISTINCT date(started_at,{LOCAL})) AS n
            FROM p WHERE kind='movie' GROUP BY item_id HAVING n >= 2 ORDER BY n DESC LIMIT 1""",
        params,
    )
    sessions = stats._sessions(scope)
    longest = max(sessions, key=lambda x: x[-1]["ended_at"] - x[0]["started_at"]) if sessions else None

    genres = stats.genres(scope, "month")["totals"]
    genres.pop("Andet", None)
    months = stats.timeline(scope, "month")
    peak = max(stats.heatmap(scope), key=lambda c: c[2])
    top_series = stats.top(scope, "series", 5)
    top_share = top_series[0]["minutes"] / s["minutes"] if top_series and s["minutes"] else 0

    return {
        "year": year,
        **s,
        "top_series": top_series,
        "top_movies": stats.top(scope, "movies", 5),
        "top_people": stats.top(scope, "people", 5),
        "top_channels": stats.top(scope, "channels", 5),
        "genres": [{"name": k, "n": v} for k, v in list(genres.items())[:5]],
        "months": months,
        "peak": {"hour": peak[0], "weekday": WEEKDAYS[peak[1]]},
        "busiest_day": busiest,
        "first_watch": first_watch,
        "rewatch": rewatch[0] if rewatch else None,
        "longest_session": {
            "minutes": (longest[-1]["ended_at"] - longest[0]["started_at"]) / 60,
            "start": longest[0]["started_at"],
            "items": len(longest),
        } if longest else None,
        "persona": _persona(s, peak[0], top_share),
    }


def _persona(s: dict, peak_hour: int, top_share: float) -> dict:
    share = {k: s[f"{k}_minutes"] / s["minutes"] if s["minutes"] else 0 for k in ("movie", "series", "video")}
    binge = s["binge"]["n"] if s["binge"] else 0
    rules = [
        (binge >= 8, "Binge-mesteren", f"{binge} afsnit af {s['binge']['name'] if s['binge'] else ''} på én dag. Bare ét afsnit mere…"),
        (share["video"] > 0.5, "Kanal-zapperen", f"{round(share['video'] * 100)} % af din seetid gik til videoer fra {s['channels']} kanaler."),
        (peak_hour >= 23 or peak_hour < 4, "Natteravnen", "Din skærm lyser, når andre sover."),
        (share["movie"] > 0.6, "Filmnørden", f"{round(share['movie'] * 100)} % af din seetid gik til film."),
        (share["series"] > 0.8 and s["series"] >= 3, "Seriejunkien", f"Serier stod for {round(share['series'] * 100)} % af din seetid."),
        (top_share > 0.3, "Den trofaste fan", f"Din yndlingsserie fyldte {round(top_share * 100)} % af alt, du så."),
        (s["titles"] > 60, "Altæderen", f"{s['titles']} forskellige film og serier – du ser lidt af det hele."),
        (peak_hour < 12, "Morgenmaden", "Du ser helst noget, før dagen rigtig er gået i gang."),
    ]
    for ok, title, text in rules:
        if ok:
            return {"title": title, "text": text}
    return {"title": "Sofaentusiasten", "text": "Film og serier er en fast del af din hverdag."}


# --- compare ---------------------------------------------------------------

def compare(scope: Scope) -> dict:
    people = []
    vectors = {}
    for u in stats.users():
        us = Scope(scope.start, scope.end, u["id"])
        t = stats._totals(us)
        if not t["plays"]:
            continue
        titles = stats.top(us, "titles", 300)
        vectors[u["id"]] = {r["name"]: r["minutes"] for r in titles}
        genres = stats.genres(us, "month")["totals"]
        genres.pop("Andet", None)
        hours = Counter()
        for h, _, n in stats.heatmap(us):
            hours[h] += n
        people.append({
            "id": u["id"],
            "name": u["name"] or u["id"],
            **t,
            "top_series": (stats.top(us, "series", 1) or [None])[0],
            "top_movie": (stats.top(us, "movies", 1) or [None])[0],
            "top_channel": (stats.top(us, "channels", 1) or [None])[0],
            "top_genre": max(genres, key=genres.get) if genres else None,
            "peak_hour": hours.most_common(1)[0][0] if hours else None,
        })

    pairs = []
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            va, vb = vectors[a["id"]], vectors[b["id"]]
            shared = sorted(set(va) & set(vb), key=lambda k: -(va[k] + vb[k]))
            pairs.append({
                "a": a["name"], "b": b["name"],
                "match": _cosine(va, vb),
                "shared": shared[:12],
                "shared_count": len(shared),
            })
    return {"people": people, "pairs": pairs}


def _cosine(a: dict, b: dict) -> float:
    # log-damped so one long series doesn't dominate the match
    la = {k: math.log1p(v) for k, v in a.items()}
    lb = {k: math.log1p(v) for k, v in b.items()}
    dot = sum(la[k] * lb[k] for k in set(la) & set(lb))
    norm = math.sqrt(sum(v * v for v in la.values())) * math.sqrt(sum(v * v for v in lb.values()))
    return dot / norm if norm else 0


# --- export ----------------------------------------------------------------

def export_csv(scope: Scope) -> str:
    where, params = scope.where(counted=None, alias="p")
    rows = db.query(
        f"""SELECT datetime(p.started_at,{LOCAL}) AS tidspunkt, p.user_name, i.type, i.series_name, i.season_number,
                   i.episode_number, i.name, i.year, i.genres, ROUND(p.watched/60.0,1) AS minutter,
                   CAST(ROUND(p.duration/60.0) AS INTEGER) AS laengde, CAST(ROUND(p.progress*100) AS INTEGER) AS naaet,
                   p.counted, p.completed,
                   p.play_method, p.height, p.audio_lang, p.subtitle_lang, p.client, p.device
            FROM plays p LEFT JOIN items i USING(item_id)
            WHERE {where} ORDER BY p.started_at""",
        params,
    )
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")  # semicolon so Danish Excel opens it directly
    w.writerow(["tidspunkt", "bruger", "type", "serie_eller_kanal", "afsnit", "titel", "år", "genrer", "minutter_set",
                "længde_min", "nået_til_pct", "talt_som_set", "set_færdig", "afspilning", "højde_px", "lydsprog",
                "undertekster", "klient", "enhed"])
    for r in rows:
        w.writerow([
            r["tidspunkt"], r["user_name"], TYPE_DA.get(r["type"], r["type"]), r["series_name"] or "",
            episode_label(r), r["name"], r["year"], ", ".join(json.loads(r["genres"] or "[]")),
            _comma(r["minutter"]), r["laengde"], r["naaet"], "ja" if r["counted"] else "nej",
            "ja" if r["completed"] else "nej", METHOD_DA.get(r["play_method"], r["play_method"] or ""), r["height"],
            r["audio_lang"], r["subtitle_lang"], r["client"], r["device"],
        ])
    return "﻿" + out.getvalue()  # BOM so Excel picks UTF-8 for æøå


def _comma(v) -> str:
    return "" if v is None else str(v).replace(".", ",")
