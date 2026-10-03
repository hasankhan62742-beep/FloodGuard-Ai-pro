"""gps_button_component.py — a fully-controlled "Use My Location" button.

Why a custom component instead of streamlit-geolocation?
- The package renders a tiny 🎯 whose clicks users miss, has NO timeout
  (a failed fix hangs forever with no message), and gives no hint when the
  browser permission was denied earlier.
- This component renders a big, clear button, calls getCurrentPosition with
  a 15-second timeout, reports the browser permission state on load, and
  shows exact guidance (allow location / turn on location services).

The frontend is embedded as strings and written to disk on first import, so
deploying needs only this .py file — no npm build, no extra uploads.
"""

import os
import tempfile

import streamlit.components.v1 as components

# --- minimal Streamlit component protocol (no npm build needed) ---
_STREAMLIT_JS = """\
(function () {
  function sendBackMsg(type, data) {
    var msg = Object.assign({ isStreamlitMessage: true, type: type }, data || {});
    window.parent.postMessage(msg, "*");
  }
  function getDataType(v) {
    if (typeof v === "string") return "string";
    if (typeof v === "number") return "number";
    if (typeof v === "boolean") return "boolean";
    return "json";
  }
  var renderListeners = [];
  var Streamlit = {
    RENDER_EVENT: "streamlit:render",
    events: {
      addEventListener: function (t, cb) {
        if (t === Streamlit.RENDER_EVENT) renderListeners.push(cb);
      },
    },
    setComponentReady: function () {
      sendBackMsg("streamlit:componentReady", { apiVersion: 1 });
    },
    setFrameHeight: function (h) {
      sendBackMsg("streamlit:setFrameHeight", {
        height: h === undefined ? document.body.scrollHeight : h,
      });
    },
    setComponentValue: function (v) {
      sendBackMsg("streamlit:setComponentValue", {
        value: v,
        dataType: getDataType(v),
      });
    },
  };
  window.addEventListener("message", function (e) {
    var d = e.data || {};
    if (d.isStreamlitMessage && d.type === Streamlit.RENDER_EVENT) {
      renderListeners.forEach(function (cb) { cb({ detail: d }); });
    }
  });
  window.Streamlit = Streamlit;
})();
"""

_INDEX_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  html, body { margin: 0; padding: 0; background: transparent; }
  body { font-family: -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; }
  #gpsbtn {
    display: flex; align-items: center; justify-content: center; gap: 8px;
    width: 100%; padding: 11px 14px; font-size: 15px; font-weight: 700;
    color: #fff; background: linear-gradient(135deg, #0b6fa4, #0891b2);
    border: none; border-radius: 10px; cursor: pointer;
    box-shadow: 0 2px 6px rgba(8, 145, 178, 0.35);
  }
  #gpsbtn:active { transform: scale(0.98); }
  #gpsbtn:disabled { opacity: 0.65; cursor: wait; }
  #gpsstatus { margin-top: 6px; font-size: 12.5px; line-height: 1.45; color: #444; min-height: 18px; }
</style>
</head>
<body>
<button id="gpsbtn">📍 Use My Location</button>
<div id="gpsstatus"></div>
<script src="./streamlit.js"></script>
<script>
(function () {
  var btn = document.getElementById("gpsbtn");
  var st = document.getElementById("gpsstatus");
  var S = {
    button: "📍 Use My Location",
    locating: "⏳ Locating… (tap Allow if your browser asks)",
    denied: "❌ Location is blocked for this site. Tap the 🔒 icon in the address bar → Permissions → Location → Allow, then tap the button again.",
    unavailable: "❌ Position unavailable — please turn ON location services (GPS) on your device and try again.",
    timeout: "⏰ Timed out — try again, or tap your place on the map below.",
    nosupport: "❌ This browser has no location support — please use the map below.",
    found: "✅ Location found!"
  };
  function say(t) { st.textContent = t; Streamlit.setFrameHeight(); }
  function send(v) { Streamlit.setComponentValue(v); }

  function applyArgs(args) {
    if (!args) return;
    ["button", "locating", "denied", "unavailable", "timeout", "nosupport", "found"].forEach(function (k) {
      if (typeof args[k] === "string") S[k] = args[k];
    });
    btn.textContent = S.button;
    Streamlit.setFrameHeight();
  }

  function reportPermission() {
    try {
      if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({ name: "geolocation" }).then(function (r) {
          send({ event: "perm", state: r.state });
          if (r.state === "denied") say(S.denied);
          r.onchange = function () { send({ event: "perm", state: r.state }); };
        }).catch(function () { /* ignore */ });
      } else {
        send({ event: "perm", state: "unknown" });
      }
    } catch (e) { /* ignore */ }
  }

  btn.addEventListener("click", function () {
    btn.disabled = true;
    say(S.locating);
    send({ event: "start" });
    if (!navigator.geolocation) {
      say(S.nosupport);
      btn.disabled = false;
      send({ event: "error", code: 0 });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      function (p) {
        btn.disabled = false;
        say(S.found);
        send({
          event: "fix",
          lat: p.coords.latitude,
          lon: p.coords.longitude,
          acc: p.coords.accuracy
        });
      },
      function (e) {
        btn.disabled = false;
        var msg = S.unavailable;
        if (e.code === 1) msg = S.denied;
        else if (e.code === 3) msg = S.timeout;
        say(msg);
        send({ event: "error", code: e.code });
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
    );
  });

  Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, function (ev) {
    applyArgs(ev.detail && ev.detail.args);
  });
  Streamlit.setComponentReady();
  applyArgs(null);
  Streamlit.setFrameHeight();
  reportPermission();
})();
</script>
</body>
</html>
"""


def _component_dir():
    """Directory holding the frontend files (written on first import)."""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(base, "gps_button")
        os.makedirs(d, exist_ok=True)
        test = os.path.join(d, ".writetest")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
    except Exception:
        d = os.path.join(tempfile.gettempdir(), "floodguard_gps_button")
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "streamlit.js"), "w", encoding="utf-8") as f:
        f.write(_STREAMLIT_JS)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(_INDEX_HTML)
    return d


_component = components.declare_component("floodguard_gps_button",
                                           path=_component_dir())


def gps_button(T, key="gps_btn"):
    """Render the GPS button. Returns a dict like
    {'event': 'fix', 'lat': .., 'lon': .., 'acc': ..} on a fresh fix,
    {'event': 'error'|'perm'|'start', ...} otherwise, or None.
    """
    return _component(
        key=key,
        default=None,
        button=T.get("gps_btn_label", "📍 Use My Location"),
        locating=T.get("gps_locating",
                       "⏳ Locating… (tap Allow if your browser asks)"),
        denied=T.get("gps_denied_msg",
                     "❌ Location is blocked for this site. Tap the 🔒 icon "
                     "in the address bar → Permissions → Location → Allow, "
                     "then tap the button again."),
        unavailable=T.get("gps_unavailable_msg",
                          "❌ Position unavailable — please turn ON location "
                          "services (GPS) on your device and try again."),
        timeout=T.get("gps_timeout_msg",
                      "⏰ Timed out — try again, or tap your place on the map below."),
        nosupport=T.get("gps_nosupport_msg",
                        "❌ This browser has no location support — please use "
                        "the map below."),
        found=T.get("gps_found_msg", "✅ Location found!"),
    )
