import pandas as pd
import yfinance as yf
import os

CSV_PATH = "../data/graves_history.csv"

def main():
    if not os.path.exists(CSV_PATH):
        print(f"File not found: {CSV_PATH}. Did you run the extraction script?")
        return

    df = pd.read_csv(CSV_PATH, parse_dates=["date"])

    if df.empty:
        print("CSV is empty.")
        return

    start = df["date"].min().strftime("%Y-%m-%d")
    end   = (df["date"].max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d") # Extend end to grab the final day properly

    print(f"Fetching NYMEX history from {start} to {end}...")

    rbob_df = yf.download("RB=F", start=start, end=end, auto_adjust=True)
    ho_df = yf.download("HO=F", start=start, end=end, auto_adjust=True)
    
    # Safely extract the 1D Series regardless of multi-index changes in newer yfinance versions
    rbob = rbob_df["Close"].iloc[:, 0] if isinstance(rbob_df["Close"], pd.DataFrame) else rbob_df["Close"]
    ho = ho_df["Close"].iloc[:, 0] if isinstance(ho_df["Close"], pd.DataFrame) else ho_df["Close"]
    
    rbob.name = "nymex_rb"
    ho.name = "nymex_ho"

    settlements = pd.DataFrame({"nymex_rb": rbob, "nymex_ho": ho})
    settlements.index = pd.to_datetime(settlements.index).normalize()
    settlements.index.name = "date"

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.set_index("date")

    # Only fill rows that are empty (e.g. from the PDF extraction)
    mask_rb = df["nymex_rb"].isna()
    mask_ho = df["nymex_ho"].isna()
    
    df.loc[mask_rb, "nymex_rb"] = settlements["nymex_rb"]
    df.loc[mask_ho, "nymex_ho"] = settlements["nymex_ho"]

    df.reset_index(inplace=True)
    
    # Ensure correct column order before saving
    df = df[["date", "nymex_rb", "nymex_ho", "rack_u", "rack_p", "rack_d"]]
    
    # Convert dates back to YYYY-MM-DD string format
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    df.to_csv(CSV_PATH, index=False)

    filled = df["nymex_rb"].notna().sum()
    missing = df["nymex_rb"].isna().sum()
    print(f"Done. Filled: {filled} rows | Still missing: {missing} rows")
    if missing > 0:
        print("Missing rows (likely market holidays or gaps in yfinance data):")
        print(df[df["nymex_rb"].isna()][["date"]])

if __name__ == "__main__":
    main()
