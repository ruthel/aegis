import json
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime


class MLLiveLogger:
    """SQLite journal for live ML decisions and trade outcomes."""

    def __init__(self, data_dir='data', open_file=None, sqlite_file=None):
        self.data_dir = data_dir
        self.sqlite_file = sqlite_file or os.path.join(data_dir, 'aegis_db.sqlite3')
        self._lock = threading.Lock()
        self._conn = None
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
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=5000')
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
                self._ensure_column(conn, 'bot_market_context', 'btc_regime', 'TEXT')
                self._ensure_column(conn, 'bot_market_context', 'bear_mode', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'confidence_bonus', 'REAL')
                self._ensure_column(conn, 'bot_market_context', 'reversal_confirmed', 'INTEGER')
                self._ensure_column(conn, 'bot_market_context', 'falling_knife_active', 'INTEGER')
                self._ensure_column(conn, 'ml_live_predictions', 'p_continue', 'REAL')
                self._ensure_column(conn, 'ml_live_predictions', 'min_p_continue', 'REAL')
                self._ensure_column(conn, 'ml_live_predictions', 'exit_decision', 'TEXT')
                self._ensure_column(conn, 'ml_live_predictions', 'exit_reason', 'TEXT')
                self._ensure_column(conn, 'ml_live_predictions', 'entry_price', 'REAL')
                conn.execute('DROP TABLE IF EXISTS support_touch_trade_results')
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS ml_raw_events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        symbol TEXT,
                        mode TEXT,
                        payload_data TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ml_entry_decisions (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        mode TEXT,
                        symbol TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        reason TEXT,
                        price REAL,
                        p_win REAL,
                        min_p_win REAL,
                        p_continue REAL,
                        min_p_continue REAL,
                        label_status TEXT,
                        features_data TEXT,
                        bot_context_data TEXT,
                        trade_context_data TEXT,
                        exit_forecast_data TEXT
                    );

                    CREATE TABLE IF NOT EXISTS ml_entry_feature_values (
                        event_id TEXT NOT NULL,
                        feature_name TEXT NOT NULL,
                        feature_value REAL,
                        feature_text TEXT,
                        PRIMARY KEY (event_id, feature_name)
                    );

                    CREATE TABLE IF NOT EXISTS ml_open_entries (
                        symbol TEXT PRIMARY KEY,
                        entry_id TEXT NOT NULL,
                        opened_at TEXT NOT NULL,
                        order_id TEXT,
                        price REAL,
                        amount REAL
                    );

                    CREATE TABLE IF NOT EXISTS ml_exit_decisions (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        mode TEXT,
                        symbol TEXT NOT NULL,
                        entry_id TEXT,
                        decision TEXT,
                        reason TEXT,
                        current_price REAL,
                        entry_p_win REAL,
                        continuation_score REAL,
                        p_continue REAL,
                        net_pnl_pct REAL,
                        duration_minutes REAL,
                        features_data TEXT
                    );

                    CREATE TABLE IF NOT EXISTS ml_exit_feature_values (
                        event_id TEXT NOT NULL,
                        feature_name TEXT NOT NULL,
                        feature_value REAL,
                        feature_text TEXT,
                        PRIMARY KEY (event_id, feature_name)
                    );

                    CREATE TABLE IF NOT EXISTS ml_trade_outcomes (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        mode TEXT,
                        symbol TEXT NOT NULL,
                        entry_id TEXT,
                        sell_price REAL,
                        buy_price REAL,
                        amount REAL,
                        pnl REAL,
                        pnl_pct REAL,
                        hold_time TEXT,
                        reason TEXT,
                        order_id TEXT,
                        label_status TEXT
                    );

                    CREATE TABLE IF NOT EXISTS telegram_messages (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        telegram_ts INTEGER,
                        message_id TEXT,
                        direction TEXT NOT NULL,
                        text TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS bot_live_status (
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
                        status_data TEXT NOT NULL,
                        updated_at TEXT,
                        created_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_live_status_symbols (
                        status_key TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        price REAL,
                        tick_count INTEGER,
                        kline_count INTEGER,
                        last_tick TEXT,
                        last_analysis TEXT,
                        symbol_data TEXT NOT NULL,
                        updated_at TEXT,
                        created_at TEXT,
                        PRIMARY KEY (status_key, symbol)
                    );

                    CREATE TABLE IF NOT EXISTS bot_commands (
                        command_id TEXT PRIMARY KEY,
                        action TEXT NOT NULL,
                        symbol TEXT,
                        seconds REAL,
                        status TEXT NOT NULL,
                        command_ts REAL,
                        command_data TEXT NOT NULL,
                        created_at TEXT,
                        updated_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS crypto_score_history (
                        score_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        score INTEGER,
                        price REAL,
                        created_at TEXT,
                        updated_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_state (
                        mode TEXT PRIMARY KEY,
                        paper_balance REAL,
                        initial_balance REAL,
                        updated_at TEXT NOT NULL,
                        created_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_app_state (
                        state_key TEXT PRIMARY KEY,
                        state_value TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_processes (
                        process_key TEXT PRIMARY KEY,
                        pid INTEGER,
                        started_at TEXT,
                        command TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_daily_stats (
                        stat_date TEXT PRIMARY KEY,
                        trades_count INTEGER,
                        total_loss REAL,
                        total_profit REAL,
                        emergency_stop INTEGER,
                        stats_data TEXT NOT NULL,
                        created_at TEXT,
                        updated_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS bot_positions (
                        mode TEXT NOT NULL,
                        idx INTEGER NOT NULL,
                        symbol TEXT,
                        side TEXT,
                        amount REAL,
                        price REAL,
                        status TEXT,
                        order_id TEXT,
                        timestamp TEXT,
                        closed_at TEXT,
                        sell_price REAL,
                        fee REAL,
                        fee_rate REAL,
                        position_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, idx)
                    );

                    CREATE TABLE IF NOT EXISTS bot_pending_orders (
                        mode TEXT NOT NULL,
                        order_id TEXT NOT NULL,
                        symbol TEXT,
                        side TEXT,
                        order_type TEXT,
                        amount REAL,
                        price REAL,
                        status TEXT,
                        created_at TEXT,
                        order_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, order_id)
                    );

                    CREATE TABLE IF NOT EXISTS bot_trailing_stops (
                        mode TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        stop_price REAL,
                        highest_price REAL,
                        buy_price REAL,
                        trailing_percent REAL,
                        initial_trailing_percent REAL,
                        breakeven_active INTEGER,
                        resistance_price REAL,
                        stop_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, symbol)
                    );

                    CREATE TABLE IF NOT EXISTS bot_symbol_cooldowns (
                        mode TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        cooldown_until REAL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, symbol)
                    );

                    CREATE TABLE IF NOT EXISTS bot_exit_recommendations (
                        mode TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        decision TEXT,
                        continuation_score REAL,
                        net_pnl_pct REAL,
                        reason TEXT,
                        recommendation_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, symbol)
                    );

                    CREATE TABLE IF NOT EXISTS bot_decision_journal (
                        mode TEXT NOT NULL,
                        idx INTEGER NOT NULL,
                        timestamp TEXT,
                        symbol TEXT,
                        action TEXT,
                        allowed INTEGER,
                        reason TEXT,
                        entry_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, idx)
                    );

                    CREATE TABLE IF NOT EXISTS bot_market_context (
                        mode TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        symbol_regime TEXT,
                        btc_regime TEXT,
                        bear_mode INTEGER,
                        confidence_bonus REAL,
                        reversal_confirmed INTEGER,
                        falling_knife_active INTEGER,
                        context_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, symbol)
                    );

                    CREATE TABLE IF NOT EXISTS ml_live_predictions (
                        mode TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        p_win REAL,
                        p_continue REAL,
                        recommendation TEXT,
                        min_probability REAL,
                        min_p_continue REAL,
                        exit_decision TEXT,
                        exit_reason TEXT,
                        entry_price REAL,
                        prediction_ts TEXT,
                        prediction_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (mode, symbol)
                    );

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

                    CREATE TABLE IF NOT EXISTS ml_model_metadata (
                        model_id TEXT PRIMARY KEY,
                        trained_at TEXT,
                        model_path TEXT,
                        n_features INTEGER,
                        exit_n_features INTEGER,
                        metadata_data TEXT NOT NULL,
                        stored_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ml_feature_importances (
                        model_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        rank INTEGER NOT NULL,
                        feature_name TEXT NOT NULL,
                        importance REAL NOT NULL,
                        PRIMARY KEY (model_id, scope, rank)
                    );

                    CREATE TABLE IF NOT EXISTS ml_analysis_runs (
                        run_id TEXT PRIMARY KEY,
                        generated_at TEXT NOT NULL,
                        accepted_entries INTEGER NOT NULL,
                        closed_entries INTEGER NOT NULL,
                        rejected_entries INTEGER NOT NULL,
                        rejected_replayed INTEGER NOT NULL,
                        brier_score REAL,
                        calibration_mae REAL,
                        live_win_rate REAL,
                        avg_pnl_pct REAL,
                        drift_status TEXT NOT NULL,
                        notes_data TEXT,
                        stored_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ml_prediction_calibration (
                        run_id TEXT NOT NULL,
                        bucket_label TEXT NOT NULL,
                        min_p_win REAL NOT NULL,
                        max_p_win REAL NOT NULL,
                        entries INTEGER NOT NULL,
                        closed_entries INTEGER NOT NULL,
                        predicted_avg REAL,
                        realized_win_rate REAL,
                        avg_pnl_pct REAL,
                        calibration_error REAL,
                        PRIMARY KEY (run_id, bucket_label)
                    );

                    CREATE TABLE IF NOT EXISTS ml_rejected_replay_results (
                        entry_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        entry_price REAL,
                        p_win REAL,
                        p_continue REAL,
                        replay_status TEXT NOT NULL,
                        replay_method TEXT,
                        exit_time TEXT,
                        exit_price REAL,
                        pnl_pct REAL,
                        would_win INTEGER,
                        reason TEXT,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS ml_drift_alerts (
                        alert_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        generated_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT NOT NULL,
                        metrics_data TEXT,
                        stored_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_ml_raw_events_type_time ON ml_raw_events(event_type, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_ml_entry_symbol_time ON ml_entry_decisions(symbol, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_ml_exit_symbol_time ON ml_exit_decisions(symbol, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_ml_entry_feature_name ON ml_entry_feature_values(feature_name);
                    CREATE INDEX IF NOT EXISTS idx_ml_exit_feature_name ON ml_exit_feature_values(feature_name);
                    CREATE INDEX IF NOT EXISTS idx_ml_outcome_entry ON ml_trade_outcomes(entry_id);
                    CREATE INDEX IF NOT EXISTS idx_telegram_messages_time ON telegram_messages(timestamp);
                    CREATE INDEX IF NOT EXISTS idx_telegram_messages_direction ON telegram_messages(direction);
                    CREATE INDEX IF NOT EXISTS idx_crypto_score_symbol_time ON crypto_score_history(symbol, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_bot_commands_status ON bot_commands(status, command_ts);
                    CREATE INDEX IF NOT EXISTS idx_support_touch_results_symbol ON support_touch_results(symbol);
                    CREATE INDEX IF NOT EXISTS idx_support_touch_results_time ON support_touch_results(generated_at);
                    CREATE INDEX IF NOT EXISTS idx_ml_model_metadata_trained ON ml_model_metadata(trained_at);
                    CREATE INDEX IF NOT EXISTS idx_ml_rejected_replay_status ON ml_rejected_replay_results(replay_status);
                    CREATE INDEX IF NOT EXISTS idx_ml_analysis_runs_time ON ml_analysis_runs(generated_at);
                    CREATE INDEX IF NOT EXISTS idx_bot_state_mode ON bot_state(mode);
                    CREATE INDEX IF NOT EXISTS idx_bot_processes_pid ON bot_processes(pid);
                    CREATE INDEX IF NOT EXISTS idx_bot_positions_symbol ON bot_positions(mode, symbol);
                    CREATE INDEX IF NOT EXISTS idx_bot_positions_order ON bot_positions(mode, order_id);
                    CREATE INDEX IF NOT EXISTS idx_bot_pending_orders_symbol ON bot_pending_orders(mode, symbol);
                    CREATE INDEX IF NOT EXISTS idx_bot_decision_journal_time ON bot_decision_journal(mode, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_bot_market_context_symbol ON bot_market_context(mode, symbol);
                    CREATE INDEX IF NOT EXISTS idx_ml_live_predictions_symbol ON ml_live_predictions(mode, symbol);
                    """
                )
                self._migrate_app_state_to_bot_state(conn)
                self._migrate_runtime_rows_out_of_bot_state(conn)
                self._compact_bot_state_schema(conn)
                self._migrate_bot_state_tables(conn)
                conn.execute('DROP TABLE IF EXISTS bot_state_sections')
                self._ensure_audit_columns(conn)
                conn.commit()
        except Exception:
            pass

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

    def _migrate_support_touch_results(self, conn):
        try:
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
            has_runs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='support_touch_backtests'"
            ).fetchone()
            has_pairs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='support_touch_pair_results'"
            ).fetchone()
            if has_runs and has_pairs:
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
                timeout=5,
                check_same_thread=False
            )
            self._conn.execute('PRAGMA busy_timeout=5000')
        return self._conn

    def close(self):
        try:
            with self._lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
        except Exception:
            pass

    def __del__(self):
        self.close()

    def _insert_sqlite_event(self, event):
        try:
            conn = self._get_conn()
            event_type = event.get('event_type')
            payload = json.dumps(event, ensure_ascii=False)
            conn.execute(
                """
                INSERT OR REPLACE INTO ml_raw_events
                (event_id, event_type, timestamp, symbol, mode, payload_data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get('event_id'),
                    event_type,
                    event.get('timestamp'),
                    event.get('symbol'),
                    event.get('mode'),
                    payload
                )
            )

            if event_type == 'entry_decision':
                self._insert_entry_decision(conn, event)
            elif event_type == 'entry_opened':
                self._insert_open_entry(conn, event)
            elif event_type == 'exit_decision':
                self._insert_exit_decision(conn, event)
            elif event_type == 'exit_outcome':
                self._insert_trade_outcome(conn, event)
            elif event_type == 'telegram_message':
                self._insert_telegram_message(conn, event)
            conn.commit()
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass

    def _insert_entry_decision(self, conn, event):
        conn.execute(
            """
            INSERT OR REPLACE INTO ml_entry_decisions
            (event_id, timestamp, mode, symbol, decision, reason, price, p_win,
             min_p_win, p_continue, min_p_continue, label_status, features_data,
             bot_context_data, trade_context_data, exit_forecast_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('event_id'),
                event.get('timestamp'),
                event.get('mode'),
                event.get('symbol'),
                event.get('decision'),
                event.get('reason'),
                event.get('price'),
                event.get('p_win'),
                event.get('min_p_win'),
                event.get('p_continue'),
                event.get('min_p_continue'),
                event.get('label_status'),
                json.dumps(event.get('features') or {}, ensure_ascii=False),
                json.dumps(event.get('bot_context') or {}, ensure_ascii=False),
                json.dumps(event.get('trade_context') or {}, ensure_ascii=False),
                json.dumps(event.get('exit_forecast') or {}, ensure_ascii=False),
            )
        )
        self._insert_feature_values(conn, 'ml_entry_feature_values', event.get('event_id'), event.get('features') or {})

    def _insert_feature_values(self, conn, table_name, event_id, features):
        if not event_id or not isinstance(features, dict):
            return
        conn.execute(f"DELETE FROM {table_name} WHERE event_id = ?", (event_id,))
        for name, value in features.items():
            clean_value = self._clean(value)
            numeric = clean_value if isinstance(clean_value, (int, float)) and not isinstance(clean_value, bool) else None
            text_value = None if numeric is not None or clean_value is None else str(clean_value)
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {table_name}
                (event_id, feature_name, feature_value, feature_text)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, str(name), numeric, text_value)
            )

    def get_state_value(self, key, default=None):
        try:
            with self._lock:
                row = self._get_conn().execute(
                    """
                    SELECT state_value FROM bot_app_state
                    WHERE state_key = ?
                    """
                    ,
                    (str(key),)
                ).fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def set_state_value(self, key, value):
        try:
            now = datetime.now().isoformat()
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """
                    INSERT INTO bot_app_state
                    (state_key, state_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        state_value = excluded.state_value,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), str(value), now, now)
                )
                conn.commit()
            return True
        except Exception:
            return False

    def claim_interval(self, key, interval_seconds, now=None, initialize_only=False):
        """Atomically claim a periodic action slot across threads/processes."""
        now = float(now if now is not None else time.time())
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute(
                    "SELECT state_value FROM bot_app_state WHERE state_key = ?",
                    (str(key),)
                ).fetchone()
                last_value = float(row[0]) if row and row[0] is not None else None
                if last_value is None:
                    conn.execute(
                        """
                        INSERT INTO bot_app_state
                        (state_key, state_value, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(state_key) DO UPDATE SET
                            state_value = excluded.state_value,
                            updated_at = excluded.updated_at
                        """,
                        (str(key), str(now), datetime.now().isoformat(), datetime.now().isoformat())
                    )
                    conn.commit()
                    return not initialize_only

                if now - last_value < float(interval_seconds):
                    conn.commit()
                    return False

                conn.execute(
                    """
                    INSERT INTO bot_app_state
                    (state_key, state_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        state_value = excluded.state_value,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), str(now), datetime.now().isoformat(), datetime.now().isoformat())
                )
                conn.commit()
                return True
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return False

    def _state_value_column(self, key):
        safe = ''.join(ch if ch.isalnum() else '_' for ch in str(key).strip().lower()).strip('_')
        return safe or 'value'

    def get_bot_process_state(self, key='dashboard_bot'):
        try:
            with self._lock:
                row = self._get_conn().execute(
                    """
                    SELECT pid, started_at, command, updated_at
                    FROM bot_processes
                    WHERE process_key = ?
                    """,
                    (key,)
                ).fetchone()
            if not row:
                return {}
            return {
                'pid': row[0],
                'started_at': row[1],
                'command': row[2],
                'updated_at': row[3],
            }
        except Exception:
            return {}

    def set_bot_process_state(self, payload, key='dashboard_bot'):
        try:
            now = datetime.now().isoformat()
            with self._lock:
                self._get_conn().execute(
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
                        payload.get('pid') if isinstance(payload, dict) else None,
                        payload.get('started_at') if isinstance(payload, dict) else None,
                        payload.get('command') if isinstance(payload, dict) else None,
                        now,
                        now,
                    )
                )
                self._get_conn().commit()
            return True
        except Exception:
            return False

    def clear_bot_process_state(self, key='dashboard_bot'):
        try:
            with self._lock:
                self._get_conn().execute(
                    "DELETE FROM bot_processes WHERE process_key = ?",
                    (key,)
                )
                self._get_conn().commit()
            return True
        except Exception:
            return False

    def load_bot_state(self, key='paper'):
        try:
            with self._lock:
                state_row = self._get_conn().execute(
                    """
                    SELECT paper_balance, initial_balance, updated_at
                    FROM bot_state
                    WHERE mode = ?
                    """,
                    (key,)
                ).fetchone()
                context_rows = self._get_conn().execute(
                    """
                    SELECT symbol, context_data
                    FROM bot_market_context
                    WHERE mode = ?
                    """,
                    (key,)
                ).fetchall()
                prediction_rows = self._get_conn().execute(
                    """
                    SELECT symbol, prediction_data
                    FROM ml_live_predictions
                    WHERE mode = ?
                    """,
                    (key,)
                ).fetchall()
                journal_rows = self._get_conn().execute(
                    """
                    SELECT entry_data
                    FROM bot_decision_journal
                    WHERE mode = ?
                    ORDER BY idx ASC
                    """,
                    (key,)
                ).fetchall()
                position_rows = self._get_conn().execute(
                    """
                    SELECT position_data
                    FROM bot_positions
                    WHERE mode = ?
                    ORDER BY idx ASC
                    """,
                    (key,)
                ).fetchall()
                order_rows = self._get_conn().execute(
                    """
                    SELECT order_id, order_data
                    FROM bot_pending_orders
                    WHERE mode = ?
                    ORDER BY order_id ASC
                    """,
                    (key,)
                ).fetchall()
                stop_rows = self._get_conn().execute(
                    """
                    SELECT symbol, stop_data
                    FROM bot_trailing_stops
                    WHERE mode = ?
                    ORDER BY symbol ASC
                    """,
                    (key,)
                ).fetchall()
                cooldown_rows = self._get_conn().execute(
                    """
                    SELECT symbol, cooldown_until
                    FROM bot_symbol_cooldowns
                    WHERE mode = ?
                    ORDER BY symbol ASC
                    """,
                    (key,)
                ).fetchall()
                exit_rows = self._get_conn().execute(
                    """
                    SELECT symbol, recommendation_data
                    FROM bot_exit_recommendations
                    WHERE mode = ?
                    ORDER BY symbol ASC
                    """,
                    (key,)
                ).fetchall()
            if not state_row:
                return None
            state = {
                'paper_balance': state_row[0],
                'initial_balance': state_row[1],
            }
            market_context = {}
            for symbol, context_data in context_rows:
                try:
                    market_context[symbol] = json.loads(context_data)
                except Exception:
                    pass
            if market_context:
                state['market_context'] = market_context
            ml_predictions = {}
            for symbol, prediction_data in prediction_rows:
                try:
                    ml_predictions[symbol] = json.loads(prediction_data)
                except Exception:
                    pass
            if ml_predictions:
                state['ml_predictions'] = ml_predictions
            positions = []
            for item in position_rows:
                try:
                    positions.append(json.loads(item[0]))
                except Exception:
                    continue
            state['positions'] = positions
            pending_orders = {}
            for order_id, order_data in order_rows:
                try:
                    pending_orders[str(order_id)] = json.loads(order_data)
                except Exception:
                    continue
            state['pending_orders'] = pending_orders
            trailing_stops = {}
            for symbol, stop_data in stop_rows:
                try:
                    trailing_stops[symbol] = json.loads(stop_data)
                except Exception:
                    continue
            state['trailing_stops'] = trailing_stops
            state['symbol_cooldowns'] = {
                symbol: cooldown_until
                for symbol, cooldown_until in cooldown_rows
            }
            exit_recommendations = {}
            for symbol, recommendation_data in exit_rows:
                try:
                    exit_recommendations[symbol] = json.loads(recommendation_data)
                except Exception:
                    continue
            state['exit_recommendations'] = exit_recommendations
            if journal_rows:
                journal = []
                for item in journal_rows:
                    try:
                        journal.append(json.loads(item[0]))
                    except Exception:
                        continue
                state['decision_journal'] = journal
            return state
        except Exception:
            return None

    def save_bot_state(self, state, key='paper'):
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
            now = datetime.now().isoformat()
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """
                    INSERT INTO bot_state
                    (mode, paper_balance, initial_balance, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(mode) DO UPDATE SET
                        paper_balance = excluded.paper_balance,
                        initial_balance = excluded.initial_balance,
                        updated_at = excluded.updated_at
                    """,
                    (
                        key,
                        self._clean(clean_state.get('paper_balance')),
                        self._clean(clean_state.get('initial_balance')),
                        now,
                        now,
                    )
                )
                conn.execute("DELETE FROM bot_positions WHERE mode = ?", (key,))
                for idx, position in enumerate(positions):
                    if not isinstance(position, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_positions
                        (mode, idx, symbol, side, amount, price, status, order_id,
                         timestamp, closed_at, sell_price, fee, fee_rate,
                         position_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            idx,
                            position.get('symbol'),
                            position.get('side'),
                            self._clean(position.get('amount')),
                            self._clean(position.get('price')),
                            position.get('status'),
                            str(position.get('order_id')) if position.get('order_id') is not None else None,
                            position.get('timestamp'),
                            position.get('closed_at'),
                            self._clean(position.get('sell_price')),
                            self._clean(position.get('fee')),
                            self._clean(position.get('fee_rate')),
                            json.dumps(position, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_pending_orders WHERE mode = ?", (key,))
                for order_id, order_data in pending_orders.items():
                    if not isinstance(order_data, dict):
                        continue
                    order = order_data.get('order') if isinstance(order_data.get('order'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_pending_orders
                        (mode, order_id, symbol, side, order_type, amount, price,
                         status, created_at, order_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            str(order_id),
                            order_data.get('symbol') or order.get('symbol'),
                            order_data.get('side') or order.get('side'),
                            order_data.get('type') or order.get('type'),
                            self._clean(order_data.get('amount') or order.get('amount')),
                            self._clean(order_data.get('price') or order.get('price')),
                            order_data.get('status') or order.get('status'),
                            order_data.get('timestamp') or order_data.get('created_at') or order.get('timestamp'),
                            json.dumps(order_data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_trailing_stops WHERE mode = ?", (key,))
                for symbol, stop_data in trailing_stops.items():
                    if not isinstance(stop_data, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_trailing_stops
                        (mode, symbol, stop_price, highest_price, buy_price,
                         trailing_percent, initial_trailing_percent,
                         breakeven_active, resistance_price, stop_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            self._clean(stop_data.get('stop_price')),
                            self._clean(stop_data.get('highest_price')),
                            self._clean(stop_data.get('buy_price')),
                            self._clean(stop_data.get('trailing_percent')),
                            self._clean(stop_data.get('initial_trailing_percent')),
                            1 if stop_data.get('breakeven_active') else 0,
                            self._clean(stop_data.get('resistance_price')),
                            json.dumps(stop_data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_symbol_cooldowns WHERE mode = ?", (key,))
                for symbol, cooldown_until in symbol_cooldowns.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_symbol_cooldowns
                        (mode, symbol, cooldown_until, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, symbol, self._clean(cooldown_until), now)
                    )
                conn.execute("DELETE FROM bot_exit_recommendations WHERE mode = ?", (key,))
                for symbol, recommendation in exit_recommendations.items():
                    if not isinstance(recommendation, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_exit_recommendations
                        (mode, symbol, decision, continuation_score, net_pnl_pct,
                         reason, recommendation_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            recommendation.get('decision'),
                            self._clean(recommendation.get('continuation_score')),
                            self._clean(recommendation.get('net_pnl_pct')),
                            recommendation.get('reason'),
                            json.dumps(recommendation, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_market_context WHERE mode = ?", (key,))
                for symbol, data in market_context.items():
                    if not isinstance(data, dict):
                        data = {}
                    reversal = data.get('reversal') if isinstance(data.get('reversal'), dict) else {}
                    falling = data.get('falling_knife') if isinstance(data.get('falling_knife'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_market_context
                        (mode, symbol, symbol_regime, btc_regime, bear_mode,
                         confidence_bonus, reversal_confirmed, falling_knife_active,
                         context_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            data.get('symbol_regime'),
                            data.get('btc_regime'),
                            1 if data.get('bear_mode') else 0,
                            self._clean(data.get('confidence_bonus')),
                            1 if reversal.get('confirmed') else 0,
                            1 if falling.get('is_falling') else 0,
                            json.dumps(data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM ml_live_predictions WHERE mode = ?", (key,))
                for symbol, data in ml_predictions.items():
                    if not isinstance(data, dict):
                        data = {}
                    exit_forecast = data.get('exit_forecast') if isinstance(data.get('exit_forecast'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO ml_live_predictions
                        (mode, symbol, p_win, p_continue, recommendation,
                         min_probability, min_p_continue, exit_decision,
                         exit_reason, entry_price, prediction_ts,
                         prediction_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            data.get('p_win') if isinstance(data, dict) else None,
                            data.get('p_continue') or exit_forecast.get('p_continue'),
                            data.get('recommendation') if isinstance(data, dict) else None,
                            data.get('min_probability') if isinstance(data, dict) else None,
                            data.get('min_p_continue') or exit_forecast.get('min_p_continue'),
                            data.get('exit_decision') or exit_forecast.get('decision'),
                            data.get('exit_reason') or exit_forecast.get('reason'),
                            self._clean(data.get('price') or data.get('entry_price') or exit_forecast.get('entry_price')),
                            data.get('timestamp') if isinstance(data, dict) else None,
                            json.dumps(data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_decision_journal WHERE mode = ?", (key,))
                for idx, entry in enumerate(decision_journal):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_decision_journal
                        (mode, idx, timestamp, symbol, action, allowed, reason, entry_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            idx,
                            entry.get('timestamp') if isinstance(entry, dict) else None,
                            entry.get('symbol') if isinstance(entry, dict) else None,
                            entry.get('action') if isinstance(entry, dict) else None,
                            1 if isinstance(entry, dict) and entry.get('allowed') else 0 if isinstance(entry, dict) and 'allowed' in entry else None,
                            entry.get('reason') if isinstance(entry, dict) else None,
                            json.dumps(entry, ensure_ascii=False),
                            now,
                        )
                    )
                conn.commit()
            return True
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return False

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

    def _migrate_bot_state_tables(self, conn):
        try:
            old_sections = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_state_sections'"
            ).fetchone()
            if old_sections:
                for mode, section, section_data, updated_at in conn.execute(
                    "SELECT mode, section, section_data, updated_at FROM bot_state_sections"
                ).fetchall():
                    try:
                        data = json.loads(section_data)
                    except Exception:
                        data = {}
                    if section == 'market_context' and isinstance(data, dict):
                        conn.execute("DELETE FROM bot_market_context WHERE mode = ?", (mode,))
                        for symbol, context in data.items():
                            if not isinstance(context, dict):
                                context = {}
                            reversal = context.get('reversal') if isinstance(context.get('reversal'), dict) else {}
                            falling = context.get('falling_knife') if isinstance(context.get('falling_knife'), dict) else {}
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO bot_market_context
                                (mode, symbol, symbol_regime, btc_regime, bear_mode,
                                 confidence_bonus, reversal_confirmed,
                                 falling_knife_active, context_data, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    mode,
                                    symbol,
                                    context.get('symbol_regime'),
                                    context.get('btc_regime'),
                                    1 if context.get('bear_mode') else 0,
                                    self._clean(context.get('confidence_bonus')),
                                    1 if reversal.get('confirmed') else 0,
                                    1 if falling.get('is_falling') else 0,
                                    json.dumps(context, ensure_ascii=False),
                                    updated_at,
                                )
                            )
                    elif section == 'ml_predictions' and isinstance(data, dict):
                        conn.execute("DELETE FROM ml_live_predictions WHERE mode = ?", (mode,))
                        for symbol, prediction in data.items():
                            if not isinstance(prediction, dict):
                                prediction = {}
                            exit_forecast = prediction.get('exit_forecast') if isinstance(prediction.get('exit_forecast'), dict) else {}
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO ml_live_predictions
                                (mode, symbol, p_win, p_continue, recommendation,
                                 min_probability, min_p_continue, exit_decision,
                                 exit_reason, entry_price, prediction_ts,
                                 prediction_data, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    mode,
                                    symbol,
                                    prediction.get('p_win') if isinstance(prediction, dict) else None,
                                    prediction.get('p_continue') or exit_forecast.get('p_continue'),
                                    prediction.get('recommendation') if isinstance(prediction, dict) else None,
                                    prediction.get('min_probability') if isinstance(prediction, dict) else None,
                                    prediction.get('min_p_continue') or exit_forecast.get('min_p_continue'),
                                    prediction.get('exit_decision') or exit_forecast.get('decision'),
                                    prediction.get('exit_reason') or exit_forecast.get('reason'),
                                    self._clean(prediction.get('price') or prediction.get('entry_price') or exit_forecast.get('entry_price')),
                                    prediction.get('timestamp') if isinstance(prediction, dict) else None,
                                    json.dumps(prediction, ensure_ascii=False),
                                    updated_at,
                                )
                            )

            bot_state_columns = [row[1] for row in conn.execute('PRAGMA table_info(bot_state)')]
            if 'state_key' not in bot_state_columns or 'value_data' not in bot_state_columns:
                return
            modes = [row[0] for row in conn.execute("SELECT DISTINCT mode FROM bot_state").fetchall()]
            for key in modes:
                state = {}
                for state_key, value_data in conn.execute(
                    "SELECT state_key, value_data FROM bot_state WHERE mode = ?",
                    (key,)
                ).fetchall():
                    try:
                        state[state_key] = json.loads(value_data)
                    except Exception:
                        state[state_key] = value_data
                if not any(name in state for name in (
                    'support_touch_filter', 'market_context', 'ml_predictions',
                    'decision_journal', 'positions', 'pending_orders',
                    'trailing_stops', 'symbol_cooldowns', 'exit_recommendations'
                )):
                    continue
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
                ) = self._split_bot_state(state)
                now = datetime.now().isoformat()
                conn.execute("DELETE FROM bot_state WHERE mode = ?", (key,))
                for state_key, value in clean_state.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_state
                        (mode, state_key, value_data, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, state_key, json.dumps(value, ensure_ascii=False), now)
                    )
                conn.execute("DELETE FROM bot_positions WHERE mode = ?", (key,))
                for idx, position in enumerate(positions):
                    if not isinstance(position, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_positions
                        (mode, idx, symbol, side, amount, price, status, order_id,
                         timestamp, closed_at, sell_price, fee, fee_rate,
                         position_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            idx,
                            position.get('symbol'),
                            position.get('side'),
                            self._clean(position.get('amount')),
                            self._clean(position.get('price')),
                            position.get('status'),
                            str(position.get('order_id')) if position.get('order_id') is not None else None,
                            position.get('timestamp'),
                            position.get('closed_at'),
                            self._clean(position.get('sell_price')),
                            self._clean(position.get('fee')),
                            self._clean(position.get('fee_rate')),
                            json.dumps(position, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_pending_orders WHERE mode = ?", (key,))
                for order_id, order_data in pending_orders.items():
                    if not isinstance(order_data, dict):
                        continue
                    order = order_data.get('order') if isinstance(order_data.get('order'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_pending_orders
                        (mode, order_id, symbol, side, order_type, amount, price,
                         status, created_at, order_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            str(order_id),
                            order_data.get('symbol') or order.get('symbol'),
                            order_data.get('side') or order.get('side'),
                            order_data.get('type') or order.get('type'),
                            self._clean(order_data.get('amount') or order.get('amount')),
                            self._clean(order_data.get('price') or order.get('price')),
                            order_data.get('status') or order.get('status'),
                            order_data.get('timestamp') or order_data.get('created_at') or order.get('timestamp'),
                            json.dumps(order_data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_trailing_stops WHERE mode = ?", (key,))
                for symbol, stop_data in trailing_stops.items():
                    if not isinstance(stop_data, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_trailing_stops
                        (mode, symbol, stop_price, highest_price, buy_price,
                         trailing_percent, initial_trailing_percent,
                         breakeven_active, resistance_price, stop_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            self._clean(stop_data.get('stop_price')),
                            self._clean(stop_data.get('highest_price')),
                            self._clean(stop_data.get('buy_price')),
                            self._clean(stop_data.get('trailing_percent')),
                            self._clean(stop_data.get('initial_trailing_percent')),
                            1 if stop_data.get('breakeven_active') else 0,
                            self._clean(stop_data.get('resistance_price')),
                            json.dumps(stop_data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_symbol_cooldowns WHERE mode = ?", (key,))
                for symbol, cooldown_until in symbol_cooldowns.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_symbol_cooldowns
                        (mode, symbol, cooldown_until, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, symbol, self._clean(cooldown_until), now)
                    )
                conn.execute("DELETE FROM bot_exit_recommendations WHERE mode = ?", (key,))
                for symbol, recommendation in exit_recommendations.items():
                    if not isinstance(recommendation, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_exit_recommendations
                        (mode, symbol, decision, continuation_score, net_pnl_pct,
                         reason, recommendation_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            recommendation.get('decision'),
                            self._clean(recommendation.get('continuation_score')),
                            self._clean(recommendation.get('net_pnl_pct')),
                            recommendation.get('reason'),
                            json.dumps(recommendation, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_market_context WHERE mode = ?", (key,))
                for symbol, data in market_context.items():
                    if not isinstance(data, dict):
                        data = {}
                    reversal = data.get('reversal') if isinstance(data.get('reversal'), dict) else {}
                    falling = data.get('falling_knife') if isinstance(data.get('falling_knife'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_market_context
                        (mode, symbol, symbol_regime, btc_regime, bear_mode,
                         confidence_bonus, reversal_confirmed, falling_knife_active,
                         context_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            data.get('symbol_regime'),
                            data.get('btc_regime'),
                            1 if data.get('bear_mode') else 0,
                            self._clean(data.get('confidence_bonus')),
                            1 if reversal.get('confirmed') else 0,
                            1 if falling.get('is_falling') else 0,
                            json.dumps(data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM ml_live_predictions WHERE mode = ?", (key,))
                for symbol, data in ml_predictions.items():
                    if not isinstance(data, dict):
                        data = {}
                    exit_forecast = data.get('exit_forecast') if isinstance(data.get('exit_forecast'), dict) else {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO ml_live_predictions
                        (mode, symbol, p_win, p_continue, recommendation,
                         min_probability, min_p_continue, exit_decision,
                         exit_reason, entry_price, prediction_ts,
                         prediction_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            data.get('p_win') if isinstance(data, dict) else None,
                            data.get('p_continue') or exit_forecast.get('p_continue'),
                            data.get('recommendation') if isinstance(data, dict) else None,
                            data.get('min_probability') if isinstance(data, dict) else None,
                            data.get('min_p_continue') or exit_forecast.get('min_p_continue'),
                            data.get('exit_decision') or exit_forecast.get('decision'),
                            data.get('exit_reason') or exit_forecast.get('reason'),
                            self._clean(data.get('price') or data.get('entry_price') or exit_forecast.get('entry_price')),
                            data.get('timestamp') if isinstance(data, dict) else None,
                            json.dumps(data, ensure_ascii=False),
                            now,
                        )
                    )
                conn.execute("DELETE FROM bot_decision_journal WHERE mode = ?", (key,))
                for idx, entry in enumerate(decision_journal):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_decision_journal
                        (mode, idx, timestamp, symbol, action, allowed, reason, entry_data, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            idx,
                            entry.get('timestamp') if isinstance(entry, dict) else None,
                            entry.get('symbol') if isinstance(entry, dict) else None,
                            entry.get('action') if isinstance(entry, dict) else None,
                            1 if isinstance(entry, dict) and entry.get('allowed') else 0 if isinstance(entry, dict) and 'allowed' in entry else None,
                            entry.get('reason') if isinstance(entry, dict) else None,
                            json.dumps(entry, ensure_ascii=False),
                            now,
                        )
                    )
        except Exception:
            pass

    def _insert_open_entry(self, conn, event):
        conn.execute(
            """
            INSERT OR REPLACE INTO ml_open_entries
            (symbol, entry_id, opened_at, order_id, price, amount)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('symbol'),
                event.get('entry_id'),
                event.get('timestamp'),
                event.get('order_id'),
                event.get('price'),
                event.get('amount'),
            )
        )

    def _insert_exit_decision(self, conn, event):
        conn.execute(
            """
            INSERT OR REPLACE INTO ml_exit_decisions
            (event_id, timestamp, mode, symbol, entry_id, decision, reason,
             current_price, entry_p_win, continuation_score, p_continue,
             net_pnl_pct, duration_minutes, features_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('event_id'),
                event.get('timestamp'),
                event.get('mode'),
                event.get('symbol'),
                event.get('entry_id'),
                event.get('decision'),
                event.get('reason'),
                event.get('current_price'),
                event.get('entry_p_win'),
                event.get('continuation_score'),
                event.get('p_continue'),
                event.get('net_pnl_pct'),
                event.get('duration_minutes'),
                json.dumps(event.get('features') or {}, ensure_ascii=False),
            )
        )
        self._insert_feature_values(conn, 'ml_exit_feature_values', event.get('event_id'), event.get('features') or {})

    def _insert_trade_outcome(self, conn, event):
        conn.execute(
            """
            INSERT OR REPLACE INTO ml_trade_outcomes
            (event_id, timestamp, mode, symbol, entry_id, sell_price, buy_price,
             amount, pnl, pnl_pct, hold_time, reason, order_id, label_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('event_id'),
                event.get('timestamp'),
                event.get('mode'),
                event.get('symbol'),
                event.get('entry_id'),
                event.get('sell_price'),
                event.get('buy_price'),
                event.get('amount'),
                event.get('pnl'),
                event.get('pnl_pct'),
                event.get('hold_time'),
                event.get('reason'),
                event.get('order_id'),
                event.get('label_status'),
            )
        )
        if event.get('entry_id'):
            conn.execute(
                "DELETE FROM ml_open_entries WHERE symbol = ?",
                (event.get('symbol'),)
            )

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

    def _insert_telegram_message(self, conn, event):
        conn.execute(
            """
            INSERT OR REPLACE INTO telegram_messages
            (event_id, timestamp, telegram_ts, message_id, direction, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('event_id'),
                event.get('timestamp'),
                event.get('telegram_ts'),
                event.get('message_id'),
                event.get('direction'),
                event.get('text'),
            )
        )

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
        compact_summary = self._compact_support_touch_summary(summary)

        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute("DELETE FROM support_touch_results WHERE run_id = ?", (run_id,))
                stored_at = datetime.now().isoformat()
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    symbol = item.get('symbol')
                    if not symbol:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO support_touch_results
                        (run_id, generated_at, exchange, run_timeframe, candle_limit,
                         run_total_trades, run_total_wins, run_win_rate,
                         run_total_pnl_percent, settings_data, symbol, timeframe,
                         candles, trades, wins, losses, win_rate, total_pnl_percent,
                         avg_pnl_percent, best_trade_percent, worst_trade_percent,
                         result_data, stored_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            generated_at,
                            summary.get('exchange'),
                            settings.get('timeframe'),
                            settings.get('limit'),
                            total_trades,
                            total_wins,
                            win_rate,
                            total_pnl,
                            json.dumps(settings, ensure_ascii=False),
                            symbol,
                            item.get('timeframe'),
                            item.get('candles'),
                            item.get('trades'),
                            item.get('wins'),
                            item.get('losses'),
                            item.get('win_rate'),
                            item.get('total_pnl_percent'),
                            item.get('avg_pnl_percent'),
                            item.get('best_trade_percent'),
                            item.get('worst_trade_percent'),
                            json.dumps(self._clean(self._compact_support_touch_result(item)), ensure_ascii=False),
                            stored_at,
                        )
                    )
                conn.commit()
            return run_id
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
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
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ml_model_metadata
                    (model_id, trained_at, model_path, n_features, exit_n_features,
                     metadata_data, stored_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_id,
                        trained_at,
                        model_path,
                        metadata.get('n_features'),
                        metadata.get('exit_n_features'),
                        json.dumps(self._clean(metadata), ensure_ascii=False),
                        datetime.now().isoformat(),
                    )
                )
                conn.execute("DELETE FROM ml_feature_importances WHERE model_id = ?", (model_id,))
                self._insert_feature_importance_rows(conn, model_id, 'entry', metadata.get('feature_importance'))
                self._insert_feature_importance_rows(conn, model_id, 'exit', metadata.get('exit_feature_importance'))
                conn.commit()
            return model_id
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return None

    def get_latest_support_touch_backtest(self):
        try:
            with self._lock:
                run = self._get_conn().execute(
                    """
                    SELECT run_id, generated_at, exchange, run_timeframe, candle_limit,
                           run_total_trades, run_total_wins, run_win_rate,
                           run_total_pnl_percent, settings_data, stored_at
                    FROM support_touch_results
                    ORDER BY datetime(generated_at) DESC, datetime(stored_at) DESC
                    LIMIT 1
                    """
                ).fetchone()
                if not run:
                    return {}
                rows = self._get_conn().execute(
                    """
                    SELECT result_data FROM support_touch_results
                    WHERE run_id = ?
                    ORDER BY symbol
                    """,
                    (run[0],)
                ).fetchall()
            settings = json.loads(run[9]) if run[9] else {}
            return {
                'generated_at': run[1],
                'exchange': run[2],
                'settings': settings,
                'results': [json.loads(row[0]) for row in rows if row and row[0]],
                'summary': {
                    'total_trades': run[5],
                    'total_wins': run[6],
                    'win_rate': run[7],
                    'total_pnl_percent': run[8],
                }
            }
        except Exception:
            return {}

    def get_latest_ml_model_metadata(self):
        try:
            with self._lock:
                row = self._get_conn().execute(
                    """
                    SELECT metadata_data FROM ml_model_metadata
                    ORDER BY datetime(trained_at) DESC, datetime(stored_at) DESC
                    LIMIT 1
                    """
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except Exception:
            return {}

    def _insert_feature_importance_rows(self, conn, model_id, scope, items):
        if not isinstance(items, list):
            return
        for rank, item in enumerate(items, start=1):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO ml_feature_importances
                (model_id, scope, rank, feature_name, importance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (model_id, scope, rank, str(item[0]), float(item[1] or 0.0))
            )

    def record_decision_journal(self, entry, mode='paper', max_entries=5000):
        if not isinstance(entry, dict):
            return False
        try:
            now = datetime.now().isoformat()
            with self._lock:
                conn = self._get_conn()
                row = conn.execute(
                    "SELECT COALESCE(MAX(idx), -1) + 1 FROM bot_decision_journal WHERE mode = ?",
                    (mode,)
                ).fetchone()
                idx = int(row[0] if row else 0)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_decision_journal
                    (mode, idx, timestamp, symbol, action, allowed, reason,
                     entry_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mode,
                        idx,
                        entry.get('timestamp'),
                        entry.get('symbol'),
                        entry.get('action'),
                        1 if entry.get('allowed') else 0 if 'allowed' in entry else None,
                        entry.get('reason'),
                        json.dumps(entry, ensure_ascii=False),
                        now,
                        now,
                    )
                )
                overflow = conn.execute(
                    "SELECT COUNT(*) FROM bot_decision_journal WHERE mode = ?",
                    (mode,)
                ).fetchone()[0] - int(max_entries)
                if overflow > 0:
                    conn.execute(
                        """
                        DELETE FROM bot_decision_journal
                        WHERE mode = ? AND idx IN (
                            SELECT idx FROM bot_decision_journal
                            WHERE mode = ?
                            ORDER BY idx ASC
                            LIMIT ?
                        )
                        """,
                        (mode, mode, overflow)
                    )
                conn.commit()
            return True
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return False

    def get_decision_journal(self, mode='paper', limit=80):
        try:
            with self._lock:
                rows = self._get_conn().execute(
                    """
                    SELECT entry_data FROM bot_decision_journal
                    WHERE mode = ?
                    ORDER BY idx DESC
                    LIMIT ?
                    """,
                    (mode, int(limit))
                ).fetchall()
            items = []
            for row in reversed(rows):
                try:
                    items.append(json.loads(row[0]))
                except Exception:
                    continue
            return items
        except Exception:
            return []

    def count_decision_journal(self, mode='paper'):
        try:
            with self._lock:
                return int(self._get_conn().execute(
                    "SELECT COUNT(*) FROM bot_decision_journal WHERE mode = ?",
                    (mode,)
                ).fetchone()[0])
        except Exception:
            return 0

    def add_bot_command(self, action, symbol=None, seconds=None, payload=None):
        try:
            now_ts = time.time()
            now = datetime.now().isoformat()
            command_id = self._new_id('cmd')
            data = dict(payload or {})
            data.update({
                'command_id': command_id,
                'action': action,
                'symbol': symbol,
                'seconds': seconds,
                'timestamp': now_ts,
            })
            with self._lock:
                self._get_conn().execute(
                    """
                    INSERT OR REPLACE INTO bot_commands
                    (command_id, action, symbol, seconds, status, command_ts,
                     command_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (command_id, action, symbol, self._clean(seconds), now_ts, json.dumps(data, ensure_ascii=False), now, now)
                )
                self._get_conn().commit()
            return command_id
        except Exception:
            return None

    def claim_pending_bot_commands(self, limit=100):
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute('BEGIN IMMEDIATE')
                rows = conn.execute(
                    """
                    SELECT command_id, command_data FROM bot_commands
                    WHERE status = 'pending'
                    ORDER BY command_ts ASC
                    LIMIT ?
                    """,
                    (int(limit),)
                ).fetchall()
                ids = [row[0] for row in rows]
                if ids:
                    now = datetime.now().isoformat()
                    conn.executemany(
                        "UPDATE bot_commands SET status='claimed', updated_at=? WHERE command_id=?",
                        [(now, command_id) for command_id in ids]
                    )
                conn.commit()
            commands = []
            for _, data in rows:
                try:
                    commands.append(json.loads(data))
                except Exception:
                    continue
            return commands
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return []

    def record_crypto_score(self, symbol, score, price):
        try:
            now = datetime.now().isoformat()
            score_id = self._new_id('score')
            with self._lock:
                self._get_conn().execute(
                    """
                    INSERT OR REPLACE INTO crypto_score_history
                    (score_id, timestamp, symbol, score, price, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (score_id, now, symbol, int(score), self._clean(price), now, now)
                )
                self._get_conn().commit()
            return score_id
        except Exception:
            return None

    def get_crypto_scores(self, symbol, since_iso=None, limit=2000):
        try:
            params = [symbol]
            where = "symbol = ?"
            if since_iso:
                where += " AND datetime(timestamp) >= datetime(?)"
                params.append(since_iso)
            params.append(int(limit))
            with self._lock:
                rows = self._get_conn().execute(
                    f"""
                    SELECT timestamp, symbol, score, price
                    FROM crypto_score_history
                    WHERE {where}
                    ORDER BY datetime(timestamp) ASC
                    LIMIT ?
                    """,
                    params
                ).fetchall()
            return [
                {'timestamp': r[0], 'symbol': r[1], 'score': r[2], 'price': r[3]}
                for r in rows
            ]
        except Exception:
            return []

    def save_live_status(self, status):
        if not isinstance(status, dict):
            return False
        try:
            now = datetime.now().isoformat()
            key = 'latest'
            symbols = status.get('symbols') if isinstance(status.get('symbols'), dict) else {}
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_live_status
                    (key, timestamp, exchange, connected, running, mode_name,
                     reconnect_attempts, queue_size, queue_maxsize, worker_alive,
                     ws_thread_alive, status_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        status.get('timestamp'),
                        status.get('exchange'),
                        1 if status.get('connected') else 0,
                        1 if status.get('running') else 0,
                        status.get('mode'),
                        status.get('reconnect_attempts'),
                        status.get('queue_size'),
                        status.get('queue_maxsize'),
                        1 if status.get('worker_alive') else 0,
                        1 if status.get('ws_thread_alive') else 0,
                        json.dumps(status, ensure_ascii=False),
                        now,
                        now,
                    )
                )
                conn.execute("DELETE FROM bot_live_status_symbols WHERE status_key = ?", (key,))
                for symbol, data in symbols.items():
                    if not isinstance(data, dict):
                        data = {}
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_live_status_symbols
                        (status_key, symbol, price, tick_count, kline_count,
                         last_tick, last_analysis, symbol_data, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            symbol,
                            self._clean(data.get('price')),
                            data.get('tick_count'),
                            data.get('kline_count'),
                            data.get('last_tick'),
                            data.get('last_analysis'),
                            json.dumps(data, ensure_ascii=False),
                            now,
                            now,
                        )
                    )
                conn.commit()
            return True
        except Exception:
            try:
                self._get_conn().rollback()
            except Exception:
                pass
            return False

    def get_live_status(self):
        try:
            with self._lock:
                row = self._get_conn().execute(
                    "SELECT status_data FROM bot_live_status WHERE key='latest'"
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except Exception:
            return {}

    def save_daily_stats(self, stats):
        if not isinstance(stats, dict):
            return False
        try:
            now = datetime.now().isoformat()
            stat_date = str(stats.get('date') or datetime.now().strftime('%Y-%m-%d'))
            with self._lock:
                self._get_conn().execute(
                    """
                    INSERT OR REPLACE INTO bot_daily_stats
                    (stat_date, trades_count, total_loss, total_profit,
                     emergency_stop, stats_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stat_date,
                        int(stats.get('trades_count') or 0),
                        self._clean(stats.get('total_loss') or 0),
                        self._clean(stats.get('total_profit') or 0),
                        1 if stats.get('emergency_stop') else 0,
                        json.dumps(stats, ensure_ascii=False),
                        now,
                        now,
                    )
                )
                self._get_conn().commit()
            return True
        except Exception:
            return False

    def load_daily_stats(self, stat_date=None):
        try:
            stat_date = stat_date or datetime.now().strftime('%Y-%m-%d')
            with self._lock:
                row = self._get_conn().execute(
                    "SELECT stats_data FROM bot_daily_stats WHERE stat_date = ?",
                    (stat_date,)
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except Exception:
            return {}

    def load_open_entries(self):
        try:
            with self._lock:
                rows = self._get_conn().execute(
                    """
                    SELECT symbol, entry_id, opened_at, order_id, price, amount
                    FROM ml_open_entries
                    """
                ).fetchall()
            return {
                row[0]: {
                    'entry_id': row[1],
                    'symbol': row[0],
                    'opened_at': row[2],
                    'order_id': row[3],
                    'price': row[4],
                    'amount': row[5],
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
