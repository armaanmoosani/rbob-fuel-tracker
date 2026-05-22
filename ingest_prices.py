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
from bs4 import BeautifulSoup

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
TO_EMAIL = os.environ.get('TO_EMAIL')
GRAVES_EMAIL = os.environ.get('GRAVES_EMAIL')
GRAVES_APP_PASSWORD = os.environ.get('GRAVES_APP_PASSWORD')
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

LABELS = {
    "rack_u": "E10 - UNLEADED",
    "rack_p": "E10 - PREMIUM",
    "rack_d": "CLEAR DIESEL",
}

def extract_price_near_label(text, label):
    pattern = rf'{re.escape(label)}.*?\$?(\d+\.\d{{2,5}})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def check_inbox_for_prices():
    if not GRAVES_EMAIL or not GRAVES_APP_PASSWORD:
        print("Missing GRAVES_EMAIL or GRAVES_APP_PASSWORD. Cannot check invoices.")
        return None, None
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GRAVES_EMAIL, GRAVES_APP_PASSWORD)
        mail.select('"[Gmail]/All Mail"')
        
        # Look back 1 day to handle the case where the job runs exactly at midnight
        yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%d-%b-%Y")
        
        # Hyper-specific, non-invasive search query that ignores UNSEEN status so you can read them yourself
        search_query = f'(FROM "donotreply@gravesoil.com" SUBJECT "Latest prices from Graves Oil Company" SINCE "{yesterday}")'
        status, messages = mail.search(None, search_query)
        
        if status != "OK" or not messages[0]:
            return None, None

        # Process the most recent email first
        for num in reversed(messages[0].split()):
            try:
                status, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                body = ""
                
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get('Content-Disposition'))
                        if ctype == 'text/plain' and 'attachment' not in cdispo:
                            body += part.get_payload(decode=True).decode('utf-8', errors='ignore') + "\n"
                        elif ctype == 'text/html' and 'attachment' not in cdispo:
                            html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            body += BeautifulSoup(html, "html.parser").get_text(separator=" ") + "\n"
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')

                prices = []
                for key, label in LABELS.items():
                    p = extract_price_near_label(body, label)
                    if p is None or not (1.50 <= p <= 6.00):
                        break
                    prices.append(p)
                    
                if len(prices) == 3:
                    import email.utils
                    email_date = email.utils.parsedate_to_datetime(msg.get('Date'))
                    local_date_str = email_date.astimezone(TZ).date().isoformat()
                    return local_date_str, tuple(prices)
            except Exception as loop_e:
                print(f"Skipping badly formatted email {num}: {loop_e}")
                continue

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
    
    print("Triggering nightly backtester auto-tune...")
    try:
        subprocess.run(["python", "backtest.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Backtester crashed: {e}")
        send_alert_email("Fuel Tracker Error", "The nightly backtester crashed and could not update the statistical thresholds. Check GitHub Actions logs.")

if __name__ == "__main__":
    main()
