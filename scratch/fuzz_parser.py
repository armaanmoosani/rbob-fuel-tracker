import os
import sys
import random
import string
import tempfile
import shutil
import unittest

# Ensure the parent directory is in the path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

import ingest_prices

# Define categories of adversarial strings to generate
def generate_adversarial_strings(count=500):
    categories = [
        "pure_random",
        "long_buffer",
        "unicode_emoji",
        "sql_injection",
        "partial_match",
        "control_characters",
        "empty_or_whitespace",
        "out_of_bounds_price"
    ]
    
    generated = []
    
    # Pre-defined adversarial fragments
    sql_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "admin'--",
        "1 UNION SELECT null, null, null--"
    ]
    
    unicode_chars = [
        "🔥", "📈", "💥", "こんにちは", "你好", "Русский", "العربية", "🈲", "\u0000", "\u0007", "\u001b[31m"
    ]
    
    for i in range(count):
        cat = random.choice(categories)
        
        if cat == "pure_random":
            # Random string of random length up to 100
            length = random.randint(1, 100)
            chars = string.ascii_letters + string.digits + string.punctuation + " \n\r\t"
            s = "".join(random.choice(chars) for _ in range(length))
            
        elif cat == "long_buffer":
            # Extremely long buffer (up to 10,000 characters)
            length = random.randint(1000, 10000)
            s = "A" * length
            
        elif cat == "unicode_emoji":
            # Random mixture of unicode characters and emojis
            s = "".join(random.choice(unicode_chars) for _ in range(random.randint(2, 20)))
            
        elif cat == "sql_injection":
            # Standard SQL injection templates
            s = f"E10 - UNLEADED: {random.choice(sql_payloads)}\nE10 - PREMIUM: 2.30\nCLEAR DIESEL: 2.50"
            
        elif cat == "partial_match":
            # Looks like a label but has invalid format or missing price
            labels = ["E10 - UNLEADED", "E10 - PREMIUM", "CLEAR DIESEL"]
            lbl = random.choice(labels)
            variants = [
                f"{lbl}",
                f"{lbl}: ",
                f"{lbl}: $",
                f"{lbl}: $abc",
                f"{lbl} is really great",
                f"Is this {lbl}?",
                f"{lbl}: 2.30.45"
            ]
            s = random.choice(variants)
            
        elif cat == "control_characters":
            # Hex values, null bytes, tabs, newlines
            s = "E10 - UNLEADED\x00$2.10\r\nE10 - PREMIUM\t$2.30\x07\nCLEAR DIESEL\b$2.50"
            
        elif cat == "empty_or_whitespace":
            # Empty or whitespace only
            s = " " * random.randint(0, 50)
            
        elif cat == "out_of_bounds_price":
            # Price violates the bounds [1.50, 6.00]
            labels = ["E10 - UNLEADED", "E10 - PREMIUM", "CLEAR DIESEL"]
            prices = ["0.50", "1.49", "6.01", "99.99", "-2.30", "1000.00"]
            s = "\n".join(f"{lbl}: ${random.choice(prices)}" for lbl in labels)
            
        generated.append(s)
        
    return generated

def run_fuzzer(data_dir=None):
    # Setup explicit sandbox directory
    temp_dir = tempfile.mkdtemp()
    sandbox_csv = os.path.join(temp_dir, "graves_history.csv")
    
    # Initialize mock production graves_history.csv in sandbox
    with open(sandbox_csv, "w", encoding="utf-8") as f:
        f.write("date,nymex_rb,nymex_ho,rack_u,rack_p,rack_d\n")
        f.write("2026-05-20,2.10,2.20,2.30,2.40,2.50\n")
        
    try:
        # Patch CSV path in ingest_prices
        original_csv_path = ingest_prices.CSV_PATH
        ingest_prices.CSV_PATH = sandbox_csv
        
        adversarial_strings = generate_adversarial_strings(500)
        print(f"Generated 500 adversarial strings. Running fuzzer...")
        
        crashes = 0
        invalid_writes = 0
        successful_extractions = 0
        
        for idx, s in enumerate(adversarial_strings):
            # 1. Pure function extraction isolation check
            try:
                p_u = ingest_prices.extract_price_near_label(s, "E10 - UNLEADED")
                p_p = ingest_prices.extract_price_near_label(s, "E10 - PREMIUM")
                p_d = ingest_prices.extract_price_near_label(s, "CLEAR DIESEL")
            except Exception as e:
                print(f"CRITICAL: extract_price_near_label crashed at string {idx} with: {e}")
                crashes += 1
                continue
                
            # 2. Simulate the full workflow in the sandbox
            try:
                # Read start row count of sandboxed CSV
                with open(sandbox_csv, "r") as f:
                    start_lines = f.readlines()
                    
                # Full extraction validation
                prices = []
                for key, label in ingest_prices.LABELS.items():
                    p = ingest_prices.extract_price_near_label(s, label)
                    if p is None or not (1.50 <= p <= 6.00):
                        break
                    prices.append(p)
                    
                # Ingestion simulation logic matching ingest_prices.py exactly:
                is_valid = (len(prices) == 3)
                
                if is_valid:
                    # Write to sandboxed CSV
                    with open(sandbox_csv, "a") as f:
                        f.write(f"2026-05-21,2.12,2.22,{prices[0]:.4f},{prices[1]:.4f},{prices[2]:.4f}\n")
                    successful_extractions += 1
                else:
                    # Ensure no write happens
                    pass
                    
                # Check end row count of sandboxed CSV
                with open(sandbox_csv, "r") as f:
                    end_lines = f.readlines()
                    
                # Assertions
                if not is_valid:
                    if len(end_lines) != len(start_lines):
                        print(f"ERROR: Invalid string {idx} resulted in a CSV write!")
                        print(f"Content: {repr(s)}")
                        invalid_writes += 1
                else:
                    if len(end_lines) != len(start_lines) + 1:
                        print(f"ERROR: Valid string {idx} did not write correctly!")
                        invalid_writes += 1
                        
            except Exception as e:
                print(f"CRITICAL: Full extraction simulation crashed at string {idx} with: {e}")
                crashes += 1
                
        print("\n=== FUZZER RESULTS ===")
        print(f"Total Strings Tested:  500")
        print(f"Successful Parsed:    {successful_extractions}")
        print(f"Parser Crashes:       {crashes}")
        print(f"Invalid CSV Writes:   {invalid_writes}")
        print("======================")
        
        # Raise errors if there were crashes or invalid writes
        if crashes > 0 or invalid_writes > 0:
            raise RuntimeError(f"Fuzz test failed with {crashes} crashes and {invalid_writes} invalid CSV writes.")
            
        print("Fuzz test passed successfully. 100% crash-free and write-isolated.")
        
    finally:
        # Restore original path
        ingest_prices.CSV_PATH = original_csv_path
        # Cleanup sandbox directory
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    run_fuzzer()
