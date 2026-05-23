import os
import sys
import json
import imaplib
import email
import email.utils
import re
import smtplib
import subprocess
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pytz
from bs4 import BeautifulSoup
import validate_data


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
        subprocess.run(["git", "add", "data/graves_history.csv", "data/integrity_hashes.csv"], check=True)
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

def check_inbox_for_prices(target_date_str):
    if not GRAVES_EMAIL or not GRAVES_APP_PASSWORD:
        print("Missing GRAVES_EMAIL or GRAVES_APP_PASSWORD. Cannot check invoices.")
        return None, None
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GRAVES_EMAIL, GRAVES_APP_PASSWORD)
        mail.select('"[Gmail]/All Mail"')
        
        # Look back 2 days to handle any timezone/date boundary differences
        since_date = (datetime.now(TZ) - timedelta(days=2)).strftime("%d-%b-%Y")
        
        # Hyper-specific, non-invasive search query that ignores UNSEEN status so you can read them yourself
        search_query = f'(FROM "donotreply@gravesoil.com" SUBJECT "Latest prices from Graves Oil Company" SINCE "{since_date}")'
        status, messages = mail.search(None, search_query)
        
        if status != "OK" or not messages[0]:
            return None, None

        # Process the most recent email first
        for num in reversed(messages[0].split()):
            try:
                status, data = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(data[0][1])
                
                # Verify that the email belongs to the target date
                email_date = email.utils.parsedate_to_datetime(msg.get('Date'))
                if not email_date:
                    continue
                local_date_str = email_date.astimezone(TZ).date().isoformat()
                
                if local_date_str != target_date_str:
                    continue

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
    validate_data.validate_all(DATA_DIR)
    
    # Calculate target date based on Chicago timezone local hour
    now_local = datetime.now(TZ)
    if now_local.hour < 4:
        target_date_str = (now_local - timedelta(days=1)).date().isoformat()
    else:
        target_date_str = now_local.date().isoformat()
        
    print(f"Target date determined: {target_date_str} (local hour: {now_local.hour})")
    
    # Check if target date is a weekend (5 = Saturday, 6 = Sunday)
    target_dt = datetime.fromisoformat(target_date_str)
    if target_dt.weekday() in (5, 6):
        print(f"Target date {target_date_str} is weekend. Graves Oil is closed. Exiting silently.")
        sys.exit(0)
        
    # Read CSV to check for existing date (idempotency check)
    existing_dates = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r") as f:
            for line in f:
                parts = line.strip().split(',')
                if parts and parts[0]:
                    existing_dates.add(parts[0])
                    
    if target_date_str in existing_dates:
        print(f"Prices for {target_date_str} already ingested. Exiting silently.")
        sys.exit(0)
        
    # Query inbox for target date's email
    date_str, prices = check_inbox_for_prices(target_date_str)
    
    if not prices:
        # Determine retry vs. warning behavior
        current_hour = now_local.hour
        is_final_check = (current_hour == 0) or (current_hour < 4)
        is_manual = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        
        print(f"No valid price email found for {target_date_str}.")
        if is_final_check or is_manual:
            send_alert_email(
                "WARNING: Graves Oil Prices Missing",
                f"No Graves Oil prices received today for {target_date_str} by midnight. Please check Graves Oil email/website manually."
            )
        else:
            print(f"Prices missing at hour {current_hour}. Will retry on next scheduled run.")
        sys.exit(0)

    print(f"Found prices for {date_str}: Unleaded={prices[0]}, Premium={prices[1]}, Diesel={prices[2]}")
    
    # Read CSV to check for duplicates (double check)
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
        
    validate_data.validate_all(DATA_DIR)
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
