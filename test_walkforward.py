import os
import pandas as pd
import numpy as np
import backtest

def test_walk_forward_flow():
    print("Testing walk-forward components...")
    
    # 1. Test clamp
    assert backtest.clamp(5.0, 1.0, 3.0) == 3.0
    assert backtest.clamp(-5.0, -3.0, -1.0) == -3.0
    assert backtest.clamp(2.0, 1.0, 3.0) == 2.0
    print("[PASSED] clamp")

    # 2. Mock a dataframe to test data cleaning and delta calculations
    dates = pd.date_range(start="2026-01-01", periods=100, freq="B") # business days (excludes weekends)
    df_mock = pd.DataFrame({
        "date": dates,
        "nymex_rb": np.linspace(2.0, 2.5, 100) + np.random.normal(0, 0.02, 100),
        "rack_u": np.linspace(2.1, 2.6, 100) + np.random.normal(0, 0.02, 100)
    })
    
    # Test cleaning & delta conversion
    del_nymex, del_rack = backtest.get_clean_deltas(df_mock, "nymex_rb", "rack_u")
    assert isinstance(del_nymex, pd.Series)
    assert isinstance(del_rack, pd.Series)
    assert len(del_nymex) == len(del_rack)
    print(f"[PASSED] get_clean_deltas (cleaned length: {len(del_nymex)})")

    # 3. Test threshold training
    hike_t, drop_t = backtest.train_thresholds(del_nymex, del_rack, Hp=15, Dp=85)
    assert 0.3 <= hike_t <= 3.0
    assert -3.0 <= drop_t <= -0.3
    print(f"[PASSED] train_thresholds (Hike: {hike_t:.2f}c, Drop: {drop_t:.2f}c)")

    # 4. Test walk forward simulation function
    # Mocking larger history to support folds (W=30, test_size=10, folds=3 -> needs 60 rows min)
    df_large = pd.DataFrame({
        "date": pd.date_range(start="2026-01-01", periods=200, freq="B"),
        "nymex_rb": np.sin(np.linspace(0, 10, 200)) + 2.0,
        "rack_u": np.sin(np.linspace(0, 10, 200)) + 2.1
    })
    
    # Temporarily set variables inside simulate_walk_forward to run on small parameters
    # Let's inspect simulate_walk_forward output on mock data
    med_sav = backtest.simulate_walk_forward(df_large, "nymex_rb", "rack_u", W=100, Hp=15, Dp=85)
    assert isinstance(med_sav, float)
    print(f"[PASSED] simulate_walk_forward (Median OOS Savings: {med_sav:+.2f}c)")

    # 5. Verify config loading and updating
    cfg = backtest.load_config()
    assert isinstance(cfg, dict)
    print("[PASSED] load_config")

    print("\nALL WALK-FORWARD ENGINE TESTS PASSED!")

if __name__ == "__main__":
    test_walk_forward_flow()
