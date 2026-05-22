import os
import smtplib
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
TO_EMAIL = os.environ.get('TO_EMAIL')

def send_prompt():
    if not TO_EMAIL or not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Cannot send prompt: missing credentials.")
        return

    subject = "Graves Oil Prices Needed"
    body = "Please reply with today's Graves Oil prices.\nFormat: Unleaded Premium Diesel\n(e.g. 2.10 2.30 2.50)"
    
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = TO_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"Price prompt sent successfully to {TO_EMAIL}")
    except Exception as e:
        print(f"Failed to send price prompt: {e}")

if __name__ == "__main__":
    print("Starting daily price prompt...")
    send_prompt()
