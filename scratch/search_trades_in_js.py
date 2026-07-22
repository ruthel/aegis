with open('dashboard/static/dashboard.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if 'tradesBody' in line or 'pnlNet' in line or 'pnl_net' in line or 'signedPercent' in line or '0.00' in line or 'pnlNetVal' in line:
        print(f"Line {idx+1}: {line.strip()}")
