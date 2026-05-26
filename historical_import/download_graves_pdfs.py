import imaplib
import email
import os
import re
import getpass
from datetime import datetime
from email.header import decode_header

# --- CONFIG ---
SENDER_SEARCH = "donotreply@gravesoil.com"   # Adjust to match Graves Oil's actual sender address
OUTPUT_DIR = "graves_pdfs"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def clean_filename(s):
    return re.sub(r'[^\w\-_.]', '_', s)

def connect_imap(email_addr, app_pw):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_addr, app_pw)
    # Search All Mail instead of just inbox to catch archived emails
    mail.select('"[Gmail]/All Mail"')
    return mail

def fetch_all_graves_emails(mail, subject_filter=""):
    # Search by sender — adjust the search string to match exactly
    search_query = f'FROM "{SENDER_SEARCH}"'
    if subject_filter:
        search_query += f' SUBJECT "{subject_filter}"'
        
    status, messages = mail.search(None, search_query)
    if status != "OK":
        print("No messages found.")
        return []
    return messages[0].split()

def parse_email_date(msg):
    """Extract and format the received date as YYYY-MM-DD."""
    date_str = msg.get("Date", "")
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Fallback: strip timezone suffix and try again
    date_str_clean = re.sub(r'\s+\(.*\)$', '', date_str).strip()
    try:
        return datetime.strptime(date_str_clean, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d")
    except Exception:
        return "UNKNOWN_DATE"

def download_attachments(mail, email_ids):
    downloaded = 0
    skipped = 0
    errors = 0

    for i, eid in enumerate(email_ids):
        try:
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            date_str = parse_email_date(msg)

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                if part.get("Content-Disposition") is None:
                    continue

                filename = part.get_filename()
                if not filename or not filename.lower().endswith(".pdf"):
                    continue

                # Filename format: YYYY-MM-DD_original_name.pdf
                safe_name = clean_filename(filename)
                output_path = os.path.join(OUTPUT_DIR, f"{date_str}_{safe_name}")

                if os.path.exists(output_path):
                    skipped += 1
                    continue

                with open(output_path, "wb") as f:
                    f.write(part.get_payload(decode=True))
                downloaded += 1

            if (i + 1) % 50 == 0:
                print(f"Progress: {i + 1}/{len(email_ids)} emails processed...")

        except Exception as e:
            print(f"Error on email {eid}: {e}")
            errors += 1

    print(f"\nDone. Downloaded: {downloaded} | Skipped (already exist): {skipped} | Errors: {errors}")

if __name__ == "__main__":
    print("=== Graves Oil PDF Downloader ===")
    print("Enter the credentials for the Gmail account that contains the PDF history.")
    email_addr = input("Gmail Address: ").strip()
    app_pw = getpass.getpass("App Password (input will be hidden): ").strip()
    subject_filter = input("Optional Subject Filter (e.g., 'prices' or leave blank for all): ").strip()
    
    if not email_addr or not app_pw:
        print("Error: You must provide both an email address and an app password.")
        exit(1)
        
    print("\nConnecting to Gmail...")
    try:
        mail = connect_imap(email_addr, app_pw)
    except Exception as e:
        print(f"Failed to login: {e}")
        exit(1)
        
    print("Fetching Graves Oil email list...")
    email_ids = fetch_all_graves_emails(mail, subject_filter)
    print(f"Found {len(email_ids)} emails. Starting download...")
    download_attachments(mail, email_ids)
    mail.logout()
