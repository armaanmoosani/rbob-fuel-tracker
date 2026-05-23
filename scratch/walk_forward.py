import pandas as pd
import numpy as np
from scipy import stats
import sys

def find_best_lag_and_window(df):
    windows = [90, 120, 180, 240, 365, None]
    correlations = {}
    for window in windows:
        if window is not None and len(df) < window:
            continue
        df_sliced = df.tail(window) if window else df
        for lag in range(0, 3):
            nymex = df_sliced['nymex_rb'].shift(lag)
            rack = df_sliced['rack_u']
            valid = ~(nymex.isna() | rack.isna())
            if valid.sum() < 20: continue
            slope, _, r_value, p_value, _ = stats.linregress(nymex[valid], rack[valid])
            correlations[(lag, window)] = r_value**2
    if not correlations: return 0, None
    best_lag, best_window = max(correlations, key=correlations.get)
    return best_lag, best_window

def get_thresholds(df, lag, window):
    if window: df = df.tail(window).copy()
    if lag > 0: df['nymex_rb'] = df['nymex_rb'].shift(lag)
    
    df_clean = df.dropna(subset=['nymex_rb', 'rack_u'])
    delta_nymex = df_clean['nymex_rb'].diff() * 100
    delta_rack = df_clean['rack_u'].diff() * 100
    
    valid = ~(delta_nymex.isna() | delta_rack.isna())
    delta_nymex = delta_nymex[valid]
    delta_rack = delta_rack[valid]
    
    hike_mask = (delta_rack > 0) & (delta_nymex > 0)
    drop_mask = (delta_rack < 0) & (delta_nymex < 0)
    
    hike_thresh = 1.0
    if hike_mask.sum() >= 5:
        hike_thresh = max(0.3, min(np.percentile(delta_nymex[hike_mask], 15), 3.0))
        
    drop_thresh = -1.0
    if drop_mask.sum() >= 5:
        drop_thresh = max(-3.0, min(np.percentile(delta_nymex[drop_mask], 85), -0.3))
        
    return hike_thresh, drop_thresh

df = pd.read_csv('data/graves_history.csv')
print("Total rows:", len(df))

# Start at row 200, step 30 rows at a time
correct_hikes = 0
false_hikes = 0
correct_drops = 0
false_drops = 0
missed_moves = 0

step_size = 30
start_idx = 200

print(f"{'Date Range':<25} | {'Lag/Win':<10} | {'H/D Thresh':<15} | {'Pred Hikes':<10} | {'Pred Drops':<10}")
print("-" * 80)

for i in range(start_idx, len(df), step_size):
    train_df = df.iloc[:i].copy()
    test_df = df.iloc[i:min(i+step_size, len(df))].copy()
    
    best_lag, best_win = find_best_lag_and_window(train_df)
    h_thresh, d_thresh = get_thresholds(train_df, best_lag, best_win)
    
    # We must combine the end of train_df with test_df so .diff() works across the boundary
    combined_df = pd.concat([train_df.tail(best_lag + 2), test_df])
    
    # Shift nymex by best_lag for testing
    if best_lag > 0:
        combined_df['nymex_rb'] = combined_df['nymex_rb'].shift(best_lag)
        
    delta_nymex = combined_df['nymex_rb'].diff() * 100
    delta_rack = combined_df['rack_u'].diff() * 100
    
    # Extract just the testing portion
    test_delta_nymex = delta_nymex.tail(len(test_df))
    test_delta_rack = delta_rack.tail(len(test_df))
    
    pred_hikes = 0
    pred_drops = 0
    
    for n_diff, r_diff in zip(test_delta_nymex, test_delta_rack):
        if pd.isna(n_diff) or pd.isna(r_diff): continue
        
        predicted_hike = (n_diff >= h_thresh)
        predicted_drop = (n_diff <= d_thresh)
        actual_hike = (r_diff > 0.1)
        actual_drop = (r_diff < -0.1)
        
        if predicted_hike:
            pred_hikes += 1
            if actual_hike: correct_hikes += 1
            else: false_hikes += 1
        elif predicted_drop:
            pred_drops += 1
            if actual_drop: correct_drops += 1
            else: false_drops += 1
        else:
            if actual_hike or actual_drop: missed_moves += 1
            
    date_str = f"{test_df['date'].iloc[0]} to {test_df['date'].iloc[-1]}"
    print(f"{date_str:<25} | L:{best_lag} W:{best_win if best_win else 'A':<4} | {h_thresh:.1f} / {d_thresh:.1f} | {pred_hikes:<10} | {pred_drops:<10}")

print("-" * 80)
print(f"Correct Hikes Predicted: {correct_hikes}")
print(f"False Hikes Predicted  : {false_hikes}")
print(f"Correct Drops Predicted: {correct_drops}")
print(f"False Drops Predicted  : {false_drops}")
print(f"Moves Missed (Flat Pred): {missed_moves}")
total_calls = correct_hikes + false_hikes + correct_drops + false_drops
print(f"Overall Alert Accuracy : {(correct_hikes + correct_drops) / total_calls * 100:.1f}%")

