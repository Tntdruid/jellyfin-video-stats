"""Fill dev/data/video_stats.db with a year of fake viewing so the dashboard can be tried without Jellyfin.

    python dev/seed_demo.py
"""
import os
import random
import sys
import time
from pathlib import Path

os.environ.setdefault("DATA_DIR", str(Path(__file__).parent / "data"))
sys.path.insert(0, str(Path(__file__).parent.parent / "jellyfin_video_stats" / "app"))

import db  # noqa: E402

random.seed(11)

ACTORS = ["Sofie Holm", "Mads Kjær", "Ida Lund", "Rasmus Bech", "Freja Dahl", "Jonas Vinter", "Asta Brink",
          "Oliver Strand", "Clara Fog", "Viktor Ravn", "Nanna Krog", "Emil Storm"]
DIRECTORS = ["Lene Sand", "Bo Elm", "Karl Hede"]


def cast(seed: int, n: int = 4) -> list:
    rnd = random.Random(seed)
    people = [{"id": f"p{ACTORS.index(a)}", "name": a, "type": "Actor", "role": f"Rolle {i + 1}"}
              for i, a in enumerate(rnd.sample(ACTORS, n))]
    d = rnd.choice(DIRECTORS)
    return people + [{"id": f"d{DIRECTORS.index(d)}", "name": d, "type": "Director", "role": None}]


SERIES = [  # name, genres, seasons, episodes per season, minutes per episode
    ("Havnebyen", ["Drama", "Krimi"], 3, 8, 52),
    ("Kometjægerne", ["Science Fiction", "Eventyr"], 2, 10, 45),
    ("Køkkenkaos", ["Komedie"], 4, 12, 24),
    ("Den Sidste Vinter", ["Drama", "Thriller"], 1, 6, 58),
    ("Robotskolen", ["Animation", "Familie"], 2, 13, 22),
    ("Nattevagten", ["Krimi", "Mysterie"], 2, 8, 48),
]
MOVIES = [  # name, genres, year, minutes
    ("Stormfloden", ["Action", "Thriller"], 2021, 128), ("Sommer i Skagen", ["Romantik", "Drama"], 2019, 104),
    ("Månebasen", ["Science Fiction"], 2023, 141), ("Bedstefars Bil", ["Komedie", "Familie"], 2018, 92),
    ("Skyggespillet", ["Thriller", "Mysterie"], 2022, 117), ("Ulvenes Dal", ["Eventyr", "Familie"], 2020, 99),
    ("Den Glemte Kode", ["Thriller", "Science Fiction"], 2024, 133), ("Kaffe og Kaos", ["Komedie"], 2017, 88),
    ("Fyrtårnet", ["Drama"], 2016, 121), ("Rumrotterne", ["Animation", "Familie"], 2022, 85),
    ("Sidste Tog", ["Action"], 2025, 112), ("Byens Lys", ["Drama", "Romantik"], 2015, 109),
]

db.connect()
db.execute("DELETE FROM plays")
db.execute("DELETE FROM items")

episodes = {}
for si, (name, genres, seasons, per, minutes) in enumerate(SERIES):
    sid = f"ser{si}"
    people = cast(si)
    episodes[si] = []
    for s in range(1, seasons + 1):
        for e in range(1, per + 1):
            item = {
                "item_id": f"ep{si}x{s}x{e}", "type": "Episode", "name": f"Afsnit {e}", "series_id": sid,
                "series_name": name, "season_number": s, "episode_number": e, "year": 2018 + si, "genres": genres,
                "studios": ["DR"], "people": people, "official_rating": "11", "duration": minutes * 60 + random.randint(-90, 90),
                "fetched_at": int(time.time()),
            }
            db.upsert_item(item)
            episodes[si].append(item)

movies = []
for mi, (name, genres, year, minutes) in enumerate(MOVIES):
    item = {
        "item_id": f"mov{mi}", "type": "Movie", "name": name, "year": year, "genres": genres, "studios": ["Nordisk Film"],
        "people": cast(100 + mi, 5), "official_rating": "15", "community_rating": round(random.uniform(5.5, 8.6), 1),
        "duration": minutes * 60, "fetched_at": int(time.time()),
    }
    db.upsert_item(item)
    movies.append(item)

CHANNELS = [  # YouTube-style downloads in a home videos library: name, genres, typical minutes
    ("Kodehjørnet", ["Teknologi"], 18), ("Haveliv med Hanne", ["Hobby"], 12),
    ("Retro Spilhallen", ["Gaming"], 25), ("Rumnyt", ["Videnskab"], 9),
]
videos = []
for ci, (name, genres, minutes) in enumerate(CHANNELS):
    for vi in range(25):
        item = {
            "item_id": f"vid{ci}x{vi}", "type": "Video", "name": f"{name.split()[0]} #{vi + 1}", "series_id": f"chan{ci}",
            "series_name": name, "genres": genres, "duration": max(120, minutes * 60 + random.randint(-300, 300)),
            "fetched_at": int(time.time()),
        }
        db.upsert_item(item)
        videos.append((ci, item))

CLIENTS = [  # client, device, chance of transcoding
    ("Jellyfin Android TV", "Stue-TV", 0.05), ("Jellyfin Web", "Chrome", 0.45),
    ("Infuse", "Apple TV", 0.0), ("Jellyfin Mobile", "Telefon", 0.25),
]
REASONS = [["AudioCodecNotSupported"], ["VideoCodecNotSupported"], ["ContainerBitrateExceedsLimit"], ["SubtitleCodecNotSupported"]]
now = time.time()
DAY = 86400
users = [("u1", "Christian"), ("u2", "Gæst")]
progress = {(u, si): 0 for u, _ in users for si in range(len(SERIES))}


def play(uid, uname, item, t, client):
    cname, device, tc_chance = client
    dur = item["duration"]
    peek = random.random() < 0.07
    if peek:
        frac = random.uniform(0.05, 0.3)
    elif random.random() < 0.12:
        frac = random.uniform(0.4, 0.85)
    else:
        frac = random.uniform(0.93, 1.0)
    watched = dur * frac
    transcode = random.random() < tc_chance
    db.insert_play({
        "item_id": item["item_id"], "user_id": uid, "user_name": uname, "client": cname, "device": device,
        "started_at": int(t), "ended_at": int(t + watched + random.randint(0, 600)), "watched": round(watched, 1),
        "duration": dur, "progress": round(frac, 3), "counted": int(watched >= min(dur * 0.5, 1800)),
        "completed": int(frac >= 0.9),
        "play_method": "Transcode" if transcode else random.choice(["DirectPlay", "DirectPlay", "DirectStream"]),
        "video_codec": random.choice(["h264", "hevc", "hevc", "av1"]), "height": random.choice([2160, 1080, 1080, 1080, 720]),
        "audio_lang": random.choice(["eng", "eng", "eng", "dan"]),
        "subtitle_lang": random.choice([None, "dan", "dan", "eng"]),
        "transcode_reasons": random.choice(REASONS) if transcode else [],
    })
    return t + watched + random.randint(60, 300)


for day in range(400, -1, -1):
    weekend = time.localtime(now - day * DAY).tm_wday >= 5
    for uid, uname in users:
        if random.random() < (0.35 if uid == "u1" else 0.75):
            continue
        hour = random.choice([19, 20, 20, 21, 21, 22] + ([14, 15, 16, 23] if weekend else [7, 23]))
        base = now - day * DAY
        lt = time.localtime(base)
        t = base - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) + hour * 3600 + random.randint(0, 1800)
        client = random.choices(CLIENTS, [5, 2, 3, 2] if uid == "u1" else [1, 3, 0, 4])[0]
        if uid == "u1" and random.random() < 0.4:  # a few videos before the evening's main thing
            for _ in range(random.randint(1, 4)):
                _, item = random.choices(videos, [4 if ci == 0 else 3 if ci == 2 else 1 for ci, _ in videos])[0]
                t = play(uid, uname, item, t - 3600, CLIENTS[3]) + 3600
        if random.random() < (0.45 if weekend else 0.18):
            t = play(uid, uname, random.choice(movies if day > 30 else movies[-4:] + movies), t, client)
        else:
            # taste drifts: Kometjægerne gets binged in spring, Nattevagten only shows up recently
            weights = [3, 4 if 150 < day < 260 else 0.5, 2, 1, 1.5 if weekend else 0.3, 6 if day < 60 else 0]
            si = random.choices(range(len(SERIES)), weights)[0]
            n = random.choice([1, 1, 2, 2, 3]) + (random.randint(2, 7) if weekend and random.random() < 0.3 else 0)
            for _ in range(n):
                idx = progress[(uid, si)] % len(episodes[si])
                progress[(uid, si)] += 1
                t = play(uid, uname, episodes[si][idx], t, client)
                if t > now:
                    break

db.execute("DELETE FROM plays WHERE started_at > ?", [int(now)])

# what the progress refresher would have fetched from Jellyfin: full episode lists, some with seasons not watched yet
for table in ("series_episodes", "series_info", "episode_played"):
    db.execute(f"DELETE FROM {table}")
EXTRA_SEASONS = {0: 1, 5: 1}  # Havnebyen and Nattevagten got a new season nobody has started
STATUS = {0: "Continuing", 1: "Ended", 2: "Ended", 3: "Ended", 4: "Continuing", 5: "Continuing"}
for si, (name, genres, seasons, per, minutes) in enumerate(SERIES):
    db.execute("INSERT INTO series_info (series_id, name, status, refreshed_at) VALUES (?,?,?,?)",
               [f"ser{si}", name, STATUS[si], int(now)])
    for s in range(1, seasons + 1 + EXTRA_SEASONS.get(si, 0)):
        for e in range(1, per + 1):
            db.execute("INSERT INTO series_episodes VALUES (?,?,?,?,?,?)",
                       [f"ep{si}x{s}x{e}", f"ser{si}", s, e, f"Afsnit {e}", minutes * 60])
# the guest marked the first season of Den Sidste Vinter as watched by hand in Jellyfin
for e in range(1, 7):
    db.execute("INSERT OR REPLACE INTO episode_played VALUES ('u2', ?, NULL)", [f"ep3x1x{e}"])
# and the first episodes of Nattevagten exist, but the last ones haven't been reached by anyone
db.execute("DELETE FROM plays WHERE item_id IN ('ep5x2x6','ep5x2x7','ep5x2x8')")
print(db.query("SELECT COUNT(*) AS n FROM plays")[0]["n"], "plays seeded")
