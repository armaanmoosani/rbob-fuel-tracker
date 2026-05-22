# Graves Oil Pricing Risk Engine

An institutional-grade, fully automated fuel purchasing predictor built specifically for independent gas stations and bulk fuel buyers. 

This system acts as a headless, serverless data pipeline and machine learning engine. It mathematically correlates the physical supplier rack prices (Graves Oil Company) with the NYMEX commodity futures market to predict whether wholesale gasoline and diesel prices will rise or fall tomorrow.

## Core Features

- **Automated Price Ingestion (`ingest_prices.py`)**: Nightly connects via IMAP to read the official supplier invoice. It parses the true `Date` header, extracts the exact cents-per-gallon price for E10 Unleaded, E10 Premium, and Clear Diesel, and appends it to an immutable CSV history.
- **Dynamic Regime Detection (`backtest.py`)**: Runs every night to backtest the historical relationship between NYMEX futures and Graves Oil. It dynamically selects the optimal `LAG_DAYS` (0 vs 1) and optimal `ROLLING_WINDOW_DAYS` (e.g., 90, 120, 180) to maximize out-of-sample $R^2$, mathematically protecting you against quiet supplier formula changes.
- **Asymmetric Thresholds**: Uses SciPy linear regression to calculate the exact 15th-percentile NYMEX move required to force the supplier to hike prices, isolating true signal from market noise.
- **Real-Time SMS Alerts (`main.py`)**: Polls the Yahoo Finance API (`RB=F`, `HO=F`, `CL=F`) every 5 minutes. Tracks the 3:2:1 Crack Spread. At 2:35 PM CT (post-NYMEX settlement), it texts the dispatcher a clear "EXPECT HIKE", "EXPECT DROP", or "NO EDGE" verdict.
- **Immutable Audit Log**: Every prediction is permanently written to `prediction_log.csv` milliseconds before the SMS fires, guaranteeing an unalterable history of the bot's decisions.
- **Weekly Performance Dashboard (`weekly_report.py`)**: Automatically backfills prediction outcomes by comparing them to the next trading day's physical rack price. Every Saturday morning, it emails a premium HTML dashboard containing a Confusion Matrix and a Matplotlib chart plotting Cumulative Savings in ¢/gal.

## System Architecture

1. **GitHub Actions Cron Jobs**: 
    - Real-Time Tracker runs every 5 minutes during CME trading hours.
    - Nightly Ingestion runs at 11:45 PM CT to ingest Graves Oil invoices.
    - Nightly Backtest auto-tunes the ML model parameters at 11:55 PM CT.
    - Weekly Dashboard runs at 3:00 AM CT on Saturdays.
2. **Data Storage**: `data/graves_history.csv` and `data/prediction_log.csv` act as lightweight, headless databases synced directly to the `main` git branch. 
3. **No Database/Servers**: 100% serverless execution.

## Setup Instructions

To deploy this securely to your own private repository:

1. **Fork the Repository**
2. **Configure GitHub Secrets**: Go to **Settings > Secrets and variables > Actions** and add:
   - `GRAVES_EMAIL`: Your corporate Gmail address receiving the Graves invoices.
   - `GRAVES_APP_PASSWORD`: The 16-character Google App Password for that account.
   - `GMAIL_USER`: The email address the bot uses to send the SMS text emails.
   - `GMAIL_APP_PASSWORD`: The Google App Password for the sending account.
   - `TO_EMAIL`: The destination SMS gateway (e.g., `1234567890@vtext.com` for Verizon).

## Disclaimer

This software is a decision-support tool built for informational purposes only. It does not constitute financial advice. The maintainers are not responsible for fuel purchasing decisions, inventory stockouts, or financial losses resulting from the use of this tool.
