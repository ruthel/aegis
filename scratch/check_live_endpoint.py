import urllib.request
import json

try:
    req = urllib.request.urlopen('http://127.0.0.1:8080/api/status')
    data = json.loads(req.read().decode('utf-8'))
    print("LIVE HTTP /api/status RESPONSE:")
    print("  paper_balance:", data.get('balance', {}).get('paper_balance'))
    print("  open positions count:", len(data.get('positions', [])))
    for p in data.get('positions', []):
        print(f"  Pos: {p['symbol']} | ExitRec: {p.get('exit_recommendation')}")
except Exception as e:
    print("HTTP Request failed:", e)
