# Independent Operator System Evaluation: Graves Oil Predictor

This report provides a direct, honest assessment of the Oil Pricing Risk Engine from the perspective of an independent bulk fuel buyer with variable order volumes, limited tank capacity, and an exclusive supply contract with Graves Oil that features **load-time price locking**.

## 1. Operational Fit & The "Load-Time" Problem

Based on your specific confirmation that **your price locks when the fuel is physically loaded onto the truck, not when you place the order**, this system's operational fit is deeply flawed.

**The Arbitrage Mechanism:**
The system relies entirely on physical arbitrage. It detects a spike in the NYMEX futures market at 1:30 PM CT, texts you at 2:35 PM CT, and assumes you can order and secure today's cheaper physical rack price before Graves raises it at midnight.

**The Reality of Your Contract:**
If you place an order at 2:45 PM on a "HIKE" alert, you *do not secure today's price*. You are entirely at the mercy of Graves Oil's dispatch efficiency. If they load your truck at 10:00 PM, you capture the savings. If they load the truck at 7:00 AM the next morning, you pay the newly hiked price.

**Your New Daily Routine:**
To use this system, on roughly 12 days a month (averaging ~3 times a week), you will receive a text at 2:35 PM CT. You must immediately drop what you are doing, calculate your available tank capacity, call Graves dispatch before 3:00 PM, and aggressively demand that the truck be loaded *before midnight*. If you cannot successfully bully dispatch into same-day loads, the system's value erodes rapidly.

## 2. Honest Performance Assessment (The Real Math)

I have analyzed the real historical prediction logs (`prediction_log.csv`) rather than the theoretical max-capacity examples in the README. Because your order sizes vary, we must look purely at the **Expected Value (EV) in cents per gallon (¢/gal)**.

**The System's Statistical Edge is Real:**
The model is genuinely predictive and captures the "Rockets and Feathers" asymmetry.
*   **Precision:** Out of 468 historical HIKE alerts, the system was correct **69.4%** of the time.
*   **Average Win:** When it correctly predicted a hike, the rack price jumped an average of **+5.25¢/gal**.
*   **Average Loss:** When it was wrong (false alarm), the rack price dropped by an average of **-3.30¢/gal**.

Assuming 100% same-day loading, the baseline expected value is:
*(0.694 * 5.25¢) + (0.306 * -3.30¢) = **+2.63¢/gal expected savings per alert.***

**The Adjusted Edge Under Load-Time Pricing:**
Because Graves often loads the next morning, your expected value is proportional to the percentage ($P$) of orders they successfully load before midnight.
*   If Graves loads same-day 80% of the time: your EV drops to **+2.10¢/gal**.
*   If Graves loads same-day 50% of the time: your EV drops to **+1.31¢/gal**.

## 3. Failure Modes Specific to Your Situation

The theoretical failure mode is a statistical miss (a false HIKE alert where the price actually drops). However, the "Rockets and Feathers" pricing mitigates this (-3.30¢ loss vs +5.25¢ win).

**Your specific operational failure mode is far worse:**
You receive a HIKE alert predicting a massive 10¢ jump. You call Graves. You top off your tanks with 5,000 gallons of fuel you didn't strictly need yet, tying up cash. Graves delays the load until 6:00 AM the next morning. You are billed at the new, higher price. **You incurred the operational and holding cost of rushing an order, but captured absolutely zero arbitrage savings.**

## 4. Minimum Requirements to Capture Value

For this system to be worth your time and effort, you must meet two minimum thresholds:
1.  **Dispatch Compliance:** You must historically confirm (by auditing your past Bills of Lading) that Graves Oil successfully loads afternoon orders before midnight at least **70-80% of the time**. Below 50%, the expected value becomes so diluted that a single dispatch delay wipes out weeks of accumulated edge.
2.  **Spare Capacity:** You must consistently have enough spare underground tank capacity at 2:35 PM to accept a meaningful drop (e.g., at least 2,000-3,000 gallons) without risking overflow. If you are regularly full, you cannot act on HIKE alerts.

## 5. What the System Cannot Do

*   **It cannot guarantee your price:** The system assumes instantaneous order fulfillment. It has zero visibility into terminal congestion, driver shortages, or Graves Oil's internal dispatch prioritization.
*   **It cannot manage your inventory:** The system does not know how much fuel is in your ground. It will happily tell you to BUY when your tanks are at 95% capacity.
*   **It cannot predict "Wait" savings if you run dry:** If it tells you to DROP (wait to order), it assumes you have enough fuel to survive until the next day. If you run out of fuel while waiting for a price drop, the lost retail sales will vastly exceed wholesale savings.

## 6. Verdict

**Given your load-time price locking contract and Graves Oil's inconsistent delivery behavior, this system is structurally impaired for your operation and should NOT be relied upon as a primary procurement strategy as-is.**

The underlying machine learning model is sound and statistically profitable (+2.63¢/gal EV), but your supply chain realities act as a broken pipe, preventing you from capturing those profits.

**The Only Path Forward:**
If you want to use this system, you must shift your focus entirely from the software to your supplier relationship.
1.  For the next 14 days, place test orders when HIKE alerts fire at 2:35 PM.
2.  Audit the Bills of Lading to see exactly what time those trucks were loaded.
3.  If Graves consistently pushes the loads past midnight, the system is dead for you.
4.  If you can successfully manage your dispatcher to prioritize same-day loading, the system will print money over the long term. But the edge belongs to your dispatcher management skills, not just the algorithm.
