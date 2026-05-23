import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def run_regime_conviction_audit(df, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name):
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    records = []
    for i in range(opt_W, len(df)):
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]
        
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, nymex_col, rack_col)
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, opt_Hp, opt_Dp)
        
        # We need nymex daily std for Z-score
        valid_mask = ~(train_nymex.isna() | train_rack.isna())
        nymex_std = float(train_nymex[valid_mask].std()) if train_nymex[valid_mask].sum() else 1.0
        
        ch = df_today['delta_nymex']
        act = df_today['delta_rack']
        
        if pd.isna(ch) or pd.isna(act):
            continue
            
        z = ch / nymex_std if nymex_std > 0 else 0.0
        abs_z = abs(z)
        
        alert_triggered = False
        direction = ""
        is_correct = False
        
        if ch >= h_t:
            alert_triggered = True
            direction = "BUY"
            is_correct = (act > 0)
        elif ch <= d_t:
            alert_triggered = True
            direction = "WAIT"
            is_correct = (act < 0)
            
        if alert_triggered:
            if abs_z >= 1.5:
                conviction = "High"
            elif abs_z >= 1.0:
                conviction = "Moderate"
            else:
                conviction = "Low"
                
            records.append({
                "year": df_today['date'].year,
                "conviction": conviction,
                "is_correct": is_correct,
                "savings": act if direction == "BUY" else -act
            })
            
    df_rec = pd.DataFrame(records)
    if len(df_rec) == 0:
        print("No alerts triggered.")
        return
        
    print(f"\n================ Regime Conviction Audit: {commodity_name} ================")
    for year in sorted(df_rec['year'].unique()):
        print(f"\n--- Year: {year} ---")
        print(f"{'Conviction':<12} | {'Alerts':<6} | {'Correct':<7} | {'Precision':<9} | {'Avg Savings (c/gal)':<20}")
        print("-" * 65)
        df_yr = df_rec[df_rec['year'] == year]
        for conv in ["High", "Moderate", "Low"]:
            sub = df_yr[df_yr['conviction'] == conv]
            n_alerts = len(sub)
            n_correct = sub['is_correct'].sum()
            prec = n_correct / n_alerts if n_alerts > 0 else 0.0
            avg_sav = sub['savings'].mean() if n_alerts > 0 else 0.0
            print(f"{conv:<12} | {n_alerts:<6} | {n_correct:<7} | {prec:<9.2%} | {avg_sav:<+20.2f}")

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    run_regime_conviction_audit(df_clean, "nymex_rb", "rack_u", 120, 15, 85, "RBOB Unleaded")
    run_regime_conviction_audit(df_clean, "nymex_ho", "rack_d", 240, 15, 85, "Heating Oil Diesel")

if __name__ == "__main__":
    main()
