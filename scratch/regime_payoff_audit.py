import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def analyze_payoffs(df, opt_W, opt_Hp, opt_Dp, year, nymex_col, rack_col):
    # Pre-compute deltas on full history to avoid boundaries
    df = df.copy()
    df['delta_nymex'] = df[nymex_col].diff() * 100
    df['delta_rack'] = df[rack_col].diff() * 100
    
    wins = []
    losses = []
    
    for i in range(opt_W, len(df)):
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]
        
        # Check if the date is in the target year
        if df_today['date'].year != year:
            continue
            
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, nymex_col, rack_col)
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, opt_Hp, opt_Dp)
        
        ch = df_today['delta_nymex']
        act = df_today['delta_rack']
        
        if pd.isna(ch) or pd.isna(act):
            continue
            
        # BUY signal
        if ch >= h_t:
            if act > 0:
                wins.append(act) # Saved act cents/gal
            elif act < 0:
                losses.append(-act) # Lost -act cents/gal (positive number for cost)
        # WAIT signal
        elif ch <= d_t:
            if act < 0:
                wins.append(-act) # Saved -act cents/gal
            elif act > 0:
                losses.append(act) # Lost act cents/gal (positive number for cost)
                
    total_alerts = len(wins) + len(losses)
    precision = len(wins) / total_alerts if total_alerts > 0 else 0.0
    avg_win = np.mean(wins) if len(wins) > 0 else 0.0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.0
    payoff_asymmetry = avg_win - avg_loss
    ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    return {
        "year": year,
        "alerts": total_alerts,
        "wins": len(wins),
        "losses": len(losses),
        "precision": precision,
        "avg_win_cents": avg_win,
        "avg_loss_cents": avg_loss,
        "asymmetry_cents": payoff_asymmetry,
        "win_loss_ratio": ratio,
        "net_savings_cents": sum(wins) - sum(losses)
    }

def run_for_commodity(df_clean, name, nymex_col, rack_col, opt_W, opt_Hp, opt_Dp):
    print(f"\n--- Payoff Asymmetry for {name} (Win={opt_W}, Hp={opt_Hp}, Dp={opt_Dp}) ---")
    years = [2023, 2024, 2025]
    results = []
    
    for yr in years:
        df_yr = df_clean[df_clean['year'] == yr].copy()
        if len(df_yr) < 30:
            continue
            
        yr_first_idx = df_yr.index[0]
        train_start_idx = max(0, yr_first_idx - opt_W)
        df_yr_with_history = df_clean.iloc[train_start_idx:df_yr.index[-1] + 1].copy().reset_index(drop=True)
        
        res = analyze_payoffs(df_yr_with_history, opt_W, opt_Hp, opt_Dp, yr, nymex_col, rack_col)
        results.append(res)
        
    print(f"{'Year':<6} | {'Alerts':<6} | {'Precision':<9} | {'Avg Win (c)':<11} | {'Avg Loss (c)':<12} | {'Asymmetry (c)':<13} | {'Ratio':<6} | {'Net Savings (c)':<15}")
    print("-" * 105)
    for r in results:
        print(f"{r['year']:<6} | {r['alerts']:<6} | {r['precision']:<9.2%} | {r['avg_win_cents']:<11.2f} | {r['avg_loss_cents']:<12.2f} | {r['asymmetry_cents']:<13.2f} | {r['win_loss_ratio']:<6.2f} | {r['net_savings_cents']:<+15.2f}")

def main():
    print("======================================================================")
    print("         GRAVES PRICING ENGINE - PAYOFF ASYMMETRY AUDIT (RB & HO)")
    print("======================================================================")

    if not os.path.exists(CSV_PATH):
        print(f"Error: CSV file not found at {CSV_PATH}")
        return

    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy().reset_index(drop=True)
    df_clean['year'] = df_clean['date'].dt.year

    # RBOB (Gasoline)
    run_for_commodity(df_clean, "Unleaded / RBOB (RB)", "nymex_rb", "rack_u", 120, 15, 85)
    
    # Heating Oil (Diesel)
    run_for_commodity(df_clean, "Diesel / Heating Oil (HO)", "nymex_ho", "rack_d", 240, 15, 85)

    print("\n======================================================================")

if __name__ == "__main__":
    main()
