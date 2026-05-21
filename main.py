import os
import sys
import io
import json
import uuid
import base64
import smtplib
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — must be set before other matplotlib imports
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, date, timezone
import requests
import pytz
from base64 import b64encode
from nacl import encoding, public

# ---------------------------------------------------------------------------
# Environment Variables
# ---------------------------------------------------------------------------
SCHWAB_APP_KEY    = os.environ['SCHWAB_APP_KEY']
SCHWAB_APP_SECRET = os.environ['SCHWAB_APP_SECRET']
SCHWAB_REFRESH_TOKEN = os.environ['SCHWAB_REFRESH_TOKEN']
GH_PAT  = os.environ['GH_PAT']
GH_REPO = os.environ['GH_REPO']
GMAIL_USER        = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
TO_EMAIL = os.environ['TO_EMAIL']

GH_HEADERS = {
    "Authorization": f"token {GH_PAT}",
    "Accept": "application/vnd.github.v3+json"
}

TZ = pytz.timezone('America/Chicago')
MAX_HISTORY = 300  # ~25 hours of data at 5-min intervals

# ---------------------------------------------------------------------------
# GitHub Repo Variable Helpers  (used for deduplication + price history)
# ---------------------------------------------------------------------------

def get_repo_variable(name):
    """Read a GitHub Actions repository variable. Returns None if missing."""
    url = f"https://api.github.com/repos/{GH_REPO}/actions/variables/{name}"
    res = requests.get(url, headers=GH_HEADERS)
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return res.json().get("value")


def set_repo_variable(name, value):
    """Create or update a GitHub Actions repository variable."""
    url = f"https://api.github.com/repos/{GH_REPO}/actions/variables/{name}"
    res = requests.patch(url, headers=GH_HEADERS, json={"name": name, "value": value})
    if res.status_code == 404:
        res = requests.post(
            f"https://api.github.com/repos/{GH_REPO}/actions/variables",
            headers=GH_HEADERS,
            json={"name": name, "value": value}
        )
    res.raise_for_status()


# ---------------------------------------------------------------------------
# Price History  (persisted as JSON in a GitHub repo variable)
# ---------------------------------------------------------------------------

def load_price_history():
    raw = get_repo_variable("RB_PRICE_HISTORY")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def save_price_history(history):
    try:
        set_repo_variable("RB_PRICE_HISTORY", json.dumps(history))
    except Exception as e:
        print(f"⚠️  Could not save price history: {e}")


def append_price(history, ts, price):
    """Add a new point and trim to MAX_HISTORY."""
    history.append({"t": ts.isoformat(), "p": round(price, 4)})
    return history[-MAX_HISTORY:]


# ---------------------------------------------------------------------------
# Chart Generation
# ---------------------------------------------------------------------------

def generate_chart(history, current_price, open_price, daily_pct):
    """
    Render a dark-themed price chart of the last ~25 hours.
    Returns a base64-encoded PNG string, or None if not enough data.
    """
    if len(history) < 3:
        return None

    times  = [datetime.fromisoformat(h['t']).astimezone(TZ) for h in history]
    prices = [h['p'] for h in history]

    is_up      = daily_pct >= 0
    line_color = '#22c55e' if is_up else '#ef4444'   # green / red
    bg_dark    = '#0f172a'
    bg_panel   = '#1e293b'
    grid_color = '#334155'
    text_color = '#94a3b8'

    fig, ax = plt.subplots(figsize=(10, 3.8))
    fig.patch.set_facecolor(bg_dark)
    ax.set_facecolor(bg_panel)

    # Price line + area fill
    ax.plot(times, prices, color=line_color, linewidth=2.2, zorder=3)
    ax.fill_between(times, prices, min(prices) * 0.9995,
                    alpha=0.18, color=line_color, zorder=2)

    # Current price dot
    ax.scatter([times[-1]], [prices[-1]], color=line_color, s=70, zorder=5, linewidths=0)

    # Open price dashed reference line
    if open_price and open_price > 0:
        ax.axhline(y=open_price, color=text_color, linewidth=1,
                   linestyle='--', alpha=0.55, label=f'Open  ${open_price:.4f}')
        ax.legend(facecolor=bg_panel, edgecolor=grid_color,
                  labelcolor=text_color, fontsize=8.5, loc='upper left')

    # Current price annotation
    ax.annotate(
        f'  ${current_price:.4f}',
        xy=(times[-1], prices[-1]),
        color=line_color, fontsize=10.5, fontweight='bold', va='center'
    )

    # Axes formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%-I %p', tz=TZ))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.xticks(rotation=0, ha='center', color=text_color, fontsize=8)
    plt.yticks(color=text_color, fontsize=8)
    ax.set_ylabel('$/gal', color=text_color, fontsize=9)

    pct_sign = '+' if is_up else ''
    ax.set_title(
        f'/RB RBOB Gasoline   {pct_sign}{daily_pct:.2f}% today   '
        f'as of {times[-1].strftime("%-I:%M %p CT, %b %-d")}',
        color='#e2e8f0', fontsize=11, fontweight='bold', pad=10
    )

    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.6)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ---------------------------------------------------------------------------
# Email Sending  (HTML with embedded chart)
# ---------------------------------------------------------------------------

def send_email(subject, text_body, chart_b64=None):
    """
    Send a styled HTML email with an optional embedded price chart.
    Falls back gracefully if chart is unavailable.
    """
    try:
        cid = uuid.uuid4().hex

        # ---- Plain-text version (fallback) ----
        plain = MIMEText(text_body, 'plain')

        # ---- HTML version ----
        chart_tag = (
            f'<img src="cid:{cid}" alt="Price Chart" '
            f'style="width:100%;border-radius:8px;margin-top:16px;" />'
            if chart_b64 else
            '<p style="color:#475569;font-size:12px;">Chart unavailable — not enough data yet.</p>'
        )
        html_body = f"""
        <html>
        <body style="margin:0;padding:24px;background:#0f172a;
                     font-family:'SF Mono','Courier New',monospace;color:#e2e8f0;">
          <div style="max-width:680px;margin:0 auto;background:#1e293b;
                      border-radius:12px;padding:24px;border:1px solid #334155;">

            <h2 style="margin:0 0 4px;font-size:15px;
                       color:#e2e8f0;letter-spacing:0.02em;">{subject}</h2>
            <p style="margin:0 0 16px;font-size:11px;color:#475569;">
              RBOB Gasoline Futures &nbsp;|&nbsp; Automated Alert
            </p>

            <pre style="background:#0f172a;padding:16px;border-radius:8px;
                        font-size:13px;color:#94a3b8;
                        margin:0;line-height:1.6;">{text_body}</pre>

            {chart_tag}

            <p style="margin:16px 0 0;font-size:10px;color:#334155;text-align:center;">
              armaanmoosani/rbob-fuel-tracker &nbsp;|&nbsp; GitHub Actions
            </p>
          </div>
        </body>
        </html>
        """

        # Build the MIME message
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL

        alt = MIMEMultipart('alternative')
        alt.attach(plain)
        alt.attach(MIMEText(html_body, 'html'))
        msg.attach(alt)

        if chart_b64:
            img = MIMEImage(base64.b64decode(chart_b64), 'png')
            img.add_header('Content-ID', f'<{cid}>')
            img.add_header('Content-Disposition', 'inline', filename='rb_chart.png')
            msg.attach(img)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        server.quit()
        print(f"✅ Email sent: {subject}")

    except Exception as e:
        print(f"❌ Email send failed: {e}")


# ---------------------------------------------------------------------------
# Deduplication  (each alert key fires at most once per calendar day)
# ---------------------------------------------------------------------------

def already_sent_today(key):
    today = date.today().isoformat()
    return get_repo_variable(f"LAST_ALERT_{key}") == today


def mark_sent_today(key):
    try:
        set_repo_variable(f"LAST_ALERT_{key}", date.today().isoformat())
    except Exception as e:
        print(f"⚠️  Could not record sent state for {key}: {e}")


def send_once_today(key, subject, text_body, chart_b64=None):
    """Send an alert at most once per calendar day for the given key."""
    if already_sent_today(key):
        print(f"⏭️  Skipping '{key}' — already sent today")
        return
    send_email(subject, text_body, chart_b64)
    mark_sent_today(key)


# ---------------------------------------------------------------------------
# GitHub Secret Rotation
# ---------------------------------------------------------------------------

def update_github_secret(new_token):
    """Encrypt and overwrite SCHWAB_REFRESH_TOKEN in GitHub Secrets."""
    key_url = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    res = requests.get(key_url, headers=GH_HEADERS)
    res.raise_for_status()
    kd  = res.json()
    key = public.PublicKey(kd['key'].encode(), encoding.Base64Encoder())
    box = public.SealedBox(key)
    enc = b64encode(box.encrypt(new_token.encode())).decode()
    put = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/SCHWAB_REFRESH_TOKEN",
        headers=GH_HEADERS,
        json={"encrypted_value": enc, "key_id": kd['key_id']}
    )
    put.raise_for_status()
    print("✅ GitHub secret updated")


# ===========================================================================
# MAIN EXECUTION
# ===========================================================================

# --- Weekend / Market-Hours Guard ---
now = datetime.now(TZ)
weekday = now.weekday()  # 0=Mon … 5=Sat, 6=Sun

if weekday == 5:
    print("📅 Saturday — /RB market closed. Exiting.")
    sys.exit(0)
if weekday == 6 and now.hour < 17:
    print("📅 Sunday before 5:00 PM CT market open. Exiting.")
    sys.exit(0)

# --- OAuth Token Refresh ---
auth_header = base64.b64encode(
    f"{SCHWAB_APP_KEY}:{SCHWAB_APP_SECRET}".encode()
).decode()

try:
    auth_res = requests.post(
        "https://api.schwabapi.com/v1/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": SCHWAB_REFRESH_TOKEN},
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    auth_res.raise_for_status()
    auth_json      = auth_res.json()
    access_token   = auth_json['access_token']
    new_refresh    = auth_json['refresh_token']
    print("✅ Schwab OAuth refreshed")
except Exception as e:
    send_email(
        "🚨 EMERGENCY: RBOB Tracker Auth Failed!",
        f"OAuth token refresh failed — tracker is DOWN.\n\n"
        f"Error: {e}\n\n"
        f"ACTION REQUIRED: Re-authenticate at developer.schwab.com\n"
        f"and update SCHWAB_REFRESH_TOKEN in GitHub Secrets."
    )
    print(f"❌ FATAL: OAuth refresh failed: {e}")
    sys.exit(1)

# Store new token BEFORE anything else (old token is now invalidated)
try:
    update_github_secret(new_refresh)
except Exception as e:
    send_email(
        "🚨 EMERGENCY: GitHub Secret Update Failed!",
        f"New Schwab token obtained but FAILED to save.\n\n"
        f"Error: {e}\n\n"
        f"⚠️  Tracker WILL break on next run.\n"
        f"Manually update SCHWAB_REFRESH_TOKEN in GitHub Secrets NOW."
    )
    print(f"❌ FATAL: GitHub secret update failed: {e}")
    sys.exit(1)

# --- Fetch Live /RB Market Data ---
try:
    quote_res = requests.get(
        "https://api.schwabapi.com/marketdata/v1/quotes?symbols=/RB",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    quote_res.raise_for_status()
    rb       = quote_res.json()['/RB']['quote']
    current_price = rb['lastPrice']
    open_price    = rb['openPrice']
except Exception as e:
    print(f"❌ Market data fetch failed: {e}")
    sys.exit(1)

# Daily % change (division-by-zero safe)
if open_price and open_price != 0:
    daily_pct = ((current_price - open_price) / open_price) * 100
else:
    daily_pct = 0.0
    print("⚠️  Open price missing — defaulting daily_pct to 0.0")

print(f"📊 /RB: ${current_price:.4f} | {daily_pct:+.2f}% | {now.strftime('%-I:%M %p CT')}")

# --- Update & persist price history ---
history = load_price_history()
history = append_price(history, now, current_price)
save_price_history(history)

# --- Build email body ---
arrow = "▲" if daily_pct >= 0 else "▼"
message_body = (
    f"Price:        ${current_price:.4f} / gal\n"
    f"Daily Change: {arrow} {daily_pct:+.2f}%\n"
    f"Open:         ${open_price:.4f} / gal\n"
    f"Market Time:  {now.strftime('%-I:%M %p CT, %b %-d %Y')}"
)

# --- Generate chart ---
chart = generate_chart(history, current_price, open_price, daily_pct)
if chart:
    print("✅ Chart generated")
else:
    print("⚠️  Not enough history for chart yet")

# ===========================================================================
# Alert Logic  — each key fires at most once per calendar day
# ===========================================================================

# 3% swing alert — checked every run, deduped per day
if abs(daily_pct) >= 3.0:
    direction = "▲ UP" if daily_pct > 0 else "▼ DOWN"
    send_once_today(
        "SWING3",
        f"🚨 MAJOR MOVE: /RB {direction} {daily_pct:+.2f}%",
        message_body,
        chart
    )

# 5:30 PM rack-price window (±7 min buffer for cron delays)
elif now.hour == 17 and 23 <= now.minute < 38:
    send_once_today(
        "RACK_530",
        "⏰ 5:30 PM — Check Supplier App Now",
        message_body,
        chart
    )

# 1:30 PM settlement alert (±7 min buffer)
elif now.hour == 13 and 23 <= now.minute < 38:
    send_once_today(
        "SETTLE_130",
        "📊 1:30 PM — /RB Daily Settlement Price",
        message_body,
        chart
    )

# 6-hour status updates (8-min buffer)
elif now.hour in [0, 6, 12, 18] and 0 <= now.minute < 8:
    hour_key = f"UPDATE_{now.strftime('%H')}"
    send_once_today(
        hour_key,
        f"⏱️ {now.strftime('%-I %p')} — /RB 6-Hour Update",
        message_body,
        chart
    )
