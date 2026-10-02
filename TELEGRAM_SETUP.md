# 🗣️ Telegram Community Reports — Setup Guide (5 minute, FREE)

FloodGuard ke users apne elaqay mein **paani jama hone / selab ki live report**
bhej sakein — jo seedha Telegram channel par post hogi aur app ke map par
nazar aayegi. Koi kharcha nahi.

---

## Step 1 — Bot banayein (BotFather)

1. Telegram kholein aur **@BotFather** search kar ke chat kholein
2. Bhejein: `/newbot`
3. Bot ka naam likhein, masalan: `FloodGuard Reports`
4. Username likhein (akhir mein `bot` hona chahiye), masalan: `floodguard_reports_bot`
5. BotFather aapko **HTTP API token** dega — ye save kar lein:
   ```
   1234567890:AAH... (lambi string)
   ```
   > ⚠️ Ye token **secret** hai — kisi ko na dein, GitHub par public na karein.

## Step 2 — Channel banayein aur bot ko admin banayein

1. Telegram mein **New Channel** banayein, naam: `FloodGuard Flood Reports`
2. Channel ko **Public** rakhein (taake log reports dekh sakein) ya Private (sirf app ke liye)
3. Channel kholein → naam par tap → **Administrators → Add Admin** → apna bot search kar ke add karein
4. Bot ko **"Post Messages"** ka permission dein (baqi sab off kar sakte hain)

## Step 3 — Chat ID nikalein

1. Channel mein aik test message bhejein (kuch bhi, masalan "test")
2. Browser mein ye kholein (TOKEN ki jagah apna token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Jo JSON aaye us mein dhoondein:
   ```json
   "chat": { "id": -1001234567890, "title": "FloodGuard Flood Reports", ... }
   ```
4. Ye **chat id** (minus sign ke sath, masalan `-1001234567890`) save kar lein.

> 💡 Agar `getUpdates` khaali aaye to channel mein dobara message bhejein aur phir kholein.

## Step 4 — Streamlit Secrets mein dalna

Streamlit Cloud → apni app → **Settings → Secrets** mein ye likhein:

```toml
TELEGRAM_BOT_TOKEN = "1234567890:AAH...aapka-token"
TELEGRAM_CHAT_ID = "-1001234567890"
```

**Save** dabayein — app khud reboot ho jayegi.

> 🖥️ Local testing ke liye: terminal mein ye env vars set karein:
> ```
> export TELEGRAM_BOT_TOKEN="..."
> export TELEGRAM_CHAT_ID="..."
> ```

## Step 5 — Test karein

1. App mein **"🗣️ Community Reports"** section kholein
2. Severity select kar ke test report bhejein
3. Telegram channel mein report nazar aani chahiye ✅
4. App ka map refresh karne par wahan **marker** lag jayega ✅

---

## Kaise kaam karta hai? (mukhtasar)

- Report bhejne par app Telegram Bot API ko message bhejti hai — text mein
  machine-readable code hota hai (`FLOODREPORT|lat|lon|...`) taake app usay
  wapas parh kar map par laga sake.
- Koi database nahi chahiye — Telegram hi "database" hai (muft!).
- `getUpdates` pichle ~100 messages dekhta hai, is liye **taaza tareen**
  reports hi map par aati hain. Zyada purani reports ke liye channel khud
  archive ka kaam karta hai.
