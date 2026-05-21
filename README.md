# RBOB Fuel Tracker

An autonomous, serverless market tracker designed for independent gas stations and fuel buyers. This system continuously monitors CME RBOB Wholesale Gasoline futures (`/RB`) and generates professional, chart-rich email alerts exactly when fuel procurement decisions need to be made.

## Features

- **Serverless Architecture**: Runs entirely on GitHub Actions via a 5-minute cron schedule. No servers to maintain.
- **Charles Schwab API Integration**: Pulls live `/RB` futures data.
- **Robust Fallback**: Automatically falls back to Yahoo Finance (`RB=F`) if the primary broker API experiences downtime.
- **Self-Healing OAuth**: Handles 7-day token expirations by automatically requesting new refresh tokens and securely rotating them back into GitHub Secrets using PyNaCl.
- **Accurate CME Session Tracking**: Correctly calculates "Intraday" charts across midnight boundaries by respecting the true 5:00 PM CT to 4:00 PM CT CME trading session.
- **Smart Alerts**: 
  - **5:30 PM CT Rack Window:** Timed perfectly for evening OPIS/Terminal price releases.
  - **1:30 PM CT Settlement:** Reports the official CME daily settlement price.
  - **Volatility Swings:** Triggers immediate alerts if the price swings > 2.5% from the last baseline.
  - **Scheduled Summaries:** Provides routine 6-hour updates.

## Email Layout

The email reports are generated with pure Python (`matplotlib` + `email.mime`) and are formatted as responsive, dark-themed HTML specifically tailored for quick decision-making:
- **Intraday & 5-Day Trend Charts** (embedded inline)
- **Position in Today's Range** (visual progress bar)
- **Contextual Stats** (Yesterday Close, 30-Day Avg %, 5-Day High/Low)

---

## 🚀 Setup & Deployment

To run this in your own GitHub account:

1. **Fork the Repository**
2. **Create a GitHub Personal Access Token (PAT)** with repository write permissions (needed to save price history state and rotate OAuth tokens).
3. **Configure GitHub Secrets**:
   Go to your repository **Settings > Secrets and variables > Actions** and add the following repository secrets:
   - `GH_PAT`: Your GitHub Personal Access Token
   - `GH_REPO`: Your repository path (e.g., `username/rbob-fuel-tracker`)
   - `GMAIL_USER`: The sending Gmail address
   - `GMAIL_APP_PASSWORD`: Google App Password (not your standard login password)
   - `TO_EMAIL`: The destination email address for the alerts
   - `SCHWAB_APP_KEY`: Your Schwab Developer App Key
   - `SCHWAB_APP_SECRET`: Your Schwab Developer App Secret
   - `SCHWAB_REFRESH_TOKEN`: Your initial Schwab OAuth Refresh Token (use `handshake.py` to generate this locally first)

4. **Enable GitHub Actions**:
   Go to the Actions tab and enable workflows. The tracker will now run every 5 minutes during the trading week.

## Local Testing

You can generate a local preview of the email template without needing any API keys. The preview generator pulls delayed public data from Yahoo Finance and outputs an HTML file you can open in your browser.

```bash
pip install -r requirements.txt
python generate_preview.py
# Then open email_preview.html in any web browser
```

## Disclaimer

This software is for informational purposes only. It does not constitute financial advice. The maintainers are not responsible for fuel purchasing decisions or financial losses resulting from the use of this tool.
