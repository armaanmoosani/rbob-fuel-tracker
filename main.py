import os
import sys
import io
import json
import uuid
import base64
import smtplib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, date, timezone
import requests
import pytz
import yfinance as yf
import concurrent.futures
import pandas_market_calendars as mcal

SCHWAB_APP_KEY       = os.environ['SCHWAB_APP_KEY']
SCHWAB_APP_SECRET    = os.environ['SCHWAB_APP_SECRET']
SCHWAB_REFRESH_TOKEN = os.environ['SCHWAB_REFRESH_TOKEN']
GH_PAT               = os.environ['GH_PAT']
GH_REPO              = os.environ['GH_REPO']
GMAIL_USER           = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD   = os.environ['GMAIL_APP_PASSWORD']
TO_EMAIL             = os.environ['TO_EMAIL']
TO_PHONE_SMS         = os.environ.get('PHONE_SMS_ADDRESS', '')

GH_HEADERS = {
    "Authorization": f"token {GH_PAT}",
    "Accept": "application/vnd.github.v3+json"
}

TZ = pytz.timezone('America/Chicago')

COMMODITIES = {
    'RB': {
        'name': 'Wholesale Gas',
        'yf_symbol': 'RB=F',
        'display_name': 'UNLEADED (/RB)'
    },
    'HO': {
        'name': 'Diesel',
        'yf_symbol': 'HO=F',
        'display_name': 'DIESEL (/HO)'
    }
}

def get_session_start(dt):
    import datetime
    if dt.hour >= 17:
        return dt.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        prev_day = dt - datetime.timedelta(days=1)
        return prev_day.replace(hour=17, minute=0, second=0, microsecond=0)

def get_session_date_str(dt):
    import datetime
    if dt.hour >= 17:
        return (dt + datetime.timedelta(days=1)).date().isoformat()
    return dt.date().isoformat()

DELIVERY_MONTH_CODES = {
    1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
    7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
}

def get_front_month_schwab_symbol(dt, prefix):
    import calendar
    from datetime import date, timedelta
    today = dt.date()
    candidate_month = today.month + 1
    candidate_year  = today.year
    if candidate_month > 12:
        candidate_month = 1
        candidate_year += 1
    for _ in range(14):
        prev_month = candidate_month - 1
        prev_year  = candidate_year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        last_day = calendar.monthrange(prev_year, prev_month)[1]
        ltd = date(prev_year, prev_month, last_day)
        while ltd.weekday() >= 5:
            ltd -= timedelta(days=1)
        days_away = (ltd - today).days
        if days_away > 10:
            break
        candidate_month += 1
        if candidate_month > 12:
            candidate_month = 1
            candidate_year += 1
    code = DELIVERY_MONTH_CODES[candidate_month]
    return f"/{prefix}{code}{candidate_year % 100:02d}"

def get_repo_variable(name):
    url = f"https://api.github.com/repos/{GH_REPO}/actions/variables/{name}"
    res = requests.get(url, headers=GH_HEADERS)
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return res.json().get("value")

def set_repo_variable(name, value):
    url = f"https://api.github.com/repos/{GH_REPO}/actions/variables/{name}"
    res = requests.patch(url, headers=GH_HEADERS, json={"name": name, "value": value})
    if res.status_code == 404:
        res = requests.post(
            f"https://api.github.com/repos/{GH_REPO}/actions/variables",
            headers=GH_HEADERS,
            json={"name": name, "value": value}
        )
    res.raise_for_status()

def update_github_secret(new_refresh_token):
    from nacl import encoding, public
    url_key = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    res_key = requests.get(url_key, headers=GH_HEADERS)
    res_key.raise_for_status()
    key_data = res_key.json()
    public_key = key_data['key']
    key_id = key_data['key_id']

    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder)
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = sealed_box.encrypt(new_refresh_token.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    url_secret = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/SCHWAB_REFRESH_TOKEN"
    res_secret = requests.put(
        url_secret,
        headers=GH_HEADERS,
        json={"encrypted_value": encrypted_b64, "key_id": key_id}
    )
    res_secret.raise_for_status()

def load_price_history(prefix):
    raw = get_repo_variable(f"{prefix}_PRICE_HISTORY")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []

def save_price_history(history, prefix):
    try:
        set_repo_variable(f"{prefix}_PRICE_HISTORY", json.dumps(history))
    except Exception as e:
        print(f"Warning: could not save price history for {prefix}: {e}")

def append_price(history, ts, price):
    session_start = get_session_start(ts)
    filtered = []
    for h in history:
        h_dt = datetime.fromisoformat(h['t'])
        if h_dt >= session_start:
            filtered.append(h)
    filtered.append({"t": ts.isoformat(), "p": round(price, 4)})
    return filtered

def generate_intraday_chart(history, current_price, open_price, high_price, low_price, daily_pct, commodity_name):
    if len(history) < 3:
        return None
    times  = [datetime.fromisoformat(h['t']).astimezone(TZ) for h in history]
    prices = [h['p'] for h in history]
    is_up      = daily_pct >= 0
    line_color = '#22c55e' if is_up else '#ef4444'
    bg_dark    = '#ffffff'
    bg_panel   = '#f8fafc'
    grid_color = '#e2e8f0'
    text_color = '#64748b'

    fig, ax = plt.subplots(figsize=(12, 5.5))
    fig.patch.set_facecolor(bg_dark)
    ax.set_facecolor(bg_panel)

    if high_price > 0 and low_price > 0:
        ax.axhspan(low_price, high_price, alpha=0.04, color='#94a3b8', zorder=1)

    if open_price:
        ax.axhline(open_price, color='#94a3b8', linestyle='--', linewidth=1, zorder=2)
        ax.annotate(f' Open: ${open_price:.4f}', xy=(times[0], open_price),
                    color='#94a3b8', fontsize=14, va='bottom', ha='left')

    ax.plot(times, prices, color=line_color, linewidth=2.5, zorder=4)
    ax.fill_between(times, min(prices) if min(prices) < open_price else open_price, prices,
                    alpha=0.10, color=line_color, zorder=2)
    ax.scatter([times[-1]], [prices[-1]], color='#22c55e', s=60, zorder=5, linewidths=0)
    ax.annotate(f'  ${current_price:.4f}', xy=(times[-1], prices[-1]),
                color='#22c55e', fontsize=18, fontweight='bold', va='center')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%-I:%M %p', tz=TZ))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=0, ha='center', color=text_color, fontsize=14)
    plt.yticks(color=text_color, fontsize=14)
    ax.set_ylabel('$/gal', color=text_color, fontsize=16)

    pct_sign = '+' if is_up else ''
    ax.set_title(
        f'{commodity_name} Intraday   {pct_sign}{daily_pct:.2f}% vs open   '
        f'as of {times[-1].strftime("%-I:%M %p CT")}',
        color='#e2e8f0', fontsize=20, fontweight='bold', pad=12
    )
    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.5)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=180, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def generate_5day_chart(history_5d, current_price):
    if len(history_5d) < 3:
        return None
    times  = [datetime.fromisoformat(h['t']).astimezone(TZ) for h in history_5d]
    prices = [h['p'] for h in history_5d]
    bg_dark    = '#ffffff'
    bg_panel   = '#f8fafc'
    grid_color = '#e2e8f0'
    text_color = '#64748b'
    line_color = '#60a5fa'

    fig, ax = plt.subplots(figsize=(12, 4.0))
    fig.patch.set_facecolor(bg_dark)
    ax.set_facecolor(bg_panel)

    ax.plot(times, prices, color=line_color, linewidth=2, zorder=4)
    ax.fill_between(times, min(prices) * 0.99, prices,
                    alpha=0.10, color=line_color, zorder=2)
    ax.scatter([times[-1]], [prices[-1]], color='#22c55e', s=60, zorder=5, linewidths=0)
    ax.annotate(f'  ${current_price:.4f}', xy=(times[-1], prices[-1]),
                color='#22c55e', fontsize=18, fontweight='bold', va='center')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%a', tz=TZ))
    ax.xaxis.set_major_locator(mdates.DayLocator(tz=TZ))
    plt.xticks(rotation=0, ha='center', color=text_color, fontsize=14)
    plt.yticks(color=text_color, fontsize=14)
    ax.set_ylabel('$/gal', color=text_color, fontsize=16)
    ax.set_title('5-Day Price Trend', color='#e2e8f0', fontsize=20, fontweight='bold', pad=10)

    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.5)
    ax.xaxis.grid(True, color=grid_color, linewidth=0.8, alpha=0.4)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=180, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def build_html_block(prefix, info, now):
    cid_intra = uuid.uuid4().hex
    cid_5d    = uuid.uuid4().hex
    
    current_price = info['current_price']
    open_price = info['open_price']
    high_price = info['high_price']
    low_price = info['low_price']
    daily_pct = info['daily_pct']
    yesterday_close = info['yesterday_close']
    five_day_high = info['five_day_high']
    five_day_low = info['five_day_low']
    thirty_day_avg = info['thirty_day_avg']
    chart_intraday_b64 = info['chart_intraday_b64']
    chart_5d_b64 = info['chart_5d_b64']
    
    is_up      = daily_pct >= 0
    pct_color  = '#22c55e' if is_up else '#ef4444'
    pct_bg     = '#0a2010' if is_up else '#200a0a'
    arrow      = '\u25b2' if is_up else '\u25bc'
    pct_sign   = '+' if is_up else ''
    dollar_chg = current_price - open_price

    price_range  = (high_price - low_price) if (high_price > 0 and low_price > 0) else 0
    range_pct    = ((current_price - low_price) / price_range * 100) if price_range > 0 else 50.0
    range_bar_pos = min(max(range_pct, 2), 98)

    def fmt_price(p): return f'${p:.4f}' if p else 'N/A'

    yest_cell = fmt_price(yesterday_close)
    yest_chg  = ''
    if yesterday_close:
        yc = ((current_price - yesterday_close) / yesterday_close) * 100
        yest_chg = f'<br><span style="font-size:11px;color:{"#22c55e" if yc >= 0 else "#ef4444"};">{("+" if yc >= 0 else "")}{yc:.2f}%</span>'

    ctx_5d_high = fmt_price(five_day_high)
    ctx_5d_low  = fmt_price(five_day_low)
    ctx_30d_avg = fmt_price(thirty_day_avg)
    ctx_30d_vs  = ''
    if thirty_day_avg:
        diff = ((current_price - thirty_day_avg) / thirty_day_avg) * 100
        ctx_30d_vs = f'<br><span style="font-size:11px;color:{"#22c55e" if diff >= 0 else "#ef4444"};">{("+" if diff >= 0 else "")}{diff:.2f}% vs avg</span>'

    if chart_intraday_b64:
        intraday_section = f'<img src="cid:{cid_intra}" style="width:100%;max-width:100%;height:auto;border-radius:6px;display:block;"/>'
    else:
        intraday_section = '<p style="color:#475569;font-size:11px;margin:0;">Chart waiting for data.</p>'

    if chart_5d_b64:
        fiveday_section = f'<img src="cid:{cid_5d}" style="width:100%;max-width:100%;height:auto;border-radius:6px;display:block;"/>'
    else:
        fiveday_section = ''

    html = f"""
    <!-- ══ COMMODITY BLOCK: {COMMODITIES[prefix]['name']} ══ -->
    <div style="background:#ffffff;padding:20px 20px 16px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:2px solid #94a3b8;">
      <p style="margin:0 0 2px;font-size:12px;color:#334155;letter-spacing:0.05em;text-transform:uppercase;font-weight:700;">{COMMODITIES[prefix]['name']} (/{prefix})</p>
      <p style="margin:0;font-size:44px;font-weight:700;color:#0f172a;letter-spacing:-1.5px;line-height:1.05;">
        ${current_price:.4f}
        <span style="font-size:14px;color:#64748b;font-weight:400;">&nbsp;/gal</span>
      </p>
      <div style="display:inline-block;margin-top:9px;padding:4px 13px;background:{pct_bg};border-radius:20px;border:1px solid {pct_color}33;">
        <span style="font-size:14px;font-weight:700;color:{pct_color};">{arrow}&nbsp;{pct_sign}{daily_pct:.2f}%</span>
        <span style="font-size:12px;color:{pct_color};opacity:0.8;">&nbsp;({pct_sign}${dollar_chg:.4f})</span>
        <span style="font-size:10px;color:#64748b;">&nbsp;vs open</span>
      </div>
    </div>

    <!-- STATS ROW 1 -->
    <div style="background:#f8fafc;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">Open</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#334155;">${open_price:.4f}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#22c55e;">{f"${high_price:.4f}" if high_price > 0 else "N/A"}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#ef4444;">{f"${low_price:.4f}" if low_price > 0 else "N/A"}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">$ Change</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:{pct_color};">{pct_sign}${dollar_chg:.4f}</p>
          </td>
        </tr>
      </table>
    </div>

    <!-- STATS ROW 2 -->
    <div style="background:#ffffff;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">Yest. Close</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#334155;">{yest_cell}{yest_chg}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">5-Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#334155;">{ctx_5d_high}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #e2e8f0;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">5-Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#334155;">{ctx_5d_low}</p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#64748b;text-transform:uppercase;">30-Day Avg</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#334155;">{ctx_30d_avg}{ctx_30d_vs}</p>
          </td>
        </tr>
      </table>
    </div>

    <!-- RANGE BAR -->
    <div style="background:#f8fafc;padding:12px 20px 16px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
        <tr>
          <td><p style="margin:0;font-size:8px;color:#94a3b8;text-transform:uppercase;font-weight:600;">Position in Today's Range</p></td>
          <td style="text-align:right;"><p style="margin:0;font-size:10px;color:#475569;font-weight:600;">{range_pct:.0f}% of day range</p></td>
        </tr>
      </table>
      <div style="position:relative;height:4px;background:#e2e8f0;border-radius:2px;">
        <div style="height:4px;width:{range_bar_pos:.0f}%;background:linear-gradient(to right,#cbd5e1,#94a3b8);border-radius:2px;"></div>
        <div style="position:absolute;top:-5px;left:calc({range_bar_pos:.0f}% - 7px);width:14px;height:14px;border-radius:50%;background:{pct_color};border:2px solid #ffffff;"></div>
      </div>
    </div>

    <!-- INTRADAY CHART -->
    <div style="background:#ffffff;padding:16px 20px 18px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;">
      {intraday_section}
    </div>
    <!-- 5-DAY CHART -->
    {'<div style="background:#ffffff;padding:14px 20px 16px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;">' + fiveday_section + '</div>' if fiveday_section else ''}
    """
    return html, cid_intra, cid_5d

def build_html_email(subject, all_data, now, alert_context):
    blocks = []
    cids = {}
    
    for prefix in ['RB', 'HO']:
        if prefix in all_data:
            block_html, cid_intra, cid_5d = build_html_block(prefix, all_data[prefix], now)
            blocks.append(block_html)
            cids[f"{prefix}_intra"] = cid_intra
            cids[f"{prefix}_5d"] = cid_5d

    action_line = ''
    if alert_context.get('action'):
        ac = alert_context.get('action_color', '#64748b')
        action_line = f'''
    <div style="padding:14px 22px;background:#ffffff;border-left:4px solid {ac};border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;margin-bottom:15px;">
      <p style="margin:0 0 3px;font-size:9px;color:{ac};text-transform:uppercase;letter-spacing:0.1em;font-weight:700;">
        {alert_context['label']}
      </p>
      <p style="margin:0;font-size:12px;color:#475569;line-height:1.6;">
        {alert_context['action']}
      </p>
    </div>'''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f1f5f9;">
    <tr>
      <td align="center" style="padding:20px 10px;">
        <div style="max-width:620px;margin:0 auto;width:100%;text-align:left;">
          <!-- HEADER -->
          <div style="background:#ffffff;border-radius:10px 10px 0 0;padding:13px 20px;border:1px solid #e2e8f0;border-bottom:none;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td><p style="margin:0;font-size:10px;color:#64748b;letter-spacing:0.1em;text-transform:uppercase;font-weight:600;">Fuel Tracker &nbsp;&middot;&nbsp; NYMEX CME</p></td>
                <td style="text-align:right;"><p style="margin:0;font-size:10px;color:#94a3b8;">{now.strftime('%-I:%M %p CT &nbsp;&middot;&nbsp; %b %-d, %Y')}</p></td>
              </tr>
            </table>
          </div>
          
          {action_line}
          {''.join(blocks)}
          
          <!-- FOOTER -->
          <div style="background:#f1f5f9;border-radius:0 0 10px 10px;padding:10px 20px;border:1px solid #e2e8f0;border-top:none;">
            <p style="margin:0;font-size:9px;color:#64748b;line-height:1.6;">Automated by armaanmoosani/rbob-ho-fuel-tracker</p>
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""
    
    return html, cids

def send_sms(all_data, now, alert_context):
    if not TO_PHONE_SMS:
        return
        
    label    = alert_context.get('label', 'Update')
    time_str = now.strftime('%-I:%M %p CT')

    if 'Swing' in label or 'Movement' in label:
        alert_type = 'PRICE ALERT'
    elif 'Rack' in label:
        alert_type = 'RACK WINDOW'
    elif 'Settlement' in label:
        alert_type = 'SETTLEMENT'
    else:
        alert_type = 'UPDATE'

    lines = [f"{alert_type}"]
    lines.append("")
    
    for prefix in ['RB', 'HO']:
        if prefix in all_data:
            info = all_data[prefix]
            cname = COMMODITIES[prefix]['display_name']
            pct_sign  = '+' if info['daily_pct'] >= 0 else ''
            
            lines.append(f"{cname}")
            lines.append(f"Now: ${info['current_price']:.4f} ({pct_sign}{info['daily_pct']:.2f}%)")
            
            if info['high_price'] > 0 and info['low_price'] > 0:
                lines.append(f"H: ${info['high_price']:.4f} | L: ${info['low_price']:.4f}")
            lines.append("")
            
    lines.append(f"{time_str}")
    body = "\n".join(lines).strip()

    try:
        sms_msg = MIMEText(body)
        sms_msg['Subject'] = ''
        sms_msg['From']    = GMAIL_USER
        sms_msg['To']      = TO_PHONE_SMS
        srv = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        srv.starttls()
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_PHONE_SMS, sms_msg.as_string())
        srv.quit()
        print(f"SMS sent to gateway ({TO_PHONE_SMS})")
    except Exception as e:
        print(f"SMS send failed (non-fatal): {e}")

def send_email(subject, all_data, now, alert_context):
    try:
        html_body, cids = build_html_email(subject, all_data, now, alert_context)
        
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL
        
        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText("Please view in an HTML-compatible email client.", 'plain'))
        alt.attach(MIMEText(html_body, 'html'))
        msg.attach(alt)

        for prefix in ['RB', 'HO']:
            if prefix in all_data:
                info = all_data[prefix]
                if info.get('chart_intraday_b64'):
                    img = MIMEImage(base64.b64decode(info['chart_intraday_b64']), 'png')
                    img.add_header('Content-ID', f'<{cids[f"{prefix}_intra"]}>')
                    msg.attach(img)
                if info.get('chart_5d_b64'):
                    img2 = MIMEImage(base64.b64decode(info['chart_5d_b64']), 'png')
                    img2.add_header('Content-ID', f'<{cids[f"{prefix}_5d"]}>')
                    msg.attach(img2)

        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email send failed: {e}")

    send_sms(all_data, now, alert_context)

def send_once_today(key, subject, all_data, now, alert_context):
    session_str = get_session_date_str(now).replace('-', '_')
    db_key = f"SENT_{key}_{session_str}"
    
    if get_repo_variable(db_key):
        print(f"Alert {key} already sent today. Skipping.")
        return
        
    send_email(subject, all_data, now, alert_context)
    try:
        set_repo_variable(db_key, "1")
    except Exception as e:
        print(f"Warning: could not save lock {db_key}: {e}")


def is_market_open(dt):
    try:
        cme = mcal.get_calendar('CMEGlobex_RB')
        from datetime import timedelta
        start = (dt - timedelta(days=1)).date()
        end = (dt + timedelta(days=2)).date()
        schedule = cme.schedule(start_date=start, end_date=end)
        return cme.open_at_time(schedule, dt)
    except Exception as e:
        print(f"Calendar check failed: {e}. Defaulting to open.")
        return True

def fetch_commodity(prefix, cfg, now, access_token):
    schwab_symbol = get_front_month_schwab_symbol(now, prefix)
    print(f"[{prefix}] Targeting front-month: Schwab {schwab_symbol} | yf {cfg['yf_symbol']}")
    
    current_price = open_price = high_price = low_price = None
    data_source = None
    try:
        res = requests.get(
            "https://api.schwabapi.com/marketdata/v1/quotes",
            params={"symbols": schwab_symbol},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15
        )
        res.raise_for_status()
        res_json = res.json()
        if schwab_symbol in res_json:
            quote = res_json[schwab_symbol]['quote']
        else:
            quote = res_json[list(res_json.keys())[0]]['quote']
        
        current_price = float(quote['lastPrice'])
        open_price    = float(quote['openPrice'])
        high_price    = float(quote.get('highPrice', 0.0))
        low_price     = float(quote.get('lowPrice', 0.0))
        data_source   = 'schwab'
        print(f"[{prefix}] Schwab success")
    except Exception as e:
        print(f"[{prefix}] Schwab failed: {e}. Falling back to yfinance.")
        import time
        for attempt in range(3):
            try:
                yf_t = yf.Ticker(cfg['yf_symbol'])
                current_price = float(yf_t.fast_info['last_price'])
                hist = yf_t.history(period='1d', interval='5m')
                if not hist.empty:
                    open_price = float(hist['Open'].iloc[0])
                    high_price = float(hist['High'].max())
                    low_price  = float(hist['Low'].min())
                else:
                    open_price = current_price
                    high_price = low_price = 0.0
                data_source = 'yfinance'
                print(f"[{prefix}] yfinance fallback success")
                break
            except Exception as yf_err:
                if attempt < 2:
                    time.sleep(10)
                else:
                    print(f"[{prefix}] yfinance fallback failed: {yf_err}")

    if not current_price:
        print(f"[{prefix}] Could not fetch data, skipping.")
        return None
        
    if not open_price: open_price = current_price
    daily_pct = ((current_price - open_price) / open_price) * 100
    
    yesterday_close = five_day_high = five_day_low = thirty_day_avg = None
    history_5d = []
    try:
        yf_t = yf.Ticker(cfg['yf_symbol'])
        h5d = yf_t.history(period='5d', interval='1h')
        if not h5d.empty:
            history_5d = [{"t": idx.astimezone(TZ).isoformat(), "p": round(float(row['Close']), 4)} for idx, row in h5d.iterrows()]
            five_day_high = float(h5d['High'].max())
            five_day_low  = float(h5d['Low'].min())
            today_date = now.date()
            prev = h5d[[d.date() < today_date for d in h5d.index.to_pydatetime()]]
            if not prev.empty: yesterday_close = float(prev['Close'].iloc[-1])
        h30d = yf_t.history(period='1mo', interval='1d')
        if not h30d.empty:
            thirty_day_avg = float(h30d['Close'].mean())
    except Exception:
        pass

    history_intra = load_price_history(prefix)
    history_intra = append_price(history_intra, now, current_price)
    save_price_history(history_intra, prefix)
    
    chart_intra = generate_intraday_chart(history_intra, current_price, open_price, high_price, low_price, daily_pct, cfg['name'])
    chart_5d = generate_5day_chart(history_5d, current_price)
    
    print(f"[{prefix}] Fetched: ${current_price:.4f} ({daily_pct:+.2f}%)")
    return {
        'prefix': prefix,
        'current_price': current_price,
        'open_price': open_price,
        'high_price': high_price,
        'low_price': low_price,
        'daily_pct': daily_pct,
        'yesterday_close': yesterday_close,
        'five_day_high': five_day_high,
        'five_day_low': five_day_low,
        'thirty_day_avg': thirty_day_avg,
        'chart_intraday_b64': chart_intra,
        'chart_5d_b64': chart_5d
    }


if __name__ == "__main__":

    now = datetime.now(TZ)
    
    if not is_market_open(now):
        print(f"Market is closed at {now}. Exiting to prevent stale alerts.")
        sys.exit(0)

    
    auth_header = base64.b64encode(f"{SCHWAB_APP_KEY}:{SCHWAB_APP_SECRET}".encode()).decode()
    try:
        auth_res = requests.post(
            "https://api.schwabapi.com/v1/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": SCHWAB_REFRESH_TOKEN},
            headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"}
        )
        auth_res.raise_for_status()
        auth_json = auth_res.json()
        access_token = auth_json['access_token']
        new_refresh = auth_json['refresh_token']
        print("Schwab OAuth refreshed")
    except Exception as e:
        print(f"FATAL: OAuth refresh failed: {e}")
        sys.exit(1)

    try:
        update_github_secret(new_refresh)
    except Exception as e:
        print(f"FATAL: GitHub secret update failed: {e}")
        sys.exit(1)

    all_data = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(COMMODITIES)) as executor:
        futures = [executor.submit(fetch_commodity, prefix, cfg, now, access_token) for prefix, cfg in COMMODITIES.items()]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                all_data[res.pop('prefix')] = res

    session_str = get_session_date_str(now)
    
    any_swing = False
    swing_strs = []
    swing_colors = []
    
    for prefix in ['RB', 'HO']:
        if prefix not in all_data: continue
        raw = get_repo_variable(f"LAST_SWING_INFO_{prefix}")
        last_alert_price = None
        if raw:
            try:
                info = json.loads(raw)
                if info.get("date") == session_str:
                    last_alert_price = float(info.get("price"))
            except Exception:
                pass
                
        curr = all_data[prefix]['current_price']
        ref = last_alert_price if last_alert_price else all_data[prefix]['open_price']
        swing = ((curr - ref) / ref * 100) if ref else 0.0
        
        if abs(swing) >= 2.5:
            any_swing = True
            ps = '+' if swing > 0 else ''
            swing_strs.append(f"{COMMODITIES[prefix]['name']}: {ps}{swing:.2f}%")
            swing_colors.append('#f97316' if swing > 0 else '#22c55e')
            try:
                set_repo_variable(f"LAST_SWING_INFO_{prefix}", json.dumps({"date": session_str, "price": round(curr, 4)}))
            except Exception:
                pass
                
    if any_swing:
        send_email(
            subject=f"Price Move: {' | '.join(swing_strs)}",
            all_data=all_data,
            now=now,
            alert_context={
                'label': f'Price Movement Alert',
                'action': f"Significant price movement detected from last reference point. {' | '.join(swing_strs)}",
                'action_color': swing_colors[0]
            }
        )

    if now.hour == 17 and now.minute >= 23:
        send_once_today('RACK_530', "Rack Pricing Window", all_data, now, {
            'label': 'Rack Pricing Window — 5:30 PM CT',
            'action': 'Tonight\'s rack prices go effective at 7:00 PM CT.',
            'action_color': '#f59e0b'
        })

    if now.hour == 13 and now.minute >= 23:
        send_once_today('SETTLE_130', "CME Settlement", all_data, now, {
            'label': 'CME Daily Settlement — 1:30 PM CT',
            'action': 'Official CME settlement window closed. Rack postings reference this level.',
            'action_color': '#60a5fa'
        })

    if now.hour in [0, 6, 12, 18]:
        send_once_today(f"UPDATE_{now.strftime('%H')}", f"Market Update — {now.strftime('%-I %p')}", all_data, now, {
            'label': f'Scheduled Market Update — {now.strftime("%-I:%M %p CT")}',
            'action': 'Periodic fuel market snapshot.',
            'action_color': '#475569'
        })
