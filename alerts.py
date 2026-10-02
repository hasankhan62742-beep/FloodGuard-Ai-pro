"""
FloodGuard AI — Flood Alert subscriptions (WhatsApp + Email).

Pure helper module (no Streamlit dependency). The Streamlit app imports
`subscribe_alert` / `load_subscribers` for the signup form; the standalone
`check_alerts.py` script (run by GitHub Actions) re-checks every subscriber
and sends WhatsApp/Email alerts when risk >= threshold.

Secrets are NEVER hardcoded: they come from a passed `secrets` mapping
(Streamlit: st.secrets) or environment variables. Missing secrets ->
functions return an explicit "not configured" status; nothing crashes.

Subscriber storage: local CSV `alerts_subscribers.csv` next to this file.
NOTE for production: on Streamlit Community Cloud the local filesystem is
ephemeral (wiped on reboot/redeploy). For a durable subscriber list, migrate
to Google Sheets or Supabase — see ALERTS_SETUP.md "Going production".
"""

import csv
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
SUBSCRIBERS_CSV = os.path.join(_HERE, "alerts_subscribers.csv")
ALERT_LOG_CSV = os.path.join(_HERE, "alerts_log.csv")

_CSV_FIELDS = ["name", "contact", "contact_type", "lat", "lon",
               "village", "lang", "subscribed_at", "last_alert_at",
               "last_alert_prob"]

_DEFAULT_TIMEOUT = 20
_UA = {"User-Agent": "FloodGuardAI/1.0 (flood alerts)"}


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

def get_contacts_cfg(secrets=None):
    """Collect alert-sending credentials from `secrets` mapping or env vars.

    Returns dict with keys: callmebot_apikey, smtp_host, smtp_port,
    smtp_user, smtp_pass, smtp_from. Missing values are None.
    """
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

    return {
        "callmebot_apikey": pick("CALLMEBOT_APIKEY", "callmebot_apikey"),
        "smtp_host": pick("ALERT_SMTP_HOST", "smtp_host") or "smtp.gmail.com",
        "smtp_port": int(pick("ALERT_SMTP_PORT", "smtp_port") or 587),
        "smtp_user": pick("ALERT_SMTP_USER", "smtp_user"),
        "smtp_pass": pick("ALERT_SMTP_PASS", "smtp_pass"),
        "smtp_from": pick("ALERT_SMTP_FROM", "smtp_from"),
    }


# ---------------------------------------------------------------------------
# Subscriptions (CSV)
# ---------------------------------------------------------------------------

def _ensure_csv(path, fields):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _detect_contact_type(contact):
    contact = (contact or "").strip()
    if "@" in contact and "." in contact.split("@")[-1]:
        return "email"
    digits = re.sub(r"\D", "", contact)
    if len(digits) >= 10:
        return "whatsapp"
    return "unknown"


def subscribe_alert(name, contact, lat, lon, village="", lang="en"):
    """Add/update a subscriber. Returns (ok: bool, message: str)."""
    name = (name or "").strip()
    contact = (contact or "").strip()
    ctype = _detect_contact_type(contact)
    if not name:
        return False, "Name is required."
    if ctype == "unknown":
        return False, "Enter a valid WhatsApp number (with country code) or email address."
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False, "Invalid coordinates."

    _ensure_csv(SUBSCRIBERS_CSV, _CSV_FIELDS)
    rows = load_subscribers()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated = False
    for r in rows:
        if r["contact"].strip().lower() == contact.lower():
            r.update({"name": name, "lat": lat_f, "lon": lon_f,
                      "village": village, "lang": lang})
            updated = True
    if not updated:
        rows.append({"name": name, "contact": contact, "contact_type": ctype,
                     "lat": lat_f, "lon": lon_f, "village": village,
                     "lang": lang, "subscribed_at": now,
                     "last_alert_at": "", "last_alert_prob": ""})
    with open(SUBSCRIBERS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return True, ("Subscription updated." if updated
                  else "Subscribed! You will be alerted when flood risk is high.")


def load_subscribers():
    _ensure_csv(SUBSCRIBERS_CSV, _CSV_FIELDS)
    with open(SUBSCRIBERS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def unsubscribe(contact):
    rows = [r for r in load_subscribers()
            if r["contact"].strip().lower() != (contact or "").strip().lower()]
    with open(SUBSCRIBERS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return True


def mark_alert_sent(contact, prob):
    rows = load_subscribers()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        if r["contact"].strip().lower() == (contact or "").strip().lower():
            r["last_alert_at"] = now
            r["last_alert_prob"] = prob
    with open(SUBSCRIBERS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def log_alert(contact, channel, prob, status):
    _ensure_csv(ALERT_LOG_CSV, ["time_utc", "contact", "channel", "prob", "status"])
    with open(ALERT_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=["time_utc", "contact", "channel",
                                      "prob", "status"]).writerow({
            "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "contact": contact, "channel": channel, "prob": prob, "status": status})


# ---------------------------------------------------------------------------
# Message formatting (bilingual)
# ---------------------------------------------------------------------------

def format_alert_message(village, prob, lang="en"):
    if lang == "ur":
        return (
            f"🌊 فلڈ گارڈ الرٹ\n"
            f"مقام: {village}\n"
            f"سیلاب کا خطرہ: {prob}% (زیادہ)\n"
            f"براہ کرم احتیاط کریں، قیمتی سامان محفوظ جگہ منتقل کریں اور PDMA/NDMA کی ہدایات پر عمل کریں۔\n"
            f"ایمرجنسی: PDMA 1129 | Rescue 1122"
        )
    return (
        f"🌊 FloodGuard ALERT\n"
        f"Location: {village}\n"
        f"Flood risk: {prob}% (HIGH)\n"
        f"Please take precautions — move valuables to safety and follow PDMA/NDMA advisories.\n"
        f"Emergency: PDMA 1129 | Rescue 1122"
    )


# ---------------------------------------------------------------------------
# Sending — WhatsApp via CallMeBot (free tier)
# ---------------------------------------------------------------------------

def send_whatsapp_callmebot(phone, message, apikey):
    """Send a WhatsApp message via CallMeBot's free API.

    Returns (ok, detail). NEVER raises. The recipient must first send
    "I allow callmebot to send me messages" to +34 644 71 56 43 (one-time
    opt-in — see ALERTS_SETUP.md).
    """
    if not apikey:
        return False, "CALLMEBOT_APIKEY not configured"
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return False, "invalid phone number"
    try:
        r = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": digits, "text": message, "apikey": apikey},
            headers=_UA, timeout=_DEFAULT_TIMEOUT)
        txt = r.text or ""
        # CallMeBot returns 200 with an error message body on failure.
        if r.status_code == 200 and ("ERROR" not in txt.upper()[:200]):
            return True, txt[:200]
        return False, f"HTTP {r.status_code}: {txt[:200]}"
    except Exception as e:  # network etc.
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Sending — Email via SMTP (Gmail app password)
# ---------------------------------------------------------------------------

def send_email_smtp(to_email, subject, body, cfg):
    """Send email via SMTP. cfg from get_contacts_cfg(). Returns (ok, detail)."""
    if not cfg.get("smtp_user") or not cfg.get("smtp_pass"):
        return False, "SMTP credentials not configured"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.get("smtp_from") or cfg["smtp_user"]
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"],
                           timeout=_DEFAULT_TIMEOUT) as s:
            s.starttls()
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
