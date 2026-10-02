"""
FloodGuard AI — Advisory modules.

Standalone helper module (no Streamlit dependency) providing:
  1. get_soil(lat, lon)            — ISRIC SoilGrids v2 soil properties + fertility verdict
  2. crop_advice(prob_pct, soil, temp_c, month)
                                   — Pakistan-specific, bilingual, rule-based agronomy advisory
  3. get_river_levels()            — FFD Pakistan daily bulletin (scraped) +
                                     GloFAS river discharge via Open-Meteo Flood API
  4. satellite_image_url(lat, lon, date_str)
                                   — NASA GIBS WMS true-colour satellite image URL

All functions are pure / cache-friendly and NEVER fabricate data:
on any upstream failure they return an explicit unavailable status.

Live-tested 2026-10-02 (see module docstring notes / PATCH_NOTES_ADVISORY.md).
"""

import re
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 30
_UA = {"User-Agent": "FloodGuardAI/1.0 (advisory module; contact: FloodGuard AI)"}


def _get_json(url, params=None, timeout=_DEFAULT_TIMEOUT):
    r = requests.get(url, params=params, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _get_text(url, timeout=_DEFAULT_TIMEOUT):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.text


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ===========================================================================
# 1. SOIL — ISRIC SoilGrids v2 (free, no key)
# ===========================================================================

# rest.soilgrids.org was unreachable from our network (empty reply);
# rest.isric.org is the official alternate host and works. Keep both.
_SOILGRIDS_HOSTS = [
    "https://rest.isric.org/soilgrids/v2.0",
    "https://rest.soilgrids.org/soilgrids/v2.0",
]

# d_factor converts the raw integer to real units.
_SOIL_PROPERTIES = {
    "phh2o": 10.0,     # pH * 10
    "soc": 10.0,       # soil organic carbon, dg/kg -> g/kg
    "nitrogen": 100.0,  # total nitrogen, cg/kg -> g/kg
    "clay": 10.0,      # g/kg -> %
    "sand": 10.0,      # g/kg -> %
    "silt": 10.0,      # g/kg -> %
}


def _texture_class(clay, sand, silt):
    """Simplified USDA texture triangle."""
    if clay is None or sand is None:
        return None
    if clay >= 40:
        return "Clay"
    if sand >= 85:
        return "Sand"
    if sand >= 70 and clay < 15:
        return "Sandy Loam"
    if silt is not None and silt >= 80:
        return "Silt"
    if clay >= 27 and sand < 45:
        return "Clay Loam"
    if sand >= 50 and clay < 20:
        return "Loamy Sand"
    if silt is not None and silt >= 50 and clay < 27:
        return "Silt Loam"
    if clay >= 20 and sand < 45:
        return "Loam"
    return "Loam"


def get_soil(lat, lon):
    """Fetch topsoil (0-5cm) properties from ISRIC SoilGrids v2.

    Returns dict with pH, soc_gkg, nitrogen_gkg, clay/sand/silt %,
    texture_class, fertility verdict (High/Moderate/Low) + reasoning.
    On failure returns {"status": "unavailable", ...} — never fake numbers.
    """
    params = [("lon", lon), ("lat", lat), ("depth", "0-5cm"), ("value", "mean")]
    for prop in _SOIL_PROPERTIES:
        params.append(("property", prop))

    last_err = None
    for host in _SOILGRIDS_HOSTS:
        try:
            data = _get_json(f"{host}/properties/query", params=params)
            break
        except Exception as e:  # noqa: BLE001 - try next host
            last_err = e
    else:
        return {
            "status": "unavailable",
            "reason": f"SoilGrids unreachable: {last_err}",
            "source": "ISRIC SoilGrids v2",
        }

    try:
        vals = {}
        for layer in data["properties"]["layers"]:
            name = layer["name"]
            mean = layer["depths"][0]["values"]["mean"]
            if mean is None:
                vals[name] = None
            else:
                vals[name] = mean / _SOIL_PROPERTIES[name]

        ph = vals.get("phh2o")
        soc = vals.get("soc")
        nitrogen = vals.get("nitrogen")
        clay, sand, silt = vals.get("clay"), vals.get("sand"), vals.get("silt")
        texture = _texture_class(clay, sand, silt)

        # ---- fertility scoring (arid/semi-arid Punjab-calibrated) ----
        score, notes = 0, []
        if soc is not None:
            if soc >= 10:
                score += 2; notes.append(f"good organic carbon ({soc:.1f} g/kg)")
            elif soc >= 4:
                score += 1; notes.append(f"moderate organic carbon ({soc:.1f} g/kg)")
            else:
                notes.append(f"low organic carbon ({soc:.1f} g/kg)")
        if ph is not None:
            if 6.5 <= ph <= 7.8:
                score += 2; notes.append(f"neutral pH ({ph:.1f})")
            elif 6.0 <= ph <= 8.5:
                score += 1; notes.append(f"acceptable pH ({ph:.1f})")
            else:
                notes.append(f"problematic pH ({ph:.1f})")
        if nitrogen is not None:
            if nitrogen >= 2:
                score += 2; notes.append(f"good nitrogen ({nitrogen:.2f} g/kg)")
            elif nitrogen >= 0.8:
                score += 1; notes.append(f"moderate nitrogen ({nitrogen:.2f} g/kg)")
            else:
                notes.append(f"low nitrogen ({nitrogen:.2f} g/kg)")
        if texture in ("Loam", "Silt Loam", "Clay Loam"):
            score += 1; notes.append(f"favourable {texture.lower()} texture")
        elif texture in ("Sand", "Loamy Sand"):
            notes.append(f"{(texture or 'coarse').lower()} texture drains fast, holds fewer nutrients")

        fertility = "High" if score >= 5 else ("Moderate" if score >= 3 else "Low")

        return {
            "status": "ok",
            "latitude": lat,
            "longitude": lon,
            "depth": "0-5cm",
            "ph": round(ph, 1) if ph is not None else None,
            "soc_gkg": round(soc, 1) if soc is not None else None,
            "nitrogen_gkg": round(nitrogen, 2) if nitrogen is not None else None,
            "clay_pct": round(clay, 1) if clay is not None else None,
            "sand_pct": round(sand, 1) if sand is not None else None,
            "silt_pct": round(silt, 1) if silt is not None else None,
            "texture_class": texture,
            "fertility": fertility,
            "fertility_reason": "; ".join(notes) + ".",
            "source": "ISRIC SoilGrids v2 (modelled, 250m)",
            "fetched_at": _now_iso(),
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "reason": f"Parse error: {e}",
                "source": "ISRIC SoilGrids v2"}


# ===========================================================================
# 2. CROP ADVISORY — Pakistan-specific, bilingual, rule-based
# ===========================================================================

_KHARIF_MONTHS = {4, 5, 6, 7, 8, 9, 10}  # Apr-Oct


def _season(month):
    return "kharif" if month in _KHARIF_MONTHS else "rabi"


def _risk_band(p):
    if p >= 60:
        return "high"
    if p >= 30:
        return "moderate"
    return "low"


# Crop knowledge base: real agronomic guidance for Punjab/Sindh.
# suitability keys resolved per (risk_band, season) below.
_CROPS = {
    "rice_sub1": {
        "crop_en": "Rice — submergence-tolerant varieties (Swarna-Sub1 / IR64-Sub1)",
        "crop_ur": "چاول — زیرِ آب برداشت کرنے والی اقسام (سورنا سب 1)",
        "sowing_tip": "Raise nursery in May–June, transplant in July; Sub1 varieties survive 10–14 days of complete submergence.",
        "sowing_tip_ur": "مئی جون میں پنیری لگائیں، جولائی میں منتقلی کریں؛ سب 1 اقسام 10 سے 14 دن مکمل زیر آب رہ کر بھی بچ جاتی ہیں۔",
    },
    "sugarcane": {
        "crop_en": "Sugarcane",
        "crop_ur": "گنا",
        "sowing_tip": "Plant Feb–Mar (spring) or Sep–Oct (autumn); deep root system tolerates prolonged waterlogging.",
        "sowing_tip_ur": "فروری مارچ (بہاریہ) یا ستمبر اکتوبر (خزاں) میں کاشت کریں؛ گہری جڑیں دیر تک پانی کھڑا رہنے کو برداشت کرتی ہیں۔",
    },
    "dhaincha": {
        "crop_en": "Dhaincha (Sesbania) — green manure",
        "crop_ur": "ڈھینچہ (سبز کھاد)",
        "sowing_tip": "Sow May–July, plough under at 45–50 days; extremely flood-tolerant and rebuilds soil after flood damage.",
        "sowing_tip_ur": "مئی سے جولائی میں بوئیں، 45 سے 50 دن پر زمین میں دبائیں؛ سیلاب کے بعد زمین کی زرخیزی بحال کرنے کا بہترین ذریعہ۔",
    },
    "cotton": {
        "crop_en": "Cotton",
        "crop_ur": "کپاس",
        "sowing_tip": "Sow Apr–May on well-drained, levelled fields only; bolls rot quickly in standing water.",
        "sowing_tip_ur": "صرف اچھی نکاسی والی ہموار زمین میں اپریل مئی میں بوئیں؛ کھڑے پانی میں ٹینڈے گل جاتے ہیں۔",
    },
    "maize": {
        "crop_en": "Maize",
        "crop_ur": "مکئی",
        "sowing_tip": "Sow Jul–Aug (Kharif) or Feb (spring); use raised beds / ridges so roots never sit in water.",
        "sowing_tip_ur": "جولائی اگست (خریف) یا فروری (بہاریہ) میں بوئیں؛ اونچی پٹیوں پر کاشت کریں تاکہ جڑیں پانی میں نہ ڈوبیں۔",
    },
    "mungbean": {
        "crop_en": "Mungbean (short duration 60–70 days)",
        "crop_ur": "مونگ (کم دورانیہ 60 تا 70 دن)",
        "sowing_tip": "Sow June–July; short duration lets the crop escape late-season floods.",
        "sowing_tip_ur": "جون جولائی میں بوئیں؛ کم دورانیہ کی وجہ سے فصل دیر کے سیلاب سے بچ جاتی ہے۔",
    },
    "wheat": {
        "crop_en": "Wheat",
        "crop_ur": "گندم",
        "sowing_tip": "Sow 1–20 Nov; avoid waterlogged patches — use raised beds or delay sowing till field drains.",
        "sowing_tip_ur": "یکم تا 20 نومبر بوائی کریں؛ پانی کھڑا رہنے والے حصوں سے گریز کریں یا نکاسی کے بعد بوائی کریں۔",
    },
    "berseem": {
        "crop_en": "Berseem (fodder)",
        "crop_ur": "برسیم (چارہ)",
        "sowing_tip": "Sow Oct; tolerates wet soils better than most Rabi crops — good fodder option after floods.",
        "sowing_tip_ur": "اکتوبر میں بوئیں؛ گیلی زمین کو زیادہ تر ربیع فصلوں سے بہتر برداشت کرتا ہے۔",
    },
    "mustard": {
        "crop_en": "Mustard / Canola (Sarson)",
        "crop_ur": "سرسوں / رایا",
        "sowing_tip": "Sow Oct; short-duration oilseed, moderate tolerance to residual moisture.",
        "sowing_tip_ur": "اکتوبر میں بوائی کریں؛ کم دورانیہ کی تیل دار فصل، ہلکی نمی برداشت کر لیتی ہے۔",
    },
    "sunflower": {
        "crop_en": "Sunflower",
        "crop_ur": "سورج مکھی",
        "sowing_tip": "Sow Jan–Feb (spring); avoid fields that stay waterlogged.",
        "sowing_tip_ur": "جنوری فروری (بہاریہ) میں بوئیں؛ پانی کھڑا رہنے والی زمین سے گریز کریں۔",
    },
}

# (risk_band, season) -> list of (crop_key, suitability, reason_en, reason_ur)
_ADVISORY_TABLE = {
    ("high", "kharif"): [
        ("rice_sub1", "Highly Recommended",
         "Survives 10–14 days of complete submergence — bred exactly for flood-prone deltas.",
         "10 سے 14 دن مکمل زیر آب رہنے کے باوجود بچ جاتی ہے — سیلاب زدہ علاقوں کے لیے خاص طور پر تیار کردہ قسم۔"),
        ("sugarcane", "Highly Recommended",
         "Deep root system tolerates prolonged waterlogging; crop stands through the flood season.",
         "گہری جڑوں کی وجہ سے دیر تک پانی کھڑا رہنے کو برداشت کرتا ہے؛ فصل سیلاب کے موسم میں قائم رہتی ہے۔"),
        ("dhaincha", "Recommended",
         "Extremely flood-tolerant green manure; ploughing it under restores flood-damaged soil.",
         "نہایت سیلاب برداشت سبز کھاد؛ زمین میں دبانے سے سیلاب زدہ زمین کی زرخیزی بحال ہوتی ہے۔"),
        ("mungbean", "Suitable with caution",
         "Short duration can escape floods, but only on higher, well-drained patches.",
         "کم دورانیہ سیلاب سے بچا سکتا ہے، مگر صرف اونچی اور نکاسی والی زمین میں۔"),
        ("cotton", "Not Recommended",
         "Bolls rot in standing water — near-total loss risk in high flood years.",
         "کھڑے پانی میں ٹینڈے گل جاتے ہیں — زیادہ سیلابی سال میں تقریباً مکمل نقصان کا خطرہ۔"),
        ("maize", "Not Recommended",
         "Extremely sensitive to waterlogging; roots suffocate within 48 hours of standing water.",
         "پانی کھڑا رہنے کے لیے نہایت حساس؛ 48 گھنٹے میں جڑیں گل جاتی ہیں۔"),
    ],
    ("moderate", "kharif"): [
        ("rice_sub1", "Highly Recommended",
         "Short-duration and Sub1 varieties give the best risk-adjusted return under moderate flood threat.",
         "کم دورانیہ اور سب 1 اقسام درمیانے سیلابی خطرے میں بہترین منافع دیتی ہیں۔"),
        ("maize", "Suitable with caution",
         "Grow on raised beds/ridges so a moderate flood event does not drown the root zone.",
         "اونچی پٹیوں پر کاشت کریں تاکہ درمیانہ سیلاب جڑوں کو نہ ڈبوئے۔"),
        ("mungbean", "Recommended",
         "60–70 day crop escapes late-season floods; good contingency crop.",
         "60 سے 70 دن کی فصل دیر کے سیلاب سے بچ جاتی ہے؛ بہترین متبادل فصل۔"),
        ("sugarcane", "Recommended",
         "Safe long-duration option; weathers moderate waterlogging well.",
         "محفوظ طویل دورانیہ فصل؛ درمیانہ پانی کھڑا رہنا برداشت کر لیتی ہے۔"),
        ("cotton", "Suitable with caution",
         "Only on well-drained, slightly elevated fields; keep drainage channels clear.",
         "صرف اچھی نکاسی والی اونچی زمین میں؛ نکاسی نالیاں صاف رکھیں۔"),
    ],
    ("low", "kharif"): [
        ("cotton", "Highly Recommended",
         "Normal conditions — cotton gives the best cash return in Punjab's Kharif belt.",
         "معمول کے حالات — پنجاب کی خریف پٹی میں کپاس بہترین نقد منافع دیتی ہے۔"),
        ("maize", "Highly Recommended",
         "Full yield potential under low flood risk; follow standard sowing calendar.",
         "کم سیلابی خطرے میں بھرپور پیداوار؛ معمول کے کیلنڈر پر بوائی کریں۔"),
        ("rice_sub1", "Recommended",
         "Reliable staple option; standard varieties also fine at low risk.",
         "قابلِ اعتماد فصل؛ کم خطرے میں عام اقسام بھی ٹھیک ہیں۔"),
        ("sugarcane", "Recommended",
         "Steady long-term income where mill access is good.",
         "جہاں شوگر مل کی رسائی ہو، مستحکم طویل مدتی آمدنی۔"),
    ],
    ("high", "rabi"): [
        ("berseem", "Highly Recommended",
         "Tolerates wet, heavy soils better than grain crops — secure fodder after flood season.",
         "گیلی بھاری زمین کو اناج والی فصلوں سے بہتر برداشت کرتا ہے — سیلاب کے بعد محفوظ چارہ۔"),
        ("wheat", "Suitable with caution",
         "Sow only after the field fully drains; use raised beds on low-lying patches.",
         "صرف مکمل نکاسی کے بعد بوائی کریں؛ نشیبی حصوں میں اونچی پٹیاں بنائیں۔"),
        ("mustard", "Suitable with caution",
         "Short duration helps, but avoid plots that stay waterlogged into November.",
         "کم دورانیہ فائدہ مند، مگر نومبر تک پانی کھڑا رہنے والی زمین سے گریز کریں۔"),
    ],
    ("moderate", "rabi"): [
        ("wheat", "Highly Recommended",
         "Standard Rabi staple; ensure field drainage before the November sowing window.",
         "معمول کی ربیع فصل؛ نومبر کی بوائی سے پہلے نکاسی یقینی بنائیں۔"),
        ("mustard", "Recommended",
         "Good oilseed alternative with moderate moisture tolerance.",
         "اچھی تیل دار متبادل فصل، درمیانی نمی برداشت کر لیتی ہے۔"),
        ("berseem", "Recommended",
         "Reliable fodder on residual-moisture fields.",
         "بچی ہوئی نمی والی زمین میں قابلِ اعتماد چارہ۔"),
        ("sunflower", "Suitable",
         "Spring option where drainage is adequate.",
         "بہاریہ متبادل جہاں نکاسی مناسب ہو۔"),
    ],
    ("low", "rabi"): [
        ("wheat", "Highly Recommended",
         "Normal conditions — follow the standard 1–20 Nov sowing window.",
         "معمول کے حالات — یکم تا 20 نومبر کی معیاری بوائی کریں۔"),
        ("mustard", "Recommended",
         "Profitable oilseed break crop in the wheat rotation.",
         "گندم کی گردش میں منافع بخش تیل دار فصل۔"),
        ("sunflower", "Recommended",
         "Good spring cash crop under low risk.",
         "کم خطرے میں اچھی بہاریہ نقد فصل۔"),
        ("berseem", "Suitable",
         "For livestock households needing winter fodder.",
         "مویشی پال گھرانوں کے لیے سرمائی چارہ۔"),
    ],
}


def crop_advice(flood_probability_pct, soil=None, temperature_c=None, month=None):
    """Rule-based, Pakistan-specific crop advisory (bilingual).

    Args:
        flood_probability_pct: 0-100 flood probability from the risk model.
        soil: dict from get_soil() (optional; used for texture/pH tweaks).
        temperature_c: current temperature °C (optional; heat/cold notes).
        month: 1-12 (defaults to current month).

    Returns:
        List of dicts: {crop_en, crop_ur, suitability, reason_en, reason_ur,
        sowing_tip, sowing_tip_ur, season, risk_band}.
    """
    if month is None:
        month = datetime.now().month
    month = max(1, min(12, int(month)))
    p = max(0.0, min(100.0, float(flood_probability_pct or 0)))

    season = _season(month)
    band = _risk_band(p)

    advisories = []
    for key, suitability, reason_en, reason_ur in _ADVISORY_TABLE[(band, season)]:
        c = _CROPS[key]
        advisories.append({
            "crop_en": c["crop_en"],
            "crop_ur": c["crop_ur"],
            "suitability": suitability,
            "reason_en": reason_en,
            "reason_ur": reason_ur,
            "sowing_tip": c["sowing_tip"],
            "sowing_tip_ur": c["sowing_tip_ur"],
            "season": season,
            "risk_band": band,
        })

    # ---- soil-based tweaks ----
    if isinstance(soil, dict) and soil.get("status") == "ok":
        sand = soil.get("sand_pct")
        ph = soil.get("ph")
        if sand is not None and sand > 60:
            advisories.append({
                "crop_en": "Soil note — sandy soil",
                "crop_ur": "زمینی نوٹ — ریتلی زمین",
                "suitability": "Advisory",
                "reason_en": f"Sandy topsoil ({sand:.0f}% sand) drains fast: prefer sugarcane/dhaincha over paddy, and add farmyard manure.",
                "reason_ur": f"ریتلی زمین ({sand:.0f} فیصد ریت) جلد خشک ہوتی ہے: دھان کی بجائے گنے یا ڈھینچہ کو ترجیح دیں اور گوبر کی کھاد ڈالیں۔",
                "sowing_tip": "Apply 8–10 tonnes/acre farmyard manure to improve water retention.",
                "sowing_tip_ur": "پانی روکنے کی صلاحیت بڑھانے کے لیے 8 سے 10 ٹن فی ایکڑ گوبر کی کھاد ڈالیں۔",
                "season": season, "risk_band": band,
            })
        if ph is not None and ph > 8.5:
            advisories.append({
                "crop_en": "Soil note — sodic/alkaline soil",
                "crop_ur": "زمینی نوٹ — کلراٹھی زمین",
                "suitability": "Advisory",
                "reason_en": f"High pH ({ph:.1f}) indicates sodicity: apply gypsum before sowing rice/wheat.",
                "reason_ur": f"زیادہ پی ایچ ({ph:.1f}) کلر کی علامت ہے: دھان یا گندم سے پہلے جپسم ڈالیں۔",
                "sowing_tip": "Get a lab soil test; typical gypsum dose 40–50 kg/acre for mild sodicity.",
                "sowing_tip_ur": "لیبارٹری ٹیسٹ کروائیں؛ ہلکے کلر کے لیے عام طور پر 40 سے 50 کلو جپسم فی ایکڑ۔",
                "season": season, "risk_band": band,
            })

    # ---- temperature notes ----
    if temperature_c is not None:
        try:
            t = float(temperature_c)
            if season == "kharif" and t >= 42:
                advisories.append({
                    "crop_en": "Weather note — extreme heat",
                    "crop_ur": "موسمی نوٹ — شدید گرمی",
                    "suitability": "Advisory",
                    "reason_en": f"{t:.0f}°C stresses young seedlings: irrigate in the evening and mulch nurseries.",
                    "reason_ur": f"{t:.0f} ڈگری سینٹی گریڈ ننھی پنیری کے لیے نقصان دہ: شام کو پانی دیں اور پنیری پر ملچ ڈالیں۔",
                    "sowing_tip": "Delay transplanting to late July if a heatwave persists.",
                    "sowing_tip_ur": "اگر گرمی کی لہر جاری رہے تو منتقلی جولائی کے آخر تک موخر کریں۔",
                    "season": season, "risk_band": band,
                })
            elif season == "rabi" and t <= 5:
                advisories.append({
                    "crop_en": "Weather note — frost risk",
                    "crop_ur": "موسمی نوٹ — کہرے کا خطرہ",
                    "suitability": "Advisory",
                    "reason_en": f"{t:.0f}°C risks frost damage to mustard/potato: light irrigation on frost nights helps.",
                    "reason_ur": f"{t:.0f} ڈگری پر سرسوں اور آلو کو کہرے کا خطرہ: کہرے والی راتوں میں ہلکا پانی فائدہ مند۔",
                    "sowing_tip": "Watch PMD frost advisories in Dec–Jan.",
                    "sowing_tip_ur": "دسمبر جنوری میں محکمہ موسمیات کی کہرے کی پیشگوئی دیکھیں۔",
                    "season": season, "risk_band": band,
                })
        except (TypeError, ValueError):
            pass

    return advisories


# ===========================================================================
# 3. RIVER LEVELS — FFD Pakistan bulletin + GloFAS via Open-Meteo Flood API
# ===========================================================================

FFD_BULLETIN_URL = "https://ffd.pmd.gov.pk/bulletin"
FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"

# Reference barrage points (verified live 2026-10-02; Jhelum/Ravi/Sutlej
# GloFAS cells return ~0 at these coords — reported honestly as no-data).
RIVER_GAUGES = [
    {"river": "Indus", "river_ur": "دریائے سندھ", "site": "Tarbela", "lat": 34.08, "lon": 72.70},
    {"river": "Chenab", "river_ur": "دریائے چناب", "site": "Marala", "lat": 32.65, "lon": 74.45},
    {"river": "Jhelum", "river_ur": "دریائے جہلم", "site": "Mangla", "lat": 33.13, "lon": 73.64},
    {"river": "Ravi", "river_ur": "دریائے راوی", "site": "Balloki", "lat": 31.23, "lon": 73.86},
    {"river": "Sutlej", "river_ur": "دریائے ستلج", "site": "Sulemanki", "lat": 30.38, "lon": 73.87},
    {"river": "Kabul", "river_ur": "دریائے کابل", "site": "Nowshera", "lat": 34.01, "lon": 71.95},
]


def _parse_ffd_bulletin(html):
    """Parse FFD daily bulletin HTML -> dict. Raises ValueError if structure changes."""
    cells = re.findall(
        r'data-ffd="flood-level".*?<strong[^>]*>([A-Z]+)</strong>'
        r'.*?<span data-ffd-label[^>]*>([^<]+)</span>',
        html, re.S,
    )
    if not cells:
        raise ValueError("Rivers-at-a-glance table not found")
    levels = {river.strip().title(): level.strip() for river, level in cells}

    meta = {}
    m = re.search(r"BULLETIN No:\s*([^<]+)</", html)
    if m:
        meta["number"] = m.group(1).strip()
    m = re.search(r'class="meta-dated">Dated:\s*([^<]+)<', html)
    if m:
        meta["dated"] = m.group(1).strip()
    m = re.search(r'class="meta-time">Time:\s*([^<]+)<', html)
    if m:
        meta["time"] = m.group(1).strip()
    m = re.search(r"(DAILY FLOOD BULLETIN[^<]{0,40})", html, re.I)
    if m:
        meta["title"] = m.group(1).strip()
    return {"meta": meta, "levels": levels}


def _glofas_discharge(lat, lon):
    """GloFAS v4 river discharge (m³/s) via Open-Meteo Flood API. No key needed."""
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "river_discharge_mean,river_discharge_median",
        "past_days": 2, "forecast_days": 3, "timezone": "auto",
    }
    data = _get_json(FLOOD_API_URL, params=params)
    daily = data.get("daily", {})
    times = daily.get("time", [])
    mean = daily.get("river_discharge_mean", [])
    median = daily.get("river_discharge_median", [])
    if not times or not mean:
        return None
    today_idx = next((i for i, v in enumerate(mean) if v is not None), None)
    return {
        "dates": times,
        "mean_m3s": mean,
        "median_m3s": median,
        "today_m3s": mean[today_idx] if today_idx is not None else None,
        "elevation_m": data.get("elevation"),
    }


def get_river_levels():
    """Combined river status: official FFD bulletin + GloFAS modelled discharge.

    NEVER fabricates numbers. Any unavailable piece is reported with status
    and the official source link instead.
    """
    out = {
        "status": "ok",
        "fetched_at": _now_iso(),
        "ffd_bulletin": {"status": "unavailable"},
        "glofas": [],
        "sources": [
            FFD_BULLETIN_URL,
            "https://flood-api.open-meteo.com (GloFAS v4 reanalysis)",
            "https://www.globalfloods.eu (official GloFAS viewer)",
        ],
        "disclaimer": ("FFD bulletin is the official qualitative flood status. "
                       "GloFAS values are modelled river discharge (m³/s), not live gauge readings."),
    }

    # --- 1. FFD daily bulletin (official) ---
    try:
        html = _get_text(FFD_BULLETIN_URL)
        parsed = _parse_ffd_bulletin(html)
        out["ffd_bulletin"] = {"status": "ok", **parsed}
    except Exception as e:  # noqa: BLE001
        out["ffd_bulletin"] = {
            "status": "unavailable",
            "reason": f"Could not parse FFD bulletin: {e}",
            "check_manually": FFD_BULLETIN_URL,
        }
        out["status"] = "degraded"

    # --- 2. GloFAS discharge at reference barrages ---
    for g in RIVER_GAUGES:
        try:
            d = _glofas_discharge(g["lat"], g["lon"])
        except Exception as e:  # noqa: BLE001
            d = None
            err = str(e)
        else:
            err = None
        if d is None or d.get("today_m3s") in (None, 0, 0.0):
            out["glofas"].append({
                **g, "discharge_today_m3s": None,
                "note": "No GloFAS river cell at this point" if err is None else f"API error: {err}",
            })
        else:
            out["glofas"].append({
                **g,
                "discharge_today_m3s": round(d["today_m3s"], 1),
                "forecast_3d_m3s": [round(v, 1) if v is not None else None for v in d["mean_m3s"]],
                "forecast_dates": d["dates"],
                "note": "GloFAS modelled discharge",
            })

    if all(x["discharge_today_m3s"] is None for x in out["glofas"]) \
            and out["ffd_bulletin"].get("status") != "ok":
        out["status"] = "unavailable"
    return out


# ===========================================================================
# 4. SATELLITE — NASA GIBS WMS (free, no key)
# ===========================================================================

GIBS_WMS_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
GIBS_LAYERS = {
    "true_color": "MODIS_Terra_CorrectedReflectance_TrueColor",
    "viirs_true_color": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
}


def satellite_image_url(lat, lon, date_str, half_deg=0.25, width=1024, height=1024,
                        layer="true_color"):
    """Build a NASA GIBS WMS GetMap URL (true-colour satellite image).

    Args:
        lat, lon: centre point.
        date_str: "YYYY-MM-DD" (GIBS 'best' supports recent dates).
        half_deg: half-width of the bounding box in degrees.
        width, height: image size in px.
        layer: "true_color" (MODIS Terra) or "viirs_true_color".

    Returns:
        URL string. Raises ValueError on bad input.
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"date_str must be YYYY-MM-DD, got {date_str!r}")
    lat = max(-90.0, min(90.0, float(lat)))
    lon = max(-180.0, min(180.0, float(lon)))
    layer_name = GIBS_LAYERS.get(layer, layer)
    bbox = f"{lat - half_deg},{lon - half_deg},{lat + half_deg},{lon + half_deg}"
    return (
        f"{GIBS_WMS_URL}?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&CRS=EPSG:4326"
        f"&LAYERS={layer_name}"
        f"&BBOX={bbox}&WIDTH={int(width)}&HEIGHT={int(height)}"
        f"&FORMAT=image/jpeg&TIME={date_str}"
    )


if __name__ == "__main__":
    import json as _json

    print("=== 1. get_soil (Multan 30.15, 71.52) ===")
    print(_json.dumps(get_soil(30.15, 71.52), indent=1, ensure_ascii=False))

    print("\n=== 2. crop_advice (high risk, kharif) — first 2 ===")
    adv = crop_advice(72, get_soil(30.15, 71.52), 38, 7)
    print(_json.dumps(adv[:2], indent=1, ensure_ascii=False))
    print("total advisories:", len(adv))

    print("\n=== 3. get_river_levels ===")
    print(_json.dumps(get_river_levels(), indent=1, ensure_ascii=False))

    print("\n=== 4. satellite_image_url ===")
    print(satellite_image_url(30.15, 71.52, "2026-09-25"))
