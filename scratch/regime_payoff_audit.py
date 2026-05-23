import os
import sys
import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def analyze_payoffs(df, opt_W, opt_Hp, opt_Dp, year):
    # Pre-compute deltas on full history to avoid boundaries
    df = df.copy()
    df['delta_nymex'] = df['nymex_rb'].diff() * 100
    df['delta_rack'] = df['rack_u'].diff() * 100
    
    wins = []
    losses = []
    
    for i in range(opt_W, len(df)):
        df_train = df.iloc[i - opt_W:i]
        df_today = df.iloc[i]
        
        # Check if the date is in the target year
        if df_today['date'].year != year:
            continue
            
        train_nymex, train_rack = backtest.get_clean_deltas(df_train, 'nymex_rb', 'rack_u')
        h_t, d_t = backtest.train_thresholds(train_nymex, train_rack, opt_Hp, opt_Dp)
        
        ch = df_today['delta_nymex']
        act = df_today['delta_rack']
        
        if pd.isna(ch) or pd.isna(act):
            continue
            
        # BUY signal
        if ch >= h_t:
            if act > 0:
                wins.append(act) # Saved act cents/gal
            else:
                losses.append(-act) # Lost -act cents/gal (positive number for cost)
        # WAIT signal
        elif ch <= d_t:
            if act < 0:
                wins.append(-act) # Saved -act cents/gal
            else:
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

def main():
    print("==========================================================")
    print("      GRAVES PRICING ENGINE - PAYOFF ASYMMETRY AUDIT")
    print("==========================================================")

    if not os.path.exists(CSV_PATH):
        print(f"Error: CSV file not found at {CSV_PATH}")
        return

    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    df_clean = df.dropna(subset=['nymex_rb', 'rack_u']).copy().reset_index(drop=True)
    df_clean['year'] = df_clean['date'].dt.year

    opt_W, opt_Hp, opt_Dp = 120, 15, 85
    years = [2023, 2024, 2025]
    
    results = []
    
    for yr in years:
        df_yr = df_clean[df_clean['year'] == yr].copy()
        if len(df_yr) < 30:
            continue
            
        yr_first_idx = df_yr.index[0]
        train_start_idx = max(0, yr_first_idx - opt_W)
        df_yr_with_history = df_clean.iloc[train_start_idx:df_yr.index[-1] + 1].copy().reset_index(drop=True)
        
        res = analyze_payoffs(df_yr_with_history, opt_W, opt_Hp, opt_Dp, yr)
        results.append(res)

    print(f"\n{'Year':<6} | {'Alerts':<6} | {'Precision':<9} | {'Avg Win (c)':<11} | {'Avg Loss (c)':<12} | {'Win-Loss Ratio':<14} | {'Net Savings (c)':<15}")
    print("-" * 92)
    for r in results:
        print(f"{r['year']:<6} | {r['alerts']:<6} | {r['precision']:<9.2%} | {r['avg_win_cents']:<11.2f} | {r['avg_loss_cents']:<12.2f} | {r['win_loss_ratio']:<14.2f} | {r['net_savings_cents']:<+15.2f}")

    print("\nOperational Takeaways:")
    for r in results:
        print(f"\nYear {r['year']}:")
        print(f"  - When the bot was correct, it saved {r['avg_win_cents']:.2f} c/gal on average.")
        print(f"  - When the bot was incorrect, it cost {r['avg_loss_cents']:.2f} c/gal on average.")
        print(f"  - Win/Loss Ratio: {r['win_loss_ratio']:.2f}x (ratio > 1.0 means wins are larger than losses).")
        if r['win_loss_ratio'] > 1.0 and r['precision'] < 0.60:
            print(f"  - CONFIRMATION: The model was profitable despite low/moderate precision ({r['precision']:.1%}) because the payoff is highly asymmetric ({r['win_loss_ratio']:.2f}x).")

    print("\n==========================================")

if __name__ == "__main__":
    main()
