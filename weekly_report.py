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
            if hist_idx and hist_idx[0] + 1 < len(hist_df):
                next_idx = hist_idx[0] + 1
                curr_row = hist_df.iloc[hist_idx[0]]
                next_row = hist_df.iloc[next_idx]
                
                rack_col = 'rack_u' if row['commodity'] == 'RB' else 'rack_d'
                
                if pd.notna(curr_row[rack_col]) and pd.notna(next_row[rack_col]):
                    move = (next_row[rack_col] - curr_row[rack_col]) * 100
                    log_df.at[idx, 'actual_next_day_move_cents'] = round(move, 2)
                    updates_made = True

    if updates_made:
        log_df.to_csv(LOG_PATH, index=False)
        print("Backfilled PENDING outcomes.")

    # Calculate Metrics
    # Filter to only rows that have been resolved
    df = log_df[log_df['actual_next_day_move_cents'] != 'PENDING'].copy()
    if len(df) == 0:
        print("No resolved predictions yet.")
        return

    df['actual_move'] = df['actual_next_day_move_cents'].astype(float)
    
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
    plt.figure(figsize=(10, 6))
    
    # Plot actual savings
    dates = [d.split('T')[0] for d in df['timestamp']]
    plt.plot(dates, savings_history, marker='o', label='Cumulative Savings', color='#22c55e', linewidth=2)
    
    # Rolling 4-week trend (approx 20 trading days if we had 1 alert per day, but since alerts are sparse, we'll just do rolling 5 alerts)
    if len(df) >= 5:
        trend = df['cumulative_savings'].rolling(window=5, min_periods=1).mean()
        plt.plot(dates, trend, linestyle='--', color='#3b82f6', label='Rolling Trend')

    plt.axhline(0, color='gray', linestyle='-', linewidth=1)
    plt.title('Cumulative Expected Savings (¢/gal)', fontsize=14)
    plt.ylabel('Cents per Gallon Saved', fontsize=12)
    plt.xlabel('Alert Date', fontsize=12)
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()
    
    report_date = datetime.now().strftime("%Y-%m-%d")
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
    <html>
      <body style="font-family: Arial, sans-serif; color: #333;">
        <h2 style="color: #1e293b;">Graves Oil - Weekly Performance Dashboard</h2>
        <p><strong>Cumulative Savings:</strong> {cumulative_savings_cents:+.2f} ¢/gal</p>
        <p><strong>Total Alerts Fired:</strong> {total_alerts}</p>
        
        <h3>Confusion Matrix Breakdown</h3>
        <ul>
            <li><strong>Correct Hikes Predicted:</strong> {correct_hikes}</li>
            <li><strong>Correct Drops Predicted:</strong> {correct_drops}</li>
            <li><strong>False Alarms (Flat Next Day):</strong> {false_flat} <span style="color: #64748b; font-size: 0.9em;">(No loss, just bought early)</span></li>
            <li><strong>False Alarms (Wrong Direction):</strong> {false_wrong_dir} <span style="color: #ef4444; font-size: 0.9em;">(Real loss)</span></li>
            <li><strong>Missed Moves (Predicted Flat):</strong> {missed_moves}</li>
        </ul>
        
        <p>The cumulative savings chart is attached below.</p>
        <img src="cid:chart_img" style="max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 4px;" />
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
        
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(email_user, email_pass)
        server.sendmail(email_user, email_to, msg.as_string())
        server.quit()
        print("Weekly report email sent.")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    main()
