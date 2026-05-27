import os
import sys

# Add parent directory to path so we can import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set dummy env vars for all required env vars at import time
os.environ['GH_PAT'] = 'mock_pat'
os.environ['GH_REPO'] = 'mock_repo'
os.environ['GMAIL_USER'] = 'mock_user'
os.environ['GMAIL_APP_PASSWORD'] = 'mock_pass'
os.environ['TO_EMAIL'] = 'mock_to@example.com'
os.environ['PHONE_SMS_ADDRESS'] = '5551234567@vtext.com'
os.environ['GRAVES_EMAIL'] = 'mock_graves@example.com'

import main

def test_masking():
    # Set the specific environment variables for this test to be independent of other test files
    os.environ['GMAIL_USER'] = 'mygmail@gmail.com'
    os.environ['TO_EMAIL'] = 'recipient1@example.com,recipient2@example.com'
    os.environ['PHONE_SMS_ADDRESS'] = '5551234567@vtext.com'
    os.environ['GRAVES_EMAIL'] = 'graves_secrets@gravesoil.com'
    os.environ['GH_PAT'] = 'mock_pat'
    os.environ['GH_REPO'] = 'mock_repo'

    print("Running masking verification tests...")
    
    # 1. Test mask_recipient direct calls
    email = "mygmail@gmail.com"
    masked = main.mask_recipient(email)
    print(f"Masked single: {email} -> {masked}")
    assert masked == "my***l@gmail.com", f"Expected my***l@gmail.com, got {masked}"
    
    sms = "5551234567@vtext.com"
    masked_sms = main.mask_recipient(sms)
    print(f"Masked SMS: {sms} -> {masked_sms}")
    assert masked_sms == "55***7@vtext.com", f"Expected 55***7@vtext.com, got {masked_sms}"

    # 2. Test mask_sensitive_text on raw exception/logs containing secrets
    secret_log = "Error sending mail to recipient1@example.com from mygmail@gmail.com. Details: SMTPRecipientsRefused: {'recipient1@example.com': (550, 'User unknown')}"
    masked_log = main.mask_sensitive_text(secret_log)
    print(f"Original log: {secret_log}")
    print(f"Masked log:   {masked_log}")
    
    assert "recipient1@example.com" not in masked_log
    assert "mygmail@gmail.com" not in masked_log
    assert "re***1@example.com" in masked_log
    assert "my***l@gmail.com" in masked_log
    
    # 3. Test that normal error context is preserved
    normal_error = "IMAP Error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate in certificate chain (_ssl.c:1007)"
    masked_normal = main.mask_sensitive_text(normal_error)
    print(f"Original normal error: {normal_error}")
    print(f"Masked normal error:   {masked_normal}")
    assert normal_error == masked_normal, "Normal error message should not be modified by mask_sensitive_text"
    
    print("\nALL MASKING VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_masking()
