import pdfplumber
import pandas as pd
import re
import os
from datetime import datetime

# --- CONFIG ---
PDF_DIR = "graves_pdfs"
OUTPUT_CSV = "../data/graves_history.csv"  # Write directly to the repo's actual dataset
PRICE_MIN = 1.50
PRICE_MAX = 6.00

# IMPORTANT: Replace these with the exact label text from your PDFs.
# Run the debug block below on one PDF first to see raw extracted text.
LABELS = {
    "rack_u": "E10 - UNLEADED",
    "rack_p": "E10 - PREMIUM",
    "rack_d": "CLEAR DIESEL",
}

def debug_one_pdf(filepath):
    """Run this first on a single PDF to see raw text and tune your labels."""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            print(page.extract_text())

def extract_price_near_label(text, label):
    """
    Find a dollar price on the same line as a given label.
    Handles formats: 2.1050, $2.1050, 2.105, 2.10, 3.22960
    """
    pattern = rf'{re.escape(label)}.*?\$?(\d+\.\d{{2,5}})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def validate_price(price, label):
    if price is None:
        return False, f"Could not find price for '{label}'"
    if not (PRICE_MIN <= price <= PRICE_MAX):
        return False, f"Price {price} for '{label}' is outside valid range"
    return True, None

def extract_from_pdf(filepath):
    with pdfplumber.open(filepath) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    results = {}
    for field, label in LABELS.items():
        price = extract_price_near_label(full_text, label)
        valid, err = validate_price(price, label)
        if not valid:
            raise ValueError(f"In {os.path.basename(filepath)}: {err}")
        results[field] = price

    return results

def parse_date_from_filename(filename):
    """Extract YYYY-MM-DD from the filename prefix set by the downloader."""
    match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot parse date from filename: {filename}")

def main():
    # Load existing CSV if it exists to avoid duplicates
    if os.path.exists(OUTPUT_CSV):
        existing_df = pd.read_csv(OUTPUT_CSV, parse_dates=["date"])
        existing_df["date"] = pd.to_datetime(existing_df["date"])
        existing_dates = set(existing_df["date"].dt.strftime("%Y-%m-%d"))
        print(f"Existing CSV has {len(existing_df)} rows.")
    else:
        existing_df = pd.DataFrame(columns=["date", "nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"])
        existing_dates = set()

    if not os.path.exists(PDF_DIR):
        print(f"Directory {PDF_DIR} not found. Did you run the download script?")
        return

    pdf_files = sorted([f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")])
    print(f"Found {len(pdf_files)} PDFs to process.")

    new_rows = []
    errors = []

    for filename in pdf_files:
        try:
            date_str = parse_date_from_filename(filename)

            if date_str in existing_dates:
                continue  # Already in CSV
            
            # Add to set so we don't process duplicate PDFs for the same day
            existing_dates.add(date_str)

            filepath = os.path.join(PDF_DIR, filename)
            prices = extract_from_pdf(filepath)

            new_rows.append({
                "date": date_str,
                "rack_u": prices["rack_u"],
                "rack_p":  prices["rack_p"],
                "rack_d":   prices["rack_d"],
                "nymex_rb":  None,  # Filled by next step
                "nymex_ho":  None,  # Filled by next step
            })

        except Exception as e:
            errors.append((filename, str(e)))

    print(f"\nExtracted {len(new_rows)} new rows. Errors: {len(errors)}")

    if errors:
        print("\n--- ERRORS (review these PDFs manually) ---")
        for fname, err in errors:
            print(f"  {fname}: {err}")

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # Keep schema matching exactly
        new_df = new_df[["date", "nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"]]
        
        if not existing_df.empty:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined = new_df
            
        combined.sort_values("date", inplace=True)
        os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
        combined.to_csv(OUTPUT_CSV, index=False)
        print(f"\nCSV saved to {OUTPUT_CSV}: {len(combined)} total rows.")

if __name__ == "__main__":
    # STEP 0: Uncomment this and run on ONE pdf first to see raw text
    # debug_one_pdf("graves_pdfs/2024-11-15_somefile.pdf")

    main()
