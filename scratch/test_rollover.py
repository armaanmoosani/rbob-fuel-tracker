import datetime, calendar

DELIVERY_MONTH_CODES = {
    1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
    7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
}

def get_front_month_schwab_symbol(dt, prefix):
    today = dt.date()
    candidate_month = today.month + 1
    candidate_year  = today.year
    if candidate_month > 12:
        candidate_month = 1
        candidate_year += 1
    for _ in range(14):
        prev_month = candidate_month - 1
        prev_year  = candidate_year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        last_day = calendar.monthrange(prev_year, prev_month)[1]
        ltd = datetime.date(prev_year, prev_month, last_day)
        while ltd.weekday() >= 5:
            ltd -= datetime.timedelta(days=1)
        days_away = (ltd - today).days
        print(f"Candidate: {candidate_month}/{candidate_year}, LTD of prev month: {ltd}, days_away: {days_away}")
        if days_away > 10:
            break
        candidate_month += 1
        if candidate_month > 12:
            candidate_month = 1
            candidate_year += 1
    code = DELIVERY_MONTH_CODES[candidate_month]
    return f"/{prefix}{code}{candidate_year % 100:02d}"

print(get_front_month_schwab_symbol(datetime.datetime(2026, 5, 22), "RB"))
