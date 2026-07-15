"""Tiny on-disk JSON cache for API responses.

Scholarly metadata barely changes, so caching every successful API response
means: (1) re-opening a paper you've already explored is instant, and (2) we
almost never re-hit the rate-limited anonymous API. This is what makes the
no-key setup comfortable for everyday personal use.

Cache lives in backend/.cache/*.json. Delete that folder to clear it.
"""
import hashlib
import json
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# Kept in sync with config.DATA_DIR so both land in the same place.
_DIR = os.path.join(os.environ.get("LITGRAPH_DATA_DIR") or _HERE, ".cache")
TTL_SECONDS = 30 * 24 * 3600  # 30 days; metadata is effectively static


def _path(key: str) -> str:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return os.path.join(_DIR, h + ".json")


def get(key: str):
    p = _path(key)
    try:
        with open(p, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    if time.time() - blob.get("_ts", 0) > TTL_SECONDS:
        return None
    return blob.get("data")


def set(key: str, data) -> None:
    os.makedirs(_DIR, exist_ok=True)
    tmp = _path(key) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "data": data}, f)
        os.replace(tmp, _path(key))
    except OSError:
        pass  # cache is best-effort; never fail the request over it
