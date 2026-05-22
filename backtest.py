import os
import sys
import json
import subprocess
import pandas as pd
import numpy as np
from scipy import stats

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {
        "MIN_ROWS_FOR_TUNING": 30,
        "BLEND_ALPHA": 0.3,
        "RB_HIKE_THRESHOLD_CENTS": 1.0,
        "RB_DROP_THRESHOLD_CENTS": -1.0,
        "HO_HIKE_THRESHOLD_CENTS": 1.0,
        "HO_DROP_THRESHOLD_CENTS": -1.0,
        "LAG_DAYS": 0,
        "ROLLING_WINDOW_DAYS": 120
    }

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def clamp(val, min_val, max_val):
    return max(min_val, min(val, max_val))

def git_commit_push(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "data/config.json"], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Git commit/push failed: {e}")

def run_tuning(df, nymex_col, rack_col, prefix, cfg):
    # Drop rows where either is missing so .diff() correctly calculates Monday - Friday
    df_clean = df.dropna(subset=[nymex_col, rack_col])
    
    delta_nymex = df_clean[nymex_col].diff() * 100 # cents
    delta_rack = df_clean[rack_col].diff() * 100 # cents
    
    # Drop the first row which will be NaN after diff()
    valid = ~(delta_nymex.isna() | delta_rack.isna())
    delta_nymex = delta_nymex[valid]
    delta_rack = delta_rack[valid]

    if len(delta_nymex) < 10:
        return cfg, "Insufficient valid diffs"

    slope, intercept, r_value, p_value, std_err = stats.linregress(delta_nymex, delta_rack)
    if p_value > 0.10:
        return cfg, f"p={p_value:.3f} > 0.10"

    # Empirical threshold: 15th percentile of NYMEX moves that triggered a Rack move
    hike_mask = (delta_rack > 0) & (delta_nymex > 0)
    drop_mask = (delta_rack < 0) & (delta_nymex < 0)

    if hike_mask.sum() >= 5:
        raw_hike = np.percentile(delta_nymex[hike_mask], 15)
        clamped_hike = clamp(raw_hike, 0.3, 3.0)
        old_hike = cfg.get(f"{prefix}_HIKE_THRESHOLD_CENTS", 1.0)
        cfg[f"{prefix}_HIKE_THRESHOLD_CENTS"] = round(cfg["BLEND_ALPHA"] * clamped_hike + (1 - cfg["BLEND_ALPHA"]) * old_hike, 2)
        
    if drop_mask.sum() >= 5:
        raw_drop = np.percentile(delta_nymex[drop_mask], 85) # 85th percentile of negative drops (e.g. closer to zero)
        clamped_drop = clamp(raw_drop, -3.0, -0.3)
        old_drop = cfg.get(f"{prefix}_DROP_THRESHOLD_CENTS", -1.0)
        cfg[f"{prefix}_DROP_THRESHOLD_CENTS"] = round(cfg["BLEND_ALPHA"] * clamped_drop + (1 - cfg["BLEND_ALPHA"]) * old_drop, 2)

    return cfg, f"R2={r_value**2:.2f}, p={p_value:.3f}, pass_thru={slope:.2f}"

def find_best_lag_and_window(df):
    windows = [90, 120, 180, 240, 365, None] # None means all historical data
    correlations = {}
    
    for window in windows:
        if window is not None and len(df) < window:
            continue
            
        df_sliced = df.tail(window) if window else df
        
        # Physical transmission lag is always 0 in daily fuel rack price setting.
        # Scanning non-zero lags on small rolling windows causes overfitting/spurious correlations.
        lag = 0
        nymex = df_sliced['nymex_rb'].diff().shift(lag)
        rack = df_sliced['rack_u'].diff()
        
        valid = ~(nymex.isna() | rack.isna())
        if valid.sum() < 20:
            continue
            
        slope, intercept, r_value, p_value, std_err = stats.linregress(nymex[valid], rack[valid])
        correlations[(lag, window)] = r_value**2

    if not correlations:
        return 0, None
        
    best_lag, best_window = max(correlations, key=correlations.get)
    return best_lag, best_window

def main():
    print("Starting backtest engine...")
    cfg = load_config()
    
    if not os.path.exists(CSV_PATH):
        print("No CSV data found. Exiting.")
        sys.exit(0)
        
    df = pd.read_csv(CSV_PATH)
    
    min_rows = cfg.get("MIN_ROWS_FOR_TUNING", 30)
    if len(df) < min_rows:
        print(f"Insufficient data. Have {len(df)} rows, need {min_rows}. Exiting.")
        sys.exit(0)

    # Find best lag and best rolling window
    best_lag, best_window = find_best_lag_and_window(df)
    cfg["LAG_DAYS"] = best_lag
    cfg["ROLLING_WINDOW_DAYS"] = best_window if best_window else 0
    print(f"Optimal Lag: {best_lag} days | Optimal Window: {best_window if best_window else 'ALL'} days")

    # Slice the dataframe to the optimal rolling window before tuning the thresholds
    if best_window:
        df = df.tail(best_window).copy()

    # If lag is > 0, we shift the nymex columns for the threshold tuning so the deltas align!
    if best_lag > 0:
        df['nymex_rb'] = df['nymex_rb'].shift(best_lag)
        df['nymex_ho'] = df['nymex_ho'].shift(best_lag)

    cfg, msg_rb = run_tuning(df, 'nymex_rb', 'rack_u', 'RB', cfg)
    cfg, msg_ho = run_tuning(df, 'nymex_ho', 'rack_d', 'HO', cfg)

    save_config(cfg)
    
    local_now = pd.Timestamp.now(tz='America/Chicago')
    commit_msg = f"Auto-tune [{local_now.strftime('%Y-%m-%d')}]: Lag={best_lag}, Win={best_window if best_window else 'ALL'}. RB({msg_rb}) HO({msg_ho})"
    print(commit_msg)
    git_commit_push(commit_msg)

if __name__ == "__main__":
    main()
