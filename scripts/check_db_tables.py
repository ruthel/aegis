#!/usr/bin/env python3
"""Inspect SQLite tables used by Aegis."""
import argparse
import os
import sqlite3

from dotenv import load_dotenv


def main():
    load_dotenv(".env", override=True)
    parser = argparse.ArgumentParser(description="Liste les tables SQLite Aegis et leur nombre de lignes.")
    parser.add_argument(
        "--db",
        default=os.getenv("ML_LIVE_SQLITE_FILE", "data/aegis_db.sqlite3"),
        help="Chemin de la base SQLite Aegis.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"Base introuvable: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables in {args.db}:")
        for table in tables:
            # table names come from sqlite_master, not user input.
            cursor.execute(f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34) * 2)}"')
            count = cursor.fetchone()[0]
            print(f"  - {table}: {count} rows")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
