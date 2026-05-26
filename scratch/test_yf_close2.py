import yfinance as yf
print("RB=F:", yf.Ticker("RB=F").history(period="5d")['Close'].iloc[-2])
print("RBM26.NYM:", yf.Ticker("RBM26.NYM").history(period="5d")['Close'].iloc[-2])
print("RBN26.NYM:", yf.Ticker("RBN26.NYM").history(period="5d")['Close'].iloc[-2])
