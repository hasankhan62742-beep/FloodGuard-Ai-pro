"""voice.py — Urdu voice readout of a flood-risk result (gTTS, free, no key).

speak_urdu(text) -> BytesIO (MP3) or None on any failure.
build_result_speech(village, risk_pct, band) -> Urdu summary string.
Self-contained: no streamlit import at module level.
"""

import io

BAND_UR = {"Low": "کم خطرہ", "Moderate": "درمیانہ خطرہ", "High": "زیادہ خطرہ"}


def build_result_speech(village, risk_pct, band):
    """Compose a 2-3 sentence Urdu summary of the result."""
    band = band if band in BAND_UR else "Moderate"
    try:
        pct = float(risk_pct)
    except Exception:
        pct = 0.0
    pct = max(0.0, min(100.0, pct))
    v = str(village)[:60] if village else "آپ کا علاقہ"

    if band == "High":
        advice = ("احتیاط کریں، نشیبی علاقوں سے دور رہیں، اور PDMA کی ہدایات پر عمل کریں۔")
    elif band == "Moderate":
        advice = ("موسم پر نظر رکھیں اور مقامی انتظامیہ کی ہدایات پر عمل کریں۔")
    else:
        advice = ("فی الحال صورتحال بہتر ہے، پھر بھی موسم کی خبر سنتے رہیں۔")

    return (f"فلڈ گارڈ اے آئی رپورٹ۔ {v} میں سیلاب کا خطرہ {pct:.0f} فیصد ہے، "
            f"یعنی {BAND_UR[band]}۔ {advice}")


def speak_urdu(text):
    """Text -> MP3 BytesIO via gTTS (lang='ur'). Returns None on failure."""
    if not text or not str(text).strip():
        return None
    try:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(text=str(text)[:1500], lang="ur").write_to_fp(buf)
        buf.seek(0)
        return buf if buf.getbuffer().nbytes > 1000 else None
    except Exception:
        return None


def render_voice_result(village, risk_pct, band, T):
    """Streamlit section: Urdu voice readout. Safe to call from app.py."""
    import streamlit as st

    st.markdown(
        f'<div class="fg-card"><h3 style="margin-top:0">{T["voice_title"]}</h3>',
        unsafe_allow_html=True)
    speech = build_result_speech(village, risk_pct, band)
    st.write(speech)
    with st.spinner(T.get("loading", "Loading...")):
        audio = speak_urdu(speech)
    if audio is not None:
        st.audio(audio, format="audio/mp3")
    else:
        st.info(T["voice_unavailable"])
    st.markdown("</div>", unsafe_allow_html=True)
