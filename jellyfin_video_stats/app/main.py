import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
import images
import stats
import views
from collector import Collector
import importer
from config import load_settings
from importer import Importer
from jellyfin import JellyfinClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # otherwise one line per poll
log = logging.getLogger("main")

settings = load_settings()
STATIC = Path(__file__).parent / "static"
state = {"collector": None, "client": None, "importer": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    task = None
    if settings.collector_enabled:
        client = JellyfinClient(settings.jellyfin_url, settings.api_key)
        collector = Collector(settings, client)
        state.update(client=client, collector=collector)
        task = asyncio.create_task(collector.run())
        log.info("collecting from %s every %ss", settings.jellyfin_url, settings.poll_interval)
        state["importer"] = Importer(settings, client)
        if not db.get_meta("import_playback_reporting"):  # first start: pull in history once, if the plugin is there
            state["import_task"] = asyncio.create_task(state["importer"].run())
    else:
        log.warning("jellyfin_url/api_key not set - collector disabled, serving existing data only")
    yield
    if task:
        task.cancel()
        state["collector"].flush()
        await state["client"].close()


app = FastAPI(lifespan=lifespan)


def scope(start: Optional[int], end: Optional[int], user: Optional[str]) -> stats.Scope:
    return stats.Scope(start or 0, end or int(time.time()) + 60, user or None)


def current_user(request: Request, users: list) -> dict:
    """Match the Home Assistant user behind the ingress request to a Jellyfin user.

    HA's ingress proxy adds X-Remote-User-Name / -Display-Name; the user_map option covers
    people whose HA and Jellyfin names differ.
    """
    ha_names = [request.headers.get(h, "").strip().lower()
                for h in ("X-Remote-User-Name", "X-Remote-User-Display-Name")]
    ha_names = [n for n in ha_names if n]
    wanted = [settings.user_map[n] for n in ha_names if n in settings.user_map] + ha_names
    by_name = {(u["name"] or "").lower(): u["id"] for u in users}
    match = next((by_name[n] for n in wanted if n in by_name), None)
    return {"ha_user": request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name"),
            "jellyfin_user": match}


@app.get("/api/meta")
def meta(request: Request):
    c = state["collector"]
    users = stats.users()
    return {
        "users": users,
        "me": current_user(request, users),
        "first_play": stats.first_play(),
        "collector": {
            "enabled": settings.collector_enabled,
            "last_poll": c.state.last_poll if c else None,
            "poll_interval": settings.poll_interval,
            "last_error": c.state.last_error if c else None,
        },
        "import": {
            **importer.status,
            "enabled": state["importer"] is not None,
            "last_run": db.get_meta("import_playback_reporting"),
            "total": db.query("SELECT COUNT(*) AS n FROM plays WHERE source = ?", [importer.SOURCE])[0]["n"],
        },
    }


@app.post("/api/import")
async def run_import():
    if not state["importer"]:
        raise HTTPException(400, "Opsamlingen er ikke sat op (mangler Jellyfin URL/API-nøgle)")
    if not importer.status["running"]:
        state["import_task"] = asyncio.create_task(state["importer"].run())
    return {"started": True}


@app.get("/api/now")
def now_playing():
    c = state["collector"]
    return c.now_playing() if c else []


@app.get("/api/latest")
def latest():
    """Cheap change marker; the page polls it and reloads its data when it moves."""
    row = db.query("SELECT MAX(id) AS play, COUNT(*) AS n FROM plays")[0]
    return {"marker": f"{row['play']}-{row['n']}"}


@app.get("/api/summary")
def summary(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    return stats.summary(scope(start, end, user))


@app.get("/api/timeline")
def timeline(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None,
             bucket: str = Query("day", pattern="^(day|week|month)$")):
    return stats.timeline(scope(start, end, user), bucket)


@app.get("/api/top")
def top(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None,
        kind: str = Query("series", pattern="^(series|movies|people|channels|videos|titles)$"), limit: int = Query(10, le=100)):
    return stats.top(scope(start, end, user), kind, limit)


@app.get("/api/genres")
def genres(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None,
           bucket: str = Query("month", pattern="^(day|week|month)$")):
    return stats.genres(scope(start, end, user), bucket)


@app.get("/api/heatmap")
def heatmap(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    return stats.heatmap(scope(start, end, user))


@app.get("/api/tech")
def tech(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    return stats.tech(scope(start, end, user))


@app.get("/api/recent")
def recent(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    return stats.recent(scope(start, end, user))


@app.get("/api/insights")
def insights(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    return stats.insights(scope(start, end, user))


@app.get("/api/detail")
def detail(key: str, kind: str = Query(pattern="^(series|movie|person|channel)$"),
           start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    data = views.detail(scope(start, end, user), kind, key)
    if not data:
        raise HTTPException(404, "Intet set i perioden")
    return data


@app.get("/api/wrapped")
def wrapped(year: Optional[int] = None, user: Optional[str] = None):
    years = views.wrapped_years()
    year = year or (years[0] if years else datetime.now().year)
    return {"years": years, **views.wrapped(year, user or None)}


@app.get("/api/compare")
def compare(start: Optional[int] = None, end: Optional[int] = None):
    return views.compare(scope(start, end, None))


@app.get("/api/export.csv")
def export(start: Optional[int] = None, end: Optional[int] = None, user: Optional[str] = None):
    filename = f"videostatistik-{datetime.now():%Y-%m-%d}.csv"
    return Response(views.export_csv(scope(start, end, user)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/image/{item_id}")
async def image(item_id: str):
    if not item_id.isalnum():
        raise HTTPException(404)
    path = await images.get(state["client"], item_id)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type=images.MEDIA_TYPE.get(path.suffix, "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
