"""dashboard.py — District Risk Dashboard (folium circle-marker map + top-10 table).

Reads district_risk.csv (built by build_districts.py). Self-contained:
no streamlit import at module level; render_district_dashboard(T) is the
streamlit entry point for the integrator.
"""

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "district_risk.csv")

BAND_COLORS = {"Low": "#2ecc71", "Moderate": "#f1c40f", "High": "#e74c3c"}
BAND_UR = {"Low": "کم", "Moderate": "درمیانہ", "High": "زیادہ"}


def load_district_risk(path=CSV_PATH):
    """Load the build-time district risk table. Returns DataFrame or None."""
    try:
        df = pd.read_csv(path)
        if df.empty or "risk_pct" not in df.columns:
            return None
        return df
    except Exception:
        return None


def get_top_districts(n=10, path=CSV_PATH):
    """Top-n riskiest districts as a DataFrame (district, province, risk)."""
    df = load_district_risk(path)
    if df is None:
        return None
    return df.sort_values("risk_pct", ascending=False).head(n)[
        ["district", "province", "risk_pct", "band"]].reset_index(drop=True)


def build_district_map(df=None, path=CSV_PATH):
    """Build a folium map with one circle marker per district.

    Color: band (green/yellow/red). Radius scales with risk. Returns a
    folium.Map, or None if folium/data unavailable.
    """
    try:
        import folium
    except Exception:
        return None
    if df is None:
        df = load_district_risk(path)
    if df is None or df.empty:
        return None

    m = folium.Map(location=[30.0, 69.8], zoom_start=5,
                   tiles="OpenStreetMap", control_scale=True)
    for _, r in df.iterrows():
        try:
            lat, lon, pct = float(r["lat"]), float(r["lon"]), float(r["risk_pct"])
        except Exception:
            continue
        band = r.get("band", "Moderate")
        color = BAND_COLORS.get(band, "#95a5a6")
        folium.CircleMarker(
            location=[lat, lon],
            radius=5 + pct / 100 * 14,
            color=color, weight=2, fill=True, fill_color=color,
            fill_opacity=0.55,
            popup=folium.Popup(
                f"<b>{r['district']}</b> ({r.get('province', '')})<br>"
                f"Flood risk: <b>{pct:.1f}%</b> — {band}",
                max_width=220),
            tooltip=f"{r['district']}: {pct:.1f}%",
        ).add_to(m)

    # legend
    legend = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:10px 14px;border-radius:8px;
                box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:13px">
      <b>District flood risk</b><br>
      <span style="color:#2ecc71">●</span> Low (&lt;30%)<br>
      <span style="color:#f1c40f">●</span> Moderate (30–60%)<br>
      <span style="color:#e74c3c">●</span> High (≥60%)
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    return m


def render_district_dashboard(T):
    """Streamlit section: national district dashboard. Safe to call from app.py."""
    import streamlit as st

    st.markdown(
        f'<div class="fg-card"><h3 style="margin-top:0">{T["dash_title"]}</h3>',
        unsafe_allow_html=True)
    df = load_district_risk()
    if df is None:
        st.info(T["dash_unavailable"])
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.caption(T["dash_sub"].format(n=len(df)))
    try:
        from streamlit_folium import st_folium

        fmap = build_district_map(df)
        if fmap is not None:
            st_folium(fmap, width=700, height=480)
        else:
            st.info(T["dash_unavailable"])
    except Exception:
        st.info(T["dash_unavailable"])

    st.subheader(T["dash_top10"])
    top = get_top_districts(10)
    if top is not None:
        st.table(top.rename(columns={
            "district": T.get("col_district", "District"),
            "province": T.get("col_province", "Province"),
            "risk_pct": T.get("col_risk", "Risk %"),
            "band": T.get("col_band", "Band"),
        }))
    st.caption(T["dash_note"])
    st.markdown("</div>", unsafe_allow_html=True)
