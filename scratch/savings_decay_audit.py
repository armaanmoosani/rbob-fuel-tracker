import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def run_savings_decay_audit(df, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp, commodity_name):
    # Pre-compute deltas
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    # We will log the actual rack changes at lag+1, lag+2, lag+3
    # relative to the day the signal was generated (day T)
    lag1_moves = []
    lag2_moves = []
    lag3_moves = []
    
    for i in range(opt_W, len(df)):
        # Check boundary condition to prevent off-by-one or out-of-bounds at tail
        # We need lag+3 to be within the dataset
        if i + 3 >= len(df):
            continue
            
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]  # Day T
        
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, nymex_col, rack_col)
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, opt_Hp, opt_Dp)
        
        ch = df_today['delta_nymex']
        
        # We only look at BUY_NOW signals
        if ch >= h_t:
            # Day T is index i.
            # Tonight's rack price (rack[T]) is df.iloc[i][rack_col]
            # lag+1 rack price is df.iloc[i+1][rack_col] (next trading day)
            # lag+2 rack price is df.iloc[i+2][rack_col]
            # lag+3 rack price is df.iloc[i+3][rack_col]
            
            p_T = df.iloc[i][rack_col]
            p_lag1 = df.iloc[i + 1][rack_col]
            p_lag2 = df.iloc[i + 2][rack_col]
            p_lag3 = df.iloc[i + 3][rack_col]
            
            # Change in cents/gal vs price at T
            move_1 = (p_lag1 - p_T) * 100
            move_2 = (p_lag2 - p_T) * 100
            move_3 = (p_lag3 - p_T) * 100
            
            lag1_moves.append(move_1)
            lag2_moves.append(move_2)
            lag3_moves.append(move_3)
            
    print(f"\n================ Savings Decay Audit: {commodity_name} ================")
    print(f"Total BUY_NOW signals audited: {len(lag1_moves)}")
    if len(lag1_moves) > 0:
        print(f"Average Rack Price Move (cents/gal):")
        print(f"  lag+1 (Next Day):    {np.mean(lag1_moves):+.2f} c/gal")
        print(f"  lag+2 (Day After):   {np.mean(lag2_moves):+.2f} c/gal")
        print(f"  lag+3 (3 Days Out):  {np.mean(lag3_moves):+.2f} c/gal")
    else:
        print("No BUY_NOW signals found.")

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    
    run_savings_decay_audit(df_clean, "nymex_rb", "rack_u", 120, 15, 85, "RBOB Unleaded")
    run_savings_decay_audit(df_clean, "nymex_ho", "rack_d", 240, 15, 85, "Heating Oil Diesel")

if __name__ == "__main__":
    main()
