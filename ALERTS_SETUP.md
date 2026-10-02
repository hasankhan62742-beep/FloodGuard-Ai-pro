# 📲 FloodGuard Alerts — Setup Guide (5–10 minute)

Ye guide aapko FloodGuard ke **WhatsApp + Email alerts** chalu karne mein madad karegi.
Koi coding nahi — sirf 3 cheezein chahiye:

1. **CallMeBot API key** (free WhatsApp messages ke liye)
2. **Gmail App Password** (alert emails ke liye)
3. **GitHub Secrets** mein ye dalna (taake daily automatic check chale)

---

## Step 1 — CallMeBot WhatsApp API key (FREE)

> ⚠️ Zaroori: CallMeBot **sirf un numbers par message bhej sakta hai jinhon ne pehle opt-in kiya ho.**
> Har subscriber ko **aik dafa** ye karna parega (neeche Step 1b).

**1a. API key lena:**
1. Apne phone ke contacts mein ye number save karein: **+34 694 24 25 62**
   (naam kuch bhi rakhein, masalan "CallMeBot")
2. WhatsApp par us contact ko ye exact message bhejein:
   `I allow callmebot to send me messages`
3. 2 minute ke andar jawab mein aapko **apikey** milegi (masalan `123456`). Ye save kar lein.
   > Agar 2 minute mein jawab na aaye to 24 ghante baad dobara try karein (official hidayat).

**1b. Subscriber opt-in (har user ke liye, sirf aik dafa):**
- Har kisan/user ko bhi upar wala message **+34 694 24 25 62** par bhejna parega,
  warna unko WhatsApp alert nahi jayega.
- Ye WhatsApp ki policy hai (spam rokne ke liye) — iska koi hal nahi.

**Free limit:** CallMeBot free tier mein rozana taqreeban 30–50 messages deta hai.
Zyada subscribers hon to Twilio (paid) par shift karein.

---

## Step 2 — Gmail App Password (email alerts ke liye)

1. Apne Gmail account mein jayein → **Google Account → Security**
2. **2-Step Verification ON** karein (agar pehle se on nahi)
3. Phir **Security → App passwords** par click karein
4. App ka naam likhein: `FloodGuard` → **Create**
5. 16-huroof ka password milega (masalan `abcd efgh ijkl mnop`) — **ye copy kar lein.**
   > ⚠️ Ye aapka Gmail login password NAHI hai — ye alag "app password" hai.

---

## Step 3 — GitHub Secrets mein dalna

1. GitHub par apna repo kholein: `FloodGuard-Ai-pro`
2. **Settings → Secrets and variables → Actions → New repository secret**
3. Ye 3 secrets aik-aik kar ke banayein:

| Secret ka naam       | Value (kya dalein)                        |
|----------------------|-------------------------------------------|
| `CALLMEBOT_APIKEY`   | Step 1a wali apikey                        |
| `ALERT_SMTP_USER`    | Aapka Gmail address (masalan `aap@gmail.com`) |
| `ALERT_SMTP_PASS`    | Step 2 wala 16-huroof app password         |

4. (Optional) `ALERT_THRESHOLD` naam ka secret banayein agar 60% se mukhtalif
   threshold chahiye (masalan `70`).

---

## Step 4 — Workflow enable karna

1. GitHub repo → **Actions** tab kholein
2. Agar "Workflows aren't being run on this forked repository" jesa message aaye to
   **"I understand my workflows, go ahead and enable them"** dabayein
3. Left side mein **"FloodGuard daily alerts"** nazar aayega
4. **Test karne ke liye:** workflow par click → **"Run workflow"** → **"Run workflow"**
   (ye foran check chala dega, roz 06:00 PKT ka intezar nahi karna parega)
5. Run ke baad **"Upload alert log"** artifact mein `alerts_log.csv` download kar ke
   dekh sakte hain ke kis ko alert gaya.

---

## App mein subscriber kaise banein?

Streamlit app mein **"📲 Flood Alerts"** section mein:
- Naam + WhatsApp number (country code ke sath, masalan `923001234567`) ya Email
- **"Subscribe"** dabayein — bas!

Jab aapke gaon ka flood risk **60% ya zyada** hoga to roz subah 06:00 PKT
automatic alert aa jayega (Urdu ya English — jo language app mein select ho).

---

## Production note (zaroori)

- `alerts_subscribers.csv` **Streamlit Cloud par ephemeral hai** — app reboot/redeploy
  par wipe ho sakti hai. Public launch se pehle subscribers ko **Google Sheet**
  ya **Supabase** (free) mein shift karein — `subscribe_alert()` mein sirf
  storage layer badalna parega, baqi code same rahega.
- **Anti-spam:** aik user ko 48 ghante mein dobara alert nahi jata (jab tak risk
  10 points na barh jaye).
