import time
from collections import defaultdict
from flask import session
from utils.logger import get_logger

logger = get_logger("cache")

_data_cache = {}
_global_cache_version = 1
_center_cache_versions = defaultdict(lambda: 1)

DEFAULT_CACHE_TTL = 90


def get_current_version(center_id=None):
    if center_id:
        return _center_cache_versions[str(center_id)]
    return _global_cache_version


def get_cached(key: str, center_id=None):
    entry = _data_cache.get(key)
    if not entry:
        return None

    now = time.time()
    if now > entry.get("expires_at", 0):
        _data_cache.pop(key, None)
        return None

    expected_ver = get_current_version(center_id)
    if entry.get("version", 0) != expected_ver:
        _data_cache.pop(key, None)
        return None

    if session and "db_cache_version" in session:
        if entry.get("session_version", 0) < session.get("db_cache_version", 0):
            _data_cache.pop(key, None)
            return None

    return entry.get("data")


def set_cached(key: str, data, center_id=None, ttl: int = DEFAULT_CACHE_TTL):
    ver = get_current_version(center_id)
    sess_ver = session.get("db_cache_version", 0) if session else 0
    _data_cache[key] = {
        "data": data,
        "version": ver,
        "session_version": sess_ver,
        "expires_at": time.time() + ttl,
    }
    if len(_data_cache) > 500:
        _prune_cache()


def invalidate_cache(center_id=None, user_id=None):
    global _global_cache_version
    _global_cache_version += 1
    if center_id:
        _center_cache_versions[str(center_id)] += 1

    try:
        from utils.auth_helpers import invalidate_user_cache
        invalidate_user_cache(user_id)
    except Exception:
        pass

    if session:
        session["db_cache_version"] = time.time()

    logger.debug("Cache invalidated (center_id=%s, global_version=%s)", center_id, _global_cache_version)


def _prune_cache():
    now = time.time()
    expired = [k for k, v in _data_cache.items() if now > v.get("expires_at", 0)]
    for k in expired:
        _data_cache.pop(k, None)


def get_cached_reference(key: str, fetch_fn, ttl: int = 180):
    cached = get_cached(f"ref:{key}")
    if cached is not None:
        return cached
    data = fetch_fn()
    set_cached(f"ref:{key}", data, ttl=ttl)
    return data
