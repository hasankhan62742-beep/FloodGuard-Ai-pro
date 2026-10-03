"""geocode.py — free reverse geocoding via OpenStreetMap Nominatim (no key).

reverse_geocode(lat, lon) -> dict with status 'ok' and:
    village, district, province, display_name, lat, lon
On any failure: {'status': 'unavailable'}. Never raises.

Usage policy respected: single request per call, proper User-Agent,
1-second gap between calls. Callers should cache per coordinate.
"""

import time

import requests

_NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_UA = {"User-Agent": "FloodGuardAI/1.0 (flood-risk app; contact: admin)"}
_last_call = 0.0


def _throttle():
    global _last_call
    gap = time.time() - _last_call
    if gap < 1.1:
        time.sleep(1.1 - gap)
    _last_call = time.time()


def reverse_geocode(lat, lon, lang="en"):
    """ lat/lon -> nearest named place (village/mouza/dihat level when OSM knows it). """
    try:
        _throttle()
        r = requests.get(
            _NOMINATIM,
            params={"lat": float(lat), "lon": float(lon), "format": "jsonv2",
                    "zoom": 14, "addressdetails": 1,
                    "accept-language": lang},
            headers=_UA, timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        addr = d.get("address", {}) if isinstance(d, dict) else {}
        village = (addr.get("village") or addr.get("hamlet")
                   or addr.get("isolated_dwelling") or addr.get("suburb")
                   or addr.get("neighbourhood") or addr.get("town")
                   or addr.get("city_district") or addr.get("city")
                   or addr.get("county") or "")
        district = (addr.get("county") or addr.get("state_district")
                    or addr.get("city") or "")
        # avoid repeating the same name as village
        if district and village and district.lower() == village.lower():
            district = addr.get("state_district") or ""
        province = addr.get("state") or ""
        if not village:
            return {"status": "unavailable", "reason": "no named place found"}
        return {"status": "ok", "village": village, "district": district,
                "province": province,
                "display_name": d.get("display_name", ""),
                "lat": float(lat), "lon": float(lon)}
    except Exception as e:  # never break the app
        return {"status": "unavailable", "reason": str(e)[:100]}


def describe_place(place):
    """Human-friendly one-liner: 'Village, District' (skips blanks)."""
    if not place or place.get("status") != "ok":
        return ""
    parts = [place.get("village", ""), place.get("district", "")]
    return ", ".join(p for p in parts if p)
