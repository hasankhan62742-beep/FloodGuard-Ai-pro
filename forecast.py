"""forecast.py — 7-day rainfall forecast (Open-Meteo, free, no key).

Self-contained: no streamlit import at module level. The integrator calls
render_7day_forecast(lat, lon, T) from app.py.
"""

import requests

try:
    import plotly.graph_objects as go
except Exception:  # pragma: no cover
    go = None


def get_7day_forecast(lat, lon):
    """Fetch 7-day daily forecast.

    Returns dict with status 'ok' and lists: dates, precip_mm,
    prob_pct (max precipitation probability), tmax_c. On failure returns
    {'status': 'unavailable', 'reason': ...}. Never raises.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": round(float(lat), 4),
                "longitude": round(float(lon), 4),
                "daily": "precipitation_sum,precipitation_probability_max,"
                         "temperature_2m_max,temperature_2m_min,weathercode",
                "forecast_days": 7,
                "timezone": "auto",
            },
            timeout=20,
        )
        r.raise_for_status()
        d = r.json().get("daily", {})
        dates = d.get("time", [])
        if not dates:
            return {"status": "unavailable", "reason": "empty response"}
        return {
            "status": "ok",
            "dates": dates,
            "precip_mm": [float(x) if x is not None else 0.0
                          for x in d.get("precipitation_sum", [])],
            "prob_pct": [float(x) if x is not None else 0.0
                         for x in d.get("precipitation_probability_max", [])],
            "tmax_c": [float(x) if x is not None else None
                       for x in d.get("temperature_2m_max", [])],
            "tmin_c": [float(x) if x is not None else None
                       for x in d.get("temperature_2m_min", [])],
            "source": "Open-Meteo (free, no key)",
        }
    except Exception as e:  # never break the app
        return {"status": "unavailable", "reason": str(e)[:120]}


def render_7day_chart(fc):
    """Build a plotly bar (rain mm) + line (probability %) figure.

    fc: dict from get_7day_forecast with status 'ok'. Returns a
    plotly Figure, or None if plotly/fc unavailable.
    """
    if go is None or fc.get("status") != "ok":
        return None
    dates = fc["dates"]
    labels = [d[5:] for d in dates]  # MM-DD
    fig = go.Figure()
    fig.add_bar(
        x=labels, y=fc["precip_mm"], name="Rain (mm)",
        marker_color="#3498db", yaxis="y",
        hovertemplate="%{x}: %{y:.1f} mm<extra></extra>",
    )
    fig.add_trace(go.Scatter(
        x=labels, y=fc["prob_pct"], name="Rain probability (%)",
        mode="lines+markers", line={"color": "#e74c3c", "width": 2},
        yaxis="y2",
        hovertemplate="%{x}: %{y:.0f}%<extra></extra>",
    ))
    fig.update_layout(
        title="7-day rainfall outlook",
        xaxis_title="Date (MM-DD)",
        yaxis={"title": "Rain (mm)", "side": "left"},
        yaxis2={"title": "Probability (%)", "side": "right",
                "overlaying": "y", "range": [0, 105]},
        legend={"orientation": "h", "y": 1.12},
        margin={"t": 60, "b": 40, "l": 40, "r": 40},
        height=340,
        template="plotly_white",
    )
    return fig


def render_7day_forecast(lat, lon, T):
    """Streamlit section: 7-day forecast chart. Safe to call from app.py."""
    import streamlit as st

    st.markdown(
        f'<div class="fg-card"><h3 style="margin-top:0">{T["fc_title"]}</h3>',
        unsafe_allow_html=True)
    with st.spinner(T.get("loading", "Loading...")):
        fc = get_7day_forecast(lat, lon)
    if fc.get("status") == "ok":
        fig = render_7day_chart(fc)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        total = sum(fc["precip_mm"])
        mx = max(fc["prob_pct"]) if fc["prob_pct"] else 0
        st.caption(f"{T['fc_total']}: {total:.1f} mm · "
                   f"{T['fc_maxprob']}: {mx:.0f}% · {fc['source']}")
        if total >= 50:
            st.warning(T["fc_heavy"])
    else:
        st.info(T["fc_unavailable"])
    st.markdown("</div>", unsafe_allow_html=True)
