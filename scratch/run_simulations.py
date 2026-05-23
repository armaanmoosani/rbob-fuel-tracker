import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import backtest
import verify_statistics

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")

def run_parameter_sensitivity(df):
    """
    Sweeps a dense grid of percentiles to test for parameter stability (overfitting check).
    If small changes in percentiles lead to massive changes in savings, the model is overfitted.
    """
    print("\n--- TEST 1: Parameter Sensitivity & Overfitting Sweep ---")
    df_clean = df.dropna(subset=['nymex_rb', 'rack_u']).copy()
    
    # Precompute deltas
    df_clean['delta_nymex'] = df_clean['nymex_rb'].diff() * 100
    df_clean['delta_rack'] = df_clean['rack_u'].diff() * 100
    
    # Exclude Mondays & Roll days for calibration
    df_train = df_clean.copy()
    df_train = df_train[df_train['date'].dt.dayofweek != 0]
    df_train = df_train[df_train['date'].dt.day > 5]
    
    hike_pcts = np.arange(5, 30, 2)  # 5% to 29%
    drop_pcts = np.arange(70, 95, 2)  # 70% to 93%
    
    results = []
    
    for Hp in hike_pcts:
        for Dp in drop_pcts:
            # Calibrate thresholds on train
            h_t, d_t = backtest.train_thresholds(df_train['delta_nymex'], df_train['delta_rack'], Hp, Dp)
            # Simulate on full clean data (with precomputed deltas)
            sav, prec, alerts, _ = verify_statistics.run_simulation(df_clean, h_t, d_t, 'nymex_rb', 'rack_u')
            results.append({
                "Hp": Hp,
                "Dp": Dp,
                "hike_t": h_t,
                "drop_t": d_t,
                "savings": sav,
                "precision": prec,
                "alerts": alerts
            })
            
    df_res = pd.DataFrame(results)
    
    # Check stats
    mean_sav = df_res['savings'].mean()
    std_sav = df_res['savings'].std()
    min_sav = df_res['savings'].min()
    max_sav = df_res['savings'].max()
    
    print(f"Sweep results across {len(df_res)} parameter combinations:")
    print(f"  - Average savings: {mean_sav:+.2f} c/gal")
    print(f"  - Std Dev:         {std_sav:.2f} c/gal (low std dev is better, shows stability)")
    print(f"  - Range:           [{min_sav:+.2f}c, {max_sav:+.2f}c]")
    
    # Overfitting verdict
    coef_var = std_sav / abs(mean_sav) if mean_sav != 0 else 999.0
    if coef_var < 0.15:
        print("  => VERDICT: Excellent stability. Performance is robust and not sensitive to micro-tuning.")
    elif coef_var < 0.30:
        print("  => VERDICT: Moderate stability. Model has minor sensitivity but remains robust.")
    else:
        print("  => VERDICT: WARNING! Spikey parameter space. High risk of overfitting.")
        
    return df_res

def run_black_swan_stress_test(df):
    """
    Simulates extreme market shocks (Black Swans) and checks model adaptability.
    """
    print("\n--- TEST 2: Geopolitical Black Swan Stress Test ---")
    df_shock = df.dropna(subset=['nymex_rb', 'rack_u']).copy().reset_index(drop=True)
    
    # Inject a series of extreme price spikes and drops in RBOB
    # Index 300: +40c spike (unprecedented)
    # Index 350: -40c drop (unprecedented)
    original_prices = df_shock['nymex_rb'].copy()
    
    df_shock.loc[300, 'nymex_rb'] += 0.40  # +40 cents
    df_shock.loc[301, 'nymex_rb'] += 0.10  # another +10 cents
    df_shock.loc[350, 'nymex_rb'] -= 0.40  # -40 cents
    df_shock.loc[351, 'nymex_rb'] -= 0.10  # another -10 cents
    
    # Re-run walk forward on the shocked data
    print("Running calibration on SHOCKED data...")
    cfg = {
        "MIN_ROWS_FOR_TUNING": 30,
        "BLEND_ALPHA": 0.3,
        "RB_HIKE_THRESHOLD_CENTS": 1.0,
        "RB_DROP_THRESHOLD_CENTS": -1.0,
        "HO_HIKE_THRESHOLD_CENTS": 1.0,
        "HO_DROP_THRESHOLD_CENTS": -1.0,
        "LAG_DAYS": 0,
        "ROLLING_WINDOW_DAYS": 120
    }
    
    # Get optimal params & metrics for RB on shocked data
    cfg_rb, msg_rb, _ = backtest.run_optimization(df_shock, 'nymex_rb', 'rack_u', 'RB', cfg)
    
    print(f"Shocked Config Output:")
    print(f"  - Calibrated Volatility (Std Dev): {cfg_rb['RB_nymex_daily_std']:.4f}c")
    print(f"  - Calibrated Hike Threshold:       {cfg_rb['RB_HIKE_THRESHOLD_CENTS']:.2f}c")
    print(f"  - Calibrated Drop Threshold:       {cfg_rb['RB_DROP_THRESHOLD_CENTS']:.2f}c")
    
    # Verify that standard deviation absorbed the shock
    # In normal data standard deviation is ~9.6c, with shocks it should be higher
    if cfg_rb['RB_nymex_daily_std'] > 10.0:
        print("  => SUCCESS: System successfully expanded volatility bands in response to price shocks.")
    else:
        print("  => WARNING: Volatility standard deviation remained insensitive to shocks.")

def run_contract_roll_audit(df):
    """
    Measures the exact proportion of savings generated on contract roll days
    vs. normal days to check for spurious edge.
    """
    print("\n--- TEST 3: Contract Roll Spurious Edge Audit ---")
    df_clean = df.dropna(subset=['nymex_rb', 'rack_u']).copy()
    df_clean['delta_nymex'] = df_clean['nymex_rb'].diff() * 100
    df_clean['delta_rack'] = df_clean['rack_u'].diff() * 100
    
    # Exclude Mondays for evaluation
    df_clean = df_clean[df_clean['date'].dt.dayofweek != 0]
    
    # Evaluate model under live thresholds
    h_t = 1.93
    d_t = -0.76
    
    roll_savings = 0.0
    normal_savings = 0.0
    roll_alerts = 0
    normal_alerts = 0
    
    for idx, row in df_clean.iterrows():
        ch = row['delta_nymex']
        act = row['delta_rack']
        if pd.isna(ch) or pd.isna(act):
            continue
            
        is_roll_day = row['date'].day <= 5
        
        if ch >= h_t:
            if is_roll_day:
                roll_savings += act
                roll_alerts += 1
            else:
                normal_savings += act
                normal_alerts += 1
        elif ch <= d_t:
            if is_roll_day:
                roll_savings += -act
                roll_alerts += 1
            else:
                normal_savings += -act
                normal_alerts += 1
                
    total_sav = roll_savings + normal_savings
    pct_roll = (roll_savings / total_sav * 100) if total_sav != 0 else 0
    print(f"Savings Distribution:")
    print(f"  - Roll-day Savings (Days 1-5 of Month): {roll_savings:+.2f} c/gal (Alerts: {roll_alerts})")
    print(f"  - Normal-day Savings (Rest of Month):   {normal_savings:+.2f} c/gal (Alerts: {normal_alerts})")
    print(f"  - Roll-day Proportion of Total Savings: {pct_roll:.2f}%")
    
    # We calibrate thresholds excluding rolls. If we still make good savings on normal days, the model is genuine.
    if normal_savings > 0 and normal_savings > roll_savings:
        print("  => SUCCESS: Model edge is genuine. The majority of savings are achieved outside the contract roll zones.")
    else:
        print("  => WARNING: Model depends heavily on roll-day artifacts for its performance.")

def run_holiday_boundary_test():
    """
    Tests specific historical holidays to verify CME Globex calendar logic.
    """
    print("\n--- TEST 4: CME Globex Calendar Holiday Verification ---")
    import validate_data
    from datetime import datetime
    
    test_holidays = [
        ("Thanksgiving 2025", datetime(2025, 11, 27)),
        ("Good Friday 2025", datetime(2025, 4, 18)),
        ("Christmas Day 2025", datetime(2025, 12, 25)),
        ("Normal Day 2025", datetime(2025, 12, 23))
    ]
    
    for name, dt in test_holidays:
        is_hol = validate_data.is_cme_holiday(dt)
        print(f"  - {name:<20} | Date: {dt.strftime('%Y-%m-%d')} | CME Holiday: {is_hol}")
        if "Normal Day" in name:
            assert not is_hol
        else:
            assert is_hol
            
    print("  => SUCCESS: CME Holiday alignments verified successfully.")

def main():
    print("==========================================================")
    print("      GRAVES OIL PRICING ENGINE - SIMULATION SUITE")
    print("==========================================================")
    
    if not os.path.exists(CSV_PATH):
        print(f"Historical database missing at: {CSV_PATH}")
        sys.exit(1)
        
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    # Run tests
    df_sensitivity = run_parameter_sensitivity(df)
    run_black_swan_stress_test(df)
    run_contract_roll_audit(df)
    run_holiday_boundary_test()
    
    print("\n==========================================================")
    print("             SIMULATION SUITE COMPLETE")
    print("==========================================================")

if __name__ == "__main__":
    main()
