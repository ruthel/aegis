import ast
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update

from core.db_orm import (
    Base,
    BotAppState,
    BotCommand,
    BotDailyStat,
    Crypto,
    BotProcess,
    BotState,
    Account,
    Balance,
    Order,
    Fill,
    LedgerEntry,
    MlExitRecommendation,
    CryptoScore,
    MlFeatureImportance,
    DecisionLog,
    MlFeatureValue,
    MlOpenEntry,
    MlModelMetadata,
    MlSizingRecommendation,
    SysAudit,
    MlTradeOutcome,
    SupportTouchResult,
    Notification,
    GovernanceLog,
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
                self._migrate_table_name(conn, 'crypto_score_history', 'crypto_scores')
                self._migrate_live_symbols_to_cryptos(conn)
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
                self._ensure_cryptos_columns(conn)
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
                self._ensure_column(conn, 'bot_daily_stats', 'winning_trades_count', 'INTEGER')
                self._ensure_column(conn, 'bot_daily_stats', 'losing_trades_count', 'INTEGER')
                self._ensure_column(conn, 'decision_logs', 'slippage_pct', 'REAL')
                self._ensure_column(conn, 'decision_logs', 'spread_pct', 'REAL')
                self._ensure_column(conn, 'decision_logs', 'order_type', 'TEXT')
                self._ensure_column(conn, 'decision_logs', 'duration_ms', 'REAL')
                self._ensure_column(conn, 'ml_open_entries', 'expected_price', 'REAL')
                self._ensure_column(conn, 'ml_open_entries', 'requested_price', 'REAL')
                self._ensure_column(conn, 'ml_open_entries', 'slippage_pct', 'REAL')
                self._ensure_column(conn, 'ml_open_entries', 'spread_pct', 'REAL')
                self._ensure_column(conn, 'ml_open_entries', 'order_type', 'TEXT')
                self._ensure_column(conn, 'ml_open_entries', 'duration_ms', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'p_continue', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'raw_sizing_factor', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'min_position_size_usd', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'max_position_size_usd', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'exposure_before_usd', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'exposure_after_usd', 'REAL')
                self._ensure_column(conn, 'ml_sizing_recommendations', 'max_exposure_usd', 'REAL')
                self._ensure_column(conn, 'ml_trade_outcomes', 'slippage_pct', 'REAL')
                self._ensure_column(conn, 'ml_trade_outcomes', 'spread_pct', 'REAL')
                # Renommer la table ml_raw_events en sys_audit si besoin
                try:
                    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
                    if 'ml_raw_events' in tables and 'sys_audit' not in tables:
                        conn.execute("ALTER TABLE ml_raw_events RENAME TO sys_audit;")
                    conn.execute("DROP TABLE IF EXISTS ml_raw_events;")
                except Exception:
                    pass
                conn.execute('DROP TABLE IF EXISTS support_touch_trade_results')
                Base.metadata.create_all(self._Session.kw['bind'])
                self._migrate_live_symbols_to_cryptos(conn)
                self._ensure_cryptos_columns(conn)
                self._ensure_ml_exit_recommendations_columns(conn)
                self._migrate_exit_fields_to_ml_exit_recommendations(conn)
                self._migrate_bot_exit_recommendations_to_ml_exit_recommendations(conn)
                self._migrate_pending_ml_exit_rows(conn)
                self._backfill_ml_exit_recommendation_context(conn)
                self._drop_live_symbol_exit_columns(conn)
                conn.execute("DROP TABLE IF EXISTS pending_orders")
                try:
                    conn.execute("DROP TABLE IF EXISTS telegram_messages;")
                    conn.execute("DROP TABLE IF EXISTS ml_raw_events;")
                    conn.execute("DROP TABLE IF EXISTS ml_decisions;")
                    conn.execute("DROP TABLE IF EXISTS bot_decision_journal;")
                    conn.execute("DROP TABLE IF EXISTS bot_decision_metrics;")
                    conn.execute("DROP TABLE IF EXISTS bot_symbol_cooldowns;")
                    conn.execute("DROP TABLE IF EXISTS bot_market_context;")
                    conn.execute("DROP TABLE IF EXISTS ml_live_predictions;")
                except Exception:
                    pass
                self._migrate_app_state_to_bot_state(conn)
                self._migrate_runtime_rows_out_of_bot_state(conn)
                self._compact_bot_state_schema(conn)
                self._migrate_live_status_schema(conn)
                conn.execute(
                    """
                    DROP INDEX IF EXISTS idx_live_symbols_symbol
                    """
                )
                conn.execute(
                    """
                    DROP INDEX IF EXISTS idx_crypto_score_symbol_time
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cryptos_symbol
                    ON cryptos (symbol)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_crypto_scores_symbol_time
                    ON crypto_scores (symbol, timestamp)
                    """
                )
                self._migrate_runtime_payload_schema(conn)
                self._migrate_ml_payload_schema(conn)
                self._migrate_bot_state_tables(conn)
                conn.execute('DROP TABLE IF EXISTS bot_state_sections')
                self._ensure_audit_columns(conn)
                self._migrate_ml_decisions_table(conn)
                self._migrate_ml_feature_values_table(conn)
                self._merge_live_symbol_aliases(conn)
                self._sync_accounting_from_bot_positions(conn, mode='paper')
                self._backfill_ledger_balances(conn)
                self._drop_retired_tables(conn)
                conn.commit()
        except Exception as exc:
            print(f"⚠️ SQLite init failed: {type(exc).__name__}: {exc}")

    def _account_id(self, mode='paper'):
        exchange = os.getenv('EXCHANGE', 'kraken').lower()
        return f'{mode}:{exchange}:USD'

    def _split_symbol_assets(self, symbol):
        value = self._normalize_live_symbol(symbol)
        if '/' in value:
            base, quote = value.split('/', 1)
            return base, quote
        return value, 'USD'

    def _normalize_asset_code(self, asset):
        value = str(asset or '').upper()
        aliases = {
            'XXBT': 'BTC',
            'XBT': 'BTC',
            'XETH': 'ETH',
            'ZUSD': 'USD',
            'ZCAD': 'CAD',
            'ZUSDT': 'USDT',
        }
        return aliases.get(value, value)

    def _map_exchange_ledger_type(self, entry):
        raw_type = str((entry or {}).get('type') or '').lower()
        direction = str((entry or {}).get('direction') or '').lower()
        info = (entry or {}).get('info') if isinstance((entry or {}).get('info'), dict) else {}
        raw_ref_type = str(info.get('type') or info.get('subtype') or '').lower()
        text = f'{raw_type} {direction} {raw_ref_type}'
        if 'deposit' in text:
            return 'deposit'
        if 'withdraw' in text:
            return 'withdrawal'
        if 'fee' in text:
            return 'fee'
        if 'trade' in text:
            return 'trade'
        if 'transfer' in text or 'staking' in text:
            return 'transfer'
        if 'margin' in text or 'adjust' in text or 'correction' in text:
            return 'adjustment'
        return raw_type or 'external_ledger'

    def _insert_ledger_entry(self, conn, ledger_id, account_id, entry_ts, entry_type, asset, amount, order_id=None, fill_id=None, symbol=None, source_position_idx=None, description=None, source='state_accounting', balance_after=None):
        now = now_iso()
        clean_amount = self._clean(amount) or 0.0
        if balance_after is not None:
            computed_balance_after = float(balance_after)
        else:
            previous_balance = conn.execute(
                """
                SELECT balance_after
                FROM ledger_entries
                WHERE account_id=? AND asset=? AND ledger_id<>?
                ORDER BY entry_ts DESC, created_at DESC, ledger_id DESC
                LIMIT 1
                """,
                (account_id, asset, ledger_id),
            ).fetchone()
            if previous_balance and previous_balance[0] is not None:
                computed_balance_after = float(previous_balance[0] or 0.0) + float(clean_amount)
            else:
                existing_total = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM ledger_entries
                    WHERE account_id=? AND asset=? AND ledger_id<>?
                    """,
                    (account_id, asset, ledger_id),
                ).fetchone()
                computed_balance_after = float(existing_total[0] or 0.0) + float(clean_amount)
        conn.execute(
            """
            INSERT OR REPLACE INTO ledger_entries
            (ledger_id, account_id, entry_ts, entry_type, asset, amount, balance_after,
             order_id, fill_id, symbol, source, source_position_idx, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger_id,
                account_id,
                entry_ts or now,
                entry_type,
                asset,
                clean_amount,
                computed_balance_after,
                order_id,
                fill_id,
                symbol,
                source,
                source_position_idx,
                description,
                now,
                now,
            ),
        )

    def _ensure_account(self, conn, mode='paper', initial_balance=None):
        account_id = self._account_id(mode)
        now = now_iso()
        existing = conn.execute(
            "SELECT created_at, initial_balance FROM accounts WHERE account_id=?",
            (account_id,),
        ).fetchone()
        seed_balance = float(
            initial_balance
            if initial_balance is not None
            else existing[1] if existing and existing[1] is not None
            else os.getenv('PAPER_BALANCE', '1000')
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO accounts
            (account_id, mode, exchange, base_currency, name, status, initial_balance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                mode,
                os.getenv('EXCHANGE', 'kraken').lower(),
                'USD',
                f'{mode} account',
                'active',
                seed_balance,
                existing[0] if existing and existing[0] else now,
                now,
            ),
        )
        return account_id

    def _recalculate_balances(self, conn, account_id):
        now = now_iso()
        locked_assets = {
            asset: float(amount or 0.0)
            for asset, amount in conn.execute(
                """
                SELECT substr(symbol, 1, instr(symbol || '/', '/') - 1) AS asset,
                       COALESCE(SUM(amount), 0)
                FROM orders
                WHERE account_id=? AND side='sell' AND status='open'
                GROUP BY asset
                """,
                (account_id,),
            ).fetchall()
            if asset
        }
        totals = {
            asset: float(total or 0.0)
            for asset, total in conn.execute(
                """
                SELECT asset, COALESCE(SUM(amount), 0)
                FROM ledger_entries
                WHERE account_id=?
                GROUP BY asset
                """,
                (account_id,),
            ).fetchall()
        }
        conn.execute("DELETE FROM balances WHERE account_id=?", (account_id,))
        for asset, total in sorted(totals.items()):
            locked = min(max(locked_assets.get(asset, 0.0), 0.0), max(total, 0.0)) if asset != 'USD' else 0.0
            free = total - locked
            conn.execute(
                """
                INSERT OR REPLACE INTO balances
                (account_id, asset, free, locked, total, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, asset, free, locked, total, now, now),
            )

    def _backfill_ledger_balances(self, conn):
        try:
            rows = conn.execute(
                """
                SELECT ledger_id, account_id, asset, amount
                FROM ledger_entries
                ORDER BY account_id, asset, entry_ts, created_at, ledger_id
                """
            ).fetchall()
            running = {}
            for ledger_id, account_id, asset, amount in rows:
                key = (account_id, asset)
                next_balance = running.get(key, 0.0) + float(amount or 0.0)
                running[key] = next_balance
                conn.execute(
                    "UPDATE ledger_entries SET balance_after=? WHERE ledger_id=?",
                    (next_balance, ledger_id),
                )
        except Exception:
            pass

    def record_account_deposit(self, amount, asset='USD', mode='paper', description='deposit'):
        return self._record_account_cash_movement(amount, asset, mode, 'deposit', description)

    def record_account_withdrawal(self, amount, asset='USD', mode='paper', description='withdrawal'):
        return self._record_account_cash_movement(-abs(float(amount or 0.0)), asset, mode, 'withdrawal', description)

    def _record_account_cash_movement(self, amount, asset='USD', mode='paper', entry_type='deposit', description=None):
        try:
            amount = float(amount or 0.0)
            if amount == 0:
                return None
            asset = str(asset or 'USD').upper()
            now = now_iso()
            with self._lock:
                conn = self._get_conn()
                account_id = self._ensure_account(conn, mode)
                if amount < 0:
                    current = conn.execute(
                        "SELECT free FROM balances WHERE account_id=? AND asset=?",
                        (account_id, asset),
                    ).fetchone()
                    if current and float(current[0] or 0.0) + amount < -1e-9:
                        return None
                ledger_id = f"{account_id}:{entry_type}:{asset}:{uuid.uuid4().hex}"
                self._insert_ledger_entry(
                    conn,
                    ledger_id,
                    account_id,
                    now,
                    entry_type,
                    asset,
                    amount,
                    description=description or entry_type,
                    source='accounting_transaction',
                )
                if asset == 'USD':
                    state = conn.execute(
                        "SELECT paper_balance, created_at FROM bot_state WHERE mode=?",
                        (mode,),
                    ).fetchone()
                    previous_balance = float(state[0] if state and state[0] is not None else 0.0)
                    created_at = state[1] if state and state[1] else now
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_state
                        (mode, paper_balance, initial_balance, created_at, updated_at)
                        VALUES (?, ?, COALESCE((SELECT initial_balance FROM bot_state WHERE mode=?), ?), ?, ?)
                        """,
                        (
                            mode,
                            previous_balance + amount,
                            mode,
                            previous_balance + amount,
                            created_at,
                            now,
                        ),
                    )
                self._recalculate_balances(conn, account_id)
                conn.commit()
            return ledger_id
        except Exception:
            return None

    def record_order_transaction(self, symbol, side, amount, price=None, order_type='market', status='open', order_id=None, mode='paper', source='accounting_transaction', recalculate_balances=True):
        try:
            now = now_iso()
            symbol = self._normalize_live_symbol(symbol)
            side = str(side or '').lower()
            status = str(status or 'open').lower()
            order_id = str(order_id or f"{source}_{side}_{symbol.replace('/', '')}_{uuid.uuid4().hex[:12]}")
            with self._lock:
                conn = self._get_conn()
                account_id = self._ensure_account(conn, mode)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO orders
                    (account_id, order_id, symbol, side, order_type, status, amount, price,
                     filled_amount, avg_fill_price, source, source_position_idx,
                     opened_at, closed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT filled_amount FROM orders WHERE account_id=? AND order_id=?), 0),
                            COALESCE((SELECT avg_fill_price FROM orders WHERE account_id=? AND order_id=?), NULL),
                            ?, NULL,
                            COALESCE((SELECT opened_at FROM orders WHERE account_id=? AND order_id=?), ?),
                            CASE WHEN ? IN ('filled', 'closed', 'cancelled') THEN COALESCE((SELECT closed_at FROM orders WHERE account_id=? AND order_id=?), ?) ELSE NULL END,
                            COALESCE((SELECT created_at FROM orders WHERE account_id=? AND order_id=?), ?),
                            ?)
                    """,
                    (
                        account_id, order_id, symbol, side, order_type, status, self._clean(amount), self._clean(price),
                        account_id, order_id,
                        account_id, order_id,
                        source,
                        account_id, order_id, now,
                        status, account_id, order_id, now,
                        account_id, order_id, now,
                        now,
                    ),
                )
                if recalculate_balances:
                    self._recalculate_balances(conn, account_id)
                conn.commit()
            return order_id
        except Exception:
            return None

    def record_fill_transaction(self, order_id, symbol, side, amount, price, fee_amount=None, fee_asset=None, mode='paper', source='accounting_transaction', write_ledger=True, recalculate_balances=True):
        try:
            now = now_iso()
            symbol = self._normalize_live_symbol(symbol)
            base, quote = self._split_symbol_assets(symbol)
            side = str(side or '').lower()
            amount = float(amount or 0.0)
            price = float(price or 0.0)
            if amount <= 0 or price <= 0 or side not in {'buy', 'sell'}:
                return None
            fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0
            fee_amount = float(fee_amount if fee_amount is not None else amount * price * fee_rate)
            fee_asset = str(fee_asset or quote).upper()
            order_id = str(order_id or f"{source}_{side}_{symbol.replace('/', '')}_{uuid.uuid4().hex[:12]}")
            fill_id = f"{self._account_id(mode)}:fill:{uuid.uuid4().hex}"
            with self._lock:
                conn = self._get_conn()
                account_id = self._ensure_account(conn, mode)
                existing_order = conn.execute(
                    "SELECT order_id FROM orders WHERE account_id=? AND order_id=?",
                    (account_id, order_id),
                ).fetchone()
                if not existing_order:
                    conn.execute(
                        """
                        INSERT INTO orders
                        (account_id, order_id, symbol, side, order_type, status, amount, price,
                         filled_amount, avg_fill_price, source, source_position_idx,
                         opened_at, closed_at, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 'market', 'open', ?, ?, 0, NULL, ?, NULL, ?, NULL, ?, ?)
                        """,
                        (account_id, order_id, symbol, side, amount, price, source, now, now, now),
                    )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fills
                    (fill_id, account_id, order_id, symbol, side, amount, price, fee_amount,
                     fee_asset, source, source_position_idx, fill_ts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (fill_id, account_id, order_id, symbol, side, amount, price, fee_amount, fee_asset, source, now, now, now),
                )
                gross = amount * price
                usd_delta = 0.0
                if write_ledger:
                    if side == 'buy':
                        self._insert_ledger_entry(conn, f'{fill_id}:quote', account_id, now, 'trade', quote, -gross, order_id, fill_id, symbol, description='buy_quote_debit', source=source)
                        self._insert_ledger_entry(conn, f'{fill_id}:base', account_id, now, 'trade', base, amount, order_id, fill_id, symbol, description='buy_base_credit', source=source)
                        if fee_amount:
                            self._insert_ledger_entry(conn, f'{fill_id}:fee', account_id, now, 'fee', fee_asset, -fee_amount, order_id, fill_id, symbol, description='buy_fee', source=source)
                        usd_delta = -gross - (fee_amount if fee_asset == quote == 'USD' else 0.0)
                    else:
                        self._insert_ledger_entry(conn, f'{fill_id}:base', account_id, now, 'trade', base, -amount, order_id, fill_id, symbol, description='sell_base_debit', source=source)
                        self._insert_ledger_entry(conn, f'{fill_id}:quote', account_id, now, 'trade', quote, gross, order_id, fill_id, symbol, description='sell_quote_credit', source=source)
                        if fee_amount:
                            self._insert_ledger_entry(conn, f'{fill_id}:fee', account_id, now, 'fee', fee_asset, -fee_amount, order_id, fill_id, symbol, description='sell_fee', source=source)
                        usd_delta = gross - (fee_amount if fee_asset == quote == 'USD' else 0.0)
                conn.execute(
                    """
                    UPDATE orders
                    SET status='filled',
                        filled_amount=COALESCE(filled_amount, 0) + ?,
                        avg_fill_price=?,
                        closed_at=COALESCE(closed_at, ?),
                        updated_at=?
                    WHERE account_id=? AND order_id=?
                    """,
                    (amount, price, now, now, account_id, order_id),
                )
                if side == 'sell':
                    conn.execute(
                        """
                        UPDATE orders
                        SET status='cancelled',
                            closed_at=COALESCE(closed_at, ?),
                            updated_at=?
                        WHERE account_id=?
                          AND symbol=?
                          AND side='sell'
                          AND status='open'
                          AND order_id<>?
                        """,
                        (now, now, account_id, symbol, order_id),
                    )
                if write_ledger and quote == 'USD' and mode == 'paper':
                    state = conn.execute(
                        "SELECT paper_balance, created_at FROM bot_state WHERE mode=?",
                        (mode,),
                    ).fetchone()
                    previous_balance = float(state[0] if state and state[0] is not None else 0.0)
                    created_at = state[1] if state and state[1] else now
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO bot_state
                        (mode, paper_balance, initial_balance, created_at, updated_at)
                        VALUES (?, ?, COALESCE((SELECT initial_balance FROM bot_state WHERE mode=?), ?), ?, ?)
                        """,
                        (
                            mode,
                            previous_balance + usd_delta,
                            mode,
                            previous_balance + usd_delta,
                            created_at,
                            now,
                        ),
                    )
                if recalculate_balances:
                    self._recalculate_balances(conn, account_id)
                conn.commit()
            return fill_id
        except Exception:
            return None

    def cancel_open_orders(self, symbol=None, side=None, mode='paper', source=None):
        try:
            now = now_iso()
            with self._lock:
                conn = self._get_conn()
                account_id = self._ensure_account(conn, mode)
                clauses = ["account_id=?", "status='open'"]
                params = [account_id]
                if symbol:
                    clauses.append("symbol=?")
                    params.append(self._normalize_live_symbol(symbol))
                if side:
                    clauses.append("side=?")
                    params.append(str(side).lower())
                if source:
                    clauses.append("source=?")
                    params.append(source)
                sql = f"""
                    UPDATE orders
                    SET status='cancelled', closed_at=COALESCE(closed_at, ?), updated_at=?
                    WHERE {' AND '.join(clauses)}
                """
                conn.execute(sql, [now, now, *params])
                self._recalculate_balances(conn, account_id)
                conn.commit()
            return True
        except Exception:
            return False

    def _sync_accounting_from_positions(self, conn, positions, mode='paper', paper_balance=None, initial_balance=None, state_created_at=None):
        try:
            account_id = self._account_id(mode)
            now = now_iso()
            state = conn.execute(
                "SELECT paper_balance, initial_balance, created_at, updated_at FROM bot_state WHERE mode=?",
                (mode,),
            ).fetchone()
            paper_balance = float(
                paper_balance
                if paper_balance is not None
                else state[0] if state and state[0] is not None
                else 0.0
            )
            initial_balance = float(
                initial_balance
                if initial_balance is not None
                else state[1] if state and state[1] is not None
                else os.getenv('PAPER_BALANCE', '1000')
            )
            state_created_at = state_created_at or (state[2] if state else now)

            conn.execute(
                """
                INSERT OR REPLACE INTO accounts
                (account_id, mode, exchange, base_currency, name, status, initial_balance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM accounts WHERE account_id=?), ?), ?)
                """,
                (
                    account_id,
                    mode,
                    os.getenv('EXCHANGE', 'kraken').lower(),
                    'USD',
                    f'{mode} account',
                    'active',
                    initial_balance,
                    account_id,
                    state_created_at or now,
                    now,
                ),
            )

            for table in ('ledger_entries', 'fills', 'orders'):
                conn.execute(
                    f"DELETE FROM {table} WHERE account_id=? AND source IN ('bot_positions_mirror', 'state_accounting')",
                    (account_id,),
                )
            conn.execute("DELETE FROM balances WHERE account_id=?", (account_id,))

            self._insert_ledger_entry(
                conn,
                f'{account_id}:seed',
                account_id,
                state_created_at or now,
                'deposit',
                'USD',
                initial_balance,
                description='paper_seed_from_bot_state',
            )

            locked_assets = {}
            for idx, position in enumerate(positions or []):
                if not isinstance(position, dict):
                    continue
                symbol = position.get('symbol')
                side = position.get('side')
                amount = position.get('amount')
                price = position.get('price')
                status = position.get('status')
                raw_order_id = position.get('order_id')
                timestamp = position.get('timestamp')
                closed_at = position.get('closed_at')
                fee = position.get('fee')
                fee_rate = position.get('fee_rate')
                created_at = position.get('created_at')
                updated_at = position.get('updated_at')
                symbol = self._normalize_live_symbol(symbol)
                base, quote = self._split_symbol_assets(symbol)
                side = str(side or '').lower()
                status_text = str(status or '').lower()
                amount = float(amount or 0.0)
                price = float(price or 0.0)
                fee_rate = float(fee_rate if fee_rate is not None else (float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100.0))
                order_id = f"{raw_order_id or 'position'}_{idx}"
                order_status = 'open' if status_text == 'opened' else 'filled' if status_text in {'executed', 'filled'} else status_text or 'unknown'
                order_type = 'limit' if side == 'sell' and status_text == 'opened' else 'market'
                filled_amount = amount if order_status == 'filled' else 0.0

                conn.execute(
                    """
                    INSERT OR REPLACE INTO orders
                    (account_id, order_id, symbol, side, order_type, status, amount, price,
                     filled_amount, avg_fill_price, source, source_position_idx,
                     opened_at, closed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        order_id,
                        symbol,
                        side,
                        order_type,
                        order_status,
                        amount,
                        price,
                        filled_amount,
                        price if filled_amount else None,
                        'state_accounting',
                        idx,
                        timestamp,
                        closed_at,
                        created_at or timestamp or now,
                        updated_at or now,
                    ),
                )

                if side == 'sell' and order_status == 'open':
                    locked_assets[base] = locked_assets.get(base, 0.0) + amount

                if order_status != 'filled' or amount <= 0 or price <= 0:
                    continue

                fill_id = f'{account_id}:fill:{idx}'
                gross = amount * price
                fee_amount = float(fee) if fee is not None and side == 'buy' else gross * fee_rate
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fills
                    (fill_id, account_id, order_id, symbol, side, amount, price, fee_amount,
                     fee_asset, source, source_position_idx, fill_ts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fill_id,
                        account_id,
                        order_id,
                        symbol,
                        side,
                        amount,
                        price,
                        fee_amount,
                        quote,
                        'state_accounting',
                        idx,
                        timestamp or closed_at or now,
                        created_at or timestamp or now,
                        updated_at or now,
                    ),
                )

                if side == 'buy':
                    self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:quote', account_id, timestamp, 'trade', quote, -gross, order_id, fill_id, symbol, idx, 'buy_quote_debit')
                    self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:base', account_id, timestamp, 'trade', base, amount, order_id, fill_id, symbol, idx, 'buy_base_credit')
                    if fee_amount:
                        self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:fee', account_id, timestamp, 'fee', quote, -fee_amount, order_id, fill_id, symbol, idx, 'buy_fee')
                elif side == 'sell':
                    self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:base', account_id, timestamp, 'trade', base, -amount, order_id, fill_id, symbol, idx, 'sell_base_debit')
                    self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:quote', account_id, timestamp, 'trade', quote, gross, order_id, fill_id, symbol, idx, 'sell_quote_credit')
                    if fee_amount:
                        self._insert_ledger_entry(conn, f'{account_id}:ledger:{idx}:fee', account_id, timestamp, 'fee', quote, -fee_amount, order_id, fill_id, symbol, idx, 'sell_fee')

            totals = {
                asset: float(total or 0.0)
                for asset, total in conn.execute(
                    """
                    SELECT asset, COALESCE(SUM(amount), 0)
                    FROM ledger_entries
                    WHERE account_id=?
                    GROUP BY asset
                    """,
                    (account_id,),
                ).fetchall()
            }
            usd_diff = paper_balance - totals.get('USD', 0.0)
            if abs(usd_diff) >= 0.005:
                self._insert_ledger_entry(
                    conn,
                    f'{account_id}:reconcile:USD',
                    account_id,
                    now,
                    'adjustment',
                    'USD',
                    usd_diff,
                    description='balance_reconciliation_to_bot_state',
                )
                totals['USD'] = totals.get('USD', 0.0) + usd_diff

            for asset, total in sorted(totals.items()):
                locked = min(max(locked_assets.get(asset, 0.0), 0.0), max(total, 0.0)) if asset != 'USD' else 0.0
                free = total - locked
                conn.execute(
                    """
                    INSERT OR REPLACE INTO balances
                    (account_id, asset, free, locked, total, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM balances WHERE account_id=? AND asset=?), ?), ?)
                    """,
                    (account_id, asset, free, locked, total, account_id, asset, now, now),
                )
        except Exception:
            pass

    def _sync_accounting_from_bot_positions(self, conn, mode='paper'):
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_positions'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute(
                """
                SELECT symbol, side, amount, price, status, order_id, timestamp,
                       closed_at, fee, fee_rate, position_size_usd, position_size_crypto,
                       risk_reward_ratio, target_price, reason, created_at, updated_at
                FROM bot_positions
                WHERE mode=?
                ORDER BY idx ASC
                """,
                (mode,),
            ).fetchall()
            positions = []
            for row in rows:
                (
                    symbol, side, amount, price, status, order_id, timestamp,
                    closed_at, fee, fee_rate, position_size_usd, position_size_crypto,
                    risk_reward_ratio, target_price, reason, created_at, updated_at
                ) = row
                positions.append({
                    'symbol': symbol,
                    'side': side,
                    'amount': amount,
                    'price': price,
                    'status': status,
                    'order_id': order_id,
                    'timestamp': timestamp,
                    'closed_at': closed_at,
                    'fee': fee,
                    'fee_rate': fee_rate,
                    'position_size_usd': position_size_usd,
                    'position_size_crypto': position_size_crypto,
                    'risk_reward_ratio': risk_reward_ratio,
                    'target_price': target_price,
                    'reason': reason,
                    'created_at': created_at,
                    'updated_at': updated_at,
                })
            if positions:
                self._sync_accounting_from_positions(conn, positions, mode=mode)
        except Exception:
            pass

    def _drop_retired_tables(self, conn):
        for table in (
            'bot_live_status',
            'bot_live_status_symbols',
            'bot_live_status_subscriptions',
            'bot_decision_metrics',
            'bot_decision_journal',
            'bot_market_context',
            'ml_live_predictions',
            'bot_symbol_cooldowns',
            'ml_decisions',
            'ml_raw_events',
            'telegram_messages',
            'pending_orders',
            'bot_exit_recommendations',
            'bot_positions',
            'bot_trailing_stops',
        ):
            try:
                conn.execute(f'DROP TABLE IF EXISTS {table}')
            except Exception:
                pass

    def _migrate_ml_decisions_table(self, conn):
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            if 'ml_decisions' in tables and 'decision_logs' not in tables:
                conn.execute("ALTER TABLE ml_decisions RENAME TO decision_logs;")
            elif 'ml_decisions' in tables and 'decision_logs' in tables:
                self._copy_common_columns(conn, 'ml_decisions', 'decision_logs')
                conn.execute("DROP TABLE IF EXISTS ml_decisions;")

            conn.execute("DROP TABLE IF EXISTS bot_decision_journal;")
            conn.execute("DROP TABLE IF EXISTS bot_decision_metrics;")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS decision_logs (
                    event_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    timestamp TEXT,
                    mode TEXT,
                    symbol TEXT,
                    entry_id TEXT,
                    decision TEXT,
                    reason TEXT,
                    price REAL,
                    confidence REAL,
                    min_confidence REAL,
                    p_win REAL,
                    p_continue REAL,
                    label_status TEXT,
                    net_pnl_pct REAL,
                    duration_minutes REAL
                )
            """)
            for column_name, column_type in (
                ('slippage_pct', 'REAL'),
                ('spread_pct', 'REAL'),
                ('order_type', 'TEXT'),
                ('duration_ms', 'REAL'),
            ):
                self._ensure_column(conn, 'decision_logs', column_name, column_type)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_logs_type_sym ON decision_logs (action_type, symbol, timestamp)")
            conn.execute("DROP TABLE IF EXISTS ml_decisions;")
            
            has_entries = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ml_entry_decisions'").fetchone()
            if has_entries:
                conn.execute("""
                    INSERT OR IGNORE INTO decision_logs (
                        event_id, action_type, timestamp, mode, symbol, decision, reason, price, confidence, p_win, min_confidence, label_status
                    )
                    SELECT event_id, 'ENTRY', timestamp, mode, symbol, decision, reason, price, p_win, p_win, min_p_win, label_status
                    FROM ml_entry_decisions
                """)

            has_exits = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ml_exit_decisions'").fetchone()
            if has_exits:
                conn.execute("""
                    INSERT OR IGNORE INTO decision_logs (
                        event_id, action_type, timestamp, mode, symbol, entry_id, decision, reason, price, confidence, p_continue, net_pnl_pct, duration_minutes
                    )
                    SELECT event_id, 'EXIT', timestamp, mode, symbol, entry_id, decision, reason, current_price, COALESCE(p_continue, continuation_score), p_continue, net_pnl_pct, duration_minutes
                    FROM ml_exit_decisions
                """)

            # Supprimer physiquement les anciennes tables devenues obsolètes
            conn.execute("DROP TABLE IF EXISTS ml_entry_decisions")
            conn.execute("DROP TABLE IF EXISTS ml_exit_decisions")
            conn.execute("DROP TABLE IF EXISTS ml_decisions")
        except Exception:
            pass

    def _migrate_ml_feature_values_table(self, conn):
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ml_feature_values (
                    event_id TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    feature_value REAL,
                    feature_text TEXT,
                    PRIMARY KEY (event_id, feature_name)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_feature_name ON ml_feature_values (feature_name)")

            has_entry_feats = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ml_entry_feature_values'").fetchone()
            if has_entry_feats:
                conn.execute("INSERT OR IGNORE INTO ml_feature_values SELECT * FROM ml_entry_feature_values")

            has_exit_feats = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ml_exit_feature_values'").fetchone()
            if has_exit_feats:
                conn.execute("INSERT OR IGNORE INTO ml_feature_values SELECT * FROM ml_exit_feature_values")

            conn.execute("DROP TABLE IF EXISTS ml_entry_feature_values")
            conn.execute("DROP TABLE IF EXISTS ml_exit_feature_values")
        except Exception:
            pass

    def _orm_session(self):
        return self._Session()

    def _quote_ident(self, name):
        return '"' + str(name).replace('"', '""') + '"'

    def _normalize_live_symbol(self, symbol):
        value = str(symbol or '').strip().upper().replace('XBT', 'BTC')
        if not value:
            return ''
        if '/' in value:
            base, quote = value.split('/', 1)
            return f'{base}/{quote}'
        for quote in ('USDT', 'USDC', 'USD', 'EUR'):
            if value.endswith(quote) and len(value) > len(quote):
                return f'{value[:-len(quote)]}/{quote}'
        return value

    def _normalize_symbol_map(self, data):
        if not isinstance(data, dict):
            return {}
        normalized = {}
        for symbol, value in data.items():
            normalized_symbol = self._normalize_live_symbol(symbol)
            if normalized_symbol:
                normalized[normalized_symbol] = value
        return normalized

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

    def _migrate_live_symbols_to_cryptos(self, conn):
        try:
            old_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_symbols'"
            ).fetchone()
            new_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cryptos'"
            ).fetchone()
            if old_exists and not new_exists:
                conn.execute("ALTER TABLE live_symbols RENAME TO cryptos")
            elif old_exists and new_exists:
                self._copy_common_columns(conn, 'live_symbols', 'cryptos')
                conn.execute("DROP TABLE IF EXISTS live_symbols")
            conn.execute("DROP INDEX IF EXISTS idx_live_symbols_symbol")
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

    def _copy_common_columns(self, conn, source_table, target_table):
        try:
            source_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (source_table,)
            ).fetchone()
            target_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (target_table,)
            ).fetchone()
            if not source_exists or not target_exists:
                return
            source_columns = {row[1] for row in conn.execute(f'PRAGMA table_info({self._quote_ident(source_table)})')}
            target_columns = [row[1] for row in conn.execute(f'PRAGMA table_info({self._quote_ident(target_table)})')]
            common_columns = [column for column in target_columns if column in source_columns]
            if not common_columns:
                return
            column_sql = ', '.join(self._quote_ident(column) for column in common_columns)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {self._quote_ident(target_table)} ({column_sql})
                SELECT {column_sql}
                FROM {self._quote_ident(source_table)}
                """
            )
        except Exception:
            pass

    def _merge_live_symbol_aliases(self, conn):
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cryptos'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute("SELECT * FROM cryptos").fetchall()
            columns = [row[1] for row in conn.execute("PRAGMA table_info(cryptos)")]
            for row in rows:
                data = dict(zip(columns, row))
                source_symbol = data.get('symbol')
                normalized_symbol = self._normalize_live_symbol(source_symbol)
                mode = data.get('mode') or 'paper'
                if not normalized_symbol or normalized_symbol == source_symbol:
                    continue
                target = conn.execute(
                    "SELECT * FROM cryptos WHERE mode=? AND symbol=?",
                    (mode, normalized_symbol)
                ).fetchone()
                if not target:
                    conn.execute(
                        "UPDATE cryptos SET symbol=? WHERE mode=? AND symbol=?",
                        (normalized_symbol, mode, source_symbol)
                    )
                    continue
                target_data = dict(zip(columns, target))
                assignments = []
                values = []
                for column in columns:
                    if column in ('mode', 'symbol'):
                        continue
                    source_value = data.get(column)
                    target_value = target_data.get(column)
                    if target_value is None and source_value is not None:
                        assignments.append(f'{self._quote_ident(column)}=?')
                        values.append(source_value)
                if assignments:
                    values.extend([mode, normalized_symbol])
                    conn.execute(
                        f"UPDATE cryptos SET {', '.join(assignments)} WHERE mode=? AND symbol=?",
                        values
                    )
                conn.execute(
                    "DELETE FROM cryptos WHERE mode=? AND symbol=?",
                    (mode, source_symbol)
                )
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

    def _ensure_cryptos_columns(self, conn):
        columns = (
            ('price', 'REAL'),
            ('bid', 'REAL'),
            ('ask', 'REAL'),
            ('spread_percent', 'REAL'),
            ('high', 'REAL'),
            ('low', 'REAL'),
            ('high_24h', 'REAL'),
            ('low_24h', 'REAL'),
            ('volume_24h', 'REAL'),
            ('volume_usd', 'REAL'),
            ('quote_volume', 'REAL'),
            ('candle_high', 'REAL'),
            ('candle_low', 'REAL'),
            ('candle_volume', 'REAL'),
            ('candle_volume_usd', 'REAL'),
            ('trend_score', 'INTEGER'),
            ('ws_connected', 'INTEGER'),
            ('cooldown_until', 'REAL'),
            ('symbol_regime', 'TEXT'),
            ('btc_regime', 'TEXT'),
            ('bear_mode', 'INTEGER'),
            ('symbol_bear', 'INTEGER'),
            ('btc_bear', 'INTEGER'),
            ('trade_multiplier', 'REAL'),
            ('btc_momentum_percent', 'REAL'),
            ('symbol_momentum_percent', 'REAL'),
            ('confidence_bonus', 'REAL'),
            ('reversal_confirmed', 'INTEGER'),
            ('falling_knife_active', 'INTEGER'),
            ('p_win', 'REAL'),
            ('recommendation', 'TEXT'),
            ('min_probability', 'REAL'),
            ('prediction_ts', 'TEXT'),
            ('created_at', 'TEXT'),
            ('updated_at', 'TEXT'),
        )
        for column_name, column_type in columns:
            self._ensure_column(conn, 'cryptos', column_name, column_type)

    def _ensure_ml_exit_recommendations_columns(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_exit_recommendations (
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry_price REAL,
                p_continue REAL,
                min_p_continue REAL,
                exit_decision TEXT,
                exit_reason TEXT,
                net_pnl_pct REAL,
                duration_minutes REAL,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (mode, symbol)
            )
            """
        )
        for column_name, column_type in (
            ('entry_price', 'REAL'),
            ('p_continue', 'REAL'),
            ('min_p_continue', 'REAL'),
            ('exit_decision', 'TEXT'),
            ('exit_reason', 'TEXT'),
            ('net_pnl_pct', 'REAL'),
            ('duration_minutes', 'REAL'),
            ('created_at', 'TEXT'),
            ('updated_at', 'TEXT'),
        ):
            self._ensure_column(conn, 'ml_exit_recommendations', column_name, column_type)

    def _migrate_exit_fields_to_ml_exit_recommendations(self, conn):
        try:
            live_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cryptos'"
            ).fetchone()
            if not live_exists:
                return
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cryptos)")}
            exit_columns = {'entry_price', 'p_continue', 'min_p_continue', 'exit_decision', 'exit_reason'}
            if not exit_columns.intersection(columns):
                return
            select_expr = {
                'entry_price': 'entry_price' if 'entry_price' in columns else 'NULL',
                'p_continue': 'p_continue' if 'p_continue' in columns else 'NULL',
                'min_p_continue': 'min_p_continue' if 'min_p_continue' in columns else 'NULL',
                'exit_decision': 'exit_decision' if 'exit_decision' in columns else 'NULL',
                'exit_reason': 'exit_reason' if 'exit_reason' in columns else 'NULL',
            }
            rows = conn.execute(
                f"""
                SELECT mode, symbol,
                       {select_expr['entry_price']},
                       {select_expr['p_continue']},
                       {select_expr['min_p_continue']},
                       {select_expr['exit_decision']},
                       {select_expr['exit_reason']},
                       created_at, updated_at
                FROM cryptos
                WHERE {select_expr['entry_price']} IS NOT NULL
                   OR {select_expr['p_continue']} IS NOT NULL
                   OR {select_expr['min_p_continue']} IS NOT NULL
                   OR {select_expr['exit_decision']} IS NOT NULL
                   OR {select_expr['exit_reason']} IS NOT NULL
                """
            ).fetchall()
            for row in rows:
                mode, symbol, entry_price, p_continue, min_p_continue, exit_decision, exit_reason, created_at, updated_at = row
                normalized_symbol = self._normalize_live_symbol(symbol)
                if not normalized_symbol:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ml_exit_recommendations
                    (mode, symbol, entry_price, p_continue, min_p_continue,
                     exit_decision, exit_reason, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mode or 'paper',
                        normalized_symbol,
                        entry_price,
                        p_continue,
                        min_p_continue,
                        exit_decision,
                        exit_reason,
                        created_at,
                        updated_at,
                    )
                )
        except Exception:
            pass

    def _migrate_bot_exit_recommendations_to_ml_exit_recommendations(self, conn):
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_exit_recommendations'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute(
                """
                SELECT mode, symbol, decision, continuation_score, net_pnl_pct,
                       reason, created_at, updated_at
                FROM bot_exit_recommendations
                """
            ).fetchall()
            for row in rows:
                mode, symbol, decision, continuation_score, net_pnl_pct, reason, created_at, updated_at = row
                normalized_symbol = self._normalize_live_symbol(symbol)
                if not normalized_symbol:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ml_exit_recommendations
                    (mode, symbol, p_continue, exit_decision, exit_reason,
                     net_pnl_pct, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mode or 'paper',
                        normalized_symbol,
                        continuation_score,
                        decision,
                        reason,
                        net_pnl_pct,
                        created_at,
                        updated_at,
                    )
                )
            conn.execute("DROP TABLE IF EXISTS bot_exit_recommendations")
        except Exception:
            pass

    def _migrate_pending_ml_exit_rows(self, conn):
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_orders'"
            ).fetchone()
            if not exists:
                return
            columns = {row[1] for row in conn.execute("PRAGMA table_info(pending_orders)")}
            if 'source' not in columns:
                return
            rows = conn.execute(
                """
                SELECT mode, symbol, entry_price, p_continue, min_p_continue,
                       exit_decision, exit_reason, net_pnl_pct, duration_minutes,
                       created_at, updated_at
                FROM pending_orders
                WHERE source='ml_exit_recommendation'
                   OR status='pending_ml_exit'
                """
            ).fetchall()
            for row in rows:
                (
                    mode, symbol, entry_price, p_continue, min_p_continue,
                    exit_decision, exit_reason, net_pnl_pct, duration_minutes,
                    created_at, updated_at,
                ) = row
                normalized_symbol = self._normalize_live_symbol(symbol)
                if not normalized_symbol:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ml_exit_recommendations
                    (mode, symbol, entry_price, p_continue, min_p_continue,
                     exit_decision, exit_reason, net_pnl_pct, duration_minutes,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mode or 'paper',
                        normalized_symbol,
                        entry_price,
                        p_continue,
                        min_p_continue,
                        exit_decision,
                        exit_reason,
                        net_pnl_pct,
                        duration_minutes,
                        created_at,
                        updated_at,
                    )
                )
            conn.execute(
                """
                DELETE FROM pending_orders
                WHERE source='ml_exit_recommendation'
                   OR status='pending_ml_exit'
                """
            )
        except Exception:
            pass

    def _drop_live_symbol_exit_columns(self, conn):
        for column in ('entry_price', 'p_continue', 'min_p_continue', 'exit_decision', 'exit_reason'):
            self._drop_column(conn, 'cryptos', column)

    def _backfill_ml_exit_recommendation_context(self, conn):
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ml_exit_recommendations'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute(
                """
                SELECT mode, symbol, min_p_continue, exit_reason
                FROM ml_exit_recommendations
                """
            ).fetchall()
            default_min = float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0'))
            now_dt = datetime.now()
            for mode, symbol, min_p_continue, exit_reason in rows:
                mode_key = mode or 'paper'
                normalized_symbol = self._normalize_live_symbol(symbol)
                if not normalized_symbol:
                    continue
                accounting_positions = self._positions_from_accounting(conn, mode_key)
                active_positions = [p for p in accounting_positions if p.get('symbol') == normalized_symbol]
                buy_row = next(
                    (
                        p for p in reversed(active_positions)
                        if p.get('side') == 'buy' and not p.get('closed_at')
                    ),
                    None,
                )
                open_sell_exists = any(
                    p.get('side') == 'sell' and p.get('status') == 'opened'
                    for p in active_positions
                )
                if not buy_row and not open_sell_exists:
                    conn.execute(
                        "DELETE FROM ml_exit_recommendations WHERE mode=? AND symbol=?",
                        (mode_key, normalized_symbol),
                    )
                    continue

                threshold = min_p_continue
                if threshold is None:
                    reason = str(exit_reason or '')
                    marker = 'threshold_'
                    if marker in reason:
                        try:
                            threshold = float(reason.split(marker, 1)[1].split('%', 1)[0])
                        except Exception:
                            threshold = default_min
                    else:
                        threshold = default_min

                entry_price = buy_row.get('price') if buy_row else None
                duration_minutes = None
                if buy_row and buy_row.get('timestamp'):
                    try:
                        opened_at = datetime.fromisoformat(str(buy_row.get('timestamp')).replace('Z', '+00:00'))
                        if opened_at.tzinfo is not None:
                            opened_at = opened_at.astimezone().replace(tzinfo=None)
                        duration_minutes = max(0.0, (now_dt - opened_at).total_seconds() / 60.0)
                    except Exception:
                        duration_minutes = None

                conn.execute(
                    """
                    UPDATE ml_exit_recommendations
                    SET symbol=?,
                        entry_price=COALESCE(entry_price, ?),
                        min_p_continue=COALESCE(min_p_continue, ?),
                        duration_minutes=COALESCE(duration_minutes, ?),
                        updated_at=COALESCE(updated_at, ?)
                    WHERE mode=? AND symbol=?
                    """,
                    (
                        normalized_symbol,
                        entry_price,
                        threshold,
                        duration_minutes,
                        now_iso(),
                        mode_key,
                        symbol,
                    ),
                )
        except Exception:
            pass

    def _exit_threshold_from_reason(self, reason, default=None):
        threshold = default
        try:
            reason_text = str(reason or '')
            marker = 'threshold_'
            if marker in reason_text:
                threshold = float(reason_text.split(marker, 1)[1].split('%', 1)[0])
        except Exception:
            pass
        return threshold

    def _continue_probability_from_reason(self, reason):
        try:
            reason_text = str(reason or '')
            marker = 'ml_continue_'
            if marker in reason_text:
                return float(reason_text.split(marker, 1)[1].split('%', 1)[0])
        except Exception:
            pass
        return None

    def _position_duration_minutes(self, timestamp):
        if not timestamp:
            return None
        try:
            opened_at = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
            if opened_at.tzinfo is not None:
                opened_at = opened_at.astimezone().replace(tzinfo=None)
            return max(0.0, (datetime.now() - opened_at).total_seconds() / 60.0)
        except Exception:
            return None

    def _active_buy_context_by_symbol(self, positions):
        contexts = {}
        if not isinstance(positions, list):
            return contexts
        for position in positions:
            if not isinstance(position, dict):
                continue
            if position.get('side') != 'buy' or position.get('closed_at'):
                continue
            symbol = self._normalize_live_symbol(position.get('symbol'))
            if not symbol:
                continue
            contexts[symbol] = {
                'entry_price': self._clean(position.get('price')),
                'duration_minutes': self._position_duration_minutes(position.get('timestamp')),
            }
        return contexts

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

            conn.execute('DROP TABLE IF EXISTS bot_live_status_symbols')
            conn.execute('DROP TABLE IF EXISTS bot_live_status_subscriptions')
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cryptos (
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL,
                    bid REAL,
                    ask REAL,
                    spread_percent REAL,
                    high REAL,
                    low REAL,
                    high_24h REAL,
                    low_24h REAL,
                    volume_24h REAL,
                    volume_usd REAL,
                    quote_volume REAL,
                    candle_high REAL,
                    candle_low REAL,
                    candle_volume REAL,
                    candle_volume_usd REAL,
                    trend_score INTEGER,
                    ws_connected INTEGER,
                    cooldown_until REAL,
                    symbol_regime TEXT,
                    btc_regime TEXT,
                    bear_mode INTEGER,
                    symbol_bear INTEGER,
                    btc_bear INTEGER,
                    trade_multiplier REAL,
                    btc_momentum_percent REAL,
                    symbol_momentum_percent REAL,
                    confidence_bonus REAL,
                    reversal_confirmed INTEGER,
                    falling_knife_active INTEGER,
                    p_win REAL,
                    recommendation TEXT,
                    min_probability REAL,
                    prediction_ts TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (mode, symbol)
                )
                """
            )
            for row in status_rows:
                (
                    key, timestamp, exchange, connected, running, mode_name,
                    reconnect_attempts, queue_size, queue_maxsize, worker_alive,
                    ws_thread_alive, status_data, created_at, updated_at
                ) = row
                live_payload = {
                    'timestamp': timestamp,
                    'exchange': exchange,
                    'connected': bool(connected),
                    'running': bool(running),
                    'mode': mode_name,
                    'reconnect_attempts': reconnect_attempts,
                    'queue_size': queue_size,
                    'queue_maxsize': queue_maxsize,
                    'worker_alive': bool(worker_alive),
                    'ws_thread_alive': bool(ws_thread_alive),
                }
                subscribed = []
                if status_data:
                    try:
                        subscribed = json.loads(status_data).get('subscribed_symbols') or []
                    except Exception:
                        subscribed = []
                if subscribed:
                    live_payload['subscribed_symbols'] = subscribed
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_app_state
                    (state_key, state_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        'live_status',
                        json.dumps(live_payload, ensure_ascii=False),
                        created_at,
                        updated_at,
                    )
                )
                for symbol in subscribed:
                    normalized_symbol = self._normalize_live_symbol(symbol)
                    if not normalized_symbol:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO cryptos
                        (mode, symbol, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        ('paper', normalized_symbol, created_at, updated_at)
                    )
            for row in symbol_rows:
                status_key, symbol, price, tick_count, kline_count, last_tick, last_analysis, symbol_data, created_at, updated_at = row
                normalized_symbol = self._normalize_live_symbol(symbol)
                if not normalized_symbol:
                    continue
                data = {}
                if symbol_data:
                    try:
                        data = json.loads(symbol_data)
                    except Exception:
                        data = {}
                conn.execute(
                        """
                    INSERT OR REPLACE INTO cryptos
                    (mode, symbol, price, bid, ask, spread_percent,
                     high, low, high_24h, low_24h, volume_24h, volume_usd, quote_volume,
                     candle_high, candle_low, candle_volume, candle_volume_usd,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        'paper',
                        normalized_symbol,
                        self._clean(data.get('price', price)),
                        self._clean(data.get('bid')),
                        self._clean(data.get('ask')),
                        self._clean(data.get('spread_percent')),
                        self._first_clean(data.get('high'), data.get('high_24h'), data.get('candle_high')),
                        self._first_clean(data.get('low'), data.get('low_24h'), data.get('candle_low')),
                        self._first_clean(data.get('high_24h'), data.get('high')),
                        self._first_clean(data.get('low_24h'), data.get('low')),
                        self._first_clean(data.get('volume_24h'), data.get('volume')),
                        self._first_clean(
                            data.get('volume_usd'),
                            data.get('quote_volume'),
                            data.get('volume_24h_usd'),
                            self._volume_usd(data.get('volume_24h'), data.get('price', price)),
                        ),
                        self._first_clean(data.get('quote_volume'), data.get('volume_usd'), data.get('volume_24h_usd')),
                        self._first_clean(data.get('candle_high'), data.get('high')),
                        self._first_clean(data.get('candle_low'), data.get('low')),
                        self._clean(data.get('candle_volume')),
                        self._first_clean(data.get('candle_volume_usd'), self._volume_usd(data.get('candle_volume'), data.get('price', price))),
                        created_at,
                        updated_at,
                    )
                )
            conn.execute('DROP TABLE IF EXISTS bot_live_status_symbols')
            conn.execute('DROP TABLE IF EXISTS bot_live_status_subscriptions')
            conn.execute('DROP TABLE IF EXISTS bot_live_status')
        except Exception:
            pass

    def _migrate_runtime_payload_schema(self, conn):
        try:
            conn.execute("DROP TABLE IF EXISTS bot_decision_metrics")
            for table, column in (
                ('bot_commands', 'command_data'),
                ('bot_daily_stats', 'stats_data'),
                ('bot_positions', 'position_data'),
                ('bot_trailing_stops', 'stop_data'),
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
                session.merge(SysAudit(
                    event_id=event.get('event_id'),
                    event_type=event_type,
                    timestamp=event.get('timestamp'),
                    symbol=event.get('symbol'),
                    mode=event.get('mode'),
                ))

                if event_type in ('entry_decision', 'exit_decision'):
                    if self._should_store_decision_log(event):
                        self._insert_decision(session, event)
                elif event_type == 'entry_opened':
                    self._insert_open_entry(session, event)
                elif event_type == 'exit_outcome':
                    self._insert_trade_outcome(session, event)
                elif event_type == 'telegram_message':
                    self._insert_telegram_message(session, event)
                session.commit()
        except Exception:
            pass

    def _should_store_decision_log(self, event):
        event_type = event.get('event_type')
        if event_type != 'exit_decision':
            return True

        decision = str(event.get('decision') or '').upper()
        reason = str(event.get('reason') or '').lower()
        if decision == 'HOLD':
            return False
        if reason.startswith('ml_continue') or 'ml continue' in reason:
            return False
        return True

    def _insert_decision(self, session, event):
        event_type = event.get('event_type')
        action_type = 'ENTRY' if event_type == 'entry_decision' else 'EXIT'
        
        if action_type == 'ENTRY':
            p_val = event.get('p_win')
            min_p = event.get('min_p_win')
        else:
            p_val = event.get('p_continue') if event.get('p_continue') is not None else event.get('continuation_score')
            min_p = event.get('min_p_continue')

        session.merge(DecisionLog(
            event_id=event.get('event_id'),
            action_type=action_type,
            timestamp=event.get('timestamp'),
            mode=event.get('mode'),
            symbol=event.get('symbol') or '',
            entry_id=event.get('entry_id'),
            decision=event.get('decision') or '',
            reason=event.get('reason'),
            price=event.get('price') or event.get('current_price'),
            confidence=p_val,
            min_confidence=min_p,
            p_win=event.get('p_win'),
            p_continue=event.get('p_continue'),
            label_status=event.get('label_status'),
            net_pnl_pct=event.get('net_pnl_pct'),
            duration_minutes=event.get('duration_minutes'),
        ))
        # Ne stocker les 40+ features détaillées que pour les vrais événements (non-HOLD) pour préserver l'espace disque
        if event.get('decision') != 'HOLD':
            self._insert_feature_values(session, MlFeatureValue, event.get('event_id'), event.get('features') or {})

    def record_sizing_recommendation(self, **payload):
        """Journalise une recommandation de taille sans polluer le journal de decisions final."""
        try:
            now = now_iso()
            sizing_id = payload.get('sizing_id') or self._new_id('sizing')
            with self._orm_session() as session:
                session.merge(MlSizingRecommendation(
                    sizing_id=str(sizing_id),
                    timestamp=payload.get('timestamp') or now,
                    mode=payload.get('mode'),
                    symbol=payload.get('symbol') or '',
                    entry_id=payload.get('entry_id'),
                    p_win=self._clean(payload.get('p_win')),
                    p_continue=self._clean(payload.get('p_continue')),
                    base_position_size_usd=self._clean(payload.get('base_position_size_usd')),
                    raw_sizing_factor=self._clean(payload.get('raw_sizing_factor')),
                    sizing_factor=self._clean(payload.get('sizing_factor')),
                    final_position_size_usd=self._clean(payload.get('final_position_size_usd')),
                    min_position_size_usd=self._clean(payload.get('min_position_size_usd')),
                    max_position_size_usd=self._clean(payload.get('max_position_size_usd')),
                    exposure_before_usd=self._clean(payload.get('exposure_before_usd')),
                    exposure_after_usd=self._clean(payload.get('exposure_after_usd')),
                    max_exposure_usd=self._clean(payload.get('max_exposure_usd')),
                    decision=payload.get('decision'),
                    reason=payload.get('reason'),
                    risk_veto_reason=payload.get('risk_veto_reason'),
                    created_at=now,
                    updated_at=now,
                ))
                session.commit()
            return sizing_id
        except Exception as exc:
            print(f"⚠️ Erreur record_sizing_recommendation: {exc}")
            return None

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
        ok = self._save_bot_state_orm(state, key)
        transaction_source = os.getenv('ACCOUNTING_TRANSACTION_SOURCE', 'true').lower() == 'true'
        if ok and not transaction_source:
            self.refresh_accounting_mirror(key, state)
        return ok

    def refresh_accounting_mirror(self, key='paper', state=None):
        try:
            with self._lock:
                conn = self._get_conn()
                if isinstance(state, dict):
                    self._sync_accounting_from_positions(
                        conn,
                        state.get('positions') or [],
                        mode=key,
                        paper_balance=state.get('paper_balance'),
                        initial_balance=state.get('initial_balance'),
                    )
                else:
                    self._sync_accounting_from_bot_positions(conn, mode=key)
                conn.commit()
            return True
        except Exception:
            return False

    def sync_external_balances(self, balances, mode='live', source='exchange_balance'):
        """Remplace les soldes d'un compte par la verite retournee par l'exchange."""
        if mode == 'paper' or not isinstance(balances, dict):
            return False
        try:
            now = now_iso()
            clean_rows = []
            for asset, data in balances.items():
                if asset in ('free', 'used', 'total', 'info') or not isinstance(data, dict):
                    continue
                free = self._clean(data.get('free')) or 0.0
                locked = self._clean(data.get('used') if data.get('used') is not None else data.get('locked')) or 0.0
                total = self._clean(data.get('total'))
                if total is None:
                    total = free + locked
                if abs(float(free or 0.0)) < 1e-12 and abs(float(locked or 0.0)) < 1e-12 and abs(float(total or 0.0)) < 1e-12:
                    continue
                clean_rows.append((str(asset).upper(), float(free), float(locked), float(total)))
            if not clean_rows:
                return False

            with self._lock:
                conn = self._get_conn()
                account_id = self._ensure_account(conn, mode=mode, initial_balance=0.0)
                conn.execute("DELETE FROM balances WHERE account_id=?", (account_id,))
                for asset, free, locked, total in clean_rows:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO balances
                        (account_id, asset, free, locked, total, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM balances WHERE account_id=? AND asset=?), ?), ?)
                        """,
                        (account_id, asset, free, locked, total, account_id, asset, now, now),
                    )
                conn.commit()
            return True
        except Exception:
            return False

    def latest_exchange_ledger_since_ms(self, mode='live', source='kraken_ledger'):
        try:
            account_id = self._account_id(mode)
            conn = self._get_conn()
            row = conn.execute(
                """
                SELECT entry_ts
                FROM ledger_entries
                WHERE account_id=? AND source=?
                ORDER BY entry_ts DESC, created_at DESC
                LIMIT 1
                """,
                (account_id, source),
            ).fetchone()
            if not row or not row[0]:
                return None
            try:
                from datetime import datetime, timezone
                text = str(row[0]).replace('Z', '+00:00')
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return max(0, int(dt.timestamp() * 1000) - 60000)
            except Exception:
                return None
        except Exception:
            return None

    def import_exchange_ledger(self, entries, mode='live', source='kraken_ledger'):
        """Importe le ledger reel Kraken/CCXT sans deviner depuis les deltas de balance."""
        if mode == 'paper' or not entries:
            return 0
        imported = 0
        try:
            now = now_iso()
            account_id = self._account_id(mode)
            with self._lock:
                conn = self._get_conn()
                self._ensure_account(conn, mode=mode, initial_balance=0.0)
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    external_id = str(entry.get('id') or entry.get('txid') or entry.get('referenceId') or '').strip()
                    currency = self._normalize_asset_code(entry.get('currency') or entry.get('code') or entry.get('asset'))
                    if not currency:
                        continue
                    amount = self._clean(entry.get('amount'))
                    if amount is None:
                        continue
                    direction = str(entry.get('direction') or '').lower()
                    if direction in {'out', 'debit'} and amount > 0:
                        amount = -amount
                    entry_type = self._map_exchange_ledger_type(entry)
                    timestamp = entry.get('datetime') or entry.get('timestamp') or now
                    if isinstance(timestamp, (int, float)):
                        from datetime import datetime, timezone
                        timestamp = datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc).isoformat()
                    balance_after = self._clean(entry.get('after'))
                    reference_id = entry.get('referenceId') or entry.get('reference_id')
                    ledger_id = f'{account_id}:{source}:{external_id or reference_id or currency + ":" + str(timestamp) + ":" + str(amount)}'
                    exists = conn.execute(
                        "SELECT 1 FROM ledger_entries WHERE ledger_id=?",
                        (ledger_id,),
                    ).fetchone()
                    description_payload = {
                        'exchange_type': entry.get('type'),
                        'direction': entry.get('direction'),
                        'reference_id': reference_id,
                        'status': entry.get('status'),
                    }
                    self._insert_ledger_entry(
                        conn,
                        ledger_id,
                        account_id,
                        timestamp,
                        entry_type,
                        currency,
                        amount,
                        order_id=str(reference_id) if reference_id else None,
                        description=json.dumps(description_payload, ensure_ascii=False),
                        source=source,
                        balance_after=balance_after,
                    )
                    if not exists:
                        imported += 1
                self._sync_orders_from_exchange_ledger(conn, account_id, source=source)
                conn.commit()
            return imported
        except Exception:
            return imported

    def _sync_orders_from_exchange_ledger(self, conn, account_id, source='kraken_ledger'):
        """Cree les orders/fills locaux manquants depuis les paires trade du ledger exchange."""
        try:
            now = now_iso()
            tradable_assets = {'BTC', 'ETH', 'SOL', 'ADA'}
            rows = conn.execute(
                """
                SELECT order_id, MIN(entry_ts) AS entry_ts
                FROM ledger_entries
                WHERE account_id=? AND source=? AND entry_type='trade' AND order_id IS NOT NULL
                GROUP BY order_id
                """,
                (account_id, source),
            ).fetchall()
            for order_id, entry_ts in rows:
                if not order_id:
                    continue
                if conn.execute(
                    "SELECT 1 FROM orders WHERE account_id=? AND order_id=?",
                    (account_id, order_id),
                ).fetchone():
                    continue
                legs = conn.execute(
                    """
                    SELECT asset, SUM(amount) AS amount
                    FROM ledger_entries
                    WHERE account_id=? AND source=? AND entry_type='trade' AND order_id=?
                    GROUP BY asset
                    """,
                    (account_id, source, order_id),
                ).fetchall()
                amounts = {str(asset or '').upper(): float(amount or 0.0) for asset, amount in legs}
                quote_amount = amounts.get('USD', 0.0)
                base_asset = None
                base_amount = 0.0
                for asset, amount in amounts.items():
                    if asset in tradable_assets and abs(amount) > abs(base_amount):
                        base_asset = asset
                        base_amount = amount
                if not base_asset or abs(base_amount) <= 1e-12 or abs(quote_amount) <= 1e-12:
                    continue
                side = None
                if base_amount > 0 and quote_amount < 0:
                    side = 'buy'
                elif base_amount < 0 and quote_amount > 0:
                    side = 'sell'
                if not side:
                    continue
                symbol = f'{base_asset}/USD'
                amount = abs(base_amount)
                price = abs(quote_amount) / amount if amount > 0 else 0.0
                if price <= 0:
                    continue
                ts = entry_ts or now
                
                # Skip si un live_trade existe deja pour ce meme trade (eviter doublons)
                if self._has_matching_local_live_trade(conn, account_id, symbol, side, amount, ts):
                    continue
                
                # Pas de fee_amount pour kraken_ledger: les frais sont deja integres
                # dans les montants du ledger (prix net apres frais)
                fee_amount = 0
                
                fill_id = f'{account_id}:fill:{source}:{order_id}'
                conn.execute(
                    """
                    INSERT INTO orders
                    (account_id, order_id, symbol, side, order_type, status, amount, price,
                     filled_amount, avg_fill_price, source, source_position_idx,
                     opened_at, closed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'market', 'filled', ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (account_id, order_id, symbol, side, amount, price, amount, price, source, ts, ts, ts, now),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fills
                    (fill_id, account_id, order_id, symbol, side, amount, price, fee_amount,
                     fee_asset, source, source_position_idx, fill_ts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, NULL, ?, ?, ?)
                    """,
                    (fill_id, account_id, order_id, symbol, side, amount, price, fee_amount, source, ts, ts, now),
                )
                if side == 'sell':
                    conn.execute(
                        """
                        UPDATE orders
                        SET status='cancelled',
                            closed_at=COALESCE(closed_at, ?),
                            updated_at=?
                        WHERE account_id=?
                          AND symbol=?
                          AND side='sell'
                          AND status='open'
                          AND order_id<>?
                        """,
                        (ts, now, account_id, symbol, order_id),
                    )
        except Exception:
            return

    def _has_matching_local_live_trade(self, conn, account_id, symbol, side, amount, entry_ts, tolerance_seconds=300):
        try:
            from datetime import datetime, timezone
            target_text = str(entry_ts or '').replace('Z', '+00:00')
            target_dt = datetime.fromisoformat(target_text)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)
            target_seconds = target_dt.timestamp()
            rows = conn.execute(
                """
                SELECT opened_at, amount
                FROM orders
                WHERE account_id=?
                  AND symbol=?
                  AND side=?
                  AND status='filled'
                  AND source='live_trade'
                """,
                (account_id, symbol, side),
            ).fetchall()
            for opened_at, local_amount in rows:
                if abs(float(local_amount or 0.0) - float(amount or 0.0)) > max(1e-8, abs(float(amount or 0.0)) * 0.001):
                    continue
                local_text = str(opened_at or '').replace('Z', '+00:00')
                local_dt = datetime.fromisoformat(local_text)
                if local_dt.tzinfo is None:
                    local_dt = local_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
                if abs(local_dt.timestamp() - target_seconds) <= tolerance_seconds:
                    return True
            return False
        except Exception:
            return False

    def _positions_from_accounting(self, conn, mode='paper'):
        account_id = self._account_id(mode)
        positions = []
        rows = conn.execute(
            """
            SELECT o.order_id, o.symbol, o.side, o.status, o.amount, o.price,
                   o.opened_at, o.closed_at, o.created_at, o.updated_at,
                   o.source_position_idx, f.fee_amount, o.source
            FROM orders o
            LEFT JOIN fills f
              ON f.account_id=o.account_id AND f.order_id=o.order_id
            WHERE o.account_id=?
            ORDER BY COALESCE(o.source_position_idx, 999999999), o.opened_at, o.created_at, o.order_id
            """,
            (account_id,),
        ).fetchall()

        def _parse_accounting_ts(raw):
            try:
                dt = datetime.fromisoformat(str(raw or '').replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    try:
                        from zoneinfo import ZoneInfo
                        dt = dt.replace(tzinfo=ZoneInfo(os.getenv('AEGIS_LOCAL_TZ', 'America/Toronto')))
                    except Exception:
                        offset_hours = float(os.getenv('AEGIS_LOCAL_UTC_OFFSET_HOURS', '-4'))
                        dt = dt.replace(tzinfo=timezone(timedelta(hours=offset_hours)))
                return dt.timestamp()
            except Exception:
                return 0.0

        def _is_duplicate_live_trade(row, kraken_rows, tolerance_seconds=120):
            if mode != 'live':
                return False
            order_id, symbol, side, status, amount, price, opened_at, closed_at = row[:8]
            source = row[12] if len(row) > 12 else None
            if source != 'live_trade':
                return False
            if str(status or '').lower() not in {'filled', 'closed', 'executed'}:
                return False
            row_symbol = self._normalize_live_symbol(symbol)
            row_side = str(side or '').lower()
            row_amount = float(amount or 0.0)
            row_ts = _parse_accounting_ts(opened_at or row[8] or row[9])
            for kraken_row in kraken_rows:
                k_symbol = self._normalize_live_symbol(kraken_row[1])
                k_side = str(kraken_row[2] or '').lower()
                k_amount = float(kraken_row[4] or 0.0)
                if row_symbol != k_symbol or row_side != k_side:
                    continue
                if abs(row_amount - k_amount) > max(1e-8, abs(k_amount) * 0.005):
                    continue
                if abs(row_ts - _parse_accounting_ts(kraken_row[6] or kraken_row[8] or kraken_row[9])) <= tolerance_seconds:
                    return True
            return False

        if mode == 'live':
            kraken_rows = [
                row for row in rows
                if str(row[12] or '').startswith('kraken_ledger')
                and str(row[3] or '').lower() in {'filled', 'closed', 'executed'}
            ]
            rows = [row for row in rows if not _is_duplicate_live_trade(row, kraken_rows)]

        def _row_ts(row):
            raw = row[6] or row[8] or row[9] or ''
            try:
                dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    try:
                        from zoneinfo import ZoneInfo
                        dt = dt.replace(tzinfo=ZoneInfo(os.getenv('AEGIS_LOCAL_TZ', 'America/Toronto')))
                    except Exception:
                        offset_hours = float(os.getenv('AEGIS_LOCAL_UTC_OFFSET_HOURS', '-4'))
                        dt = dt.replace(tzinfo=timezone(timedelta(hours=offset_hours)))
                return dt.timestamp()
            except Exception:
                return 0.0

        rows = sorted(
            rows,
            key=lambda row: (
                row[10] if row[10] is not None else 999999999,
                _row_ts(row),
                str(row[0] or ''),
            ),
        )
        buy_remaining = {}
        buy_closed_at = {}
        buy_queues = {}
        for row in rows:
            order_id, symbol, side, status, amount, price, opened_at, closed_at = row[:8]
            created_at = row[8]
            side_text = str(side or '').lower()
            status_text = str(status or '').lower()
            normalized_symbol = self._normalize_live_symbol(symbol)
            qty = float(amount or 0.0)
            if qty <= 0:
                continue
            if side_text == 'buy' and status_text in {'filled', 'closed', 'executed'}:
                buy_remaining[order_id] = qty
                buy_queues.setdefault(normalized_symbol, []).append([order_id, qty])
            elif side_text == 'sell' and status_text in {'filled', 'closed', 'executed'}:
                remaining_sell = qty
                queue = buy_queues.get(normalized_symbol, [])
                while remaining_sell > 1e-12 and queue:
                    buy_item = queue[0]
                    consumed = min(remaining_sell, buy_item[1])
                    buy_item[1] -= consumed
                    buy_remaining[buy_item[0]] = max(0.0, buy_remaining.get(buy_item[0], 0.0) - consumed)
                    remaining_sell -= consumed
                    if buy_item[1] <= 1e-12:
                        buy_closed_at[buy_item[0]] = closed_at or opened_at or created_at
                        queue.pop(0)

        for row in rows:
            (
                order_id, symbol, side, status, amount, price, opened_at, closed_at,
                created_at, updated_at, source_position_idx, fee_amount, source
            ) = row
            side_text = str(side or '').lower()
            status_text = str(status or '').lower()
            bot_status = 'opened' if status_text == 'open' else 'executed' if status_text == 'filled' else status
            position_closed_at = buy_closed_at.get(order_id) if side_text == 'buy' else closed_at
            positions.append({
                'symbol': self._normalize_live_symbol(symbol),
                'side': side_text,
                'amount': self._clean(amount),
                'price': self._clean(price),
                'status': bot_status,
                'order_id': order_id,
                'timestamp': opened_at or created_at,
                'closed_at': position_closed_at,
                'order_closed_at': closed_at,
                'fee': self._clean(fee_amount),
                'fee_rate': self._clean((float(fee_amount) / (float(amount or 0) * float(price or 0))) if fee_amount and amount and price else None),
                'position_size_usd': self._clean(float(amount or 0) * float(price or 0)),
                'position_size_crypto': self._clean(amount),
                'source_position_idx': source_position_idx,
                'source': source,
            })
        return positions

    def _pending_orders_from_accounting(self, conn, mode='paper'):
        account_id = self._account_id(mode)
        pending_orders = {}
        rows = conn.execute(
            """
            SELECT order_id, symbol, side, order_type, status, amount, price, opened_at
            FROM orders
            WHERE account_id=? AND side='sell' AND status='open'
            ORDER BY opened_at, created_at, order_id
            """,
            (account_id,),
        ).fetchall()
        for order_id, symbol, side, order_type, status, amount, price, opened_at in rows:
            pending_orders[str(order_id)] = {
                'order': {
                    'id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'type': order_type or 'limit',
                    'amount': amount,
                    'price': price,
                    'status': 'opened' if status == 'open' else status,
                },
                'timestamp': opened_at,
                'symbol': symbol,
                'side': side,
                'source': 'orders',
                'status': 'opened' if status == 'open' else status,
                'amount': amount,
                'price': price,
                'type': order_type or 'limit',
            }
        return pending_orders

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
                live_symbol_rows = session.scalars(
                    select(Crypto).where(Crypto.mode == key).order_by(Crypto.symbol.asc())
                ).all()
                exit_recommendation_rows = session.scalars(
                    select(MlExitRecommendation).where(MlExitRecommendation.mode == key).order_by(MlExitRecommendation.symbol.asc())
                ).all()
                open_entry_rows = []
                open_entry_rows = session.scalars(
                    select(MlOpenEntry).order_by(MlOpenEntry.opened_at.asc())
                ).all()

            state = {
                'paper_balance': state_row.paper_balance,
                'initial_balance': state_row.initial_balance,
            }
            market_context = {}
            ml_predictions = {}
            symbol_cooldowns = {}
            for row in live_symbol_rows:
                if row.cooldown_until:
                    symbol_cooldowns[row.symbol] = row.cooldown_until
                if row.symbol_regime or row.btc_regime:
                    symbol_regime = row.symbol_regime
                    inferred_mode = 'BEAR' if row.bear_mode else 'NORMAL'
                    regime_text = str(symbol_regime or '')
                    if 'BULL' in regime_text or 'UP' in regime_text:
                        inferred_mode = 'BULL'
                    elif 'BEAR' in regime_text or 'DOWN' in regime_text:
                        inferred_mode = 'BEAR'
                    elif 'SIDE' in regime_text or 'RANGE' in regime_text:
                        inferred_mode = 'RANGE'
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
                if row.p_win is not None or row.recommendation is not None:
                    ml_predictions[row.symbol] = {
                        'p_win': row.p_win,
                        'recommendation': row.recommendation,
                        'min_probability': row.min_probability,
                        'timestamp': row.prediction_ts,
                    }
            exit_recommendations = {}
            conn = self._get_conn()
            accounting_positions = self._positions_from_accounting(conn, key)
            pending_orders = self._pending_orders_from_accounting(conn, key)
            for row in exit_recommendation_rows:
                if row.symbol and (row.exit_decision or row.p_continue is not None or row.entry_price is not None):
                    exit_recommendations[row.symbol] = {
                        'decision': row.exit_decision,
                        'continuation_score': row.p_continue,
                        'min_p_continue': row.min_p_continue,
                        'entry_price': row.entry_price,
                        'net_pnl_pct': row.net_pnl_pct,
                        'duration_minutes': row.duration_minutes,
                        'reason': row.exit_reason,
                    }
                    pred = ml_predictions.setdefault(row.symbol, {})
                    pred['exit_forecast'] = {
                        'p_continue': row.p_continue,
                        'min_p_continue': row.min_p_continue,
                        'decision': row.exit_decision,
                        'reason': row.exit_reason,
                        'entry_price': row.entry_price,
                    }
                    pred['p_continue'] = row.p_continue
                    pred['min_p_continue'] = row.min_p_continue
                    pred['exit_decision'] = row.exit_decision
                    pred['exit_reason'] = row.exit_reason
                    pred['entry_price'] = row.entry_price
            if market_context:
                state['market_context'] = market_context
            if ml_predictions:
                state['ml_predictions'] = ml_predictions
            if symbol_cooldowns:
                state['symbol_cooldowns'] = symbol_cooldowns
            if exit_recommendations:
                state['exit_recommendations'] = exit_recommendations

            state['positions'] = accounting_positions
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
                        'fee_rate': float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0,
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
            if pending_orders or 'pending_orders' not in state:
                state['pending_orders'] = pending_orders
            state['trailing_stops'] = {}
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
            symbol_cooldowns = self._normalize_symbol_map(symbol_cooldowns)
            exit_recommendations = self._normalize_symbol_map(exit_recommendations)
            market_context = self._normalize_symbol_map(market_context)
            ml_predictions = self._normalize_symbol_map(ml_predictions)
            active_buy_context = self._active_buy_context_by_symbol(positions)
            default_exit_threshold = float(os.getenv('ML_EXIT_ENTRY_MIN_CONTINUE_PROB', '50.0'))
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
                            MlExitRecommendation,
                        ):
                            session.execute(delete(model).where(model.mode == key))

                    session.execute(
                        update(Crypto)
                        .where(Crypto.mode == key)
                        .values(
                            cooldown_until=None,
                            symbol_regime=None,
                            btc_regime=None,
                            bear_mode=None,
                            symbol_bear=None,
                            btc_bear=None,
                            trade_multiplier=None,
                            btc_momentum_percent=None,
                            symbol_momentum_percent=None,
                            confidence_bonus=None,
                            reversal_confirmed=None,
                            falling_knife_active=None,
                            p_win=None,
                            recommendation=None,
                            min_probability=None,
                            prediction_ts=None,
                            updated_at=now,
                        )
                    )

                    saved_exit_symbols = set()
                    for symbol, recommendation in exit_recommendations.items():
                        if not isinstance(recommendation, dict):
                            continue
                        normalized_symbol = self._normalize_live_symbol(symbol)
                        if not normalized_symbol:
                            continue
                        context = active_buy_context.get(normalized_symbol, {})
                        reason = text_value(recommendation.get('reason'))
                        min_p_continue = (
                            recommendation.get('min_p_continue')
                            if recommendation.get('min_p_continue') is not None
                            else self._exit_threshold_from_reason(reason, default_exit_threshold)
                        )
                        p_continue = (
                            recommendation.get('p_continue')
                            if recommendation.get('p_continue') is not None
                            else recommendation.get('continuation_probability')
                        )
                        if p_continue is None:
                            p_continue = self._continue_probability_from_reason(reason)
                        session.merge(MlExitRecommendation(
                            mode=key,
                            symbol=normalized_symbol,
                            entry_price=self._clean(recommendation.get('entry_price') or context.get('entry_price')),
                            p_continue=self._clean(p_continue),
                            min_p_continue=self._clean(min_p_continue),
                            exit_decision=text_value(recommendation.get('decision')),
                            exit_reason=reason,
                            net_pnl_pct=self._clean(recommendation.get('net_pnl_pct')),
                            duration_minutes=self._clean(recommendation.get('duration_minutes') or context.get('duration_minutes')),
                            created_at=now,
                            updated_at=now,
                        ))
                        saved_exit_symbols.add(normalized_symbol)

                    all_symbols = set(symbol_cooldowns.keys()) | set(market_context.keys()) | set(ml_predictions.keys())
                    for symbol in all_symbols:
                        if not symbol:
                            continue
                        ctx = market_context.get(symbol) or {}
                        if not isinstance(ctx, dict):
                            ctx = {}
                        reversal = ctx.get('reversal') if isinstance(ctx.get('reversal'), dict) else {}
                        falling = ctx.get('falling_knife') if isinstance(ctx.get('falling_knife'), dict) else {}
                        
                        pred = ml_predictions.get(symbol) or {}
                        if not isinstance(pred, dict):
                            pred = {}
                        exit_forecast = pred.get('exit_forecast') if isinstance(pred.get('exit_forecast'), dict) else {}
                        should_save_exit_forecast = (
                            symbol not in saved_exit_symbols
                            and (
                                exit_forecast
                                or pred.get('p_continue') is not None
                                or pred.get('exit_decision') is not None
                            )
                        )
                        if should_save_exit_forecast:
                            context = active_buy_context.get(symbol, {})
                            reason = text_value(pred.get('exit_reason') or exit_forecast.get('reason'))
                            min_p_continue = (
                                pred.get('min_p_continue')
                                if pred.get('min_p_continue') is not None
                                else exit_forecast.get('min_p_continue')
                            )
                            if min_p_continue is None:
                                min_p_continue = self._exit_threshold_from_reason(reason, default_exit_threshold)
                            p_continue = (
                                pred.get('p_continue')
                                if pred.get('p_continue') is not None
                                else exit_forecast.get('p_continue')
                            )
                            if p_continue is None:
                                p_continue = self._continue_probability_from_reason(reason)
                            session.merge(MlExitRecommendation(
                                mode=key,
                                symbol=symbol,
                                entry_price=self._clean(pred.get('price') or pred.get('entry_price') or exit_forecast.get('entry_price') or context.get('entry_price')),
                                p_continue=self._clean(p_continue),
                                min_p_continue=self._clean(min_p_continue),
                                exit_decision=text_value(pred.get('exit_decision') or exit_forecast.get('decision')),
                                exit_reason=reason,
                                duration_minutes=self._clean(exit_forecast.get('duration_minutes') or pred.get('duration_minutes') or context.get('duration_minutes')),
                                created_at=now,
                                updated_at=now,
                            ))

                        live_row = session.get(Crypto, (key, symbol))
                        if not live_row:
                            live_row = Crypto(mode=key, symbol=symbol, created_at=now, updated_at=now)
                            session.add(live_row)
                        live_row.cooldown_until = self._clean(symbol_cooldowns.get(symbol))
                        live_row.symbol_regime = ctx.get('symbol_regime')
                        live_row.btc_regime = ctx.get('btc_regime')
                        live_row.bear_mode = 1 if ctx.get('bear_mode') else 0
                        live_row.symbol_bear = 1 if ctx.get('symbol_bear') else 0
                        live_row.btc_bear = 1 if ctx.get('btc_bear') else 0
                        live_row.trade_multiplier = self._clean(ctx.get('trade_multiplier'))
                        live_row.btc_momentum_percent = self._clean(ctx.get('btc_momentum_percent'))
                        live_row.symbol_momentum_percent = self._clean(ctx.get('symbol_momentum_percent'))
                        live_row.confidence_bonus = self._clean(ctx.get('confidence_bonus'))
                        live_row.reversal_confirmed = 1 if reversal.get('confirmed') else 0
                        live_row.falling_knife_active = 1 if falling.get('is_falling') else 0
                        live_row.p_win = pred.get('p_win')
                        live_row.recommendation = pred.get('recommendation')
                        live_row.min_probability = pred.get('min_probability')
                        live_row.prediction_ts = text_value(pred.get('timestamp'))
                        live_row.updated_at = now

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
        if event.get('entry_id'):
            entry_row = session.get(DecisionLog, event.get('entry_id'))
            if entry_row:
                entry_row.label_status = 'opened'



    def _insert_trade_outcome(self, session, event):
        self._resolve_outcome_entry_link(session, event)
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
            entry_row = session.get(DecisionLog, event.get('entry_id'))
            if entry_row:
                entry_row.label_status = 'closed'
            session.execute(delete(MlOpenEntry).where(MlOpenEntry.symbol == event.get('symbol')))

    def _resolve_outcome_entry_link(self, session, event):
        """Relie une sortie a la meilleure entree ML ouverte quand le lien direct manque."""
        if not isinstance(event, dict) or event.get('entry_id'):
            return
        symbol = event.get('symbol')
        if not symbol:
            return

        open_entry = session.get(MlOpenEntry, symbol)
        if open_entry and open_entry.entry_id:
            event['entry_id'] = open_entry.entry_id
            event['label_status'] = 'closed'
            return

        linked_outcomes = select(MlTradeOutcome.entry_id).where(MlTradeOutcome.entry_id.is_not(None))
        candidates = session.scalars(
            select(DecisionLog)
            .where(DecisionLog.action_type == 'ENTRY')
            .where(DecisionLog.symbol == symbol)
            .where(DecisionLog.decision == 'accepted')
            .where(~DecisionLog.event_id.in_(linked_outcomes))
            .order_by(DecisionLog.timestamp.desc())
            .limit(1)
        ).all()
        if candidates:
            event['entry_id'] = candidates[0].event_id
            event['label_status'] = 'closed_relinked'

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
        session.merge(Notification(
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
                self._add_feature_importance_orm(session, model_id, 'sizing', metadata.get('sizing_feature_importance'))
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
            sizing_feature_importance = []
            for item in importances:
                if item.scope == 'exit':
                    target = exit_feature_importance
                elif item.scope == 'sizing':
                    target = sizing_feature_importance
                else:
                    target = feature_importance
                target.append((item.feature_name, item.importance))
            return {
                'model_id': row.model_id,
                'trained_at': row.trained_at,
                'model_path': row.model_path,
                'n_features': row.n_features,
                'exit_n_features': row.exit_n_features,
                'sizing_n_features': len(sizing_feature_importance) or None,
                'stored_at': row.stored_at,
                'feature_importance': feature_importance,
                'exit_feature_importance': exit_feature_importance,
                'sizing_feature_importance': sizing_feature_importance,
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
        """Store final bot decisions in the unified decision log table.

        Older code still calls this method after the decision journal tables were
        folded into decision_logs. Keep the public API stable and map the useful
        journal fields to the unified schema.
        """
        if not isinstance(entry, dict):
            return False
        try:
            metrics = entry.get('metrics') if isinstance(entry.get('metrics'), dict) else {}
            confidence = (
                metrics.get('confidence')
                if metrics.get('confidence') is not None
                else metrics.get('score')
            )
            p_win = (
                metrics.get('p_win')
                if metrics.get('p_win') is not None
                else metrics.get('ml_p_win')
            )
            p_continue = (
                metrics.get('p_continue')
                if metrics.get('p_continue') is not None
                else metrics.get('continuation_score')
            )
            price = metrics.get('price') if metrics.get('price') is not None else entry.get('price')
            action = str(entry.get('action') or 'decision').upper()
            allowed = bool(entry.get('allowed'))
            event_id = (
                entry.get('event_id')
                or self._new_id(f"decision_{action.lower()}")
            )
            timestamp = entry.get('timestamp') or now_iso()

            with self._lock:
                with self._orm_session() as session:
                    session.merge(SysAudit(
                        event_id=str(event_id),
                        event_type=f"decision_{action.lower()}",
                        timestamp=timestamp,
                        symbol=entry.get('symbol') or '',
                        mode=entry.get('mode') or mode,
                    ))
                    session.merge(DecisionLog(
                        event_id=str(event_id),
                        action_type=action,
                        timestamp=timestamp,
                        mode=entry.get('mode') or mode,
                        symbol=entry.get('symbol') or '',
                        entry_id=entry.get('entry_id'),
                        decision='accepted' if allowed else 'rejected',
                        reason=entry.get('reason'),
                        price=self._clean(price),
                        confidence=self._clean(confidence),
                        min_confidence=self._clean(metrics.get('min_confidence') or metrics.get('threshold')),
                        p_win=self._clean(p_win),
                        p_continue=self._clean(p_continue),
                        label_status='final',
                        net_pnl_pct=self._clean(metrics.get('net_pnl_pct')),
                        duration_minutes=self._clean(metrics.get('duration_minutes')),
                        slippage_pct=self._clean(metrics.get('slippage_pct')),
                        spread_pct=self._clean(metrics.get('spread_pct')),
                        order_type=metrics.get('order_type'),
                        duration_ms=self._clean(metrics.get('duration_ms')),
                    ))
                    self._trim_decision_logs(session, mode=entry.get('mode') or mode, max_entries=max_entries)
                    session.commit()
            return True
        except Exception:
            return False

    def log_decision_journal(self, entry, mode='paper', max_entries=5000):
        return self.record_decision_journal(entry, mode=mode, max_entries=max_entries)

    def _trim_decision_logs(self, session, mode='paper', max_entries=5000):
        try:
            max_entries = int(max_entries or 0)
            if max_entries <= 0:
                return
            count = session.scalar(
                select(func.count())
                .select_from(DecisionLog)
                .where(DecisionLog.mode == mode)
            ) or 0
            overflow = int(count) - max_entries
            if overflow <= 0:
                return
            old_ids = session.scalars(
                select(DecisionLog.event_id)
                .where(DecisionLog.mode == mode)
                .order_by(DecisionLog.timestamp.asc())
                .limit(overflow)
            ).all()
            if old_ids:
                session.execute(delete(MlFeatureValue).where(MlFeatureValue.event_id.in_(old_ids)))
                session.execute(delete(DecisionLog).where(DecisionLog.event_id.in_(old_ids)))
        except Exception:
            pass

    def get_decision_journal(self, mode='paper', limit=80):
        try:
            with self._orm_session() as session:
                rows = session.scalars(
                    select(DecisionLog)
                    .where(DecisionLog.mode == mode)
                    .order_by(DecisionLog.timestamp.desc())
                    .limit(int(limit))
                ).all()
            items = []
            for row in reversed(rows):
                items.append({
                    'timestamp': row.timestamp,
                    'symbol': row.symbol,
                    'action': row.action_type,
                    'allowed': row.decision == 'accepted',
                    'reason': row.reason,
                    'mode': mode,
                    'metrics': {
                        'decision': row.decision,
                        'confidence': row.confidence,
                        'p_win': row.p_win,
                        'p_continue': row.p_continue,
                        'price': row.price,
                    },
                })
            return items
        except Exception:
            return []

    @staticmethod
    def _serialize_sizing_row(row):
        return {
            'sizing_id': row.sizing_id,
            'timestamp': row.timestamp,
            'mode': row.mode,
            'symbol': row.symbol,
            'entry_id': row.entry_id,
            'p_win': row.p_win,
            'p_continue': row.p_continue,
            'base_position_size_usd': row.base_position_size_usd,
            'raw_sizing_factor': row.raw_sizing_factor,
            'sizing_factor': row.sizing_factor,
            'final_position_size_usd': row.final_position_size_usd,
            'min_position_size_usd': row.min_position_size_usd,
            'max_position_size_usd': row.max_position_size_usd,
            'exposure_before_usd': row.exposure_before_usd,
            'exposure_after_usd': row.exposure_after_usd,
            'max_exposure_usd': row.max_exposure_usd,
            'decision': row.decision,
            'reason': row.reason,
            'risk_veto_reason': row.risk_veto_reason,
        }

    def get_latest_sizing_recommendations(self, mode='paper', limit=20):
        try:
            with self._orm_session() as session:
                rows = session.scalars(
                    select(MlSizingRecommendation)
                    .where(MlSizingRecommendation.mode == mode)
                    .order_by(MlSizingRecommendation.timestamp.desc())
                    .limit(int(limit))
                ).all()
            return [self._serialize_sizing_row(row) for row in rows]
        except Exception:
            return []

    def get_latest_sizing_recommendation_per_symbol(self, mode='paper'):
        """Retourne la recommandation de sizing la PLUS RÉCENTE pour chaque symbole.

        Garantit qu'aucune paire n'est masquée par une paire plus active (ex: BTC),
        contrairement à un simple LIMIT global. Un balayage suffit car les lignes
        sont triées par timestamp décroissant: la première vue d'un symbole est sa
        plus récente."""
        try:
            with self._orm_session() as session:
                rows = session.scalars(
                    select(MlSizingRecommendation)
                    .where(MlSizingRecommendation.mode == mode)
                    .order_by(MlSizingRecommendation.timestamp.desc())
                ).all()
            by_symbol = {}
            for row in rows:
                if row.symbol and row.symbol not in by_symbol:
                    by_symbol[row.symbol] = self._serialize_sizing_row(row)
            return by_symbol
        except Exception:
            return {}

    def count_decision_journal(self, mode='paper'):
        try:
            with self._orm_session() as session:
                return int(session.scalar(
                    select(func.count())
                    .select_from(DecisionLog)
                    .where(DecisionLog.mode == mode)
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
                session.add(CryptoScore(
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
                query = select(CryptoScore).where(CryptoScore.symbol == symbol)
                if since_iso:
                    query = query.where(CryptoScore.timestamp >= since_iso)
                rows = session.scalars(
                    query.order_by(CryptoScore.timestamp.asc()).limit(int(limit))
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
            symbols = status.get('symbols') if isinstance(status.get('symbols'), dict) else {}
            payload = {
                'timestamp': status.get('timestamp'),
                'exchange': status.get('exchange'),
                'connected': bool(status.get('connected')),
                'running': bool(status.get('running')),
                'mode': status.get('mode'),
                'reconnect_attempts': status.get('reconnect_attempts'),
                'queue_size': status.get('queue_size'),
                'queue_maxsize': status.get('queue_maxsize'),
                'worker_alive': bool(status.get('worker_alive')),
                'ws_thread_alive': bool(status.get('ws_thread_alive')),
                'subscribed_symbols': [
                    self._normalize_live_symbol(symbol)
                    for symbol in (status.get('subscribed_symbols') or [])
                    if self._normalize_live_symbol(symbol)
                ],
            }
            with self._orm_session() as session:
                row = session.get(BotAppState, 'live_status')
                if not row:
                    row = BotAppState(state_key='live_status', created_at=now)
                    session.add(row)
                row.state_value = json.dumps(payload, ensure_ascii=False)
                row.updated_at = now

                for symbol, data in symbols.items():
                    if not isinstance(data, dict):
                        data = {}
                    normalized_symbol = self._normalize_live_symbol(symbol)
                    if not normalized_symbol:
                        continue
                    live_row = session.get(Crypto, ('paper', normalized_symbol))
                    if not live_row:
                        live_row = Crypto(mode='paper', symbol=normalized_symbol, created_at=now, updated_at=now)
                        session.add(live_row)
                    price = self._clean(data.get('price'))
                    live_row.price = price
                    live_row.bid = self._clean(data.get('bid'))
                    live_row.ask = self._clean(data.get('ask'))
                    live_row.spread_percent = self._clean(data.get('spread_percent'))
                    live_row.high = self._first_clean(data.get('high'), data.get('high_24h'), data.get('candle_high'))
                    live_row.low = self._first_clean(data.get('low'), data.get('low_24h'), data.get('candle_low'))
                    live_row.high_24h = self._first_clean(data.get('high_24h'), data.get('high'))
                    live_row.low_24h = self._first_clean(data.get('low_24h'), data.get('low'))
                    live_row.volume_24h = self._first_clean(data.get('volume_24h'), data.get('volume'))
                    live_row.quote_volume = self._first_clean(data.get('quote_volume'), data.get('volume_usd'), data.get('volume_24h_usd'))
                    live_row.volume_usd = self._first_clean(
                        data.get('volume_usd'),
                        data.get('quote_volume'),
                        data.get('volume_24h_usd'),
                        self._volume_usd(data.get('volume_24h'), price),
                    )
                    live_row.candle_high = self._first_clean(data.get('candle_high'), data.get('high'))
                    live_row.candle_low = self._first_clean(data.get('candle_low'), data.get('low'))
                    live_row.candle_volume = self._clean(data.get('candle_volume'))
                    live_row.candle_volume_usd = self._first_clean(
                        data.get('candle_volume_usd'),
                        self._volume_usd(data.get('candle_volume'), price),
                    )
                    live_row.ws_connected = 1 if status.get('connected') else 0
                    live_row.updated_at = now

                session.commit()
            return True
        except Exception:
            return False

    def get_live_status(self):
        try:
            with self._orm_session() as session:
                row = session.get(BotAppState, 'live_status')
                payload = {}
                if row and row.state_value:
                    try:
                        payload = json.loads(row.state_value)
                    except Exception:
                        payload = {}
                symbol_rows = session.scalars(
                    select(Crypto)
                    .where(Crypto.mode == 'paper')
                    .order_by(Crypto.symbol.asc())
                ).all()
                subscriptions = payload.get('subscribed_symbols') or [item.symbol for item in symbol_rows]
            symbols = {}
            for item in symbol_rows:
                data = {
                    'price': item.price,
                    'bid': item.bid,
                    'ask': item.ask,
                    'spread_percent': item.spread_percent,
                    'high': item.high,
                    'low': item.low,
                    'high_24h': item.high_24h,
                    'low_24h': item.low_24h,
                    'volume_24h': item.volume_24h,
                    'volume_usd': item.volume_usd,
                    'quote_volume': item.quote_volume,
                    'candle_high': item.candle_high,
                    'candle_low': item.candle_low,
                    'candle_volume': item.candle_volume,
                    'candle_volume_usd': item.candle_volume_usd,
                    'trend_score': item.trend_score,
                    'p_win': item.p_win,
                    'recommendation': item.recommendation,
                }
                symbols[item.symbol] = {key: value for key, value in data.items() if value is not None}
            return {
                'timestamp': payload.get('timestamp'),
                'exchange': payload.get('exchange'),
                'connected': bool(payload.get('connected')),
                'running': bool(payload.get('running')),
                'mode': payload.get('mode'),
                'reconnect_attempts': payload.get('reconnect_attempts'),
                'queue_size': payload.get('queue_size'),
                'queue_maxsize': payload.get('queue_maxsize'),
                'worker_alive': bool(payload.get('worker_alive')),
                'ws_thread_alive': bool(payload.get('ws_thread_alive')),
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
                # Persistance des compteurs gagnants/perdants (tolérance si colonne absente)
                try:
                    row.winning_trades_count = int(stats.get('winning_trades_count') or 0)
                    row.losing_trades_count = int(stats.get('losing_trades_count') or 0)
                except Exception:
                    pass
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
            result = {
                'date': row.stat_date,
                'trades_count': row.trades_count or 0,
                'total_loss': row.total_loss or 0,
                'total_profit': row.total_profit or 0,
                'emergency_stop': bool(row.emergency_stop),
            }
            # Charger les compteurs persistés si la colonne existe
            try:
                result['winning_trades_count'] = row.winning_trades_count or 0
                result['losing_trades_count'] = row.losing_trades_count or 0
            except Exception:
                pass
            return result
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

    def log_execution_metric(self, symbol, side, order_type, expected_price, requested_price, executed_price, slippage_pct, spread_pct, amount, duration_ms, success, reason):
        """Enregistre les métriques de microstructure et d'exécution dans MlOpenEntry (Phase 7)."""
        try:
            with self._orm_session() as session:
                row = session.get(MlOpenEntry, str(symbol))
                if row:
                    row.expected_price = self._clean(expected_price)
                    row.requested_price = self._clean(requested_price)
                    row.slippage_pct = self._clean(slippage_pct)
                    row.spread_pct = self._clean(spread_pct)
                    row.order_type = str(order_type)
                    row.duration_ms = self._clean(duration_ms)
                    session.commit()
            return True
        except Exception:
            return False

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
                # Persistance des compteurs gagnants/perdants (tolérance si colonne absente)
                try:
                    row.winning_trades_count = int(stats.get('winning_trades_count') or 0)
                    row.losing_trades_count = int(stats.get('losing_trades_count') or 0)
                except Exception:
                    pass
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
            result = {
                'date': row.stat_date,
                'trades_count': row.trades_count or 0,
                'total_loss': row.total_loss or 0,
                'total_profit': row.total_profit or 0,
                'emergency_stop': bool(row.emergency_stop),
            }
            # Charger les compteurs persistés si la colonne existe
            try:
                result['winning_trades_count'] = row.winning_trades_count or 0
                result['losing_trades_count'] = row.losing_trades_count or 0
            except Exception:
                pass
            return result
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

    def log_execution_metric(self, symbol, side, order_type, expected_price, requested_price, executed_price, slippage_pct, spread_pct, amount, duration_ms, success, reason):
        """Enregistre les métriques de microstructure et d'exécution dans MlOpenEntry (Phase 7)."""
        try:
            with self._orm_session() as session:
                row = session.get(MlOpenEntry, str(symbol))
                if row:
                    row.expected_price = self._clean(expected_price)
                    row.requested_price = self._clean(requested_price)
                    row.slippage_pct = self._clean(slippage_pct)
                    row.spread_pct = self._clean(spread_pct)
                    row.order_type = str(order_type)
                    row.duration_ms = self._clean(duration_ms)
                    session.commit()
            return True
        except Exception:
            return False

    def _features_to_dict(self, feature_names, features):
        if features is None:
            return {}
        if isinstance(features, dict):
            return {
                str(name): self._clean(value)
                for name, value in features.items()
            }
        try:
            values = list(features.tolist() if hasattr(features, 'tolist') else features)
            names = list(feature_names or [])
            if not names:
                names = [f'feature_{idx}' for idx in range(len(values))]
            return {
                str(name): self._clean(values[idx])
                for idx, name in enumerate(names[:len(values)])
            }
        except Exception:
            return {}

    def _new_id(self, prefix):
        return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}"

    def _stable_id(self, prefix, value):
        safe = ''.join(ch if ch.isalnum() else '_' for ch in str(value))[:80].strip('_')
        return f"{prefix}_{safe or uuid.uuid4().hex[:10]}"

    def backup_db(self, dest_dir='data/backups', keep_max=7):
        """Exécute un checkpoint WAL complet et crée un snapshot daté de aegis_db.sqlite3."""
        try:
            if not os.path.exists(self.sqlite_file):
                return None
            os.makedirs(dest_dir, exist_ok=True)

            with self._lock:
                conn = self._get_conn()
                try:
                    conn.execute("PRAGMA wal_checkpoint(FULL);")
                except Exception:
                    pass

            now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            dest_file = os.path.join(dest_dir, f"aegis_db_{now_str}.sqlite3")

            import shutil
            shutil.copy2(self.sqlite_file, dest_file)

            backups = sorted([
                os.path.join(dest_dir, f) for f in os.listdir(dest_dir)
                if f.startswith('aegis_db_') and f.endswith('.sqlite3')
            ])
            if len(backups) > keep_max:
                for old in backups[:-keep_max]:
                    try:
                        os.remove(old)
                    except Exception:
                        pass

            return dest_file
        except Exception as e:
            print(f"⚠️ Erreur backup_db: {e}")
            return None

    def record_governance_event(self, event_type, source_model=None, target_model=None, metrics=None, trigger_type='auto', reason=None):
        """Enregistre un événement de gouvernance dans la table unifiée governance_logs."""
        try:
            now = now_iso()
            gov_id = self._new_id('gov')
            metrics_json = json.dumps(metrics, ensure_ascii=False) if isinstance(metrics, dict) else (str(metrics) if metrics else None)
            with self._orm_session() as session:
                session.add(GovernanceLog(
                    gov_id=gov_id,
                    timestamp=now,
                    event_type=str(event_type),
                    source_model=str(source_model) if source_model else None,
                    target_model=str(target_model) if target_model else None,
                    metrics_json=metrics_json,
                    trigger_type=str(trigger_type),
                    reason=str(reason) if reason else None,
                    created_at=now,
                    updated_at=now,
                ))
                session.commit()
            return gov_id
        except Exception as e:
            print(f"⚠️ Erreur record_governance_event: {e}")
            return None

    def _clean(self, value):
        if isinstance(value, dict):
            return {str(k): self._clean(v) for k, v in value.items()}
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

    def _first_clean(self, *values):
        for value in values:
            cleaned = self._clean(value)
            if cleaned is not None:
                return cleaned
        return None

    def _volume_usd(self, volume, price):
        clean_volume = self._clean(volume)
        clean_price = self._clean(price)
        if clean_volume is None:
            return None
        if clean_price is None:
            return clean_volume
        return clean_volume * clean_price

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
