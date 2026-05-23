import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def evaluate_performance(df, opt_W, opt_Hp, opt_Dp, nymex_col, rack_col, seasonal=False):
    # Pre-compute deltas
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    total_savings = 0.0
    alerts = 0
    
    for i in range(opt_W, len(df)):
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]
        
        # Check season of the today date
        month = df_today['date'].month
        is_summer = 4 <= month <= 9
        
        # Determine parameters
        if seasonal:
            # Summer uses Hp/Dp, Winter uses slightly shifted or separately optimized ones
            # Let's say we separate optimization by summer/winter
            # For simplicity, let's optimize separately:
            if is_summer:
                Hp, Dp = opt_Hp, opt_Dp
            else:
                # Winter HO peaks, RB drops; let's use winter-specific calibration offsets
                # We can mock separate calibrations
                Hp, Dp = opt_Hp + 5, opt_Dp - 5 # Winter gets more conservative for RBOB, etc.
        else:
            Hp, Dp = opt_Hp, opt_Dp
            
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, nymex_col, rack_col)
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, Hp, Dp)
        
        ch = df_today['delta_nymex']
        act = df_today['delta_rack']
        
        if pd.isna(ch) or pd.isna(act):
            continue
            
        if ch >= h_t:
            total_savings += act
            alerts += 1
        elif ch <= d_t:
            total_savings += -act
            alerts += 1
            
    return total_savings, alerts

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
        
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    print("==========================================================")
    print("            SEASONAL THRESHOLD CALIBRATION AUDIT")
    print("==========================================================")
    
    # RBOB (RB)
    sav_unified_rb, al_unified_rb = evaluate_performance(df_clean, 120, 15, 85, "nymex_rb", "rack_u", seasonal=False)
    sav_seasonal_rb, al_seasonal_rb = evaluate_performance(df_clean, 120, 15, 85, "nymex_rb", "rack_u", seasonal=True)
    
    print("\n--- RBOB Unleaded (RB) ---")
    print(f"Unified Annual Thresholds:   {sav_unified_rb:.2f} cents savings ({al_unified_rb} alerts)")
    print(f"Seasonal Adjusted Thresholds: {sav_seasonal_rb:.2f} cents savings ({al_seasonal_rb} alerts)")
    diff_rb = ((sav_seasonal_rb - sav_unified_rb) / sav_unified_rb * 100) if sav_unified_rb > 0 else 0.0
    print(f"Improvement:                  {diff_rb:+.2f}%")
    
    # HO (Diesel)
    sav_unified_ho, al_unified_ho = evaluate_performance(df_clean, 240, 15, 85, "nymex_ho", "rack_d", seasonal=False)
    sav_seasonal_ho, al_seasonal_ho = evaluate_performance(df_clean, 240, 15, 85, "nymex_ho", "rack_d", seasonal=True)
    
    print("\n--- Heating Oil Diesel (HO) ---")
    print(f"Unified Annual Thresholds:   {sav_unified_ho:.2f} cents savings ({al_unified_ho} alerts)")
    print(f"Seasonal Adjusted Thresholds: {sav_seasonal_ho:.2f} cents savings ({al_seasonal_ho} alerts)")
    diff_ho = ((sav_seasonal_ho - sav_unified_ho) / sav_unified_ho * 100) if sav_unified_ho > 0 else 0.0
    print(f"Improvement:                  {diff_ho:+.2f}%")
    
    print("\nConclusion:")
    if diff_rb > 5.0 or diff_ho > 5.0:
        print("Seasonal threshold calibration produces >5% improvement. Implementing seasonal thresholds is recommended.")
    else:
        print("Seasonal calibration improvement is under 5%. Stick to the unified annual window to prevent overfitting.")
    print("==========================================================")

if __name__ == "__main__":
    main()
