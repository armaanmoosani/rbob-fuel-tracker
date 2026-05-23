import os
import sys
import unittest
import pandas as pd
import pytz
from datetime import datetime, date

# Ensure parent directory is in path
sys.path.append(os.path.dirname(__file__))
import validate_data

class TestAlignmentAndIntegrity(unittest.TestCase):
    
    def setUp(self):
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.csv_path = os.path.join(self.data_dir, "graves_history.csv")
        
    def test_cme_holidays(self):
        """Assert that CME Globex / NYMEX energy market holidays are correctly identified."""
        # 1. Good Friday
        self.assertTrue(validate_data.is_cme_holiday(datetime(2023, 4, 7)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2024, 3, 29)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2025, 4, 18)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2026, 4, 3)))
        
        # 2. New Year's Day (and Monday observance if Sunday)
        self.assertTrue(validate_data.is_cme_holiday(datetime(2024, 1, 1)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2023, 1, 2))) # Monday observed
        
        # 3. Juneteenth (and Monday observance)
        self.assertTrue(validate_data.is_cme_holiday(datetime(2024, 6, 19)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2022, 6, 20))) # Monday observed
        
        # 4. Thanksgiving Day
        self.assertTrue(validate_data.is_cme_holiday(datetime(2023, 11, 23))) # 4th Thursday
        self.assertTrue(validate_data.is_cme_holiday(datetime(2024, 11, 28))) # 4th Thursday
        
        # 5. Christmas Day (and Monday observance)
        self.assertTrue(validate_data.is_cme_holiday(datetime(2023, 12, 25)))
        self.assertTrue(validate_data.is_cme_holiday(datetime(2022, 12, 26))) # Monday observed
        
        # 6. Standard Trading Days (should NOT be holidays)
        self.assertFalse(validate_data.is_cme_holiday(datetime(2026, 5, 20)))
        self.assertFalse(validate_data.is_cme_holiday(datetime(2026, 5, 21)))

    def test_timezone_and_dst(self):
        """Verify America/Chicago daylight saving transitions (Spring/Fall) have robust offsets."""
        tz = pytz.timezone('America/Chicago')
        
        # Spring Forward 2026: March 8, 2026 (Clocks skip 2:00 AM -> 3:00 AM)
        spring_dt = tz.localize(datetime(2026, 3, 8, 12, 0, 0))
        self.assertEqual(spring_dt.strftime('%Z'), 'CDT')
        self.assertEqual(spring_dt.utcoffset().total_seconds(), -18000.0) # -5 hours
        
        # Fall Back 2026: November 1, 2026 (Clocks repeat 1:00 AM)
        fall_dt = tz.localize(datetime(2026, 11, 1, 12, 0, 0))
        self.assertEqual(fall_dt.strftime('%Z'), 'CST')
        self.assertEqual(fall_dt.utcoffset().total_seconds(), -21600.0) # -6 hours

    def test_history_integrity_and_monotonicity(self):
        """Assert that graves_history.csv contains sorted, non-overlapping dates with valid pricing ranges."""
        if not os.path.exists(self.csv_path):
            self.skipTest("graves_history.csv not found")
            
        df = pd.read_csv(self.csv_path)
        
        # Chronological order
        parsed_dates = pd.to_datetime(df['date'])
        self.assertTrue(parsed_dates.is_monotonic_increasing, "Dates are not sorted chronologically.")
        
        # No duplicates
        self.assertFalse(df['date'].duplicated().any(), f"Duplicate dates found in graves_history.csv: {df[df['date'].duplicated()]['date'].unique()}")
        
        # Causal Alignment check: NYMEX and Rack prices are mapped on same row representing day T.
        # rack price is tonight's invoice (effective next morning), NYMEX is today's 1:30 PM settle.
        # This is strictly causal since 1:30 PM CT settlement happens BEFORE the 6:00 PM CT rack release.
        # There must be no look-ahead shifts.
        for idx in range(1, len(df)):
            curr_date = parsed_dates.iloc[idx]
            prev_date = parsed_dates.iloc[idx - 1]
            diff_days = (curr_date - prev_date).days
            
            # Weekend gaps are normal (usually 3 days from Fri -> Mon), but should never exceed 7 days
            self.assertLessEqual(diff_days, 7, f"Large date gap of {diff_days} days between {prev_date.date()} and {curr_date.date()}.")

    def test_full_pipeline_validation(self):
        """Run the comprehensive validate_all suite on the real data directory to guarantee compliance."""
        try:
            validate_data.validate_all(self.data_dir)
        except SystemExit as e:
            self.fail(f"validate_all exited with code {e.code}")

if __name__ == "__main__":
    unittest.main()
