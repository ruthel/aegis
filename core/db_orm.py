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


class BotPosition(Base):
    __tablename__ = 'bot_positions'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)
    fee: Mapped[float | None] = mapped_column(Float)
    fee_rate: Mapped[float | None] = mapped_column(Float)
    position_size_usd: Mapped[float | None] = mapped_column(Float)
    position_size_crypto: Mapped[float | None] = mapped_column(Float)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float)
    target_price: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotTrailingStop(Base):
    __tablename__ = 'bot_trailing_stops'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    stop_price: Mapped[float | None] = mapped_column(Float)
    highest_price: Mapped[float | None] = mapped_column(Float)
    buy_price: Mapped[float | None] = mapped_column(Float)
    trailing_percent: Mapped[float | None] = mapped_column(Float)
    initial_trailing_percent: Mapped[float | None] = mapped_column(Float)
    breakeven_active: Mapped[int | None] = mapped_column(Integer)
    resistance_price: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotSymbolCooldown(Base):
    __tablename__ = 'bot_symbol_cooldowns'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    cooldown_until: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotExitRecommendation(Base):
    __tablename__ = 'bot_exit_recommendations'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    decision: Mapped[str | None] = mapped_column(Text)
    continuation_score: Mapped[float | None] = mapped_column(Float)
    net_pnl_pct: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotMarketContext(Base):
    __tablename__ = 'bot_market_context'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    context_mode: Mapped[str | None] = mapped_column(Text)
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
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class MlLivePrediction(Base):
    __tablename__ = 'ml_live_predictions'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    p_win: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(Text)
    min_probability: Mapped[float | None] = mapped_column(Float)
    min_p_continue: Mapped[float | None] = mapped_column(Float)
    exit_decision: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    entry_price: Mapped[float | None] = mapped_column(Float)
    prediction_ts: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotDailyStat(Base):
    __tablename__ = 'bot_daily_stats'

    stat_date: Mapped[str] = mapped_column(Text, primary_key=True)
    trades_count: Mapped[int | None] = mapped_column(Integer)
    total_loss: Mapped[float | None] = mapped_column(Float)
    total_profit: Mapped[float | None] = mapped_column(Float)
    emergency_stop: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class CryptoScoreHistory(Base):
    __tablename__ = 'crypto_score_history'

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


class BotDecisionJournal(Base):
    __tablename__ = 'bot_decision_journal'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    allowed: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


class BotDecisionMetric(Base):
    __tablename__ = 'bot_decision_metrics'

    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_value: Mapped[float | None] = mapped_column(Float)
    metric_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class BotLiveStatus(Base):
    __tablename__ = 'bot_live_status'

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    connected: Mapped[int | None] = mapped_column(Integer)
    running: Mapped[int | None] = mapped_column(Integer)
    mode_name: Mapped[str | None] = mapped_column(Text)
    reconnect_attempts: Mapped[int | None] = mapped_column(Integer)
    queue_size: Mapped[int | None] = mapped_column(Integer)
    queue_maxsize: Mapped[int | None] = mapped_column(Integer)
    worker_alive: Mapped[int | None] = mapped_column(Integer)
    ws_thread_alive: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class BotLiveStatusSubscription(Base):
    __tablename__ = 'bot_live_status_subscriptions'

    status_key: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class BotLiveStatusSymbol(Base):
    __tablename__ = 'bot_live_status_symbols'

    status_key: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    price: Mapped[float | None] = mapped_column(Float)
    tick_count: Mapped[int | None] = mapped_column(Integer)
    kline_count: Mapped[int | None] = mapped_column(Integer)
    analysis_trigger_countdown: Mapped[int | None] = mapped_column(Integer)
    price_change_since_analysis_percent: Mapped[float | None] = mapped_column(Float)
    last_tick: Mapped[str | None] = mapped_column(Text)
    last_tick_age_seconds: Mapped[float | None] = mapped_column(Float)
    last_analysis: Mapped[str | None] = mapped_column(Text)
    last_analysis_age_seconds: Mapped[float | None] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    spread_percent: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)
    candle_timestamp: Mapped[str | None] = mapped_column(Text)
    candle_open: Mapped[float | None] = mapped_column(Float)
    candle_high: Mapped[float | None] = mapped_column(Float)
    candle_low: Mapped[float | None] = mapped_column(Float)
    candle_volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class MlRawEvent(Base):
    __tablename__ = 'ml_raw_events'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)


class MlEntryDecision(Base):
    __tablename__ = 'ml_entry_decisions'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float)
    p_win: Mapped[float | None] = mapped_column(Float)
    min_p_win: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    min_p_continue: Mapped[float | None] = mapped_column(Float)
    label_status: Mapped[str | None] = mapped_column(Text)


class MlEntryFeatureValue(Base):
    __tablename__ = 'ml_entry_feature_values'

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


class MlExitDecision(Base):
    __tablename__ = 'ml_exit_decisions'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    entry_id: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[float | None] = mapped_column(Float)
    entry_p_win: Mapped[float | None] = mapped_column(Float)
    continuation_score: Mapped[float | None] = mapped_column(Float)
    p_continue: Mapped[float | None] = mapped_column(Float)
    net_pnl_pct: Mapped[float | None] = mapped_column(Float)
    duration_minutes: Mapped[float | None] = mapped_column(Float)


class MlExitFeatureValue(Base):
    __tablename__ = 'ml_exit_feature_values'

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_name: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_value: Mapped[float | None] = mapped_column(Float)
    feature_text: Mapped[str | None] = mapped_column(Text)


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


class TelegramMessage(Base):
    __tablename__ = 'telegram_messages'

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
    would_win: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)


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


Index('idx_ml_raw_events_type_time', MlRawEvent.event_type, MlRawEvent.timestamp)
Index('idx_ml_entry_symbol_time', MlEntryDecision.symbol, MlEntryDecision.timestamp)
Index('idx_ml_exit_symbol_time', MlExitDecision.symbol, MlExitDecision.timestamp)
Index('idx_ml_entry_feature_name', MlEntryFeatureValue.feature_name)
Index('idx_ml_exit_feature_name', MlExitFeatureValue.feature_name)
Index('idx_ml_outcome_entry', MlTradeOutcome.entry_id)
Index('idx_telegram_messages_time', TelegramMessage.timestamp)
Index('idx_telegram_messages_direction', TelegramMessage.direction)
Index('idx_crypto_score_symbol_time', CryptoScoreHistory.symbol, CryptoScoreHistory.timestamp)
Index('idx_bot_commands_status', BotCommand.status, BotCommand.command_ts)
Index('idx_bot_live_status_symbols_symbol', BotLiveStatusSymbol.symbol)
Index('idx_support_touch_results_symbol', SupportTouchResult.symbol)
Index('idx_support_touch_results_time', SupportTouchResult.generated_at)
Index('idx_ml_model_metadata_trained', MlModelMetadata.trained_at)
Index('idx_ml_rejected_replay_status', MlRejectedReplayResult.replay_status)
Index('idx_ml_analysis_runs_time', MlAnalysisRun.generated_at)
Index('idx_bot_state_mode', BotState.mode)
Index('idx_bot_processes_pid', BotProcess.pid)
Index('idx_bot_positions_symbol', BotPosition.mode, BotPosition.symbol)
Index('idx_bot_positions_order', BotPosition.mode, BotPosition.order_id)
Index('idx_bot_decision_journal_time', BotDecisionJournal.mode, BotDecisionJournal.timestamp)
Index('idx_bot_market_context_symbol', BotMarketContext.mode, BotMarketContext.symbol)
Index('idx_ml_live_predictions_symbol', MlLivePrediction.mode, MlLivePrediction.symbol)


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
