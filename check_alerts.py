#!/usr/bin/env python3
"""
FloodGuard AI — daily alert checker (standalone, NO streamlit dependency).

Run by GitHub Actions (see .github/workflows/alerts.yml) or manually:
    python check_alerts.py [--threshold 60] [--dry-run]

For every subscriber in alerts_subscribers.csv it recomputes flood risk with
the SAME 2026 national model pipeline as the app (7 features), and sends a
WhatsApp (CallMeBot) and/or Email (SMTP) alert when probability >= threshold.

Secrets come ONLY from environment variables (GitHub Actions secrets):
    CALLMEBOT_APIKEY   — CallMeBot WhatsApp API key
    ALERT_SMTP_HOST    — default smtp.gmail.com
    ALERT_SMTP_PORT    — default 587
    ALERT_SMTP_USER    — Gmail address
    ALERT_SMTP_PASS    — Gmail APP password (not your login password!)
    ALERT_SMTP_FROM    — optional From header
    ALERT_THRESHOLD    — default 60
    FLOODGUARD_DIR     — base dir override (default: this script's dir)

Anti-spam: a contact is not re-alerted within 48h unless the new
probability is at least 10 points higher than the last alerted value.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("FLOODGUARD_DIR", _HERE)

MODEL_PATH = os.path.join(BASE, "floodguard_model_2026.joblib")
META_PATH = os.path.join(BASE, "model_meta.json")
MASTER_CSV = os.path.join(BASE, "pakistan_master.csv")
MONSOON_CACHE = os.path.join(BASE, ".alerts_monsoon_cache.json")

sys.path.insert(0, _HERE)
import alerts  # noqa: E402  (pure module, no streamlit)

_UA = {"User-Agent": "FloodGuardAI/1.0 (alert checker)"}

# Approximate river waypoint traces (same documented approximation as app.py).
RIVERS = {
    "Indus": [(35.30, 75.60), (34.95, 73.60), (34.60, 72.90), (34.10, 72.70),
              (33.90, 72.25), (33.50, 71.90), (32.60, 71.55), (31.83, 70.95),
              (31.20, 70.80), (30.71, 70.65), (30.00, 70.60), (29.30, 70.50),
              (28.40, 69.70), (27.71, 68.86), (27.00, 68.60), (26.30, 68.30),
              (25.40, 68.40), (24.75, 67.93), (24.10, 67.50)],
    "Jhelum": [(34.35, 73.47), (33.80, 73.60), (33.13, 73.64), (32.93, 73.73),
               (32.50, 73.30), (32.30, 72.35), (31.70, 72.20), (31.17, 72.15)],
    "Chenab": [(32.50, 74.50), (32.57, 74.08), (32.20, 73.80), (31.72, 72.98),
               (31.27, 72.33), (30.70, 71.90), (30.16, 71.52), (29.60, 71.30),
               (29.25, 71.05)],
    "Ravi": [(32.10, 74.90), (31.90, 74.50), (31.55, 74.35), (31.20, 73.90),
             (30.90, 73.20), (30.70, 72.60), (30.60, 72.15)],
    "Sutlej": [(31.10, 74.40), (30.70, 74.00), (30.30, 73.60), (29.99, 73.25),
              (29.60, 72.70), (29.35, 71.50), (29.30, 71.05)],
    "Kabul": [(34.10, 71.10), (34.05, 71.40), (34.00, 71.55), (34.01, 71.80),
              (34.01, 71.98), (33.95, 72.10), (33.90, 72.25)],
}


def river_dist_km(lat, lon):
    best = float("inf")
    la1, lo1 = math.radians(float(lat)), math.radians(float(lon))
    for pts in RIVERS.values():
        for rla, rlo in pts:
            dp = math.radians(rla) - la1
            dl = math.radians(rlo) - lo1
            a = (math.sin(dp / 2) ** 2 + math.cos(la1)
                 * math.cos(math.radians(rla)) * math.sin(dl / 2) ** 2)
            best = min(best, 2 * 6371.0 * math.asin(math.sqrt(min(a, 1.0))))
    return best


def get_elevation(lat, lon):
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": round(float(lat), 4),
                                 "longitude": round(float(lon), 4)},
                         headers=_UA, timeout=15)
        r.raise_for_status()
        elev = (r.json().get("elevation") or [None])[0]
        return float(elev) if elev is not None else None
    except Exception:
        return None


def _load_monsoon_cache():
    try:
        with open(MONSOON_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_monsoon_cache(cache):
    try:
        with open(MONSOON_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def get_monsoon(lat, lon, cache):
    """(mean, trend) Jul-Sep precipitation 1991->2026-10-02, ERA5 archive."""
    key = f"{round(float(lat), 2)},{round(float(lon), 2)}"
    if key in cache:
        return tuple(cache[key])
    for attempt in range(3):
        try:
            r = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={"latitude": round(float(lat), 2),
                        "longitude": round(float(lon), 2),
                        "start_date": "1991-01-01", "end_date": "2026-10-02",
                        "daily": "precipitation_sum", "timezone": "auto"},
                headers=_UA, timeout=90)
            r.raise_for_status()
            d = r.json()
            loc = d[0] if isinstance(d, list) else d
            times = loc.get("daily", {}).get("time", [])
            prec = loc.get("daily", {}).get("precipitation_sum", [])
            yearly = {}
            for t, x in zip(times, prec):
                if len(t) >= 7 and t[5:7] in ("07", "08", "09") and x is not None:
                    yearly[t[:4]] = yearly.get(t[:4], 0.0) + float(x)
            yrs = sorted(yearly)
            if len(yrs) < 10:
                return None
            vals = [yearly[y] for y in yrs]
            mean = float(np.mean(vals))
            xs = np.arange(len(yrs), dtype=float)
            slope = float((len(xs) * np.dot(xs, vals) - xs.sum() * np.sum(vals))
                          / (len(xs) * np.dot(xs, xs) - xs.sum() ** 2))
            cache[key] = [mean, slope]
            _save_monsoon_cache(cache)
            return mean, slope
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def nearest_village(master, lat, lon):
    latf = np.cos(np.radians(float(lat)))
    dlat = master["latitude"].to_numpy() - float(lat)
    dlon = master["longitude"].to_numpy() - float(lon)
    dist_deg = np.sqrt(dlat ** 2 + (dlon * latf) ** 2)
    idx = int(np.argmin(dist_deg))
    row = master.iloc[idx]
    return row, float(dist_deg[idx] * 111.32)


def predict(lat, lon, model, meta, master, monsoon_cache):
    meds = meta.get("medians", {})
    row, _dist = nearest_village(master, lat, lon)
    dem = row["dem_m"]
    if pd.isna(dem):
        dem = get_elevation(float(row["latitude"]), float(row["longitude"]))
    if dem is None or pd.isna(dem):
        dem = meds.get("elevation_m", 199.0)
    pop = (row["population"] if pd.notna(row["population"])
           else meds.get("population", 4591.0))
    mon = get_monsoon(float(row["latitude"]), float(row["longitude"]),
                      monsoon_cache)
    if mon is None:
        mon = (meds.get("monsoon_mean_mm", 291.7),
               meds.get("monsoon_trend_mm_yr", 0.15))
    X = pd.DataFrame([{
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "elevation_m": float(dem),
        "population": float(pop),
        "river_dist_km": float(river_dist_km(float(row["latitude"]),
                                             float(row["longitude"]))),
        "monsoon_mean_mm": float(mon[0]),
        "monsoon_trend_mm_yr": float(mon[1]),
    }])
    return round(float(model.predict_proba(X)[0, 1]) * 100, 2)


def should_alert(sub, prob, cooldown_h=48, min_rise=10.0):
    """Anti-spam: skip if alerted within cooldown_h and prob hasn't risen."""
    try:
        last_at = sub.get("last_alert_at") or ""
        last_prob = float(sub.get("last_alert_prob") or 0)
        if last_at:
            dt = (datetime.now(timezone.utc)
                  - datetime.fromisoformat(last_at))
            if dt.total_seconds() < cooldown_h * 3600 \
                    and prob < last_prob + min_rise:
                return False
    except Exception:
        pass
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("ALERT_THRESHOLD", 60)))
    ap.add_argument("--dry-run", action="store_true",
                    help="compute risks but send nothing")
    args = ap.parse_args()

    print(f"[check_alerts] threshold={args.threshold} dry_run={args.dry_run}",
          flush=True)
    if not os.path.exists(MODEL_PATH):
        print(f"[check_alerts] FATAL: model not found: {MODEL_PATH}")
        return 2
    model = joblib.load(MODEL_PATH)
    with open(META_PATH, encoding="utf-8") as f:
        meta = json.load(f)
    master = pd.read_csv(MASTER_CSV)
    for c in ["population", "dem_m"]:
        if c in master.columns:
            master[c] = pd.to_numeric(master[c], errors="coerce")
    print(f"[check_alerts] model + master loaded ({len(master)} villages)",
          flush=True)

    cfg = alerts.get_contacts_cfg()
    subs = alerts.load_subscribers()
    print(f"[check_alerts] {len(subs)} subscriber(s)", flush=True)
    monsoon_cache = _load_monsoon_cache()

    sent, skipped, failed = 0, 0, 0
    for s in subs:
        try:
            lat, lon = float(s["lat"]), float(s["lon"])
        except (TypeError, ValueError):
            print(f"  skip {s.get('contact')}: bad coords")
            skipped += 1
            continue
        try:
            prob = predict(lat, lon, model, meta, master, monsoon_cache)
        except Exception as e:
            print(f"  ERROR {s.get('contact')}: predict failed: {e}")
            failed += 1
            continue
        print(f"  {s.get('contact')} -> {prob}% (village={s.get('village')})",
              flush=True)
        if prob < args.threshold or not should_alert(s, prob):
            skipped += 1
            continue
        if args.dry_run:
            print("    dry-run: would alert")
            continue
        msg = alerts.format_alert_message(s.get("village") or "your area",
                                          prob, s.get("lang") or "en")
        ok_any = False
        if s.get("contact_type") == "whatsapp":
            ok, detail = alerts.send_whatsapp_callmebot(
                s["contact"], msg, cfg["callmebot_apikey"])
            print(f"    whatsapp: {'OK' if ok else 'FAIL'} {detail}")
            alerts.log_alert(s["contact"], "whatsapp", prob,
                             "sent" if ok else f"fail: {detail}")
            ok_any = ok_any or ok
        elif s.get("contact_type") == "email":
            ok, detail = alerts.send_email_smtp(
                s["contact"], "🌊 FloodGuard Flood Alert", msg, cfg)
            print(f"    email: {'OK' if ok else 'FAIL'} {detail}")
            alerts.log_alert(s["contact"], "email", prob,
                             "sent" if ok else f"fail: {detail}")
            ok_any = ok_any or ok
        if ok_any:
            alerts.mark_alert_sent(s["contact"], prob)
            sent += 1
        else:
            failed += 1
    print(f"[check_alerts] done: sent={sent} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
