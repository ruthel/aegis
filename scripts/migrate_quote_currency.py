#!/usr/bin/env python3
"""Idempotent database migration for Aegis quote-currency support.

This migration is intentionally conservative:
- legacy bot_state rows are tagged as USD;
- switching AEGIS_QUOTE_CURRENCY never relabels historical USD transactions as CAD/EUR/etc.;
- per-quote bot state is archived and restored when switching back;
- accounting accounts remain separated by their account_id suffix (mode:exchange:QUOTE);
- the migration is safe to run at every server/bot startup.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIGRATION_ID = "quote_currency_state_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    raw = os.getenv("ML_LIVE_SQLITE_FILE", "data/aegis_db.sqlite3")
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _backup_once(db_path: Path) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size <= 0:
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.pre_{MIGRATION_ID}{db_path.suffix}"
    if backup_path.exists():
        return backup_path
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    return backup_path


def _migration_already_applied(db_path: Path) -> bool:
    if not db_path.exists() or db_path.stat().st_size <= 0:
        return False
    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return False
        return bool(
            conn.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_id=?",
                (MIGRATION_ID,),
            ).fetchone()
        )
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate_quote_currency_database(db_path: str | os.PathLike[str] | None = None) -> dict:
    load_dotenv(ROOT / ".env", override=True)

    from utils.currency import get_quote_currency

    quote = get_quote_currency()
    exchange = str(os.getenv("EXCHANGE", "kraken") or "kraken").strip().lower()
    resolved = Path(db_path) if db_path else _db_path()
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # Backup BEFORE any logger/schema initializer can mutate the database.
    # Only one backup is kept for this structural migration version.
    pre_applied = _migration_already_applied(resolved)
    backup_path = None if pre_applied else _backup_once(resolved)

    # Run the normal schema initializer after the safety backup so every
    # historical Aegis schema reaches the current baseline.
    from core.ml_live_logger import MLLiveLogger

    logger = MLLiveLogger(data_dir=str(resolved.parent), sqlite_file=str(resolved))
    logger.close()

    conn = sqlite3.connect(str(resolved), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                details TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state_quote_archive (
                mode TEXT NOT NULL,
                quote_currency TEXT NOT NULL,
                paper_balance REAL,
                initial_balance REAL,
                created_at TEXT,
                updated_at TEXT,
                archived_at TEXT NOT NULL,
                PRIMARY KEY (mode, quote_currency)
            )
            """
        )

        columns = _table_columns(conn, "bot_state")
        if columns and "quote_currency" not in columns:
            conn.execute("ALTER TABLE bot_state ADD COLUMN quote_currency TEXT")
            columns.add("quote_currency")
        if columns:
            conn.execute(
                """
                UPDATE bot_state
                SET quote_currency='USD'
                WHERE quote_currency IS NULL OR TRIM(quote_currency)=''
                """
            )

        structural_done = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if not structural_done:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_migrations
                (migration_id, applied_at, details)
                VALUES (?, ?, ?)
                """,
                (
                    MIGRATION_ID,
                    _utc_now(),
                    "Adds bot_state quote tracking and per-quote state archive; historical money is never FX-converted.",
                ),
            )
            conn.commit()

        switched_modes: list[str] = []
        restored_modes: list[str] = []
        seeded_modes: list[str] = []

        # CREATE/UPDATE statements above may have opened an implicit sqlite3
        # transaction (especially on subsequent idempotent runs). Close it before
        # taking the explicit write lock for quote-state switching.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT mode, quote_currency, paper_balance, initial_balance, created_at, updated_at
            FROM bot_state
            WHERE mode IN ('paper', 'live')
            """
        ).fetchall()

        by_mode = {str(row[0]): row for row in rows}
        now = _utc_now()
        paper_seed = float(os.getenv("PAPER_BALANCE", "1000") or 1000)

        for mode in ("paper", "live"):
            row = by_mode.get(mode)
            if row is None:
                if mode == "paper":
                    conn.execute(
                        """
                        INSERT INTO bot_state
                        (mode, quote_currency, paper_balance, initial_balance, updated_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (mode, quote, paper_seed, paper_seed, now, now),
                    )
                    seeded_modes.append(mode)
                continue

            current_quote = str(row[1] or "USD").upper()
            if current_quote == quote:
                continue

            # Preserve the old quote state exactly as-is.
            conn.execute(
                """
                INSERT INTO bot_state_quote_archive
                (mode, quote_currency, paper_balance, initial_balance, created_at, updated_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mode, quote_currency) DO UPDATE SET
                    paper_balance=excluded.paper_balance,
                    initial_balance=excluded.initial_balance,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    archived_at=excluded.archived_at
                """,
                (mode, current_quote, row[2], row[3], row[4], row[5], now),
            )

            target = conn.execute(
                """
                SELECT paper_balance, initial_balance, created_at, updated_at
                FROM bot_state_quote_archive
                WHERE mode=? AND quote_currency=?
                """,
                (mode, quote),
            ).fetchone()

            if target:
                paper_balance, initial_balance, created_at, _updated_at = target
                restored_modes.append(mode)
            elif mode == "paper":
                paper_balance = paper_seed
                initial_balance = paper_seed
                created_at = now
                seeded_modes.append(mode)
            else:
                # Live cash comes from the exchange. Never transplant the numeric
                # value from another quote currency.
                paper_balance = None
                initial_balance = None
                created_at = now
                seeded_modes.append(mode)

            conn.execute(
                """
                UPDATE bot_state
                SET quote_currency=?,
                    paper_balance=?,
                    initial_balance=?,
                    created_at=?,
                    updated_at=?
                WHERE mode=?
                """,
                (quote, paper_balance, initial_balance, created_at, now, mode),
            )
            switched_modes.append(mode)

        # Legacy/null account metadata can be repaired without changing money.
        account_columns = _table_columns(conn, "accounts")
        if account_columns:
            account_rows = conn.execute(
                "SELECT account_id, base_currency FROM accounts"
            ).fetchall()
            for account_id, base_currency in account_rows:
                account_text = str(account_id or "")
                parts = account_text.split(":")
                account_quote = parts[-1].upper() if len(parts) >= 3 else None
                if account_quote and (base_currency is None or not str(base_currency).strip()):
                    conn.execute(
                        "UPDATE accounts SET base_currency=? WHERE account_id=?",
                        (account_quote, account_id),
                    )

        # Ensure the currently active paper account exists. Old quote accounts are
        # deliberately retained as historical accounting partitions.
        paper_state = conn.execute(
            """
            SELECT paper_balance, initial_balance
            FROM bot_state
            WHERE mode='paper'
            """
        ).fetchone()
        if paper_state:
            account_id = f"paper:{exchange}:{quote}"
            conn.execute(
                """
                INSERT INTO accounts
                (account_id, mode, exchange, base_currency, name, status,
                 initial_balance, created_at, updated_at)
                VALUES (?, 'paper', ?, ?, 'paper account', 'active', ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    base_currency=excluded.base_currency,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    exchange,
                    quote,
                    paper_state[1] if paper_state[1] is not None else paper_state[0],
                    now,
                    now,
                ),
            )

        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_status = str(integrity[0] if integrity else "unknown")
        if integrity_status.lower() != "ok":
            conn.rollback()
            raise RuntimeError(f"SQLite integrity_check failed: {integrity_status}")

        conn.commit()
        return {
            "ok": True,
            "database": str(resolved),
            "quote_currency": quote,
            "migration_id": MIGRATION_ID,
            "backup": str(backup_path) if backup_path else None,
            "switched_modes": switched_modes,
            "restored_modes": restored_modes,
            "seeded_modes": seeded_modes,
            "integrity": integrity_status,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    try:
        result = migrate_quote_currency_database()
        changed = bool(
            result["switched_modes"]
            or result["restored_modes"]
            or result["seeded_modes"]
            or result["backup"]
        )
        status = "migration appliquée" if changed else "déjà à jour"
        print(
            f"✅ DB quote-currency: {status} | "
            f"quote={result['quote_currency']} | integrity={result['integrity']}"
        )
        if result.get("backup"):
            print(f"   Backup de sécurité: {result['backup']}")
        return 0
    except Exception as exc:
        print(f"❌ DB quote-currency migration failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
