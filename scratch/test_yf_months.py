import yfinance as yf
print("RBM26.NYM:", yf.Ticker("RBM26.NYM").fast_info.get('last_price'))
print("RBN26.NYM:", yf.Ticker("RBN26.NYM").fast_info.get('last_price'))
print("RBN24.NYM:", yf.Ticker("RBN24.NYM").fast_info.get('last_price')) # Just in case it's 2024? Wait, the year is 2026
