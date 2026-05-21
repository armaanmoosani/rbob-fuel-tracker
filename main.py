import os
import sys
import base64
import smtplib
from email.mime.text import MIMEText
import requests
from datetime import datetime
import pytz
from base64 import b64encode
from nacl import encoding, public

# --- Environment Variables ---
SCHWAB_APP_KEY = os.environ['SCHWAB_APP_KEY']
SCHWAB_APP_SECRET = os.environ['SCHWAB_APP_SECRET']
SCHWAB_REFRESH_TOKEN = os.environ['SCHWAB_REFRESH_TOKEN']
GH_PAT = os.environ['GH_PAT']
GH_REPO = os.environ['GH_REPO']
GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
TO_EMAIL = os.environ['TO_EMAIL']


def send_vip_email(subject, body):
    """Send an alert email via Gmail SMTP."""
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = GMAIL_USER
        msg['To'] = TO_EMAIL
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        server.quit()
        print(f"✅ Email sent: {subject}")
    except Exception as e:
        print(f"❌ Email send failed: {e}")


def update_github_secret(new_refresh_token):
    """Encrypt and update the SCHWAB_REFRESH_TOKEN in GitHub Secrets."""
    headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json"}
    key_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    res = requests.get(key_url, headers=headers)
    res.raise_for_status()
    key_data = res.json()
    key = public.PublicKey(key_data['key'].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(key)
    encrypted = b64encode(sealed_box.encrypt(new_refresh_token.encode("utf-8"))).decode("utf-8")
    put_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/SCHWAB_REFRESH_TOKEN"
    put_res = requests.put(put_url, headers=headers, json={"encrypted_value": encrypted, "key_id": key_data['key_id']})
    put_res.raise_for_status()
    print("✅ GitHub secret updated successfully")


# --- Weekend / Market Hours Guard ---
tz = pytz.timezone('America/Chicago')
now = datetime.now(tz)
weekday = now.weekday()  # 0=Mon, 5=Sat, 6=Sun

if weekday == 5:  # Saturday — market closed all day
    print("📅 Saturday — /RB market closed. Exiting.")
    sys.exit(0)
if weekday == 6 and now.hour < 17:  # Sunday before 5 PM CT — still closed
    print("📅 Sunday before market open (5:00 PM CT). Exiting.")
    sys.exit(0)

# --- OAuth Token Refresh (using officially documented Basic Auth method) ---
auth_url = "https://api.schwabapi.com/v1/oauth/token"
auth_header = base64.b64encode(f"{SCHWAB_APP_KEY}:{SCHWAB_APP_SECRET}".encode()).decode()
auth_data = {
    "grant_type": "refresh_token",
    "refresh_token": SCHWAB_REFRESH_TOKEN
}
try:
    auth_res = requests.post(
        auth_url,
        data=auth_data,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    auth_res.raise_for_status()
    auth_json = auth_res.json()
    access_token = auth_json['access_token']
    new_refresh_token = auth_json['refresh_token']
    print("✅ Schwab OAuth token refreshed")
except Exception as e:
    send_vip_email(
        "🚨 EMERGENCY: RBOB Tracker Auth Failed!",
        f"OAuth token refresh failed — the tracker is DOWN.\n\n"
        f"Error: {e}\n\n"
        f"ACTION REQUIRED: Re-authenticate at developer.schwab.com and update SCHWAB_REFRESH_TOKEN in GitHub Secrets."
    )
    print(f"❌ FATAL: OAuth refresh failed: {e}")
    sys.exit(1)

# --- Store New Token BEFORE doing anything else ---
# CRITICAL: old token is now invalid. If this step fails, the system breaks permanently.
try:
    update_github_secret(new_refresh_token)
except Exception as e:
    send_vip_email(
        "🚨 EMERGENCY: GitHub Secret Update Failed!",
        f"New Schwab token was obtained but FAILED to save to GitHub Secrets.\n\n"
        f"Error: {e}\n\n"
        f"⚠️ The tracker WILL break on the next run. Manually update SCHWAB_REFRESH_TOKEN in GitHub Secrets immediately."
    )
    print(f"❌ FATAL: GitHub secret update failed: {e}")
    sys.exit(1)

# --- Fetch Live /RB Market Data ---
try:
    api_headers = {"Authorization": f"Bearer {access_token}"}
    quote_url = "https://api.schwabapi.com/marketdata/v1/quotes?symbols=/RB"
    quote_res = requests.get(quote_url, headers=api_headers)
    quote_res.raise_for_status()
    quote_data = quote_res.json()
    rb_data = quote_data['/RB']['quote']
    current_price = rb_data['lastPrice']
    open_price = rb_data['openPrice']
except Exception as e:
    print(f"❌ Market data fetch failed: {e}")
    sys.exit(1)

# --- Calculate Daily Change (with division-by-zero guard) ---
if open_price and open_price != 0:
    daily_pct = ((current_price - open_price) / open_price) * 100
else:
    daily_pct = 0.0
    print("⚠️ Open price is zero or missing — defaulting daily_pct to 0.0")

message_body = (
    f"Price: ${current_price:.4f}\n"
    f"Daily Change: {daily_pct:+.2f}%\n"
    f"Market Time: {now.strftime('%I:%M %p CT')}"
)
print(f"📊 /RB: ${current_price:.4f} | {daily_pct:+.2f}% | {now.strftime('%I:%M %p CT')}")

# --- Alert Logic ---
# Windows are widened to 15 min to account for GitHub Actions cron delays
if abs(daily_pct) >= 3.0:
    send_vip_email('🚨 MAJOR 3% SWING ON /RB!', message_body)
elif now.hour == 17 and 25 <= now.minute < 40:
    send_vip_email('⏰ 5:30 PM: CHECK SUPPLIER APP!', message_body)
elif now.hour == 13 and 25 <= now.minute < 40:
    send_vip_email('📊 1:30 PM: /RB Market Settled', message_body)
elif now.hour in [0, 6, 12, 18] and 0 <= now.minute < 10:
    send_vip_email(f'⏱️ 6-Hour Update ({now.strftime("%I %p")})', message_body)
