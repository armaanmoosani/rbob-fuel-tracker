import unittest
import os
import sys
import base64
import pytz
from datetime import datetime, date

# Add current directory to path
sys.path.append(os.path.dirname(__file__))
import generate_preview

class TestPreview(unittest.TestCase):
    def setUp(self):
        self.tz = pytz.timezone('America/Chicago')
        
    def test_generate_intraday_chart_insufficient_data(self):
        # Less than 3 items -> returns None
        self.assertIsNone(generate_preview.generate_intraday_chart([], 2.10, 2.00, 2.20, 1.95, 5.0))
        self.assertIsNone(generate_preview.generate_intraday_chart([
            {"t": "2026-05-20T10:00:00-05:00", "p": 2.05}
        ], 2.10, 2.00, 2.20, 1.95, 5.0))

    def test_generate_intraday_chart_valid(self):
        # 3 items -> returns base64 string
        history = [
            {"t": "2026-05-20T10:00:00-05:00", "p": 2.00},
            {"t": "2026-05-20T11:00:00-05:00", "p": 2.05},
            {"t": "2026-05-20T12:00:00-05:00", "p": 2.10}
        ]
        res = generate_preview.generate_intraday_chart(history, 2.10, 2.00, 2.20, 1.95, 5.0)
        self.assertIsNotNone(res)
        decoded = base64.b64decode(res)
        self.assertTrue(len(decoded) > 0)

    def test_generate_5day_chart_insufficient_data(self):
        # Less than 5 items -> returns None
        self.assertIsNone(generate_preview.generate_5day_chart([], 2.10))
        self.assertIsNone(generate_preview.generate_5day_chart([
            {"t": "2026-05-20T10:00:00-05:00", "p": 2.05}
        ] * 4, 2.10))

    def test_generate_5day_chart_valid(self):
        # 5 items -> returns base64 string
        history_5d = [
            {"t": "2026-05-16T12:00:00-05:00", "p": 2.00},
            {"t": "2026-05-17T12:00:00-05:00", "p": 2.02},
            {"t": "2026-05-18T12:00:00-05:00", "p": 2.05},
            {"t": "2026-05-19T12:00:00-05:00", "p": 2.08},
            {"t": "2026-05-20T12:00:00-05:00", "p": 2.10}
        ]
        res = generate_preview.generate_5day_chart(history_5d, 2.10)
        self.assertIsNotNone(res)
        decoded = base64.b64decode(res)
        self.assertTrue(len(decoded) > 0)

    def test_build_html_email(self):
        now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=self.tz)
        alert_context = {
            'label': 'Routine 6-Hour Alert',
            'action': 'BUY NOW — Wholesale Gas (/RB) price hike expected.',
            'action_color': '#22c55e'
        }
        
        html = generate_preview.build_html_email(
            "Test Subject",
            current_price=2.20,
            open_price=2.00,
            high_price=2.25,
            low_price=1.95,
            daily_pct=10.0,
            now=now,
            alert_context=alert_context,
            chart_intraday_b64="mock_base64_intra",
            chart_5d_b64="mock_base64_5d",
            yesterday_close=2.00,
            five_day_high=2.25,
            five_day_low=1.95,
            thirty_day_avg=2.05
        )
        
        # Verify rendered text exists
        self.assertIn("Routine 6-Hour Alert", html)
        self.assertIn("BUY NOW", html)
        self.assertIn("mock_base64_intra", html)

if __name__ == "__main__":
    unittest.main()
