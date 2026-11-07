"""Local copies of posters, thumbnails and portraits, so they survive the item being deleted from Jellyfin.

Files live next to the database (images/<item_id>.<ext>) and are therefore part of Home Assistant backups.
A copy older than REFRESH is fetched again when Jellyfin is reachable, to pick up changed artwork; if that
fails the old copy is kept.
"""
import logging
import time
from pathlib import Path
from typing import Iterable, Optional

from config import DB_DIR

log = logging.getLogger("images")

DIR = DB_DIR / "images"
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
MEDIA_TYPE = {ext: mime for mime, ext in EXT.items()}
REFRESH = 30 * 86400
MISS_RETRY = 86400  # items without artwork aren't asked for again for a day

_misses: dict = {}


def cached(item_id: str) -> Optional[Path]:
    for ext in MEDIA_TYPE:
        p = DIR / f"{item_id}{ext}"
        if p.exists():
            return p
    return None


async def get(client, item_id: str) -> Optional[Path]:
    """The local file for an item's primary image, downloading it first when needed and possible."""
    path = cached(item_id)
    fresh = path and time.time() - path.stat().st_mtime < REFRESH
    recently_missing = item_id in _misses and time.time() - _misses[item_id] < MISS_RETRY
    if fresh or client is None or recently_missing:
        return path
    try:
        r = await client.image(item_id)
    except Exception as e:  # Jellyfin down: whatever we have is better than nothing
        log.debug("image %s: %s", item_id, e)
        return path
    if not r:
        _misses[item_id] = time.time()
        return path
    ext = EXT.get(r.headers.get("content-type", "").split(";")[0].strip(), ".jpg")
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / f"{item_id}.tmp"
    tmp.write_bytes(r.content)
    if path and path.suffix != ext:
        path.unlink(missing_ok=True)
    target = DIR / f"{item_id}{ext}"
    tmp.replace(target)
    return target


async def prefetch(client, ids: Iterable[Optional[str]]) -> None:
    """Save artwork as soon as something is played, before anyone has opened the dashboard."""
    for item_id in dict.fromkeys(i for i in ids if i and i.isalnum()):
        try:
            await get(client, item_id)
        except Exception as e:
            log.warning("could not cache image %s: %s", item_id, e)
