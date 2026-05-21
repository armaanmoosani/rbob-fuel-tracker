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
import yfinance as yf
from base64 import b64encode
from nacl import encoding, public

# ---------------------------------------------------------------------------
# Environment Variables
# ---------------------------------------------------------------------------
SCHWAB_APP_KEY       = os.environ['SCHWAB_APP_KEY']
SCHWAB_APP_SECRET    = os.environ['SCHWAB_APP_SECRET']
SCHWAB_REFRESH_TOKEN = os.environ['SCHWAB_REFRESH_TOKEN']
GH_PAT               = os.environ['GH_PAT']
GH_REPO              = os.environ['GH_REPO']
GMAIL_USER           = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD   = os.environ['GMAIL_APP_PASSWORD']
TO_EMAIL             = os.environ['TO_EMAIL']

GH_HEADERS = {
    "Authorization": f"token {GH_PAT}",
    "Accept": "application/vnd.github.v3+json"
}

TZ          = pytz.timezone('America/Chicago')

def get_session_start(dt):
    """
    Returns the datetime of the open for the current CME trading session.
    A session opens at 5:00 PM CT the calendar day before the trade date.
    """
    import datetime
    if dt.hour >= 17:
        return dt.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        prev_day = dt - datetime.timedelta(days=1)
        return prev_day.replace(hour=17, minute=0, second=0, microsecond=0)

def get_session_date_str(dt):
    """
    Returns an ISO date string for the trading session.
    If it is after 5PM, it counts as tomorrow's trade date.
    """
    import datetime
    if dt.hour >= 17:
        return (dt + datetime.timedelta(days=1)).date().isoformat()
    return dt.date().isoformat()


# ---------------------------------------------------------------------------
# GitHub Repo Variable Helpers
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
# Price History  (persisted in a GitHub repo variable)
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
        print(f"Warning: could not save price history: {e}")


def append_price(history, ts, price):
    """Append a data point and keep only points from the current trading session."""
    session_start = get_session_start(ts)
    filtered = []
    for h in history:
        h_dt = datetime.fromisoformat(h['t'])
        if h_dt >= session_start:
            filtered.append(h)
    
    filtered.append({"t": ts.isoformat(), "p": round(price, 4)})
    return filtered


# ---------------------------------------------------------------------------
# Chart Generation — Intraday (today's session)
# ---------------------------------------------------------------------------

def generate_intraday_chart(history, current_price, open_price, high_price, low_price, daily_pct):
    """
    Render a dark-themed intraday price chart from the accumulated session history.
    Shows current price, open reference line, and today's H/L band.
    Returns base64-encoded PNG or None if not enough data.
    """
    if len(history) < 3:
        return None

    times  = [datetime.fromisoformat(h['t']).astimezone(TZ) for h in history]
    prices = [h['p'] for h in history]

    is_up      = daily_pct >= 0
    line_color = '#22c55e' if is_up else '#ef4444'
    bg_dark    = '#0f172a'
    bg_panel   = '#1e293b'
    grid_color = '#334155'
    text_color = '#94a3b8'

    fig, ax = plt.subplots(figsize=(10, 4.0))
    fig.patch.set_facecolor(bg_dark)
    ax.set_facecolor(bg_panel)

    # Subtle H/L band — today's range for context
    if high_price > 0 and low_price > 0:
        ax.axhspan(low_price, high_price, alpha=0.04, color='#94a3b8', zorder=1)

    # Price line + fill
    ax.plot(times, prices, color=line_color, linewidth=2.2, zorder=3)
    ax.fill_between(times, prices, min(prices) * 0.999,
                    alpha=0.15, color=line_color, zorder=2)

    # Current price dot
    ax.scatter([times[-1]], [prices[-1]], color=line_color, s=75, zorder=5, linewidths=0)

    # Open reference line
    if open_price and open_price > 0:
        ax.axhline(y=open_price, color='#64748b', linewidth=1.1,
                   linestyle='--', alpha=0.7, label=f'Open  ${open_price:.4f}')
        ax.legend(facecolor=bg_panel, edgecolor=grid_color,
                  labelcolor=text_color, fontsize=8.5, loc='upper left', framealpha=0.8)

    # Day H/L labels at right edge
    if high_price > 0:
        ax.annotate(f'  H  ${high_price:.4f}', xy=(times[-1], high_price),
                    color='#94a3b8', fontsize=8, alpha=0.75, va='center')
    if low_price > 0:
        ax.annotate(f'  L  ${low_price:.4f}', xy=(times[-1], low_price),
                    color='#94a3b8', fontsize=8, alpha=0.75, va='center')

    # Current price annotation
    ax.annotate(f'  ${current_price:.4f}', xy=(times[-1], prices[-1]),
                color=line_color, fontsize=11, fontweight='bold', va='center')

    # Axes
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%-I:%M %p', tz=TZ))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=0, ha='center', color=text_color, fontsize=8)
    plt.yticks(color=text_color, fontsize=8)
    ax.set_ylabel('$/gal', color=text_color, fontsize=9)

    pct_sign = '+' if is_up else ''
    ax.set_title(
        f'Wholesale Gas (/RB) Intraday   {pct_sign}{daily_pct:.2f}% vs open   '
        f'as of {times[-1].strftime("%-I:%M %p CT")}',
        color='#e2e8f0', fontsize=11, fontweight='bold', pad=10
    )

    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.5)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ---------------------------------------------------------------------------
# Chart Generation — 5-Day Trend
# ---------------------------------------------------------------------------

def generate_5day_chart(history_5d, current_price):
    """
    Render a compact 5-day hourly trend chart.
    Uses a neutral blue line — no directional color since this spans multiple days.
    Returns base64-encoded PNG or None if not enough data.
    """
    if len(history_5d) < 5:
        return None

    times  = [datetime.fromisoformat(h['t']).astimezone(TZ) for h in history_5d]
    prices = [h['p'] for h in history_5d]

    bg_dark    = '#0f172a'
    bg_panel   = '#1e293b'
    grid_color = '#334155'
    text_color = '#94a3b8'
    line_color = '#60a5fa'   # neutral blue — not directional

    fig, ax = plt.subplots(figsize=(10, 2.8))
    fig.patch.set_facecolor(bg_dark)
    ax.set_facecolor(bg_panel)

    ax.plot(times, prices, color=line_color, linewidth=1.8, zorder=3)
    ax.fill_between(times, prices, min(prices) * 0.999,
                    alpha=0.10, color=line_color, zorder=2)
    ax.scatter([times[-1]], [prices[-1]], color='#22c55e', s=60, zorder=5, linewidths=0)
    ax.annotate(f'  ${current_price:.4f}', xy=(times[-1], prices[-1]),
                color='#22c55e', fontsize=9, fontweight='bold', va='center')

    # Day separators
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%a', tz=TZ))
    ax.xaxis.set_major_locator(mdates.DayLocator(tz=TZ))
    plt.xticks(rotation=0, ha='center', color=text_color, fontsize=8)
    plt.yticks(color=text_color, fontsize=8)
    ax.set_ylabel('$/gal', color=text_color, fontsize=9)
    ax.set_title('5-Day Price Trend', color='#e2e8f0', fontsize=10, fontweight='bold', pad=8)

    for spine in ax.spines.values():
        spine.set_edgecolor(grid_color)
    ax.tick_params(colors=text_color)
    ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.5)
    # Vertical day-boundary lines
    ax.xaxis.grid(True, color=grid_color, linewidth=0.8, alpha=0.4)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ---------------------------------------------------------------------------
# Email Builder
# ---------------------------------------------------------------------------

def build_html_email(
    subject, current_price, open_price, high_price, low_price, daily_pct,
    now, alert_context, chart_intraday_b64, chart_5d_b64=None,
    yesterday_close=None, five_day_high=None, five_day_low=None, thirty_day_avg=None
):
    """
    Build the HTML email body.
    - Two stats rows: today's OHLC + weekly/monthly context
    - Today's range bar (purely factual, no opinion)
    - Alert banner (factual context about what triggered this email)
    - Intraday chart (primary)
    - 5-day chart (secondary)
    alert_context keys: 'label', 'action', 'action_color'
    """
    cid_intra = uuid.uuid4().hex
    cid_5d    = uuid.uuid4().hex

    is_up      = daily_pct >= 0
    pct_color  = '#22c55e' if is_up else '#ef4444'
    pct_bg     = '#0a2010' if is_up else '#200a0a'
    arrow      = '\u25b2' if is_up else '\u25bc'
    pct_sign   = '+' if is_up else ''
    dollar_chg = current_price - open_price

    # ---------- Today's range bar (factual position) ----------
    price_range  = (high_price - low_price) if (high_price > 0 and low_price > 0) else 0
    range_pct    = ((current_price - low_price) / price_range * 100) if price_range > 0 else 50.0
    range_bar_pos = min(max(range_pct, 2), 98)

    # ---------- Context stats (second row) ----------
    def fmt_price(p):
        return f'${p:.4f}' if p else 'N/A'

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

    # ---------- Chart sections ----------
    if chart_intraday_b64:
        intraday_section = (
            f'<img src="cid:{cid_intra}" alt="Intraday Price Chart" '
            f'style="width:100%;border-radius:6px;display:block;"/>'
        )
    else:
        intraday_section = (
            '<p style="color:#475569;font-size:11px;margin:0;">'
            'Intraday chart will appear after the first few data points accumulate.</p>'
        )

    if chart_5d_b64:
        fiveday_section = (
            f'<img src="cid:{cid_5d}" alt="5-Day Trend Chart" '
            f'style="width:100%;border-radius:6px;display:block;"/>'
        )
    else:
        fiveday_section = ''

    # ---------- Alert banner ----------
    action_line = ''
    if alert_context.get('action'):
        ac = alert_context['action_color']
        action_line = f'''
    <div style="padding:14px 22px;background:#0b1829;
                border-left:4px solid {ac};border-right:1px solid #1e293b;">
      <p style="margin:0 0 3px;font-size:9px;color:{ac};
                text-transform:uppercase;letter-spacing:0.1em;font-weight:700;">
        {alert_context['label']}
      </p>
      <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
        {alert_context['action']}
      </p>
    </div>'''

    # ---------- Source label ----------
    source_label = (
        'Live data via Charles Schwab Trader API'
        if data_source == 'schwab'
        else 'Delayed data via Yahoo Finance (RB=F) \u2014 approx. 15 min'
    )

    # ---------- Plain-text fallback ----------
    plain_text = (
        f"{alert_context.get('label', 'RBOB Alert')}\n"
        f"{'=' * 44}\n"
        f"Price:           ${current_price:.4f} / gal\n"
        f"Change:          {arrow} {pct_sign}{daily_pct:.2f}%  ({pct_sign}${dollar_chg:.4f})\n"
        f"Open:            ${open_price:.4f}\n"
        f"Day High:        ${high_price:.4f}\n"
        f"Day Low:         ${low_price:.4f}\n"
    )
    if yesterday_close:
        plain_text += f"Yesterday Close: ${yesterday_close:.4f}\n"
    if five_day_high and five_day_low:
        plain_text += f"5-Day Range:     ${five_day_low:.4f} - ${five_day_high:.4f}\n"
    if thirty_day_avg:
        plain_text += f"30-Day Avg:      ${thirty_day_avg:.4f}\n"
    plain_text += f"As of:           {now.strftime('%I:%M %p CT  %A, %b %d %Y')}\n"
    if alert_context.get('action'):
        plain_text += f"\n{alert_context['action']}\n"

    # ---------- HTML ----------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:20px 10px;background:#070c18;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">

  <div style="max-width:620px;margin:0 auto;">

    <!-- ══ HEADER ══ -->
    <div style="background:#0d1526;border-radius:10px 10px 0 0;
                padding:13px 20px;border:1px solid #1a2640;border-bottom:none;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="margin:0;font-size:10px;color:#3d5070;
                      letter-spacing:0.1em;text-transform:uppercase;font-weight:600;">
              /RB &nbsp;&middot;&nbsp; RBOB Gasoline Futures &nbsp;&middot;&nbsp; NYMEX CME
            </p>
          </td>
          <td style="text-align:right;">
            <p style="margin:0;font-size:10px;color:#2d3d55;">
              {now.strftime('%-I:%M %p CT &nbsp;&middot;&nbsp; %b %-d, %Y')}
            </p>
          </td>
        </tr>
      </table>
    </div>

    <!-- ══ CURRENT PRICE ══ -->
    <div style="background:#111e35;padding:20px 20px 16px;
                border-left:1px solid #1a2640;border-right:1px solid #1a2640;">
      <p style="margin:0 0 2px;font-size:9px;color:#3d5070;
                letter-spacing:0.1em;text-transform:uppercase;font-weight:600;">Current Price</p>
      <p style="margin:0;font-size:50px;font-weight:700;color:#f0f4f8;
                letter-spacing:-1.5px;line-height:1.05;">
        ${current_price:.4f}
        <span style="font-size:14px;color:#3d5070;font-weight:400;">&nbsp;/gal</span>
      </p>
      <div style="display:inline-block;margin-top:9px;padding:4px 13px;
                  background:{pct_bg};border-radius:20px;border:1px solid {pct_color}33;">
        <span style="font-size:14px;font-weight:700;color:{pct_color};">
          {arrow}&nbsp;{pct_sign}{daily_pct:.2f}%
        </span>
        <span style="font-size:12px;color:{pct_color};opacity:0.8;">
          &nbsp;({pct_sign}${dollar_chg:.4f})
        </span>
        <span style="font-size:10px;color:#3d5070;">&nbsp;vs open</span>
      </div>
    </div>

    <!-- ══ TODAY'S STATS ROW ══ -->
    <div style="background:#0d1929;border-left:1px solid #1a2640;
                border-right:1px solid #1a2640;border-top:1px solid #1a2640;">
      <p style="margin:0;padding:7px 20px 0;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">
        Today's Session
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">Open</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">
              ${open_price:.4f}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#22c55e;">
              {f"${high_price:.4f}" if high_price > 0 else "N/A"}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#ef4444;">
              {f"${low_price:.4f}" if low_price > 0 else "N/A"}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">$ Change</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:{pct_color};">
              {pct_sign}${dollar_chg:.4f}
            </p>
          </td>
        </tr>
      </table>
    </div>

    <!-- ══ CONTEXT STATS ROW ══ -->
    <div style="background:#0a1422;border-left:1px solid #1a2640;
                border-right:1px solid #1a2640;border-top:1px solid #141f30;">
      <p style="margin:0;padding:7px 20px 0;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">
        Historical Context
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">Yest. Close</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">
              {yest_cell}{yest_chg}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">5-Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">
              {ctx_5d_high}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;border-right:1px solid #1a2640;
                                  text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">5-Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">
              {ctx_5d_low}
            </p>
          </td>
          <td width="25%" style="padding:7px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;
                      text-transform:uppercase;letter-spacing:0.07em;">30-Day Avg</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">
              {ctx_30d_avg}{ctx_30d_vs}
            </p>
          </td>
        </tr>
      </table>
    </div>

    <!-- ══ TODAY'S RANGE BAR ══ -->
    <div style="background:#0d1929;padding:12px 20px 16px;
                border-left:1px solid #1a2640;border-right:1px solid #1a2640;
                border-top:1px solid #141f30;">
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:8px;">
        <tr>
          <td>
            <p style="margin:0;font-size:8px;color:#2d3d55;
                      text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">
              Position in Today's Range
            </p>
          </td>
          <td style="text-align:right;">
            <p style="margin:0;font-size:10px;color:#556678;font-weight:600;">
              {range_pct:.0f}% of day range &nbsp;
              (L: ${low_price:.4f} &nbsp;&ndash;&nbsp; H: ${high_price:.4f})
            </p>
          </td>
        </tr>
      </table>
      <div style="position:relative;height:4px;background:#1a2640;border-radius:2px;">
        <div style="height:4px;width:{range_bar_pos:.0f}%;
                    background:linear-gradient(to right,#2d4a6a,#4a6a8a);
                    border-radius:2px;"></div>
        <div style="position:absolute;top:-5px;left:calc({range_bar_pos:.0f}% - 7px);
                    width:14px;height:14px;border-radius:50%;
                    background:{pct_color};border:2px solid #0d1929;"></div>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;">
        <tr>
          <td style="font-size:9px;color:#2d3d55;">Low &nbsp;${low_price:.4f}</td>
          <td style="text-align:right;font-size:9px;color:#2d3d55;">High &nbsp;${high_price:.4f}</td>
        </tr>
      </table>
    </div>

    <!-- ══ ALERT BANNER ══ -->
    {action_line}

    <!-- ══ INTRADAY CHART ══ -->
    <div style="background:#111e35;padding:16px 20px 18px;
                border-left:1px solid #1a2640;border-right:1px solid #1a2640;
                border-top:1px solid #141f30;">
      <p style="margin:0 0 10px;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">
        Intraday Price Chart &mdash; Today's Session
      </p>
      {intraday_section}
    </div>

    <!-- ══ 5-DAY CHART ══ -->
    {'<div style="background:#0d1526;padding:14px 20px 16px;border-left:1px solid #1a2640;border-right:1px solid #1a2640;border-top:1px solid #101828;"><p style="margin:0 0 10px;font-size:8px;color:#2d3d55;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">5-Day Trend &mdash; Mon through Today</p>' + fiveday_section + '</div>' if fiveday_section else ''}

    <!-- ══ FOOTER ══ -->
    <div style="background:#070c18;border-radius:0 0 10px 10px;padding:10px 20px;
                border:1px solid #1a2640;border-top:none;">
      <p style="margin:0;font-size:9px;color:#1e2d40;line-height:1.6;">
        Automated by
        <a href="https://github.com/{GH_REPO}" style="color:#2d4060;text-decoration:none;">
          armaanmoosani/rbob-fuel-tracker
        </a>
        &nbsp;&middot;&nbsp; GitHub Actions &nbsp;&middot;&nbsp; {source_label}
      </p>
    </div>

  </div>
</body>
</html>"""

    return cid_intra, cid_5d, plain_text, html


# ---------------------------------------------------------------------------
# Email Dispatch
# ---------------------------------------------------------------------------

def send_email(
    subject, current_price, open_price, high_price, low_price, daily_pct,
    now, alert_context, chart_intraday_b64=None, chart_5d_b64=None,
    yesterday_close=None, five_day_high=None, five_day_low=None, thirty_day_avg=None
):
    """Assemble and send the HTML email with both charts."""
    try:
        cid_intra, cid_5d, plain_text, html_body = build_html_email(
            subject, current_price, open_price, high_price, low_price, daily_pct,
            now, alert_context, chart_intraday_b64, chart_5d_b64,
            yesterday_close, five_day_high, five_day_low, thirty_day_avg
        )

        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL

        alt = MIMEMultipart('alternative')
        alt.attach(MIMEText(plain_text, 'plain'))
        alt.attach(MIMEText(html_body,  'html'))
        msg.attach(alt)

        if chart_intraday_b64:
            img = MIMEImage(base64.b64decode(chart_intraday_b64), 'png')
            img.add_header('Content-ID', f'<{cid_intra}>')
            img.add_header('Content-Disposition', 'inline', filename='rb_intraday.png')
            msg.attach(img)

        if chart_5d_b64:
            img2 = MIMEImage(base64.b64decode(chart_5d_b64), 'png')
            img2.add_header('Content-ID', f'<{cid_5d}>')
            img2.add_header('Content-Disposition', 'inline', filename='rb_5day.png')
            msg.attach(img2)

        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent: {subject}")

    except Exception as e:
        print(f"Email send failed: {e}")


# ---------------------------------------------------------------------------
# Deduplication  (each alert key fires at most once per CT calendar day)
# ---------------------------------------------------------------------------

def already_sent_today(key):
    session_str = get_session_date_str(datetime.now(TZ))
    return get_repo_variable(f"LAST_ALERT_{key}") == session_str


def mark_sent_today(key):
    try:
        session_str = get_session_date_str(datetime.now(TZ))
        set_repo_variable(f"LAST_ALERT_{key}", session_str)
    except Exception as e:
        print(f"Warning: could not record sent state for {key}: {e}")


def send_once_today(
    key, subject, current_price, open_price, high_price, low_price, daily_pct,
    now, alert_context, chart_intraday_b64=None, chart_5d_b64=None,
    yesterday_close=None, five_day_high=None, five_day_low=None, thirty_day_avg=None
):
    """Send an alert at most once per CT calendar day for the given key."""
    if already_sent_today(key):
        print(f"Skipping '{key}' — already sent today")
        return
    send_email(
        subject, current_price, open_price, high_price, low_price, daily_pct,
        now, alert_context, chart_intraday_b64, chart_5d_b64,
        yesterday_close, five_day_high, five_day_low, thirty_day_avg
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
    print("GitHub secret updated")


# ===========================================================================
# MAIN EXECUTION
# ===========================================================================

# --- Weekend / Market-Hours Guard ---
now     = datetime.now(TZ)
weekday = now.weekday()   # 0=Mon … 5=Sat, 6=Sun

if weekday == 5:
    print("Saturday — /RB market closed. Exiting.")
    sys.exit(0)
if weekday == 6 and now.hour < 17:
    print("Sunday before 5:00 PM CT market open. Exiting.")
    sys.exit(0)

# --- Schwab OAuth Token Refresh ---
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
    auth_json    = auth_res.json()
    access_token = auth_json['access_token']
    new_refresh  = auth_json['refresh_token']
    print("Schwab OAuth refreshed")
except Exception as e:
    try:
        msg = MIMEText(
            f"OAuth token refresh failed — tracker is DOWN.\n\n"
            f"Error: {e}\n\n"
            f"ACTION REQUIRED:\n"
            f"1. Go to developer.schwab.com\n"
            f"2. Complete the OAuth handshake\n"
            f"3. Update SCHWAB_REFRESH_TOKEN in GitHub Secrets."
        )
        msg['Subject'] = "RBOB Tracker — Auth Failure (Action Required)"
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL
        srv = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        srv.starttls()
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        srv.quit()
    except Exception:
        pass
    print(f"FATAL: OAuth refresh failed: {e}")
    sys.exit(1)

# Store new token BEFORE anything else (old token is now invalidated)
try:
    update_github_secret(new_refresh)
except Exception as e:
    try:
        msg = MIMEText(
            f"New Schwab token obtained but FAILED to save to GitHub Secrets.\n\n"
            f"Error: {e}\n\n"
            f"The tracker WILL break on the next run.\n"
            f"Manually update SCHWAB_REFRESH_TOKEN in GitHub Secrets NOW."
        )
        msg['Subject'] = "RBOB Tracker — GitHub Secret Update Failed (Action Required)"
        msg['From']    = GMAIL_USER
        msg['To']      = TO_EMAIL
        srv = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        srv.starttls()
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
        srv.quit()
    except Exception:
        pass
    print(f"FATAL: GitHub secret update failed: {e}")
    sys.exit(1)

# --- Fetch Live /RB Price (Schwab primary, yfinance fallback) ---
data_source   = None
current_price = open_price = high_price = low_price = None

try:
    quote_res = requests.get(
        "https://api.schwabapi.com/marketdata/v1/quotes?symbols=/RB",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15
    )
    quote_res.raise_for_status()
    rb            = quote_res.json()['/RB']['quote']
    current_price = float(rb['lastPrice'])
    open_price    = float(rb['openPrice'])
    high_price    = float(rb.get('highPrice', 0.0))
    low_price     = float(rb.get('lowPrice', 0.0))
    data_source   = 'schwab'
    print("Market data: Schwab real-time")
except Exception as schwab_err:
    print(f"Schwab market data failed ({schwab_err}) — falling back to yfinance")

if data_source is None:
    try:
        rb_yf         = yf.Ticker("RB=F")
        fi            = rb_yf.fast_info
        current_price = float(fi['last_price'])
        hist          = rb_yf.history(period='1d', interval='5m')
        if not hist.empty:
            open_price = float(hist['Open'].iloc[0])
            high_price = float(hist['High'].max())
            low_price  = float(hist['Low'].min())
        else:
            open_price = current_price
            high_price = 0.0
            low_price  = 0.0
        data_source = 'yfinance'
        print("Market data: yfinance fallback (RB=F, ~15 min delayed)")
    except Exception as yf_err:
        print(f"yfinance fallback also failed: {yf_err}")
        sys.exit(1)

if not open_price or open_price == 0:
    open_price = current_price

daily_pct = ((current_price - open_price) / open_price) * 100 if open_price else 0.0

print(f"Wholesale Gas (/RB): ${current_price:.4f} | {daily_pct:+.2f}% | H: ${high_price:.4f} | L: ${low_price:.4f}")

# --- Fetch 5-day & 30-day context from yfinance (always, regardless of price source) ---
yesterday_close = five_day_high = five_day_low = thirty_day_avg = None
history_5d = []

try:
    rb_ctx = yf.Ticker("RB=F")

    # 5-day hourly — for 5-day chart, yesterday close, and 5-day H/L
    h5d = rb_ctx.history(period='5d', interval='1h')
    if not h5d.empty:
        history_5d  = [
            {"t": idx.astimezone(TZ).isoformat(), "p": round(float(row['Close']), 4)}
            for idx, row in h5d.iterrows()
        ]
        five_day_high = float(h5d['High'].max())
        five_day_low  = float(h5d['Low'].min())
        # Yesterday's close = last bar whose date is before today CT
        today_date = now.date()
        prev = h5d[[d.date() < today_date for d in h5d.index.to_pydatetime()]]
        if not prev.empty:
            yesterday_close = float(prev['Close'].iloc[-1])

    # 30-day daily — for 30-day average
    h30d = rb_ctx.history(period='1mo', interval='1d')
    if not h30d.empty:
        thirty_day_avg = float(h30d['Close'].mean())

    print(f"Context: yest=${yesterday_close:.4f if yesterday_close else 'N/A'} "
          f"5d H/L=${five_day_high:.4f if five_day_high else 'N/A'}/"
          f"${five_day_low:.4f if five_day_low else 'N/A'} "
          f"30dAvg=${thirty_day_avg:.4f if thirty_day_avg else 'N/A'}")
except Exception as e:
    print(f"Warning: 5-day context fetch failed: {e}")

# --- Update & persist intraday price history ---
history_intra = load_price_history()
history_intra = append_price(history_intra, now, current_price)
save_price_history(history_intra)

# --- Generate charts ---
chart_intraday = generate_intraday_chart(
    history_intra, current_price, open_price, high_price, low_price, daily_pct
)
print("Intraday chart: generated" if chart_intraday else "Intraday chart: not enough data yet")

chart_5d = generate_5day_chart(history_5d, current_price)
print("5-day chart: generated" if chart_5d else "5-day chart: not enough data")

# Shared kwargs passed to every send_email / send_once_today call
ctx = dict(
    chart_intraday_b64=chart_intraday,
    chart_5d_b64=chart_5d,
    yesterday_close=yesterday_close,
    five_day_high=five_day_high,
    five_day_low=five_day_low,
    thirty_day_avg=thirty_day_avg,
)

# ===========================================================================
# Alert Logic
# ===========================================================================

# 1. Smart Swing Alert — fires any time price moves ±2.5% from last alert reference
session_str    = get_session_date_str(now)
raw_swing_info = get_repo_variable("LAST_SWING_INFO")
last_alert_price = None

if raw_swing_info:
    try:
        info = json.loads(raw_swing_info)
        if info.get("date") == session_str:
            last_alert_price = float(info.get("price"))
    except Exception:
        pass

ref_price      = last_alert_price if last_alert_price else open_price
swing_from_ref = ((current_price - ref_price) / ref_price * 100) if ref_price else 0.0

if abs(swing_from_ref) >= 2.5:
    ps   = '+' if swing_from_ref > 0 else ''
    send_email(
        subject=f"Wholesale Gas (/RB) Price Move: {ps}{swing_from_ref:.2f}% — ${current_price:.4f}/gal",
        current_price=current_price, open_price=open_price,
        high_price=high_price, low_price=low_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': f'Price Movement Alert — {ps}{swing_from_ref:.2f}% from Last Reference',
            'action': (
                f'Wholesale Gas (/RB) has moved {ps}{swing_from_ref:.2f}% from the last alert reference '
                f'(${ref_price:.4f}). Current: ${current_price:.4f}/gal. '
                f'Day range: ${low_price:.4f} \u2013 ${high_price:.4f}.'
            ),
            'action_color': '#f97316' if swing_from_ref > 0 else '#22c55e',
        },
        **ctx
    )
    try:
        set_repo_variable("LAST_SWING_INFO",
                          json.dumps({"date": session_str, "price": round(current_price, 4)}))
    except Exception as e:
        print(f"Warning: could not save swing info: {e}")

# 2. 5:30 PM rack-price window (±7 min buffer for cron timing variance)
if now.hour == 17 and 23 <= now.minute < 38:
    send_once_today(
        key='RACK_530',
        subject=f"Wholesale Gas (/RB) Rack Window — ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price,
        high_price=high_price, low_price=low_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': 'Rack Pricing Window — 5:30 PM CT',
            'action': (
                f'Graves Oil releases tonight\'s prices between 5:00 PM and 9:30 PM (effective at 7:00 PM CT). '
                f'Current Wholesale Gas (/RB): ${current_price:.4f}/gal ({daily_pct:+.2f}% from open of ${open_price:.4f}). '
                f'Day range: ${low_price:.4f} \u2013 ${high_price:.4f} '
                f'(${abs(high_price - low_price):.4f} spread).'
            ),
            'action_color': '#f59e0b',
        },
        **ctx
    )

# 3. 1:30 PM CME settlement (±7 min buffer)
if now.hour == 13 and 23 <= now.minute < 38:
    send_once_today(
        key='SETTLE_130',
        subject=f"Wholesale Gas (/RB) Settlement — ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price,
        high_price=high_price, low_price=low_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': 'CME Daily Settlement — 1:30 PM CT',
            'action': (
                f'Official CME Wholesale Gas (/RB) settlement: ${current_price:.4f}/gal '
                f'({daily_pct:+.2f}% from open of ${open_price:.4f}). '
                f'Day range: ${low_price:.4f} \u2013 ${high_price:.4f}. '
                f'Tonight\'s rack postings are expected to reference this settlement level.'
            ),
            'action_color': '#60a5fa',
        },
        **ctx
    )

# 4. 6-hour status updates (8-min buffer)
if now.hour in [0, 6, 12, 18] and 0 <= now.minute < 8:
    hour_key   = f"UPDATE_{now.strftime('%H')}"
    time_label = now.strftime('%-I %p')
    send_once_today(
        key=hour_key,
        subject=f"Wholesale Gas (/RB) {time_label} Update — ${current_price:.4f}/gal ({daily_pct:+.2f}%)",
        current_price=current_price, open_price=open_price,
        high_price=high_price, low_price=low_price, daily_pct=daily_pct,
        now=now,
        alert_context={
            'label': f'Scheduled Market Update — {now.strftime("%-I:%M %p CT")}',
            'action': (
                f'Current Wholesale Gas (/RB): ${current_price:.4f}/gal ({daily_pct:+.2f}% from open of ${open_price:.4f}). '
                f'Day range: ${low_price:.4f} \u2013 ${high_price:.4f} '
                f'(${abs(high_price - low_price):.4f} spread).'
            ),
            'action_color': '#475569',
        },
        **ctx
    )
