import yfinance as yf
print("HON26.NYM:", not yf.Ticker("HON26.NYM").history(period="5d").empty)
print("CLN26.NYM:", not yf.Ticker("CLN26.NYM").history(period="5d").empty)
