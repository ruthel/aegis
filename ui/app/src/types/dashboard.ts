export type View = 'live' | 'analytics' | 'trades' | 'ledger' | 'console' | 'config'
export type DataViewMode = 'paper' | 'live' | 'all'
export type JsonMap = Record<string, unknown>

export type BotControl = {
  running?: boolean
  pid?: number | string | null
  started_at?: string | null
}

export type StatusPayload = {
  bot?: {
    name?: string
    mode?: string
    view_mode?: DataViewMode | string
    exchange?: string
    last_update?: string
    control?: BotControl
  }
  live?: {
    symbols?: Record<string, JsonMap>
  }
  positions?: JsonMap[]
  sell_orders?: JsonMap[]
  decisions?: JsonMap[]
  cooldowns?: JsonMap[]
  logs?: string[]
  balance?: {
    paper_balance?: number
    balances?: Record<string, JsonMap>
    balances_by_mode?: Record<string, Record<string, JsonMap>>
    view_mode?: DataViewMode | string
    source?: string
  }
  stats?: {
    total_trades?: number
    wins?: number
    losses?: number
    win_rate?: number
    total_pnl_gross?: number
    total_fees?: number
    total_pnl_net?: number
    total_pnl?: number
    days_active?: number
    avg_stake?: number
  }
  market_context?: Record<string, JsonMap>
  support_touch?: Record<string, JsonMap>
  next_buy_forecast?: JsonMap
  total_decisions?: number
}

export type MlStatus = {
  is_trained?: boolean
  trained_at?: string | null
  total_samples?: number
  min_probability?: number
  live_predictions?: Record<string, JsonMap>
  analytics?: JsonMap
  sizing_model_active?: boolean
  sizing_n_features?: number | null
  top_sizing_features?: Array<[string, number]>
  sizing_recommendations?: JsonMap[]
}

export type ConsolePayload = {
  lines?: string[]
  total?: number
}

export type ConfigPayload = {
  fields?: ConfigField[]
  values?: Record<string, string | number | boolean | null>
  secrets?: Array<{ name: string; configured: boolean }>
  ml_retraining?: {
    pid?: number | string | null
    started_at?: string | null
    command?: string | null
    status?: string
    trigger?: string | null
    check_only?: boolean | null
    fast?: boolean | null
    running?: boolean
    exit_code?: number | null
  }
  ml_model_evaluations?: ModelEvaluation[]
  risk_sizing?: JsonMap
  ml_sizing_recommendations?: JsonMap[]
  ml_sizing_backtests?: JsonMap[]
  trading_mode?: {
    mode?: 'paper' | 'live' | string
    paper_trading?: boolean
    live_ready?: boolean
    requires_restart?: boolean
  }
  ok?: boolean
  errors?: Record<string, string>
  message?: string
}

export type ModelEvaluation = {
  timestamp?: string | null
  event_type?: string | null
  source_model?: string | null
  target_model?: string | null
  trigger_type?: string | null
  reason?: string | null
  metrics?: JsonMap
}

export type ConfigField = {
  name: string
  label: string
  section?: string
  type?: string
  value?: string | number | boolean | null
  source?: string
  restart?: string
}

export type AnalyticsPayload = {
  advanced_metrics?: JsonMap
  heatmap?: {
    by_crypto?: JsonMap[]
    by_day?: JsonMap[]
    by_hour?: JsonMap[]
  }
  capital_breakdown?: JsonMap
  pnl_history?: {
    initial_balance?: number
    current_balance?: number
    total_pnl?: number
    history?: JsonMap[]
  }
}

export type TradesPayload = {
  trades?: JsonMap[]
  buys?: JsonMap[]
  sells?: JsonMap[]
  total?: number
}

export type LedgerEntry = {
  ledger_id?: string
  account_id?: string
  mode?: DataViewMode | string
  entry_ts?: string | null
  entry_type?: string
  asset?: string
  amount?: number
  balance_after?: number | null
  order_id?: string | null
  fill_id?: string | null
  symbol?: string | null
  source?: string | null
  description?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type LedgerPayload = {
  entries?: LedgerEntry[]
  total?: number
  view_mode?: DataViewMode | string
  limit?: number
}
