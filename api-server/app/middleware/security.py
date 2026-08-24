"""
Security Middleware — suspicious access detection + IP geolocation logging.

Detects:
  - Failed login attempts (POST /api/auth/login → 401)
  - Common vulnerability scans (/.env, /wp-admin, /phpmyadmin, /etc/passwd, etc.)
  - Repeated requests from the same IP within a short window
  - Invalid / malformed JWT token attempts

Logs to: /app/storage/logs/security.log (one JSON line per event)

Each log line:
  {
    "timestamp": "2026-04-29T05:13:00Z",
    "event": "failed_login" | "path_scan" | "auth_abuse" | "rate_limit",
    "ip": "1.2.3.4",
    "method": "POST",
    "path": "/api/auth/login",
    "status": 401,
    "user_agent": "...",
    "geo": {
      "country": "China",
      "country_code": "CN",
      "region": "Guangdong",
      "city": "Shenzhen",
      "lat": 22.5333,
      "lon": 114.1333,
      "isp": "..."
    }
  }
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("ptm-security")

# ── Configuration ─────────────────────────────────────────────────────────────

SECURITY_LOG_PATH = Path("/app/storage/logs/security.log")
SECURITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Rate-limit window: more than RATE_LIMIT_COUNT requests in RATE_LIMIT_WINDOW seconds
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_COUNT = 300   # SPA polling + page loads; login has a separate lockout

# Health, SSE, and status polls are exempt so a live order page is not 429'd.
_RATE_EXEMPT = re.compile(
    r"^/api/(health(/|$)|version$|events/)|/api/orders/\d+/status$"
)

# Failed-login threshold: 5 failures in 5 minutes → log as brute-force
LOGIN_FAIL_WINDOW  = 300  # seconds
LOGIN_FAIL_THRESH  = 5

# Known attack path patterns
ATTACK_PATHS = re.compile(
    r"(\.env|\.git|wp-admin|wp-login|phpmyadmin|/admin(?!/)|"
    r"etc/passwd|/shell|/cmd|/eval|/config\.php|/xmlrpc|"
    r"actuator|/console|\.aws|\.ssh|/manager/html|/solr|"
    r"/cgi-bin|autodiscover|/owa/|/telescope|laravel|"
    r"setup\.cgi|/boaform|/GponForm)",
    re.I,
)

# Private / loopback IPs — skip geolocation for these
_PRIVATE_IP = re.compile(
    r"^(127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|::1$|localhost)"
)

# ── In-memory state ───────────────────────────────────────────────────────────

# ip → deque of request timestamps (for rate limiting)
_request_times: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=200))
# ip → deque of failed login timestamps
_login_fails: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=20))
# ip → cached geo result
_geo_cache: dict[str, dict] = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _real_ip(request: Request) -> str:
    """Extract real client IP (handles X-Forwarded-For from nginx)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _geolocate(ip: str) -> dict:
    """Call ip-api.com to get geolocation info. Results are cached per IP."""
    if ip in _geo_cache:
        return _geo_cache[ip]
    if _PRIVATE_IP.match(ip):
        result = {"country": "Private/Local", "country_code": "LO", "city": "", "region": "", "lat": 0, "lon": 0, "isp": ""}
        _geo_cache[ip] = result
        return result
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={
                    "fields": "status,country,countryCode,regionName,city,lat,lon,isp,org",
                    "lang": "ko",   # 한국어 지명 반환 (서울, 부산, 대전 등)
                },
            )
            data = r.json()
            if data.get("status") == "success":
                city   = data.get("city", "")
                region = data.get("regionName", "")
                result = {
                    "country":      data.get("country", ""),
                    "country_code": data.get("countryCode", ""),
                    "region":       region,
                    "city":         city,
                    # 시/도 + 시/군/구 조합 표시용
                    "location":     f"{region} {city}".strip() if region != city else city,
                    "lat":          data.get("lat", 0),
                    "lon":          data.get("lon", 0),
                    "isp":          data.get("isp") or data.get("org", ""),
                }
                _geo_cache[ip] = result
                return result
    except Exception:
        pass
    fallback = {"country": "Unknown", "country_code": "??", "region": "", "city": "", "lat": 0, "lon": 0, "isp": ""}
    _geo_cache[ip] = fallback
    return fallback


def _write_log(entry: dict) -> None:
    """Append one JSON line to the security log file."""
    try:
        with open(SECURITY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Security log write failed: {e}")


async def _log_event(event: str, ip: str, request: Request, status: int) -> None:
    geo = await _geolocate(ip)
    entry = {
        "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event":      event,
        "ip":         ip,
        "method":     request.method,
        "path":       request.url.path,
        "status":     status,
        "user_agent": request.headers.get("user-agent", ""),
        "geo":        geo,
    }
    _write_log(entry)
    location = geo.get("location") or geo.get("city") or geo.get("country") or "?"
    flag = "🚨" if event in ("brute_force", "path_scan") else "⚠️"
    logger.warning(
        f"{flag} [{event}] {ip} ({geo.get('country','?')} / {location}) "
        f"{request.method} {request.url.path} → {status}"
    )

# ── Middleware ─────────────────────────────────────────────────────────────────

class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        ip   = _real_ip(request)
        path = request.url.path
        now  = time.time()

        is_login = (request.method == "POST" and "/auth/login" in path)

        # Login lockout: too many recent failures → reject before hitting the handler
        if is_login:
            fails = _login_fails[ip]
            while fails and fails[0] < now - LOGIN_FAIL_WINDOW:
                fails.popleft()
            if len(fails) >= LOGIN_FAIL_THRESH:
                asyncio.create_task(_log_event("brute_force", ip, request, 429))
                return JSONResponse(
                    {"detail": "Too many failed login attempts. Try again later."},
                    status_code=429,
                )

        # ── 1. Rate limiting ──────────────────────────────────────────────────
        if not _RATE_EXEMPT.search(path):
            times = _request_times[ip]
            times.append(now)
            while times and times[0] < now - RATE_LIMIT_WINDOW:
                times.popleft()
            if len(times) > RATE_LIMIT_COUNT:
                asyncio.create_task(_log_event("rate_limit", ip, request, 429))
                return JSONResponse(
                    {"detail": "Too many requests"},
                    status_code=429,
                )

        # ── 2. Attack path scan ───────────────────────────────────────────────
        if ATTACK_PATHS.search(path):
            # Let the request through (returns 404) but log it
            response = await call_next(request)
            asyncio.create_task(_log_event("path_scan", ip, request, response.status_code))
            return response

        # ── 3. Execute the actual request ─────────────────────────────────────
        response = await call_next(request)

        # ── 4. Failed login detection ─────────────────────────────────────────
        is_login = (request.method == "POST" and "/auth/login" in path)
        if is_login and response.status_code == 401:
            fails = _login_fails[ip]
            fails.append(now)
            while fails and fails[0] < now - LOGIN_FAIL_WINDOW:
                fails.popleft()
            event = "brute_force" if len(fails) >= LOGIN_FAIL_THRESH else "failed_login"
            asyncio.create_task(_log_event(event, ip, request, 401))

        # ── 5. Auth token abuse (401/403 on non-login endpoints) ──────────────
        elif response.status_code in (401, 403) and not is_login:
            asyncio.create_task(_log_event("auth_abuse", ip, request, response.status_code))

        return response
