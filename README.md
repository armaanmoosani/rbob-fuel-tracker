# Graves Oil Pricing Risk Engine

An institutional-grade, fully automated wholesale fuel purchasing predictor built specifically for independent gas stations and bulk fuel buyers to optimize physical inventory procurement.

This system acts as a headless, serverless data pipeline and machine learning engine. It mathematically correlates the physical supplier rack prices (Graves Oil Company) with the NYMEX commodity futures market to predict whether wholesale gasoline and diesel prices will rise or fall tomorrow, allowing you to buy before hikes and wait before drops.

---

## Model Performance & Historical Edge

Wholesale physical rack pricing is synchronous with futures: Graves Oil sets its rack price at 6:00 PM based on that day's 1:30 PM NYMEX settle. Since the buyer's purchase deadline at the previous day's price is midnight, this creates a physical arbitrage window. The buyer uses NYMEX settlements to predict the upcoming Graves price change, allowing them to order fuel at the old price.

An out-of-sample quantitative audit across three distinct market regimes (2023–2026) reveals the following historical performance envelopes:

### 1. Multi-Year Precision & Savings Baseline

The primary metric of the engine's edge is **expected net savings in cents per gallon (¢/gal)**. Dollar savings are presented as worked examples assuming a single standard 8,500-gallon capacity delivery truck per active alert day.

*   **Unleaded Gasoline (RBOB):**
    *   **Honest Multi-Year Precision Envelope:** **53%–73%** (with an overall historical average of **71.0%** and an average savings of **+6.04¢/gal** per active alert).
    *   **Conservative Floor for Planning:** **53.0%** precision.
    *   **Yearly Out-of-Sample Performance Breakdown (Unleaded):**
        *   **2023 (Moderate Volatility):** 34 alerts | 52.94% precision | **+29.96¢/gal** net savings | **$2,546.60** annual savings (worked example).
        *   **2024 (Low-to-Moderate Volatility):** 146 alerts | 54.11% precision | **+61.31¢/gal** net savings | **$5,211.35** annual savings (worked example).
        *   **2025 (High Volatility/Low Noise):** 158 alerts | 72.78% precision | **+217.06¢/gal** net savings | **$18,450.10** annual savings (worked example).
        *   **Recent Out-of-Sample Window (Late 2025 into 2026):** 80 alerts in 90 days | 96.25% precision | **+542.03¢/gal** savings | **$46,072.55** OOS savings (not a reliable annual projection).
*   **Diesel / Heating Oil (HO):**
    *   **Honest Multi-Year Precision Envelope:** **60%–79%** (with an overall historical average of **94.8%** and an average savings of **+9.97¢/gal** per active alert).
    *   **Conservative Floor for Planning:** **60.0%** precision.
    *   **Yearly Out-of-Sample Performance Breakdown (Diesel):**
        *   **2023:** N/A (insufficient warm-up window history).
        *   **2024:** 84 alerts | 59.52% precision | **+69.41¢/gal** net savings | **$5,900.00** annual savings (worked example).
        *   **2025:** 178 alerts | 78.65% precision | **+492.13¢/gal** net savings | **$41,831.05** annual savings (worked example).

### 2. Payoff Asymmetry & Rockets-and-Feathers Edge

The model's durability across low-precision years (such as 2023 and 2024 at ~53%–59% precision) is driven by **Rockets and Feathers** asymmetric pass-through pricing. Wholesale suppliers raise prices rapidly in response to NYMEX hikes ("rockets") but lower them gradually in response to drops ("feathers"). 

Consequently, the engine's correct alerts capture large moves, while incorrect alerts incur smaller costs. This results in a structurally profitable **Win-to-Loss ratio of 1.06x to 1.50x**:

*   **RBOB (Gasoline) Payoff Asymmetry:**
    *   **2023:** Avg Win: 5.11¢/gal | Avg Loss: 3.87¢/gal | **Win-Loss Asymmetry: +1.23¢/gal** (Ratio: 1.32x)
    *   **2024:** Avg Win: 2.83¢/gal | Avg Loss: 2.42¢/gal | **Win-Loss Asymmetry: +0.41¢/gal** (Ratio: 1.17x)
    *   **2025:** Avg Win: 2.75¢/gal | Avg Loss: 2.30¢/gal | **Win-Loss Asymmetry: +0.44¢/gal** (Ratio: 1.19x)
*   **HO (Diesel) Payoff Asymmetry:**
    *   **2024:** Avg Win: 3.90¢/gal | Avg Loss: 3.69¢/gal | **Win-Loss Asymmetry: +0.21¢/gal** (Ratio: 1.06x)
    *   **2025:** Avg Win: 4.29¢/gal | Avg Loss: 2.87¢/gal | **Win-Loss Asymmetry: +1.43¢/gal** (Ratio: 1.50x)

### 3. Understanding the Precision Trend (Monotonic Growth)

Unleaded precision has increased monotonically over the three years (52.9% -> 54.1% -> 72.8%). This trend likely reflects a combination of three factors:
1.  **Accumulating History:** The model accumulating more Graves-specific history to tune thresholds.
2.  **Structural Pegging:** Graves Oil's pricing behavior becoming more mechanically tied to NYMEX.
3.  **Low-Volatility Regime Bias (Warning Caveat):** Recent low-volatility/calm market conditions in 2025 making direction easier to call.

> [!CAUTION]
> **Volatility Warning:** If the 2025 precision increase is primarily a result of calm markets rather than model improvement, a return of high-volatility spikes in 2026 could cause performance to revert to the conservative planning floor of **53% (RB)** / **60% (HO)**. Decisions like storage capacity investment or cash flow planning should always be stress-tested at the 53% / 60% floors, not the recent 96% regime levels.

---

## Core Features

- **Hourly Ingestion Retries (`ingest_prices.py`)**: Nightly connects via IMAP to read the official supplier invoice. It queries hourly from 8:00 PM to 12:00 AM CT to prevent false missing-email alarms, handles target date calculations across the midnight boundary, and appends parsed rack prices to an immutable CSV history.
- **Walk-Forward Calibration (`backtest.py`)**: Re-engineers threshold calibration using a robust 3-fold Walk-Forward Validation strategy over the last 365 days of history (90-day out-of-sample test windows). Parameters ($W, Hp, Dp$) are chosen to maximize **median out-of-sample savings** to prevent backtest overfitting.
- **Dynamic Volatility & Z-Score Conviction (`main.py`)**: Evaluates the strength of futures moves using the rolling standard deviation of daily changes ($\sigma$). It translates daily changes into Z-scores to grade alerts by conviction: **High Conviction** ($|Z| \ge 1.5$), **Moderate Conviction** ($1.0 \le |Z| < 1.5$), or **Low Conviction** ($|Z| < 1.0$).
- **Quantified Deferral Risk (CVaR)**: Computes the 95% Conditional Value-at-Risk (worst-case tail risk) over the optimal window. For "WAIT" alerts, it computes the expected price spike cost:
  *e.g., "Risk Note: On the worst 5% of days historically, rack prices spiked +4.20¢/gal (+$357 per 8,500 gal truck)."*
- **Real-Time SMS & Email Alerts**: Polls the Schwab API and Yahoo Finance API (`RB=F`, `HO=F`, `CL=F`) during CME trading hours. At 2:35 PM CT (post-NYMEX settlement), it sends structured, high-value alerts containing the verdict, Z-score conviction, and tail-risk warnings.
- **Overnight verification loop**: Automatically backfills prediction outcomes by comparing them to the next trading day's physical rack price, appending results to `prediction_log.csv` and displaying the confirmation table in morning notifications.
- **Outlook-Safe Weekly Dashboard (`weekly_report.py`)**: Runs every Saturday morning. It calculates cumulative savings in cents-per-gallon and equivalent dollar totals (assuming an 8,500 gallon capacity delivery truck). It runs a stable **180-day permutation significance test** (computing a p-value to prove model edge over random chance) and formats the dashboard using nested HTML tables for rendering safety.
- **Blockchain-Style Data Validation (`validate_data.py`)**: Protects the database against corruption and manual edits using an append-only registry of SHA-256 hashes (`data/integrity_hashes.csv`), treating `config.json` as a mutable schema-checked file.

---

## System Architecture

1. **GitHub Actions Workflows**: 
   - **Real-Time Tracker (`tracker.yml`)**: Runs every 5 minutes during CME Globex hours to monitor futures and send alerts.
   - **Nightly Ingestion & Backtest (`backtest_ingest.yml`)**: Checks hourly from 8:00 PM to 12:00 AM Chicago time to pull Graves invoices, validate hashes, run walk-forward calibration, and push configuration files.
   - **Weekly Dashboard (`weekly_report.yml`)**: Runs Saturday mornings at 3:00 AM CT to backfill pending outcomes, compute permutation significance, generate Matplotlib performance charts, and send reports.
2. **Data Storage**: `data/graves_history.csv` and `data/prediction_log.csv` act as lightweight, flat-file databases synced directly to the `main` git branch. 
3. **Serverless Execution**: 100% serverless execution on GitHub Actions.

---

## Setup Instructions

To deploy this securely to your own private repository:

1. **Fork the Repository**
2. **Configure GitHub Secrets**: Go to **Settings > Secrets and variables > Actions** and add:
   - `GRAVES_EMAIL`: Your corporate Gmail address receiving the Graves invoices.
   - `GRAVES_APP_PASSWORD`: The 16-character Google App Password for that account.
   - `GMAIL_USER`: The email address the bot uses to send the SMS text emails.
   - `GMAIL_APP_PASSWORD`: The Google App Password for the sending account.
   - `TO_EMAIL`: The destination SMS gateway (e.g., `1234567890@vtext.com` for Verizon).
   - `PHONE_SMS_ADDRESS`: Optional comma-separated SMS gateway addresses (falls back to `TO_EMAIL` if empty).

---

## Testing & Verification

The repository contains a highly thorough, multi-tiered testing framework:

1. **Comprehensive Test Suite (`comprehensive_test_suite.py`)**: 
   - A unit-test suite with 37 tests covering all 10 core categories (email parsing, bounds checks, sorting order, timezone boundaries, lag math, OLS Rockets & Feathers, threshold clamping, walk-forward isolation, CVaR and Z-score calculations). Run with:
     ```bash
     python comprehensive_test_suite.py
     ```
2. **Deterministic Day Replay (`replay_day.py`)**:
   - Performs a stateful point-in-time prediction audit on historically logged days to guarantee the system is deterministic, timezone-stable, and free of future-data leakages. Run with:
     ```bash
     python replay_day.py --date YYYY-MM-DD
     ```
3. **Statistical Validation & Shadow Benchmarks (`verify_statistics.py`)**:
   - Audits model significance against randomized null models (permutation test), evaluates out-of-sample holdout datasets, computes yearly regime shifts, analyzes residual diagnostics, and measures model performance against shadow baselines. Run with:
     ```bash
     python verify_statistics.py
     ```
4. **Stress Testing and Sensitivity Sweep (`scratch/run_simulations.py`)**:
   - Audits model limitations under parameter sensitivity (169 grid sweep), simulates extreme geopolitical black swan shocks ($\pm40\text{¢/gal}$ daily moves) to verify threshold adaptability, and conducts contract roll spuriousness checks. Run with:
     ```bash
     python scratch/run_simulations.py
     ```
5. **Data Injections (`scratch/test_validation_injection.py`)**:
   - Asserts that the data validation parser successfully catches duplicate dates, invalid bounds, weekday gaps, and negative numbers. Run with:
     ```bash
     python scratch/test_validation_injection.py
     ```

---

## Disclaimer

This software is a decision-support tool built for informational purposes only. It does not constitute financial advice. The maintainers are not responsible for fuel purchasing decisions, inventory stockouts, or financial losses resulting from the use of this tool.
