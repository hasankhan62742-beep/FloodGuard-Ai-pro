"""
FloodGuard AI — Pro Edition
============================
GPS-based Flood Risk & Live Environmental Monitoring (pro rebuild).

DEPLOY: push this file + requirements.txt to GitHub, then deploy via
Streamlit Cloud (share.streamlit.io) with main file = app.py.

MODEL INTEGRATION
-----------------
Priority: 2026 national model -> user's 2022 model -> demo.
  - floodguard_model_2026.joblib (sklearn RandomForest, 400 trees, 7 features:
    latitude, longitude, elevation_m, population, river_dist_km,
    monsoon_mean_mm, monsoon_trend_mm_yr; trained on 79 historical Pakistan
    flood events 2006-2025; holdout accuracy 98.5%)
  - model_meta.json (feature medians, metrics)
  - pakistan_flood_history.csv (79 events for the Flood History section)
  - floodguard_final_static_model_2022.joblib (user's original, fallback)
  - floodguard_deployment_master.geojson      (user's village rows, stdlib json)
  - pakistan_master.csv  (AUTO fallback: 28,916 HOTOSM Pakistan settlements,
    built by build_master.py — no upload needed; dem_m fetched LIVE per
    query from Open-Meteo elevation API)
Advisory modules in advisory.py: SoilGrids soil fertility, bilingual crop
advisory, FFD/GloFAS river levels, NASA GIBS satellite view.
If no model file is present the app shows a banner and uses demo
probabilities (locations stay real when a master dataset is present).
"""

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import advisory  # soil, crop advice, river levels, satellite (no streamlit dep)

# ======================================================================
#  PAGE CONFIG
# ======================================================================
st.set_page_config(
    page_title="FloodGuard AI",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

PKT = timezone(timedelta(hours=5))

# ======================================================================
#  STRINGS — Urdu / English (all UI text lives here)
# ======================================================================
STRINGS = {
    "en": {
        "tagline": "GPS-based Flood Risk & Live Environmental Monitoring",
        "desc": ("The current ML prediction is based on the 2022 observed-flood model. "
                 "Live weather and air quality are shown as supplementary context only."),
        "demo_banner": "⚠️ Demo data — connect your trained model and 23,774-village dataset to go live.",
        "auto_banner": "ℹ️ Auto data active — {n} Pakistan settlements loaded, elevation fetched live per query. Predictions use your trained model.",
        "nomodel_banner": "⚠️ Trained model file not found — locations are real but probabilities are demo. Upload floodguard_final_static_model_2022.joblib for real predictions.",
        "language": "Language / زبان",
        "theme": "Theme",
        "theme_dark": "🌊 Ocean Dark",
        "theme_light": "☀️ Light",
        "location": "📍 Location",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "check": "🔎 Check FloodGuard Risk",
        "gps": "📍 Use my location",
        "gps_ok": "Location detected!",
        "gps_fail": "GPS not available in this environment — please enter coordinates manually.",
        "nearest_village": "Nearest Village",
        "village_id": "Village ID",
        "distance": "Distance",
        "coords": "Coordinates",
        "risk_model": "🌊 Flood Risk Model",
        "static_prob": "Static Flood Probability",
        "prediction": "Model Prediction",
        "low": "Low", "moderate": "Moderate", "high": "High",
        "no_flood": "No flood indication",
        "mod_risk": "Moderate flood risk",
        "high_risk": "High flood risk — take precautions",
        "weather": "🌤️ Live Weather",
        "temp": "Temperature", "humidity": "Humidity", "rain": "Rain",
        "wind": "Wind", "rain24": "Next 24h Rain", "rain24prob": "Next 24h Rain Prob.",
        "wind72": "72h Max Wind", "gust72": "72h Max Gust",
        "weather_note": ("Important: live weather and AQI are NOT inputs to the current ML model. "
                         "They are shown as live environmental information. The flood probability "
                         "comes from the static 2022 observed-flood Random Forest model."),
        "aqi": "🌫️ Live Air Quality",
        "us_aqi": "US AQI", "eu_aqi": "European AQI",
        "aqi_good": "Good", "aqi_moderate": "Moderate", "aqi_usg": "Unhealthy for Sensitive Groups",
        "aqi_unhealthy": "Unhealthy", "aqi_very": "Very Unhealthy", "aqi_hazard": "Hazardous",
        "history": "📜 Check History",
        "clear_history": "Clear history",
        "no_history": "No checks yet.",
        "compare": "📊 Compare Locations",
        "save_compare": "💾 Save for comparison",
        "compare_full": "You can save up to 3 locations.",
        "compare_empty": "Save at least 2 locations to compare.",
        "compare_saved": "Saved!",
        "emergency": "🆘 Emergency Information",
        "helplines": "Helplines (Pakistan)",
        "tips": "Safety Tips",
        "download": "📥 Download Report (PDF)",
        "disclaimer": "⚠️ Not for emergency use — always follow official PDMA / NDMA alerts.",
        "analysis_time": "Analysis generated",
        "footer": "FloodGuard AI | Production dataset: 23,774 villages | Static observed-flood model: 2022 | Live weather/AQI: Open-Meteo",
        "map_title": "🗺️ Risk Map",
        "flood_history": "📜 Flood History Near This Location",
        "no_nearby_events": "No recorded flood events within 25 km in our archive.",
        "model2026_active": "✅ 2026 national model active — trained on 79 historical Pakistan flood events (2006–2025).",
        "soil_title": "🧪 Soil Fertility",
        "soil_ph": "pH",
        "soil_texture": "Texture",
        "soil_soc": "Organic Carbon",
        "soil_fertility": "Fertility",
        "soil_unavailable": "Soil data unavailable right now.",
        "crop_title": "🌾 Crop Advisory",
        "river_title": "🌊 River Levels",
        "river_discharge": "River Discharge",
        "river_ffd_unavailable": "FFD bulletin unavailable — check ffd.pmd.gov.pk directly.",
        "sat_title": "🛰️ Satellite View",
        "sat_date": "Image date",
        "village": "Village",
        "probability": "Probability",
        "weather_fail": "Live weather unavailable right now.",
        "aqi_fail": "Air quality data unavailable right now.",
        "tips_list": [
            "Move to higher ground immediately if water starts rising.",
            "Never walk or drive through flood water.",
            "Turn off electricity and gas if authorities instruct.",
            "Keep important documents in a waterproof bag.",
            "Follow only official PDMA / NDMA alerts — ignore rumors.",
        ],
    },
    "ur": {
        "tagline": "جی پی ایس پر مبنی سیلاب کے خطرے کی پیش گوئی اور لائیو ماحولیاتی نگرانی",
        "desc": ("موجودہ ایم ایل پیش گوئی 2022 کے مشاہدہ شدہ سیلاب ماڈل پر مبنی ہے۔ "
                 "لائیو موسم اور ہوا کا معیار صرف اضافی معلومات کے طور پر دکھایا جاتا ہے۔"),
        "demo_banner": "⚠️ ڈیمو ڈیٹا — لائیو کرنے کے لیے اپنا تربیت یافتہ ماڈل اور 23,774 دیہات کا ڈیٹا سیٹ منسلک کریں۔",
        "auto_banner": "ℹ️ خودکار ڈیٹا فعال — {n} پاکستانی بستیاں لوڈ ہو گئیں، بلندی ہر سوال پر لائیو حاصل کی جاتی ہے۔ پیش گوئیاں آپ کے تربیت یافتہ ماڈل سے ہوں گی۔",
        "nomodel_banner": "⚠️ تربیت یافتہ ماڈل فائل نہیں ملی — مقامات اصل ہیں لیکن امکانات ڈیمو ہیں۔ اصل پیش گوئیوں کے لیے floodguard_final_static_model_2022.joblib اپ لوڈ کریں۔",
        "language": "زبان / Language",
        "theme": "تھیم",
        "theme_dark": "🌊 گہرا سمندری",
        "theme_light": "☀️ روشن",
        "location": "📍 مقام",
        "latitude": "عرض بلد",
        "longitude": "طول بلد",
        "check": "🔎 فلڈ گارڈ رسک چیک کریں",
        "gps": "📍 میری لوکیشن استعمال کریں",
        "gps_ok": "لوکیشن مل گئی!",
        "gps_fail": "اس ماحول میں GPS دستیاب نہیں — براہ کرم کوآرڈینیٹس خود درج کریں۔",
        "nearest_village": "قریبی گاؤں",
        "village_id": "گاؤں کا نمبر",
        "distance": "فاصلہ",
        "coords": "کوآرڈینیٹس",
        "risk_model": "🌊 سیلاب کے خطرے کا ماڈل",
        "static_prob": "جامد سیلاب کا امکان",
        "prediction": "ماڈل کی پیش گوئی",
        "low": "کم", "moderate": "درمیانہ", "high": "زیادہ",
        "no_flood": "سیلاب کا کوئی اشارہ نہیں",
        "mod_risk": "درمیانے درجے کا سیلاب کا خطرہ",
        "high_risk": "شدید سیلاب کا خطرہ — احتیاط کریں",
        "weather": "🌤️ لائیو موسم",
        "temp": "درجہ حرارت", "humidity": "نمی", "rain": "بارش",
        "wind": "ہوا کی رفتار", "rain24": "اگلے 24 گھنٹے میں بارش",
        "rain24prob": "اگلے 24 گھنٹے میں بارش کا امکان",
        "wind72": "72 گھنٹے میں زیادہ سے زیادہ ہوا", "gust72": "72 گھنٹے میں زیادہ سے زیادہ جھونکا",
        "weather_note": ("اہم: لائیو موسم اور ہوا کا معیار موجودہ ایم ایل ماڈل کا ان پٹ نہیں ہیں۔ "
                         "یہ صرف لائیو ماحولیاتی معلومات ہیں۔ سیلاب کا امکان 2022 کے جامد "
                         "مشاہدہ شدہ سیلاب رینڈم فاریسٹ ماڈل سے حاصل ہوتا ہے۔"),
        "aqi": "🌫️ لائیو ہوا کا معیار",
        "us_aqi": "امریکی اے کیو آئی", "eu_aqi": "یورپی اے کیو آئی",
        "aqi_good": "اچھا", "aqi_moderate": "درمیانہ",
        "aqi_usg": "حساس افراد کے لیے نقصان دہ",
        "aqi_unhealthy": "نقصان دہ", "aqi_very": "بہت نقصان دہ", "aqi_hazard": "خطرناک",
        "history": "📜 چیک کی تاریخ",
        "clear_history": "تاریخ صاف کریں",
        "no_history": "ابھی کوئی چیک نہیں کیا گیا۔",
        "compare": "📊 مقامات کا موازنہ",
        "save_compare": "💾 موازنے کے لیے محفوظ کریں",
        "compare_full": "زیادہ سے زیادہ 3 مقامات محفوظ کیے جا سکتے ہیں۔",
        "compare_empty": "موازنے کے لیے کم از کم 2 مقامات محفوظ کریں۔",
        "compare_saved": "محفوظ ہو گیا!",
        "emergency": "🆘 ایمرجنسی معلومات",
        "helplines": "ہیلپ لائنز (پاکستان)",
        "tips": "حفاظتی تدابیر",
        "download": "📥 رپورٹ ڈاؤن لوڈ کریں (PDF)",
        "disclaimer": "⚠️ ایمرجنسی کے لیے استعمال نہ کریں — ہمیشہ پی ڈی ایم اے / این ڈی ایم اے کی سرکاری ہدایات پر عمل کریں۔",
        "analysis_time": "تجزیہ کا وقت",
        "footer": "فلڈ گارڈ اے آئی | ڈیٹا سیٹ: 23,774 دیہات | جامد مشاہدہ شدہ سیلاب ماڈل: 2022 | لائیو موسم/ہوا: Open-Meteo",
        "map_title": "🗺️ رسک کا نقشہ",
        "flood_history": "📜 اس مقام کے قریب ماضی کے سیلاب",
        "no_nearby_events": "ہمارے ریکارڈ میں 25 کلومیٹر کے اندر کوئی سیلاب درج نہیں۔",
        "model2026_active": "✅ 2026 قومی ماڈل فعال — پاکستان کے 79 تاریخی سیلاب واقعات (2006–2025) پر تربیت یافتہ۔",
        "soil_title": "🧪 زمین کی زرخیزی",
        "soil_ph": "پی ایچ",
        "soil_texture": "ساخت",
        "soil_soc": "نامیاتی کاربن",
        "soil_fertility": "زرخیزی",
        "soil_unavailable": "زمین کا ڈیٹا اس وقت دستیاب نہیں۔",
        "crop_title": "🌾 فصل کا مشورہ",
        "river_title": "🌊 دریاؤں کی صورتحال",
        "river_discharge": "دریائی بہاؤ",
        "river_ffd_unavailable": "ایف ایف ڈی بلیٹن دستیاب نہیں — ffd.pmd.gov.pk خود دیکھیں۔",
        "sat_title": "🛰️ سیٹلائٹ منظر",
        "sat_date": "تصویر کی تاریخ",
        "village": "گاؤں",
        "probability": "امکان",
        "weather_fail": "لائیو موسم اس وقت دستیاب نہیں۔",
        "aqi_fail": "ہوا کے معیار کا ڈیٹا اس وقت دستیاب نہیں۔",
        "tips_list": [
            "پانی بڑھنے لگے تو فوراً اونچی جگہ منتقل ہو جائیں۔",
            "سیلابی پانی میں پیدل یا گاڑی سے کبھی نہ گزریں۔",
            "حکام کی ہدایت پر بجلی اور گیس بند کر دیں۔",
            "اہم کاغذات واٹر پروف تھیلے میں رکھیں۔",
            "صرف پی ڈی ایم اے / این ڈی ایم اے کی سرکاری ہدایات پر عمل کریں — افواہوں پر کان نہ دھریں۔",
        ],
    },
}

# ======================================================================
#  THEME CSS
# ======================================================================
DARK_CSS = """
<style>
.stApp { background: linear-gradient(180deg, #06121f 0%, #0a2238 100%); color: #e8f1f8; }
.fg-header { background: linear-gradient(135deg, #0a3d62 0%, #0c5b8f 55%, #0891b2 100%);
    padding: 26px 30px; border-radius: 16px; color: #fff; margin-bottom: 16px;
    box-shadow: 0 8px 24px rgba(8,145,178,.25); }
.fg-header h1 { margin: 0; font-size: 2.1rem; letter-spacing: .5px; }
.fg-header p { margin: 8px 0 0 0; opacity: .92; font-size: 1rem; }
.fg-card { background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12);
    border-radius: 14px; padding: 18px 20px; margin-bottom: 14px; }
.fg-demo { background: rgba(255,193,7,.12); border: 1px solid rgba(255,193,7,.45); color: #ffd970;
    padding: 10px 16px; border-radius: 10px; margin-bottom: 14px; font-weight: 600; }
.fg-note { background: rgba(255,193,7,.10); border-left: 4px solid #ffc107; color: #ffe08a;
    padding: 10px 14px; border-radius: 6px; margin: 12px 0; }
.fg-footer { text-align: center; color: #8fa9bd; font-size: .82rem; margin-top: 26px;
    padding-top: 14px; border-top: 1px solid rgba(255,255,255,.1); }
[data-testid="stMetric"] { background: rgba(255,255,255,.045); border: 1px solid rgba(255,255,255,.1);
    border-radius: 12px; padding: 12px 14px; }
[data-testid="stMetricLabel"] { color: #9fc3d8; }
section[data-testid="stSidebar"] { background: #081827; }
</style>
"""

LIGHT_CSS = """
<style>
.stApp { background: #f4f8fb; color: #1c2b3a; }
.fg-header { background: linear-gradient(135deg, #0a3d62 0%, #0e6ea8 55%, #12a3c7 100%);
    padding: 26px 30px; border-radius: 16px; color: #fff; margin-bottom: 16px;
    box-shadow: 0 8px 24px rgba(10,61,98,.18); }
.fg-header h1 { margin: 0; font-size: 2.1rem; letter-spacing: .5px; }
.fg-header p { margin: 8px 0 0 0; opacity: .95; font-size: 1rem; }
.fg-card { background: #ffffff; border: 1px solid #dbe7f0; border-radius: 14px;
    padding: 18px 20px; margin-bottom: 14px; box-shadow: 0 2px 10px rgba(10,61,98,.06); }
.fg-demo { background: #fff8e1; border: 1px solid #ffe082; color: #7a5b00;
    padding: 10px 16px; border-radius: 10px; margin-bottom: 14px; font-weight: 600; }
.fg-note { background: #fff8e1; border-left: 4px solid #ffb300; color: #7a5b00;
    padding: 10px 14px; border-radius: 6px; margin: 12px 0; }
.fg-footer { text-align: center; color: #6b7f90; font-size: .82rem; margin-top: 26px;
    padding-top: 14px; border-top: 1px solid #dbe7f0; }
[data-testid="stMetric"] { background: #ffffff; border: 1px solid #dbe7f0;
    border-radius: 12px; padding: 12px 14px; box-shadow: 0 2px 8px rgba(10,61,98,.05); }
</style>
"""

# ======================================================================
#  MODEL INTEGRATION — REAL FloodGuard model + master dataset
# ======================================================================
# Real files (must sit next to app.py on deploy):
#   floodguard_final_static_model_2022.joblib   (sklearn RandomForest)
#   floodguard_deployment_master.geojson        (village rows)
# If either file is missing the app automatically falls back to DEMO mode.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(APP_DIR, "floodguard_final_static_model_2022.joblib")
MODEL2026_PATH = os.path.join(APP_DIR, "floodguard_model_2026.joblib")
META2026_PATH = os.path.join(APP_DIR, "model_meta.json")
HISTORY_PATH = os.path.join(APP_DIR, "pakistan_flood_history.csv")
MASTER_PATH = os.path.join(APP_DIR, "floodguard_deployment_master.geojson")
# Auto-built fallback: pakistan_master.csv (~29k HOTOSM Pakistan settlements).
# Generated by build_master.py — no user upload needed.
AUTO_MASTER_PATH = os.path.join(APP_DIR, "pakistan_master.csv")

DEMO_VILLAGES = [
    {"name": "Muzaffargarh",  "vid": "FG-DEMO-01", "lat": 30.07, "lon": 71.18},
    {"name": "Multan",        "vid": "FG-DEMO-02", "lat": 30.15, "lon": 71.52},
    {"name": "D.G. Khan",     "vid": "FG-DEMO-03", "lat": 30.05, "lon": 70.63},
    {"name": "Rajanpur",      "vid": "FG-DEMO-04", "lat": 29.10, "lon": 70.32},
    {"name": "Rahim Yar Khan","vid": "FG-DEMO-05", "lat": 28.42, "lon": 70.30},
    {"name": "Bahawalpur",    "vid": "FG-DEMO-06", "lat": 29.39, "lon": 71.68},
    {"name": "Lodhran",       "vid": "FG-DEMO-07", "lat": 29.54, "lon": 71.63},
    {"name": "Kot Addu",      "vid": "FG-DEMO-08", "lat": 30.47, "lon": 71.05},
]


def model_kind():
    """Which trained model file is deployed: '2026' | '2022' | None."""
    if os.path.exists(MODEL2026_PATH):
        return "2026"
    if os.path.exists(MODEL_PATH):
        return "2022"
    return None


@st.cache_resource
def load_model():
    """Load the trained RandomForest. Priority: 2026 national model ->
    user's 2022 model -> None (demo mode)."""
    kind = model_kind()
    if kind is None:
        return None
    try:
        return joblib.load(MODEL2026_PATH if kind == "2026" else MODEL_PATH)
    except Exception:
        return None


@st.cache_data
def load_model_meta():
    """model_meta.json for the 2026 model (medians, metrics). None if absent."""
    try:
        with open(META2026_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@st.cache_data
def load_master():
    """Village master dataset. Priority:
    1. user's floodguard_deployment_master.geojson (their 23,774 villages)
    2. pakistan_master.csv (auto-built from HOTOSM Pakistan, ~29k places)
    3. None -> 8-village demo fallback in find_nearest_village().
    """
    for loader in (_master_from_geojson, _master_from_auto_csv):
        try:
            df = loader()
            if df is not None:
                return df
        except Exception:
            continue
    return None


@st.cache_data
def master_source():
    """'user' | 'auto' | None — which master dataset load_master() resolved."""
    if load_master() is None:
        return None
    if os.path.exists(MASTER_PATH):
        return "user"
    return "auto"


def _finalise_master(df):
    """Shared cleanup + documented NaN approximations.

    population / area_km2: NaN -> column median. (Approximation: OSM only
    carries population for ~3% of places and has no area field at all; the
    median fill keeps model inputs finite. Noted here, not hidden.)
    dem_m: NaN -> median ONLY when a finite median exists (user geojson).
    The auto CSV ships dem_m empty on purpose — predict_probability()
    fetches elevation LIVE per query via get_elevation(), so it stays NaN.
    """
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    for c in ["population", "dem_m", "area_km2"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    for c in ["population", "area_km2"]:
        # notna().any() guard avoids "Mean of empty slice" warnings
        med = df[c].median() if df[c].notna().any() else float("nan")
        df[c] = df[c].fillna(med if pd.notna(med) else 0.0)
    dem_med = df["dem_m"].median() if df["dem_m"].notna().any() else float("nan")
    if pd.notna(dem_med):
        df["dem_m"] = df["dem_m"].fillna(dem_med)
    return df if len(df) else None


def _master_from_geojson():
    """User's own deployment master (parsed with stdlib json, no geopandas)."""
    with open(MASTER_PATH, "r", encoding="utf-8") as f:
        gj = json.load(f)
    rows = []
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        rows.append({
            "village": props.get("village"),
            "village_id": props.get("village_id"),
            # GeoJSON coordinate order is [longitude, latitude]
            "longitude": coords[0],
            "latitude": coords[1],
            "population": props.get("population"),
            "dem_m": props.get("dem_m"),
            "area_km2": props.get("area_km2"),
        })
    return _finalise_master(pd.DataFrame(rows))


def _master_from_auto_csv():
    """Auto-built Pakistan settlements CSV (see build_master.py)."""
    return _finalise_master(pd.read_csv(AUTO_MASTER_PATH))


def is_live():
    """True when the real model AND a master dataset are both available."""
    return load_model() is not None and load_master() is not None


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_nearest_village(lat, lon):
    """REAL logic — mirrors the owner's production app exactly:
    numpy nearest-neighbour on lat/lon with cos(lat) lon-scaling,
    distance_km = deg * 111.32. Falls back to the 8 demo villages
    when no master dataset (user geojson / auto CSV) is available.
    """
    master = load_master()
    if master is None:
        best, best_d = None, float("inf")
        for v in DEMO_VILLAGES:
            d = _haversine_km(lat, lon, v["lat"], v["lon"])
            if d < best_d:
                best, best_d = v, d
        return {"name": best["name"], "vid": best["vid"],
                "lat": best["lat"], "lon": best["lon"],
                "dist_km": best_d, "_row": None, "_demo": True}

    lat_factor = np.cos(np.radians(lat))
    dlat = master["latitude"].to_numpy() - lat
    dlon = master["longitude"].to_numpy() - lon
    distance_deg = np.sqrt(dlat ** 2 + (dlon * lat_factor) ** 2)
    idx = int(np.argmin(distance_deg))
    row = master.iloc[idx]
    distance_km = float(distance_deg[idx] * 111.32)
    village = row["village"] if "village" in row.index and pd.notna(row["village"]) else "Unknown"
    village_id = row["village_id"] if "village_id" in row.index and pd.notna(row["village_id"]) else "Unknown"
    return {"name": str(village), "vid": str(village_id),
            "lat": float(row["latitude"]), "lon": float(row["longitude"]),
            "dist_km": distance_km, "_row": row, "_demo": False}


@st.cache_data
def load_flood_history():
    """pakistan_flood_history.csv -> DataFrame, or None if missing."""
    try:
        return pd.read_csv(HISTORY_PATH)
    except Exception:
        return None


def nearby_events(lat, lon, radius_km=25.0):
    """Past flood events within radius_km of (lat, lon), oldest first."""
    hist = load_flood_history()
    if hist is None or len(hist) == 0:
        return []
    out = []
    for _, r in hist.iterrows():
        try:
            d = _haversine_km(lat, lon, float(r["latitude"]), float(r["longitude"]))
        except Exception:
            continue
        if d <= radius_km:
            out.append({"name": str(r["event_name"]), "year": int(r["year"]),
                        "dist_km": round(d, 1), "source": str(r["source"])})
    return sorted(out, key=lambda e: (e["year"], e["dist_km"]))


def predict_probability(lat, lon, model=None):
    """REAL logic: build the village feature row and run
    model.predict_proba(X)[0, 1].

    - 2026 national model: 7 features (lat, lon, elevation_m, population,
      river_dist_km, monsoon_mean_mm, monsoon_trend_mm_yr).
    - 2022 model (user's): 5 features — exactly like the production app.

    Demo fallback (model is None, or master missing): deterministic
    hash probability, stable per location.
    """
    if model is None:
        key = f"{round(lat, 4)},{round(lon, 4)}"
        h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
        return round((h % 7000) / 100, 2)  # 0.00 – 69.99
    if model_kind() == "2026":
        # National 2026 model: 7 features
        # [latitude, longitude, elevation_m, population,
        #  river_dist_km, monsoon_mean_mm, monsoon_trend_mm_yr]
        # (village coords; elevation/monsoon live; population median-filled — same as training)
        v = find_nearest_village(lat, lon)
        row = v.get("_row")
        if row is None:
            key = f"{round(lat, 4)},{round(lon, 4)}"
            h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
            return round((h % 7000) / 100, 2)
        meta = load_model_meta() or {}
        meds = meta.get("medians", {})
        dem = row["dem_m"]
        if pd.isna(dem):
            dem = get_elevation(float(v["lat"]), float(v["lon"]))  # live Open-Meteo
        if dem is None or pd.isna(dem):
            dem = meds.get("elevation_m", 199.0)
        pop = row["population"] if pd.notna(row["population"]) else meds.get("population", 4591.0)
        mon = get_monsoon(float(v["lat"]), float(v["lon"]))  # live archive API, cached
        if mon is None:
            mon = (meds.get("monsoon_mean_mm", 291.7), meds.get("monsoon_trend_mm_yr", 0.15))
        X = pd.DataFrame([{
            "latitude": float(v["lat"]),
            "longitude": float(v["lon"]),
            "elevation_m": float(dem),
            "population": float(pop),
            "river_dist_km": float(river_dist_km(float(v["lat"]), float(v["lon"]))),
            "monsoon_mean_mm": float(mon[0]),
            "monsoon_trend_mm_yr": float(mon[1]),
        }])
        return round(float(model.predict_proba(X)[0, 1]) * 100, 2)
    v = find_nearest_village(lat, lon)
    row = v.get("_row")
    if row is None:  # model present but master file missing
        key = f"{round(lat, 4)},{round(lon, 4)}"
        h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
        return round((h % 7000) / 100, 2)
    X = pd.DataFrame([{
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "population": float(row["population"]),
        "dem_m": float(_resolve_dem_m(row)),
        "area_km2": float(row["area_km2"]),
    }])
    return round(float(model.predict_proba(X)[0, 1]) * 100, 2)


def _resolve_dem_m(row):
    """Elevation for the model row.

    The auto Pakistan CSV ships dem_m empty -> fetch it LIVE per query from
    Open-Meteo (cached). Falls back to the row value, then 0.0 as a
    documented last resort.
    """
    dem = row["dem_m"]
    if pd.isna(dem):
        dem = get_elevation(float(row["latitude"]), float(row["longitude"]))
    if dem is None or (isinstance(dem, float) and pd.isna(dem)):
        dem = 0.0
    return dem


# ======================================================================
#  HELPERS
# ======================================================================
def risk_band(prob, T):
    if prob < 30:
        return T["low"], "#2ecc71"
    if prob < 60:
        return T["moderate"], "#f1c40f"
    return T["high"], "#e74c3c"


def prediction_text(prob, T):
    if prob < 30:
        return T["no_flood"]
    if prob < 60:
        return T["mod_risk"]
    return T["high_risk"]


def aqi_category(aqi, T):
    if aqi is None:
        return "–"
    if aqi <= 50:
        return T["aqi_good"]
    if aqi <= 100:
        return T["aqi_moderate"]
    if aqi <= 150:
        return T["aqi_usg"]
    if aqi <= 200:
        return T["aqi_unhealthy"]
    if aqi <= 300:
        return T["aqi_very"]
    return T["aqi_hazard"]


def now_pkt_str():
    return datetime.now(PKT).strftime("%d %b %Y, %H:%M PKT")


def fetch_weather(lat, lon):
    """Open-Meteo forecast API — no key needed."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
        "&hourly=precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m"
        "&forecast_days=3&timezone=auto"
    )
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    return r.json()


def fetch_aqi(lat, lon):
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}&current=us_aqi,european_aqi,pm2_5,pm10"
    )
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    return r.json()


def parse_weather(data):
    """Summarise current + next-24h + 72h extremes from Open-Meteo payload."""
    cur = data.get("current", {})
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    out = {
        "temp": cur.get("temperature_2m"),
        "humidity": cur.get("relative_humidity_2m"),
        "rain": cur.get("precipitation"),
        "wind": cur.get("wind_speed_10m"),
        "rain24": None, "rain24prob": None,
        "wind72": None, "gust72": None,
    }
    try:
        cur_t = cur.get("time", "")
        idx = 0
        for i, t in enumerate(times):
            if t <= cur_t:
                idx = i
        precip = hourly.get("precipitation", [])[idx:idx + 24]
        prob = hourly.get("precipitation_probability", [])[idx:idx + 24]
        wind = hourly.get("wind_speed_10m", [])[:72]
        gust = hourly.get("wind_gusts_10m", [])[:72]
        out["rain24"] = round(sum(x for x in precip if x is not None), 1)
        out["rain24prob"] = max((x for x in prob if x is not None), default=None)
        out["wind72"] = round(max((x for x in wind if x is not None), default=0), 1)
        out["gust72"] = round(max((x for x in gust if x is not None), default=0), 1)
    except Exception:
        pass
    return out


@st.cache_data
def get_elevation(lat, lon):
    """Live elevation in metres from Open-Meteo — no API key needed.

    The auto Pakistan CSV ships dem_m empty on purpose; predict_probability()
    calls this per query so the model gets a real elevation. Cached per
    coordinate (rounded) to avoid repeat API hits. Returns None on failure.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": round(float(lat), 4),
                    "longitude": round(float(lon), 4)},
            timeout=10,
        )
        r.raise_for_status()
        elev = (r.json().get("elevation") or [None])[0]
        return float(elev) if elev is not None else None
    except Exception:
        return None


# ---- Flood model v2: rivers + monsoon climatology ---------------------
# RIVERS: approximate waypoint polylines tracing each river through Pakistan.
# Documented approximation: distances are min-haversine to the nearest
# waypoint, not true point-to-polyline distance.
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
    """Min haversine distance (km) from (lat, lon) to any river waypoint."""
    best = float("inf")
    la1, lo1 = math.radians(float(lat)), math.radians(float(lon))
    for pts in RIVERS.values():
        for rla, rlo in pts:
            dp = math.radians(rla) - la1
            dl = math.radians(rlo) - lo1
            a = (math.sin(dp / 2) ** 2 + math.cos(la1)
                 * math.cos(math.radians(rla)) * math.sin(dl / 2) ** 2)
            d = 2 * 6371.0 * math.asin(math.sqrt(min(a, 1.0)))
            if d < best:
                best = d
    return best


@st.cache_data
def get_monsoon(lat, lon):
    """Monsoon climatology for one location: (mean Jul-Sep seasonal total mm,
    linear trend mm/yr) over 1991-01-01 -> 2026-10-02, Open-Meteo archive API
    (ERA5). Cached per coordinate. Returns None on failure (caller falls back
    to training medians). NOTE: the archive API rate-limits (~429) under burst
    load - retries with backoff are built in; cached results are never refetched.
    """
    import time
    for attempt in range(3):
        try:
            r = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={"latitude": round(float(lat), 2),
                        "longitude": round(float(lon), 2),
                        "start_date": "1991-01-01", "end_date": "2026-10-02",
                        "daily": "precipitation_sum", "timezone": "auto"},
                timeout=60,
            )
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
            return mean, slope
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)   # soil barely changes
def cached_soil(lat, lon):
    return advisory.get_soil(round(lat, 4), round(lon, 4))


@st.cache_data(ttl=3600, show_spinner=False)             # rivers change daily
def cached_rivers():
    return advisory.get_river_levels()


def try_gps():
    """Best-effort GPS: uses streamlit_geolocation if installed, else None.

    Never raises — the UI shows a graceful fallback message instead.
    """
    try:
        from streamlit_geolocation import streamlit_geolocation

        loc = streamlit_geolocation()
        if isinstance(loc, dict):
            lat = loc.get("latitude") or (loc.get("coords") or {}).get("latitude")
            lon = loc.get("longitude") or (loc.get("coords") or {}).get("longitude")
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    except Exception:
        pass
    return None, None


def risk_gauge(prob, T):
    """Plotly gauge 0–100 with green/yellow/red bands."""
    band_label = f"{T['static_prob']}"
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=prob,
            number={"suffix": "%", "font": {"size": 40}},
            title={"text": band_label, "font": {"size": 15}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": "#1f77b4", "thickness": 0.35},
                "steps": [
                    {"range": [0, 30], "color": "#2ecc71"},
                    {"range": [30, 60], "color": "#f1c40f"},
                    {"range": [60, 100], "color": "#e74c3c"},
                ],
                "threshold": {
                    "line": {"color": "#111", "width": 3},
                    "thickness": 0.8, "value": prob,
                },
            },
        )
    )
    fig.update_layout(height=300, margin=dict(l=25, r=25, t=45, b=15),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def build_map(lat, lon, village, prob, T):
    """Folium map: user marker + risk-coloured village circle."""
    import folium

    color = "green" if prob < 30 else ("orange" if prob < 60 else "red")
    m = folium.Map(location=[lat, lon], zoom_start=9, tiles="OpenStreetMap")
    folium.Marker(
        [lat, lon],
        popup=T["coords"],
        tooltip=T["location"],
        icon=folium.Icon(color="blue", icon="user", prefix="fa"),
    ).add_to(m)
    folium.CircleMarker(
        [village["lat"], village["lon"]],
        radius=14,
        color=color, fill=True, fill_color=color, fill_opacity=0.55,
        popup=f"{village['name']} — {prob}%",
        tooltip=f"{village['name']} ({prob}%)",
    ).add_to(m)
    folium.Circle(
        [village["lat"], village["lon"]], radius=15000,
        color=color, fill=True, fill_opacity=0.08, weight=1,
    ).add_to(m)
    return m


def build_pdf(result):
    """Small English PDF report via fpdf2 (Latin-safe text only)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "FloodGuard AI - Flood Risk Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Generated: {result['time']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    rows = [
        ("Nearest village", result["village"]),
        ("Village ID", result["vid"]),
        ("Distance", f"{result['dist_km']:.2f} km"),
        ("Coordinates", f"{result['lat']:.4f}, {result['lon']:.4f}"),
        ("Static flood probability", f"{result['prob']}%"),
        ("Risk band", result["band"]),
        ("Model prediction", result["prediction_en"]),
    ]
    for e in result.get("nearby_events", [])[:10]:
        rows.append(("Past flood", f"{e['name']} ({e['year']}) - {e['dist_km']} km"))
    w = result.get("weather") or {}
    rows += [
        ("Temperature", f"{w.get('temp')} C"),
        ("Humidity", f"{w.get('humidity')} %"),
        ("Rain (current)", f"{w.get('rain')} mm"),
        ("Wind", f"{w.get('wind')} km/h"),
        ("Next 24h rain", f"{w.get('rain24')} mm"),
    ]
    pdf.set_font("Helvetica", "B", 11)
    for k, v in rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(60, 8, str(k) + ":")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, str(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 6, "Disclaimer: not for emergency use. Always follow official PDMA / NDMA alerts. "
                         "Probability is a susceptibility estimate from a model trained on proximity to 79 "
                         "historical Pakistan flood events (2006-2025); live weather shown as context only.")
    return bytes(pdf.output())


# ======================================================================
#  SESSION STATE
# ======================================================================
for key, default in [("history", []), ("compare", []), ("result", None),
                     ("lang", "en"), ("theme", "dark"),
                     ("lat", 30.0726), ("lon", 71.1938)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ======================================================================
#  SIDEBAR
# ======================================================================
with st.sidebar:
    lang_choice = st.radio(
        STRINGS[st.session_state["lang"]]["language"],
        options=["en", "ur"],
        format_func=lambda x: "English" if x == "en" else "اردو",
        index=0 if st.session_state["lang"] == "en" else 1,
        key="lang_radio",
    )
    if lang_choice != st.session_state["lang"]:
        st.session_state["lang"] = lang_choice
        st.rerun()

    T = STRINGS[st.session_state["lang"]]

    theme_choice = st.radio(
        T["theme"],
        options=["dark", "light"],
        format_func=lambda x: T["theme_dark"] if x == "dark" else T["theme_light"],
        index=0 if st.session_state["theme"] == "dark" else 1,
        key="theme_radio",
    )
    st.session_state["theme"] = theme_choice

    st.markdown("---")
    st.subheader(T["history"])
    if st.session_state["history"]:
        for h in reversed(st.session_state["history"][-8:]):
            st.caption(f"{h['village']} — {h['prob']}% · {h['time']}")
        if st.button(T["clear_history"]):
            st.session_state["history"] = []
            st.rerun()
    else:
        st.caption(T["no_history"])

st.markdown(DARK_CSS if st.session_state["theme"] == "dark" else LIGHT_CSS,
            unsafe_allow_html=True)

# ======================================================================
#  HEADER
# ======================================================================
st.markdown(
    f"""<div class="fg-header">
    <h1>🌊 FloodGuard AI</h1>
    <p>{T['tagline']}</p>
    <p style="font-size:.85rem;opacity:.8">{T['desc']}</p>
    </div>""",
    unsafe_allow_html=True,
)
# Banner states:
#  - model + user's own geojson  -> fully live, no banner
#  - model + auto Pakistan CSV   -> info banner (auto data active)
#  - no model (any master)       -> warning banner (demo probabilities)
#  - nothing at all              -> original demo banner
_model_now = load_model()
_src_now = master_source()
if _model_now is None and _src_now is None:
    st.markdown(f'<div class="fg-demo">{T["demo_banner"]}</div>', unsafe_allow_html=True)
elif _model_now is None:
    st.markdown(f'<div class="fg-demo">{T["nomodel_banner"]}</div>', unsafe_allow_html=True)
elif _src_now == "auto":
    _n = f"{len(load_master()):,}"
    st.markdown(f'<div class="fg-demo">{T["auto_banner"].format(n=_n)}</div>',
                unsafe_allow_html=True)
if model_kind() == "2026":
    st.markdown(f'<div class="fg-note">{T["model2026_active"]}</div>', unsafe_allow_html=True)

# ======================================================================
#  LOCATION INPUT
# ======================================================================
st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["location"]}</h3>',
            unsafe_allow_html=True)
c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    lat = st.number_input(T["latitude"], value=float(st.session_state["lat"]),
                          format="%.4f", step=0.0001, key="lat_in")
with c2:
    lon = st.number_input(T["longitude"], value=float(st.session_state["lon"]),
                          format="%.4f", step=0.0001, key="lon_in")
with c3:
    st.write("")
    st.write("")
    if st.button(T["gps"], key="gps_btn"):
        glat, glon = try_gps()
        if glat is not None:
            st.session_state["lat"], st.session_state["lon"] = round(glat, 4), round(glon, 4)
            st.success(T["gps_ok"])
            st.rerun()
        else:
            st.warning(T["gps_fail"])
st.session_state["lat"], st.session_state["lon"] = lat, lon

check = st.button(T["check"], type="primary", use_container_width=True,
                  key="check_btn")
st.markdown("</div>", unsafe_allow_html=True)

# ======================================================================
#  RUN CHECK
# ======================================================================
if check:
    model = load_model()  # real model, or None -> demo fallback
    village = find_nearest_village(lat, lon)
    prob = predict_probability(lat, lon, model)
    band, _ = risk_band(prob, T)
    result = {
        "lat": lat, "lon": lon,
        "village": village["name"], "vid": village["vid"],
        "vlat": village["lat"], "vlon": village["lon"],
        "dist_km": village["dist_km"],
        "prob": prob, "band": band,
        "prediction": prediction_text(prob, T),
        "prediction_en": prediction_text(prob, STRINGS["en"]),
        "time": now_pkt_str(),
        "nearby_events": nearby_events(lat, lon),
    }
    try:
        wraw = fetch_weather(lat, lon)
        result["weather"] = parse_weather(wraw)
    except Exception:
        result["weather"] = None
    try:
        araw = fetch_aqi(lat, lon).get("current", {})
        result["aqi"] = {
            "us": araw.get("us_aqi"), "eu": araw.get("european_aqi"),
            "pm25": araw.get("pm2_5"), "pm10": araw.get("pm10"),
        }
    except Exception:
        result["aqi"] = None
    st.session_state["result"] = result
    st.session_state["history"].append(
        {"village": result["village"], "lat": lat, "lon": lon,
         "prob": prob, "time": result["time"]})
    st.rerun()

result = st.session_state["result"]

# ======================================================================
#  RESULTS
# ======================================================================
if result:
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["risk_model"]}</h3>',
                unsafe_allow_html=True)
    i1, i2, i3, i4 = st.columns(4)
    i1.metric(T["nearest_village"], result["village"])
    i2.metric(T["village_id"], result["vid"])
    i3.metric(T["distance"], f"{result['dist_km']:.2f} km")
    i4.metric(T["coords"], f"{result['lat']:.4f}, {result['lon']:.4f}")

    g1, g2 = st.columns([1, 1.2])
    with g1:
        st.plotly_chart(risk_gauge(result["prob"], T), use_container_width=True)
        band, color = risk_band(result["prob"], T)
        st.markdown(
            f"<h4 style='text-align:center;color:{color}'>{band} — {result['prediction']}</h4>",
            unsafe_allow_html=True)
    with g2:
        st.subheader(T["map_title"])
        try:
            from streamlit_folium import st_folium

            fmap = build_map(result["lat"], result["lon"],
                             {"name": result["village"], "lat": result["vlat"],
                              "lon": result["vlon"]}, result["prob"], T)
            st_folium(fmap, width=700, height=380)
        except Exception as e:
            st.warning(f"Map unavailable: {e}")
    st.caption(f"{T['analysis_time']}: {result['time']}")
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Flood history ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["flood_history"]}</h3>',
                unsafe_allow_html=True)
    _nearby = result.get("nearby_events") or []
    if _nearby:
        for e in _nearby:
            st.markdown(f"• **{e['name']}** ({e['year']}) — {e['dist_km']} km")
    else:
        st.caption(T["no_nearby_events"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Weather ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["weather"]}</h3>',
                unsafe_allow_html=True)
    w = result.get("weather")
    if w:
        w1, w2, w3, w4 = st.columns(4)
        w1.metric(T["temp"], f"{w['temp']} °C")
        w2.metric(T["humidity"], f"{w['humidity']} %")
        w3.metric(T["rain"], f"{w['rain']} mm")
        w4.metric(T["wind"], f"{w['wind']} km/h")
        w5, w6, w7, w8 = st.columns(4)
        w5.metric(T["rain24"], f"{w['rain24']} mm")
        w6.metric(T["rain24prob"], f"{w['rain24prob']} %" if w["rain24prob"] is not None else "–")
        w7.metric(T["wind72"], f"{w['wind72']} km/h")
        w8.metric(T["gust72"], f"{w['gust72']} km/h")
    else:
        st.warning(T["weather_fail"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Soil Fertility ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["soil_title"]}</h3>',
                unsafe_allow_html=True)
    soil_data = cached_soil(result["lat"], result["lon"])
    if soil_data.get("status") == "ok":
        s1, s2, s3, s4 = st.columns(4)
        s1.metric(T["soil_ph"], soil_data["ph"])
        s2.metric(T["soil_texture"], soil_data["texture_class"])
        s3.metric(T["soil_soc"], f'{soil_data["soc_gkg"]} g/kg')
        s4.metric(T["soil_fertility"], soil_data["fertility"])
        st.caption(soil_data["fertility_reason"])
        st.caption(f"Source: {soil_data['source']}")
    else:
        st.info(T["soil_unavailable"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Crop Advisory ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["crop_title"]}</h3>',
                unsafe_allow_html=True)
    _lang_now = st.session_state["lang"]
    adv = advisory.crop_advice(result["prob"], soil_data,
                               temperature_c=(result.get("weather") or {}).get("temp"),
                               month=datetime.now().month)
    for a in adv:
        icon = {"Highly Recommended": "✅", "Recommended": "👍",
                "Suitable": "⚠️", "Suitable with caution": "⚠️",
                "Not Recommended": "🚫", "Advisory": "📌"}.get(a["suitability"], "•")
        with st.expander(f'{icon} {a["crop_en"]} — {a["suitability"]}'):
            st.write(f'**{a["crop_ur"]}**')
            st.write(a["reason_en"] if _lang_now == "en" else a["reason_ur"])
            st.caption(a["sowing_tip"] if _lang_now == "en" else a["sowing_tip_ur"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- River Levels ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["river_title"]}</h3>',
                unsafe_allow_html=True)
    rv = cached_rivers()
    b = rv["ffd_bulletin"]
    if b.get("status") == "ok":
        st.subheader(f'FFD — {b["meta"].get("title", "")} ({b["meta"].get("dated", "")})')
        st.table([{"River": k, "Status": v} for k, v in b["levels"].items()])
    else:
        st.warning(T["river_ffd_unavailable"])
    st.subheader("GloFAS " + T["river_discharge"])
    rows_r = [{"River": g["river"], "Site": g["site"],
               "Today (m³/s)": g["discharge_today_m3s"] if g["discharge_today_m3s"] else "—",
               "Note": g["note"]} for g in rv["glofas"]]
    st.table(rows_r)
    st.caption(rv["disclaimer"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Satellite View ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["sat_title"]}</h3>',
                unsafe_allow_html=True)
    _today = datetime.now().date()
    sat_date = st.date_input(T["sat_date"], value=_today,
                             min_value=_today - timedelta(days=30),
                             max_value=_today, key="sat_date")
    try:
        sat_url = advisory.satellite_image_url(result["lat"], result["lon"],
                                               sat_date.isoformat())
        st.image(sat_url,
                 caption=f"NASA MODIS Terra true-colour — {sat_date.isoformat()}",
                 use_container_width=True)
    except Exception as e:
        st.warning(f"Satellite image unavailable: {e}")
    st.caption("Source: NASA GIBS (free, no key)")
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- AQI ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["aqi"]}</h3>',
                unsafe_allow_html=True)
    a = result.get("aqi")
    if a and a.get("us") is not None:
        a1, a2, a3, a4 = st.columns(4)
        a1.metric(f"{T['us_aqi']} ({aqi_category(a['us'], T)})", a["us"])
        a2.metric(T["eu_aqi"], a["eu"])
        a3.metric("PM2.5", a["pm25"])
        a4.metric("PM10", a["pm10"])
    else:
        st.warning(T["aqi_fail"])
    st.markdown(f'<div class="fg-note">{T["weather_note"]}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Compare ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["compare"]}</h3>',
                unsafe_allow_html=True)
    if st.button(T["save_compare"], key="save_cmp"):
        if len(st.session_state["compare"]) >= 3:
            st.warning(T["compare_full"])
        elif any(c["vid"] == result["vid"] for c in st.session_state["compare"]):
            st.info(T["compare_saved"])
        else:
            st.session_state["compare"].append(result)
            st.success(T["compare_saved"])
            st.rerun()
    cmp_list = st.session_state["compare"]
    if len(cmp_list) >= 2:
        df = pd.DataFrame([{
            T["village"]: c["village"],
            T["coords"]: f"{c['lat']:.4f}, {c['lon']:.4f}",
            f"{T['static_prob']} %": c["prob"],
            T["prediction"]: c["prediction"],
        } for c in cmp_list])
        st.dataframe(df, use_container_width=True)
        chart_df = pd.DataFrame({
            T["village"]: [c["village"] for c in cmp_list],
            T["probability"]: [c["prob"] for c in cmp_list],
        }).set_index(T["village"])
        st.bar_chart(chart_df)
    else:
        st.caption(T["compare_empty"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Emergency ----
    with st.expander(T["emergency"]):
        st.markdown(f"**{T['helplines']}:**")
        st.markdown("- PDMA Punjab: **1129**\n- Rescue: **1122**")
        st.markdown(f"**{T['tips']}:**")
        for tip in T["tips_list"]:
            st.markdown(f"- {tip}")

    # ---- Download ----
    try:
        pdf_bytes = build_pdf(result)
        st.download_button(
            label=T["download"],
            data=pdf_bytes,
            file_name=f"floodguard_report_{result['vid']}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(f"PDF unavailable: {e}")

st.markdown(f'<div class="fg-note" style="margin-top:18px">{T["disclaimer"]}</div>',
            unsafe_allow_html=True)
if model_kind() == "2026":
    _footer = ("FloodGuard AI | 2026 national model: 79 historical flood events (2006–2025), "
               "28,916 villages | Live elevation/weather/AQI: Open-Meteo")
    if st.session_state["lang"] == "ur":
        _footer = ("فلڈ گارڈ اے آئی | 2026 قومی ماڈل: 79 تاریخی سیلاب واقعات، 28,916 بستیاں | "
                   "لائیو بلندی/موسم/ہوا: Open-Meteo")
else:
    _footer = T["footer"]
st.markdown(f'<div class="fg-footer">{_footer}</div>', unsafe_allow_html=True)
