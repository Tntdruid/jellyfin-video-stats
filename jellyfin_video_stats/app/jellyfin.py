import hashlib
import time
from typing import Optional

import httpx

TICKS_PER_SECOND = 10_000_000
# "Video" covers home videos, mixed-content libraries and channel plugins, which is where YouTube downloads
# usually end up; in a Movies or Shows library they arrive as Movie or Episode instead.
VIDEO_TYPES = ("Movie", "Episode", "Video")
PEOPLE_TYPES = ("Actor", "Director")
MAX_PEOPLE = 25
ITEM_FIELDS = "Genres,Studios,People,ProductionYear,OfficialRating,CommunityRating,ParentId,Path"
LIBRARY_TYPES = ("CollectionFolder", "UserRootFolder", "AggregateFolder")


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                # the standard scheme; newer Jellyfin versions can reject the legacy X-Emby-Token header
                "Authorization": (
                    'MediaBrowser Client="Jellyfin Video Stats", Device="Home Assistant", '
                    f'DeviceId="jellyfin-video-stats", Version="0.1", Token="{api_key}"'
                ),
                "X-Emby-Token": api_key,
                "Accept": "application/json",
            },
            timeout=15,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def sessions(self) -> list:
        r = await self.client.get("/Sessions")
        r.raise_for_status()
        return r.json()

    async def item(self, item_id: str, user_id: Optional[str]) -> Optional[dict]:
        params = {"ids": item_id, "fields": ITEM_FIELDS, "enableImages": "false"}
        if user_id:
            params["userId"] = user_id
        r = await self.client.get("/Items", params=params)
        r.raise_for_status()
        items = r.json().get("Items", [])
        return items[0] if items else None

    async def items(self, ids: list) -> list:
        """Several items in one call; ids that no longer exist are simply missing from the result."""
        r = await self.client.get("/Items", params={"ids": ",".join(ids), "fields": ITEM_FIELDS, "enableImages": "false",
                                                    "recursive": "true"})
        r.raise_for_status()
        return r.json().get("Items", [])

    async def episodes(self, series_id: str, user_id: Optional[str]) -> Optional[list]:
        """All episodes of a series, with the user's played mark when a user is given; None if the series is gone."""
        params = {"fields": "UserData", "enableImages": "false"}
        if user_id:
            params["userId"] = user_id
        r = await self.client.get(f"/Shows/{series_id}/Episodes", params=params)
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.json().get("Items", [])

    async def recent_episodes(self, limit: int = 100) -> list:
        """Episodes most recently added to the library, newest first."""
        r = await self.client.get("/Items", params={
            "IncludeItemTypes": "Episode", "Recursive": "true", "SortBy": "DateCreated", "SortOrder": "Descending",
            "Limit": str(limit), "Fields": "DateCreated", "enableImages": "false",
        })
        r.raise_for_status()
        return r.json().get("Items", [])

    async def users(self) -> list:
        r = await self.client.get("/Users")
        r.raise_for_status()
        return r.json()

    async def playback_reporting(self, sql: str) -> Optional[list]:
        """Rows from the Playback Reporting plugin's database, or None when the plugin isn't installed."""
        r = await self.client.post("/user_usage_stats/submit_custom_query",
                                   json={"CustomQueryString": sql, "ReplaceUserId": False}, timeout=120)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if data.get("message") and not data.get("results") and "no data returned" not in data["message"]:
            raise RuntimeError(f"Playback Reporting: {data['message'][:200]}")
        cols = data.get("colums") or data.get("columns") or []  # the plugin really spells it "colums"
        return [dict(zip(cols, row)) for row in data.get("results") or []]

    async def image(self, item_id: str, max_width: int = 300) -> Optional[httpx.Response]:
        r = await self.client.get(
            f"/Items/{item_id}/Images/Primary", params={"maxWidth": max_width, "quality": 85}
        )
        return r if r.status_code == 200 else None


def people_of(item: dict) -> list:
    return [
        {"id": p.get("Id"), "name": p["Name"], "type": p.get("Type"), "role": p.get("Role")}
        for p in item.get("People") or []
        if p.get("Name") and p.get("Type") in PEOPLE_TYPES
    ]


def to_item(item: dict) -> dict:
    """series_id/series_name hold the series for an episode and the channel for a video."""
    ticks = item.get("RunTimeTicks") or 0
    video = item.get("Type") == "Video"
    return {
        "item_id": item["Id"],
        "type": item.get("Type"),
        "name": item.get("Name") or "Ukendt",
        "series_id": item.get("ChannelId") if video else item.get("SeriesId"),
        "series_name": item.get("ChannelName") if video else item.get("SeriesName"),
        "season_number": item.get("ParentIndexNumber"),
        "episode_number": item.get("IndexNumber"),
        "year": item.get("ProductionYear"),
        "genres": [g.strip() for g in item.get("Genres") or [] if g.strip()],
        "studios": [s["Name"] for s in item.get("Studios") or [] if s.get("Name")],
        "people": people_of(item)[:MAX_PEOPLE],
        "official_rating": item.get("OfficialRating"),
        "community_rating": item.get("CommunityRating"),
        "duration": ticks / TICKS_PER_SECOND if ticks else None,
        "fetched_at": int(time.time()),
    }


def merge_series(episode: dict, series: dict) -> dict:
    """Episodes rarely carry genres or the main cast themselves; borrow them from the series."""
    if not episode["genres"]:
        episode["genres"] = [g.strip() for g in series.get("Genres") or [] if g.strip()]
    if not episode["studios"]:
        episode["studios"] = [s["Name"] for s in series.get("Studios") or [] if s.get("Name")]
    if not episode["year"]:
        episode["year"] = series.get("ProductionYear")
    if not episode["official_rating"]:
        episode["official_rating"] = series.get("OfficialRating")
    seen = {p["name"] for p in episode["people"]}
    extra = [p for p in people_of(series) if p["name"] not in seen]
    episode["people"] = (extra + episode["people"])[:MAX_PEOPLE]  # main cast first, then guests
    return episode


def in_video_folder(path: Optional[str], folders) -> bool:
    """True when one of the folders in the item's path is named like a configured video folder (e.g. "Youtube").

    YouTube downloads in a Movies library come through as Movie, so this is how they are told apart.
    Whole folder names are compared, so a film called "YouTube Story" in a normal folder isn't caught.
    """
    if not path or not folders:
        return False
    parts = [p.lower() for p in path.replace("\\", "/").split("/")[:-1]]
    wanted = [f.strip().strip("/\\").lower() for f in folders if f.strip()]
    return any(("/" in w and f"/{w}/" in "/".join(parts) + "/") or w in parts for w in wanted)


def as_video(item: dict, raw: dict, folders) -> dict:
    """Reclassify a Movie living in a video folder as a Video, so it is grouped by channel instead."""
    if item["type"] == "Movie" and in_video_folder(raw.get("Path"), folders):
        item["type"] = "Video"
        studio = next((s["Name"] for s in raw.get("Studios") or [] if s.get("Name")), None)
        item["series_name"] = item["series_name"] or studio
    return item


def set_channel(video: dict, raw: dict, parent: Optional[dict]) -> dict:
    """Group a video under a channel when Jellyfin didn't name one.

    yt-dlp/ytdl-sub write the channel as <studio> in the video's .nfo, which Jellyfin reads into Studios, so that
    is the most precise source. Without it the parent folder is the best guess (downloaders tend to make one
    folder per channel), and the library itself is the last resort.
    """
    if video["series_id"]:
        return video
    studio = next((s for s in raw.get("Studios") or [] if s.get("Name")), None)
    if studio:
        name = studio["Name"].strip()
        # Jellyfin's own studio id when it has one, so the id stays stable; otherwise one derived from the name
        sid = studio.get("Id") if (studio.get("Id") or "").isalnum() else None
        video["series_id"] = sid or "studio" + hashlib.md5(name.lower().encode("utf-8")).hexdigest()
        video["series_name"] = name
    elif parent and parent.get("Type") not in LIBRARY_TYPES and parent.get("Name"):
        video["series_id"], video["series_name"] = parent["Id"], parent["Name"]
    elif parent and parent.get("Name"):
        video["series_id"], video["series_name"] = parent["Id"], parent["Name"]
    return video


def tech_of(session: dict, item: dict) -> dict:
    """How the item is being played: direct or transcoded, resolution, chosen audio and subtitle language."""
    ps = session.get("PlayState") or {}
    ti = session.get("TranscodingInfo") or {}
    streams = item.get("MediaStreams") or []
    video = next((m for m in streams if m.get("Type") == "Video"), {})

    def stream_lang(kind: str, index) -> Optional[str]:
        if index is None or index < 0:
            return None
        s = next((m for m in streams if m.get("Type") == kind and m.get("Index") == index), None)
        return (s.get("Language") or "und") if s else None

    reasons = ti.get("TranscodeReasons") or []
    if isinstance(reasons, str):
        reasons = [r for r in reasons.split(",") if r]
    method = ps.get("PlayMethod")
    if ti and not ti.get("IsVideoDirect", True) and method != "Transcode":
        method = "Transcode"
    return {
        "play_method": method,
        "video_codec": video.get("Codec"),
        "height": video.get("Height") or item.get("Height"),
        "audio_lang": stream_lang("Audio", ps.get("AudioStreamIndex")),
        "subtitle_lang": stream_lang("Subtitle", ps.get("SubtitleStreamIndex")),
        "transcode_reasons": reasons,
    }
