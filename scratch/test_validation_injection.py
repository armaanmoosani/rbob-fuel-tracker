import os
import sys
import shutil
import subprocess

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_DIR, "data")
CSV_PATH = os.path.join(DATA_DIR, "graves_history.csv")
BACKUP_PATH = os.path.join(DATA_DIR, "graves_history.csv.bak")

def run_validator():
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_DIR, "validate_data.py")],
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout + result.stderr

def restore_backup():
    if os.path.exists(BACKUP_PATH):
        shutil.copyfile(BACKUP_PATH, CSV_PATH)
        os.remove(BACKUP_PATH)

def main():
    print("Starting data validation injection tests...")
    
    # 1. Ensure clean data passes
    code, output = run_validator()
    if code != 0:
        print(f"FAILED: Initial clean data did not pass validator (exit code {code}). Output:\n{output}")
        sys.exit(1)
    print("PASS: Initial clean data passed validator successfully.")

    # Create backup
    shutil.copyfile(CSV_PATH, BACKUP_PATH)

    try:
        # Test Case A: Duplicate Date
        print("\n--- Test Case A: Duplicate Date Injected ---")
        with open(CSV_PATH, "r") as f:
            lines = f.readlines()
        # Duplicate the last line
        lines.append(lines[-1])
        with open(CSV_PATH, "w") as f:
            f.writelines(lines)
            
        code, output = run_validator()
        if code == 1 and "Duplicate dates found" in output:
            print("PASS: Successfully blocked duplicate date injection.")
        else:
            print(f"FAILED: Did not detect duplicate date (exit code {code}). Output:\n{output}")
            sys.exit(1)
            
        # Restore
        shutil.copyfile(BACKUP_PATH, CSV_PATH)

        # Test Case B: Impossible negative price
        print("\n--- Test Case B: Negative Price Injected ---")
        with open(CSV_PATH, "r") as f:
            lines = f.readlines()
        # Modify last line's rack price to be negative
        parts = lines[-1].strip().split(',')
        parts[3] = "-2.5000"
        lines[-1] = ",".join(parts) + "\n"
        with open(CSV_PATH, "w") as f:
            f.writelines(lines)
            
        code, output = run_validator()
        if code == 1 and "Negative or zero price found" in output:
            print("PASS: Successfully blocked negative price injection.")
        else:
            print(f"FAILED: Did not detect negative price (exit code {code}). Output:\n{output}")
            sys.exit(1)
            
        # Restore
        shutil.copyfile(BACKUP_PATH, CSV_PATH)

        # Test Case C: Out of bounds price spike (> $1.00 change)
        print("\n--- Test Case C: Spurious Price Spike Injected ---")
        with open(CSV_PATH, "r") as f:
            lines = f.readlines()
        # Modify last line's rack price to spike by $2.00
        parts = lines[-1].strip().split(',')
        prev_parts = lines[-2].strip().split(',')
        parts[3] = f"{float(prev_parts[3]) + 2.00:.4f}"
        lines[-1] = ",".join(parts) + "\n"
        with open(CSV_PATH, "w") as f:
            f.writelines(lines)
            
        code, output = run_validator()
        if code == 1 and "Spurious price movement" in output:
            print("PASS: Successfully blocked spurious price spike injection.")
        else:
            print(f"FAILED: Did not detect spurious price spike (exit code {code}). Output:\n{output}")
            sys.exit(1)
            
        # Restore
        shutil.copyfile(BACKUP_PATH, CSV_PATH)

        # Test Case D: Missing NYMEX on standard business day
        print("\n--- Test Case D: Missing NYMEX Price on Weekday Injected ---")
        with open(CSV_PATH, "r") as f:
            lines = f.readlines()
        # Find a weekday row (e.g. Wednesday or Thursday) near the end and make NYMEX price NaN
        # Let's just find the last line and if it's a weekday, make NYMEX price empty
        parts = lines[-1].strip().split(',')
        # Let's verify the day of the week
        date_str = parts[0]
        import pandas as pd
        dt = pd.to_datetime(date_str)
        if dt.dayofweek < 5:  # It's a weekday
            parts[1] = ""  # nymex_rb is empty
            lines[-1] = ",".join(parts) + "\n"
            with open(CSV_PATH, "w") as f:
                f.writelines(lines)
                
            code, output = run_validator()
            # Since we cleared nymex_rb, it should trigger mismatched presence or missing NYMEX on weekday
            if code == 1 and ("Missing NYMEX prices on standard trading day" in output or "Mismatched NYMEX" in output):
                print("PASS: Successfully blocked missing NYMEX price on weekday injection.")
            else:
                print(f"FAILED: Did not detect missing NYMEX price on weekday (exit code {code}). Output:\n{output}")
                sys.exit(1)
        else:
            print("Skipping Test Case D: Last row is not a weekday.")

    finally:
        restore_backup()
        print("\nCleaned up all temporary files and restored original Graves history database.")

if __name__ == "__main__":
    main()
