import os
import sys
import pandas as pd
import numpy as np

def is_cme_holiday(dt):
    year, month, day = dt.year, dt.month, dt.day
    dow = dt.dayofweek # 0 is Monday, 6 is Sunday
    
    # Good Friday dates (NYMEX holiday)
    good_fridays = {
        2023: (4, 7),
        2024: (3, 29),
        2025: (4, 18),
        2026: (4, 3),
        2027: (3, 26)
    }
    if year in good_fridays and (month, day) == good_fridays[year]:
        return True

    # New Year's Day
    if month == 1 and day == 1:
        return True
    if month == 1 and day == 2 and dow == 0:
        return True
    if month == 12 and day == 31 and dow == 4:
        return True

    # MLK Day
    if month == 1 and dow == 0 and 15 <= day <= 21:
        return True

    # Presidents' Day
    if month == 2 and dow == 0 and 15 <= day <= 21:
        return True

    # Memorial Day
    if month == 5 and dow == 0 and day >= 25:
        return True

    # Juneteenth
    if month == 6 and day == 19:
        return True
    if month == 6 and day == 20 and dow == 0:
        return True
    if month == 6 and day == 18 and dow == 4:
        return True

    # Independence Day
    if month == 7 and day == 4:
        return True
    if month == 7 and day == 5 and dow == 0:
        return True
    if month == 7 and day == 3 and dow == 4:
        return True

    # Labor Day
    if month == 9 and dow == 0 and day <= 7:
        return True

    # Thanksgiving Day
    if month == 11 and dow == 3 and 22 <= day <= 28:
        return True

    # Christmas Day
    if month == 12 and day == 25:
        return True
    if month == 12 and day == 26 and dow == 0:
        return True
    if month == 12 and day == 24 and dow == 4:
        return True

    return False

def validate_graves_history(csv_path):
    if not os.path.exists(csv_path):
        print(f"Data validation failed: Graves history CSV not found at {csv_path}")
        sys.exit(1)
        
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Data validation failed: Failed to read Graves history CSV. Error: {e}")
        sys.exit(1)
        
    required_cols = ["date", "nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"]
    for col in required_cols:
        if col not in df.columns:
            print(f"Data validation failed: Missing column '{col}' in Graves history CSV.")
            sys.exit(1)
            
    # Check for empty dataframe
    if len(df) == 0:
        print("Data validation failed: Graves history CSV is empty.")
        sys.exit(1)

    # 1. Duplicate dates
    if df['date'].duplicated().any():
        dup_dates = df[df['date'].duplicated()]['date'].unique()
        print(f"Data validation failed: Duplicate dates found: {dup_dates}")
        sys.exit(1)

    # Convert date and sort check
    try:
        parsed_dates = pd.to_datetime(df['date'])
    except Exception as e:
        print(f"Data validation failed: Invalid date format in Graves history CSV. Error: {e}")
        sys.exit(1)

    # 2. Monotonic date ordering
    if not parsed_dates.is_monotonic_increasing:
        print("Data validation failed: Dates are not sorted chronologically.")
        sys.exit(1)

    # Check for gaps between consecutive rows
    date_diffs = parsed_dates.diff()
    max_gap_days = 7
    if (date_diffs > pd.Timedelta(days=max_gap_days)).any():
        indices = date_diffs[date_diffs > pd.Timedelta(days=max_gap_days)].index
        for idx in indices:
            print(f"Data validation failed: Large date gap of {date_diffs[idx].days} days found between {df.loc[idx-1, 'date']} and {df.loc[idx, 'date']}.")
        sys.exit(1)

    # 3. Impossible Prices (must be positive and within [1.00, 10.00])
    price_cols = ["nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"]
    for col in price_cols:
        valid_prices = df[col].dropna()
        if (valid_prices <= 0).any():
            print(f"Data validation failed: Negative or zero price found in '{col}'.")
            sys.exit(1)
        if (valid_prices < 1.00).any() or (valid_prices > 10.00).any():
            print(f"Data validation failed: Out of bounds price (< $1.00 or > $10.00) found in '{col}'.")
            sys.exit(1)

    # Sudden daily spikes/drops (> $1.00)
    for col in price_cols:
        col_clean = df[['date', col]].dropna().copy()
        if len(col_clean) > 1:
            diffs = col_clean[col].diff().abs()
            if (diffs > 1.00).any():
                bad_idx = diffs[diffs > 1.00].index
                for idx in bad_idx:
                    # Find matching row in original df to show original index
                    orig_row = df.loc[idx]
                    print(f"Data validation failed: Spurious price movement of ${diffs[idx]:.4f} in '{col}' on date {orig_row['date']}.")
                sys.exit(1)

    # 4. NaN Verification for NYMEX
    for idx, row in df.iterrows():
        dt = parsed_dates.iloc[idx]
        is_weekend = dt.dayofweek >= 5
        is_holiday = is_cme_holiday(dt)
        
        if not is_weekend and not is_holiday:
            if pd.isna(row['nymex_rb']) or pd.isna(row['nymex_ho']):
                print(f"Data validation failed: Missing NYMEX prices on standard trading day {row['date']}.")
                sys.exit(1)

    # 5. Settlement Alignment
    if not (df['nymex_rb'].isna() == df['nymex_ho'].isna()).all():
        print("Data validation failed: Mismatched NYMEX RBOB and Heating Oil price presence (one is NaN and the other is not).")
        sys.exit(1)

    print("Graves history data validation: PASSED")

def validate_prediction_log(log_path):
    if not os.path.exists(log_path):
        return
        
    try:
        df = pd.read_csv(log_path)
    except Exception as e:
        print(f"Data validation failed: Failed to read prediction log CSV. Error: {e}")
        sys.exit(1)

    required_cols = ["timestamp", "commodity", "predicted_direction", "actual_next_day_move_cents"]
    for col in required_cols:
        if col not in df.columns:
            print(f"Data validation failed: Missing column '{col}' in prediction log CSV.")
            sys.exit(1)

    valid_dirs = {"HIKE", "DROP", "FLAT"}
    if not df['predicted_direction'].isin(valid_dirs).all():
        invalid = df[~df['predicted_direction'].isin(valid_dirs)]['predicted_direction'].unique()
        print(f"Data validation failed: Invalid predicted direction(s) found in prediction log: {invalid}")
        sys.exit(1)

    valid_comms = {"RB", "HO"}
    if not df['commodity'].isin(valid_comms).all():
        invalid = df[~df['commodity'].isin(valid_comms)]['commodity'].unique()
        print(f"Data validation failed: Invalid commodity value(s) found in prediction log: {invalid}")
        sys.exit(1)

    for idx, val in enumerate(df['actual_next_day_move_cents']):
        if val == 'PENDING':
            continue
        try:
            float(val)
        except ValueError:
            print(f"Data validation failed: Invalid actual move value '{val}' at row {idx} in prediction log.")
            sys.exit(1)

    print("Prediction log validation: PASSED")

def validate_all(data_dir=None):
    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
    csv_path = os.path.join(data_dir, "graves_history.csv")
    log_path = os.path.join(data_dir, "prediction_log.csv")
    
    validate_graves_history(csv_path)
    validate_prediction_log(log_path)

if __name__ == "__main__":
    validate_all()
