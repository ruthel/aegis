import json

with open('data/decision_journal.jsonl', 'r', encoding='utf-8') as f:
    lines = [json.loads(l) for l in f if l.strip()]

for entry in lines:
    ts = entry.get('timestamp', '')
    if '2026-07-21T21:0' in ts or '2026-07-21T21:1' in ts or '2026-07-21T21:2' in ts:
        print(entry)
