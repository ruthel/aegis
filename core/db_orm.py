import os
from datetime import datetime

from sqlalchemy import Float, Index, Integer, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class BotAppState(Base):
    __tablename__ = 'bot_app_state'

    state_key: Mapped[str] = mapped_column(Text, primary_key=True)
    state_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class BotProcess(Base):
    __tablename__ = 'bot_processes'

    process_key: Mapped[str] = mapped_column(Text, primary_key=True)
    pid: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class BotCommand(Base):
    __tablename__ = 'bot_commands'

    command_id: Mapped[str] = mapped_column(Text, primary_key=True)
    action: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    seconds: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text)
    command_ts: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class BotState(Base):
    __tablename__ = 'bot_state'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_balance: Mapped[float | None] = mapped_column(Float)
    initial_balance: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class Account(Base):
    __tablename__ = 'accounts'

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    base_currency: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    initial_balance: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Balance(Base):
    __tablename__ = 'balances'

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset: Mapped[str] = mapped_column(Text, primary_key=True)
    free: Mapped[float | None] = mapped_column(Float)
    locked: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class Order(Base):
    __tablename__ = 'orders'

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    order_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    filled_amount: Mapped[float | None] = mapped_column(Float)
    avg_fill_price: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(Text)
    source_position_idx: Mapped[int | None] = mapped_column(Integer)
    opened_at: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class Fill(Base):
    __tablename__ = 'fills'

    fill_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    fee_amount: Mapped[float | None] = mapped_column(Float)
    fee_asset: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    source_position_idx: Mapped[int | None] = mapped_column(Integer)
    fill_ts: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'

    ledger_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text)
    entry_ts: Mapped[str | None] = mapped_column(Text)
    entry_type: Mapped[str] = mapped_column(Text)
    asset: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float | None] = mapped_column(Float)
    order_id: Mapped[str | None] = mapped_column(Text)
    fill_id: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    source_position_idx: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class MlExitRecommendation(Base):
    __tablename__ = 'ml_exit_recommendations'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    min_p_continue: Mapped[float | None] = mapped_column(Float)
    exit_decision: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    net_pnl_pct: Mapped[float | None] = mapped_column(Float)
    duration_minutes: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class Crypto(Base):
    __tablename__ = 'cryptos'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)

    # Status & Price
    price: Mapped[float | None] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    spread_percent: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    high_24h: Mapped[float | None] = mapped_column(Float)
    low_24h: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)
    volume_usd: Mapped[float | None] = mapped_column(Float)
    quote_volume: Mapped[float | None] = mapped_column(Float)
    candle_high: Mapped[float | None] = mapped_column(Float)
    candle_low: Mapped[float | None] = mapped_column(Float)
    candle_volume: Mapped[float | None] = mapped_column(Float)
    candle_volume_usd: Mapped[float | None] = mapped_column(Float)
    trend_score: Mapped[int | None] = mapped_column(Integer)
    ws_connected: Mapped[int | None] = mapped_column(Integer)

    # Cooldown & Market Context
    cooldown_until: Mapped[float | None] = mapped_column(Float)
    symbol_regime: Mapped[str | None] = mapped_column(Text)
    btc_regime: Mapped[str | None] = mapped_column(Text)
    bear_mode: Mapped[int | None] = mapped_column(Integer)
    symbol_bear: Mapped[int | None] = mapped_column(Integer)
    btc_bear: Mapped[int | None] = mapped_column(Integer)
    trade_multiplier: Mapped[float | None] = mapped_column(Float)
    btc_momentum_percent: Mapped[float | None] = mapped_column(Float)
    symbol_momentum_percent: Mapped[float | None] = mapped_column(Float)
    confidence_bonus: Mapped[float | None] = mapped_column(Float)
    reversal_confirmed: Mapped[int | None] = mapped_column(Integer)
    falling_knife_active: Mapped[int | None] = mapped_column(Integer)

    # ML Predictions Live
    p_win: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(Text)
    min_probability: Mapped[float | None] = mapped_column(Float)
    prediction_ts: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotDailyStat(Base):
    __tablename__ = 'bot_daily_stats'

    stat_date: Mapped[str] = mapped_column(Text, primary_key=True)
    trades_count: Mapped[int | None] = mapped_column(Integer)
    winning_trades_count: Mapped[int | None] = mapped_column(Integer)
    losing_trades_count: Mapped[int | None] = mapped_column(Integer)
    total_loss: Mapped[float | None] = mapped_column(Float)
    total_profit: Mapped[float | None] = mapped_column(Float)
    emergency_stop: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class CryptoScore(Base):
    __tablename__ = 'crypto_scores'

    score_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class MlModelMetadata(Base):
    __tablename__ = 'ml_model_metadata'

    model_id: Mapped[str] = mapped_column(Text, primary_key=True)
    trained_at: Mapped[str | None] = mapped_column(Text)
    model_path: Mapped[str | None] = mapped_column(Text)
    n_features: Mapped[int | None] = mapped_column(Integer)
    exit_n_features: Mapped[int | None] = mapped_column(Integer)
    stored_at: Mapped[str] = mapped_column(Text)


class MlFeatureImportance(Base):
    __tablename__ = 'ml_feature_importances'

    model_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_name: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float)


class SupportTouchResult(Base):
    __tablename__ = 'support_touch_results'

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    generated_at: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    run_timeframe: Mapped[str | None] = mapped_column(Text)
    candle_limit: Mapped[int | None] = mapped_column(Integer)
    run_total_trades: Mapped[int | None] = mapped_column(Integer)
    run_total_wins: Mapped[int | None] = mapped_column(Integer)
    run_win_rate: Mapped[float | None] = mapped_column(Float)
    run_total_pnl_percent: Mapped[float | None] = mapped_column(Float)
    timeframe: Mapped[str | None] = mapped_column(Text)
    candles: Mapped[int | None] = mapped_column(Integer)
    trades: Mapped[int | None] = mapped_column(Integer)
    wins: Mapped[int | None] = mapped_column(Integer)
    losses: Mapped[int | None] = mapped_column(Integer)
    win_rate: Mapped[float | None] = mapped_column(Float)
    total_pnl_percent: Mapped[float | None] = mapped_column(Float)
    avg_pnl_percent: Mapped[float | None] = mapped_column(Float)
    best_trade_percent: Mapped[float | None] = mapped_column(Float)
    worst_trade_percent: Mapped[float | None] = mapped_column(Float)
    stored_at: Mapped[str] = mapped_column(Text)


class SysAudit(Base):
    __tablename__ = 'sys_audit'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)


class DecisionLog(Base):
    __tablename__ = 'decision_logs'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    action_type: Mapped[str] = mapped_column(Text)  # 'ENTRY' or 'EXIT'
    timestamp: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    entry_id: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    min_confidence: Mapped[float | None] = mapped_column(Float)
    p_win: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    label_status: Mapped[str | None] = mapped_column(Text)
    net_pnl_pct: Mapped[float | None] = mapped_column(Float)
    duration_minutes: Mapped[float | None] = mapped_column(Float)
    slippage_pct: Mapped[float | None] = mapped_column(Float)
    spread_pct: Mapped[float | None] = mapped_column(Float)
    order_type: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class MlFeatureValue(Base):
    __tablename__ = 'ml_feature_values'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_name: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_value: Mapped[float | None] = mapped_column(Float)
    feature_text: Mapped[str | None] = mapped_column(Text)


class MlOpenEntry(Base):
    __tablename__ = 'ml_open_entries'

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    entry_id: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    expected_price: Mapped[float | None] = mapped_column(Float)
    requested_price: Mapped[float | None] = mapped_column(Float)
    slippage_pct: Mapped[float | None] = mapped_column(Float)
    spread_pct: Mapped[float | None] = mapped_column(Float)
    order_type: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class MlTradeOutcome(Base):
    __tablename__ = 'ml_trade_outcomes'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    entry_id: Mapped[str | None] = mapped_column(Text)
    sell_price: Mapped[float | None] = mapped_column(Float)
    buy_price: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)
    hold_time: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    label_status: Mapped[str | None] = mapped_column(Text)
    slippage_pct: Mapped[float | None] = mapped_column(Float)
    spread_pct: Mapped[float | None] = mapped_column(Float)


class Notification(Base):
    __tablename__ = 'notifications'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    telegram_ts: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)


class MlAnalysisRun(Base):
    __tablename__ = 'ml_analysis_runs'

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    generated_at: Mapped[str] = mapped_column(Text)
    accepted_entries: Mapped[int] = mapped_column(Integer)
    closed_entries: Mapped[int] = mapped_column(Integer)
    rejected_entries: Mapped[int] = mapped_column(Integer)
    rejected_replayed: Mapped[int] = mapped_column(Integer)
    brier_score: Mapped[float | None] = mapped_column(Float)
    calibration_mae: Mapped[float | None] = mapped_column(Float)
    live_win_rate: Mapped[float | None] = mapped_column(Float)
    avg_pnl_pct: Mapped[float | None] = mapped_column(Float)
    drift_status: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    stored_at: Mapped[str] = mapped_column(Text)


class MlPredictionCalibration(Base):
    __tablename__ = 'ml_prediction_calibration'

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    bucket_label: Mapped[str] = mapped_column(Text, primary_key=True)
    min_p_win: Mapped[float] = mapped_column(Float)
    max_p_win: Mapped[float] = mapped_column(Float)
    entries: Mapped[int] = mapped_column(Integer)
    closed_entries: Mapped[int] = mapped_column(Integer)
    predicted_avg: Mapped[float | None] = mapped_column(Float)
    realized_win_rate: Mapped[float | None] = mapped_column(Float)
    avg_pnl_pct: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)


class MlRejectedReplayResult(Base):
    __tablename__ = 'ml_rejected_replay_results'

    entry_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(Text)
    entry_price: Mapped[float | None] = mapped_column(Float)
    p_win: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    replay_status: Mapped[str] = mapped_column(Text)
    replay_method: Mapped[str | None] = mapped_column(Text)
    exit_time: Mapped[str | None] = mapped_column(Text)
    exit_price: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)


class MlDriftAlert(Base):
    __tablename__ = 'ml_drift_alerts'

    alert_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    accepted_entries: Mapped[int | None] = mapped_column(Integer)
    closed_entries: Mapped[int | None] = mapped_column(Integer)
    rejected_entries: Mapped[int | None] = mapped_column(Integer)
    rejected_replayed: Mapped[int | None] = mapped_column(Integer)
    live_win_rate: Mapped[float | None] = mapped_column(Float)
    calibration_mae: Mapped[float | None] = mapped_column(Float)
    avg_pnl_pct: Mapped[float | None] = mapped_column(Float)
    stored_at: Mapped[str] = mapped_column(Text)


class GovernanceLog(Base):
    __tablename__ = 'governance_logs'

    gov_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    source_model: Mapped[str | None] = mapped_column(Text)
    target_model: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


Index('idx_sys_audit_type_time', SysAudit.event_type, SysAudit.timestamp)
Index('idx_decision_logs_type_symbol_time', DecisionLog.action_type, DecisionLog.symbol, DecisionLog.timestamp)
Index('idx_ml_feature_name', MlFeatureValue.feature_name)
Index('idx_ml_outcome_entry', MlTradeOutcome.entry_id)
Index('idx_notifications_time', Notification.timestamp)
Index('idx_notifications_direction', Notification.direction)
Index('idx_crypto_scores_symbol_time', CryptoScore.symbol, CryptoScore.timestamp)
Index('idx_accounts_mode', Account.mode)
Index('idx_balances_asset', Balance.asset)
Index('idx_orders_symbol_status', Order.symbol, Order.status)
Index('idx_fills_order', Fill.account_id, Fill.order_id)
Index('idx_ledger_account_asset_time', LedgerEntry.account_id, LedgerEntry.asset, LedgerEntry.entry_ts)
Index('idx_governance_type_time', GovernanceLog.event_type, GovernanceLog.timestamp)
Index('idx_ml_exit_recommendations_symbol', MlExitRecommendation.mode, MlExitRecommendation.symbol)
Index('idx_cryptos_symbol', Crypto.mode, Crypto.symbol)


def sqlite_url(sqlite_file):
    path = os.path.abspath(sqlite_file)
    return 'sqlite:///' + path.replace('\\', '/')


def create_sqlite_engine(sqlite_file):
    engine = create_engine(
        sqlite_url(sqlite_file),
        connect_args={'check_same_thread': False, 'timeout': 30},
        future=True,
    )
    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()
    return engine


def create_session_factory(sqlite_file):
    engine = create_sqlite_engine(sqlite_file)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False, future=True)


def now_iso():
    return datetime.now().isoformat()
