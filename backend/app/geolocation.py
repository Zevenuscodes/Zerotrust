"""Best-effort IP geolocation. Uses a free, no-API-key lookup service and
degrades gracefully (returns None) if offline, rate-limited, or the IP is
private/loopback (e.g. local dev) — the risk engine treats "unknown" as
neutral rather than failing the request."""

import ipaddress
from typing import Optional, Tuple

import requests

from app.config import settings

_TIMEOUT_SECONDS = 1.5


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        return False


def lookup(ip: str) -> Optional[Tuple[float, float, str, str]]:
    """Returns (lat, lon, city, country) or None."""
    if not settings.geolocation_enabled or not is_public_ip(ip):
        return None
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=_TIMEOUT_SECONDS)
        data = resp.json()
        if data.get("status") != "success":
            return None
        return data["lat"], data["lon"], data.get("city", ""), data.get("country", "")
    except Exception:
        return None
