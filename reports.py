"""
FloodGuard AI — Community flood reporting via Telegram (FREE).

Design:
- The app posts each user report to a Telegram channel/group via the Bot API.
- Messages use a compact machine-readable encoding:
      FLOODREPORT|<lat>|<lon>|<village>|<severity>|<reporter>|<note>
  so `fetch_reports()` can parse them back reliably for the map overlay.
- Severity: low | moderate | severe  (map colours green / orange / red)

Secrets (NEVER hardcoded): passed as a `secrets` mapping (Streamlit:
st.secrets) or environment variables:
    TELEGRAM_BOT_TOKEN — from BotFather
    TELEGRAM_CHAT_ID   — channel/group chat id (bot must be admin/member)

No Streamlit dependency in this module. The integrator wires the form UI
and folium markers (see reports_to_markers).
"""

import os
import re
import time
from datetime import datetime, timezone

import requests

_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 20
_UA = {"User-Agent": "FloodGuardAI/1.0 (community reports)"}

SEVERITIES = ("low", "moderate", "severe")
_SEV_COLOR = {"low": "green", "moderate": "orange", "severe": "red"}
_SEV_EMOJI = {"low": "🟢", "moderate": "🟠", "severe": "🔴"}

_PREFIX = "FLOODREPORT"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def get_telegram_creds(secrets=None):
    """Returns (token, chat_id) or (None, None) when not configured."""
    secrets = secrets or {}

    def pick(*names):
        for n in names:
            if n in secrets and secrets[n]:
                return secrets[n]
        for n in names:
            v = os.environ.get(n)
            if v:
                return v
        return None

    return (pick("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
            pick("TELEGRAM_CHAT_ID", "telegram_chat_id"))


def is_configured(secrets=None):
    token, chat_id = get_telegram_creds(secrets)
    return bool(token and chat_id)


# ---------------------------------------------------------------------------
# Encoding / parsing
# ---------------------------------------------------------------------------

def _clean(s, maxlen=120):
    s = re.sub(r"[|\n\r]", " ", str(s or "")).strip()
    return s[:maxlen]


def encode_report(lat, lon, village, severity, reporter, note=""):
    severity = (severity or "low").lower()
    if severity not in SEVERITIES:
        severity = "low"
    return "|".join([
        _PREFIX,
        f"{float(lat):.4f}",
        f"{float(lon):.4f}",
        _clean(village, 60),
        severity,
        _clean(reporter, 40),
        _clean(note, 120),
    ])


def parse_report(text):
    """Parse an encoded report message. Returns dict or None."""
    if not text or not text.strip().startswith(_PREFIX + "|"):
        return None
    parts = text.strip().split("|")
    if len(parts) < 7:
        return None
    try:
        lat, lon = float(parts[1]), float(parts[2])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    sev = parts[4].lower() if parts[4].lower() in SEVERITIES else "low"
    return {"lat": lat, "lon": lon, "village": parts[3],
            "severity": sev, "reporter": parts[5], "note": parts[6],
            "time": "", "message_id": None}


# ---------------------------------------------------------------------------
# Bot API
# ---------------------------------------------------------------------------

def _call(token, method, params=None, timeout=_TIMEOUT):
    r = requests.get(_API.format(token=token, method=method),
                     params=params or {}, headers=_UA, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        return False, f"HTTP {r.status_code}: non-JSON response"
    if r.status_code == 200 and data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", f"HTTP {r.status_code}")


def send_report(lat, lon, village, reporter, severity, note="", secrets=None):
    """Post a community report to the Telegram channel.

    Returns (ok: bool, detail: str). NEVER raises.
    """
    token, chat_id = get_telegram_creds(secrets)
    if not token or not chat_id:
        return False, ("Telegram not configured — set TELEGRAM_BOT_TOKEN and "
                       "TELEGRAM_CHAT_ID (see TELEGRAM_SETUP.md)")
    body = encode_report(lat, lon, village, severity, reporter, note)
    sev = (severity or "low").lower()
    human = (f"{_SEV_EMOJI.get(sev, '🟢')} <b>Flood report — {sev.upper()}</b>\n"
             f"📍 {village} ({lat:.4f}, {lon:.4f})\n"
             f"👤 {reporter}\n"
             f"📝 {note or '—'}\n\n<code>{body}</code>")
    ok, detail = _call(token, "sendMessage",
                       {"chat_id": chat_id, "text": human,
                        "parse_mode": "HTML"})
    if not ok:
        return False, f"Telegram error: {detail}"
    return True, "Report posted ✅"


def fetch_reports(limit=50, secrets=None):
    """Fetch recent community reports via getUpdates.

    Returns (reports: list[dict], status: str). Each report has
    lat/lon/village/severity/reporter/note/time. NEVER raises; on failure
    returns ([], "unavailable: ...").

    NOTE: getUpdates only sees messages the bot can read. For a channel, add
    the bot as ADMIN; for a group, add it as member (or admin). Long-polling
    is not used — we take the most recent `limit` updates each call.
    """
    token, chat_id = get_telegram_creds(secrets)
    if not token or not chat_id:
        return [], "not configured"
    ok, result = _call(token, "getUpdates",
                       {"limit": 100, "timeout": 0,
                        "allowed_updates": ["channel_post", "message"]})
    if not ok:
        return [], f"unavailable: {result}"
    out = []
    for upd in result or []:
        msg = upd.get("channel_post") or upd.get("message") or {}
        text = msg.get("text") or ""
        parsed = parse_report(text)
        if not parsed:
            continue
        ts = msg.get("date")
        if ts:
            try:
                parsed["time"] = datetime.fromtimestamp(
                    ts, tz=timezone.utc).strftime("%d %b %Y, %H:%M UTC")
            except Exception:
                pass
        parsed["message_id"] = msg.get("message_id")
        out.append(parsed)
    # newest first, cap
    out = out[-limit:][::-1]
    return out, "ok"


# ---------------------------------------------------------------------------
# Map overlay hook (for the app integrator)
# ---------------------------------------------------------------------------

def reports_to_markers(reports):
    """Convert parsed reports to folium-marker specs for the integrator.

    Returns list of dicts: {lat, lon, color, popup_html}. The integrator
    builds actual folium.Marker objects (keeps folium import in app.py).
    """
    markers = []
    for r in reports:
        sev = r.get("severity", "low")
        popup = (f"<b>{_SEV_EMOJI.get(sev, '')} Community flood report</b><br>"
                 f"{r.get('village', '')} — {sev}<br>"
                 f"Reporter: {r.get('reporter', 'anonymous')}<br>"
                 f"{r.get('note', '')}<br>"
                 f"<i>{r.get('time', '')}</i>")
        markers.append({"lat": r["lat"], "lon": r["lon"],
                        "color": _SEV_COLOR.get(sev, "green"),
                        "popup_html": popup})
    return markers


def severity_options():
    return list(SEVERITIES)
