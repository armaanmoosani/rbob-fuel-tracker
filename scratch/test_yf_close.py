import yfinance as yf
print("RB=F close:", yf.Ticker("RB=F").fast_info.get('previous_close'))
print("RBM26.NYM close:", yf.Ticker("RBM26.NYM").fast_info.get('previous_close'))
print("RBN26.NYM close:", yf.Ticker("RBN26.NYM").fast_info.get('previous_close'))
