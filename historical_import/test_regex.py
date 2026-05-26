import re

LABELS = {
    "rack_u": "E10 - UNLEADED",
    "rack_p": "E10 - PREMIUM",
    "rack_d": "CLEAR DIESEL",
}

def extract_price_near_label(text, label):
    pattern = rf'{re.escape(label)}.*?\$?(\d+\.\d{{2,5}})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

pdf_text = """
Item ID	Description	Unit Price	Tax	Total
11	E10 - UNLEADED	3.22960	0.46158	3.69118
4	CLEAR DIESEL	3.96740	0.53220	4.49960
13	E10 - PREMIUM	4.04980	0.46185	4.51165
"""

print("=== EXTRACTION TEST ===")
for key, label in LABELS.items():
    price = extract_price_near_label(pdf_text, label)
    print(f"Searching for '{label}': Extracted Unit Price -> {price}")
