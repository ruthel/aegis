import os
import glob
import json

for fname in glob.glob('data/*'):
    if 'tmp' in fname or 'bak' in fname:
        print("Found backup/tmp file:", fname)
        if os.path.exists(fname):
            try:
                with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if '2096.66' in content:
                        print("  -> CONTAINS 2096.66!")
            except Exception as e:
                print("  -> error reading:", e)
