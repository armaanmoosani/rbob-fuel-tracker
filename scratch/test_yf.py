import yfinance as yf
yf_t = yf.Ticker('RB=F')
print("RB=F:", yf_t.fast_info['last_price'])
print("RB=F daily%:", (yf_t.fast_info['last_price'] - yf_t.fast_info['previous_close']) / yf_t.fast_info['previous_close'] * 100)
