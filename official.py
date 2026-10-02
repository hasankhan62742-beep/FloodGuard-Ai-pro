"""
FloodGuard AI — Official alerts from NDMA / PDMA (Pakistan).

What is ACTUALLY programmatically accessible (verified 2026-10-02):
  1. NDMA daily monsoon SITREP listing (HTML, static, scrapable):
         https://ndma.gov.pk/sitreps?cat_id=3
     -> 9 latest cards: title ("NDMA - Monsoon 2026 Daily Situation Report
         No. 97"), date, direct PDF URL.
  2. NDMA SITREP PDFs (text-extractable): casualties, house damage by
     district, relief activities, dam levels, river flows, rainfall annexures.
  3. ReliefWeb mirrors of NDMA sitreps (fallback source).
  4. PDMA Punjab daily situation reports page is JS-driven -> best-effort
     only; official links are always returned as fallback.

NEVER fabricates: on any failure returns status "unavailable" with the
official links so the UI can show those instead of numbers.

New pip dep for PDF parsing: pypdf (pure-python, lightweight).
"""

import io
import os
import re
from datetime import datetime, timezone

import requests

_TIMEOUT = 30
_UA = {"User-Agent": "FloodGuardAI/1.0 (official alerts; contact: FloodGuard AI)"}

NDMA_SITREP_LISTING = "https://ndma.gov.pk/sitreps?cat_id=3"
NDMA_HOME = "https://ndma.gov.pk/"
PDMA_PUNJAB_REPORTS = "https://pdma.punjab.gov.pk/daily-situation-reports"
PDMA_PUNJAB_HOME = "https://pdma.punjab.gov.pk/"
FFD_BULLETIN = "https://ffd.pmd.gov.pk/bulletin"

# Compact district gazetteer for affected-district extraction
# (major + flood-prone districts; matching is case-insensitive substring).
DISTRICTS = [
    # South Punjab (priority)
    "Multan", "Muzaffargarh", "Dera Ghazi Khan", "D.G. Khan", "Rajanpur",
    "Rahim Yar Khan", "Bahawalpur", "Bahawalnagar", "Lodhran", "Vehari",
    "Khanewal", "Layyah", "Mianwali", "Bhakkar", "Kot Addu",
    # Rest of Punjab
    "Lahore", "Rawalpindi", "Faisalabad", "Gujranwala", "Sialkot", "Gujrat",
    "Sargodha", "Jhang", "Sahiwal", "Okara", "Kasur", "Sheikhupura",
    "Nankana Sahib", "Chiniot", "Toba Tek Singh", "Pakpattan", "Jhelum",
    "Chakwal", "Attock", "Mandi Bahauddin", "Hafizabad", "Narowal",
    "Khushab", "Wazirabad",
    # Sindh
    "Karachi", "Hyderabad", "Sukkur", "Larkana", "Dadu", "Jamshoro",
    "Badin", "Thatta", "Sujawal", "Mirpurkhas", "Tharparkar", "Umerkot",
    "Sanghar", "Nawabshah", "Shaheed Benazirabad", "Khairpur", "Shikarpur",
    "Jacobabad", "Kashmore", "Qambar Shahdadkot", "Ghotki",
    # KP
    "Peshawar", "Nowshera", "Charsadda", "Swat", "Dir", "Chitral",
    "Mansehra", "Abbottabad", "Haripur", "Mardan", "Swabi", "Kohat",
    "Dera Ismail Khan", "Tank", "Bannu", "Lakki Marwat", "Karak",
    "Shangla", "Battagram", "Kohistan", "Buner", "Malakand", "Bajaur",
    "Mohmand", "Khyber", "Orakzai", "Kurram", "Hangu", "South Waziristan",
    "North Waziristan",
    # Balochistan
    "Quetta", "Turbat", "Kech", "Gwadar", "Lasbela", "Khuzdar", "Jaffarabad",
    "Nasirabad", "Sibi", "Zhob", "Loralai", "Barkhan", "Musakhel",
    "Kohlu", "Dera Bugti", "Awaran", "Panjgur", "Washuk", "Chagai",
    # GB / AJK / ICT
    "Gilgit", "Hunza", "Skardu", "Diamer", "Astore", "Ghizer", "Nagar",
    "Muzaffarabad", "Neelum", "Rawalakot", "Poonch", "Kotli", "Mirpur",
    "Bhimber", "Hattian", "Haveli", "Sudhnoti", "Jhelum Valley",
    "Islamabad",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_text(url, timeout=_TIMEOUT):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.text


def _get_bytes(url, timeout=60):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.content


# ---------------------------------------------------------------------------
# 1. NDMA SITREP listing
# ---------------------------------------------------------------------------

_CARD_RE = re.compile(
    r'<a href="(https://www\.ndma\.gov\.pk//storage/sitrep/[^"]+\.pdf)"'
    r'[^>]*class="sr-card[^"]*">(.*?)</a>', re.S)


def get_ndma_sitreps(limit=5):
    """Scrape NDMA's official situation-report listing.

    Returns (items, status) where items = [{source, title, date, url}].
    status is "ok" or "unavailable: <reason>". NEVER raises.
    """
    try:
        html = _get_text(NDMA_SITREP_LISTING)
    except Exception as e:
        return [], f"unavailable: listing fetch failed ({type(e).__name__})"
    items = []
    for url, inner in _CARD_RE.findall(html):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", inner))
        parts = [p.strip() for p in text.split("|") if p.strip()
                 and p.strip().lower() not in ("view", "latest")]
        title = parts[0] if parts else "NDMA Situation Report"
        date = parts[1] if len(parts) > 1 else ""
        # date sanity: expect like "30 Sep 2026"
        if date and not re.search(r"\d{1,2}\s+\w+\s+\d{4}", date):
            date = ""
        items.append({"source": "NDMA", "title": title, "date": date,
                      "url": url})
        if len(items) >= limit:
            break
    if not items:
        return [], "unavailable: no sitrep cards parsed (page layout changed?)"
    return items, "ok"


# ---------------------------------------------------------------------------
# 2. NDMA SITREP PDF parsing
# ---------------------------------------------------------------------------

def _pdf_text(pdf_bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf not installed (add to requirements.txt)"
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for p in reader.pages[:12]:  # first 12 pages hold the key sections
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                pass
        return "\n".join(pages), "ok"
    except Exception as e:
        return None, f"pdf parse failed ({type(e).__name__})"


def extract_districts(text, max_n=12):
    """Find gazetteer district mentions in sitrep text."""
    found, seen = [], set()
    low = " " + text.lower() + " "
    for d in DISTRICTS:
        key = d.lower()
        if f" {key} " in low or f" {key}," in low or f" {key}:" in low:
            norm = "D.G. Khan" if key in ("d.g. khan", "dera ghazi khan") else d
            if norm not in seen:
                seen.add(norm)
                found.append(norm)
        if len(found) >= max_n:
            break
    return found


def parse_ndma_sitrep_pdf(pdf_url):
    """Download + parse one NDMA SITREP PDF.

    Returns (data, status). data keys: report_no, date, casualties_24h,
    cumulative_deaths, affected_districts, summary, url. NEVER raises.
    """
    try:
        pdf_bytes = _get_bytes(pdf_url)
    except Exception as e:
        return {}, f"unavailable: pdf download failed ({type(e).__name__})"
    text, st = _pdf_text(pdf_bytes)
    if text is None:
        return {}, f"unavailable: {st}"
    data = {"url": pdf_url}
    m = re.search(r"Situation Report No\.\s*(\d+)", text, re.I)
    data["report_no"] = m.group(1) if m else ""
    m = re.search(r"Dated:\s*([0-9]{1,2}\s+\w+\s+20\d{2})", text)
    data["date"] = m.group(1) if m else ""
    # Split 24h vs cumulative sections to avoid cross-matching.
    # "Grand Total" row = Male Female Children Total (deceased) +
    # Male Female Children Total (injured). Separators vary (pipes/spaces).
    sep = r"\s*\|?\s*"
    gt_re = (r"Grand Total" + sep + r"(\d+)" + sep + r"(\d+)" + sep
             + r"(\d+)" + sep + r"(\d+)")
    cut = text.find("Cumulative Casualties")
    seg24, segcum = (text[:cut], text[cut:]) if cut >= 0 else (text, "")
    m = re.search(gt_re, seg24)
    if m:
        data["casualties_24h"] = {
            "deaths": int(m.group(4)),
            "note": "last 24h (deaths total from Grand Total row)"}
    m2 = re.search(gt_re, segcum)
    if m2:
        data["cumulative_deaths"] = int(m2.group(4))
    data["affected_districts"] = extract_districts(text)
    # short summary: first meaningful lines of the house-damage section
    summ = []
    if data.get("casualties_24h"):
        summ.append(f"Last 24h deaths: {data['casualties_24h']['deaths']}")
    if data.get("cumulative_deaths"):
        summ.append(f"Cumulative deaths (season): {data['cumulative_deaths']}")
    if data["affected_districts"]:
        summ.append("Districts mentioned: "
                    + ", ".join(data["affected_districts"][:8]))
    data["summary"] = " | ".join(summ) if summ else "Daily situation report"
    return data, "ok"


# ---------------------------------------------------------------------------
# 3. PDMA Punjab (best-effort — listing is JS-driven)
# ---------------------------------------------------------------------------

def get_pdma_punjab_latest():
    """Best-effort PDMA Punjab daily report discovery.

    The listing page is JS-driven, so static scraping usually finds nothing.
    Returns (items, status); status explains the limitation honestly.
    """
    try:
        html = _get_text(PDMA_PUNJAB_REPORTS, timeout=20)
    except Exception as e:
        return [], f"unavailable: page fetch failed ({type(e).__name__})"
    pdfs = re.findall(r'href="([^"]+\.pdf[^"]*)"', html)
    items = [{"source": "PDMA Punjab", "title": "Daily Situation Report (PDF)",
              "date": "", "url": u if u.startswith("http")
              else "https://pdma.punjab.gov.pk" + u}
             for u in pdfs[:3]]
    if items:
        return items, "ok"
    return [], ("unavailable: PDMA Punjab listing is JavaScript-driven; "
                "open the official page manually")


# ---------------------------------------------------------------------------
# 4. Combined feed
# ---------------------------------------------------------------------------

OFFICIAL_LINKS = [
    ("NDMA Situation Reports", NDMA_SITREP_LISTING),
    ("NDMA Website", NDMA_HOME),
    ("PDMA Punjab Daily Reports", PDMA_PUNJAB_REPORTS),
    ("PDMA Punjab", PDMA_PUNJAB_HOME),
    ("FFD Flood Bulletin (Lahore)", FFD_BULLETIN),
    ("NDMA WhatsApp", "https://wa.me/923000881641"),
]


def get_official_alerts(limit=5, parse_latest_pdf=True):
    """Combined official feed for the app's 🏛️ section.

    Returns dict:
      {items: [{source,title,date,summary,url}], latest_sitrep: {...}|None,
       status: "ok" | "partial" | "unavailable",
       notice: str, links: [(label, url)]}

    NEVER raises and NEVER fabricates: every item comes from a live fetch.
    """
    items, latest = [], None
    notices = []
    sitreps, st = get_ndma_sitreps(limit=limit)
    if st == "ok":
        for s in sitreps:
            items.append({"source": s["source"], "title": s["title"],
                          "date": s["date"], "summary": "",
                          "url": s["url"]})
        if parse_latest_pdf and sitreps:
            data, pst = parse_ndma_sitrep_pdf(sitreps[0]["url"])
            if pst == "ok":
                latest = data
                items[0]["summary"] = data.get("summary", "")
            else:
                notices.append(f"Latest PDF parse: {pst}")
    else:
        notices.append(f"NDMA listing: {st}")
    p_items, pst = get_pdma_punjab_latest()
    if pst == "ok":
        items.extend(p_items)
    else:
        notices.append(f"PDMA Punjab: {pst}")

    if items:
        status = "ok" if not notices else "partial"
    else:
        status = "unavailable"
        notices.append("No official items could be fetched right now.")
    return {"items": items, "latest_sitrep": latest, "status": status,
            "notice": " ".join(notices),
            "links": OFFICIAL_LINKS}
