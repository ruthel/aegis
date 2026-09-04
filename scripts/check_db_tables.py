#!/usr/bin/env python3
"""Check what tables exist in the database."""
import sqlite3

conn = sqlite3.connect('data/aegis_db.sqlite3')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables in aegis_db.sqlite3:")
for t in tables:
    print(f"  - {t}")
    cursor.execute(f"SELECT COUNT(*) FROM {t}")
    count = cursor.fetchone()[0]
    print(f"    ({count} rows)")
conn.close()
