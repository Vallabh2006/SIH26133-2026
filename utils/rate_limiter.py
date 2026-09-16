import time
from collections import defaultdict
from flask import request, jsonify, redirect, flash
from utils.security import get_client_ip
from utils.logger import get_logger

logger = get_logger("rate_limiter")

RATE_LIMIT_WINDOW = 30
RATE_LIMIT_MAX_REQUESTS = 15

_request_history = defaultdict(list)
_last_cleanup = 0


def is_rate_limited(key: str, max_requests: int = RATE_LIMIT_MAX_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW):
    global _last_cleanup
    now = time.time()

    if now - _last_cleanup > 60:
        _cleanup_expired(now, window_seconds)
        _last_cleanup = now

    timestamps = _request_history[key]
    cutoff = now - window_seconds
    _request_history[key] = [t for t in timestamps if t > cutoff]
    timestamps = _request_history[key]

    if len(timestamps) >= max_requests:
        oldest = timestamps[0]
        retry_after = max(1, int(window_seconds - (now - oldest)) + 1)
        return True, retry_after, 0

    timestamps.append(now)
    remaining = max_requests - len(timestamps)
    return False, 0, remaining


def _cleanup_expired(now: float, window_seconds: int):
    cutoff = now - (window_seconds * 2)
    keys_to_delete = []
    for k, times in _request_history.items():
        valid = [t for t in times if t > cutoff]
        if valid:
            _request_history[k] = valid
        else:
            keys_to_delete.append(k)
    for k in keys_to_delete:
        _request_history.pop(k, None)


def check_custom_rate_limit():
    path = request.path or "/"

    if (
        path.startswith("/static/")
        or path.startswith("/public/")
        or path in ("/favicon.ico", "/service-worker.js", "/manifest.json", "/api/health")
    ):
        return None

    client_ip = get_client_ip()
    key = f"{client_ip}:{request.method}:{path}"

    limited, retry_after, remaining = is_rate_limited(key)
    if not limited:
        return None

    logger.warning("Custom rate limit exceeded for %s on %s (retry_after=%ss)", client_ip, path, retry_after)

    is_ajax = (
        path.startswith("/api/")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
        or request.headers.get("Sec-Fetch-Mode") == "cors"
    )

    if is_ajax:
        resp = jsonify({
            "status": "error",
            "rate_limited": True,
            "error": "Rate limit exceeded",
            "message": f"Rate limit reached: Maximum 15 requests per 30 seconds. Please wait {retry_after}s.",
            "retry_after": retry_after,
            "limit": RATE_LIMIT_MAX_REQUESTS,
            "window": RATE_LIMIT_WINDOW
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        resp.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_MAX_REQUESTS)
        resp.headers["X-RateLimit-Remaining"] = "0"
        resp.headers["X-RateLimit-Reset"] = str(retry_after)
        return resp

    flash(f"Rate limit reached: Maximum 15 requests per 30 seconds. Please wait {retry_after}s before trying again.", "warning")

    target = request.referrer or request.path
    if request.method == "GET" and (not request.referrer or request.referrer == request.url):
        from flask import render_template
        try:
            return render_template("errors/429.html", retry_after=retry_after), 429
        except Exception:
            pass

    resp = redirect(target)
    resp.headers["X-RateLimit-Exceeded"] = "1"
    resp.headers["X-RateLimit-Reset"] = str(retry_after)
    return resp
