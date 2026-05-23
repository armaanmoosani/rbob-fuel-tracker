import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def analyze_drawdown_streaks(df, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name):
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    # Store result flags for sequential alerts
    overall_alerts = []
    high_z_alerts = []
    mod_z_alerts = []
    low_z_alerts = []
    
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
            # An alert is "incorrect" if is_correct is False
            is_loss = not is_correct
            overall_alerts.append(is_loss)
            
            if abs_z >= 1.5:
                high_z_alerts.append(is_loss)
            elif abs_z >= 1.0:
                mod_z_alerts.append(is_loss)
            else:
                low_z_alerts.append(is_loss)
                
    def get_max_streak(losses_list):
        max_streak = 0
        current_streak = 0
        for is_loss in losses_list:
            if is_loss:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak
        
    print(f"\n================ Drawdown Streak Audit: {commodity_name} ================")
    print(f"Overall Alerts Max Losing Streak:       {get_max_streak(overall_alerts)} consecutive losses (total alerts: {len(overall_alerts)})")
    print(f"High Conviction (|Z| >= 1.5):           {get_max_streak(high_z_alerts)} consecutive losses (alerts: {len(high_z_alerts)})")
    print(f"Moderate Conviction (1.0 <= |Z| < 1.5): {get_max_streak(mod_z_alerts)} consecutive losses (alerts: {len(mod_z_alerts)})")
    print(f"Low Conviction (|Z| < 1.0):             {get_max_streak(low_z_alerts)} consecutive losses (alerts: {len(low_z_alerts)})")

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    run_drawdown_streaks(df_clean, "nymex_rb", "rack_u", 120, 15, 85, "RBOB Unleaded")
    run_drawdown_streaks(df_clean, "nymex_ho", "rack_d", 240, 15, 85, "Heating Oil Diesel")

# Helper wrapper
def run_drawdown_streaks(df_clean, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name):
    analyze_drawdown_streaks(df_clean, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name)

if __name__ == "__main__":
    main()
