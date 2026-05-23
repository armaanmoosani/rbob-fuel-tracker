import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def run_weekday_audit(df, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name):
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    records = []
    for i in range(opt_W, len(df)):
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]
        
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, nymex_col, rack_col)
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, opt_Hp, opt_Dp)
        
        ch = df_today['delta_nymex']
        act = df_today['delta_rack']
        
        if pd.isna(ch) or pd.isna(act):
            continue
            
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
            # Get weekday: 0=Monday, ..., 4=Friday
            weekday_num = df_today['date'].dayofweek
            weekday_name = df_today['date'].strftime('%A')
            
            records.append({
                "weekday_num": weekday_num,
                "weekday_name": weekday_name,
                "is_correct": is_correct,
                "savings": act if direction == "BUY" else -act
            })
            
    df_rec = pd.DataFrame(records)
    if len(df_rec) == 0:
        print("No alerts triggered.")
        return
        
    print(f"\n================ Weekday Performance Audit: {commodity_name} ================")
    print(f"{'Weekday':<12} | {'Alerts':<6} | {'Correct':<7} | {'Precision':<9} | {'Avg Savings (c/gal)':<20}")
    print("-" * 65)
    # Order by weekday number
    for num in sorted(df_rec['weekday_num'].unique()):
        sub = df_rec[df_rec['weekday_num'] == num]
        name = sub['weekday_name'].iloc[0]
        n_alerts = len(sub)
        n_correct = sub['is_correct'].sum()
        prec = n_correct / n_alerts if n_alerts > 0 else 0.0
        avg_sav = sub['savings'].mean() if n_alerts > 0 else 0.0
        print(f"{name:<12} | {n_alerts:<6} | {n_correct:<7} | {prec:<9.2%} | {avg_sav:<+20.2f}")

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    run_weekday_audit(df_clean, "nymex_rb", "rack_u", 120, 15, 85, "RBOB Unleaded")
    run_weekday_audit(df_clean, "nymex_ho", "rack_d", 240, 15, 85, "Heating Oil Diesel")

if __name__ == "__main__":
    main()
