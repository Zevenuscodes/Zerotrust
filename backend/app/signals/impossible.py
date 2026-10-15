"""Conditions that are not merely unusual but physically impossible.

These are binary rather than statistical, which is what makes them
valuable: no baseline, no training data, no threshold tuning. Either the
same session was used from two networks at once or it wasn't.
"""

import math
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from app.geolocation import is_public_ip
from app.models import KnownContext, SessionNetwork

EARTH_RADIUS_KM = 6371.0
IMPOSSIBLE_TRAVEL_KMH = 900.0   # faster than a commercial airliner
MIN_TRAVEL_DISTANCE_KM = 100.0  # ignore GPS/IP jitter over short distances

# Two different networks inside this window means two places at once, not a
# person moving between them.
CONCURRENT_NETWORK_WINDOW = timedelta(minutes=5)

# A browser's clock should track the server's. Large drift suggests a
# tampered or replayed client.
MAX_CLOCK_SKEW_MS = 120_000

# The clock says one timezone, the IP says another: a standard VPN/proxy
# tell. Not damning on its own -- plenty of legitimate VPN use -- so it is
# weighted as a mild signal.
TZ_MISMATCH_TOLERANCE_MIN = 180


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def evaluate(
    db,
    user_id: str,
    session_id: str,
    ip: str,
    geo: Optional[Tuple[float, float, str, str]],
    environment: dict,
    server_now: datetime,
) -> Tuple[float, List[str], List[dict]]:
    score = 100.0
    reasons: List[str] = []
    checks: List[dict] = []

    # --- same session, two networks, same moment ---------------------------
    recent = (
        db.query(SessionNetwork)
        .filter(
            SessionNetwork.session_id == session_id,
            SessionNetwork.seen_at >= server_now - CONCURRENT_NETWORK_WINDOW,
        )
        .all()
    )
    others = {r.ip_address for r in recent if r.ip_address and r.ip_address != ip}
    if not is_public_ip(ip):
        others = set()  # current address identifies no network either
    if others:
        score -= 60.0
        detail = (f"Session used from {len(others) + 1} networks within "
                  f"{int(CONCURRENT_NETWORK_WINDOW.total_seconds() / 60)} minutes "
                  f"({ip} and {', '.join(sorted(others))})")
        reasons.append(detail)
        checks.append({"name": "Concurrent networks", "score": 40.0, "detail": detail})
    else:
        checks.append({"name": "Concurrent networks", "score": 100.0,
                       "detail": "Single network for this session"})

    # --- impossible travel -------------------------------------------------
    if geo is None:
        checks.append({"name": "Travel plausibility", "score": 100.0,
                       "detail": "No geolocation available"})
    else:
        lat, lon, _city, _country = geo
        last = (
            db.query(KnownContext)
            .filter(KnownContext.user_id == user_id, KnownContext.geo_lat.isnot(None))
            .order_by(KnownContext.last_seen.desc())
            .first()
        )
        if last is None or last.geo_lat is None:
            checks.append({"name": "Travel plausibility", "score": 100.0,
                           "detail": "No prior location on record"})
        else:
            distance = _haversine_km(last.geo_lat, last.geo_lon, lat, lon)
            hours = max((server_now - last.last_seen).total_seconds() / 3600.0, 0.01)
            speed = distance / hours
            if speed > IMPOSSIBLE_TRAVEL_KMH and distance > MIN_TRAVEL_DISTANCE_KM:
                score -= 55.0
                detail = (f"Impossible travel: {distance:.0f}km in {hours:.1f}h "
                          f"(~{speed:.0f} km/h) since {last.geo_city}, {last.geo_country}")
                reasons.append(detail)
                checks.append({"name": "Travel plausibility", "score": 45.0, "detail": detail})
            else:
                checks.append({"name": "Travel plausibility", "score": 100.0,
                               "detail": f"{distance:.0f}km since last seen -- plausible"})

    # --- client clock skew -------------------------------------------------
    client_ms = environment.get("client_time_ms")
    if client_ms:
        skew = abs(client_ms - server_now.timestamp() * 1000)
        if skew > MAX_CLOCK_SKEW_MS:
            score -= 25.0
            detail = f"Client clock is {skew / 1000:.0f}s from server time"
            reasons.append(detail)
            checks.append({"name": "Clock agreement", "score": 75.0, "detail": detail})
        else:
            checks.append({"name": "Clock agreement", "score": 100.0,
                           "detail": f"Within {skew / 1000:.1f}s of server"})

    # --- timezone vs network location -------------------------------------
    offset = environment.get("timezone_offset_min")
    if geo is not None and offset is not None:
        lon = geo[1]
        # ~15 degrees of longitude per hour is a rough but adequate estimate
        # of the timezone the network location implies.
        implied_min = (lon / 15.0) * 60.0
        delta = abs(implied_min - offset)
        if delta > TZ_MISMATCH_TOLERANCE_MIN:
            score -= 20.0
            detail = (f"Browser timezone is {offset:+.0f}min but the network location "
                      f"implies ~{implied_min:+.0f}min (possible VPN or proxy)")
            reasons.append(detail)
            checks.append({"name": "Timezone vs network", "score": 80.0, "detail": detail})
        else:
            checks.append({"name": "Timezone vs network", "score": 100.0,
                           "detail": "Browser timezone agrees with network location"})

    return max(0.0, score), reasons, checks


def record_network(db, session_id: str, ip: str, seen_at: datetime) -> None:
    """Only public addresses are recorded. A loopback or RFC1918 address
    identifies no network -- in local development every session starts from
    one, and treating that as 'a different network' made the very first
    heartbeat look like concurrent use from two places."""
    if not is_public_ip(ip):
        return
    db.add(SessionNetwork(session_id=session_id, ip_address=ip, seen_at=seen_at))
