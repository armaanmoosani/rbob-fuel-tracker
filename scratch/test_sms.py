import os
import smtplib
from email.mime.text import MIMEText

def main():
    email_user = os.environ.get('GMAIL_USER')
    email_pass = os.environ.get('GMAIL_APP_PASSWORD')
    phone_sms = os.environ.get('PHONE_SMS_ADDRESS')
    to_email = os.environ.get('TO_EMAIL')

    print("=== SMS Broadcast Testing Utility ===")
    print(f"GMAIL_USER: {email_user}")
    print(f"GMAIL_APP_PASSWORD: {'SET' if email_pass else 'NOT SET'}")
    print(f"PHONE_SMS_ADDRESS: {phone_sms}")
    print(f"TO_EMAIL: {to_email}")

    if not email_user or not email_pass:
        print("Error: Missing GMAIL_USER or GMAIL_APP_PASSWORD.")
        return

    # Gather phone numbers
    phones = []
    if phone_sms:
        phones = [p.strip() for p in phone_sms.split(',') if p.strip()]
    elif to_email:
        # Fallback to TO_EMAIL if it has the phone numbers
        phones = [p.strip() for p in to_email.split(',') if p.strip()]

    if not phones:
        print("Error: No recipient addresses found in PHONE_SMS_ADDRESS or TO_EMAIL.")
        return

    print(f"\nResolved recipients to test: {phones}")

    body = "Test broadcast from Graves Fuel Tracker. If you receive this, multi-number SMS alerts are working!"
    sms_msg = MIMEText(body)
    sms_msg['Subject'] = ''
    sms_msg['From'] = email_user

    try:
        print("\nConnecting to smtp.gmail.com:587...")
        srv = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        srv.starttls()
        print("Logging in...")
        srv.login(email_user, email_pass)
        
        for phone in phones:
            # Replace To header
            if 'To' in sms_msg:
                sms_msg.replace_header('To', phone)
            else:
                sms_msg.add_header('To', phone)
                
            print(f"Sending to {phone}...")
            srv.sendmail(email_user, phone, sms_msg.as_string())
            print(f"Success: Sent to {phone}")
            
        srv.quit()
        print("\nAll test messages sent successfully!")
    except Exception as e:
        print(f"\nFailed to send: {e}")

if __name__ == "__main__":
    main()
