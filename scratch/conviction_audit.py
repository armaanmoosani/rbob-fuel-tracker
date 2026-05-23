import os
import sys
import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def analyze_conviction_levels(df, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp):
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
        
        # Determine alert type
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
            abs_z = abs(z)
            if abs_z >= 1.5:
                conviction = "High"
            elif abs_z >= 1.0:
                conviction = "Moderate"
            else:
                conviction = "Low"
                
            records.append({
                "date": df_today['date'],
                "conviction": conviction,
                "direction": direction,
                "is_correct": is_correct,
                "savings": act if direction == "BUY" else -act
            })
            
    df_rec = pd.DataFrame(records)
    if len(df_rec) == 0:
        print("No alerts triggered.")
        return
        
    print(f"\nConviction Level | Alerts | Correct | Precision | Avg Savings (c/gal)")
    print("-" * 65)
    for conv in ["High", "Moderate", "Low"]:
        sub = df_rec[df_rec['conviction'] == conv]
        n_alerts = len(sub)
        n_correct = sub['is_correct'].sum()
        prec = n_correct / n_alerts if n_alerts > 0 else 0.0
        avg_sav = sub['savings'].mean() if n_alerts > 0 else 0.0
        print(f"{conv:<16} | {n_alerts:<6} | {n_correct:<7} | {prec:<9.2%} | {avg_sav:<+.2f}")

def main():
    print("==========================================================")
    print("      CONVICTION-CONDITIONAL MODEL PERFORMANCE AUDIT")
    print("==========================================================")
    
    if not os.path.exists(CSV_PATH):
        print(f"Error: CSV file not found at {CSV_PATH}")
        return
        
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    print("\n--- Unleaded / RBOB (RB) ---")
    analyze_conviction_levels(df_clean, "nymex_rb", "rack_u", 120, 15, 85)
    
    print("\n--- Diesel / Heating Oil (HO) ---")
    analyze_conviction_levels(df_clean, "nymex_ho", "rack_d", 240, 15, 85)
    print("==========================================================")

if __name__ == "__main__":
    main()
