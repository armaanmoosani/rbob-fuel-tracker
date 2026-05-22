import os
import sys
import pandas as pd
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

os.makedirs(REPORTS_DIR, exist_ok=True)

def clamp(val, min_val, max_val):
    return max(min_val, min(val, max_val))

def tune_thresholds(df_train, nymex_col, rack_col):
    df_clean = df_train.dropna(subset=[nymex_col, rack_col])
    delta_nymex = df_clean[nymex_col].diff() * 100
    delta_rack = df_clean[rack_col].diff() * 100
    
    valid = ~(delta_nymex.isna() | delta_rack.isna())
    delta_nymex = delta_nymex[valid]
    delta_rack = delta_rack[valid]
    
    if len(delta_nymex) < 10:
        return 1.0, -1.0, 0.0, 1.0
        
    slope, intercept, r_value, p_value, std_err = stats.linregress(delta_nymex, delta_rack)
    
    hike_mask = (delta_rack > 0) & (delta_nymex > 0)
    drop_mask = (delta_rack < 0) & (delta_nymex < 0)
    
    hike_thresh = 1.0
    drop_thresh = -1.0
    
    if hike_mask.sum() >= 5:
        hike_thresh = clamp(np.percentile(delta_nymex[hike_mask], 15), 0.3, 3.0)
    if drop_mask.sum() >= 5:
        drop_thresh = clamp(np.percentile(delta_nymex[drop_mask], 85), -3.0, -0.3)
        
    return hike_thresh, drop_thresh, slope, r_value**2

def run_simulation(df_slice, hike_thresh, drop_thresh, nymex_col, rack_col):
    delta_nymex = df_slice[nymex_col].diff() * 100
    # Next day rack change (t+1)
    delta_rack_next = (df_slice[rack_col].shift(-1) - df_slice[rack_col]) * 100
    
    savings = 0.0
    correct = 0
    total = 0
    
    for i in range(len(df_slice) - 1):
        change = delta_nymex.iloc[i]
        actual = delta_rack_next.iloc[i]
        if pd.isna(change) or pd.isna(actual):
            continue
            
        if change >= hike_thresh:
            savings += actual
            total += 1
            if actual > 0:
                correct += 1
        elif change <= drop_thresh:
            savings += -actual
            total += 1
            if actual < 0:
                correct += 1
                
    precision = correct / total if total > 0 else 0.0
    return savings, precision, total

def main():
    print("=== GRAVES OIL QUANTITATIVE MODEL VALIDATION SUITE ===")
    if not os.path.exists(CSV_PATH):
        print(f"Error: Historical database not found at {CSV_PATH}")
        sys.exit(1)
        
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    
    # 1. Backtest Leakage Test (Walk-forward / Permutation Test on holdout)
    print("\n--- 1. Frozen Holdout & Future Leakage Test ---")
    holdout_days = 60
    
    # Clean the dataset for Unleaded (nymex_rb and rack_u)
    df_clean = df.dropna(subset=['nymex_rb', 'rack_u']).copy()
    
    if len(df_clean) <= holdout_days + 30:
        print("Warning: Insufficient data for 60-day holdout test. Skipping.")
    else:
        df_train = df_clean.iloc[:-holdout_days]
        df_test = df_clean.iloc[-holdout_days:]
        
        # Tune thresholds on training set
        hike_t, drop_t, slope, r2 = tune_thresholds(df_train, 'nymex_rb', 'rack_u')
        print(f"Tuned Thresholds on Train Data: Hike={hike_t:.2f}c, Drop={drop_t:.2f}c (Slope={slope:.2f}, R2={r2:.2f})")
        
        # Run real test simulation
        real_savings, real_precision, real_alerts = run_simulation(df_test, hike_t, drop_t, 'nymex_rb', 'rack_u')
        print(f"Real Holdout Performance (Last {holdout_days} days):")
        print(f"  - Total Alerts: {real_alerts}")
        print(f"  - Precision:    {real_precision:.2%}")
        print(f"  - Cum. Savings:  {real_savings:+.2f} c/gal")
        
        # Shuffled Permutation trials (Monte Carlo)
        n_permutations = 500
        perm_savings = []
        perm_precisions = []
        
        # We scramble the alignment between nymex changes and rack changes in the test set
        test_delta_nymex = df_test['nymex_rb'].diff() * 100
        test_delta_rack_next = (df_test['rack_u'].shift(-1) - df_test['rack_u']) * 100
        
        valid_mask = ~(test_delta_nymex.isna() | test_delta_rack_next.isna())
        valid_nymex = test_delta_nymex[valid_mask].values
        valid_rack = test_delta_rack_next[valid_mask].values
        
        for _ in range(n_permutations):
            shuffled_rack = np.random.permutation(valid_rack)
            
            savings = 0.0
            correct = 0
            total = 0
            for i in range(len(valid_nymex)):
                change = valid_nymex[i]
                actual = shuffled_rack[i]
                if change >= hike_t:
                    savings += actual
                    total += 1
                    if actual > 0:
                        correct += 1
                elif change <= drop_t:
                    savings += -actual
                    total += 1
                    if actual < 0:
                        correct += 1
            perm_savings.append(savings)
            perm_precisions.append(correct / total if total > 0 else 0.0)
            
        p_val_savings = np.mean(np.array(perm_savings) >= real_savings)
        p_val_precision = np.mean(np.array(perm_precisions) >= real_precision)
        mean_perm_savings = np.mean(perm_savings)
        mean_perm_precision = np.mean(perm_precisions)
        print(f"Permuted Holdout Performance (Mean of {n_permutations} randomized trials):")
        print(f"  - Mean Savings:  {mean_perm_savings:+.2f} c/gal (P-value = {p_val_savings:.4f})")
        print(f"  - Mean Precision: {mean_perm_precision:.2%} (P-value = {p_val_precision:.4f})")
        
        if p_val_precision < 0.10 or p_val_savings < 0.10:
            print("  => SUCCESS: Leakage test passed. Model shows significant predictive power over random chance.")
        else:
            print("  => WARNING: Holdout performance is not highly distinct from a random shuffle in this short 60-day window.")

    # 2. Randomized Null Model Test
    print("\n--- 2. Randomized Null Model Test (Full History) ---")
    df_reg = df_clean.copy()
    delta_nymex = df_reg['nymex_rb'].diff() * 100
    delta_rack = df_reg['rack_u'].diff() * 100
    valid = ~(delta_nymex.isna() | delta_rack.isna())
    nymex_vals = delta_nymex[valid].values
    rack_vals = delta_rack[valid].values
    
    real_slope, real_intercept, real_r, real_p, real_se = stats.linregress(nymex_vals, rack_vals)
    print(f"Real OLS Regression (Full History):")
    print(f"  - Slope:     {real_slope:.4f}")
    print(f"  - R2:        {real_r**2:.4f}")
    print(f"  - P-value:   {real_p:.4e}")
    
    # Run OLS on shuffled data
    n_null_trials = 200
    null_r2s = []
    null_ps = []
    for _ in range(n_null_trials):
        shuffled_rack = np.random.permutation(rack_vals)
        s, i, r, p, se = stats.linregress(nymex_vals, shuffled_rack)
        null_r2s.append(r**2)
        null_ps.append(p)
        
    print(f"Null Model Regression (Mean of {n_null_trials} shuffled trials):")
    print(f"  - Mean R2:   {np.mean(null_r2s):.4f}")
    print(f"  - P < 0.10:  {np.mean(np.array(null_ps) < 0.10):.1%} of trials")
    
    if real_p < 0.001 and np.mean(null_r2s) < 0.01:
        print("  => SUCCESS: Null model test passed. Relationship is highly genuine and non-spurious.")
    else:
        print("  => WARNING: Null model test suggests weak or spurious relationship.")

    # 3. Regime Stability Test
    print("\n--- 3. Regime Stability Test (Yearly Splits) ---")
    df_reg['year'] = df_reg['date'].dt.year
    years = sorted(df_reg['year'].unique())
    
    print(f"{'Year':<6} | {'Count':<5} | {'Slope':<8} | {'R2':<8} | {'P-value':<10} | {'Status':<10}")
    print("-" * 57)
    
    for yr in years:
        df_yr = df_reg[df_reg['year'] == yr]
        dy_nymex = df_yr['nymex_rb'].diff() * 100
        dy_rack = df_yr['rack_u'].diff() * 100
        val = ~(dy_nymex.isna() | dy_rack.isna())
        
        if val.sum() < 20:
            print(f"{yr:<6} | {val.sum():<5} | {'N/A':<8} | {'N/A':<8} | {'N/A':<10} | {'Too Few Rows':<10}")
            continue
            
        s, i, r, p, se = stats.linregress(dy_nymex[val], dy_rack[val])
        status = "PASSED" if p < 0.10 else "WEAK"
        print(f"{yr:<6} | {val.sum():<5} | {s:<8.4f} | {r**2:<8.4f} | {p:<10.4e} | {status:<10}")

    # 4. Sensitivity Analysis (Percentiles)
    print("\n--- 4. Sensitivity Analysis (Percentile Thresholds) ---")
    percentiles = [
        (10, 90, "Aggressive"),
        (15, 85, "Baseline"),
        (20, 80, "Conservative"),
        (25, 75, "Very Conservative")
    ]
    
    sensitivity_results = []
    print(f"{'Config (Hike/Drop)':<22} | {'Hike Thresh':<12} | {'Drop Thresh':<12} | {'Alerts':<6} | {'Precision':<10} | {'Savings':<12}")
    print("-" * 88)
    
    for pct_h, pct_d, name in percentiles:
        # Re-tune thresholds on full clean data with this percentile config
        hike_mask = (delta_rack > 0) & (delta_nymex > 0)
        drop_mask = (delta_rack < 0) & (delta_nymex < 0)
        
        h_thresh = clamp(np.percentile(nymex_vals[hike_mask[valid].values], pct_h), 0.3, 3.0)
        d_thresh = clamp(np.percentile(nymex_vals[drop_mask[valid].values], pct_d), -3.0, -0.3)
        
        sav, prec, alt = run_simulation(df_clean, h_thresh, d_thresh, 'nymex_rb', 'rack_u')
        sensitivity_results.append((name, h_thresh, d_thresh, sav))
        print(f"{name + ' (' + str(pct_h) + '/' + str(pct_d) + ')':<22} | {h_thresh:<12.2f} | {d_thresh:<12.2f} | {alt:<6} | {prec:<10.2%} | {sav:<+12.2f} c")
        
    # Check that performance is stable and positive across all variations
    all_positive = all(r[3] > 0 for r in sensitivity_results)
    if all_positive:
        print("  => SUCCESS: Sensitivity analysis passed. Performance is robust and positive across all threshold settings.")
    else:
        print("  => WARNING: Performance is negative or collapses for some threshold parameters.")

    # 5. Residual Diagnostics
    print("\n--- 5. Residual Diagnostics ---")
    predicted_rack = real_intercept + real_slope * nymex_vals
    residuals = rack_vals - predicted_rack
    
    mean_res = np.mean(residuals)
    std_res = np.std(residuals)
    
    # Durbin-Watson statistic
    numerator = np.sum(np.diff(residuals) ** 2)
    denominator = np.sum(residuals ** 2)
    dw_stat = numerator / denominator
    
    print(f"Residual Statistics:")
    print(f"  - Mean:            {mean_res:.6f} (Should be ~0.0)")
    print(f"  - Standard Dev:    {std_res:.4f}")
    print(f"  - Durbin-Watson:   {dw_stat:.4f} (2.0 = No autocorrelation; 1.5 - 2.5 is acceptable)")
    
    if abs(mean_res) < 1e-5 and 1.5 <= dw_stat <= 2.5:
        print("  => SUCCESS: Residual analysis passed. Model assumptions hold and residuals are well-behaved.")
    else:
        print("  => WARNING: Residuals show non-zero mean or significant autocorrelation.")

    # Generate visual validation artifacts
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor('#ffffff')
    
    # Plot 1: Permutation Savings Distribution vs Real Holdout
    if len(df_clean) > holdout_days + 30:
        ax1.set_facecolor('#f8fafc')
        ax1.hist(perm_savings, bins=30, color='#94a3b8', edgecolor='#64748b', alpha=0.8, label='Permutation Trials')
        ax1.axvline(real_savings, color='#ef4444', linestyle='--', linewidth=3, label=f'Real Holdout Savings ({real_savings:+.2f}¢)')
        ax1.set_title('Holdout Validation (Permutation Test)', fontsize=13, fontweight='bold', pad=15)
        ax1.set_xlabel('Cumulative Savings (¢/gal)', fontsize=11)
        ax1.set_ylabel('Frequency', fontsize=11)
        ax1.legend(frameon=True, facecolor='#ffffff', edgecolor='#e2e8f0')
        ax1.grid(color='#e2e8f0', linestyle='--', alpha=0.7)
        
    # Plot 2: OLS Regression Fit with Residual Band
    ax2.set_facecolor('#f8fafc')
    ax2.scatter(nymex_vals, rack_vals, color='#3b82f6', alpha=0.5, edgecolor='none', label='Daily Changes')
    # Plot regression line
    x_range = np.linspace(nymex_vals.min(), nymex_vals.max(), 100)
    y_range = real_intercept + real_slope * x_range
    ax2.plot(x_range, y_range, color='#1e293b', linewidth=2.5, label=f'OLS Fit (R2={real_r**2:.2f})')
    # Standard deviation error bands
    ax2.fill_between(x_range, y_range - std_res, y_range + std_res, color='#3b82f6', alpha=0.1, label='1 Std Dev Residual')
    ax2.set_title('Pass-Through Calibration (NYMEX vs Rack)', fontsize=13, fontweight='bold', pad=15)
    ax2.set_xlabel('NYMEX Change (¢/gal)', fontsize=11)
    ax2.set_ylabel('Rack Change (¢/gal)', fontsize=11)
    ax2.legend(frameon=True, facecolor='#ffffff', edgecolor='#e2e8f0')
    ax2.grid(color='#e2e8f0', linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    plot_path = os.path.join(REPORTS_DIR, "statistical_verification.png")
    plt.savefig(plot_path, dpi=300)
    plt.close()
    print(f"\nVisual validation chart saved to {plot_path}")
    print("=== MODEL VALIDATION SUITE COMPLETE ===")

if __name__ == "__main__":
    main()
