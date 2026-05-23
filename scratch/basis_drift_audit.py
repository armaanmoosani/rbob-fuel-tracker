import os
import sys
import numpy as np
import pandas as pd
from scipy.stats import norm

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")

def mann_kendall_test(x):
    n = len(x)
    if n < 10:
        return False, 1.0, 0.0, 0.0
    
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += np.sign(x[j] - x[i])
            
    # Calculate variance of S
    var_s = (n * (n - 1) * (2 * n + 5)) / 18.0
    
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
        
    p_value = 2 * (1 - norm.cdf(abs(z)))
    
    # Sen's slope
    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            slopes.append((x[j] - x[i]) / (j - i))
    sens_slope = np.median(slopes) if slopes else 0.0
    
    # Kendall's tau
    tau = s / (0.5 * n * (n - 1))
    
    return (p_value < 0.05), p_value, sens_slope, tau

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file missing: {CSV_PATH}")
        return
        
    df = pd.read_csv(CSV_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df_clean = df.dropna(subset=['nymex_rb', 'nymex_ho', 'rack_u', 'rack_d']).copy()
    
    # Compute basis in cents/gal
    df_clean['basis_rb'] = (df_clean['rack_u'] - df_clean['nymex_rb']) * 100
    df_clean['basis_ho'] = (df_clean['rack_d'] - df_clean['nymex_ho']) * 100
    
    print("==========================================================")
    print("                 BASIS DRIFT ANALYSIS AUDIT")
    print("==========================================================")
    
    for name, col in [("RBOB Unleaded", "basis_rb"), ("Heating Oil Diesel", "basis_ho")]:
        print(f"\n--- Commodity: {name} ---")
        full_basis = df_clean[col].values
        
        # Mann-Kendall on full history
        drifted, p_val, slope, tau = mann_kendall_test(full_basis)
        print("Full History Trend Check:")
        print(f"  Kendall's Tau: {tau:.4f}")
        print(f"  P-Value: {p_val:.4e}")
        print(f"  Sen's Slope: {slope:.6f} cents/gal/day")
        print(f"  Significant Drift Detected: {drifted}")
        
        # Mann-Kendall on last 90 business days
        last_90 = full_basis[-90:]
        drifted_90, p_val_90, slope_90, tau_90 = mann_kendall_test(last_90)
        print("\nLast 90 Trading Days Trend Check:")
        print(f"  Kendall's Tau: {tau_90:.4f}")
        print(f"  P-Value: {p_val_90:.4f}")
        print(f"  Sen's Slope: {slope_90:.6f} cents/gal/day")
        print(f"  Significant Drift Detected: {drifted_90}")
        
    print("==========================================================")

if __name__ == "__main__":
    main()
