import json
import glob

for fname in glob.glob('data/*'):
    if 'state' in fname or 'json' in fname:
        try:
            with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if '2096.66' in content:
                    print("Found 2096.66 in:", fname)
        except Exception:
            pass
