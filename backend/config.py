"""Persistent config, admin auth, and sessions for LitGraph.

Stores settings in backend/config.json:
  - admin password (PBKDF2-hashed, salted)
  - Semantic Scholar API key
  - app settings (default mode)

Sessions are in-memory (cleared on restart — admin just logs in again). This is
a local, single-operator tool, but we still hash passwords properly and use
random session tokens.
"""
import hashlib
import json
import os
import secrets
import threading
import time

# Single source of truth for the version: the User-Agent we send, /api/config, the
# docs page and the generated PDF all read this, so they can never disagree.
VERSION = "2.0"
RELEASED = "2026-07-15"

HERE = os.path.dirname(os.path.abspath(__file__))
# Where to persist config.json + the response cache. Defaults to this folder; set
# LITGRAPH_DATA_DIR to keep the admin password, API key and cache somewhere else.
DATA_DIR = os.environ.get("LITGRAPH_DATA_DIR") or HERE
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
CACHE_DIR = os.path.join(DATA_DIR, ".cache")

SESSION_TTL = 8 * 3600
_sessions: dict[str, float] = {}          # token -> expiry epoch
_lock = threading.Lock()
_cfg_cache: dict | None = None

# Runtime usage counters (since server start).
STATS = {"api_calls": 0, "cache_hits": 0}


# ---- config file --------------------------------------------------------------
def load() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cfg_cache = json.load(f)
        except (FileNotFoundError, ValueError):
            _cfg_cache = {}
    return _cfg_cache


def save(cfg: dict) -> None:
    global _cfg_cache
    _cfg_cache = cfg
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ---- password / auth ----------------------------------------------------------
def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                               200_000).hex()


def is_password_set() -> bool:
    return bool(load().get("password_hash"))


def set_password(password: str) -> None:
    cfg = load()
    salt = secrets.token_hex(16)
    cfg["salt"] = salt
    cfg["password_hash"] = _hash(password, salt)
    save(cfg)


def verify_password(password: str) -> bool:
    cfg = load()
    if not cfg.get("password_hash"):
        return False
    return secrets.compare_digest(_hash(password, cfg["salt"]), cfg["password_hash"])


def create_session() -> str:
    token = secrets.token_urlsafe(24)
    with _lock:
        _sessions[token] = time.time() + SESSION_TTL
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        exp = _sessions.get(token)
        if not exp:
            return False
        if exp < time.time():
            _sessions.pop(token, None)
            return False
        return True


def destroy_session(token: str | None) -> None:
    if token:
        with _lock:
            _sessions.pop(token, None)


# ---- api key & settings -------------------------------------------------------
def get_api_key() -> str | None:
    return load().get("s2_api_key") or os.environ.get("S2_API_KEY") or None


def set_api_key(key: str | None) -> None:
    cfg = load()
    if key:
        cfg["s2_api_key"] = key.strip()
    else:
        cfg.pop("s2_api_key", None)
    save(cfg)


def get_settings() -> dict:
    s = load().get("settings") or {}
    return {"default_mode": s.get("default_mode", "deep")}


def set_settings(default_mode: str | None = None) -> None:
    cfg = load()
    s = cfg.get("settings") or {}
    if default_mode in ("quick", "deep", "complex"):
        s["default_mode"] = default_mode
    cfg["settings"] = s
    save(cfg)


# ---- stats --------------------------------------------------------------------
def cache_stats() -> dict:
    count, size = 0, 0
    try:
        for fn in os.listdir(CACHE_DIR):
            if fn.endswith(".json"):
                count += 1
                size += os.path.getsize(os.path.join(CACHE_DIR, fn))
    except FileNotFoundError:
        pass
    return {"count": count, "bytes": size}


def clear_cache() -> int:
    removed = 0
    try:
        for fn in os.listdir(CACHE_DIR):
            if fn.endswith(".json"):
                try:
                    os.remove(os.path.join(CACHE_DIR, fn))
                    removed += 1
                except OSError:
                    pass
    except FileNotFoundError:
        pass
    return removed
