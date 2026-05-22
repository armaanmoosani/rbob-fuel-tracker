import os
import sys
import json
import imaplib
import email
import re
import smtplib
import subprocess
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pytz

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
TO_EMAIL = os.environ.get('TO_EMAIL')
TZ = pytz.timezone('America/Chicago')

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")
DS_PATH = os.path.join(DATA_DIR, "daily_settlement.json")

def send_alert_email(subject, body):
    if not TO_EMAIL or not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Cannot send alert email: missing credentials.")
        return
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = TO_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"Alert email sent: {subject}")
    except Exception as e:
        print(f"Failed to send alert email: {e}")

def git_pull_rebase():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Git pull failed: {e}")
        sys.exit(1)

def git_commit_push(message):
    try:
        subprocess.run(["git", "add", "data/graves_history.csv"], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Git commit/push failed: {e}")
        sys.exit(1)

def extract_prices(text):
    # Match 3 decimals separated by space, comma, slash
    matches = re.findall(r'\b([1-6]\.\d{2,4})\b', text)
    if len(matches) == 3:
        return [float(m) for m in matches]
    return None

def check_inbox_for_prices():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
        
        today = datetime.now(TZ).strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'(UNSEEN SINCE "{today}")')
        
        if status != "OK" or not messages[0]:
            return None, None

        for num in messages[0].split():
            status, data = mail.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(data[0][1])
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode(errors='ignore')
            else:
                body = msg.get_payload(decode=True).decode(errors='ignore')

            # Check backfill
            backfill_match = re.search(r'BACKFILL\s+(\d{4}-\d{2}-\d{2})\s+([1-6]\.\d+)[,\s/]+([1-6]\.\d+)[,\s/]+([1-6]\.\d+)', body, re.IGNORECASE)
            if backfill_match:
                bf_date_str = backfill_match.group(1)
                bf_date = datetime.strptime(bf_date_str, "%Y-%m-%d").date()
                today_date = datetime.now(TZ).date()
                if (today_date - bf_date).days > 7:
                    send_alert_email("Fuel Tracker Error: Backfill Rejected", f"Backfill date {bf_date_str} is > 7 days old. Rejected to prevent data corruption.")
                    continue
                u, p, d = map(float, backfill_match.group(2, 3, 4))
                if all(1.50 <= x <= 6.00 for x in (u, p, d)):
                    mail.store(num, '+FLAGS', '\\Seen')
                    return bf_date_str, (u, p, d)

            prices = extract_prices(body)
            if prices and all(1.50 <= x <= 6.00 for x in prices):
                mail.store(num, '+FLAGS', '\\Seen')
                return datetime.now(TZ).date().isoformat(), tuple(prices)

        return None, None
    except Exception as e:
        print(f"IMAP Error: {e}")
        return None, None

def read_daily_settlement(target_date_str):
    if not os.path.exists(DS_PATH):
        return None
    with open(DS_PATH, "r") as f:
        ds = json.load(f)
    if ds.get("date") == target_date_str:
        return ds
    return None

def main():
    print("Starting SMS ingest...")
    date_str, prices = check_inbox_for_prices()
    
    if not prices:
        print("No valid SMS reply found.")
        send_alert_email("WARNING: Graves Oil Prices Missing", "No Graves Oil prices received today. Please reply to the SMS with the prices (e.g. 2.10 2.30 2.50).")
        sys.exit(0)

    print(f"Found prices for {date_str}: Unleaded={prices[0]}, Premium={prices[1]}, Diesel={prices[2]}")
    
    # Read CSV to check for duplicates
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith(date_str + ","):
                    print("Date already exists in CSV. Skipping.")
                    sys.exit(0)
    
    # Get settlement data
    ds = read_daily_settlement(date_str)
    if not ds:
        print(f"Missing daily_settlement.json for {date_str}.")
        send_alert_email("Fuel Tracker Error", f"Prices received, but missing 1:30 PM NYMEX settlement for {date_str}.")
        sys.exit(1)
        
    rb_stl = ds.get("rbob_settlement", "")
    ho_stl = ds.get("heating_oil_settlement", "")

    # Write to CSV
    git_pull_rebase()
    
    with open(CSV_PATH, "a") as f:
        f.write(f"{date_str},{rb_stl},{ho_stl},{prices[0]:.4f},{prices[1]:.4f},{prices[2]:.4f}\n")
        
    git_commit_push(f"Ingest Graves Oil prices for {date_str}")
    print("Successfully ingested.")

if __name__ == "__main__":
    main()
