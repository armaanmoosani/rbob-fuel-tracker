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

def build_html_email(
    subject, current_price, open_price, daily_pct,
    now, alert_context, chart_b64
):
    """
    Build a fully structured HTML email body.
    alert_context: dict with keys 'label', 'action', 'action_color'
    """
    cid = uuid.uuid4().hex

    is_up       = daily_pct >= 0
    pct_color   = '#22c55e' if is_up else '#ef4444'
    pct_bg      = '#052e16' if is_up else '#2d0a0a'
    arrow       = '▲' if is_up else '▼'
    pct_sign    = '+' if is_up else ''
    dollar_chg  = current_price - open_price

    chart_section = (
        f'<img src="cid:{cid}" alt="/RB Price Chart — last 25 hours" '
        f'style="width:100%;border-radius:8px;margin-top:0;display:block;"/>'
        if chart_b64
        else '<p style="color:#475569;font-size:11px;margin:0;">'  
             'Price chart will appear after the first few data points are collected.</p>'
    )

    action_line = ''
    if alert_context.get('action'):
        ac = alert_context['action_color']
        action_line = f'''
        <div style="margin:0 0 20px;padding:12px 16px;
                    background:{pct_bg};border-left:3px solid {ac};
                    border-radius:0 6px 6px 0;">
          <p style="margin:0;font-size:13px;color:{ac};font-weight:600;">
            {alert_context['action']}
          </p>
        </div>'''

    # Plain-text fallback
    plain_text = (
        f"{alert_context.get('label','RBOB Alert')}\n"
        f"{'=' * 40}\n"
        f"Price:        ${current_price:.4f} / gal\n"
        f"Change:       {arrow} {pct_sign}{daily_pct:.2f}%  "
        f"({pct_sign}${dollar_chg:.4f})\n"
        f"Open:         ${open_price:.4f} / gal\n"
        f"As of:        {now.strftime('%I:%M %p CT — %A, %b %d %Y')}\n"
    )
    if alert_context.get('action'):
        plain_text += f"\n→ {alert_context['action']}\n"

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px 12px;background:#0a0f1e;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">

  <div style="max-width:620px;margin:0 auto;">

    <!-- Header -->
    <div style="background:#0f172a;border-radius:12px 12px 0 0;
                padding:16px 24px;border:1px solid #1e293b;border-bottom:none;">
      <p style="margin:0;font-size:11px;color:#475569;letter-spacing:0.08em;text-transform:uppercase;">
        /RB &nbsp;·&nbsp; RBOB Gasoline Futures &nbsp;·&nbsp; NYMEX CME
      </p>
      <p style="margin:4px 0 0;font-size:13px;color:#64748b;">
        {now.strftime('%A, %B %-d, %Y &nbsp;·&nbsp; %-I:%M %p CT')}
      </p>
    </div>

    <!-- Hero price card -->
    <div style="background:#1e293b;padding:24px;border-left:1px solid #1e293b;
                border-right:1px solid #1e293b;">

      <p style="margin:0 0 4px;font-size:11px;color:#64748b;
                letter-spacing:0.06em;text-transform:uppercase;">Current Price</p>
      <p style="margin:0;font-size:48px;font-weight:700;color:#f1f5f9;
                letter-spacing:-1px;line-height:1;">
        ${current_price:.4f}
        <span style="font-size:16px;color:#64748b;font-weight:400;">&nbsp;/ gal</span>
      </p>

      <!-- Change badge -->
      <div style="display:inline-block;margin-top:12px;padding:6px 14px;
                  background:{pct_bg};border-radius:20px;
                  border:1px solid {pct_color}33;">
        <span style="font-size:16px;font-weight:700;color:{pct_color};">
          {arrow} {pct_sign}{daily_pct:.2f}%
        </span>
        <span style="font-size:13px;color:{pct_color};opacity:0.8;">
          &nbsp;({pct_sign}${dollar_chg:.4f})
        </span>
        <span style="font-size:11px;color:#475569;">&nbsp; vs open</span>
      </div>
    </div>

    <!-- Stats row -->
    <div style="background:#162032;display:flex;border-left:1px solid #1e293b;
                border-right:1px solid #1e293b;">

      <div style="flex:1;padding:14px 20px;border-right:1px solid #1e293b;">
        <p style="margin:0;font-size:10px;color:#475569;
                  text-transform:uppercase;letter-spacing:0.06em;">Open</p>
        <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#94a3b8;">
          ${open_price:.4f}
        </p>
      </div>

      <div style="flex:1;padding:14px 20px;border-right:1px solid #1e293b;">
        <p style="margin:0;font-size:10px;color:#475569;
                  text-transform:uppercase;letter-spacing:0.06em;">$ Change</p>
        <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:{pct_color};">
          {pct_sign}${dollar_chg:.4f}
        </p>
      </div>

      <div style="flex:1;padding:14px 20px;">
        <p style="margin:0;font-size:10px;color:#475569;
                  text-transform:uppercase;letter-spacing:0.06em;">Session</p>
        <p style="margin:4px 0 0;font-size:16px;font-weight:600;color:#94a3b8;">
          {'Higher' if is_up else 'Lower'}
        </p>
      </div>
    </div>

    <!-- Action banner (only for specific alert types) -->
    {action_line}

    <!-- Chart -->
    <div style="background:#1e293b;padding:20px 24px {'16px' if not action_line else '0 24px 20px'};
                border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
      <p style="margin:0 0 12px;font-size:10px;color:#475569;
                text-transform:uppercase;letter-spacing:0.06em;">
        Price History — Last 25 Hours
      </p>
      {chart_section}
    </div>

    <!-- Footer -->
    <div style="background:#0f172a;border-radius:0 0 12px 12px;padding:12px 24px;
                border:1px solid #1e293b;border-top:1px solid #0f172a;">
      <p style="margin:0;font-size:10px;color:#334155;">
        Automated by <a href="https://github.com/{GH_REPO}" style="color:#475569;
        text-decoration:none;">armaanmoosani/rbob-fuel-tracker</a>
        &nbsp;·&nbsp; GitHub Actions · Data via Charles Schwab Trader API
      </p>
    </div>

  </div>
</body>
</html>
"""
    return cid, plain_text, html


def send_email(
    subject, current_price, open_price, daily_pct,
    now, alert_context, chart_b64=None
):
    """Assemble and dispatch the HTML alert email."""
    try:
        cid, plain_text, html_body = build_html_email(
            subject, current_price, open_price, daily_pct,
            now, alert_context, chart_b64
        )

        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL

        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(plain_text, 'plain'))
        alt.attach(MIMEText(html_body,  'html'))
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


def send_once_today(
    key, subject, current_price, open_price, daily_pct,
    now, alert_context, chart_b64=None
):
    """Send an alert at most once per calendar day for the given key."""
    if already_sent_today(key):
        print(f"⏭️  Skipping '{key}' — already sent today")
        return
    send_email(
        subject, current_price, open_price, daily_pct,
        now, alert_context, chart_b64
    )
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
    # Emergency plain-text alert — send directly without the full HTML builder
    # since we don't have market data yet at this point
    try:
        msg = MIMEText(
            f"OAuth token refresh failed — tracker is DOWN.\n\n"
            f"Error: {e}\n\n"
            f"ACTION REQUIRED:\n"
            f"1. Go to developer.schwab.com\n"
            f"2. Complete the OAuth handshake\n"
            f"3. Update SCHWAB_REFRESH_TOKEN in GitHub Secrets."
        )
        msg['Subject'] = "🚨 EMERGENCY: RBOB Tracker Auth Failed!"
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL
        srv = smtplib.SMTP('smtp.gmail.com', 587)
        srv.starttls()
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        srv.quit()
    except Exception:
        pass
    print(f"❌ FATAL: OAuth refresh failed: {e}")
    sys.exit(1)

# Store new token BEFORE anything else (old token is now invalidated)
try:
    update_github_secret(new_refresh)
except Exception as e:
    try:
        msg = MIMEText(
            f"New Schwab token obtained but FAILED to save to GitHub Secrets.\n\n"
            f"Error: {e}\n\n"
            f"⚠️  The tracker WILL break on the next run.\n"
            f"Manually update SCHWAB_REFRESH_TOKEN in GitHub Secrets NOW."
        )
        msg['Subject'] = "🚨 EMERGENCY: GitHub Secret Update Failed!"
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL
        srv = smtplib.SMTP('smtp.gmail.com', 587)
        srv.starttls()
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        srv.quit()
    except Exception:
        pass
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

# --- Generate chart ---
chart = generate_chart(history, current_price, open_price, daily_pct)
print("✅ Chart generated" if chart else "⚠️  Not enough history for chart yet")

# ===========================================================================
# Alert Logic  — each key fires at most once per calendar day
# ===========================================================================

# 3% swing alert — checked every run, deduped per day
if abs(daily_pct) >= 3.0:
    pct_sign  = '+' if daily_pct > 0 else ''
    direction = 'higher' if daily_pct > 0 else 'lower'
    buy_note  = (
        'Prices are rising — consider whether to lock in supply now or wait.'
        if daily_pct > 0 else
        'Prices are falling — may be a good opportunity to buy ahead of rack pricing.'
    )
    send_once_today(
        key='SWING3',
        subject=f"🚨 /RB Major Move: {pct_sign}{daily_pct:.2f}% — ${current_price:.4f}/gal",
        current_price=current_price, open_price=open_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': 'Major Price Swing',
            'action': buy_note,
            'action_color': '#22c55e' if daily_pct < 0 else '#f97316',
        },
        chart_b64=chart
    )

# 5:30 PM rack-price window (±7 min buffer for cron delays)
elif now.hour == 17 and 23 <= now.minute < 38:
    send_once_today(
        key='RACK_530',
        subject=f"⏰ Rack Window Open — /RB ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': '5:30 PM Rack Price Window',
            'action': 'Rack prices go effective at 7:00 PM CT. Open your supplier app now to compare and decide.',
            'action_color': '#f59e0b',
        },
        chart_b64=chart
    )

# 1:30 PM settlement alert (±7 min buffer)
elif now.hour == 13 and 23 <= now.minute < 38:
    send_once_today(
        key='SETTLE_130',
        subject=f"📊 /RB Settled at ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': '1:30 PM Daily Settlement',
            'action': 'This is the official CME daily settlement price. Rack prices this evening will likely reflect this level.',
            'action_color': '#60a5fa',
        },
        chart_b64=chart
    )

# 6-hour status updates (8-min buffer)
elif now.hour in [0, 6, 12, 18] and 0 <= now.minute < 8:
    hour_key   = f"UPDATE_{now.strftime('%H')}"
    time_label = now.strftime('%-I %p')
    send_once_today(
        key=hour_key,
        subject=f"⏱️ {time_label} Update — /RB ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': f'{time_label} 6-Hour Update',
            'action': '',   # No specific action cue for routine updates
            'action_color': '#94a3b8',
        },
        chart_b64=chart
    )
