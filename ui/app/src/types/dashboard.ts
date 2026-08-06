export type View = 'live' | 'analytics' | 'trades' | 'console' | 'config'
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
}

export type ConsolePayload = {
  lines?: string[]
  total?: number
}

export type ConfigPayload = {
  fields?: ConfigField[]
  values?: Record<string, string | number | boolean | null>
  secrets?: Array<{ name: string; configured: boolean }>
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
