import base64
import urllib.parse

try:
    import requests
except ImportError:
    import subprocess
    import sys
    print("Installing required 'requests' library...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

print("======================================================================")
print("             CHARLES SCHWAB API INITIAL OAUTH HANDSHAKE               ")
print("======================================================================")
print("This script helps you generate your very first SCHWAB_REFRESH_TOKEN.")
print("Once generated, you will paste it into your GitHub Secrets.\n")

# 1. Get credentials from user
app_key = input("Enter your Schwab App Key: ").strip()
app_secret = input("Enter your Schwab App Secret: ").strip()
redirect_uri = input("Enter your Schwab App Redirect URI (usually https://127.0.0.1 or https://localhost): ").strip()

# 2. Construct the authorization URL
params = {
    "response_type": "code",
    "client_id": app_key,
    "redirect_uri": redirect_uri
}
auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"

print("\n----------------------------------------------------------------------")
print("STEP 1: AUTHORIZE THE APP IN YOUR BROWSER")
print("----------------------------------------------------------------------")
print("Copy and paste this URL into your browser:")
print(f"\n{auth_url}\n")
print("Log in with your Schwab credentials and authorize the application.")
print("After authorizing, your browser will redirect to a page that may not load")
print("(e.g., https://127.0.0.1/?code=...&session=...).")

# 3. Get the redirected URL or code
redirected_input = input("\nSTEP 2: Paste the ENTIRE URL you were redirected to: ").strip()

# Extract code from the URL if they pasted the full URL
code = redirected_input
if "code=" in redirected_input:
    parsed = urllib.parse.urlparse(redirected_input)
    query_params = urllib.parse.parse_qs(parsed.query)
    # The code parameter has a suffix "%40" (which is @ decoded). Schwab codes usually end with %40.
    # parse_qs automatically decodes percent encoding, which is correct for the API call.
    code = query_params.get("code", [None])[0]

if not code:
    print("[ERROR] Failed to extract authorization code. Make sure you pasted the full redirect URL.")
    exit(1)

# 4. Exchange the authorization code for tokens
print("\n----------------------------------------------------------------------")
print("STEP 3: EXCHANGING CODE FOR REFRESH TOKEN...")
print("----------------------------------------------------------------------")

auth_header = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_header}",
    "Content-Type": "application/x-www-form-urlencoded"
}
data = {
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": redirect_uri
}

try:
    res = requests.post("https://api.schwabapi.com/v1/oauth/token", data=data, headers=headers)
    res.raise_for_status()
    tokens = res.json()
    
    refresh_token = tokens.get("refresh_token")
    if refresh_token:
        print("\n[SUCCESS] Here is your initial Schwab Refresh Token:\n")
        print("======================================================================")
        print(refresh_token)
        print("======================================================================")
        print("\nCopy the entire text above and add it to your GitHub Repository Secrets")
        print("as: SCHWAB_REFRESH_TOKEN\n")
    else:
        print("[ERROR] Schwab responded successfully, but did not return a refresh token.")
        print(f"Response: {tokens}")
except Exception as e:
    print(f"[ERROR] Exchange failed. Error: {e}")
    if 'res' in locals():
        print(f"Schwab Response: {res.text}")
