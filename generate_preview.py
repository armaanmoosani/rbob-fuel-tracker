"""
generate_preview.py — Renders a sample RBOB tracker email as email_preview.html
using real market data from Yahoo Finance (no credentials required).

Usage:
    python generate_preview.py

Then open email_preview.html in any browser.
Change PREVIEW_MODE near the bottom to see different alert types:
    'rack'        — 5:30 PM rack window alert
    'settlement'  — 1:30 PM CME settlement
    'swing'       — significant price move
    'routine'     — scheduled 6-hour update
"""

import os, io, base64, uuid
from datetime import datetime
import pytz
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

TZ = pytz.timezone('America/Chicago')


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------

def get_market_data():
    ticker = yf.Ticker("RB=F")
    fi     = ticker.fast_info
    current_price = float(fi['last_price'])

    # Intraday 5-min bars
    hist_intra = ticker.history(period='1d', interval='5m')
    if not hist_intra.empty:
        open_price = float(hist_intra['Open'].iloc[0])
        high_price = float(hist_intra['High'].max())
        low_price  = float(hist_intra['Low'].min())
        history_intra = [
            {"t": idx.astimezone(TZ).isoformat(), "p": round(float(row['Close']), 4)}
            for idx, row in hist_intra.iterrows()
        ]
    else:
        open_price    = current_price
        high_price    = current_price
        low_price     = current_price
        history_intra = [{"t": datetime.now(TZ).isoformat(), "p": current_price}]

    # 5-day hourly bars
    history_5d      = []
    yesterday_close = None
    five_day_high   = None
    five_day_low    = None
    thirty_day_avg  = None

    hist_5d = ticker.history(period='5d', interval='1h')
    if not hist_5d.empty:
        history_5d    = [
            {"t": idx.astimezone(TZ).isoformat(), "p": round(float(row['Close']), 4)}
            for idx, row in hist_5d.iterrows()
        ]
        five_day_high = float(hist_5d['High'].max())
        five_day_low  = float(hist_5d['Low'].min())
        today_date    = datetime.now(TZ).date()
        prev = hist_5d[[d.date() < today_date for d in hist_5d.index.to_pydatetime()]]
        if not prev.empty:
            yesterday_close = float(prev['Close'].iloc[-1])

    # 30-day daily close average
    hist_30d = ticker.history(period='1mo', interval='1d')
    if not hist_30d.empty:
        thirty_day_avg = float(hist_30d['Close'].mean())

    return (current_price, open_price, high_price, low_price,
            history_intra, history_5d,
            yesterday_close, five_day_high, five_day_low, thirty_day_avg)


# ---------------------------------------------------------------------------
# Intraday Chart
# ---------------------------------------------------------------------------

def generate_intraday_chart(history, current_price, open_price, high_price, low_price, daily_pct):
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

    if high_price > 0 and low_price > 0:
        ax.axhspan(low_price, high_price, alpha=0.04, color='#94a3b8', zorder=1)

    ax.plot(times, prices, color=line_color, linewidth=2.2, zorder=3)
    ax.fill_between(times, prices, min(prices) * 0.999,
                    alpha=0.15, color=line_color, zorder=2)
    ax.scatter([times[-1]], [prices[-1]], color=line_color, s=75, zorder=5, linewidths=0)

    if open_price and open_price > 0:
        ax.axhline(y=open_price, color='#64748b', linewidth=1.1,
                   linestyle='--', alpha=0.7, label=f'Open  ${open_price:.4f}')
        ax.legend(facecolor=bg_panel, edgecolor=grid_color,
                  labelcolor=text_color, fontsize=8.5, loc='upper left', framealpha=0.8)

    if high_price > 0:
        ax.annotate(f'  H  ${high_price:.4f}', xy=(times[-1], high_price),
                    color='#94a3b8', fontsize=8, alpha=0.75, va='center')
    if low_price > 0:
        ax.annotate(f'  L  ${low_price:.4f}', xy=(times[-1], low_price),
                    color='#94a3b8', fontsize=8, alpha=0.75, va='center')

    ax.annotate(f'  ${current_price:.4f}', xy=(times[-1], prices[-1]),
                color=line_color, fontsize=11, fontweight='bold', va='center')

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
# 5-Day Trend Chart
# ---------------------------------------------------------------------------

def generate_5day_chart(history_5d, current_price):
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
    ax.xaxis.grid(True, color=grid_color, linewidth=0.8, alpha=0.4)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg_dark)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ---------------------------------------------------------------------------
# Email Builder — mirrors main.py exactly, uses data:URI for browser preview
# ---------------------------------------------------------------------------

def build_html_email(
    subject, current_price, open_price, high_price, low_price, daily_pct,
    now, alert_context, chart_intraday_b64, chart_5d_b64=None,
    yesterday_close=None, five_day_high=None, five_day_low=None, thirty_day_avg=None,
    data_source='schwab'
):
    is_up      = daily_pct >= 0
    pct_color  = '#22c55e' if is_up else '#ef4444'
    pct_bg     = '#0a2010' if is_up else '#200a0a'
    arrow      = '\u25b2' if is_up else '\u25bc'
    pct_sign   = '+' if is_up else ''
    dollar_chg = current_price - open_price

    price_range   = (high_price - low_price) if (high_price > 0 and low_price > 0) else 0
    range_pct     = ((current_price - low_price) / price_range * 100) if price_range > 0 else 50.0
    range_bar_pos = min(max(range_pct, 2), 98)

    def fmt(p): return f'${p:.4f}' if p else 'N/A'

    yest_cell = fmt(yesterday_close)
    yest_chg  = ''
    if yesterday_close:
        yc = ((current_price - yesterday_close) / yesterday_close) * 100
        col = '#22c55e' if yc >= 0 else '#ef4444'
        yest_chg = f'<br><span style="font-size:11px;color:{col};">{("+" if yc >= 0 else "")}{yc:.2f}%</span>'

    ctx_30d_vs = ''
    if thirty_day_avg:
        diff = ((current_price - thirty_day_avg) / thirty_day_avg) * 100
        col  = '#22c55e' if diff >= 0 else '#ef4444'
        ctx_30d_vs = f'<br><span style="font-size:11px;color:{col};">{("+" if diff >= 0 else "")}{diff:.2f}% vs avg</span>'

    # For the browser preview, embed charts inline as data URIs
    if chart_intraday_b64:
        intraday_section = (
            f'<img src="data:image/png;base64,{chart_intraday_b64}" '
            f'alt="Intraday Price Chart" '
            f'style="width:100%;border-radius:6px;display:block;"/>'
        )
    else:
        intraday_section = (
            '<p style="color:#475569;font-size:11px;margin:0;">'
            'Intraday chart will appear after the first few data points accumulate.</p>'
        )

    fiveday_section = ''
    if chart_5d_b64:
        fiveday_section = (
            f'<img src="data:image/png;base64,{chart_5d_b64}" '
            f'alt="5-Day Trend Chart" '
            f'style="width:100%;border-radius:6px;display:block;"/>'
        )

    action_line = ''
    if alert_context.get('action'):
        ac = alert_context['action_color']
        action_line = f'''
    <div style="padding:14px 22px;background:#0b1829;
                border-left:4px solid {ac};border-right:1px solid #1a2640;">
      <p style="margin:0 0 3px;font-size:9px;color:{ac};
                text-transform:uppercase;letter-spacing:0.1em;font-weight:700;">
        {alert_context['label']}
      </p>
      <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.6;">
        {alert_context['action']}
      </p>
    </div>'''

    source_label = (
        'Live data via Charles Schwab Trader API'
        if data_source == 'schwab'
        else 'Delayed data via Yahoo Finance (RB=F) \u2014 approx. 15 min'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:20px 10px;background:#070c18;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">

  <div style="max-width:620px;margin:0 auto;">

    <!-- HEADER -->
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

    <!-- CURRENT PRICE -->
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

    <!-- TODAY'S SESSION STATS -->
    <div style="background:#0d1929;border-left:1px solid #1a2640;
                border-right:1px solid #1a2640;border-top:1px solid #1a2640;">
      <p style="margin:0;padding:7px 20px 0;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">Today's Session</p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">Open</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">${open_price:.4f}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#22c55e;">{f"${high_price:.4f}" if high_price > 0 else "N/A"}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#ef4444;">{f"${low_price:.4f}" if low_price > 0 else "N/A"}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">$ Change</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:{pct_color};">{pct_sign}${dollar_chg:.4f}</p>
          </td>
        </tr>
      </table>
    </div>

    <!-- HISTORICAL CONTEXT STATS -->
    <div style="background:#0a1422;border-left:1px solid #1a2640;
                border-right:1px solid #1a2640;border-top:1px solid #141f30;">
      <p style="margin:0;padding:7px 20px 0;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">Historical Context</p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">Yest. Close</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">{yest_cell}{yest_chg}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">5-Day High</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">{fmt(five_day_high)}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;border-right:1px solid #1a2640;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">5-Day Low</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">{fmt(five_day_low)}</p>
          </td>
          <td width="25%" style="padding:6px 10px 10px;text-align:center;">
            <p style="margin:0;font-size:8px;color:#3d5070;text-transform:uppercase;letter-spacing:0.07em;">30-Day Avg</p>
            <p style="margin:4px 0 0;font-size:14px;font-weight:600;color:#8899aa;">{fmt(thirty_day_avg)}{ctx_30d_vs}</p>
          </td>
        </tr>
      </table>
    </div>

    <!-- TODAY'S RANGE BAR -->
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
              (L:&nbsp;${low_price:.4f} &nbsp;&ndash;&nbsp; H:&nbsp;${high_price:.4f})
            </p>
          </td>
        </tr>
      </table>
      <div style="position:relative;height:4px;background:#1a2640;border-radius:2px;">
        <div style="height:4px;width:{range_bar_pos:.0f}%;
                    background:linear-gradient(to right,#2d4a6a,#4a6a8a);border-radius:2px;"></div>
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

    <!-- ALERT BANNER -->
    {action_line}

    <!-- INTRADAY CHART -->
    <div style="background:#111e35;padding:16px 20px 18px;
                border-left:1px solid #1a2640;border-right:1px solid #1a2640;
                border-top:1px solid #141f30;">
      <p style="margin:0 0 10px;font-size:8px;color:#2d3d55;
                text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">
        Intraday Price Chart &mdash; Today's Session
      </p>
      {intraday_section}
    </div>

    <!-- 5-DAY CHART -->
    {'<div style="background:#0d1526;padding:14px 20px 16px;border-left:1px solid #1a2640;border-right:1px solid #1a2640;border-top:1px solid #101828;"><p style="margin:0 0 10px;font-size:8px;color:#2d3d55;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;">5-Day Trend &mdash; Mon through Today</p>' + fiveday_section + '</div>' if fiveday_section else ''}

    <!-- FOOTER -->
    <div style="background:#070c18;border-radius:0 0 10px 10px;padding:10px 20px;
                border:1px solid #1a2640;border-top:none;">
      <p style="margin:0;font-size:9px;color:#1e2d40;line-height:1.6;">
        Automated by
        <a href="https://github.com/armaanmoosani/rbob-fuel-tracker"
           style="color:#2d4060;text-decoration:none;">armaanmoosani/rbob-fuel-tracker</a>
        &nbsp;&middot;&nbsp; GitHub Actions &nbsp;&middot;&nbsp; {source_label}
      </p>
    </div>

  </div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Fetching market data from Yahoo Finance...")
    (current_price, open_price, high_price, low_price,
     history_intra, history_5d,
     yesterday_close, five_day_high, five_day_low, thirty_day_avg) = get_market_data()

    daily_pct = ((current_price - open_price) / open_price) * 100
    now       = datetime.now(TZ)

    print(f"  /RB: ${current_price:.4f}  |  Open: ${open_price:.4f}  |  "
          f"H: ${high_price:.4f}  L: ${low_price:.4f}  |  {daily_pct:+.2f}%")
    if yesterday_close:
        print(f"  Yesterday close: ${yesterday_close:.4f}")
    if five_day_high:
        print(f"  5-day H/L: ${five_day_high:.4f} / ${five_day_low:.4f}")
    if thirty_day_avg:
        print(f"  30-day avg: ${thirty_day_avg:.4f}")

    print("Generating charts...")
    chart_intraday = generate_intraday_chart(
        history_intra, current_price, open_price, high_price, low_price, daily_pct
    )
    chart_5d = generate_5day_chart(history_5d, current_price)
    print(f"  Intraday: {'OK (' + str(len(history_intra)) + ' pts)' if chart_intraday else 'skipped'}")
    print(f"  5-day:    {'OK (' + str(len(history_5d)) + ' pts)' if chart_5d else 'skipped'}")

    # -----------------------------------------------------------------------
    # PREVIEW_MODE: 'rack' | 'settlement' | 'swing' | 'routine'
    # -----------------------------------------------------------------------
    PREVIEW_MODE = 'rack'

    if PREVIEW_MODE == 'rack':
        subject = f"Wholesale Gas (/RB) Rack Window — ${current_price:.4f}/gal ({daily_pct:+.2f}%)"
        alert_context = {
            'label': 'Rack Pricing Window — 5:30 PM CT',
            'action': (
                f"Tonight's rack prices from Graves Oil go effective at 7:00 PM CT. "
                f"Current Wholesale Gas (/RB): ${current_price:.4f}/gal ({daily_pct:+.2f}% from open of ${open_price:.4f}). "
                f"Day range: ${low_price:.4f} \u2013 ${high_price:.4f} "
                f"(${abs(high_price - low_price):.4f} spread)."
            ),
            'action_color': '#f59e0b',
        }
    elif PREVIEW_MODE == 'settlement':
        subject = f"Wholesale Gas (/RB) Settlement — ${current_price:.4f}/gal ({daily_pct:+.2f}%)"
        alert_context = {
            'label': 'CME Daily Settlement — 1:30 PM CT',
            'action': (
                f"Official CME Wholesale Gas (/RB) settlement: ${current_price:.4f}/gal "
                f"({daily_pct:+.2f}% from open of ${open_price:.4f}). "
                f"Day range: ${low_price:.4f} \u2013 ${high_price:.4f}. "
                f"Tonight's rack postings are expected to reference this settlement level."
            ),
            'action_color': '#60a5fa',
        }
    elif PREVIEW_MODE == 'swing':
        sim_ref   = current_price / (1 - 0.031)
        swing_pct = ((current_price - sim_ref) / sim_ref) * 100
        subject   = f"Wholesale Gas (/RB) Price Move: {swing_pct:+.2f}% — ${current_price:.4f}/gal"
        alert_context = {
            'label': f'Price Movement Alert — {swing_pct:+.2f}% from Last Reference',
            'action': (
                f"Wholesale Gas (/RB) has moved {swing_pct:+.2f}% from the last alert reference "
                f"(${sim_ref:.4f}). Current: ${current_price:.4f}/gal. "
                f"Day range: ${low_price:.4f} \u2013 ${high_price:.4f}."
            ),
            'action_color': '#22c55e' if swing_pct < 0 else '#ef4444',
        }
    else:  # routine
        time_label = now.strftime('%-I %p')
        subject    = f"Wholesale Gas (/RB) {time_label} Update — ${current_price:.4f}/gal ({daily_pct:+.2f}%)"
        alert_context = {
            'label': f'Scheduled Market Update — {now.strftime("%-I:%M %p CT")}',
            'action': (
                f"Current Wholesale Gas (/RB): ${current_price:.4f}/gal ({daily_pct:+.2f}% from open of ${open_price:.4f}). "
                f"Day range: ${low_price:.4f} \u2013 ${high_price:.4f} "
                f"(${abs(high_price - low_price):.4f} spread)."
            ),
            'action_color': '#475569',
        }

    print(f"Rendering '{PREVIEW_MODE}' email preview...")
    html = build_html_email(
        subject, current_price, open_price, high_price, low_price, daily_pct,
        now, alert_context, chart_intraday, chart_5d,
        yesterday_close, five_day_high, five_day_low, thirty_day_avg,
        data_source='schwab'
    )

    out = os.path.abspath("email_preview.html")
    with open(out, "w") as f:
        f.write(html)

    print(f"\nDone — open in your browser:\n  file://{out}")
    print(f"\nSubject line: \"{subject}\"")
    print(f"\nChange PREVIEW_MODE to: 'rack' | 'settlement' | 'swing' | 'routine'")
