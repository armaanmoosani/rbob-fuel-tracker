import os
import sys
import json
import csv
import math
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

def mask_recipient(address):
    if not address:
        return "None"
    if isinstance(address, (list, tuple)):
        return [mask_recipient(x) for x in address]
    address = str(address)
    if ',' in address:
        return [mask_recipient(x.strip()) for x in address.split(',') if x.strip()]
    if '@' in address:
        parts = address.split('@')
        name = parts[0]
        domain = parts[1]
        if len(name) <= 3:
            masked_name = "***"
        else:
            masked_name = name[:2] + "***" + name[-1:]
        return f"{masked_name}@{domain}"
    else:
        if len(address) <= 4:
            return "***"
        return address[:2] + "***" + address[-2:]

def mask_sensitive_text(text):
    if not text:
        return ""
    text = str(text)
    sensitive_vals = []
    for env_var in ['GMAIL_USER', 'GRAVES_EMAIL', 'TO_EMAIL', 'PHONE_SMS_ADDRESS']:
        val = os.environ.get(env_var, '')
        if val:
            for item in val.split(','):
                item_stripped = item.strip()
                if item_stripped and len(item_stripped) > 2:
                    sensitive_vals.append(item_stripped)
    sensitive_vals = sorted(list(set(sensitive_vals)), key=len, reverse=True)
    for val in sensitive_vals:
        text = text.replace(val, mask_recipient(val))
    return text

def send_alert_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Cannot send alert email: missing credentials.")
        return
        
    email_to_env = os.environ.get('TO_EMAIL', '')
    phone_to_env = os.environ.get('PHONE_SMS_ADDRESS', '')
    
    recipients = []
    if email_to_env:
        recipients.extend([e.strip() for e in email_to_env.split(',') if e.strip()])
    if phone_to_env:
        recipients.extend([p.strip() for p in phone_to_env.split(',') if p.strip()])
        
    # Deduplicate keeping order
    seen = set()
    emails = []
    for r in recipients:
        if r not in seen:
            seen.add(r)
            emails.append(r)
            
    if not emails:
        emails = [GMAIL_USER]
        
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(emails)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, emails, msg.as_string())
        print(f"Alert email sent to {mask_recipient(emails)}: {subject}")
    except Exception as e:
        print(f"Failed to send alert email: {mask_sensitive_text(e)}")

def git_pull_rebase():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "pull", "--rebase"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Git pull failed: {e}")
        sys.exit(1)

def git_commit_push(message):
    subprocess.run(["git", "add", "data/graves_history.csv", "data/integrity_hashes.csv"], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Git commit and push successful.")

LABELS = {
    "rack_u": "E10 - UNLEADED",
    "rack_p": "E10 - PREMIUM",
    "rack_d": "CLEAR DIESEL",
}

def extract_price_near_label(text, label):
    pattern = rf'{re.escape(label)}[^\n]{{0,60}}?\$?(\d+\.\d{{2,5}})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def check_inbox_for_prices(target_date_str):
    if not GRAVES_EMAIL or not GRAVES_APP_PASSWORD:
        print("Missing GRAVES_EMAIL or GRAVES_APP_PASSWORD. Cannot check invoices.")
        return None, None

    price_min = 1.50
    price_max = 6.00
    try:
        config_path = os.path.join(DATA_DIR, "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = json.load(f)
                price_min = cfg.get("PRICE_MIN", 1.50)
                price_max = cfg.get("PRICE_MAX", 6.00)
    except Exception as cfg_e:
        print(f"Error loading price bounds config: {mask_sensitive_text(cfg_e)}")
        
    import time
    mail = None
    for attempt in range(3):
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
            mail.login(GRAVES_EMAIL, GRAVES_APP_PASSWORD)
            break
        except Exception as conn_e:
            print(f"IMAP connection/login attempt {attempt + 1} failed: {mask_sensitive_text(conn_e)}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                return None, None

    try:
        mail.select('"[Gmail]/All Mail"')
        
        # Look back 2 days to handle any timezone/date boundary differences
        since_date = (datetime.now(TZ) - timedelta(days=2)).strftime("%d-%b-%Y")
        
        # Hyper-specific, non-invasive search query that ignores UNSEEN status so you can read them yourself
        search_query = f'(FROM "donotreply@gravesoil.com" SUBJECT "Latest prices from Graves Oil Company" SINCE "{since_date}")'
        status, messages = mail.search(None, search_query)
        
        if status != "OK" or not messages[0]:
            print(f"IMAP search returned no messages. Status: {status}, Query: {mask_sensitive_text(search_query)}")
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
                    if p is None or not (price_min <= p <= price_max):
                        break
                    prices.append(p)
                    
                if len(prices) == 3:
                    return local_date_str, tuple(prices)
            except Exception as loop_e:
                print(f"Skipping badly formatted email {num}: {mask_sensitive_text(loop_e)}")
                continue

        return None, None
    except Exception as e:
        print(f"IMAP Error: {mask_sensitive_text(e)}")
        return None, None

def read_daily_settlement(target_date_str):
    if not os.path.exists(DS_PATH):
        return None
    with open(DS_PATH, "r") as f:
        ds = json.load(f)
    if ds.get("date") == target_date_str:
        return ds
    return None

def get_github_settlement_snapshots(target_date_str):
    gh_pat = os.environ.get('GH_PAT')
    gh_repo = os.environ.get('GH_REPO')
    if not gh_pat or not gh_repo:
        print("GitHub credentials missing from environment. Skipping GitHub variable lookup.")
        return None
        
    import requests
    headers = {
        "Authorization": f"token {gh_pat}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # Fetch SETTLE_SNAPSHOT_RB and SETTLE_SNAPSHOT_HO
        rb_url = f"https://api.github.com/repos/{gh_repo}/actions/variables/SETTLE_SNAPSHOT_RB"
        ho_url = f"https://api.github.com/repos/{gh_repo}/actions/variables/SETTLE_SNAPSHOT_HO"
        
        rb_res = requests.get(rb_url, headers=headers, timeout=10)
        ho_res = requests.get(ho_url, headers=headers, timeout=10)
        
        rb_val, ho_val = None, None
        
        if rb_res.status_code == 200:
            rb_snap = json.loads(rb_res.json().get("value", "{}"))
            if rb_snap.get("date") == target_date_str:
                rb_val = float(rb_snap["price"])
                
        if ho_res.status_code == 200:
            ho_snap = json.loads(ho_res.json().get("value", "{}"))
            if ho_snap.get("date") == target_date_str:
                ho_val = float(ho_snap["price"])
                
        if rb_val is not None and ho_val is not None:
            return {
                "date": target_date_str,
                "rbob_settlement": rb_val,
                "heating_oil_settlement": ho_val,
                "source": "github_variables"
            }
        else:
            print("GitHub variables for settlement snapshots were missing, stale, or incomplete.")
    except Exception as e:
        print(f"Failed to fetch settlement snapshots from GitHub variables: {e}")
        
    return None


def main():
    print("Starting SMS ingest...")
    git_pull_rebase()
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
        print(f"daily_settlement.json missing or stale for {date_str}. Trying GitHub repository variables...")
        ds = get_github_settlement_snapshots(date_str)
        if ds:
            print(f"GitHub variables success: RB={ds['rbob_settlement']}, HO={ds['heating_oil_settlement']}")
            
    if not ds:
        print(f"GitHub variables missing or stale. Attempting Yahoo Finance fallback...")
        try:
            import yfinance as yf
            rb_ticker = yf.Ticker("RB=F")
            ho_ticker = yf.Ticker("HO=F")
            rb_hist = rb_ticker.history(period="5d")
            ho_hist = ho_ticker.history(period="5d")
            
            rb_val = None
            ho_val = None
            for dt, row in rb_hist.iterrows():
                if dt.strftime("%Y-%m-%d") == date_str:
                    rb_val = round(float(row['Close']), 4)
                    break
            for dt, row in ho_hist.iterrows():
                if dt.strftime("%Y-%m-%d") == date_str:
                    ho_val = round(float(row['Close']), 4)
                    break
                    
            if rb_val is not None and ho_val is not None:
                ds = {
                    "date": date_str,
                    "rbob_settlement": rb_val,
                    "heating_oil_settlement": ho_val,
                    "source": "yfinance_fallback"
                }
                print(f"Yahoo Finance fallback success: RB={rb_val}, HO={ho_val}")
            else:
                print(f"Could not find matching date {date_str} in Yahoo Finance history.")
        except Exception as yf_e:
            print(f"Yahoo Finance fallback failed: {mask_sensitive_text(yf_e)}")
            
    if not ds:
        print(f"Missing daily_settlement.json for {date_str} and Yahoo Finance fallback failed.")
        send_alert_email("Fuel Tracker Error", f"Prices received, but missing 1:30 PM NYMEX settlement for {date_str}.")
        sys.exit(1)
        
    rb_stl = ds.get("rbob_settlement", "")
    ho_stl = ds.get("heating_oil_settlement", "")

    # Write to CSV using retry transaction loop
    max_retries = 3
    for attempt in range(max_retries):
        print(f"Ingestion transaction attempt {attempt + 1}/{max_retries}...")
        git_pull_rebase()
        
        # Double check if date was already written by another concurrent run that succeeded
        already_ingested = False
        if os.path.exists(CSV_PATH):
            with open(CSV_PATH, "r") as f:
                for line in f:
                    if line.startswith(date_str + ","):
                        already_ingested = True
                        break
        if already_ingested:
            print(f"Prices for {date_str} were already ingested by a concurrent run. Exiting silently.")
            sys.exit(0)
            
        # Write to CSV
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            
            def fmt_val(v):
                if v is None or v == "":
                    return ""
                try:
                    fv = float(v)
                    if math.isnan(fv) or math.isinf(fv):
                        return ""
                    return f"{fv:.4f}"
                except (ValueError, TypeError):
                    return str(v)
            
            writer.writerow([
                date_str,
                fmt_val(rb_stl),
                fmt_val(ho_stl),
                f"{prices[0]:.4f}",
                f"{prices[1]:.4f}",
                f"{prices[2]:.4f}"
            ])
            
        try:
            validate_data.validate_all(DATA_DIR)
        except Exception as val_e:
            print(f"Validation failed after write: {mask_sensitive_text(val_e)}")
            subprocess.run(["git", "reset", "--hard", "origin/main"])
            sys.exit(1)
            
        try:
            git_commit_push(f"Ingest Graves Oil prices for {date_str}")
            print("Successfully ingested.")
            break
        except Exception as push_e:
            print(f"Push conflict or commit failed on attempt {attempt + 1}: {mask_sensitive_text(push_e)}")
            subprocess.run(["git", "reset", "--hard", "origin/main"])
            if attempt == max_retries - 1:
                print("All retry attempts failed. Exiting.")
                sys.exit(1)
            import time
            import random
            time.sleep(2 ** attempt + random.uniform(0, 1))
    
    print("Triggering nightly backtester auto-tune...")
    try:
        result = subprocess.run(["python", "backtest.py"], capture_output=True, text=True, check=True)
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Backtester crashed: {mask_sensitive_text(e)}")
        if e.stdout:
            print(f"Stdout:\n{mask_sensitive_text(e.stdout)}")
        if e.stderr:
            print(f"Stderr:\n{mask_sensitive_text(e.stderr)}")
        send_alert_email(
            "CRITICAL: Nightly calibration commit failed",
            f"The nightly backtester calibration failed to run or commit changes.\n\nError: {mask_sensitive_text(e)}\n\nStderr:\n{mask_sensitive_text(e.stderr)}\n\nPlease check GitHub Actions logs."
        )

if __name__ == "__main__":
    main()
