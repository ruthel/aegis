import ast
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, text, update

from core.db_orm import (
    Base,
    BotAppState,
    BotCommand,
    BotDecisionJournal,
    BotDecisionMetric,
    BotDailyStat,
    BotExitRecommendation,
    BotLiveStatus,
    BotLiveStatusSubscription,
    BotLiveStatusSymbol,
    BotMarketContext,
    BotPosition,
    BotProcess,
    BotState,
    BotSymbolCooldown,
    BotTrailingStop,
    CryptoScoreHistory,
    MlFeatureImportance,
    MlEntryDecision,
    MlEntryFeatureValue,
    MlExitDecision,
    MlExitFeatureValue,
    MlOpenEntry,
    MlLivePrediction,
    MlModelMetadata,
    MlRawEvent,
    MlTradeOutcome,
    SupportTouchResult,
    TelegramMessage,
    create_session_factory,
    now_iso,
)


class MLLiveLogger:
    """SQLite journal for live ML decisions and trade outcomes."""

    def __init__(self, data_dir='data', open_file=None, sqlite_file=None):
        self.data_dir = data_dir
        self.sqlite_file = sqlite_file or os.path.join(data_dir, 'aegis_db.sqlite3')
        self._lock = threading.Lock()
        self._conn = None
        self._Session = create_session_factory(self.sqlite_file)
        os.makedirs(self.data_dir, exist_ok=True)
        self._init_sqlite()

    def record_entry_decision(
        self,
        symbol,
        decision,
        price,
        p_win,
        min_p_win,
        p_continue=None,
        min_p_continue=None,
        features=None,
        feature_names=None,
        bot_context=None,
        trade_context=None,
        exit_forecast=None,
        reason=None,
        mode='paper',
    ):
        decision_id = self._new_id('entry')
        event = {
            'event_id': decision_id,
            'event_type': 'entry_decision',
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'symbol': symbol,
            'decision': decision,
            'reason': reason,
            'price': self._clean(price),
            'p_win': self._clean(p_win),
            'min_p_win': self._clean(min_p_win),
            'p_continue': self._clean(p_continue),
            'min_p_continue': self._clean(min_p_continue),
            'features': self._features_to_dict(feature_names, features),
            'bot_context': self._clean(bot_context or {}),
            'trade_context': self._clean(trade_context or {}),
            'exit_forecast': self._clean(exit_forecast or {}),
            'label_status': 'pending' if decision == 'accepted' else 'candidate_rejected_pending_replay',
        }
        self.append_event(event)
        return decision_id

    def mark_entry_opened(self, symbol, entry_id, order=None, price=None, amount=None):
        if not entry_id:
            return
        self.append_event({
            'event_id': self._new_id('entry_opened'),
            'event_type': 'entry_opened',
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'entry_id': entry_id,
            'order_id': (order or {}).get('id') if isinstance(order, dict) else None,
            'price': self._clean(price),
            'amount': self._clean(amount),
        })

    def record_exit_decision(
        self,
        symbol,
        decision,
        current_price,
        features=None,
        feature_names=None,
        entry_p_win=None,
        continuation_score=None,
        p_continue=None,
        net_pnl_pct=None,
        duration_minutes=None,
        reason=None,
        mode='paper',
    ):
        open_entry = self.load_open_entries().get(symbol, {})
        event = {
            'event_id': self._new_id('exit_decision'),
            'event_type': 'exit_decision',
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'symbol': symbol,
            'entry_id': open_entry.get('entry_id'),
            'decision': decision,
            'reason': reason,
            'current_price': self._clean(current_price),
            'entry_p_win': self._clean(entry_p_win),
            'continuation_score': self._clean(continuation_score),
            'p_continue': self._clean(p_continue),
            'net_pnl_pct': self._clean(net_pnl_pct),
            'duration_minutes': self._clean(duration_minutes),
            'features': self._features_to_dict(feature_names, features),
        }
        self.append_event(event)
        return event['event_id']

    def record_exit_outcome(
        self,
        symbol,
        sell_price,
        amount,
        buy_price=None,
        pnl=None,
        pnl_pct=None,
        hold_time=None,
        reason=None,
        order=None,
        mode='paper',
    ):
        open_entries = self.load_open_entries()
        open_entry = open_entries.pop(symbol, None)

        event = {
            'event_id': self._new_id('exit'),
            'event_type': 'exit_outcome',
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'symbol': symbol,
            'entry_id': (open_entry or {}).get('entry_id'),
            'sell_price': self._clean(sell_price),
            'buy_price': self._clean(buy_price),
            'amount': self._clean(amount),
            'pnl': self._clean(pnl),
            'pnl_pct': self._clean(pnl_pct),
            'hold_time': hold_time,
            'reason': reason,
            'order_id': (order or {}).get('id') if isinstance(order, dict) else None,
            'label_status': 'closed' if open_entry else 'closed_without_entry_link',
        }
        self.append_event(event)
        return event

    def append_event(self, event):
        try:
            clean_event = self._clean(event)
            with self._lock:
                self._insert_sqlite_event(clean_event)
        except Exception:
            pass

    def _init_sqlite(self):
        try:
            os.makedirs(os.path.dirname(self.sqlite_file) or '.', exist_ok=True)
            with self._lock:
                conn = self._get_conn()
                conn.execute('PRAGMA busy_timeout=30000')
                try:
                    conn.execute('PRAGMA journal_mode=WAL')
                except sqlite3.OperationalError:
                    pass
                conn.execute('PRAGMA synchronous=NORMAL')
                self._migrate_table_name(conn, 'ml_events', 'ml_raw_events')
                self._migrate_table_name(conn, 'app_state', 'bot_app_state')
                self._migrate_table_name(conn, 'paper_bot_state', 'bot_state')
                self._migrate_column_name(conn, 'ml_raw_events', 'payload_json', 'payload_data')
                self._migrate_column_name(conn, 'ml_entry_decisions', 'features_json', 'features_data')
                self._migrate_column_name(conn, 'ml_entry_decisions', 'bot_context_json', 'bot_context_data')
                self._migrate_column_name(conn, 'ml_entry_decisions', 'trade_context_json', 'trade_context_data')
                self._migrate_column_name(conn, 'ml_entry_decisions', 'exit_forecast_json', 'exit_forecast_data')
                self._migrate_column_name(conn, 'ml_exit_decisions', 'features_json', 'features_data')
                self._migrate_column_name(conn, 'support_touch_backtests', 'settings_json', 'settings_data')
                self._migrate_column_name(conn, 'support_touch_backtests', 'payload_json', 'payload_data')
                self._migrate_column_name(conn, 'support_touch_pair_results', 'result_json', 'result_data')
                self._migrate_column_name(conn, 'ml_model_metadata', 'metadata_json', 'metadata_data')
                self._drop_column(conn, 'support_touch_backtests', 'source_file')
                self._migrate_support_touch_results(conn)
                self._migrate_bot_state_rows(conn)
                self._migrate_bot_state_columns(conn)
                self._migrate_bot_process_to_bot_state(conn)
                self._ensure_column(conn, 'bot_market_context', 'symbol_regime', 'TEXT')
                self._ensure_column(conn, 'bot_market_context', 'context_mode', 'TEXT')
                self._ensure_column(conn, 'bot_market_context', 'btc_regime', 'TEXT')
                self._ensure_column(conn, 'bot_market_context', 'bear_mode', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'symbol_bear', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'btc_bear', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'trade_multiplier', 'REAL')
                self._ensure_column(conn, 'bot_market_context', 'btc_momentum_percent', 'REAL')
                self._ensure_column(conn, 'bot_market_context', 'symbol_momentum_percent', 'REAL')
                self._ensure_column(conn, 'bot_market_context', 'confidence_bonus', 'REAL')
                self._ensure_column(conn, 'bot_market_context', 'reversal_confirmed', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'falling_knife_active', 'INTEGER')
                self._ensure_column(conn, 'ml_live_predictions', 'p_continue', 'REAL')
                self._ensure_column(conn, 'ml_live_predictions', 'min_p_continue', 'REAL')
                self._ensure_column(conn, 'ml_live_predictions', 'exit_decision', 'TEXT')
                self._ensure_column(conn, 'ml_live_predictions', 'exit_reason', 'TEXT')
                self._ensure_column(conn, 'ml_live_predictions', 'entry_price', 'REAL')
                conn.execute('DROP TABLE IF EXISTS support_touch_trade_results')
                Base.metadata.create_all(self._Session.kw['bind'])
                self._migrate_app_state_to_bot_state(conn)
                self._migrate_runtime_rows_out_of_bot_state(conn)
                self._compact_bot_state_schema(conn)
                self._migrate_live_status_schema(conn)
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_bot_live_status_symbols_symbol
                    ON bot_live_status_symbols (symbol)
                    """
                )
                self._migrate_runtime_payload_schema(conn)
                self._migrate_ml_payload_schema(conn)
                self._migrate_bot_state_tables(conn)
                conn.execute('DROP TABLE IF EXISTS bot_state_sections')
                self._ensure_audit_columns(conn)
                conn.commit()
        except Exception as exc:
            print(f"⚠️ SQLite init failed: {type(exc).__name__}: {exc}")

    def _orm_session(self):
        return self._Session()

    def _quote_ident(self, name):
        return '"' + str(name).replace('"', '""') + '"'

    def _migrate_table_name(self, conn, old_name, new_name):
        try:
            old_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (old_name,)
            ).fetchone()
            new_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (new_name,)
            ).fetchone()
            if old_exists and not new_exists:
                conn.execute(f'ALTER TABLE {old_name} RENAME TO {new_name}')
        except Exception:
            pass

    def _migrate_column_name(self, conn, table_name, old_name, new_name):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')]
            if old_name in columns and new_name not in columns:
                conn.execute(f'ALTER TABLE {table_name} RENAME COLUMN {old_name} TO {new_name}')
        except Exception:
            pass

    def _drop_column(self, conn, table_name, column_name):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')]
            if column_name in columns:
                conn.execute(f'ALTER TABLE {table_name} DROP COLUMN {column_name}')
        except Exception:
            pass

    def _ensure_column(self, conn, table_name, column_name, column_type):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')]
            if column_name not in columns:
                conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')
        except Exception:
            pass

    def _ensure_audit_columns(self, conn):
        try:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                self._ensure_column(conn, table, 'created_at', 'TEXT')
                self._ensure_column(conn, table, 'updated_at', 'TEXT')
                q_table = self._quote_ident(table)
                columns = [row[1] for row in conn.execute(f'PRAGMA table_info({q_table})')]
                created_source = 'CURRENT_TIMESTAMP'
                for candidate in ('timestamp', 'generated_at', 'stored_at', 'opened_at', 'trained_at', 'prediction_ts', 'started_at'):
                    if candidate in columns:
                        created_source = f'COALESCE({self._quote_ident(candidate)}, CURRENT_TIMESTAMP)'
                        break
                conn.execute(
                    f"""
                    UPDATE {q_table}
                    SET
                        created_at = COALESCE(created_at, {created_source}),
                        updated_at = COALESCE(updated_at, created_at, {created_source}, CURRENT_TIMESTAMP)
                    WHERE created_at IS NULL OR updated_at IS NULL
                    """
                )

                pk_cols = [
                    row[1]
                    for row in conn.execute(f'PRAGMA table_info({q_table})')
                    if row[5] > 0
                ]
                if not pk_cols:
                    continue
                trigger_suffix = ''.join(ch if ch.isalnum() else '_' for ch in table)
                where_clause = ' AND '.join(
                    f'{self._quote_ident(col)} IS NEW.{self._quote_ident(col)}'
                    for col in pk_cols
                )
                conn.execute(f'DROP TRIGGER IF EXISTS {self._quote_ident("trg_" + trigger_suffix + "_audit_insert")}')
                conn.execute(f'DROP TRIGGER IF EXISTS {self._quote_ident("trg_" + trigger_suffix + "_audit_update")}')
                conn.execute(
                    f"""
                    CREATE TRIGGER {self._quote_ident("trg_" + trigger_suffix + "_audit_insert")}
                    AFTER INSERT ON {q_table}
                    FOR EACH ROW
                    WHEN NEW.created_at IS NULL OR NEW.updated_at IS NULL
                    BEGIN
                        UPDATE {q_table}
                        SET
                            created_at = COALESCE(NEW.created_at, {created_source}),
                            updated_at = COALESCE(NEW.updated_at, NEW.created_at, {created_source}, CURRENT_TIMESTAMP)
                        WHERE {where_clause};
                    END
                    """
                )
                conn.execute(
                    f"""
                    CREATE TRIGGER {self._quote_ident("trg_" + trigger_suffix + "_audit_update")}
                    AFTER UPDATE ON {q_table}
                    FOR EACH ROW
                    WHEN NEW.updated_at IS OLD.updated_at
                    BEGIN
                        UPDATE {q_table}
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE {where_clause};
                    END
                    """
                )
        except Exception:
            pass

    def _migrate_bot_state_rows(self, conn):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_state'"
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_state)')]
            if 'state_data' not in columns:
                return

            rows = conn.execute("SELECT key, state_data, updated_at FROM bot_state").fetchall()
            conn.execute('ALTER TABLE bot_state RENAME TO bot_state_legacy')
            conn.execute(
                """
                CREATE TABLE bot_state (
                    mode TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_data TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (mode, state_key)
                )
                """
            )
            for mode, state_data, updated_at in rows:
                try:
                    state = json.loads(state_data)
                except Exception:
                    state = {}
                if not isinstance(state, dict):
                    state = {}
                for state_key, value in state.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_state
                        (mode, state_key, value_data, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (mode, state_key, json.dumps(value, ensure_ascii=False), updated_at)
                    )
            conn.execute('DROP TABLE IF EXISTS bot_state_legacy')
        except Exception:
            pass

    def _migrate_bot_state_columns(self, conn):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_state'"
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_state)')]
            if 'state_key' not in columns or 'value_data' not in columns:
                return

            rows = conn.execute(
                "SELECT mode, state_key, value_data, created_at, updated_at FROM bot_state"
            ).fetchall()
            grouped = {}
            for mode, state_key, value_data, created_at, updated_at in rows:
                item = grouped.setdefault(mode, {'created_at': created_at, 'updated_at': updated_at})
                item[str(state_key)] = value_data
                item['created_at'] = item.get('created_at') or created_at
                item['updated_at'] = updated_at or item.get('updated_at')

            conn.execute('ALTER TABLE bot_state RENAME TO bot_state_key_value_legacy')
            conn.execute(
                """
                CREATE TABLE bot_state (
                    mode TEXT PRIMARY KEY,
                    paper_balance REAL,
                    initial_balance REAL,
                    updated_at TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )
            for mode, item in grouped.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_state
                    (mode, paper_balance, initial_balance, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        mode,
                        self._clean(json.loads(item['paper_balance'])) if item.get('paper_balance') is not None else None,
                        self._clean(json.loads(item['initial_balance'])) if item.get('initial_balance') is not None else None,
                        item.get('created_at') or datetime.now().isoformat(),
                        item.get('updated_at') or datetime.now().isoformat(),
                    )
                )
            conn.execute('DROP TABLE IF EXISTS bot_state_key_value_legacy')
        except Exception:
            pass

    def _migrate_app_state_to_bot_state(self, conn):
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_app_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_app_state'"
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_app_state)')]
            if 'key' not in columns or 'value' not in columns:
                return
            rows = conn.execute("SELECT key, value, updated_at FROM bot_app_state").fetchall()
            for key, value, updated_at in rows:
                conn.execute(
                    """
                    INSERT INTO bot_app_state
                    (state_key, state_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        state_value = excluded.state_value,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), str(value), updated_at, updated_at)
                )
        except Exception:
            pass

    def _migrate_bot_process_to_bot_state(self, conn):
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_processes (
                    process_key TEXT PRIMARY KEY,
                    pid INTEGER,
                    started_at TEXT,
                    command TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_process_state'"
            ).fetchone()
            if not table_exists:
                return
            rows = conn.execute(
                "SELECT key, pid, started_at, command, created_at, updated_at FROM bot_process_state"
            ).fetchall()
            for key, pid, started_at, command, created_at, updated_at in rows:
                conn.execute(
                    """
                    INSERT INTO bot_processes
                    (process_key, pid, started_at, command, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(process_key) DO UPDATE SET
                        pid = excluded.pid,
                        started_at = excluded.started_at,
                        command = excluded.command,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        pid,
                        started_at,
                        command,
                        created_at or datetime.now().isoformat(),
                        updated_at or datetime.now().isoformat(),
                    )
                )
            conn.execute('DROP TABLE IF EXISTS bot_process_state')
        except Exception:
            pass

    def _migrate_runtime_rows_out_of_bot_state(self, conn):
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_app_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_processes (
                    process_key TEXT PRIMARY KEY,
                    pid INTEGER,
                    started_at TEXT,
                    command TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_state)')]
            if 'telegram_last_status_time' in columns:
                for value, created_at, updated_at in conn.execute(
                    """
                    SELECT telegram_last_status_time, created_at, updated_at
                    FROM bot_state
                    WHERE mode = 'app' AND telegram_last_status_time IS NOT NULL
                    """
                ).fetchall():
                    conn.execute(
                        """
                        INSERT INTO bot_app_state
                        (state_key, state_value, created_at, updated_at)
                        VALUES ('telegram_last_status_time', ?, ?, ?)
                        ON CONFLICT(state_key) DO UPDATE SET
                            state_value = excluded.state_value,
                            updated_at = excluded.updated_at
                        """,
                        (str(value), created_at or datetime.now().isoformat(), updated_at or datetime.now().isoformat())
                    )
            if {'process_pid', 'process_started_at', 'process_command'}.issubset(set(columns)):
                for mode, pid, started_at, command, created_at, updated_at in conn.execute(
                    """
                    SELECT mode, process_pid, process_started_at, process_command, created_at, updated_at
                    FROM bot_state
                    WHERE mode = 'process' OR mode LIKE 'process_%'
                    """
                ).fetchall():
                    process_key = 'dashboard_bot' if mode == 'process' else str(mode).replace('process_', '', 1)
                    conn.execute(
                        """
                        INSERT INTO bot_processes
                        (process_key, pid, started_at, command, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(process_key) DO UPDATE SET
                            pid = excluded.pid,
                            started_at = excluded.started_at,
                            command = excluded.command,
                            updated_at = excluded.updated_at
                        """,
                        (
                            process_key,
                            pid,
                            started_at,
                            command,
                            created_at or datetime.now().isoformat(),
                            updated_at or datetime.now().isoformat(),
                        )
                    )
            conn.execute("DELETE FROM bot_state WHERE mode = 'app' OR mode = 'process' OR mode LIKE 'process_%'")
        except Exception:
            pass

    def _compact_bot_state_schema(self, conn):
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_state'"
            ).fetchone()
            if not table_exists:
                return
            columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_state)')]
            expected = ['mode', 'paper_balance', 'initial_balance', 'updated_at', 'created_at']
            if columns == expected:
                return
            old_name = f"bot_state_sparse_legacy_{int(time.time() * 1000)}"
            conn.execute(f'ALTER TABLE bot_state RENAME TO {old_name}')
            conn.execute(
                """
                CREATE TABLE bot_state (
                    mode TEXT PRIMARY KEY,
                    paper_balance REAL,
                    initial_balance REAL,
                    updated_at TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )
            select_columns = {
                'paper_balance': 'paper_balance' if 'paper_balance' in columns else 'NULL',
                'initial_balance': 'initial_balance' if 'initial_balance' in columns else 'NULL',
                'updated_at': 'updated_at' if 'updated_at' in columns else "datetime('now')",
                'created_at': 'created_at' if 'created_at' in columns else "datetime('now')",
            }
            conn.execute(
                f"""
                INSERT OR REPLACE INTO bot_state
                (mode, paper_balance, initial_balance, updated_at, created_at)
                SELECT mode,
                       {select_columns['paper_balance']},
                       {select_columns['initial_balance']},
                       COALESCE({select_columns['updated_at']}, datetime('now')),
                       {select_columns['created_at']}
                FROM {old_name}
                WHERE mode IN ('paper', 'live')
                """
            )
            conn.execute(f'DROP TABLE {old_name}')
        except Exception:
            pass

    def _migrate_live_status_schema(self, conn):
        try:
            def table_columns(table):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                ).fetchone()
                if not exists:
                    return None
                return [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]

            def column_expr(columns, name, default='NULL'):
                return name if columns and name in columns else default

            status_columns = table_columns('bot_live_status')
            symbol_columns = table_columns('bot_live_status_symbols')
            subscription_columns = table_columns('bot_live_status_subscriptions')
            required_status = {
                'key', 'timestamp', 'exchange', 'connected', 'running', 'mode_name',
                'reconnect_attempts', 'queue_size', 'queue_maxsize', 'worker_alive',
                'ws_thread_alive', 'created_at', 'updated_at'
            }
            required_symbol = {
                'status_key', 'symbol', 'price', 'tick_count', 'kline_count',
                'analysis_trigger_countdown', 'price_change_since_analysis_percent',
                'last_tick', 'last_tick_age_seconds', 'last_analysis',
                'last_analysis_age_seconds', 'bid', 'ask', 'spread', 'spread_percent',
                'volume_24h', 'candle_timestamp', 'candle_open', 'candle_high',
                'candle_low', 'candle_volume', 'source', 'created_at', 'updated_at'
            }
            required_subscription = {'status_key', 'symbol', 'created_at', 'updated_at'}
            needs_migration = (
                (status_columns is not None and (
                    'status_data' in status_columns or not required_status.issubset(set(status_columns))
                ))
                or (symbol_columns is not None and (
                    'symbol_data' in symbol_columns or not required_symbol.issubset(set(symbol_columns))
                ))
                or (subscription_columns is not None and not required_subscription.issubset(set(subscription_columns)))
            )
            if not needs_migration:
                return

            status_rows = []
            symbol_rows = []
            if status_columns:
                status_rows = conn.execute(
                    f"""
                    SELECT {column_expr(status_columns, 'key')},
                           {column_expr(status_columns, 'timestamp')},
                           {column_expr(status_columns, 'exchange')},
                           {column_expr(status_columns, 'connected')},
                           {column_expr(status_columns, 'running')},
                           {column_expr(status_columns, 'mode_name')},
                           {column_expr(status_columns, 'reconnect_attempts')},
                           {column_expr(status_columns, 'queue_size')},
                           {column_expr(status_columns, 'queue_maxsize')},
                           {column_expr(status_columns, 'worker_alive')},
                           {column_expr(status_columns, 'ws_thread_alive')},
                           {column_expr(status_columns, 'status_data')},
                           {column_expr(status_columns, 'created_at', "datetime('now')")},
                           {column_expr(status_columns, 'updated_at', "datetime('now')")}
                    FROM bot_live_status
                    """
                ).fetchall()

            if symbol_columns:
                symbol_rows = conn.execute(
                    f"""
                    SELECT {column_expr(symbol_columns, 'status_key')},
                           {column_expr(symbol_columns, 'symbol')},
                           {column_expr(symbol_columns, 'price')},
                           {column_expr(symbol_columns, 'tick_count')},
                           {column_expr(symbol_columns, 'kline_count')},
                           {column_expr(symbol_columns, 'last_tick')},
                           {column_expr(symbol_columns, 'last_analysis')},
                           {column_expr(symbol_columns, 'symbol_data')},
                           {column_expr(symbol_columns, 'created_at', "datetime('now')")},
                           {column_expr(symbol_columns, 'updated_at', "datetime('now')")}
                    FROM bot_live_status_symbols
                    """
                ).fetchall()

            conn.execute('DROP TABLE IF EXISTS bot_live_status')
            conn.execute('DROP TABLE IF EXISTS bot_live_status_symbols')
            conn.execute('DROP TABLE IF EXISTS bot_live_status_subscriptions')
            conn.execute(
                """
                CREATE TABLE bot_live_status (
                    key TEXT PRIMARY KEY,
                    timestamp TEXT,
                    exchange TEXT,
                    connected INTEGER,
                    running INTEGER,
                    mode_name TEXT,
                    reconnect_attempts INTEGER,
                    queue_size INTEGER,
                    queue_maxsize INTEGER,
                    worker_alive INTEGER,
                    ws_thread_alive INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE bot_live_status_subscriptions (
                    status_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (status_key, symbol)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE bot_live_status_symbols (
                    status_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL,
                    tick_count INTEGER,
                    kline_count INTEGER,
                    analysis_trigger_countdown INTEGER,
                    price_change_since_analysis_percent REAL,
                    last_tick TEXT,
                    last_tick_age_seconds REAL,
                    last_analysis TEXT,
                    last_analysis_age_seconds REAL,
                    bid REAL,
                    ask REAL,
                    spread REAL,
                    spread_percent REAL,
                    volume_24h REAL,
                    candle_timestamp TEXT,
                    candle_open REAL,
                    candle_high REAL,
                    candle_low REAL,
                    candle_volume REAL,
                    source TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (status_key, symbol)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bot_live_status_symbols_symbol
                ON bot_live_status_symbols (symbol)
                """
            )
            for row in status_rows:
                (
                    key, timestamp, exchange, connected, running, mode_name,
                    reconnect_attempts, queue_size, queue_maxsize, worker_alive,
                    ws_thread_alive, status_data, created_at, updated_at
                ) = row
                subscribed = []
                if status_data:
                    try:
                        subscribed = json.loads(status_data).get('subscribed_symbols') or []
                    except Exception:
                        subscribed = []
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_live_status
                    (key, timestamp, exchange, connected, running, mode_name,
                     reconnect_attempts, queue_size, queue_maxsize, worker_alive,
                     ws_thread_alive, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key, timestamp, exchange, connected, running, mode_name,
                        reconnect_attempts, queue_size, queue_maxsize, worker_alive,
                        ws_thread_alive, created_at, updated_at
                    )
                )
                for symbol in subscribed:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_live_status_subscriptions
                        (status_key, symbol, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, str(symbol), created_at, updated_at)
                    )
            for row in symbol_rows:
                status_key, symbol, price, tick_count, kline_count, last_tick, last_analysis, symbol_data, created_at, updated_at = row
                data = {}
                if symbol_data:
                    try:
                        data = json.loads(symbol_data)
                    except Exception:
                        data = {}
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_live_status_symbols
                    (status_key, symbol, price, tick_count, kline_count,
                     analysis_trigger_countdown, price_change_since_analysis_percent,
                     last_tick, last_tick_age_seconds, last_analysis,
                     last_analysis_age_seconds, bid, ask, spread, spread_percent,
                     volume_24h, candle_timestamp, candle_open, candle_high,
                     candle_low, candle_volume, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        status_key,
                        symbol,
                        self._clean(data.get('price', price)),
                        data.get('tick_count', tick_count),
                        data.get('kline_count', kline_count),
                        data.get('analysis_trigger_countdown'),
                        self._clean(data.get('price_change_since_analysis_percent')),
                        data.get('last_tick', last_tick),
                        self._clean(data.get('last_tick_age_seconds')),
                        data.get('last_analysis', last_analysis),
                        self._clean(data.get('last_analysis_age_seconds')),
                        self._clean(data.get('bid')),
                        self._clean(data.get('ask')),
                        self._clean(data.get('spread')),
                        self._clean(data.get('spread_percent')),
                        self._clean(data.get('volume_24h')),
                        data.get('candle_timestamp'),
                        self._clean(data.get('candle_open')),
                        self._clean(data.get('candle_high')),
                        self._clean(data.get('candle_low')),
                        self._clean(data.get('candle_volume')),
                        data.get('source'),
                        created_at,
                        updated_at,
                    )
                )
        except Exception:
            pass

    def _migrate_runtime_payload_schema(self, conn):
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_decision_metrics (
                    mode TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL,
                    metric_text TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (mode, idx, metric_name)
                )
                """
            )
            for table, column in (
                ('bot_commands', 'command_data'),
                ('bot_daily_stats', 'stats_data'),
                ('bot_positions', 'position_data'),
                ('bot_trailing_stops', 'stop_data'),
                ('bot_exit_recommendations', 'recommendation_data'),
                ('bot_market_context', 'context_data'),
                ('ml_live_predictions', 'prediction_data'),
                ('bot_decision_journal', 'entry_data'),
            ):
                self._drop_column(conn, table, column)
            for table, column_type in (
                ('bot_positions', ('position_size_usd', 'REAL')),
                ('bot_positions', ('position_size_crypto', 'REAL')),
                ('bot_positions', ('risk_reward_ratio', 'REAL')),
                ('bot_positions', ('target_price', 'REAL')),
                ('bot_positions', ('reason', 'TEXT')),
            ):
                column, col_type = column_type
                self._ensure_column(conn, table, column, col_type)
        except Exception:
            pass

    def _migrate_ml_payload_schema(self, conn):
        try:
            for table, column in (
                ('ml_raw_events', 'payload_data'),
                ('ml_entry_decisions', 'features_data'),
                ('ml_entry_decisions', 'bot_context_data'),
                ('ml_entry_decisions', 'trade_context_data'),
                ('ml_entry_decisions', 'exit_forecast_data'),
                ('ml_exit_decisions', 'features_data'),
                ('support_touch_results', 'settings_data'),
                ('support_touch_results', 'result_data'),
                ('ml_model_metadata', 'metadata_data'),
                ('ml_analysis_runs', 'notes_data'),
                ('ml_drift_alerts', 'metrics_data'),
            ):
                self._drop_column(conn, table, column)
            for table, column, col_type in (
                ('ml_analysis_runs', 'message', 'TEXT'),
                ('ml_analysis_runs', 'method', 'TEXT'),
                ('ml_drift_alerts', 'accepted_entries', 'INTEGER'),
                ('ml_drift_alerts', 'closed_entries', 'INTEGER'),
                ('ml_drift_alerts', 'rejected_entries', 'INTEGER'),
                ('ml_drift_alerts', 'rejected_replayed', 'INTEGER'),
                ('ml_drift_alerts', 'live_win_rate', 'REAL'),
                ('ml_drift_alerts', 'calibration_mae', 'REAL'),
                ('ml_drift_alerts', 'avg_pnl_pct', 'REAL'),
            ):
                self._ensure_column(conn, table, column, col_type)
        except Exception:
            pass

    def _migrate_support_touch_results(self, conn):
        try:
            has_runs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='support_touch_backtests'"
            ).fetchone()
            has_pairs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='support_touch_pair_results'"
            ).fetchone()
            if has_runs and has_pairs:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS support_touch_results (
                        run_id TEXT NOT NULL,
                        generated_at TEXT,
                        exchange TEXT,
                        run_timeframe TEXT,
                        candle_limit INTEGER,
                        run_total_trades INTEGER,
                        run_total_wins INTEGER,
                        run_win_rate REAL,
                        run_total_pnl_percent REAL,
                        settings_data TEXT,
                        symbol TEXT NOT NULL,
                        timeframe TEXT,
                        candles INTEGER,
                        trades INTEGER,
                        wins INTEGER,
                        losses INTEGER,
                        win_rate REAL,
                        total_pnl_percent REAL,
                        avg_pnl_percent REAL,
                        best_trade_percent REAL,
                        worst_trade_percent REAL,
                        result_data TEXT NOT NULL,
                        stored_at TEXT NOT NULL,
                        PRIMARY KEY (run_id, symbol)
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO support_touch_results
                    (run_id, generated_at, exchange, run_timeframe, candle_limit,
                     run_total_trades, run_total_wins, run_win_rate,
                     run_total_pnl_percent, settings_data, symbol, timeframe,
                     candles, trades, wins, losses, win_rate, total_pnl_percent,
                     avg_pnl_percent, best_trade_percent, worst_trade_percent,
                     result_data, stored_at)
                    SELECT
                        p.run_id, b.generated_at, b.exchange, b.timeframe, b.candle_limit,
                        b.total_trades, b.total_wins, b.win_rate,
                        b.total_pnl_percent, b.settings_data, p.symbol, p.timeframe,
                        p.candles, p.trades, p.wins, p.losses, p.win_rate,
                        p.total_pnl_percent, p.avg_pnl_percent, p.best_trade_percent,
                        p.worst_trade_percent, p.result_data, b.stored_at
                    FROM support_touch_pair_results p
                    LEFT JOIN support_touch_backtests b ON b.run_id = p.run_id
                    """
                )
            conn.execute('DROP TABLE IF EXISTS support_touch_pair_results')
            conn.execute('DROP TABLE IF EXISTS support_touch_backtests')
        except Exception:
            pass

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.sqlite_file,
                timeout=30,
                check_same_thread=False
            )
            self._conn.execute('PRAGMA busy_timeout=30000')
        return self._conn

    def close(self):
        try:
            with self._lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                try:
                    engine = self._Session.kw.get('bind')
                    if engine is not None:
                        engine.dispose()
                except Exception:
                    pass
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def __del__(self):
        self.close()

    def _insert_sqlite_event(self, event):
        try:
            event_type = event.get('event_type')
            with self._orm_session() as session:
                session.merge(MlRawEvent(
                    event_id=event.get('event_id'),
                    event_type=event_type,
                    timestamp=event.get('timestamp'),
                    symbol=event.get('symbol'),
                    mode=event.get('mode'),
                ))

                if event_type == 'entry_decision':
                    self._insert_entry_decision(session, event)
                elif event_type == 'entry_opened':
                    self._insert_open_entry(session, event)
                elif event_type == 'exit_decision':
                    self._insert_exit_decision(session, event)
                elif event_type == 'exit_outcome':
                    self._insert_trade_outcome(session, event)
                elif event_type == 'telegram_message':
                    self._insert_telegram_message(session, event)
                session.commit()
        except Exception:
            pass

    def _insert_entry_decision(self, session, event):
        session.merge(MlEntryDecision(
            event_id=event.get('event_id'),
            timestamp=event.get('timestamp'),
            mode=event.get('mode'),
            symbol=event.get('symbol'),
            decision=event.get('decision'),
            reason=event.get('reason'),
            price=event.get('price'),
            p_win=event.get('p_win'),
            min_p_win=event.get('min_p_win'),
            p_continue=event.get('p_continue'),
            min_p_continue=event.get('min_p_continue'),
            label_status=event.get('label_status'),
        ))
        self._insert_feature_values(session, MlEntryFeatureValue, event.get('event_id'), event.get('features') or {})

    def _insert_feature_values(self, session, model, event_id, features):
        if not event_id or not isinstance(features, dict):
            return
        session.execute(delete(model).where(model.event_id == event_id))
        for name, value in features.items():
            clean_value = self._clean(value)
            numeric = clean_value if isinstance(clean_value, (int, float)) and not isinstance(clean_value, bool) else None
            text_value = None if numeric is not None or clean_value is None else str(clean_value)
            session.add(model(
                event_id=event_id,
                feature_name=str(name),
                feature_value=numeric,
                feature_text=text_value,
            ))

    def get_state_value(self, key, default=None):
        try:
            with self._orm_session() as session:
                row = session.get(BotAppState, str(key))
                return row.state_value if row else default
        except Exception:
            return default

    def set_state_value(self, key, value):
        try:
            now = now_iso()
            with self._orm_session() as session:
                row = session.get(BotAppState, str(key))
                if row:
                    row.state_value = str(value)
                    row.updated_at = now
                else:
                    session.add(BotAppState(
                        state_key=str(key),
                        state_value=str(value),
                        created_at=now,
                        updated_at=now,
                    ))
                session.commit()
            return True
        except Exception:
            return False

    def claim_interval(self, key, interval_seconds, now=None, initialize_only=False):
        """Atomically claim a periodic action slot across threads/processes."""
        now = float(now if now is not None else time.time())
        session = None
        try:
            with self._lock:
                session = self._orm_session()
                session.execute(text('BEGIN IMMEDIATE'))
                row = session.get(BotAppState, str(key))
                last_value = float(row.state_value) if row and row.state_value is not None else None
                stamp = now_iso()
                if last_value is None:
                    session.add(BotAppState(
                        state_key=str(key),
                        state_value=str(now),
                        created_at=stamp,
                        updated_at=stamp,
                    ))
                    session.commit()
                    session.close()
                    return not initialize_only

                if now - last_value < float(interval_seconds):
                    session.commit()
                    session.close()
                    return False

                row.state_value = str(now)
                row.updated_at = stamp
                session.commit()
                session.close()
                return True
        except Exception as exc:
            try:
                session.rollback()
                session.close()
            except Exception:
                pass
            print(f"⚠️ SQLite claim_interval failed: {type(exc).__name__}: {exc}")
            return False

    def claim_daily_key(self, key, day_key):
        """Atomically claim a once-per-day action slot across threads/processes."""
        session = None
        try:
            with self._lock:
                session = self._orm_session()
                session.execute(text('BEGIN IMMEDIATE'))
                row = session.get(BotAppState, str(key))
                stamp = now_iso()
                if row and row.state_value == str(day_key):
                    session.commit()
                    session.close()
                    return False

                if row:
                    row.state_value = str(day_key)
                    row.updated_at = stamp
                else:
                    session.add(BotAppState(
                        state_key=str(key),
                        state_value=str(day_key),
                        created_at=stamp,
                        updated_at=stamp,
                    ))
                session.commit()
                session.close()
                return True
        except Exception as exc:
            try:
                session.rollback()
                session.close()
            except Exception:
                pass
            print(f"⚠️ SQLite claim_daily_key failed: {type(exc).__name__}: {exc}")
            return False

    def get_bot_process_state(self, key='dashboard_bot'):
        try:
            with self._orm_session() as session:
                row = session.get(BotProcess, key)
            if not row:
                return {}
            return {
                'pid': row.pid,
                'started_at': row.started_at,
                'command': row.command,
                'updated_at': row.updated_at,
            }
        except Exception:
            return {}

    def set_bot_process_state(self, payload, key='dashboard_bot'):
        try:
            now = now_iso()
            pid = payload.get('pid') if isinstance(payload, dict) else None
            started_at = payload.get('started_at') if isinstance(payload, dict) else None
            command = payload.get('command') if isinstance(payload, dict) else None
            with self._orm_session() as session:
                row = session.get(BotProcess, key)
                if row:
                    row.pid = pid
                    row.started_at = started_at
                    row.command = command
                    row.updated_at = now
                else:
                    session.add(BotProcess(
                        process_key=key,
                        pid=pid,
                        started_at=started_at,
                        command=command,
                        created_at=now,
                        updated_at=now,
                    ))
                session.commit()
            return True
        except Exception:
            return False

    def clear_bot_process_state(self, key='dashboard_bot'):
        try:
            with self._orm_session() as session:
                row = session.get(BotProcess, key)
                if row:
                    session.delete(row)
                session.commit()
            return True
        except Exception:
            return False

    def load_bot_state(self, key='paper'):
        return self._load_bot_state_orm(key)

    def save_bot_state(self, state, key='paper'):
        return self._save_bot_state_orm(state, key)

    def _split_bot_state(self, state):
        clean_state = dict(state)
        clean_state.pop('support_touch_filter', None)
        clean_state.pop('last_update', None)
        positions = clean_state.pop('positions', [])
        pending_orders = clean_state.pop('pending_orders', {})
        trailing_stops = clean_state.pop('trailing_stops', {})
        symbol_cooldowns = clean_state.pop('symbol_cooldowns', {})
        exit_recommendations = clean_state.pop('exit_recommendations', {})
        market_context = clean_state.pop('market_context', {})
        ml_predictions = clean_state.pop('ml_predictions', {})
        decision_journal = clean_state.pop('decision_journal', [])
        if not isinstance(positions, list):
            positions = []
        if not isinstance(pending_orders, dict):
            pending_orders = {}
        if not isinstance(trailing_stops, dict):
            trailing_stops = {}
        if not isinstance(symbol_cooldowns, dict):
            symbol_cooldowns = {}
        if not isinstance(exit_recommendations, dict):
            exit_recommendations = {}
        if not isinstance(market_context, dict):
            market_context = {}
        if not isinstance(ml_predictions, dict):
            ml_predictions = {}
        if not isinstance(decision_journal, list):
            decision_journal = []
        return (
            clean_state,
            positions,
            pending_orders,
            trailing_stops,
            symbol_cooldowns,
            exit_recommendations,
            market_context,
            ml_predictions,
            decision_journal
        )

    def _load_bot_state_orm(self, key='paper'):
        try:
            with self._orm_session() as session:
                state_row = session.get(BotState, key)
                if not state_row:
                    return None
                context_rows = session.scalars(
                    select(BotMarketContext).where(BotMarketContext.mode == key).order_by(BotMarketContext.symbol.asc())
                ).all()
                prediction_rows = session.scalars(
                    select(MlLivePrediction).where(MlLivePrediction.mode == key).order_by(MlLivePrediction.symbol.asc())
                ).all()
                position_rows = session.scalars(
                    select(BotPosition).where(BotPosition.mode == key).order_by(BotPosition.idx.asc())
                ).all()
                order_rows = []
                stop_rows = session.scalars(
                    select(BotTrailingStop).where(BotTrailingStop.mode == key).order_by(BotTrailingStop.symbol.asc())
                ).all()
                cooldown_rows = session.scalars(
                    select(BotSymbolCooldown).where(BotSymbolCooldown.mode == key).order_by(BotSymbolCooldown.symbol.asc())
                ).all()
                exit_rows = session.scalars(
                    select(BotExitRecommendation).where(BotExitRecommendation.mode == key).order_by(BotExitRecommendation.symbol.asc())
                ).all()
                open_entry_rows = []
                if not position_rows:
                    open_entry_rows = session.scalars(
                        select(MlOpenEntry).order_by(MlOpenEntry.opened_at.asc())
                    ).all()

            state = {
                'paper_balance': state_row.paper_balance,
                'initial_balance': state_row.initial_balance,
            }
            market_context = {}
            for row in context_rows:
                symbol_regime = row.symbol_regime
                inferred_mode = row.context_mode
                if not inferred_mode:
                    regime_text = str(symbol_regime or '')
                    if 'BULL' in regime_text or 'UP' in regime_text:
                        inferred_mode = 'BULL'
                    elif 'BEAR' in regime_text or 'DOWN' in regime_text:
                        inferred_mode = 'BEAR'
                    elif 'SIDE' in regime_text or 'RANGE' in regime_text:
                        inferred_mode = 'RANGE'
                    else:
                        inferred_mode = 'BEAR' if row.bear_mode else 'NORMAL'
                market_context[row.symbol] = {
                    'mode': inferred_mode,
                    'symbol_regime': symbol_regime,
                    'btc_regime': row.btc_regime,
                    'bear_mode': bool(row.bear_mode),
                    'symbol_bear': bool(row.symbol_bear),
                    'btc_bear': bool(row.btc_bear),
                    'trade_multiplier': row.trade_multiplier if row.trade_multiplier is not None else 1.0,
                    'btc_momentum_percent': row.btc_momentum_percent if row.btc_momentum_percent is not None else 0.0,
                    'symbol_momentum_percent': row.symbol_momentum_percent if row.symbol_momentum_percent is not None else 0.0,
                    'confidence_bonus': row.confidence_bonus,
                    'reversal': {'confirmed': bool(row.reversal_confirmed)},
                    'falling_knife': {'is_falling': bool(row.falling_knife_active)},
                }
            if market_context:
                state['market_context'] = market_context

            ml_predictions = {}
            for row in prediction_rows:
                ml_predictions[row.symbol] = {
                    'p_win': row.p_win,
                    'p_continue': row.p_continue,
                    'recommendation': row.recommendation,
                    'min_probability': row.min_probability,
                    'min_p_continue': row.min_p_continue,
                    'exit_decision': row.exit_decision,
                    'exit_reason': row.exit_reason,
                    'entry_price': row.entry_price,
                    'timestamp': row.prediction_ts,
                    'exit_forecast': {
                        'p_continue': row.p_continue,
                        'min_p_continue': row.min_p_continue,
                        'decision': row.exit_decision,
                        'reason': row.exit_reason,
                        'entry_price': row.entry_price,
                    }
                }
            if ml_predictions:
                state['ml_predictions'] = ml_predictions

            state['positions'] = [
                {
                    'symbol': row.symbol,
                    'side': row.side,
                    'amount': row.amount,
                    'price': row.price,
                    'status': row.status,
                    'order_id': row.order_id,
                    'timestamp': row.timestamp,
                    'closed_at': row.closed_at,
                    'fee': row.fee,
                    'fee_rate': row.fee_rate,
                    'position_size_usd': row.position_size_usd or (float(row.amount or 0) * float(row.price or 0)),
                    'position_size_crypto': row.position_size_crypto or float(row.amount or 0),
                    'risk_reward_ratio': row.risk_reward_ratio,
                    'target_price': row.target_price,
                    'reason': row.reason,
                }
                for row in position_rows
            ]
            if not state['positions'] and open_entry_rows:
                restored_positions = []
                restored_stops = {}
                restored_orders = {}
                for idx, row in enumerate(open_entry_rows):
                    if not row.symbol or not row.amount or not row.price:
                        continue
                    price = float(row.price)
                    amount = float(row.amount)
                    symbol = row.symbol
                    target_price = price * 1.012
                    stop_price = price * 0.995
                    restored_positions.append({
                        'symbol': symbol,
                        'side': 'buy',
                        'amount': amount,
                        'price': price,
                        'status': 'executed',
                        'order_id': row.order_id,
                        'timestamp': row.opened_at,
                        'fee_rate': 0.001,
                        'position_size_usd': amount * price,
                        'position_size_crypto': amount,
                        'stop_loss_price': stop_price,
                        'stop_loss_percent': 1.0,
                        'risk_reward_ratio': 2.0,
                        'target_price': target_price,
                        'reason': 'restored_from_ml_open_entries',
                    })
                    restored_stops[symbol] = {
                        'stop_price': stop_price,
                        'highest_price': price,
                        'buy_price': price,
                        'trailing_percent': 0.5,
                        'initial_trailing_percent': 0.5,
                        'breakeven_active': False,
                        'resistance_price': target_price,
                    }
                    order_id = f"restored_sell_{symbol.replace('/', '')}_{idx}"
                    restored_orders[order_id] = {
                        'order': {
                            'id': order_id,
                            'symbol': symbol,
                            'side': 'sell',
                            'type': 'limit',
                            'amount': amount,
                            'price': target_price,
                            'status': 'opened',
                        },
                        'timestamp': None,
                        'symbol': symbol,
                        'side': 'sell',
                        'source': 'restored_from_ml_open_entries',
                        'status': 'opened',
                        'amount': amount,
                        'price': target_price,
                        'type': 'limit',
                    }
                if restored_positions:
                    state['positions'] = restored_positions
                    state['trailing_stops'] = restored_stops
                    state['pending_orders'] = restored_orders
                    if key == 'paper':
                        initial_balance = state.get('initial_balance') or state.get('paper_balance') or 1000.0
                        open_cost = sum(float(pos.get('amount') or 0.0) * float(pos.get('price') or 0.0) for pos in restored_positions)
                        state['paper_balance'] = max(0.0, float(initial_balance) - open_cost)
            if order_rows or 'pending_orders' not in state:
                state['pending_orders'] = {
                str(row.order_id): {
                    'order': {
                        'id': row.order_id,
                        'symbol': row.symbol,
                        'side': row.side,
                        'type': row.order_type,
                        'amount': row.amount,
                        'price': row.price,
                        'status': row.status,
                    },
                    'timestamp': row.order_ts,
                    'symbol': row.symbol,
                    'side': row.side,
                    'source': row.source,
                    'status': row.status,
                    'amount': row.amount,
                    'price': row.price,
                    'type': row.order_type,
                }
                for row in order_rows
                }
            if stop_rows or 'trailing_stops' not in state:
                state['trailing_stops'] = {
                row.symbol: {
                    'stop_price': row.stop_price,
                    'highest_price': row.highest_price,
                    'buy_price': row.buy_price,
                    'trailing_percent': row.trailing_percent,
                    'initial_trailing_percent': row.initial_trailing_percent,
                    'breakeven_active': bool(row.breakeven_active),
                    'resistance_price': row.resistance_price,
                }
                for row in stop_rows
                }
            state['symbol_cooldowns'] = {row.symbol: row.cooldown_until for row in cooldown_rows}
            state['exit_recommendations'] = {
                row.symbol: {
                    'decision': row.decision,
                    'continuation_score': row.continuation_score,
                    'net_pnl_pct': row.net_pnl_pct,
                    'reason': row.reason,
                }
                for row in exit_rows
            }
            journal = self.get_decision_journal(key, 5000)
            if journal:
                state['decision_journal'] = journal
            return state
        except Exception:
            return None

    def _save_bot_state_orm(self, state, key='paper'):
        def text_value(value):
            return str(value) if value is not None else None

        for attempt in range(4):
            try:
                return self._save_bot_state_orm_once(state, key, text_value)
            except Exception as exc:
                if 'database is locked' in str(exc).lower() and attempt < 3:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                print(f"⚠️ SQLite save_bot_state failed: {type(exc).__name__}: {exc}")
                return False
        return False

    def _save_bot_state_orm_once(self, state, key, text_value):
        try:
            (
                clean_state,
                positions,
                pending_orders,
                trailing_stops,
                symbol_cooldowns,
                exit_recommendations,
                market_context,
                ml_predictions,
                decision_journal
            ) = self._split_bot_state(state or {})
            now = now_iso()
            with self._lock:
                with self._orm_session() as session:
                    session.execute(text('BEGIN IMMEDIATE'))
                    with session.no_autoflush:
                        row = session.get(BotState, key)
                        if not row:
                            row = BotState(mode=key, created_at=now, updated_at=now)
                            session.add(row)
                        row.paper_balance = self._clean(clean_state.get('paper_balance'))
                        row.initial_balance = self._clean(clean_state.get('initial_balance'))
                        row.updated_at = now

                        for model in (
                            BotTrailingStop,
                            BotSymbolCooldown,
                            BotExitRecommendation,
                            BotMarketContext,
                            MlLivePrediction,
                        ):
                            session.execute(delete(model).where(model.mode == key))

                        if positions:
                            # Upsert par idx (clé primaire avec mode)
                            existing_rows = {
                                row.idx: row
                                for row in session.scalars(
                                    select(BotPosition).where(BotPosition.mode == key)
                                ).all()
                            }
                            incoming_indices = set()
                            for idx, position in enumerate(positions):
                                if not isinstance(position, dict):
                                    continue
                                incoming_indices.add(idx)
                                oid = text_value(position.get('order_id')) or f'__no_oid_{idx}'
                                if idx in existing_rows:
                                    row = existing_rows[idx]
                                    row.symbol = position.get('symbol')
                                    row.side = position.get('side')
                                    row.status = position.get('status')
                                    row.price = self._clean(position.get('price'))
                                    row.amount = self._clean(position.get('amount'))
                                    row.order_id = oid
                                    row.timestamp = text_value(position.get('timestamp'))
                                    row.closed_at = text_value(position.get('closed_at'))
                                    row.fee = self._clean(position.get('fee'))
                                    row.fee_rate = self._clean(position.get('fee_rate'))
                                    row.position_size_usd = self._clean(position.get('position_size_usd'))
                                    row.position_size_crypto = self._clean(position.get('position_size_crypto'))
                                    row.risk_reward_ratio = self._clean(position.get('risk_reward_ratio'))
                                    row.target_price = self._clean(position.get('target_price'))
                                    row.reason = text_value(position.get('reason'))
                                    row.updated_at = now
                                else:
                                    session.add(BotPosition(
                                        mode=key,
                                        idx=idx,
                                        symbol=position.get('symbol'),
                                        side=position.get('side'),
                                        amount=self._clean(position.get('amount')),
                                        price=self._clean(position.get('price')),
                                        status=position.get('status'),
                                        order_id=oid,
                                        timestamp=text_value(position.get('timestamp')),
                                        closed_at=text_value(position.get('closed_at')),
                                        fee=self._clean(position.get('fee')),
                                        fee_rate=self._clean(position.get('fee_rate')),
                                        position_size_usd=self._clean(position.get('position_size_usd')),
                                        position_size_crypto=self._clean(position.get('position_size_crypto')),
                                        risk_reward_ratio=self._clean(position.get('risk_reward_ratio')),
                                        target_price=self._clean(position.get('target_price')),
                                        reason=text_value(position.get('reason')),
                                        created_at=now,
                                        updated_at=now,
                                    ))
                            for idx_val, row in list(existing_rows.items()):
                                if idx_val not in incoming_indices:
                                    session.delete(row)

                    # bot_pending_orders logic removed - pending orders are tracked inside bot_positions with status='opened'

                    for symbol, stop_data in trailing_stops.items():
                        if not isinstance(stop_data, dict):
                            continue
                        session.add(BotTrailingStop(
                            mode=key,
                            symbol=symbol,
                            stop_price=self._clean(stop_data.get('stop_price')),
                            highest_price=self._clean(stop_data.get('highest_price')),
                            buy_price=self._clean(stop_data.get('buy_price')),
                            trailing_percent=self._clean(stop_data.get('trailing_percent')),
                            initial_trailing_percent=self._clean(stop_data.get('initial_trailing_percent')),
                            breakeven_active=1 if stop_data.get('breakeven_active') else 0,
                            resistance_price=self._clean(stop_data.get('resistance_price')),
                            created_at=now,
                            updated_at=now,
                        ))

                    for symbol, cooldown_until in symbol_cooldowns.items():
                        session.add(BotSymbolCooldown(
                            mode=key,
                            symbol=symbol,
                            cooldown_until=self._clean(cooldown_until),
                            created_at=now,
                            updated_at=now,
                        ))

                    for symbol, recommendation in exit_recommendations.items():
                        if not isinstance(recommendation, dict):
                            continue
                        session.add(BotExitRecommendation(
                            mode=key,
                            symbol=symbol,
                            decision=recommendation.get('decision'),
                            continuation_score=self._clean(recommendation.get('continuation_score')),
                            net_pnl_pct=self._clean(recommendation.get('net_pnl_pct')),
                            reason=recommendation.get('reason'),
                            created_at=now,
                            updated_at=now,
                        ))

                    for symbol, data in market_context.items():
                        if not isinstance(data, dict):
                            data = {}
                        reversal = data.get('reversal') if isinstance(data.get('reversal'), dict) else {}
                        falling = data.get('falling_knife') if isinstance(data.get('falling_knife'), dict) else {}
                        session.add(BotMarketContext(
                            mode=key,
                            symbol=symbol,
                            context_mode=data.get('mode'),
                            symbol_regime=data.get('symbol_regime'),
                            btc_regime=data.get('btc_regime'),
                            bear_mode=1 if data.get('bear_mode') else 0,
                            symbol_bear=1 if data.get('symbol_bear') else 0,
                            btc_bear=1 if data.get('btc_bear') else 0,
                            trade_multiplier=self._clean(data.get('trade_multiplier')),
                            btc_momentum_percent=self._clean(data.get('btc_momentum_percent')),
                            symbol_momentum_percent=self._clean(data.get('symbol_momentum_percent')),
                            confidence_bonus=self._clean(data.get('confidence_bonus')),
                            reversal_confirmed=1 if reversal.get('confirmed') else 0,
                            falling_knife_active=1 if falling.get('is_falling') else 0,
                            created_at=now,
                            updated_at=now,
                        ))

                    for symbol, data in ml_predictions.items():
                        if not isinstance(data, dict):
                            data = {}
                        exit_forecast = data.get('exit_forecast') if isinstance(data.get('exit_forecast'), dict) else {}
                        session.add(MlLivePrediction(
                            mode=key,
                            symbol=symbol,
                            p_win=data.get('p_win'),
                            p_continue=data.get('p_continue') or exit_forecast.get('p_continue'),
                            recommendation=data.get('recommendation'),
                            min_probability=data.get('min_probability'),
                            min_p_continue=data.get('min_p_continue') or exit_forecast.get('min_p_continue'),
                            exit_decision=data.get('exit_decision') or exit_forecast.get('decision'),
                            exit_reason=data.get('exit_reason') or exit_forecast.get('reason'),
                            entry_price=self._clean(data.get('price') or data.get('entry_price') or exit_forecast.get('entry_price')),
                            prediction_ts=text_value(data.get('timestamp')),
                            created_at=now,
                            updated_at=now,
                        ))

                    session.commit()
            return True
        except Exception as exc:
            raise

    def _migrate_bot_state_tables(self, conn):
        return

    def _insert_open_entry(self, session, event):
        session.merge(MlOpenEntry(
            symbol=event.get('symbol'),
            entry_id=event.get('entry_id'),
            opened_at=event.get('timestamp'),
            order_id=event.get('order_id'),
            price=event.get('price'),
            amount=event.get('amount'),
        ))

    def _insert_exit_decision(self, session, event):
        session.merge(MlExitDecision(
            event_id=event.get('event_id'),
            timestamp=event.get('timestamp'),
            mode=event.get('mode'),
            symbol=event.get('symbol'),
            entry_id=event.get('entry_id'),
            decision=event.get('decision'),
            reason=event.get('reason'),
            current_price=event.get('current_price'),
            entry_p_win=event.get('entry_p_win'),
            continuation_score=event.get('continuation_score'),
            p_continue=event.get('p_continue'),
            net_pnl_pct=event.get('net_pnl_pct'),
            duration_minutes=event.get('duration_minutes'),
        ))
        self._insert_feature_values(session, MlExitFeatureValue, event.get('event_id'), event.get('features') or {})

    def _insert_trade_outcome(self, session, event):
        session.merge(MlTradeOutcome(
            event_id=event.get('event_id'),
            timestamp=event.get('timestamp'),
            mode=event.get('mode'),
            symbol=event.get('symbol'),
            entry_id=event.get('entry_id'),
            sell_price=event.get('sell_price'),
            buy_price=event.get('buy_price'),
            amount=event.get('amount'),
            pnl=event.get('pnl'),
            pnl_pct=event.get('pnl_pct'),
            hold_time=event.get('hold_time'),
            reason=event.get('reason'),
            order_id=event.get('order_id'),
            label_status=event.get('label_status'),
        ))
        if event.get('entry_id'):
            session.execute(delete(MlOpenEntry).where(MlOpenEntry.symbol == event.get('symbol')))

    def record_telegram_message(self, message_id, text, timestamp=None, direction='outgoing'):
        event = {
            'event_id': self._new_id('telegram'),
            'event_type': 'telegram_message',
            'timestamp': datetime.now().isoformat(),
            'telegram_ts': self._clean(timestamp),
            'message_id': str(message_id) if message_id is not None else None,
            'direction': direction,
            'text': text or '',
        }
        self.append_event(event)
        return event['event_id']

    def _insert_telegram_message(self, session, event):
        session.merge(TelegramMessage(
            event_id=event.get('event_id'),
            timestamp=event.get('timestamp'),
            telegram_ts=event.get('telegram_ts'),
            message_id=event.get('message_id'),
            direction=event.get('direction'),
            text=event.get('text'),
        ))

    def record_support_touch_backtest(self, summary):
        if not isinstance(summary, dict):
            return None
        generated_at = summary.get('generated_at') or datetime.now().isoformat()
        run_id = self._stable_id('support_touch', generated_at)
        results = summary.get('results') if isinstance(summary.get('results'), list) else []
        total_trades = sum(int(item.get('trades') or 0) for item in results if isinstance(item, dict))
        total_wins = sum(int(item.get('wins') or 0) for item in results if isinstance(item, dict))
        total_pnl = sum(float(item.get('total_pnl_percent') or 0.0) for item in results if isinstance(item, dict))
        win_rate = (total_wins / total_trades * 100.0) if total_trades else 0.0
        settings = summary.get('settings') if isinstance(summary.get('settings'), dict) else {}

        try:
            with self._orm_session() as session:
                session.execute(delete(SupportTouchResult).where(SupportTouchResult.run_id == run_id))
                stored_at = now_iso()
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    symbol = item.get('symbol')
                    if not symbol:
                        continue
                    session.add(SupportTouchResult(
                        run_id=run_id,
                        generated_at=generated_at,
                        exchange=summary.get('exchange'),
                        run_timeframe=settings.get('timeframe'),
                        candle_limit=settings.get('limit'),
                        run_total_trades=total_trades,
                        run_total_wins=total_wins,
                        run_win_rate=win_rate,
                        run_total_pnl_percent=total_pnl,
                        symbol=symbol,
                        timeframe=item.get('timeframe'),
                        candles=item.get('candles'),
                        trades=item.get('trades'),
                        wins=item.get('wins'),
                        losses=item.get('losses'),
                        win_rate=item.get('win_rate'),
                        total_pnl_percent=item.get('total_pnl_percent'),
                        avg_pnl_percent=item.get('avg_pnl_percent'),
                        best_trade_percent=item.get('best_trade_percent'),
                        worst_trade_percent=item.get('worst_trade_percent'),
                        stored_at=stored_at,
                    ))
                session.commit()
            return run_id
        except Exception:
            return None

    def _compact_support_touch_result(self, item):
        if not isinstance(item, dict):
            return {}
        return {key: value for key, value in item.items() if key != 'trades_detail'}

    def _compact_support_touch_summary(self, summary):
        compact = dict(summary or {})
        results = compact.get('results')
        if isinstance(results, list):
            compact['results'] = [
                self._compact_support_touch_result(item)
                for item in results
                if isinstance(item, dict)
            ]
        return compact

    def record_ml_model_metadata(self, metadata, model_path=None):
        if not isinstance(metadata, dict):
            return None
        trained_at = metadata.get('trained_at') or datetime.now().isoformat()
        model_id = self._stable_id('ml_model', f"{trained_at}:{model_path or ''}")
        try:
            with self._orm_session() as session:
                row = session.get(MlModelMetadata, model_id)
                if not row:
                    row = MlModelMetadata(model_id=model_id, stored_at=now_iso())
                    session.add(row)
                row.trained_at = trained_at
                row.model_path = model_path
                row.n_features = metadata.get('n_features')
                row.exit_n_features = metadata.get('exit_n_features')
                row.stored_at = now_iso()
                session.execute(delete(MlFeatureImportance).where(MlFeatureImportance.model_id == model_id))
                self._add_feature_importance_orm(session, model_id, 'entry', metadata.get('feature_importance'))
                self._add_feature_importance_orm(session, model_id, 'exit', metadata.get('exit_feature_importance'))
                session.commit()
            return model_id
        except Exception:
            return None

    def get_latest_support_touch_backtest(self):
        try:
            with self._orm_session() as session:
                run = session.scalars(
                    select(SupportTouchResult)
                    .order_by(SupportTouchResult.generated_at.desc(), SupportTouchResult.stored_at.desc())
                    .limit(1)
                ).first()
                if not run:
                    return {}
                rows = session.scalars(
                    select(SupportTouchResult)
                    .where(SupportTouchResult.run_id == run.run_id)
                    .order_by(SupportTouchResult.symbol.asc())
                ).all()
            settings = {'timeframe': run.run_timeframe, 'limit': run.candle_limit}
            return {
                'generated_at': run.generated_at,
                'exchange': run.exchange,
                'settings': settings,
                'results': [
                    {
                        'symbol': row.symbol,
                        'timeframe': row.timeframe,
                        'candles': row.candles,
                        'trades': row.trades,
                        'wins': row.wins,
                        'losses': row.losses,
                        'win_rate': row.win_rate,
                        'total_pnl_percent': row.total_pnl_percent,
                        'avg_pnl_percent': row.avg_pnl_percent,
                        'best_trade_percent': row.best_trade_percent,
                        'worst_trade_percent': row.worst_trade_percent,
                    }
                    for row in rows
                ],
                'summary': {
                    'total_trades': run.run_total_trades,
                    'total_wins': run.run_total_wins,
                    'win_rate': run.run_win_rate,
                    'total_pnl_percent': run.run_total_pnl_percent,
                }
            }
        except Exception:
            return {}

    def get_latest_ml_model_metadata(self):
        try:
            with self._orm_session() as session:
                row = session.scalars(
                    select(MlModelMetadata)
                    .order_by(MlModelMetadata.trained_at.desc(), MlModelMetadata.stored_at.desc())
                    .limit(1)
                ).first()
                if not row:
                    return {}
                importances = session.scalars(
                    select(MlFeatureImportance)
                    .where(MlFeatureImportance.model_id == row.model_id)
                    .order_by(MlFeatureImportance.scope.asc(), MlFeatureImportance.rank.asc())
                ).all()
            feature_importance = []
            exit_feature_importance = []
            for item in importances:
                target = exit_feature_importance if item.scope == 'exit' else feature_importance
                target.append((item.feature_name, item.importance))
            return {
                'model_id': row.model_id,
                'trained_at': row.trained_at,
                'model_path': row.model_path,
                'n_features': row.n_features,
                'exit_n_features': row.exit_n_features,
                'stored_at': row.stored_at,
                'feature_importance': feature_importance,
                'exit_feature_importance': exit_feature_importance,
            }
        except Exception:
            return {}

    def _add_feature_importance_orm(self, session, model_id, scope, items):
        if not isinstance(items, list):
            return
        for rank, item in enumerate(items, start=1):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            session.add(MlFeatureImportance(
                model_id=model_id,
                scope=scope,
                rank=rank,
                feature_name=str(item[0]),
                importance=float(item[1] or 0.0),
            ))

    def record_decision_journal(self, entry, mode='paper', max_entries=5000):
        if not isinstance(entry, dict):
            return False
        try:
            now = now_iso()
            with self._lock:
                with self._orm_session() as session:
                    max_idx = session.scalar(
                        select(func.max(BotDecisionJournal.idx))
                        .where(BotDecisionJournal.mode == mode)
                    )
                    idx = int(max_idx if max_idx is not None else -1) + 1
                    session.add(BotDecisionJournal(
                        mode=mode,
                        idx=idx,
                        timestamp=entry.get('timestamp'),
                        symbol=entry.get('symbol'),
                        action=entry.get('action'),
                        allowed=1 if entry.get('allowed') else 0 if 'allowed' in entry else None,
                        reason=entry.get('reason'),
                        created_at=now,
                        updated_at=now,
                    ))
                    metrics = entry.get('metrics') if isinstance(entry.get('metrics'), dict) else {}
                    for metric_name, metric in metrics.items():
                        numeric, text_value = self._encode_metric_value(metric)
                        session.add(BotDecisionMetric(
                            mode=mode,
                            idx=idx,
                            metric_name=str(metric_name),
                            metric_value=numeric,
                            metric_text=text_value,
                            created_at=now,
                            updated_at=now,
                        ))
                    count = session.scalar(
                        select(func.count())
                        .select_from(BotDecisionJournal)
                        .where(BotDecisionJournal.mode == mode)
                    ) or 0
                    overflow = int(count) - int(max_entries)
                    if overflow > 0:
                        old_indices = session.scalars(
                            select(BotDecisionJournal.idx)
                            .where(BotDecisionJournal.mode == mode)
                            .order_by(BotDecisionJournal.idx.asc())
                            .limit(overflow)
                        ).all()
                        session.execute(
                            delete(BotDecisionMetric)
                            .where(
                                BotDecisionMetric.mode == mode,
                                BotDecisionMetric.idx.in_(old_indices),
                            )
                        )
                        session.execute(
                            delete(BotDecisionJournal)
                            .where(
                                BotDecisionJournal.mode == mode,
                                BotDecisionJournal.idx.in_(old_indices),
                            )
                        )
                    session.commit()
            return True
        except Exception:
            return False

    def get_decision_journal(self, mode='paper', limit=80):
        try:
            with self._orm_session() as session:
                rows = session.scalars(
                    select(BotDecisionJournal)
                    .where(BotDecisionJournal.mode == mode)
                    .order_by(BotDecisionJournal.idx.desc())
                    .limit(int(limit))
                ).all()
                indices = [row.idx for row in rows]
                metric_rows = session.scalars(
                    select(BotDecisionMetric)
                    .where(
                        BotDecisionMetric.mode == mode,
                        BotDecisionMetric.idx.in_(indices or [-1]),
                    )
                ).all()
            metrics_by_idx = {}
            for metric in metric_rows:
                metrics_by_idx.setdefault(metric.idx, {})[metric.metric_name] = self._decode_metric_value(metric)
            items = []
            for row in reversed(rows):
                items.append({
                    'timestamp': row.timestamp,
                    'symbol': row.symbol,
                    'action': row.action,
                    'allowed': bool(row.allowed),
                    'reason': row.reason,
                    'mode': mode,
                    'metrics': metrics_by_idx.get(row.idx, {}),
                })
            return items
        except Exception:
            return []

    def count_decision_journal(self, mode='paper'):
        try:
            with self._orm_session() as session:
                return int(session.scalar(
                    select(func.count())
                    .select_from(BotDecisionJournal)
                    .where(BotDecisionJournal.mode == mode)
                ) or 0)
        except Exception:
            return 0

    def add_bot_command(self, action, symbol=None, seconds=None, payload=None):
        try:
            now_ts = time.time()
            now = now_iso()
            command_id = self._new_id('cmd')
            with self._orm_session() as session:
                session.add(BotCommand(
                    command_id=command_id,
                    action=action,
                    symbol=symbol,
                    seconds=self._clean(seconds),
                    status='pending',
                    command_ts=now_ts,
                    created_at=now,
                    updated_at=now,
                ))
                session.commit()
            return command_id
        except Exception:
            return None

    def claim_pending_bot_commands(self, limit=100):
        session = None
        try:
            with self._lock:
                session = self._orm_session()
                session.execute(text('BEGIN IMMEDIATE'))
                rows = session.scalars(
                    select(BotCommand)
                    .where(BotCommand.status == 'pending')
                    .order_by(BotCommand.command_ts.asc())
                    .limit(int(limit))
                ).all()
                ids = [row.command_id for row in rows]
                if ids:
                    now = now_iso()
                    session.execute(
                        update(BotCommand)
                        .where(BotCommand.command_id.in_(ids))
                        .values(status='claimed', updated_at=now)
                    )
                session.commit()
            commands = []
            for row in rows:
                commands.append({
                    'command_id': row.command_id,
                    'action': row.action,
                    'symbol': row.symbol,
                    'seconds': row.seconds,
                    'timestamp': row.command_ts,
                })
            if session:
                session.close()
            return commands
        except Exception:
            try:
                if session:
                    session.rollback()
                    session.close()
            except Exception:
                pass
            return []

    def record_crypto_score(self, symbol, score, price):
        try:
            now = now_iso()
            score_id = self._new_id('score')
            with self._orm_session() as session:
                session.add(CryptoScoreHistory(
                    score_id=score_id,
                    timestamp=now,
                    symbol=symbol,
                    score=int(score),
                    price=self._clean(price),
                    created_at=now,
                    updated_at=now,
                ))
                session.commit()
            return score_id
        except Exception:
            return None

    def get_crypto_scores(self, symbol, since_iso=None, limit=2000):
        try:
            with self._orm_session() as session:
                query = select(CryptoScoreHistory).where(CryptoScoreHistory.symbol == symbol)
                if since_iso:
                    query = query.where(CryptoScoreHistory.timestamp >= since_iso)
                rows = session.scalars(
                    query.order_by(CryptoScoreHistory.timestamp.asc()).limit(int(limit))
                ).all()
            return [
                {'timestamp': r.timestamp, 'symbol': r.symbol, 'score': r.score, 'price': r.price}
                for r in rows
            ]
        except Exception:
            return []

    def save_live_status(self, status):
        if not isinstance(status, dict):
            return False
        try:
            now = now_iso()
            key = 'latest'
            symbols = status.get('symbols') if isinstance(status.get('symbols'), dict) else {}
            with self._orm_session() as session:
                row = session.get(BotLiveStatus, key)
                if not row:
                    row = BotLiveStatus(key=key, created_at=now)
                    session.add(row)
                row.timestamp = status.get('timestamp')
                row.exchange = status.get('exchange')
                row.connected = 1 if status.get('connected') else 0
                row.running = 1 if status.get('running') else 0
                row.mode_name = status.get('mode')
                row.reconnect_attempts = status.get('reconnect_attempts')
                row.queue_size = status.get('queue_size')
                row.queue_maxsize = status.get('queue_maxsize')
                row.worker_alive = 1 if status.get('worker_alive') else 0
                row.ws_thread_alive = 1 if status.get('ws_thread_alive') else 0
                row.updated_at = now
                session.execute(delete(BotLiveStatusSubscription).where(BotLiveStatusSubscription.status_key == key))
                for symbol in status.get('subscribed_symbols') or []:
                    session.add(BotLiveStatusSubscription(
                        status_key=key,
                        symbol=str(symbol),
                        created_at=now,
                        updated_at=now,
                    ))
                session.execute(delete(BotLiveStatusSymbol).where(BotLiveStatusSymbol.status_key == key))
                for symbol, data in symbols.items():
                    if not isinstance(data, dict):
                        data = {}
                    session.add(BotLiveStatusSymbol(
                        status_key=key,
                        symbol=symbol,
                        price=self._clean(data.get('price')),
                        tick_count=data.get('tick_count'),
                        kline_count=data.get('kline_count'),
                        analysis_trigger_countdown=data.get('analysis_trigger_countdown'),
                        price_change_since_analysis_percent=self._clean(data.get('price_change_since_analysis_percent')),
                        last_tick=data.get('last_tick'),
                        last_tick_age_seconds=self._clean(data.get('last_tick_age_seconds')),
                        last_analysis=data.get('last_analysis'),
                        last_analysis_age_seconds=self._clean(data.get('last_analysis_age_seconds')),
                        bid=self._clean(data.get('bid')),
                        ask=self._clean(data.get('ask')),
                        spread=self._clean(data.get('spread')),
                        spread_percent=self._clean(data.get('spread_percent')),
                        volume_24h=self._clean(data.get('volume_24h')),
                        candle_timestamp=data.get('candle_timestamp'),
                        candle_open=self._clean(data.get('candle_open')),
                        candle_high=self._clean(data.get('candle_high')),
                        candle_low=self._clean(data.get('candle_low')),
                        candle_volume=self._clean(data.get('candle_volume')),
                        source=data.get('source'),
                        created_at=now,
                        updated_at=now,
                    ))
                session.commit()
            return True
        except Exception:
            return False

    def get_live_status(self):
        try:
            with self._orm_session() as session:
                row = session.get(BotLiveStatus, 'latest')
                if not row:
                    return {}
                subscription_rows = session.scalars(
                    select(BotLiveStatusSubscription)
                    .where(BotLiveStatusSubscription.status_key == row.key)
                    .order_by(BotLiveStatusSubscription.symbol.asc())
                ).all()
                subscriptions = [item.symbol for item in subscription_rows]
                symbol_rows = session.scalars(
                    select(BotLiveStatusSymbol)
                    .where(BotLiveStatusSymbol.status_key == row.key)
                    .order_by(BotLiveStatusSymbol.symbol.asc())
                ).all()
                if not subscriptions:
                    subscriptions = [item.symbol for item in symbol_rows]
            symbols = {}
            for item in symbol_rows:
                data = {
                    'price': item.price,
                    'tick_count': item.tick_count,
                    'kline_count': item.kline_count,
                    'analysis_trigger_countdown': item.analysis_trigger_countdown,
                    'price_change_since_analysis_percent': item.price_change_since_analysis_percent,
                    'last_tick': item.last_tick,
                    'last_tick_age_seconds': item.last_tick_age_seconds,
                    'last_analysis': item.last_analysis,
                    'last_analysis_age_seconds': item.last_analysis_age_seconds,
                    'bid': item.bid,
                    'ask': item.ask,
                    'spread': item.spread,
                    'spread_percent': item.spread_percent,
                    'volume_24h': item.volume_24h,
                    'candle_timestamp': item.candle_timestamp,
                    'candle_open': item.candle_open,
                    'candle_high': item.candle_high,
                    'candle_low': item.candle_low,
                    'candle_volume': item.candle_volume,
                    'source': item.source,
                }
                symbols[item.symbol] = {key: value for key, value in data.items() if value is not None}
            return {
                'timestamp': row.timestamp,
                'exchange': row.exchange,
                'connected': bool(row.connected),
                'running': bool(row.running),
                'mode': row.mode_name,
                'reconnect_attempts': row.reconnect_attempts,
                'queue_size': row.queue_size,
                'queue_maxsize': row.queue_maxsize,
                'worker_alive': bool(row.worker_alive),
                'ws_thread_alive': bool(row.ws_thread_alive),
                'subscribed_symbols': subscriptions,
                'symbols': symbols,
            }
        except Exception:
            return {}

    def save_daily_stats(self, stats):
        if not isinstance(stats, dict):
            return False
        try:
            now = now_iso()
            stat_date = str(stats.get('date') or datetime.now().strftime('%Y-%m-%d'))
            with self._orm_session() as session:
                row = session.get(BotDailyStat, stat_date)
                if not row:
                    row = BotDailyStat(stat_date=stat_date, created_at=now)
                    session.add(row)
                row.trades_count = int(stats.get('trades_count') or 0)
                row.total_loss = self._clean(stats.get('total_loss') or 0)
                row.total_profit = self._clean(stats.get('total_profit') or 0)
                row.emergency_stop = 1 if stats.get('emergency_stop') else 0
                row.updated_at = now
                session.commit()
            return True
        except Exception:
            return False

    def load_daily_stats(self, stat_date=None):
        try:
            stat_date = stat_date or datetime.now().strftime('%Y-%m-%d')
            with self._orm_session() as session:
                row = session.get(BotDailyStat, stat_date)
            if not row:
                return {}
            return {
                'date': row.stat_date,
                'trades_count': row.trades_count or 0,
                'total_loss': row.total_loss or 0,
                'total_profit': row.total_profit or 0,
                'emergency_stop': bool(row.emergency_stop),
            }
        except Exception:
            return {}

    def load_open_entries(self):
        try:
            with self._orm_session() as session:
                rows = session.scalars(select(MlOpenEntry).order_by(MlOpenEntry.symbol.asc())).all()
            return {
                row.symbol: {
                    'entry_id': row.entry_id,
                    'symbol': row.symbol,
                    'opened_at': row.opened_at,
                    'order_id': row.order_id,
                    'price': row.price,
                    'amount': row.amount,
                }
                for row in rows
            }
        except Exception:
            return {}

    def _features_to_dict(self, feature_names, features):
        if features is None:
            return {}
        if isinstance(features, dict):
            return {
                str(name): self._clean(value)
                for name, value in features.items()
            }
        values = list(features.tolist() if hasattr(features, 'tolist') else features)
        names = list(feature_names or [])
        if not names:
            names = [f'feature_{idx}' for idx in range(len(values))]
        return {
            str(name): self._clean(values[idx])
            for idx, name in enumerate(names[:len(values)])
        }

    def _new_id(self, prefix):
        return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}"

    def _stable_id(self, prefix, value):
        safe = ''.join(ch if ch.isalnum() else '_' for ch in str(value))[:80].strip('_')
        return f"{prefix}_{safe or uuid.uuid4().hex[:10]}"

    def _clean(self, value):
        if isinstance(value, dict):
            return {str(k): self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        if hasattr(value, 'item'):
            try:
                value = value.item()
            except Exception:
                pass
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        return value

    def _encode_metric_value(self, value):
        clean_value = self._clean(value)
        if isinstance(clean_value, (dict, list)):
            return None, json.dumps(clean_value, ensure_ascii=False)
        if isinstance(clean_value, (int, float)) and not isinstance(clean_value, bool):
            return clean_value, None
        if clean_value is None:
            return None, None
        return None, str(clean_value)

    def _decode_metric_value(self, metric):
        if metric.metric_value is not None:
            return metric.metric_value
        text_value = metric.metric_text
        if not isinstance(text_value, str):
            return text_value
        stripped = text_value.strip()
        if not stripped:
            return text_value
        if stripped[0] in '{[':
            try:
                return json.loads(stripped)
            except Exception:
                try:
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except Exception:
                    pass
        if stripped in {'True', 'False'}:
            return stripped == 'True'
        return text_value
