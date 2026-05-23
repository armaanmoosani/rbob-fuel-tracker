import os
import smtplib
from email.mime.text import MIMEText

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

def main():
    email_user = os.environ.get('GMAIL_USER')
    email_pass = os.environ.get('GMAIL_APP_PASSWORD')
    phone_sms = os.environ.get('PHONE_SMS_ADDRESS')
    to_email = os.environ.get('TO_EMAIL')

    print("=== SMS Broadcast Testing Utility ===")
    print(f"GMAIL_USER: {mask_recipient(email_user)}")
    print(f"GMAIL_APP_PASSWORD: {'SET' if email_pass else 'NOT SET'}")
    print(f"PHONE_SMS_ADDRESS: {mask_recipient(phone_sms)}")
    print(f"TO_EMAIL: {mask_recipient(to_email)}")

    if not email_user or not email_pass:
        print("Error: Missing GMAIL_USER or GMAIL_APP_PASSWORD.")
        return

    # Gather phone numbers
    phones = []
    if phone_sms:
        phones = [p.strip() for p in phone_sms.split(',') if p.strip()]
    elif to_email:
        phones = [p.strip() for p in to_email.split(',') if p.strip()]

    if not phones:
        print("Error: No recipient addresses found in PHONE_SMS_ADDRESS or TO_EMAIL.")
        return

    print(f"\nResolved recipients to test: {mask_recipient(phones)}")

    body = "Test broadcast from Graves Fuel Tracker. If you receive this, multi-number SMS alerts are working!"
    sms_msg = MIMEText(body)
    sms_msg['Subject'] = 'Graves Tracker Test'
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
                
            print(f"Sending to {mask_recipient(phone)}...")
            srv.sendmail(email_user, phone, sms_msg.as_string())
            print(f"Success: Sent to {mask_recipient(phone)}")
            
        srv.quit()
        print("\nAll test messages sent successfully!")
    except Exception as e:
        print(f"\nFailed to send: {e}")

if __name__ == "__main__":
    main()
