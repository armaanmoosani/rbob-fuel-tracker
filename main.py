import os
import smtplib
from email.mime.text import MIMEText
import requests
from datetime import datetime
import pytz
from base64 import b64encode
from nacl import encoding, public

SCHWAB_APP_KEY = os.environ['SCHWAB_APP_KEY']
SCHWAB_APP_SECRET = os.environ['SCHWAB_APP_SECRET']
SCHWAB_REFRESH_TOKEN = os.environ['SCHWAB_REFRESH_TOKEN']
GH_PAT = os.environ['GH_PAT']
GH_REPO = os.environ['GH_REPO']
GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
TO_EMAIL = os.environ['TO_EMAIL']

def send_vip_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = TO_EMAIL
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    server.quit()

def update_github_secret(new_refresh_token):
    headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json"}
    key_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    res = requests.get(key_url, headers=headers).json()
    key = public.PublicKey(res['key'].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(key)
    encrypted = b64encode(sealed_box.encrypt(new_refresh_token.encode("utf-8"))).decode("utf-8")
    put_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/SCHWAB_REFRESH_TOKEN"
    requests.put(put_url, headers=headers, json={"encrypted_value": encrypted, "key_id": res['key_id']})

auth_url = "https://api.schwabapi.com/v1/oauth/token"
auth_data = {
    "grant_type": "refresh_token",
    "refresh_token": SCHWAB_REFRESH_TOKEN,
    "client_id": SCHWAB_APP_KEY,
    "client_secret": SCHWAB_APP_SECRET
}
auth_res = requests.post(auth_url, data=auth_data).json()
access_token = auth_res['access_token']
new_refresh_token = auth_res['refresh_token']
update_github_secret(new_refresh_token)

headers = {"Authorization": f"Bearer {access_token}"}
quote_url = "https://api.schwabapi.com/marketdata/v1/quotes?symbols=/RB"
quote_data = requests.get(quote_url, headers=headers).json()
rb_data = quote_data['/RB']['quote']
current_price = rb_data['lastPrice']
open_price = rb_data['openPrice']
daily_pct = ((current_price - open_price) / open_price) * 100

tz = pytz.timezone('America/Chicago')
now = datetime.now(tz)
message_body = f"Price: ${current_price:.4f}\nDaily Change: {daily_pct:.2f}%\nMarket Time: {now.strftime('%I:%M %p CT')}"

if abs(daily_pct) >= 3.0:
    send_vip_email('🚨 MAJOR 3% SWING ON /RB!', message_body)
elif now.hour == 17 and 30 <= now.minute < 35:
    send_vip_email('⏰ 5:30 PM: CHECK SUPPLIER APP!', message_body)
elif now.hour == 13 and 30 <= now.minute < 35:
    send_vip_email('📊 1:30 PM: /RB Market Settled', message_body)
elif now.hour in [0, 6, 12, 18] and 0 <= now.minute < 5:
    send_vip_email(f'⏱️ 6-Hour Update ({now.strftime("%I %p")})', message_body)
