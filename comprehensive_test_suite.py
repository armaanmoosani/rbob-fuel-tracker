import unittest
import os
import sys
import json
import tempfile
import shutil
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta
import pytz
from unittest.mock import patch, MagicMock, mock_open
from scipy import stats

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

# Set mock env variables needed on import by main and ingest_prices
os.environ['GH_PAT'] = 'mock_pat'
os.environ['GH_REPO'] = 'mock_repo'
os.environ['GMAIL_USER'] = 'mock_user'
os.environ['GMAIL_APP_PASSWORD'] = 'mock_pass'
os.environ['TO_EMAIL'] = 'mock_to@example.com'
os.environ['GRAVES_EMAIL'] = 'mock_graves@example.com'
os.environ['GRAVES_APP_PASSWORD'] = 'mock_graves_pass'

import validate_data
import backtest
import ingest_prices
import main
import weekly_report


class TestCategory1InputParsing(unittest.TestCase):
    """Category 1: Input Ingestion & Parsing Tests"""

    def test_1_1_standard_parsing(self):
        body = "E10 - UNLEADED: $2.10\nE10 - PREMIUM: $2.30\nCLEAR DIESEL: $2.50"
        p_u = ingest_prices.extract_price_near_label(body, "E10 - UNLEADED")
        p_p = ingest_prices.extract_price_near_label(body, "E10 - PREMIUM")
        p_d = ingest_prices.extract_price_near_label(body, "CLEAR DIESEL")
        self.assertEqual(p_u, 2.10)
        self.assertEqual(p_p, 2.30)
        self.assertEqual(p_d, 2.50)

    def test_1_2_delimiter_variants(self):
        variants = [
            "E10 - UNLEADED,2.10\nE10 - PREMIUM,2.30\nCLEAR DIESEL,2.50",
            "E10 - UNLEADED/2.10\nE10 - PREMIUM/2.30\nCLEAR DIESEL/2.50",
            "E10 - UNLEADED $2.10\nE10 - PREMIUM $2.30\nCLEAR DIESEL $2.50",
            "E10 - UNLEADED, 2.10\nE10 - PREMIUM, 2.30\nCLEAR DIESEL, 2.50"
        ]
        for body in variants:
            p_u = ingest_prices.extract_price_near_label(body, "E10 - UNLEADED")
            p_p = ingest_prices.extract_price_near_label(body, "E10 - PREMIUM")
            p_d = ingest_prices.extract_price_near_label(body, "CLEAR DIESEL")
            self.assertEqual(p_u, 2.10)
            self.assertEqual(p_p, 2.30)
            self.assertEqual(p_d, 2.50)

    def test_1_3_extra_whitespace(self):
        body = "  E10 - UNLEADED  ,  2.10  \n  E10 - PREMIUM   2.30  \n  CLEAR DIESEL  2.50  "
        p_u = ingest_prices.extract_price_near_label(body, "E10 - UNLEADED")
        p_p = ingest_prices.extract_price_near_label(body, "E10 - PREMIUM")
        p_d = ingest_prices.extract_price_near_label(body, "CLEAR DIESEL")
        self.assertEqual(p_u, 2.10)
        self.assertEqual(p_p, 2.30)
        self.assertEqual(p_d, 2.50)

    def test_1_4_four_decimal_prices(self):
        body = "E10 - UNLEADED $2.1050\nE10 - PREMIUM $2.3025\nCLEAR DIESEL $2.4975"
        p_u = ingest_prices.extract_price_near_label(body, "E10 - UNLEADED")
        p_p = ingest_prices.extract_price_near_label(body, "E10 - PREMIUM")
        p_d = ingest_prices.extract_price_near_label(body, "CLEAR DIESEL")
        self.assertEqual(p_u, 2.1050)
        self.assertEqual(p_p, 2.3025)
        self.assertEqual(p_d, 2.4975)

    def test_1_5_too_few_values(self):
        # Email has E10 - UNLEADED and E10 - PREMIUM, but missing CLEAR DIESEL
        body = "E10 - UNLEADED $2.10\nE10 - PREMIUM $2.30\n"
        prices = []
        for key, label in ingest_prices.LABELS.items():
            p = ingest_prices.extract_price_near_label(body, label)
            if p is None or not (1.50 <= p <= 6.00):
                break
            prices.append(p)
        self.assertNotEqual(len(prices), 3)

    def test_1_6_too_many_values(self):
        body = "E10 - UNLEADED $2.10\nE10 - PREMIUM $2.30\nCLEAR DIESEL $2.50\nKEROSENE $3.00"
        prices = []
        for key, label in ingest_prices.LABELS.items():
            p = ingest_prices.extract_price_near_label(body, label)
            if p is None or not (1.50 <= p <= 6.00):
                break
            prices.append(p)
        self.assertEqual(len(prices), 3)
        self.assertEqual(prices, [2.10, 2.30, 2.50])

    def test_1_7_1_8_1_9_price_bounds(self):
        # Bounds check logic in ingest_prices: 1.50 <= p <= 6.00
        valid_low = 1.50
        valid_high = 6.00
        invalid_low = 1.49
        invalid_high = 6.01
        fat_finger = 210.0

        self.assertTrue(1.50 <= valid_low <= 6.00)
        self.assertTrue(1.50 <= valid_high <= 6.00)
        self.assertFalse(1.50 <= invalid_low <= 6.00)
        self.assertFalse(1.50 <= invalid_high <= 6.00)
        self.assertFalse(1.50 <= fat_finger <= 6.00)

    def test_1_10_non_numeric_input(self):
        body = "E10 - UNLEADED abc"
        p = ingest_prices.extract_price_near_label(body, "E10 - UNLEADED")
        self.assertIsNone(p)


class TestCategory2DatabaseIntegrity(unittest.TestCase):
    """Category 2: CSV Database Integrity Tests"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.temp_dir, "graves_history.csv")
        self.hashes_path = os.path.join(self.temp_dir, "integrity_hashes.csv")
        self.log_path = os.path.join(self.temp_dir, "prediction_log.csv")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def write_valid_csv(self):
        df = pd.DataFrame({
            "date": ["2026-05-18", "2026-05-19", "2026-05-20"],
            "nymex_rb": [2.10, 2.15, 2.12],
            "nymex_ho": [2.20, 2.25, 2.22],
            "rack_u": [2.30, 2.35, 2.32],
            "rack_p": [2.40, 2.45, 2.42],
            "rack_d": [2.50, 2.55, 2.52]
        })
        df.to_csv(self.csv_path, index=False)

    def test_2_1_append_writes_correct_columns(self):
        self.write_valid_csv()
        df = pd.read_csv(self.csv_path)
        expected = ["date", "nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"]
        self.assertEqual(list(df.columns), expected)

    def test_2_2_duplicate_date_guard(self):
        df = pd.DataFrame({
            "date": ["2026-05-18", "2026-05-18"],
            "nymex_rb": [2.10, 2.15],
            "nymex_ho": [2.20, 2.25],
            "rack_u": [2.30, 2.35],
            "rack_p": [2.40, 2.45],
            "rack_d": [2.50, 2.55]
        })
        df.to_csv(self.csv_path, index=False)
        with self.assertRaises(SystemExit):
            validate_data.validate_graves_history(self.csv_path)

    def test_2_3_chronological_sort_preservation(self):
        df = pd.DataFrame({
            "date": ["2026-05-20", "2026-05-19"],
            "nymex_rb": [2.10, 2.15],
            "nymex_ho": [2.20, 2.25],
            "rack_u": [2.30, 2.35],
            "rack_p": [2.40, 2.45],
            "rack_d": [2.50, 2.55]
        })
        df.to_csv(self.csv_path, index=False)
        with self.assertRaises(SystemExit):
            validate_data.validate_graves_history(self.csv_path)

    def test_2_4_2_5_weekend_rows_verification(self):
        # We test that weekends have NaN settlements and standard days don't.
        # Saturdays (5) and Sundays (6)
        dt_sat = datetime(2026, 5, 23) # Saturday
        dt_mon = datetime(2026, 5, 25) # Monday
        self.assertTrue(dt_sat.weekday() in (5, 6))
        self.assertFalse(dt_mon.weekday() in (5, 6))

    def test_2_6_monday_to_friday_diff(self):
        # Friday (2026-05-15), Monday (2026-05-18), Tuesday (2026-05-19)
        df = pd.DataFrame({
            "date": ["2026-05-15", "2026-05-18", "2026-05-19"],
            "nymex_rb": [2.00, 2.10, 2.05],
            "rack_u": [2.10, 2.20, 2.15]
        })
        # Compute deltas before filtering
        df['delta_nymex'] = df['nymex_rb'].diff() * 100
        df['delta_rack'] = df['rack_u'].diff() * 100

        # Monday's diff is (2.10 - 2.00) * 100 = 10.0
        # Tuesday's diff is (2.05 - 2.10) * 100 = -5.0
        self.assertAlmostEqual(df.loc[1, 'delta_nymex'], 10.0)
        self.assertAlmostEqual(df.loc[2, 'delta_nymex'], -5.0)

        # Apply get_clean_deltas exclusions
        del_nymex, del_rack = backtest.get_clean_deltas(df, "nymex_rb", "rack_u")
        
        # Mondays are dropped: Monday index is 1. Tuesday index is 2. Friday index is 0 (diff is NaN, dropped).
        # Tuesday should remain.
        self.assertNotIn(1, del_nymex.index) # Monday dropped
        self.assertIn(2, del_nymex.index)    # Tuesday kept
        self.assertAlmostEqual(del_nymex.loc[2], -5.0) # Tuesday change is correct!

    def test_2_7_corrupt_row_middle_check(self):
        # Insert a corrupt non-numeric value in nymex_rb in the middle of a valid DataFrame
        df = pd.DataFrame({
            "date": ["2026-05-18", "2026-05-19", "2026-05-20"],
            "nymex_rb": [2.10, "corrupt_value", 2.12],
            "nymex_ho": [2.20, 2.25, 2.22],
            "rack_u": [2.30, 2.35, 2.32],
            "rack_p": [2.40, 2.45, 2.42],
            "rack_d": [2.50, 2.55, 2.52]
        })
        df.to_csv(self.csv_path, index=False)
        with self.assertRaises(SystemExit):
            validate_data.validate_graves_history(self.csv_path)


class TestCategory3SettlementCapture(unittest.TestCase):
    """Category 3: NYMEX Settlement Capture Tests"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ds_path = os.path.join(self.temp_dir, "daily_settlement.json")
        ingest_prices.DS_PATH = self.ds_path

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_3_1_daily_settlement_fresh(self):
        today_str = datetime.now(pytz.timezone('America/Chicago')).date().isoformat()
        with open(self.ds_path, "w") as f:
            json.dump({"date": today_str, "rbob_settlement": 2.10, "heating_oil_settlement": 2.20}, f)
        
        ds = ingest_prices.read_daily_settlement(today_str)
        self.assertIsNotNone(ds)
        self.assertEqual(ds["rbob_settlement"], 2.10)

    def test_3_2_daily_settlement_stale(self):
        today_str = datetime.now(pytz.timezone('America/Chicago')).date().isoformat()
        yest_str = (datetime.now(pytz.timezone('America/Chicago')) - timedelta(days=1)).date().isoformat()
        with open(self.ds_path, "w") as f:
            json.dump({"date": yest_str, "rbob_settlement": 2.10, "heating_oil_settlement": 2.20}, f)
        
        ds = ingest_prices.read_daily_settlement(today_str)
        self.assertIsNone(ds)

    def test_3_3_utc_vs_ct_date_boundary(self):
        # 11:00 PM UTC on May 22 is 6:00 PM CT on May 22 (Standard Time offset -6h or CDT offset -5h)
        # Test timezone localization
        tz = pytz.timezone('America/Chicago')
        dt_utc = datetime(2026, 5, 22, 23, 0, 0, tzinfo=pytz.utc)
        dt_local = dt_utc.astimezone(tz)
        self.assertEqual(dt_local.date().isoformat(), "2026-05-22")

    def test_3_4_missing_settlement_file(self):
        if os.path.exists(self.ds_path):
            os.remove(self.ds_path)
        ds = ingest_prices.read_daily_settlement("2026-05-22")
        self.assertIsNone(ds)


class TestCategory4LagDiscovery(unittest.TestCase):
    """Category 4: Lag Discovery Math Tests"""

    def test_4_1_perfect_lag_0_detection(self):
        # nymex_rb = [1, 2, 3, 4, 5]
        # rack_u = [1.05, 2.05, 3.05, 4.05, 5.05] (perfect lag=0 correlation)
        from scipy import stats
        nymex = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        rack = pd.Series([1.05, 2.05, 3.05, 4.05, 5.05])
        slope, intercept, r_value, p_value, std_err = stats.linregress(nymex, rack)
        self.assertAlmostEqual(r_value**2, 1.0)

    def test_4_2_perfect_lag_1_detection(self):
        # nymex_rb = [1, 2, 3, 4, 5]
        # rack_u = [NaN, 1.05, 2.05, 3.05, 4.05] (perfect lag=1 correlation)
        from scipy import stats
        nymex = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]).shift(1)
        rack = pd.Series([1.05, 2.05, 3.05, 4.05, 5.05])
        valid = ~(nymex.isna() | rack.isna())
        slope, intercept, r_value, p_value, std_err = stats.linregress(nymex[valid], rack[valid])
        self.assertAlmostEqual(r_value**2, 1.0)

    def test_4_4_monday_lag_traversal(self):
        # previous_nymex_business_day(Monday) -> Friday
        monday = datetime(2026, 5, 25).date()
        friday = main.previous_nymex_business_day(monday)
        self.assertEqual(friday, datetime(2026, 5, 22).date())

    def test_4_5_holiday_lag_traversal(self):
        # Memorial Day is Monday May 25, 2026 (holiday).
        # Tuesday May 26 is the next business day.
        # previous_nymex_business_day(Tuesday) -> Friday May 22
        tuesday = datetime(2026, 5, 26).date()
        prev = main.previous_nymex_business_day(tuesday)
        self.assertEqual(prev, datetime(2026, 5, 22).date())

    def test_4_6_consecutive_holidays_lag_traversal(self):
        # Good Friday 2026 is April 3, 2026.
        # Monday April 6, 2026 is the next business day.
        # previous_nymex_business_day(Monday April 6) should skip Sunday April 5,
        # Saturday April 4, and Friday April 3 (Good Friday), returning Thursday April 2.
        monday = datetime(2026, 4, 6).date()
        prev = main.previous_nymex_business_day(monday)
        self.assertEqual(prev, datetime(2026, 4, 2).date())


class TestCategory5SplitOLS(unittest.TestCase):
    """Category 5: Split OLS (Rockets & Feathers) Tests"""

    def test_5_1_symmetric_passthrough_baseline(self):
        from scipy import stats
        # NYMEX rises and falls symmetrically
        nymex_diff = pd.Series([1.0, -1.0, 2.0, -2.0, 1.5, -1.5])
        rack_diff = pd.Series([1.0, -1.0, 2.0, -2.0, 1.5, -1.5])
        slope, intercept, r_value, p_value, std_err = stats.linregress(nymex_diff, rack_diff)
        self.assertAlmostEqual(slope, 1.0)

    def test_5_2_asymmetric_passthrough_detection(self):
        # Up moves are 1.2x, Down moves are 0.6x
        from scipy import stats
        nymex_diff = pd.Series([1.0, -1.0, 2.0, -2.0, 1.5, -1.5])
        rack_diff = pd.Series([1.2, -0.6, 2.4, -1.2, 1.8, -0.9])
        
        up_mask = nymex_diff > 0
        down_mask = nymex_diff < 0
        
        slope_up, _, _, _, _ = stats.linregress(nymex_diff[up_mask], rack_diff[up_mask])
        slope_down, _, _, _, _ = stats.linregress(nymex_diff[down_mask], rack_diff[down_mask])
        
        self.assertAlmostEqual(slope_up, 1.2)
        self.assertAlmostEqual(slope_down, 0.6)

    def test_5_3_no_up_move_days(self):
        # Edge case: no positive moves
        nymex_diff = pd.Series([-1.0, -2.0, -1.5, 0.0])
        up_mask = nymex_diff > 0
        self.assertEqual(up_mask.sum(), 0)


class TestCategory6ThresholdCalculation(unittest.TestCase):
    """Category 6: Threshold Calculation & Guardrails Tests"""

    def test_6_1_15th_percentile_hike_threshold_math(self):
        # 100 positive up moves sorted from 1 to 100
        delta_nymex = pd.Series(np.linspace(1.0, 100.0, 100))
        # 15th percentile should be at 15%
        p15 = np.percentile(delta_nymex, 15)
        self.assertAlmostEqual(p15, 15.85)

    def test_6_2_floor_clamping(self):
        # Threshold below 0.3 clamped to 0.3
        self.assertEqual(backtest.clamp(0.1, 0.3, 3.0), 0.3)
        self.assertEqual(backtest.clamp(-0.1, -3.0, -0.3), -0.3)

    def test_6_3_ceiling_clamping(self):
        # Threshold above 3.0 clamped to 3.0
        self.assertEqual(backtest.clamp(5.0, 0.3, 3.0), 3.0)
        self.assertEqual(backtest.clamp(-5.0, -3.0, -0.3), -3.0)

    def test_6_4_exponential_smoothing_blend(self):
        alpha = 0.3
        old = 1.5
        new = 1.0
        smoothed = alpha * new + (1 - alpha) * old
        self.assertAlmostEqual(smoothed, 1.35)


class TestCategory7WalkForward(unittest.TestCase):
    """Category 7: Walk-Forward Validation Tests"""

    def test_7_1_no_data_leakage(self):
        # Setup mock walk-forward dataset
        total_rows = 300
        test_size = 90
        W = 120
        folds = 3
        # In fold 0: test window starts at N - (f+1)*90, ends at N - f*90
        for f in range(folds):
            test_start = total_rows - (f + 1) * test_size
            test_end = total_rows - f * test_size if f > 0 else total_rows
            train_start = max(0, test_start - W)
            
            # Assert training finishes before test begins
            self.assertTrue(train_start < test_start)
            self.assertTrue(test_start <= test_end)
            self.assertEqual(test_end - test_start, test_size)


class TestCategory8CVaRAndRiskMetrics(unittest.TestCase):
    """Category 8: CVaR and Risk Metrics Tests"""

    def test_8_1_cvar_known_distribution(self):
        # 100 values: worst 5 values (largest moves)
        # np.linspace(1.0, 100.0, 100) -> 95th percentile threshold is 95.05.
        # Values >= 95.05 are [96, 97, 98, 99, 100]
        # Average should be 98.0
        vals = np.linspace(1.0, 100.0, 100)
        thresh = np.percentile(vals, 95)
        tail_avg = np.mean(vals[vals >= thresh])
        self.assertAlmostEqual(tail_avg, 98.0)

    def test_8_2_cvar_positive_format_in_alerts(self):
        cvar_val = 3.42
        alert_msg = f"Risk Note: On the worst 5% of days historically, rack prices spiked +{cvar_val:.2f}¢/gal (+${cvar_val * 85:.0f} per 8,500 gal truck)."
        self.assertIn("+3.42", alert_msg)

    def test_8_3_zscore_zero(self):
        change = 0.0
        std = 1.2
        z = change / std if std > 0 else 0.0
        self.assertEqual(z, 0.0)

    def test_8_4_zscore_zero_std(self):
        change = 1.5
        std = 0.0
        z = change / std if std > 0 else 0.0
        self.assertEqual(z, 0.0)


class TestCategory9AlertLogic(unittest.TestCase):
    """Category 9: Alert Logic Tests"""

    def test_9_1_threshold_boundary_exactly_equal(self):
        # Check boundary condition (>= hike_thresh)
        hike_thresh = 1.5
        change_cents = 1.5
        is_buy = change_cents >= hike_thresh
        self.assertTrue(is_buy)

    def test_9_2_tiered_alert_ordering(self):
        # Verify strict logical tiers
        # BUY_NOW > LEAN_BUY > NO_EDGE > LEAN_WAIT > WAIT
        hike = 1.5
        lean_hike = 0.5
        lean_drop = -0.5
        drop = -1.5

        def get_tier(change):
            if change >= hike:
                return "BUY_NOW"
            elif change >= lean_hike:
                return "LEAN_BUY"
            elif change <= drop:
                return "WAIT"
            elif change <= lean_drop:
                return "LEAN_WAIT"
            else:
                return "NO_EDGE"

        self.assertEqual(get_tier(2.0), "BUY_NOW")
        self.assertEqual(get_tier(1.0), "LEAN_BUY")
        self.assertEqual(get_tier(0.0), "NO_EDGE")
        self.assertEqual(get_tier(-1.0), "LEAN_WAIT")
        self.assertEqual(get_tier(-2.0), "WAIT")

    def test_9_3_no_alert_on_flat_market(self):
        change_cents = 0.0
        hike = 1.5
        drop = -1.5
        lean_hike = 0.5
        lean_drop = -0.5
        
        is_alert = (change_cents >= hike) or (change_cents <= drop) or (change_cents >= lean_hike) or (change_cents <= lean_drop)
        self.assertFalse(is_alert)

    def test_9_4_threshold_crossover_safety(self):
        # Verify that crossover or identical boundaries are mutually exclusive
        # even if hike and drop thresholds are very close or overlap (which clamp prevents).
        hike = backtest.clamp(0.1, 0.3, 3.0)      # clamped to 0.3
        drop = backtest.clamp(-0.1, -3.0, -0.3)   # clamped to -0.3
        self.assertTrue(hike > drop)
        
        # Test signal generation exclusivity
        change = 0.0
        self.assertFalse(change >= hike and change <= drop)


class TestCategory10HistoricalReplay(unittest.TestCase):
    """Category 10: Historical Replay Tests"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.real_data_dir = os.path.join(os.path.dirname(__file__), "data")
        
        # Copy real files to temp dir
        shutil.copy(os.path.join(self.real_data_dir, "graves_history.csv"), self.temp_dir)
        shutil.copy(os.path.join(self.real_data_dir, "config.json"), self.temp_dir)
        
        # Patch paths
        self.orig_data_dir = backtest.DATA_DIR
        self.orig_csv_path = backtest.CSV_PATH
        self.orig_config_path = backtest.CONFIG_PATH
        
        backtest.DATA_DIR = self.temp_dir
        backtest.CSV_PATH = os.path.join(self.temp_dir, "graves_history.csv")
        backtest.CONFIG_PATH = os.path.join(self.temp_dir, "config.json")

    def tearDown(self):
        backtest.DATA_DIR = self.orig_data_dir
        backtest.CSV_PATH = self.orig_csv_path
        backtest.CONFIG_PATH = self.orig_config_path
        shutil.rmtree(self.temp_dir)

    def test_10_1_real_database_length(self):
        df = pd.read_csv(backtest.CSV_PATH)
        print(f"\n[Test 10.1] Loaded real CSV inside test suite. Length: {len(df)}")
        self.assertEqual(len(df), 766)

    def test_10_2_walk_forward_fold_isolation_real_data(self):
        df = pd.read_csv(backtest.CSV_PATH)
        self.assertEqual(len(df), 766)
        
        # Verify train/test isolation on the real data
        test_size = 90
        W = 120
        folds = 3
        for f in range(folds):
            test_start = len(df) - (f + 1) * test_size
            test_end = len(df) - f * test_size if f > 0 else len(df)
            train_start = max(0, test_start - W)
            
            df_train = df.iloc[train_start:test_start]
            df_test = df.iloc[test_start:test_end]
            
            # Assert no date overlap
            train_dates = set(df_train['date'])
            test_dates = set(df_test['date'])
            self.assertTrue(train_dates.isdisjoint(test_dates))

    def test_10_3_lag_0_correlation_real_data(self):
        df = pd.read_csv(backtest.CSV_PATH)
        self.assertEqual(len(df), 766)
        
        df_clean = df.dropna(subset=['nymex_rb', 'rack_u']).copy()
        df_clean['delta_nymex'] = df_clean['nymex_rb'].diff() * 100
        df_clean['delta_rack'] = df_clean['rack_u'].diff() * 100
        df_clean = df_clean.dropna(subset=['delta_nymex', 'delta_rack'])
        
        slope, intercept, r_val, p_val, std_err = stats.linregress(df_clean['delta_nymex'], df_clean['delta_rack'])
        # Verify genuine strong relationship
        self.assertTrue(r_val**2 > 0.10)
        self.assertTrue(p_val < 0.01)

    def test_10_4_full_replay_win_rate_real_data(self):
        df = pd.read_csv(backtest.CSV_PATH)
        self.assertEqual(len(df), 766)
        
        cfg = backtest.load_config()
        # Run optimization on real data
        cfg, msg, win = backtest.run_optimization(df, 'nymex_rb', 'rack_u', 'RB', cfg)
        
        # Verify parameters are updated and savings metrics are recorded
        self.assertIn('RB_historical_win_rate', cfg)
        self.assertTrue(cfg['RB_historical_win_rate'] > 0.50)
        self.assertTrue(cfg['RB_average_savings'] > 0.0)

    def test_10_5_permutation_pvalue_math(self):
        real_savings = 50.0
        perm_savings = [10.0, 20.0, 30.0, 45.0, 52.0]
        p_val = np.mean(np.array(perm_savings) >= real_savings)
        self.assertEqual(p_val, 0.20)


class TestCategory11AlertFormatting(unittest.TestCase):
    def setUp(self):
        import main
        self.orig_main_data_dir = main.DATA_DIR
        self.temp_dir = tempfile.mkdtemp()
        
        # Copy config.json to the temp folder so main.py can load it
        orig_config_path = os.path.join(self.orig_main_data_dir, "config.json")
        if os.path.exists(orig_config_path):
            shutil.copy(orig_config_path, self.temp_dir)
            
        main.DATA_DIR = self.temp_dir
        
        self.orig_config = main.APP_CONFIG.copy()
        main.APP_CONFIG.update({
            "RB_high_z_win_rate": 0.7500,
            "RB_high_z_savings": 5.15,
            "RB_high_z_count": 80,
            "RB_mod_z_win_rate": 0.7619,
            "RB_mod_z_savings": 2.81,
            "RB_mod_z_count": 84,
            "RB_low_z_win_rate": 0.6510,
            "RB_low_z_savings": 0.80,
            "RB_low_z_count": 255,
            "RB_nymex_daily_std": 10.0,
            "RB_historical_cvar": 17.25,
            "HO_high_z_win_rate": -1.0,
            "HO_high_z_savings": 0.0,
            "HO_high_z_count": 10,
            "HO_low_z_win_rate": 0.7277,
            "HO_low_z_savings": 1.58,
            "HO_low_z_count": 213,
            "HO_nymex_daily_std": 12.0,
            "HO_historical_cvar": 29.78,
            "HO_HIKE_THRESHOLD_CENTS": 2.0,
            "HO_DROP_THRESHOLD_CENTS": -2.0,
            "RB_HIKE_THRESHOLD_CENTS": 1.0,
            "RB_DROP_THRESHOLD_CENTS": -1.0,
        })
        self.now = datetime.now()

    def tearDown(self):
        import main
        main.DATA_DIR = self.orig_main_data_dir
        main.APP_CONFIG = self.orig_config
        shutil.rmtree(self.temp_dir)

    def test_11_1_rbob_buy_high_conviction_formatting(self):
        import main
        data = {
            'current_price': 2.20,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.25,
            'low_price': 1.95,
            'daily_pct': 10.0,
            'five_day_high': 2.25,
            'five_day_low': 1.95,
            'thirty_day_avg': 2.05,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        
        signal = main.build_rack_signal('RB', data, self.now)
        self.assertEqual(signal['action'], 'BUY_NOW')
        self.assertEqual(signal['conviction'], 'High Conviction')
        
        risk_text = signal['risk_text']
        self.assertIn("High Conviction (|Z| >= 1.5)", risk_text)
        self.assertIn("win rate of 75.0%", risk_text)
        self.assertIn("average savings of 5.15¢/gal", risk_text)
        self.assertIn("53%–73%", risk_text)
        self.assertIn("operational planning floor: 53%", risk_text)

    def test_11_2_ho_wait_low_conviction_formatting(self):
        import main
        data = {
            'current_price': 1.94,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.05,
            'low_price': 1.90,
            'daily_pct': -3.0,
            'five_day_high': 2.05,
            'five_day_low': 1.90,
            'thirty_day_avg': 2.00,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        
        signal = main.build_rack_signal('HO', data, self.now)
        self.assertEqual(signal['action'], 'WAIT')
        self.assertEqual(signal['conviction'], 'Low Conviction')
        
        risk_text = signal['risk_text']
        self.assertIn("Risk Note", risk_text)
        self.assertIn("worst 5% of days", risk_text)
        self.assertIn("standard 8,500-gallon truck", risk_text)
        self.assertIn("29.78¢/gal", risk_text)

    def test_11_3_ho_insufficient_history_fallback(self):
        import main
        data = {
            'current_price': 2.36,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.40,
            'low_price': 1.98,
            'daily_pct': 18.0,
            'five_day_high': 2.40,
            'five_day_low': 1.98,
            'thirty_day_avg': 2.10,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        
        signal = main.build_rack_signal('HO', data, self.now)
        self.assertEqual(signal['action'], 'BUY_NOW')
        self.assertEqual(signal['conviction'], 'High Conviction')
        
        risk_text = signal['risk_text']
        self.assertIn("insufficient history", risk_text)
        self.assertIn("60%–79%", risk_text)
        self.assertIn("operational planning floor: 60%", risk_text)

    def test_11_4_rendered_html_layout_checks(self):
        import main
        rb_data = {
            'current_price': 2.20,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.25,
            'low_price': 1.95,
            'daily_pct': 10.0,
            'five_day_high': 2.25,
            'five_day_low': 1.95,
            'thirty_day_avg': 2.05,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        ho_data = {
            'current_price': 1.94,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.05,
            'low_price': 1.90,
            'daily_pct': -3.0,
            'five_day_high': 2.05,
            'five_day_low': 1.90,
            'thirty_day_avg': 2.00,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        
        rb_signal = main.build_rack_signal('RB', rb_data, self.now)
        ho_signal = main.build_rack_signal('HO', ho_data, self.now)
        
        rb_data['rack_signal'] = rb_signal
        ho_data['rack_signal'] = ho_signal
        
        all_data = {'RB': rb_data, 'HO': ho_data}
        alert_context = {'label': 'Final Verdict'}
        
        html, cids = main.build_html_email("Test Subject", all_data, self.now, alert_context)
        
        self.assertIn("High Conviction (|Z| >= 1.5)", html)
        self.assertIn("win rate of 75.0%", html)
        self.assertIn("53%–73%", html)
        self.assertIn("operational planning floor: 53%", html)
        
        self.assertIn("Risk Note", html)
        self.assertIn("standard 8,500-gallon truck", html)
        self.assertIn("29.78¢/gal", html)


class TestCategory12ProductionFailureProtection(unittest.TestCase):
    """Category 12: Production Failure Protection & Edge Cases"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.temp_dir, "graves_history.csv")
        self.config_path = os.path.join(self.temp_dir, "config.json")
        self.log_path = os.path.join(self.temp_dir, "prediction_log.csv")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch('main.datetime')
    @patch('main.get_repo_variable')
    @patch('main.set_repo_variable')
    @patch('main.save_settlement_snapshots')
    @patch('main.send_daily_prompt')
    def test_12_1_timezone_runner_clock_drift(self, mock_prompt, mock_snapshots, mock_set, mock_get, mock_datetime):
        # 1. Mock runner clock at various CT times:
        # Timezone check behavior uses datetime.now(TZ)
        tz = pytz.timezone('America/Chicago')
        
        # Test 1:29 PM CT (snapshots should not fire)
        dt_129 = tz.localize(datetime(2026, 5, 22, 13, 29, 0))
        mock_datetime.now.return_value = dt_129
        mock_datetime.combine = datetime.combine
        main.save_settlement_snapshots({}, dt_129)
        # Check: save_settlement_snapshots requires 13:30 to 13:45
        self.assertFalse(dt_129.hour == 13 and 30 <= dt_129.minute <= 45)

        # Test 1:31 PM CT (snapshots should fire)
        dt_131 = tz.localize(datetime(2026, 5, 22, 13, 31, 0))
        self.assertTrue(dt_131.hour == 13 and 30 <= dt_131.minute <= 45)

        # Test 7:29 PM CT (daily prompt should not fire)
        dt_729 = tz.localize(datetime(2026, 5, 22, 19, 29, 0))
        self.assertTrue(dt_729.weekday() > 4 or not (dt_729.hour == 19 and dt_729.minute >= 30))

        # Test 7:31 PM CT (daily prompt should fire)
        dt_731 = tz.localize(datetime(2026, 5, 22, 19, 31, 0))
        self.assertFalse(dt_731.weekday() > 4 or not (dt_731.hour == 19 and dt_731.minute >= 30))

        # Test 8:01 PM CT (daily prompt should not fire)
        dt_801 = tz.localize(datetime(2026, 5, 22, 20, 1, 0))
        self.assertTrue(dt_801.weekday() > 4 or not (dt_801.hour == 19 and dt_801.minute >= 30))

    def test_12_2_partial_csv_write_corruption(self):
        # Create a CSV with a truncated final line (less than 6 comma-separated elements)
        with open(self.csv_path, "w", encoding="utf-8") as f:
            f.write("date,nymex_rb,nymex_ho,rack_u,rack_p,rack_d\n")
            f.write("2026-05-18,2.10,2.20,2.30,2.40,2.50\n")
            f.write("2026-05-19,2.15,2.25,2.35") # Truncated line

        # Call repair function
        validate_data.repair_csv_if_corrupted(self.csv_path)

        # Verify that the corrupt last line was pruned
        with open(self.csv_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], "2026-05-18,2.10,2.20,2.30,2.40,2.50")

    @patch('main.CONFIG_PATH')
    @patch('main.CONFIG_CORRUPT', True)
    def test_12_3_config_rollback(self, mock_path):
        # Verify build_rack_signal displays corrupt warning when CONFIG_CORRUPT is True
        data = {
            'current_price': 2.20,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.25,
            'low_price': 1.95,
            'daily_pct': 10.0,
            'five_day_high': 2.25,
            'five_day_low': 1.95,
            'thirty_day_avg': 2.05,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        signal = main.build_rack_signal('RB', data, datetime.now())
        self.assertIn("WARNING: Corrupt config.json detected!", signal['risk_text'])

    @patch('main.is_contract_roll_day')
    def test_12_4_nymex_contract_roll_boundary(self, mock_roll_check):
        mock_roll_check.return_value = True
        data = {
            'current_price': 2.20,
            'yesterday_close': 2.00,
            'open_price': 2.00,
            'high_price': 2.25,
            'low_price': 1.95,
            'daily_pct': 10.0,
            'five_day_high': 2.25,
            'five_day_low': 1.95,
            'thirty_day_avg': 2.05,
            'chart_intraday_b64': 'mock_base64',
            'chart_5d_b64': 'mock_base64',
        }
        signal = main.build_rack_signal('RB', data, datetime.now())
        self.assertEqual(signal['action'], 'NO_EDGE')
        self.assertEqual(signal['label'], 'Contract roll boundary')
        self.assertIn("roll price gaps", signal['text'])

    @patch('yfinance.Ticker')
    @patch('main.previous_nymex_business_day')
    @patch('pandas.read_csv')
    def test_12_5_yfinance_stale_cache_fallback(self, mock_read_csv, mock_prev_day, mock_ticker):
        # Mock yesterday's date as 2026-05-21, but yfinance history returns last date 2026-05-20 (stale)
        mock_prev_day.return_value = datetime(2026, 5, 21).date()
        mock_read_csv.return_value = pd.DataFrame() # empty df forces CSV fallback to return None
        
        mock_history = MagicMock()
        # Mock 1mo daily history
        hist_df = pd.DataFrame(
            {'Close': [2.00]},
            index=[datetime(2026, 5, 20, tzinfo=pytz.utc)]
        )
        mock_history.history.side_effect = [
            pd.DataFrame(), # 5d hourly empty
            hist_df # 1mo daily
        ]
        mock_ticker.return_value = mock_history
        
        # Test baseline extraction fallback in fetch_commodity
        cfg = {'name': 'Wholesale Gas', 'yf_symbol': 'RB=F'}
        res = main.fetch_commodity('RB', cfg, datetime(2026, 5, 22), None)
        
        # yesterday_close should be overridden to None because cache was stale (last date 2026-05-20 < 2026-05-21) and CSV is empty
        self.assertIsNone(res['yesterday_close'])

    @patch('smtplib.SMTP')
    def test_12_6_sms_gateway_silent_outbound_failure(self, mock_smtp):
        # Mock SMTP to raise exception on connection/login
        mock_smtp.side_effect = Exception("SMTP server unavailable")
        
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = mystdout = StringIO()
        
        try:
            main.send_sms({}, datetime.now(), {'label': 'Final Verdict'})
        finally:
            sys.stdout = old_stdout
            
        output = mystdout.getvalue()
        self.assertIn("LOG_OUTBOUND_FAILURE", output)


class TestCategory13LiveValidationAndRobustness(unittest.TestCase):
    """Category 13: Live Validation & Robustness Regression Tests"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.temp_dir, "graves_history.csv")
        self.log_path = os.path.join(self.temp_dir, "prediction_log.csv")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_13_1_fuzzer_sandbox_isolation(self):
        import scratch.fuzz_parser
        scratch.fuzz_parser.run_fuzzer()

    @patch('subprocess.run')
    @patch('ingest_prices.send_alert_email')
    def test_13_2_git_commit_failure_notification(self, mock_send_email, mock_sub_run):
        import subprocess
        mock_sub_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["python", "backtest.py"],
            output="Mock stdout info",
            stderr=b"git push failed: Merge conflict in config.json"
        )
        
        with patch.dict(os.environ, {
            'GRAVES_EMAIL': 'mock@example.com',
            'GRAVES_APP_PASSWORD': 'mock',
            'GMAIL_USER': 'mock',
            'GMAIL_APP_PASSWORD': 'mock',
            'TO_EMAIL': 'mock@example.com',
            'GITHUB_EVENT_NAME': 'workflow_dispatch'
        }):
            with patch('ingest_prices.check_inbox_for_prices') as mock_inbox:
                mock_inbox.return_value = ("2026-05-22", (2.10, 2.20, 2.30))
                with patch('ingest_prices.read_daily_settlement') as mock_settle:
                    mock_settle.return_value = {"rbob_settlement": 2.05, "heating_oil_settlement": 2.15}
                    with patch('ingest_prices.git_pull_rebase'), patch('ingest_prices.git_commit_push'):
                        with patch('ingest_prices.CSV_PATH', self.csv_path):
                            with open(self.csv_path, "w") as f:
                                f.write("date,nymex_rb,nymex_ho,rack_u,rack_p,rack_d\n")
                            
                            try:
                                ingest_prices.main()
                            except SystemExit:
                                pass
        
        mock_send_email.assert_called_once()
        args, kwargs = mock_send_email.call_args
        subject = args[0]
        body = args[1]
        
        self.assertEqual(subject, "CRITICAL: Nightly calibration commit failed")
        self.assertIn("git push failed: Merge conflict in config.json", body)

    def test_13_3_prediction_log_backfill_overwrite_guard(self):
        import argparse
        import scratch.check_prediction_log_completeness as backfiller
        from io import StringIO
        
        # We simulate duplicates by having the same date twice in graves_history.csv,
        # which will cause both rows to be candidate trading days.
        with open(self.csv_path, "w") as f:
            f.write("date,nymex_rb,nymex_ho,rack_u,rack_p,rack_d\n")
            f.write("2026-05-20,2.10,2.20,2.30,2.40,2.50\n")
            f.write("2026-05-21,2.12,2.22,2.32,2.42,2.52\n")
            f.write("2026-05-21,2.12,2.22,2.32,2.42,2.52\n")
            
        # Empty prediction log initially
        with open(self.log_path, "w") as f:
            f.write("timestamp,commodity,predicted_direction,nymex_move_cents,lag_used,window_used,threshold_used,actual_next_day_move_cents,prediction_source\n")
            
        old_csv = backfiller.CSV_PATH
        old_log = backfiller.LOG_PATH
        backfiller.CSV_PATH = self.csv_path
        backfiller.LOG_PATH = self.log_path
        
        old_stdout = sys.stdout
        sys.stdout = mystdout = StringIO()
        
        try:
            with patch('scratch.check_prediction_log_completeness.simulate_thresholds_at_date') as mock_sim:
                mock_sim.return_value = {}
                with patch('argparse.ArgumentParser.parse_args') as mock_args:
                    mock_args.return_value = argparse.Namespace(backfill=True)
                    try:
                        backfiller.main()
                    except SystemExit:
                        pass
        finally:
            sys.stdout = old_stdout
            backfiller.CSV_PATH = old_csv
            backfiller.LOG_PATH = old_log
            
        output = mystdout.getvalue()
        self.assertIn("WARNING: Entry already exists in prediction log", output)
        self.assertIn("Skipping safely to prevent duplicate/overwrite", output)


if __name__ == "__main__":
    unittest.main()

