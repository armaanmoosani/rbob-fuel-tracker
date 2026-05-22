import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
import json

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
LOG_PATH = os.path.join(DATA_DIR, "prediction_log.csv")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

os.makedirs(REPORTS_DIR, exist_ok=True)

def main():
    if not os.path.exists(LOG_PATH) or not os.path.exists(CSV_PATH):
        print("Required CSV files missing.")
        return

    log_df = pd.read_csv(LOG_PATH)
    hist_df = pd.read_csv(CSV_PATH)

    if len(log_df) == 0:
        print("No predictions logged yet.")
        return

    # Backfill PENDING
    updates_made = False
    for idx, row in log_df.iterrows():
        if str(row['actual_next_day_move_cents']) == 'PENDING':
            pred_date = row['timestamp'].split('T')[0]
            # Find pred_date in hist_df
            hist_idx = hist_df.index[hist_df['date'] == pred_date].tolist()
            if hist_idx and hist_idx[0] - 1 >= 0:
                prev_idx = hist_idx[0] - 1
                curr_row = hist_df.iloc[hist_idx[0]]
                prev_row = hist_df.iloc[prev_idx]
                
                rack_col = 'rack_u' if row['commodity'] == 'RB' else 'rack_d'
                
                if pd.notna(curr_row[rack_col]) and pd.notna(prev_row[rack_col]):
                    move = (curr_row[rack_col] - prev_row[rack_col]) * 100
                    log_df.at[idx, 'actual_next_day_move_cents'] = round(move, 2)
                    updates_made = True

    if updates_made:
        log_df.to_csv(LOG_PATH, index=False)
        print("Backfilled PENDING outcomes.")

    # Calculate Metrics
    # Filter to only rows that have been resolved
    df = log_df[log_df['actual_next_day_move_cents'] != 'PENDING'].copy()
    df['actual_move'] = pd.to_numeric(df['actual_next_day_move_cents'], errors='coerce')
    df = df.dropna(subset=['actual_move']).copy()
    if len(df) == 0:
        print("No resolved predictions yet.")
        return
    
    total_alerts = len(df)
    correct_hikes = 0
    correct_drops = 0
    false_flat = 0
    false_wrong_dir = 0
    missed_moves = 0
    cumulative_savings_cents = 0.0
    savings_history = []
    
    for idx, row in df.iterrows():
        pred = row['predicted_direction']
        actual = row['actual_move']
        
        # Savings logic: 
        # If we predicted HIKE, we bought today. If actual > 0, we saved money. If actual < 0, we lost money.
        # If we predicted DROP, we waited. If actual < 0, we saved money. If actual > 0, we lost money.
        # If we predicted FLAT, we didn't text the user (no alert).
        
        saved = 0.0
        if pred == 'HIKE':
            saved = actual # e.g. actual +2.0c means we saved 2.0c by buying early
            if actual > 0:
                correct_hikes += 1
            elif actual == 0:
                false_flat += 1
            else:
                false_wrong_dir += 1
        elif pred == 'DROP':
            saved = -actual # e.g. actual -2.0c means we saved 2.0c by waiting
            if actual < 0:
                correct_drops += 1
            elif actual == 0:
                false_flat += 1
            else:
                false_wrong_dir += 1
        else:
            # Predicted FLAT. We missed an opportunity if it moved.
            if abs(actual) > 0:
                missed_moves += 1
                
        cumulative_savings_cents += saved
        savings_history.append(cumulative_savings_cents)

    df['cumulative_savings'] = savings_history
    
    # Plotting
    fig = plt.figure(figsize=(10, 6))
    ax = fig.subplots()
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#f8fafc')
    
    # Plot actual savings
    dates = [d.split('T')[0] for d in df['timestamp']]
    ax.plot(dates, savings_history, marker='o', markersize=8, label='Cumulative Savings', color='#22c55e', linewidth=3)
    
    # Rolling 4-week trend (approx 20 trading days if we had 1 alert per day, but since alerts are sparse, we'll just do rolling 5 alerts)
    if len(df) >= 5:
        trend = df['cumulative_savings'].rolling(window=5, min_periods=1).mean()
        ax.plot(dates, trend, linestyle='--', color='#3b82f6', linewidth=2, label='Rolling Trend (5 alerts)')

    ax.axhline(0, color='#94a3b8', linestyle='-', linewidth=1.5)
    ax.set_title('Cumulative Expected Savings (¢/gal)', fontsize=16, fontweight='bold', color='#1e293b', pad=20)
    ax.set_ylabel('Cents per Gallon Saved', fontsize=12, color='#475569')
    ax.set_xlabel('Alert Date', fontsize=12, color='#475569')
    ax.tick_params(colors='#64748b')
    for spine in ax.spines.values():
        spine.set_color('#e2e8f0')
    ax.grid(color='#e2e8f0', linestyle='--', alpha=0.7)
    plt.xticks(rotation=45)
    ax.legend(frameon=True, facecolor='#ffffff', edgecolor='#e2e8f0')
    plt.tight_layout()
    
    import pytz
    TZ = pytz.timezone('America/Chicago')
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    chart_filename = f"report_{report_date}.png"
    chart_path = os.path.join(REPORTS_DIR, chart_filename)
    plt.savefig(chart_path)
    plt.close()
    
    # Send Email
    email_user = os.environ.get('GMAIL_USER')
    email_pass = os.environ.get('GMAIL_APP_PASSWORD')
    email_to = os.environ.get('TO_EMAIL', email_user)
    
    if not email_user or not email_pass:
        print("Missing email credentials. Cannot send report.")
        return
        
    subject = f"Weekly Performance Report - {report_date}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);">
            <!-- Header -->
            <div style="background-color: #f8fafc; padding: 24px; text-align: center; border-bottom: 1px solid #e2e8f0;">
                <h1 style="margin: 0; color: #0f172a; font-size: 24px; font-weight: 600;">Weekly Performance Report</h1>
                <p style="margin: 8px 0 0 0; color: #64748b; font-size: 14px;">Graves Oil Predictive Engine</p>
            </div>
            
            <div style="padding: 32px 24px;">
                <!-- KPI Cards -->
                <div style="display: table; width: 100%; margin-bottom: 24px;">
                    <div style="display: table-cell; width: 48%; background-color: #f1f5f9; padding: 16px; border-radius: 6px; text-align: center;">
                        <div style="color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Cumulative Savings</div>
                        <div style="color: #22c55e; font-size: 28px; font-weight: 700; margin-top: 8px;">{cumulative_savings_cents:+.2f} &cent;/gal</div>
                    </div>
                    <div style="display: table-cell; width: 4%;"></div>
                    <div style="display: table-cell; width: 48%; background-color: #f1f5f9; padding: 16px; border-radius: 6px; text-align: center;">
                        <div style="color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Total Alerts Fired</div>
                        <div style="color: #0f172a; font-size: 28px; font-weight: 700; margin-top: 8px;">{total_alerts}</div>
                    </div>
                </div>

                <!-- Confusion Matrix -->
                <h3 style="color: #334155; font-size: 16px; margin: 0 0 16px 0; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">Confusion Matrix</h3>
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 32px; font-size: 14px;">
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 12px 0; color: #475569;">Correct Hikes Predicted <span style="color: #94a3b8; font-size: 12px;">(Saved money)</span></td>
                        <td style="padding: 12px 0; text-align: right; font-weight: 600; color: #22c55e;">{correct_hikes}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 12px 0; color: #475569;">Correct Drops Predicted <span style="color: #94a3b8; font-size: 12px;">(Avoided loss)</span></td>
                        <td style="padding: 12px 0; text-align: right; font-weight: 600; color: #22c55e;">{correct_drops}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 12px 0; color: #475569;">False Alarms <span style="color: #94a3b8; font-size: 12px;">(Flat Next Day &mdash; No loss)</span></td>
                        <td style="padding: 12px 0; text-align: right; font-weight: 600; color: #f59e0b;">{false_flat}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 12px 0; color: #475569;">False Alarms <span style="color: #ef4444; font-size: 12px;">(Wrong Direction &mdash; Real loss)</span></td>
                        <td style="padding: 12px 0; text-align: right; font-weight: 600; color: #ef4444;">{false_wrong_dir}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 0; color: #475569;">Missed Moves <span style="color: #94a3b8; font-size: 12px;">(Predicted Flat)</span></td>
                        <td style="padding: 12px 0; text-align: right; font-weight: 600; color: #64748b;">{missed_moves}</td>
                    </tr>
                </table>

                <!-- Chart -->
                <h3 style="color: #334155; font-size: 16px; margin: 0 0 16px 0; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">Performance Trend</h3>
                <img src="cid:chart_img" style="width: 100%; max-width: 600px; height: auto; border: 1px solid #e2e8f0; border-radius: 6px;" alt="Cumulative Savings Chart" />
            </div>
            
            <!-- Footer -->
            <div style="background-color: #f8fafc; padding: 16px; text-align: center; border-top: 1px solid #e2e8f0;">
                <p style="margin: 0; color: #94a3b8; font-size: 12px;">Automated by Graves Oil Pricing Predictor</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = email_user
    msg['To'] = email_to
    
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)
    
    with open(chart_path, 'rb') as f:
        img = MIMEImage(f.read(), 'png')
        img.add_header('Content-ID', '<chart_img>')
        msg.attach(img)
        
    emails = [e.strip() for e in email_to.split(',') if e.strip()]
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(email_user, email_pass)
        server.sendmail(email_user, emails, msg.as_string())
        server.quit()
        print("Weekly report email sent.")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    main()
