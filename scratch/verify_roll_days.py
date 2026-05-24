import os
import sys
import pandas as pd
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ['GH_PAT'] = 'mock'
os.environ['GH_REPO'] = 'mock'
os.environ['GMAIL_USER'] = 'mock'
os.environ['GMAIL_APP_PASSWORD'] = 'mock'
os.environ['TO_EMAIL'] = 'mock'

import main
import futures_util

# Load baseline
baseline_path = os.path.join(os.path.dirname(__file__), "roll_days_baseline.json")
if not os.path.exists(baseline_path):
    print("Baseline not found!")
    sys.exit(1)

with open(baseline_path, "r") as f:
    baseline = json.load(f)

start_dt = pd.Timestamp("2026-04-20")
end_dt = pd.Timestamp("2026-05-20")

mismatches = []
for dt in pd.date_range(start_dt, end_dt):
    dt_str = dt.strftime("%Y-%m-%d")
    base_val = baseline[dt_str]
    
    # Calculate using main (re-exported)
    main_rb = main.is_contract_roll_day(dt, "RB")
    main_ho = main.is_contract_roll_day(dt, "HO")
    
    # Calculate using futures_util (direct)
    util_rb = futures_util.is_contract_roll_day(dt, "RB")
    util_ho = futures_util.is_contract_roll_day(dt, "HO")
    
    if main_rb != base_val["RB"] or main_ho != base_val["HO"]:
        mismatches.append(f"Date {dt_str} mismatch with baseline: old RB/HO={base_val}, current RB/HO=({main_rb}, {main_ho})")
        
    if util_rb != main_rb or util_ho != main_ho:
        mismatches.append(f"Date {dt_str} mismatch between main and futures_util: main=({main_rb}, {main_ho}), util=({util_rb}, {util_ho})")

if mismatches:
    print("Mismatches found!")
    for m in mismatches:
        print(m)
    sys.exit(1)
else:
    print("SUCCESS: Pre-refactor baseline matches post-refactor outputs exactly!")
