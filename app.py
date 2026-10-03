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
import time
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import advisory  # soil, crop advice, river levels, satellite (no streamlit dep)

import dashboard   # district risk dashboard (no streamlit dep at import)
import forecast    # 7-day rain forecast (no streamlit dep at import)
import geocode     # reverse geocoding — exact village/town name (no streamlit dep)
import official    # NDMA/PDMA official alerts (no streamlit dep)
import reports     # community flood reports via Telegram (no streamlit dep)
import voice       # Urdu voice readout via gTTS (no streamlit dep at import)

try:
    import share_image  # PIL-based shareable result card
except Exception:  # pillow missing -> share section hides itself
    share_image = None

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
        "desc": ("Flood risk predicted by the 2026 national model — trained on 79 historical "
                 "Pakistan flood events (2006–2025). Live weather, rivers and air quality shown as supplementary context."),
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
        "gps_btn_label": "📍 Use My Location",
        "gps_locating": "⏳ Locating… (tap Allow if your browser asks)",
        "gps_denied_msg": "❌ Location is blocked for this site. Tap the 🔒 icon in the address bar → Permissions → Location → Allow, then tap the button again.",
        "gps_unavailable_msg": "❌ Position unavailable — please turn ON location services (GPS) on your device and try again.",
        "gps_timeout_msg": "⏰ Timed out — try again, or tap your place on the map below.",
        "gps_nosupport_msg": "❌ This browser has no location support — please use the map below.",
        "gps_found_msg": "✅ Location found!",
        "gps_tap_hint": "👇 Tap the 🎯 button for your current location, then tap Allow",
        "gps_map_title": "🗺️ Tap your location on the map (no permission needed)",
        "gps_map_hint": "Tap anywhere on the map to set your location — the exact village name will appear.",
        "village_search_title": "🔎 Find your village by name (easiest)",
        "village_search_hint": "Type village name…",
        "village_search_pick": "Select your village",
        "village_search_go": "📍 Use this village",
        "village_search_none": "No village found with that name — try the map below.",
        "gps_fail": "GPS not available in this environment — please enter coordinates manually.",
        "gps_waiting": "📡 Waiting for browser location… please tap Allow when your browser asks.",
        "gps_denied_hint": ("Location is blocked or unavailable. Tap the 📍/🔒 icon in your "
                            "browser's address bar → allow Location for this site → then press "
                            "the button again. (Works best on a mobile phone.)"),
        "gps_you_are_at": "📍 You are at",
        "gps_accuracy": "GPS accuracy",
        "gps_exact_unavailable": "Exact place name unavailable — showing nearest mapped village.",
        "nearest_village": "Nearest Village",
        "village_id": "Village ID",
        "village_lbl": "Village",
        "tehsil_lbl": "Tehsil",
        "district_lbl": "District",
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
        "soil_moisture": "💧 Soil Moisture",
        "sm_dry": "Dry", "sm_moist": "Moist", "sm_wet": "Wet",
        "sm_saturated": "Saturated ⚠️",
        "sm_note": "Saturated soil absorbs less rain — flood risk rises.",
        "live_now": "🔴 LIVE RIGHT NOW",
        "rain_now": "Raining now", "rain_next3h": "Next 3h rain",
        "updated": "Updated",
        "auto_refresh": "🔄 Auto-refresh live data (5 min)",
        "live_hint": "Flood susceptibility changes slowly; live rain, rivers and weather refresh continuously.",
        "weather_note": ("Live weather and AQI are shown as live environmental information. "
                         "The flood probability comes from the 2026 national Random Forest model "
                         "(79 historical Pakistan flood events, 2006–2025; 98.5% holdout accuracy)."),
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
        "footer": "FloodGuard AI | 2026 national model: 79 flood events (2006–2025) | 56,615 villages | Live weather/AQI: Open-Meteo",
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
        "sat_fallback": "Closest available image shown",
        "sat_unavailable": "Satellite image unavailable right now.",
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
        "loading": "Loading...",
        "dash_title": "🗺️ District Risk Dashboard",
        "dash_sub": "Flood risk across {n} districts of Pakistan (2026 national model)",
        "dash_unavailable": "District risk data unavailable right now.",
        "dash_top10": "Top 10 riskiest districts",
        "dash_note": ("District risk is computed with the 2026 national model at each "
                      "district's centroid — indicative only, not a substitute for official alerts."),
        "col_district": "District", "col_province": "Province",
        "col_risk": "Risk %", "col_band": "Band",
        "fc_title": "📊 7-Day Rain Forecast",
        "fc_total": "Total expected rain", "fc_maxprob": "Highest rain probability",
        "fc_heavy": "⚠️ Heavy rain expected in the next 7 days — stay alert.",
        "fc_unavailable": "7-day forecast unavailable right now.",
        "share_title": "🖼️ Share This Result",
        "share_desc": "Download a shareable image of this result for WhatsApp / Facebook.",
        "share_download": "⬇️ Download shareable image",
        "voice_title": "🔊 Listen to Result (Urdu)",
        "voice_play": "🔊 Play Urdu result",
        "voice_download": "⬇️ Download voice (MP3)",
        "voice_unavailable": "Urdu voice unavailable right now.",
        "alerts_title": "📲 Flood Alerts",
        "alerts_desc": "Get a WhatsApp or Email alert when flood risk at your location reaches 60%+. Checked automatically every morning (06:00 PKT).",
        "alerts_name": "Your name",
        "alerts_contact": "WhatsApp number (with country code) or Email",
        "alerts_contact_hint": "e.g. 923001234567 or you@example.com",
        "alerts_subscribe": "🔔 Subscribe to alerts",
        "alerts_ok": "Subscribed! You will be alerted when flood risk is high.",
        "alerts_bad": "Please enter your name and a valid WhatsApp number or email.",
        "alerts_note": "Alerts are free. WhatsApp delivery needs a one-time opt-in — see ALERTS_SETUP.md. You can unsubscribe anytime.",
        "reports_title": "🗣️ Community Flood Reports",
        "reports_desc": "See waterlogging or flooding in your area? Report it — it appears on the map for everyone.",
        "reports_name": "Your name (or anonymous)",
        "reports_severity": "Severity",
        "reports_note_ph": "What do you see? e.g. knee-deep water on Main Road",
        "reports_send": "📤 Send report",
        "reports_sent": "Report posted ✅ — thank you!",
        "reports_failed": "Could not post report: ",
        "reports_recent": "Recent community reports",
        "reports_none": "No community reports yet — be the first!",
        "reports_setup": "Community reporting is not configured yet (needs TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in Streamlit Secrets — see TELEGRAM_SETUP.md).",
        "sev_low": "Low — waterlogging",
        "sev_moderate": "Moderate — streets flooded",
        "sev_severe": "Severe — houses/fields flooded",
        "official_title": "🏛️ Official Alerts (NDMA / PDMA)",
        "official_latest": "Latest NDMA Situation Report",
        "official_sitreps": "Recent NDMA situation reports",
        "official_links": "Official sources",
        "official_unavailable": "Official feed temporarily unavailable — use the links below.",
    },
    "ur": {
        "tagline": "جی پی ایس پر مبنی سیلاب کے خطرے کی پیش گوئی اور لائیو ماحولیاتی نگرانی",
        "desc": ("سیلاب کے خطرے کی پیش گوئی 2026 کے قومی ماڈل سے ہوتی ہے — 79 تاریخی پاکستانی سیلاب "
                 "واقعات (2006–2025) پر تربیت یافتہ۔ لائیو موسم، دریا اور ہوا کا معیار اضافی معلومات کے طور پر دکھائے جاتے ہیں۔"),
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
        "gps_btn_label": "📍 میری لوکیشن استعمال کریں",
        "gps_locating": "⏳ لوکیشن معلوم کی جا رہی ہے… (اگر براؤزر پوچھے تو Allow دبائیں)",
        "gps_denied_msg": "❌ اس سائٹ کے لیے لوکیشن بلاک ہے۔ ایڈریس بار میں 🔒 آئیکن دبائیں → Permissions → Location → Allow کریں، پھر بٹن دوبارہ دبائیں۔",
        "gps_unavailable_msg": "❌ لوکیشن دستیاب نہیں — اپنے ڈیوائس کی لوکیشن سروس (GPS) آن کریں اور دوبارہ کوشش کریں۔",
        "gps_timeout_msg": "⏰ وقت ختم ہو گیا — دوبارہ کوشش کریں یا نیچے نقشے پر اپنی جگہ tap کریں۔",
        "gps_nosupport_msg": "❌ یہ براؤزر لوکیشن سپورٹ نہیں کرتا — نیچے نقشہ استعمال کریں۔",
        "gps_found_msg": "✅ لوکیشن مل گئی!",
        "gps_tap_hint": "👇 اپنی موجودہ لوکیشن کے لیے 🎯 بٹن دبائیں، پھر Allow کریں",
        "gps_map_title": "🗺️ نقشے پر اپنی جگہ tap کریں (اجازت کی ضرورت نہیں)",
        "gps_map_hint": "لوکیشن سیٹ کرنے کے لیے نقشے پر کہیں بھی tap کریں — اصل گاؤں کا نام ظاہر ہوگا۔",
        "village_search_title": "🔎 نام سے اپنا گاؤں تلاش کریں (سب سے آسان)",
        "village_search_hint": "گاؤں کا نام لکھیں…",
        "village_search_pick": "اپنا گاؤں منتخب کریں",
        "village_search_go": "📍 یہ گاؤں استعمال کریں",
        "village_search_none": "اس نام کا کوئی گاؤں نہیں ملا — نیچے نقشہ آزمائیں۔",
        "gps_fail": "اس ماحول میں GPS دستیاب نہیں — براہ کرم کوآرڈینیٹس خود درج کریں۔",
        "gps_waiting": "📡 براؤزر کی لوکیشن کا انتظار ہے… براہ کرم پوچھے جانے پر Allow دبائیں۔",
        "gps_denied_hint": ("لوکیشن بلاک یا دستیاب نہیں۔ براؤزر کے ایڈریس بار میں 📍/🔒 آئیکن دبائیں ← "
                            "اس سائٹ کے لیے لوکیشن Allow کریں ← پھر بٹن دبائیں۔ (موبائل فون پر بہترین کام کرتا ہے۔)"),
        "gps_you_are_at": "📍 آپ اس وقت یہاں ہیں",
        "gps_accuracy": "GPS درستگی",
        "gps_exact_unavailable": "اصل جگہ کا نام دستیاب نہیں — قریبی درج گاؤں دکھایا جا رہا ہے۔",
        "nearest_village": "قریبی گاؤں",
        "village_id": "گاؤں کا نمبر",
        "village_lbl": "گاؤں",
        "tehsil_lbl": "تحصیل",
        "district_lbl": "ضلع",
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
        "soil_moisture": "💧 مٹی میں نمی",
        "sm_dry": "خشک", "sm_moist": "نم", "sm_wet": "گیلا",
        "sm_saturated": "پانی سے بھرا ⚠️",
        "sm_note": "بھری ہوئی مٹی کم بارش جذب کرتی ہے — سیلاب کا خطرہ بڑھتا ہے۔",
        "live_now": "🔴 ابھی لائیو",
        "rain_now": "اس وقت بارش", "rain_next3h": "اگلے 3 گھنٹے میں بارش",
        "updated": "اپ ڈیٹ ہوا",
        "auto_refresh": "🔄 لائیو ڈیٹا خودکار ریفریش (5 منٹ)",
        "live_hint": "سیلاب کا خطرہ آہستہ بدلتا ہے؛ لائیو بارش، دریا اور موسم مسلسل اپ ڈیٹ ہوتے ہیں۔",
        "weather_note": ("لائیو موسم اور ہوا کا معیار لائیو ماحولیاتی معلومات کے طور پر دکھائے جاتے ہیں۔ "
                         "سیلاب کا امکان 2026 کے قومی رینڈم فاریسٹ ماڈل سے حاصل ہوتا ہے "
                         "(79 تاریخی پاکستانی سیلاب واقعات، 2006–2025؛ 98.5% درستگی)."),
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
        "footer": "فلڈ گارڈ اے آئی | 2026 قومی ماڈل: 79 سیلاب واقعات (2006–2025) | 56,615 بستیاں | لائیو موسم/ہوا: Open-Meteo",
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
        "sat_fallback": "قریب ترین دستیاب تصویر دکھائی جا رہی ہے",
        "sat_unavailable": "سیٹلائٹ تصویر اس وقت دستیاب نہیں۔",
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
        "loading": "لوڈ ہو رہا ہے...",
        "dash_title": "🗺️ ضلعی رسک ڈیش بورڈ",
        "dash_sub": "پاکستان کے {n} اضلاع میں سیلاب کا خطرہ (2026 قومی ماڈل)",
        "dash_unavailable": "ضلعی رسک کا ڈیٹا اس وقت دستیاب نہیں۔",
        "dash_top10": "10 سب سے زیادہ خطرے والے اضلاع",
        "dash_note": ("ضلعی خطرہ 2026 قومی ماڈل سے ہر ضلع کے مرکز پر نکالا گیا ہے — صرف اشارتی، "
                      "سرکاری الرٹس کا متبادل نہیں۔"),
        "col_district": "ضلع", "col_province": "صوبہ",
        "col_risk": "خطرہ %", "col_band": "درجہ",
        "fc_title": "📊 7 دن کی بارش کی پیش گوئی",
        "fc_total": "متوقع کل بارش", "fc_maxprob": "بارش کا زیادہ سے زیادہ امکان",
        "fc_heavy": "⚠️ اگلے 7 دنوں میں موسلا دھار بارش متوقع — ہوشیار رہیں۔",
        "fc_unavailable": "7 دن کی پیش گوئی اس وقت دستیاب نہیں۔",
        "share_title": "🖼️ یہ نتیجہ شیئر کریں",
        "share_desc": "WhatsApp / Facebook کے لیے اس نتیجے کی شیئر کرنے والی تصویر ڈاؤن لوڈ کریں۔",
        "share_download": "⬇️ شیئر تصویر ڈاؤن لوڈ کریں",
        "voice_title": "🔊 نتیجہ سنیں (اردو)",
        "voice_play": "🔊 اردو نتیجہ چلائیں",
        "voice_download": "⬇️ آواز ڈاؤن لوڈ کریں (MP3)",
        "voice_unavailable": "اردو آواز اس وقت دستیاب نہیں۔",
        "alerts_title": "📲 سیلاب الرٹس",
        "alerts_desc": "جب آپ کے علاقے میں سیلاب کا خطرہ 60%+ ہو تو WhatsApp یا ای میل الرٹ حاصل کریں۔ روز صبح 06:00 بجے خودکار چیک ہوتا ہے۔",
        "alerts_name": "آپ کا نام",
        "alerts_contact": "WhatsApp نمبر (کنٹری کوڈ کے ساتھ) یا ای میل",
        "alerts_contact_hint": "مثلاً 923001234567 یا you@example.com",
        "alerts_subscribe": "🔔 الرٹ کے لیے سبسکرائب کریں",
        "alerts_ok": "سبسکرائب ہو گیا! خطرہ بڑھنے پر آپ کو الرٹ ملے گا۔",
        "alerts_bad": "براہ کرم نام اور درست WhatsApp نمبر یا ای میل درج کریں۔",
        "alerts_note": "الرٹس مفت ہیں۔ WhatsApp کے لیے ایک بار opt-in ضروری ہے — ALERTS_SETUP.md دیکھیں۔",
        "reports_title": "🗣️ عوامی سیلاب رپورٹس",
        "reports_desc": "اپنے علاقے میں پانی جمع یا سیلاب دیکھا؟ رپورٹ کریں — سب کے نقشے پر نظر آئے گی۔",
        "reports_name": "آپ کا نام (یا گمنام)",
        "reports_severity": "شدت",
        "reports_note_ph": "کیا دیکھا؟ مثلاً مین روڈ پر گھٹنوں تک پانی",
        "reports_send": "📤 رپورٹ بھیجیں",
        "reports_sent": "رپورٹ پوسٹ ہو گئی ✅ — شکریہ!",
        "reports_failed": "رپورٹ نہیں بھیجی جا سکی: ",
        "reports_recent": "حالیہ عوامی رپورٹس",
        "reports_none": "ابھی کوئی عوامی رپورٹ نہیں — پہلے آپ بھیجیں!",
        "reports_setup": "عوامی رپورٹنگ ابھی سیٹ اپ نہیں (Streamlit Secrets میں TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID درکار — TELEGRAM_SETUP.md دیکھیں)۔",
        "sev_low": "کم — پانی جمع ہے",
        "sev_moderate": "درمیانہ — گلیاں ڈوب گئیں",
        "sev_severe": "شدید — گھر/کھیت ڈوب گئے",
        "official_title": "🏛️ سرکاری الرٹس (NDMA / PDMA)",
        "official_latest": "NDMA کی تازہ ترین صورتحال رپورٹ",
        "official_sitreps": "NDMA کی حالیہ صورتحال رپورٹس",
        "official_links": "سرکاری ذرائع",
        "official_unavailable": "سرکاری فیڈ عارضی طور پر دستیاب نہیں — نیچے دیے گئے لنکس استعمال کریں۔",
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
# Auto-built fallback: pakistan_master_v3.csv (56,615 densified OSM + 2022
# FloodSave places, with district/tehsil/population/elevation — built 2026-10-03).
# Generated by merge_v2_v3.py — no user upload needed.
AUTO_MASTER_V3_PATH = os.path.join(APP_DIR, "pakistan_master_v3.csv")
# Previous fallback (kept): pakistan_master_v2.csv (33,492 OSM Pakistan places).
AUTO_MASTER_V2_PATH = os.path.join(APP_DIR, "pakistan_master_v2.csv")
# Legacy fallback (kept): pakistan_master.csv (~29k HOTOSM Pakistan settlements).
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
    2. pakistan_master_v3.csv (56,615 merged OSM + 2022 places, 2026-10-03)
    3. pakistan_master_v2.csv (33,492 densified OSM places)
    4. pakistan_master.csv (legacy auto-built, ~29k places)
    5. None -> 8-village demo fallback in find_nearest_village().
    """
    for loader in (_master_from_geojson, _master_from_auto_csv_v3,
                   _master_from_auto_csv_v2, _master_from_auto_csv):
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


def _master_from_auto_csv_v3():
    """Merged Pakistan places CSV (see merge_v2_v3.py, 2026-10-03).

    v3 columns: vid,name,name_ur,lat,lon,district,tehsil,province,
                population,elevation_m,source
    -> mapped onto the standard master schema. Real population/elevation
    ride through _finalise_master (median-fill only touches NaNs).
    """
    v3 = pd.read_csv(AUTO_MASTER_V3_PATH)
    df = pd.DataFrame({
        "village": v3["name"],
        "village_id": v3["vid"],
        "latitude": v3["lat"],
        "longitude": v3["lon"],
        "population": pd.to_numeric(v3["population"], errors="coerce"),
        "dem_m": pd.to_numeric(v3["elevation_m"], errors="coerce"),
        "area_km2": float("nan"),
        "_province": v3["province"],   # ride through _finalise_master untouched
        "_district": v3["district"],
        "_tehsil": v3["tehsil"],
    })
    return _finalise_master(df)


def _master_from_auto_csv_v2():
    """Densified Pakistan places CSV (see build_villages.py, 2026-10-03).

    v2 columns: vid,name,name_ur,lat,lon,district,province,source
    -> mapped onto the standard master schema. population/dem_m/area_km2
    stay NaN and are handled by _finalise_master (median fill; elevation
    is fetched live per query anyway).
    """
    v2 = pd.read_csv(AUTO_MASTER_V2_PATH)
    df = pd.DataFrame({
        "village": v2["name"],
        "village_id": v2["vid"],
        "latitude": v2["lat"],
        "longitude": v2["lon"],
        "population": float("nan"),
        "dem_m": float("nan"),
        "area_km2": float("nan"),
        "_province": v2["province"],  # rides through _finalise_master untouched
    })
    return _finalise_master(df)


def _master_from_auto_csv():
    """Legacy auto-built Pakistan settlements CSV (see build_master.py)."""
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
        "&hourly=precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,"
        "soil_temperature_6cm,soil_moisture_3_9cm"
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
        "rain_next3h": None,
        "soil_moisture": None, "soil_temp": None,
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
        out["rain_next3h"] = round(sum(x for x in precip[:3] if x is not None), 1)
        out["wind72"] = round(max((x for x in wind if x is not None), default=0), 1)
        out["gust72"] = round(max((x for x in gust if x is not None), default=0), 1)
        # soil state at current hour (fraction m3/m3 -> %)
        _sm = (hourly.get("soil_moisture_3_9cm", []) or [None])
        _st = (hourly.get("soil_temperature_6cm", []) or [None])
        _smi = min(idx, len(_sm) - 1)
        if _smi >= 0 and _sm[_smi] is not None:
            out["soil_moisture"] = round(float(_sm[_smi]) * 100, 1)
        if _smi >= 0 and _st[_smi] is not None:
            out["soil_temp"] = round(float(_st[_smi]), 1)
    except Exception:
        pass
    return out


def soil_moisture_verdict(pct, T):
    """Saturation verdict for flood relevance. Returns (label, is_bad)."""
    if pct is None:
        return ("–", False)
    if pct < 15:
        return (T["sm_dry"], False)
    if pct < 30:
        return (T["sm_moist"], False)
    if pct < 42:
        return (T["sm_wet"], False)
    return (T["sm_saturated"], True)


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


@st.cache_data(ttl=6 * 3600, show_spinner=False)        # NDMA site: don't hammer
def cached_official():
    return official.get_official_alerts(limit=5, parse_latest_pdf=True)


@st.cache_data(show_spinner=False)
def cached_share_image(village, prob, band_en, date_str):
    """Shareable PNG bytes for the download button; None when unavailable."""
    if share_image is None:
        return None
    try:
        return share_image.make_share_image(village, prob, band_en,
                                            date_str).getvalue()
    except Exception:
        return None


def get_secrets_dict():
    """st.secrets as a plain dict, or None when no secrets are configured."""
    try:
        return dict(st.secrets)
    except Exception:
        return None


def apply_gps_coords(glat, glon, T):
    """Apply a coordinate fix: fill the inputs, reverse-geocode the exact
    place name, and announce it. Callers guarantee this runs once per fix
    (component path uses fresh-fix detection; map path uses gps_tapped).

    NOTE (Streamlit gotcha): a number_input's displayed value comes from its
    *widget state* (key 'lat_in'), NOT from the value= parameter, once the
    widget exists. So we stash the new coords in '_set_lat'/'_set_lon' and
    the location section copies them into the widget keys BEFORE creating
    the inputs on the next run. Setting them here directly would raise
    StreamlitAPIException (widget already instantiated)."""
    glat, glon = round(float(glat), 4), round(float(glon), 4)
    st.session_state["lat"], st.session_state["lon"] = glat, glon
    # pending widget update — consumed before number_input creation
    st.session_state["_set_lat"], st.session_state["_set_lon"] = glat, glon
    # banner trigger: a fix was applied (independent of Nominatim success)
    st.session_state["place_banner"] = True
    with st.spinner(T["loading"]):
        _place = geocode.reverse_geocode(glat, glon)
    if _place.get("status") == "ok":
        st.session_state["gps_place"] = _place
        _pname = geocode.describe_place(_place)
        _acc = st.session_state.get("gps_accuracy_m")
        _acc_txt = f" ({T['gps_accuracy']}: ±{_acc:.0f} m)" if _acc else ""
        st.success(f"{T['gps_ok']} {T['gps_you_are_at']}: **{_pname}**{_acc_txt}")
    else:
        st.session_state["gps_place"] = None
        st.success(T["gps_ok"])


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
    auto_rf = st.toggle(T["auto_refresh"],
                        value=st.session_state.get("auto_refresh", False),
                        key="auto_refresh_tgl")
    st.session_state["auto_refresh"] = auto_rf
    if auto_rf:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=5 * 60 * 1000, key="live_autorefresh")
        except Exception:
            pass

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
# Pending programmatic coordinate updates (from village search / map tap /
# GPS button) must be written into the widget keys BEFORE the number_inputs
# are created — afterwards Streamlit would ignore value= and refuse the write.
if "_set_lat" in st.session_state:
    st.session_state["lat_in"] = st.session_state.pop("_set_lat")
if "_set_lon" in st.session_state:
    st.session_state["lon_in"] = st.session_state.pop("_set_lon")
c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    lat = st.number_input(T["latitude"], value=float(st.session_state["lat"]),
                          format="%.4f", step=0.0001, key="lat_in")
with c2:
    lon = st.number_input(T["longitude"], value=float(st.session_state["lon"]),
                          format="%.4f", step=0.0001, key="lon_in")
with c3:
    # Our own GPS button component: big button, 15s timeout, permission
    # guidance. Returns {'event':'fix','lat','lon','acc'} on a fresh fix.
    try:
        from gps_button_component import gps_button as _gps_btn
        _gres = _gps_btn(T, key="gps_btn")
    except Exception:
        _gres = None
        st.caption(T["gps_nosupport_msg"])
    if isinstance(_gres, dict) and _gres.get("event") == "fix":
        try:
            _glat = float(_gres.get("lat")); _glon = float(_gres.get("lon"))
            _sig = (round(_glat, 4), round(_glon, 4))
            if st.session_state.get("gps_seen") != _sig:
                st.session_state["gps_seen"] = _sig
                if _gres.get("acc") is not None:
                    st.session_state["gps_accuracy_m"] = float(_gres.get("acc"))
                apply_gps_coords(_glat, _glon, T)
                st.rerun()
        except Exception:
            pass

# ---- Method 1 (easiest): find village by name — works for everyone ----
st.markdown(f"**{T['village_search_title']}**")
_vq = st.text_input(T["village_search_hint"], key="village_q",
                    placeholder="Warianwala")
if _vq and len(_vq.strip()) >= 2:
    try:
        _vmaster = load_master()
        _hits = _vmaster[_vmaster["village"].str.contains(
            _vq.strip(), case=False, na=False)].head(20)
        if len(_hits):
            _opts = []
            for _, _r in _hits.iterrows():
                _area = _r.get("_district") or _r.get("_province") or ""
                _area = str(_area).strip()
                _opts.append(f"{_r['village']}" + (f" ({_area})" if _area and _area != "nan" else ""))
            _pick = st.selectbox(T["village_search_pick"], _opts)
            _scol1, _scol2 = st.columns([1, 3])
            with _scol1:
                if st.button(T["village_search_go"], key="village_go"):
                    _row = _hits.iloc[_opts.index(_pick)]
                    apply_gps_coords(float(_row["latitude"]),
                                     float(_row["longitude"]), T)
                    st.rerun()
        else:
            st.info(T["village_search_none"])
    except Exception:
        pass

# ---- Method 2: tap on the map — ZERO browser permission needed ----
st.markdown(f"**{T['gps_map_title']}**")
st.caption(T["gps_map_hint"])
try:
    from streamlit_folium import st_folium
    import folium as _fl

    _clat, _clon = float(st.session_state["lat"]), float(st.session_state["lon"])
    _pick = _fl.Map(location=[_clat, _clon], zoom_start=11,
                    tiles="OpenStreetMap")
    _fl.Marker([_clat, _clon], tooltip=T["gps_tap_hint"]).add_to(_pick)
    _tapped = st_folium(_pick, height=280, width=700, key="gps_pick_map")
    _lc = (_tapped or {}).get("last_clicked")
    if _lc:
        _tlat, _tlon = round(float(_lc["lat"]), 4), round(float(_lc["lng"]), 4)
        _last_tap = st.session_state.get("gps_tapped")
        if tuple(_last_tap or (None, None)) != (_tlat, _tlon):
            st.session_state["gps_tapped"] = (_tlat, _tlon)
            apply_gps_coords(_tlat, _tlon, T)
            st.rerun()
except Exception:
    pass
st.session_state["lat"], st.session_state["lon"] = lat, lon

# persistent exact-place banner (survives reruns, unlike st.success above)
# Shows the nearest village from OUR 56k dataset (exact + instant) with
# tehsil/district — triggered whenever a fix was applied.
if st.session_state.get("place_banner"):
    try:
        _bv = find_nearest_village(lat, lon)
        _brow = _bv.get("_row")

        def _bc(col):
            try:
                _v = _brow[col] if _brow is not None and col in _brow.index else ""
                return str(_v).strip() if pd.notna(_v) and str(_v).strip() != "nan" else ""
            except Exception:
                return ""

        _bsub = ", ".join(p for p in
                          [f"{T['tehsil_lbl']} {_bc('_tehsil')}" if _bc("_tehsil") else "",
                           f"{T['district_lbl']} {_bc('_district')}" if _bc("_district") else ""]
                          if p)
        _gacc = st.session_state.get("gps_accuracy_m")
        _gacct = f" ({T['gps_accuracy']}: ±{_gacc:.0f} m)" if _gacc else ""
        st.info(f"{T['gps_you_are_at']}: **{_bv['name']}**" +
                (f" ({_bsub})" if _bsub else "") + _gacct)
    except Exception:
        pass

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
    # exact place name: prefer live reverse-geocode of the checked coords
    # (falls back to the GPS-fix name, then the nearest dataset village)
    _exact = st.session_state.get("gps_place")
    if not (_exact and _exact.get("status") == "ok"
            and abs(_exact.get("lat", 0) - lat) < 0.02
            and abs(_exact.get("lon", 0) - lon) < 0.02):
        _rg = geocode.reverse_geocode(lat, lon)
        _exact = _rg if _rg.get("status") == "ok" else None
    exact_name = geocode.describe_place(_exact) if _exact else ""
    _vrow = village.get("_row")
    def _rc(col):
        try:
            v = _vrow[col] if _vrow is not None and col in _vrow.index else ""
            return str(v).strip() if pd.notna(v) else ""
        except Exception:
            return ""
    result = {
        "lat": lat, "lon": lon,
        "village": village["name"], "vid": village["vid"],
        "vlat": village["lat"], "vlon": village["lon"],
        "dist_km": village["dist_km"],
        "village_district": _rc("_district"),
        "village_tehsil": _rc("_tehsil"),
        "exact_name": exact_name,
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
    # ---- 🔴 LIVE NOW strip ----
    _w = result.get("weather") or {}
    _rain_now = _w.get("rain")
    _rain3 = _w.get("rain_next3h")
    if _rain_now is not None or _rain3 is not None:
        st.markdown(f'<div class="fg-card" style="border-left:5px solid #e74c3c">'
                    f'<h3 style="margin-top:0">{T["live_now"]}</h3>',
                    unsafe_allow_html=True)
        l1, l2, l3 = st.columns(3)
        l1.metric(T["rain_now"], f"{_rain_now} mm" if _rain_now is not None else "–")
        l2.metric(T["rain_next3h"], f"{_rain3} mm" if _rain3 is not None else "–")
        l3.metric(T["updated"], result["time"])
        st.caption(T["live_hint"])
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["risk_model"]}</h3>',
                unsafe_allow_html=True)
    i1, i2, i3, i4 = st.columns(4)
    # Village + Tehsil + District — all three, prominently (user requirement)
    i1.metric(T["village_lbl"], result["village"])
    i2.metric(T["tehsil_lbl"], result.get("village_tehsil") or "–")
    i3.metric(T["district_lbl"], result.get("village_district") or "–")
    i4.metric(T["coords"], f"{result['lat']:.4f}, {result['lon']:.4f}")
    _cap = f"{T['village_id']}: {result['vid']} · {T['distance']}: {result['dist_km']:.2f} km"
    if result.get("exact_name") and result["exact_name"] != result["village"]:
        st.caption(f"📍 {result['exact_name']} · {_cap}")
    elif not result.get("exact_name"):
        st.caption(f"{T['gps_exact_unavailable']} · {_cap}")
    else:
        st.caption(_cap)

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
            # community report markers (stashed by the 🗣️ section below)
            for _m in st.session_state.get("_report_markers", []):
                try:
                    import folium

                    folium.Marker(
                        [_m["lat"], _m["lon"]],
                        popup=_m["popup_html"],
                        icon=folium.Icon(color=_m["color"],
                                         icon="exclamation-triangle", prefix="fa"),
                    ).add_to(fmap)
                except Exception:
                    pass
            st_folium(fmap, width=700, height=380)
        except Exception as e:
            st.warning(f"Map unavailable: {e}")
    st.caption(f"{T['analysis_time']}: {result['time']}")
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Shareable image + Urdu voice ----
    _band_en = "Low" if result["prob"] < 30 else ("Moderate" if result["prob"] < 60 else "High")
    if share_image is not None:
        st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["share_title"]}</h3>',
                    unsafe_allow_html=True)
        st.caption(T["share_desc"])
        _png = cached_share_image(result["village"], result["prob"], _band_en,
                                  result["time"])
        if _png:
            st.download_button(
                label=T["share_download"],
                data=_png,
                file_name=f"floodguard_{result['vid']}.png",
                mime="image/png",
                key="share_dl",
            )
        st.markdown("</div>", unsafe_allow_html=True)
    try:
        import gtts  # noqa: F401

        st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["voice_title"]}</h3>',
                    unsafe_allow_html=True)
        # audio bytes live in session_state so the player survives reruns
        # (a bare st.button gate made the player vanish mid-playback)
        _vkey = f"voice_{result['vid']}_{int(result['prob'])}"
        _vdlkey = _vkey + "_dl"
        if _vkey not in st.session_state:
            if st.button(T["voice_play"], key="voice_btn"):
                with st.spinner(T["loading"]):
                    _speech = voice.build_result_speech(result["village"],
                                                        result["prob"], _band_en)
                    _audio = voice.speak_urdu(_speech)
                st.session_state[_vkey] = (_audio.getvalue()
                                          if _audio is not None else None)
                st.rerun()
        _vbytes = st.session_state.get(_vkey)
        if _vbytes:
            st.audio(_vbytes, format="audio/mp3")
            st.download_button(
                label=T["voice_download"], data=_vbytes,
                file_name=f"floodguard_voice_{result['vid']}.mp3",
                mime="audio/mp3", key=_vdlkey)
        elif _vkey in st.session_state:
            st.info(T["voice_unavailable"])
        st.markdown("</div>", unsafe_allow_html=True)
    except Exception:
        pass  # gTTS missing -> hide voice section silently

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
        _smv, _smbad = soil_moisture_verdict(w.get("soil_moisture"), T)
        w9, w10 = st.columns(2)
        _smtxt = f"{w['soil_moisture']} %" if w.get("soil_moisture") is not None else "–"
        w9.metric(T["soil_moisture"], _smtxt,
                  delta=_smv if w.get("soil_moisture") is not None else None)
        if _smbad:
            w10.warning(f"⚠️ {T['sm_note']}")
    else:
        st.warning(T["weather_fail"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- 7-Day Rain Forecast ----
    try:
        forecast.render_7day_forecast(result["lat"], result["lon"], T)
    except Exception:
        st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["fc_title"]}</h3>',
                    unsafe_allow_html=True)
        st.info(T["fc_unavailable"])
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
    _sat_default = _today - timedelta(days=3)  # GIBS imagery lags ~2 days
    sat_date = st.date_input(T["sat_date"], value=_sat_default,
                             min_value=_today - timedelta(days=30),
                             max_value=_today, key="sat_date")
    with st.spinner(T["loading"]):
        _sat = advisory.fetch_satellite_image(result["lat"], result["lon"],
                                              sat_date.isoformat())
    if _sat.get("status") == "ok":
        st.image(_sat["image_bytes"],
                 caption=f"NASA MODIS Terra true-colour — {_sat['date']}",
                 use_container_width=True)
        if _sat["date"] != sat_date.isoformat():
            st.caption(f"ℹ️ {T['sat_fallback']}: {_sat['date']}")
    else:
        st.warning(T["sat_unavailable"])
    st.caption("Source: NASA GIBS (free, no key)")
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Community Flood Reports ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["reports_title"]}</h3>',
                unsafe_allow_html=True)
    st.caption(T["reports_desc"])
    _secrets = get_secrets_dict()
    if reports.is_configured(_secrets):
        r1, r2 = st.columns(2)
        rname = r1.text_input(T["reports_name"], value="", key="rp_name") or "anonymous"
        sevkey = r2.selectbox(
            T["reports_severity"], ["low", "moderate", "severe"],
            format_func=lambda s: {"low": T["sev_low"],
                                   "moderate": T["sev_moderate"],
                                   "severe": T["sev_severe"]}[s],
            key="rp_sev")
        rnote = st.text_input(T["reports_note_ph"], key="rp_note",
                              label_visibility="collapsed",
                              placeholder=T["reports_note_ph"])
        if st.button(T["reports_send"], key="rp_btn"):
            ok, detail = reports.send_report(result["lat"], result["lon"],
                                             result.get("village", ""), rname,
                                             sevkey, rnote, _secrets)
            (st.success if ok else st.warning)(
                T["reports_sent"] if ok else T["reports_failed"] + detail)
        st.subheader(T["reports_recent"])
        reps, rst = reports.fetch_reports(limit=20, secrets=_secrets)
        if rst == "ok" and reps:
            for rp in reps:
                st.markdown(f"• **{rp['village']}** ({rp['severity']}) — "
                            f"{rp['note'] or '—'} <i>{rp['time']}</i>",
                            unsafe_allow_html=True)
        else:
            st.caption(T["reports_none"])
        # stash markers for the map overlay at the top of the results
        st.session_state["_report_markers"] = reports.reports_to_markers(
            reps if rst == "ok" else [])
    else:
        st.info(T["reports_setup"])
    st.markdown("</div>", unsafe_allow_html=True)

    # ---- Official Alerts (NDMA / PDMA) ----
    st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["official_title"]}</h3>',
                unsafe_allow_html=True)
    try:
        with st.spinner(T["loading"]):
            _feed = cached_official()
        _ls = _feed.get("latest_sitrep")
        if _ls:
            st.subheader(f'{T["official_latest"]} — No. {_ls.get("report_no", "")} '
                         f'({_ls.get("date", "")})')
            st.write(_ls.get("summary", ""))
        if _feed.get("items"):
            st.subheader(T["official_sitreps"])
            for it in _feed["items"]:
                st.markdown(f"• [{it['title']}]({it['url']}) — {it.get('date', '')}"
                            + (f" — {it['summary']}" if it.get("summary") else ""))
        if _feed.get("status") != "ok":
            st.caption(_feed.get("notice") or T["official_unavailable"])
        st.subheader(T["official_links"])
        for _label, _url in _feed.get("links", []):
            st.markdown(f"• [{_label}]({_url})")
    except Exception:
        st.info(T["official_unavailable"])
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

    # ---- District Risk Dashboard ----
    try:
        dashboard.render_district_dashboard(T)
    except Exception:
        st.markdown(f'<div class="fg-card"><h3 style="margin-top:0">{T["dash_title"]}</h3>',
                    unsafe_allow_html=True)
        st.info(T["dash_unavailable"])
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
               "56,615 villages | Live elevation/weather/AQI: Open-Meteo")
    if st.session_state["lang"] == "ur":
        _footer = ("فلڈ گارڈ اے آئی | 2026 قومی ماڈل: 79 تاریخی سیلاب واقعات، 56,615 بستیاں | "
                   "لائیو بلندی/موسم/ہوا: Open-Meteo")
else:
    _footer = T["footer"]
st.markdown(f'<div class="fg-footer">{_footer}</div>', unsafe_allow_html=True)
