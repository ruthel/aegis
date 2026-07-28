import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CircleDollarSign,
  Cog,
  EllipsisVertical,
  LayoutDashboard,
  ListChecks,
  Play,
  Power,
  RefreshCw,
  RotateCcw,
  ScrollText,
  Search,
  Server,
  Square,
  Terminal,
  WalletCards,
  Wifi,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useIntl, type IntlShape } from 'react-intl'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { LineChart } from '@/components/charts/LineChart'
import { ScoreHistoryChart, type ScorePoint } from '@/components/charts/ScoreHistoryChart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getJson, postJson } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/store/dashboard-store'
import type { AnalyticsPayload, ConfigPayload, ConsolePayload, JsonMap, MlStatus, StatusPayload, View } from '@/types/dashboard'

const views: Array<{ id: View; path: string; label: string; icon: typeof LayoutDashboard }> = [
  { id: 'live', path: '/', label: 'Live', icon: LayoutDashboard },
  { id: 'analytics', path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'trades', path: '/trades', label: 'Trades', icon: CircleDollarSign },
  { id: 'console', path: '/console', label: 'Console', icon: Terminal },
  { id: 'config', path: '/config', label: 'Config', icon: Cog },
]

const pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']

function num(value: unknown, digits = 2) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--'
}

function pct(value: unknown, digits = 1) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : '--'
}

function formatLivePrice(symbol: string, value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const digits = symbol.startsWith('ADA') || parsed < 1 ? 4 : parsed < 100 ? 3 : 2
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed)
}

function formatLiveVolumeUsd(value: unknown, price: unknown) {
  const parsed = Number(value)
  const parsedPrice = Number(price)
  if (!Number.isFinite(parsed) || !Number.isFinite(parsedPrice) || parsedPrice <= 0) return '--'
  const usdValue = parsed * parsedPrice
  return new Intl.NumberFormat('fr-FR', {
    notation: Math.abs(usdValue) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: Math.abs(usdValue) >= 1000 ? 1 : 2,
  }).format(usdValue)
}

function formatLivePercent(value: unknown, digits = 4, signed = false) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const normalized = Math.abs(parsed) < 0.005 && digits === 2 ? 0 : parsed
  const sign = signed && normalized > 0 ? '+' : ''
  const formatted = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(normalized)
  return `${sign}${formatted}%`
}

function formatSignedPct(value: unknown, digits = 2) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const sign = parsed > 0 ? '+' : ''
  return `${sign}${pct(parsed, digits)}`
}

function formatDateWithRelative(value: unknown) {
  const raw = asString(value, '')
  if (!raw) return '--'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  const diffSeconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000))
  const relative = diffSeconds < 60
    ? `${diffSeconds}s`
    : diffSeconds < 3600
      ? `${Math.floor(diffSeconds / 60)}min`
      : `${Math.floor(diffSeconds / 3600)}h ${Math.floor((diffSeconds % 3600) / 60)}min`
  return `Aujourd'hui · ${parsed.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} · il y a ${relative}`
}

function formatDecisionTime(value: unknown, intl: IntlShape) {
  const raw = asString(value, '')
  if (!raw) return { absolute: 'Date inconnue', relative: '--' }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return { absolute: raw, relative: '--' }

  const absolute = intl.formatDate(parsed, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSeconds)
  const unit = abs < 60 ? 'second' : abs < 3600 ? 'minute' : abs < 86400 ? 'hour' : 'day'
  const divisor = unit === 'second' ? 1 : unit === 'minute' ? 60 : unit === 'hour' ? 3600 : 86400
  const relative = intl.formatRelativeTime(Math.round(diffSeconds / divisor), unit, { numeric: 'auto' })
  return { absolute, relative }
}

function formatTradeTime(value: unknown, intl: IntlShape) {
  const raw = asString(value, '')
  if (!raw) return { absolute: 'Date inconnue', relative: '--' }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return { absolute: raw, relative: '--' }

  const now = new Date()
  const sameDay = parsed.toDateString() === now.toDateString()
  const time = intl.formatTime(parsed, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const date = sameDay
    ? "Aujourd'hui"
    : intl.formatDate(parsed, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })

  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSeconds)
  const unit = abs < 60 ? 'second' : abs < 3600 ? 'minute' : abs < 86400 ? 'hour' : 'day'
  const divisor = unit === 'second' ? 1 : unit === 'minute' ? 60 : unit === 'hour' ? 3600 : 86400
  const relative = intl.formatRelativeTime(Math.round(diffSeconds / divisor), unit, { numeric: 'auto' })

  return { absolute: `${date} · ${time}`, relative }
}

function formatCryptoAmount(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: parsed < 0.01 ? 8 : 4,
    maximumFractionDigits: 8,
  }).format(parsed)
}

function formatTradePnl(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const sign = parsed > 0 ? '+' : ''
  return `${sign}${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} USD`
}

function abbreviateRegime(value: unknown) {
  const clean = asString(value).replaceAll('_', ' ')
  return clean
    .replace(/\bSIDEWAYS DOWN\b/g, 'SIDE. DO.')
    .replace(/\bSIDEWAYS UP\b/g, 'SIDE. UP')
    .replace(/\bSIDEWAYS\b/g, 'SIDE')
    .replace(/\bDOWN\b/g, 'DO.')
}

function asString(value: unknown, fallback = '--') {
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

function parseMetricObject(value: unknown): JsonMap {
  if (!value) return {}
  if (typeof value === 'object') return value as JsonMap
  if (typeof value !== 'string') return {}
  try {
    return JSON.parse(value) as JsonMap
  } catch {
    try {
      return JSON.parse(value.replaceAll("'", '"').replaceAll('True', 'true').replaceAll('False', 'false').replaceAll('None', 'null')) as JsonMap
    } catch {
      return {}
    }
  }
}

function normalizeDecisionMetrics(metrics: unknown): JsonMap {
  const raw = parseMetricObject(metrics)
  return {
    ...raw,
    ml_decision: parseMetricObject(raw.ml_decision),
    ml_inputs: parseMetricObject(raw.ml_inputs),
    ml_exit_entry_forecast: parseMetricObject(raw.ml_exit_entry_forecast),
    market_context: parseMetricObject(raw.market_context),
  }
}

function decisionReasonTitle(reason: unknown) {
  const labels: Record<string, string> = {
    score_below_dynamic_threshold: 'Score marché insuffisant',
    technical_signal_below_threshold: 'Signal technique trop faible',
    technical_signal_not_buy: 'Signal technique sans achat',
    technical_signal_confidence_below_threshold: 'Confiance technique trop faible',
    technical_signal_not_buy_soft: 'Signal technique transmis au ML',
    technical_signal_confidence_below_threshold_soft: 'Confiance technique transmise au ML',
    support_touch_disabled_in_bear_mode: 'Support Touch désactivé en bear mode',
    insufficient_trades: 'Backtest insuffisant',
    total_pnl_below_threshold: 'Profit backtest trop faible',
    avg_pnl_below_threshold: 'Moyenne backtest trop faible',
    winrate_below_threshold: 'Win rate backtest trop faible',
    symbol_cooldown_active: 'Cooldown actif',
    htf_bias_rejected: 'Tendance haute période défavorable',
    outside_optimal_trading_time: 'Hors plage de trading',
    analysis_error: 'Erreur d’analyse',
    order_failed: 'Ordre échoué',
    buy_executed: 'Achat exécuté',
  }
  const key = String(reason || '').split(':')[0]
  return labels[key] || key.replaceAll('_', ' ') || '--'
}

function metricNumber(value: unknown, digits = 1) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--'
}

function durationText(seconds: unknown) {
  const total = Number(seconds) || 0
  const minutes = Math.floor(total / 60)
  const rest = Math.floor(total % 60)
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`
}

function cooldownDurationText(seconds: unknown) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes > 0 && rest > 0) return `${minutes} min ${rest} s`
  if (minutes > 0) return `${minutes} min`
  return `${rest} s`
}

function decisionExplanation(item: JsonMap) {
  const reason = String(item.reason || '')
  const key = reason.split(':')[0]
  const metrics = normalizeDecisionMetrics(item.metrics)
  const mlDecision = metrics.ml_decision as JsonMap
  const mlInputs = metrics.ml_inputs as JsonMap

  if (key.startsWith('ml_filter_rejected') || key.startsWith('support_touch_ml_entry_rejected')) {
    return `ML refuse l’entrée: P_win ${metricNumber(mlDecision.p_win)}% < seuil ${metricNumber(mlDecision.min_p_win)}%. Signal ${asString(mlInputs.technical_action)} ${metricNumber(mlInputs.technical_confidence)}%, score ${metricNumber(mlInputs.crypto_score)}, support ${mlInputs.support_touch ? 'oui' : 'non'}.`
  }
  if (key.startsWith('ml_exit_entry_rejected') || key.startsWith('support_touch_ml_exit_rejected')) {
    return `ML refuse l’entrée car la sortie prévue est fragile: P_continue ${metricNumber(mlDecision.p_continue)}% < seuil ${metricNumber(mlDecision.min_p_continue)}%.`
  }
  if (key === 'symbol_cooldown_active') {
    return `Le bot attend avant de retrader cette paire. Temps restant: ${durationText(metrics.cooldown_remaining_seconds)}.`
  }
  if (key === 'technical_signal_below_threshold') {
    return `Le signal technique ne confirme pas assez l’achat. Confiance ${metricNumber(metrics.confidence)}% / seuil ${metricNumber(metrics.min_confidence)}%.`
  }
  if (item.allowed) {
    if (Object.keys(mlDecision).length) {
      return `Achat autorisé par le ML: P_win ${metricNumber(mlDecision.p_win)}% / seuil ${metricNumber(mlDecision.min_p_win)}%. Signal ${asString(mlInputs.technical_action)}, score ${metricNumber(mlInputs.crypto_score)}, support ${mlInputs.support_touch ? 'oui' : 'non'}.`
    }
    return 'Décision finale enregistrée par le bot.'
  }
  return decisionReasonTitle(reason)
}

function decisionMetricChips(item: JsonMap) {
  const metrics = normalizeDecisionMetrics(item.metrics)
  const mlDecision = metrics.ml_decision as JsonMap
  const mlInputs = metrics.ml_inputs as JsonMap
  const chips: string[] = []
  if (metrics.price !== undefined) chips.push(`Prix ${num(metrics.price, Number(metrics.price) > 100 ? 2 : 4)}`)
  if (metrics.score !== undefined || metrics.min_score !== undefined) chips.push(`Score ${metricNumber(metrics.score)} / ${metricNumber(metrics.min_score)}`)
  if (metrics.confidence !== undefined || metrics.min_confidence !== undefined) chips.push(`Confiance ${metricNumber(metrics.confidence)}% / ${metricNumber(metrics.min_confidence)}%`)
  if (mlDecision.p_win !== undefined) chips.push(`P_win ${metricNumber(mlDecision.p_win)}% / ${metricNumber(mlDecision.min_p_win)}%`)
  if (mlDecision.p_continue !== undefined) chips.push(`P_continue ${metricNumber(mlDecision.p_continue)}% / ${metricNumber(mlDecision.min_p_continue)}%`)
  if (mlInputs.technical_action) chips.push(`Signal ${asString(mlInputs.technical_action)}`)
  if (mlInputs.support_touch) chips.push('Support ML')
  if (metrics.reject_cooldown_seconds !== undefined) chips.push(`Cooldown ${durationText(metrics.reject_cooldown_seconds)}`)
  return chips
}

function App() {
  const {
    setView,
    status,
    ml,
    consoleData,
    config,
    analytics,
    setStatus,
    setMl,
    setConfig,
    loading,
    bootstrap,
    refreshStatus,
    refreshMl,
    refreshConsole,
    refreshConfig,
    refreshAnalytics,
  } = useDashboardStore()
  const location = useLocation()
  const activeView = views.find((item) => item.path === location.pathname)?.id || 'live'
  const bot = status.bot
  const running = Boolean(bot?.control?.running)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    setView(activeView)
    if (activeView === 'console') void refreshConsole()
    if (activeView === 'config') void refreshConfig()
    if (activeView === 'analytics') void refreshAnalytics()
  }, [activeView, refreshAnalytics, refreshConfig, refreshConsole, setView])

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/live`)
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { __type?: string; payload?: unknown; live?: unknown }
        if (payload.__type === 'status') setStatus(payload.payload as StatusPayload)
        if (payload.__type === 'ml_status') setMl(payload.payload as MlStatus)
        if (payload.__type === 'live') setStatus((current) => ({ ...current, live: payload.live as StatusPayload['live'] }))
      } catch {
        // Ignore malformed websocket payloads.
      }
    }
    return () => ws.close()
  }, [setMl, setStatus])

  useEffect(() => {
    const statusTimer = window.setInterval(() => void refreshStatus(), 15000)
    const mlTimer = window.setInterval(() => void refreshMl(), 15000)
    const consoleTimer = window.setInterval(() => {
      if (activeView === 'console') void refreshConsole()
    }, 5000)
    return () => {
      window.clearInterval(statusTimer)
      window.clearInterval(mlTimer)
      window.clearInterval(consoleTimer)
    }
  }, [activeView, refreshConsole, refreshMl, refreshStatus])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-border bg-card/70 p-5 lg:block">
        <div className="mb-6 flex items-center gap-3">
          <img src="/public/brand/aegis-mark-transparent-512.png" alt="" className="h-9 w-9" />
          <div>
            <div className="font-['Outfit'] text-lg font-black">Aegis</div>
            <div className="text-xs uppercase text-muted-foreground">Trading Bot</div>
          </div>
        </div>
        <nav className="space-y-1">
          {views.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.id}
                to={item.path}
                className={({ isActive }) => cn(
                  'flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                  isActive && 'bg-accent text-foreground',
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </aside>

      <main className="lg:pl-60">
        <TopToolbar status={status} running={running} />

        <div className="border-b border-border p-2 lg:hidden">
          <div className="grid grid-cols-5 gap-1">
            {views.map((item) => {
              const Icon = item.icon
              return (
                <Button key={item.id} asChild variant={activeView === item.id ? 'secondary' : 'ghost'} size="sm">
                  <NavLink to={item.path}>
                    <Icon className="h-4 w-4" />
                  </NavLink>
                </Button>
              )
            })}
          </div>
        </div>

        <section className="mx-auto max-w-[1440px] p-4 lg:px-7 lg:pb-10 lg:pt-2">
          {loading && <div className="text-sm text-muted-foreground">Chargement...</div>}
          <Routes>
            <Route path="/" element={<LiveView status={status} ml={ml} />} />
            <Route path="/analytics" element={<AnalyticsView ml={ml} analytics={analytics} />} />
            <Route path="/trades" element={<TradesView />} />
            <Route path="/console" element={<ConsoleView data={consoleData} onRefresh={refreshConsole} />} />
            <Route path="/config" element={<ConfigView config={config} setConfig={setConfig} refresh={refreshConfig} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </section>
      </main>
    </div>
  )
}

function TopToolbar({ status, running }: { status: StatusPayload; running: boolean }) {
  const bot = status.bot
  const liveSymbols = Object.keys(status.live?.symbols || {}).length
  const wsLabel = liveSymbols > 0 ? `WS ${liveSymbols}` : 'WS --'
  const lastUpdate = asString(bot?.last_update, 'Chargement...')

  return (
    <header className="sticky top-0 z-10 mx-auto mb-4 flex min-h-16 max-w-[1440px] items-center justify-between gap-4 bg-background/95 px-4 py-3 backdrop-blur lg:px-7">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-[15px] font-black leading-none">{bot?.name || 'Aegis'}</div>
          <span className="inline-flex h-[18px] items-center gap-1 rounded-full border border-border bg-secondary px-2 text-[10px] font-bold leading-none text-muted-foreground">
            <Wifi className="h-3 w-3" />
            {wsLabel}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground">{lastUpdate}</div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex min-h-[30px] items-center gap-2 rounded-full border border-border bg-secondary px-3 text-[11px] font-bold text-muted-foreground">
            <span className={cn('h-2 w-2 rounded-full', running ? 'bg-emerald-400' : 'bg-rose-400')} />
            <Bot className="h-3.5 w-3.5" />
            {running ? 'bot ON' : 'bot OFF'}
          </span>

          <div className="inline-flex min-h-[30px] items-center overflow-hidden rounded-full border border-border bg-secondary text-[11px] font-bold text-muted-foreground">
            <span className="inline-flex items-center gap-1 px-3">
              <Zap className="h-3.5 w-3.5" />
              {asString(bot?.mode, 'mode')}
            </span>
            <span className="h-4 w-px bg-border" />
            <span className="inline-flex items-center gap-1 px-3">
              <Server className="h-3.5 w-3.5" />
              {asString(bot?.exchange, 'exchange')}
            </span>
          </div>
        </div>

        <BotActions running={running} />
      </div>
    </header>
  )
}

function BotActions({ running }: { running: boolean }) {
  const [pending, setPending] = useState(false)
  const runBotAction = useDashboardStore((state) => state.runBotAction)

  const runAction = async (action: 'start' | 'stop' | 'restart') => {
    setPending(true)
    try {
      await runBotAction(action)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant={running ? 'destructive' : 'default'} size="sm" disabled={pending} onClick={() => void runAction(running ? 'stop' : 'start')}>
        {running ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        {running ? 'Arrêter' : 'Démarrer'}
      </Button>
      <Button variant="outline" size="icon" disabled={pending} onClick={() => void runAction('restart')} title="Redémarrer">
        <RotateCcw className="h-4 w-4" />
      </Button>
    </div>
  )
}

function LiveView({ status, ml }: { status: StatusPayload; ml: MlStatus }) {
  return (
    <div className="space-y-4">
      <MetricsStrip status={status} />
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <LivePrices live={status.live} />
        </div>
        <div className="xl:col-span-4">
          <Cooldowns cooldowns={status.cooldowns || []} />
        </div>
      </div>
      <Positions positions={status.positions || []} live={status.live} />
      <EntryContext status={status} />
      <CoreMlEngine ml={ml} positions={status.positions || []} />
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <DecisionLog decisions={status.decisions || []} />
        </div>
        <div className="xl:col-span-5">
          <Alerts logs={status.logs || []} />
        </div>
      </div>
    </div>
  )
}

function MetricsStrip({ status }: { status: StatusPayload }) {
  const stats = status.stats || {}
  const forecast = status.next_buy_forecast || {}
  const candidate = (forecast.candidate as JsonMap | undefined) || {}
  const totalTrades = Number(stats.total_trades || 0)
  const daysActive = Number(stats.days_active || 0)
  const avgStake = Number(stats.avg_stake || 0)
  const gross = Number(stats.total_pnl_gross || 0)
  const net = Number(stats.total_pnl_net || 0)
  const perTrade = totalTrades > 0 ? net / totalTrades : 0
  const perDay = daysActive > 0 ? net / daysActive : 0

  const formatUsd = (val: number, showPlus = true) => {
    const sign = val > 0 && showPlus ? '+' : ''
    return `${sign}${num(val, 2)} $`
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
      <MetricCard icon={WalletCards} label="Solde Paper" value={`${num(status.balance?.paper_balance, 2)} USD`} />
      <SplitMetricCard
        label="Gain Cumulé"
        leftLabel="PnL Brut"
        leftValue={formatUsd(gross)}
        rightLabel="PnL Net"
        rightValue={formatUsd(net)}
      />
      <SplitMetricCard
        label="Trades & Win Rate"
        leftLabel="Total (W / L)"
        leftValue={`${totalTrades} (${stats.wins ?? 0}/${stats.losses ?? 0})`}
        rightLabel="Taux de Win"
        rightValue={pct(stats.win_rate, 1)}
      />
      <SplitMetricCard
        label="Moyenne Gain"
        leftLabel="Par Trade"
        leftValue={formatUsd(perTrade)}
        rightLabel="Par Jour"
        rightValue={`${perDay >= 0 ? '+' : ''}${num(perDay, 2)} $ / j`}
      />
      <MetricCard icon={CircleDollarSign} label="Rendement / Mise" value={pct(avgStake > 0 ? (net / avgStake) * 100 : 0, 2)} />
      <SplitMetricCard
        label="Prochain Achat Estimé"
        leftLabel={asString(candidate.symbol, '--')}
        leftValue={candidate.p_win != null ? `${pct(candidate.p_win, 1)}` : '--'}
        rightLabel="État"
        rightValue={Boolean(candidate.ready) ? 'Prêt' : 'En attente'}
      />
    </div>
  )
}

function MetricCard({ icon: Icon, label, value }: { icon: typeof LayoutDashboard; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-indigo-500/20 bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[10px] font-bold uppercase text-muted-foreground">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-primary">
          <Icon className="h-4 w-4" />
        </span>
        {label}
      </div>
      <div className="mt-3 text-lg font-black leading-tight">{value}</div>
    </div>
  )
}

function SplitMetricCard({ label, leftLabel, leftValue, rightLabel, rightValue }: { label: string; leftLabel: string; leftValue: string; rightLabel: string; rightValue: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase text-muted-foreground">{label}</div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-[9px] font-bold uppercase text-muted-foreground">{leftLabel}</div>
          <div className="text-base font-black leading-tight">{leftValue}</div>
        </div>
        <div className="h-8 w-px bg-border" />
        <div className="text-right">
          <div className="text-[9px] font-bold uppercase text-muted-foreground">{rightLabel}</div>
          <div className="text-base font-black leading-tight">{rightValue}</div>
        </div>
      </div>
    </div>
  )
}

function LivePrices({ live }: { live?: StatusPayload['live'] }) {
  const symbols = live?.symbols || {}
  const liveCount = Object.keys(symbols).length
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            Marché Live
          </CardTitle>
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] font-semibold text-muted-foreground">Source WebSocket</span>
            <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] font-semibold text-muted-foreground">Temps réel</span>
            <span className="ml-1 text-[11px] text-muted-foreground">{liveCount ? `${liveCount} flux actifs` : 'En attente WS'}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          {pairs.map((symbol) => {
            const item = liveSymbolItem(symbols, symbol)
            const rawChange = Number(item.price_change_since_analysis_percent ?? item.change_24h ?? item.change ?? 0)
            const change = Math.abs(rawChange) < 0.005 ? 0 : rawChange
            const priceValue = Number(item.price)
            const high = item.candle_high ?? item.high_24h ?? item.high
            const bid = item.bid
            const ask = item.ask
            const volume = item.volume_usd ?? item.quote_volume ?? item.volume_24h_usd ?? item.candle_volume_usd
            const baseVolume = item.volume_24h ?? item.candle_volume ?? item.volume
            const spread = item.spread_percent ?? item.spread
            const stale = item.last_tick_age_seconds === undefined || item.last_tick_age_seconds === null ? false : Number(item.last_tick_age_seconds) > 30
            return (
              <div key={symbol} className="min-w-0 rounded-lg border border-border bg-[linear-gradient(145deg,rgba(27,32,38,0.96),rgba(18,22,27,0.98))] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-transform hover:-translate-y-px hover:border-white/20">
                <header className="mb-2.5 flex items-center justify-between gap-2">
                  <h3 className="m-0 truncate text-[13px] font-bold">{symbol}</h3>
                  <div className="flex items-center gap-1.5">
                    <Badge variant={stale ? 'warning' : 'success'} className="px-2 py-0.5 text-[9px]">{stale ? 'stale' : 'live'}</Badge>
                    <Badge variant={change >= 0 ? 'success' : 'danger'}>{formatLivePercent(change, 2, true)}</Badge>
                  </div>
                </header>
                <div className="mb-2 rounded-md border border-white/[0.04] bg-black/15 px-2.5 py-2">
                  <span className="block text-[10px] text-muted-foreground">Prix</span>
                  <strong className="block text-[18px] font-black leading-tight tabular-nums">{formatLivePrice(symbol, priceValue)}</strong>
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  <QuoteBox label="Bid" value={bid !== undefined ? formatLivePrice(symbol, bid) : '--'} />
                  <QuoteBox label="Ask" value={ask !== undefined ? formatLivePrice(symbol, ask) : '--'} />
                  <QuoteBox label="High" value={high !== undefined ? formatLivePrice(symbol, high) : '--'} />
                  <QuoteBox label="Volume USD" value={volume !== undefined ? formatLiveVolumeUsd(volume, 1) : formatLiveVolumeUsd(baseVolume, priceValue)} />
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] font-semibold text-muted-foreground">Spread {spread !== undefined ? formatLivePercent(spread, 2) : '--'}</span>
                  <span className={cn('rounded-full border px-2 py-1 text-[10px] font-semibold', change >= 0 ? 'border-emerald-400/25 bg-emerald-500/15 text-emerald-300' : 'border-rose-400/25 bg-rose-500/15 text-rose-300')}>
                    Mom. {formatLivePercent(change, 2, true)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}

function liveSymbolItem(symbols: Record<string, JsonMap>, symbol: string) {
  const compact = symbol.replace('/', '')
  return symbols[symbol] || symbols[compact] || symbols[compact.replace('USDT', 'USD')] || {}
}

function supportBySymbolMap(support: JsonMap) {
  const mapped: Record<string, JsonMap> = {}
  const pairsList = Array.isArray(support.pairs) ? support.pairs as JsonMap[] : []
  pairsList.forEach((item) => {
    const symbol = asString(item.symbol, '')
    if (!symbol) return
    mapped[symbol] = item
    mapped[symbol.replace('/', '')] = item
  })
  Object.entries(support).forEach(([key, value]) => {
    if (value && typeof value === 'object' && key !== 'pairs' && key !== 'settings') {
      mapped[key] = value as JsonMap
      mapped[key.replace('/', '')] = value as JsonMap
    }
  })
  return mapped
}

function QuoteBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="mb-0.5 block text-[10px] text-muted-foreground">{label}</span>
      <strong className="block break-words text-[13px] font-black">{value}</strong>
    </div>
  )
}

function Cooldowns({ cooldowns }: { cooldowns: JsonMap[] }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Cooldowns</CardTitle>
          <span className="text-[11px] text-muted-foreground">{cooldowns.length} actif{cooldowns.length > 1 ? 's' : ''}</span>
        </div>
      </CardHeader>
      <CardContent className="px-3.5 py-2">
        {cooldowns.length === 0 && <div className="py-2 text-sm text-muted-foreground">Aucun cooldown actif</div>}
        {cooldowns.map((item, index) => (
          <div key={`${asString(item.symbol)}-${index}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-border py-2.5 text-[12.5px] last:border-b-0">
            <div className="min-w-0 overflow-hidden">
              <strong className="block truncate text-[13px]">{asString(item.symbol)}</strong>
              <span className="block truncate text-[11px] text-muted-foreground">Pause dynamique</span>
            </div>
            <Badge variant="warning" className="min-w-[46px] max-w-[76px] shrink-0 justify-center whitespace-nowrap px-2 py-1 text-[9.5px] normal-case tabular-nums">
              {cooldownDurationText(item.remaining_seconds)}
            </Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function Positions({ positions, live }: { positions: JsonMap[]; live?: StatusPayload['live'] }) {
  const runPositionAction = async (symbol: string, action: string) => {
    const payload: JsonMap = { action, symbol }
    if (action.startsWith('pause_')) {
      payload.action = 'pause_pair'
      payload.seconds = Number(action.replace('pause_', ''))
    }
    await postJson('/api/bot/command', payload)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Positions</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full min-w-[1240px] border-collapse text-left">
          <thead className="bg-secondary text-[11px] uppercase tracking-wide text-muted-foreground">
            <tr>
              {['Symbole', 'Quantité', 'Prix Moyen', 'Objectif', 'Entrée', 'Actuel', 'Frais', 'P&L Brut', 'P&L Net', ''].map((head) => (
                <th key={head} className="border-b border-border px-3.5 py-3 font-semibold whitespace-nowrap">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 && (
              <tr>
                <td className="px-3.5 py-3 text-muted-foreground" colSpan={10}>Aucune position ouverte</td>
              </tr>
            )}
            {positions.map((position, index) => {
              const symbol = asString(position.symbol)
              const normKey = symbol.replace('/', '')
              const liveInfo = live?.symbols?.[symbol] ?? live?.symbols?.[normKey]
              const livePrice = liveInfo?.price ?? position.current_price
              const avgEntry = position.avg_entry_price ?? position.price
              const entryValue = Number(position.entry_value ?? 0)
              const feePct = Number(position.trading_fee_pct ?? 0.2)
              const feeValue = Number(position.trading_fee_value ?? position.fee ?? 0)
              const livePriceNumber = Number(livePrice)
              const amount = Number(position.amount ?? position.position_size_crypto ?? 0)
              const hasLivePnl = Number.isFinite(livePriceNumber) && Number.isFinite(entryValue) && entryValue > 0 && amount > 0
              const currentValue = hasLivePnl ? amount * livePriceNumber : Number(position.current_value)
              const hasCurrentValue = Number.isFinite(currentValue)
              const pnlGross = hasLivePnl ? Number(currentValue) - entryValue : position.pnl_gross ?? position.pnl
              const pnlGrossPct = hasLivePnl ? (Number(pnlGross) / entryValue) * 100 : position.pnl_gross_pct
              const pnlNet = hasLivePnl ? Number(pnlGross) - feeValue : position.pnl_net ?? position.pnl_net_pct
              const pnlNetPct = hasLivePnl ? (Number(pnlNet) / entryValue) * 100 : position.pnl_net_pct
              const hasPnl = Number.isFinite(Number(pnlGross)) && Number.isFinite(Number(pnlNet))
              const signed = (value: unknown, digits = 2) => {
                const parsed = Number(value)
                return Number.isFinite(parsed) ? `${parsed >= 0 ? '+' : ''}${parsed.toFixed(digits)}` : '--'
              }
              return (
                <tr key={`${symbol}-${index}`} className="border-b border-border text-[12.5px] hover:bg-white/[0.02]">
                  <td className="px-3.5 py-3 font-bold whitespace-nowrap">{symbol}</td>
                  <td className="px-3.5 py-3 whitespace-nowrap">{num(amount, 6)}</td>
                  <td className="px-3.5 py-3 whitespace-nowrap">{num(avgEntry, 4)}</td>
                  <td className="px-3.5 py-3 whitespace-nowrap">
                    {num(avgEntry, 4)} <span className="mx-1 text-muted-foreground">→</span>
                    <strong className="text-emerald-300">{num(position.target_price ?? position.exit_price, 4)}</strong>
                  </td>
                  <td className="px-3.5 py-3 whitespace-nowrap">{num(entryValue, 2)} USD</td>
                  <td className="px-3.5 py-3 whitespace-nowrap">{!hasCurrentValue ? '--' : `${num(currentValue, 2)} USD`}</td>
                  <td className="px-3.5 py-3 font-medium text-muted-foreground whitespace-nowrap">{num(feeValue, 2)} USD ({num(feePct, 2)}%)</td>
                  <td className="px-3.5 py-3 whitespace-nowrap">
                    <Badge variant={Number(pnlGross ?? 0) >= 0 ? 'success' : 'danger'}>
                      {hasPnl ? `${signed(pnlGross)} (${signed(pnlGrossPct)}%)` : '--'}
                    </Badge>
                  </td>
                  <td className="px-3.5 py-3 whitespace-nowrap">
                    <Badge variant={Number(pnlNet ?? 0) >= 0 ? 'success' : 'danger'}>
                      {hasPnl ? `${signed(pnlNet)} (${signed(pnlNetPct)}%)` : '--'}
                    </Badge>
                  </td>
                  <td className="px-3.5 py-3 text-right whitespace-nowrap">
                    <Select value="" onValueChange={(value) => void runPositionAction(symbol, value)}>
                      <SelectTrigger aria-label={`Actions ${symbol}`} className="h-8 min-w-9 justify-center px-2 [&>svg:last-child]:hidden">
                        <SelectValue placeholder={<EllipsisVertical className="h-4 w-4" />} />
                      </SelectTrigger>
                      <SelectContent align="end">
                        <SelectItem value="force_sell">Vendre</SelectItem>
                        <SelectItem value="pause_900">Pause 15 min</SelectItem>
                        <SelectItem value="pause_3600">Pause 1 heure</SelectItem>
                        <SelectItem value="pause_14400">Pause 4 heures</SelectItem>
                        <SelectItem value="pause_86400">Pause 24 heures</SelectItem>
                      </SelectContent>
                    </Select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function CoreMlEngine({ ml, positions }: { ml: MlStatus; positions: JsonMap[] }) {
  const predictions = ml.live_predictions || {}
  const analytics = ml.analytics || {}
  const positionBySymbol = useMemo(() => {
    const mapped: Record<string, JsonMap> = {}
    positions.forEach((position) => {
      const symbol = asString(position.symbol, '')
      if (!symbol) return
      mapped[symbol] = position
      mapped[symbol.replace('/', '')] = position
    })
    return mapped
  }, [positions])
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle className="flex items-center gap-2">
              <Power className="h-4 w-4 text-primary" />
              Core ML Engine
              <Badge variant={ml.is_trained ? 'success' : 'danger'} className="ml-1">
                {ml.is_trained ? 'Filtre Actif (En Direct)' : 'Non entraîné'}
              </Badge>
            </CardTitle>
            <span className="text-[11px] text-muted-foreground">
              Entraîné sur {ml.total_samples || 0} trades 2026 (Features Multi-Timeframe)
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {pairs.map((symbol) => {
            const item = predictions[symbol] || {}
            const openPosition = positionBySymbol[symbol] || positionBySymbol[symbol.replace('/', '')]
            const exitRec = (openPosition?.exit_recommendation || {}) as JsonMap
            const mlExit = (exitRec.ml_exit || {}) as JsonMap
            const inSellMode = Boolean(openPosition)
            const pWin = Number(item.p_win ?? 0)
            const pContinue = Number(mlExit.p_continue ?? asString(exitRec.reason).match(/ml_continue_([\d.]+)%/)?.[1] ?? 0)
            const rec = asString(item.recommendation, 'NEUTRAL')
            const exitDecision = asString(exitRec.decision, 'HOLD').toUpperCase()
            const variant = inSellMode
              ? exitDecision === 'FORCE_EXIT' ? 'danger' : 'success'
              : rec === 'BUY_HIGH_CONFIDENCE' ? 'success' : rec === 'REJECT_RISK' ? 'danger' : 'warning'
            const label = inSellMode
              ? exitDecision === 'FORCE_EXIT' ? 'VENTE ML' : 'POSITION OUVERTE'
              : rec === 'BUY_HIGH_CONFIDENCE' ? 'ACHAT RECOMMANDÉ' : rec === 'REJECT_RISK' ? 'RISQUE ÉLEVÉ (<50%)' : 'NEUTRE (50-65%)'
            const color = inSellMode
              ? exitDecision === 'FORCE_EXIT' ? '#ef4444' : '#10b981'
              : rec === 'BUY_HIGH_CONFIDENCE' ? '#10b981' : rec === 'REJECT_RISK' ? '#ef4444' : '#f59e0b'
            const shownProbability = inSellMode ? pContinue : pWin
            return (
              <div
                key={symbol}
                className="rounded-lg border border-border bg-background/80 p-3"
                style={{ borderLeft: `3px solid ${color}` }}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <strong className="text-[13px]">{symbol}</strong>
                  <Badge variant={variant} className="px-2 py-0.5 text-[10px]">{label}</Badge>
                </div>
                <div className="mb-1 flex justify-between text-[11px]">
                  <span className="text-muted-foreground">{inSellMode ? 'Probabilité de continuer (P_continue)' : 'Probabilité de Gain (P_win)'}</span>
                  <span className="font-black" style={{ color }}>{pct(shownProbability, 1)}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full transition-all" style={{ width: `${Math.max(0, Math.min(100, shownProbability))}%`, background: color }} />
                </div>
                <div className="mt-3 flex justify-between text-[10px] text-muted-foreground">
                  <span>{inSellMode ? `Décision sortie: ${exitDecision}` : `Seuil Requis: ${num(item.min_probability ?? ml.min_probability, 0)}%`}</span>
                  {inSellMode && <span>PnL net {formatSignedPct(exitRec.net_pnl_pct, 2)}</span>}
                </div>
              </div>
            )
          })}
        </div>

        <div className="mt-4 border-t border-border pt-3">
          <h3 className="mb-3 text-[11px] font-bold uppercase text-muted-foreground">
            Analytics Quantitatives & Prévisions IA (Dataset 2026)
          </h3>
          <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
            <MlAnalyticsTile label="Précision Hors-Échantillon" value={`${num(analytics.test_precision, 1)}% Test`} tone="good" />
            <MlAnalyticsTile label="Gain / Perte Moyen Net" value={`+${num(analytics.avg_win, 2)}% / ${num(analytics.avg_loss, 2)}%`} />
            <MlAnalyticsTile label="Risk-Reward & Profit Factor" value={`${num(analytics.risk_reward, 2)}x (PF ${num(analytics.profit_factor, 2)})`} tone="info" />
            <MlAnalyticsTile label="Meilleur Jour Découvert" value={asString(analytics.best_day)} tone="warn" />
            <MlAnalyticsTile label="Heures Idéales Trading" value={asString(analytics.best_hours)} />
            <MlAnalyticsTile label="Prévision Hebdo" value={`${asString(analytics.weekly_forecast_pct)} · ${asString(analytics.weekly_forecast_usd)}`} tone="good" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function MlAnalyticsTile({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' | 'info' }) {
  const color = tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : tone === 'info' ? 'text-blue-300' : 'text-foreground'
  return (
    <div className="rounded-md border border-border bg-white/[0.03] p-2.5">
      <span className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">{label}</span>
      <span className={cn('text-[13px] font-black', color)}>{value}</span>
    </div>
  )
}

function EntryContext({ status }: { status: StatusPayload }) {
  const context = status.market_context || {}
  const support = status.support_touch || {}
  const supportBySymbol = supportBySymbolMap(support)
  const runBacktest = async () => {
    await postJson<JsonMap>('/api/support_touch/run_backtest')
  }
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>Contexte d'entrée</CardTitle>
            <span className="text-[11px] text-muted-foreground">
              {status.support_touch?.last_run ? `Backtest ${formatDateWithRelative(status.support_touch.last_run)}` : 'Backtest --'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={() => void runBacktest()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Lancer Backtest
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
        {pairs.map((symbol) => {
          const ctx = context[symbol] || {}
          const st = supportBySymbol[symbol] || supportBySymbol[symbol.replace('/', '')] || {}
          const regime = abbreviateRegime(ctx.symbol_regime ?? st.regime ?? 'UNKNOWN')
          const knife = Boolean(ctx.falling_knife_active ?? (ctx.falling_knife as JsonMap | undefined)?.is_falling)
          const symbolBear = Boolean(ctx.symbol_bear || ctx.bear_mode)
          const isBull = regime.includes('BULL') || regime.includes('UP')
          const isBear = regime.includes('BEAR') || regime.includes('DOWN') || symbolBear || knife
          const topGradient = isBear
            ? 'linear-gradient(90deg,#fbbf24,#fb7185)'
            : isBull
              ? 'linear-gradient(90deg,#34d399,#2dd4bf)'
              : 'linear-gradient(90deg,#60a5fa,#6366f1)'
          const modeBadge = isBear ? 'BEAR' : isBull ? 'BULL' : regime.includes('SIDE') ? 'RANGE' : 'UNKNOWN'
          const momentum = ctx.symbol_momentum_percent ?? ctx.btc_momentum_percent
          const retour = Boolean(ctx.reversal_confirmed ?? (ctx.reversal as JsonMap | undefined)?.confirmed)
          return (
            <section
              key={symbol}
              className="relative overflow-hidden rounded-lg border border-white/[0.055] bg-[linear-gradient(135deg,rgba(23,27,32,0.62),rgba(17,20,24,0.86))] p-3.5 transition-transform hover:-translate-y-px hover:border-white/15"
            >
              <div className="absolute inset-x-0 top-0 h-[3px]" style={{ background: topGradient }} />
              <header className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <h3 className="m-0 text-[14px] font-black leading-tight">{symbol}</h3>
                  <div className="mt-0.5 text-[12px] font-semibold text-muted-foreground">{abbreviateRegime(ctx.btc_regime ?? '--')}</div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge variant={isBear ? 'danger' : isBull ? 'success' : 'warning'} className="min-h-5 px-2 text-[9px]">
                    {modeBadge}
                  </Badge>
                </div>
              </header>

              <div className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-2.5">
                <div className="min-w-0">
                  <div className="mb-2 text-[9px] font-black uppercase text-muted-foreground">Support Touch</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <EntryBox label="Trades" value={st.trades} />
                    <EntryBox label="Win" value={st.win_rate !== undefined ? pct(st.win_rate, 1) : '--'} />
                    <EntryBox label="Total" value={st.total_pnl_percent !== undefined ? formatSignedPct(st.total_pnl_percent, 2) : st.total_pnl !== undefined ? formatSignedPct(st.total_pnl, 2) : '--'} />
                    <EntryBox label="Moy." value={st.avg_pnl_percent !== undefined ? formatSignedPct(st.avg_pnl_percent, 2) : st.avg_pnl !== undefined ? formatSignedPct(st.avg_pnl, 2) : '--'} />
                  </div>
                </div>

                <div className="min-w-0">
                  <div className="mb-2 text-[9px] font-black uppercase text-muted-foreground">Régime Marché</div>
                  <div className="mb-2 flex items-center justify-between rounded-md border border-white/[0.04] bg-white/[0.018] px-2.5 py-2">
                    <div>
                      <span className="block text-[9px] uppercase text-muted-foreground">Symbole</span>
                      <strong className={cn('block text-[14px] font-black', isBear ? 'text-rose-300' : isBull ? 'text-emerald-300' : 'text-amber-300')}>
                        {regime}
                      </strong>
                    </div>
                    <span className={cn('rounded-full border px-2 py-1 text-[10px] font-black', Number(momentum || 0) >= 0 ? 'border-emerald-400/25 bg-emerald-500/15 text-emerald-300' : 'border-rose-400/25 bg-rose-500/15 text-rose-300')}>
                      {momentum !== undefined ? formatLivePercent(momentum, 3) : '--'}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <EntryBox label="Protection" value={`${num(ctx.trade_multiplier ?? 1, 2)}x`} tone="good" />
                    <EntryBox label="Retour" value={retour ? 'OUI' : 'NON'} tone={retour ? 'good' : undefined} />
                  </div>
                </div>
              </div>

              <div className="mt-2.5 flex flex-wrap gap-1.5">
                <Badge variant={knife ? 'danger' : 'secondary'} className="min-h-5 px-2 text-[9px]">Knife: {knife ? 'OUI' : 'NON'}</Badge>
                <Badge variant="success" className="min-h-5 px-2 text-[9px]">Plein Régime</Badge>
              </div>
            </section>
          )
        })}
      </CardContent>
    </Card>
  )
}

function EntryBox({ label, value, tone }: { label: string; value: unknown; tone?: 'good' }) {
  return (
    <div className="rounded-md border border-white/[0.04] bg-white/[0.018] px-2 py-1.5">
      <div className="text-[9px] uppercase text-muted-foreground">{label}</div>
      <strong className={cn('block text-[13px] font-black leading-tight', tone === 'good' && 'text-emerald-300')}>{asString(value)}</strong>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-border bg-card p-2">
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="text-sm font-black">{asString(value)}</div>
    </div>
  )
}

function DecisionLog({ decisions }: { decisions: JsonMap[] }) {
  const intl = useIntl()
  const visible = decisions.slice(-20).reverse()
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" />
            Décisions
          </CardTitle>
          <Select defaultValue="20">
            <SelectTrigger aria-label="Nombre de décisions affichées">
              <SelectValue placeholder="20 dernières" />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="20">20 dernières</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="max-h-[420px] overflow-y-auto px-4 py-2">
        {decisions.length === 0 && <div className="text-sm text-muted-foreground">Aucune décision récente</div>}
        {visible.map((item, index) => {
          const allowed = Boolean(item.allowed)
          const chips = decisionMetricChips(item)
          const time = formatDecisionTime(item.timestamp, intl)
          return (
            <div key={`${asString(item.timestamp)}-${index}`} className="border-b border-border py-3.5 last:border-b-0">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <strong className="block truncate text-[13px] leading-tight">
                    {asString(item.symbol)} · {decisionReasonTitle(item.reason)}
                  </strong>
                  <span className="mt-1 block text-[11px] text-muted-foreground">
                    {asString(item.action)} · {time.absolute} · {time.relative}
                  </span>
                </div>
                <Badge variant={allowed ? 'success' : 'danger'} className="shrink-0">{allowed ? 'autorisé' : 'bloqué'}</Badge>
              </div>
              <p className="text-[12px] leading-[1.5] text-muted-foreground">{decisionExplanation(item)}</p>
              {chips.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {chips.map((chip) => (
                    <span key={chip} className="min-h-5 rounded-full border border-blue-400/25 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold text-blue-200">
                      {chip}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        {decisions.length > visible.length && (
          <p className="py-2 text-center text-[11px] text-muted-foreground">+{decisions.length - visible.length} décision(s) plus ancienne(s) masquée(s)</p>
        )}
      </CardContent>
    </Card>
  )
}

function Alerts({ logs }: { logs: string[] }) {
  const visibleLogs = logs.slice(-20).reverse()
  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Alertes</CardTitle>
          <span className="text-[11px] text-muted-foreground">{visibleLogs.length} dernières</span>
        </div>
      </CardHeader>
      <CardContent className="max-h-[420px] overflow-y-auto px-4 py-2">
        {visibleLogs.length === 0 && <div className="py-2 text-sm text-muted-foreground">Aucune alerte récente</div>}
        {visibleLogs.map((line, index) => {
          const match = /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*(.*)$/.exec(line)
          const body = match ? match[2] : line
          const tone = body.includes('Erreur') || body.includes('failed') || body.includes('bloqué')
            ? 'text-rose-300'
            : body.includes('⚠️') || body.includes('warning') || body.includes('détecté')
              ? 'text-amber-300'
              : body.includes('✅') || body.includes('autorisé')
                ? 'text-emerald-300'
                : 'text-muted-foreground'
          return (
            <div key={`${line}-${index}`} className="border-b border-border py-2 last:border-b-0">
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="text-[11px] font-semibold text-muted-foreground">{match ? match[1] : 'Date inconnue'}</span>
                <span className="h-1.5 w-1.5 rounded-full bg-primary/70" />
              </div>
              <p className={cn('text-[12px] leading-[1.5]', tone)}>{body || line}</p>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function AnalyticsView({ ml, analytics }: { ml: MlStatus; analytics: AnalyticsPayload }) {
  const advanced = analytics.advanced_metrics || {}
  const capital = analytics.capital_breakdown || {}
  const pnlHistory = analytics.pnl_history || {}
  const heatmap = analytics.heatmap || {}
  const mlAnalytics = ml.analytics || {}
  const pnlPoints = useMemo(() => (pnlHistory.history || []).map((item, index) => ({
    label: `#${index + 1}`,
    value: Number(item.pnl ?? 0),
    event: asString(item.event ?? `Événement #${index + 1}`),
    balance: Number(item.balance ?? 1000),
    time: asString(item.time ?? ''),
  })), [pnlHistory.history])

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard icon={BarChart3} label="Sharpe Ratio" value={num(advanced.sharpe_ratio, 2)} />
        <MetricCard icon={CircleDollarSign} label="Profit Factor" value={num(advanced.profit_factor ?? mlAnalytics.profit_factor, 2)} />
        <MetricCard icon={Activity} label="Max Drawdown" value={pct(advanced.max_drawdown, 2)} />
        <MetricCard icon={Zap} label="Kelly %" value={pct(advanced.kelly_percent, 2)} />
        <MetricCard icon={Power} label="Expectancy" value={num(advanced.expectancy ?? mlAnalytics.expectancy, 2)} />
        <SplitMetricCard
          label="Avg Win / Avg Loss"
          leftLabel="Avg Win"
          leftValue={pct(advanced.avg_win ?? mlAnalytics.avg_win, 2)}
          rightLabel="Avg Loss"
          rightValue={pct(advanced.avg_loss ?? mlAnalytics.avg_loss, 2)}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Capital Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <CapitalBreakdown capital={capital} />
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-12 border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="text-lg font-bold flex items-center gap-2">
                  📈 Historique P&L Net (PnL History)
                </CardTitle>
                <div className="flex flex-wrap items-center gap-4 pt-1.5 text-xs">
                  <span className="flex items-center gap-1.5 font-semibold text-emerald-400">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" /> Axe Y (Vertical) : P&L Net Cumulé ($ USD)
                  </span>
                  <span className="flex items-center gap-1.5 font-semibold text-blue-400">
                    <span className="h-2 w-2 rounded-full bg-blue-400" /> Axe X (Horizontal) : Événements & Trades (N°)
                  </span>
                </div>
              </div>
              <div className="text-left sm:text-right border-t sm:border-t-0 border-border/60 pt-2 sm:pt-0">
                <span className="text-xs font-semibold text-muted-foreground block">
                  Solde initial : {num(pnlHistory.initial_balance, 2)} $ → Actuel : {num(pnlHistory.current_balance, 2)} $
                </span>
                <span className={cn('text-xs font-bold', Number(pnlHistory.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                  P&L Total : {Number(pnlHistory.total_pnl || 0) >= 0 ? '+' : ''}{num(pnlHistory.total_pnl, 2)} USD
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {pnlPoints.length > 1 ? (
              <LineChart
                data={pnlPoints}
                color={Number(pnlHistory.total_pnl || 0) >= 0 ? '#34d399' : '#fb7185'}
                yAxisTitle="P&L Net Cumulé ($ USD)"
                xAxisTitle="Chronologie des Trades & Événements (N° Événement)"
              />
            ) : (
              <EmptyAnalytics text="Pas assez de trades pour afficher l'historique P&L" />
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-12">
          <CardHeader>
            <CardTitle>Historique des Scores Crypto</CardTitle>
          </CardHeader>
          <CardContent>
            <ScoreHistoryPanel />
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Heatmap par Crypto</CardTitle>
          </CardHeader>
          <CardContent>
            <HeatmapList rows={heatmap.by_crypto || []} labelKey="symbol" />
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Par Jour</CardTitle>
          </CardHeader>
          <CardContent>
            <HeatmapList rows={heatmap.by_day || []} labelKey="day" compact />
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Par Heure</CardTitle>
          </CardHeader>
          <CardContent className="max-h-[340px] overflow-y-auto">
            <HeatmapList rows={heatmap.by_hour || []} labelKey="hour" compact />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function CapitalBreakdown({ capital }: { capital: JsonMap }) {
  const total = Number(capital.total_capital || 0)
  const available = Number(capital.available || 0)
  const positions = Number(capital.in_positions || 0)
  const limitOrders = Number(capital.in_limit_orders || 0)
  const pctAvailable = total > 0 ? (available / total) * 100 : 0
  const pctPositions = total > 0 ? (positions / total) * 100 : 0
  const pctLimit = total > 0 ? (limitOrders / total) * 100 : 0

  return (
    <div className="space-y-4">
      <div className="h-4 overflow-hidden rounded-full bg-muted">
        <div className="flex h-full">
          <div className="bg-emerald-400/80" style={{ width: `${pctAvailable}%` }} />
          <div className="bg-indigo-400/80" style={{ width: `${pctPositions}%` }} />
          <div className="bg-amber-400/80" style={{ width: `${pctLimit}%` }} />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Total" value={`${num(total, 2)} USD`} />
        <Metric label="Disponible" value={`${num(available, 2)} USD`} />
        <Metric label="Positions" value={`${num(positions, 2)} USD`} />
        <Metric label="Limit Orders" value={`${num(limitOrders, 2)} USD`} />
      </div>
    </div>
  )
}

function ScoreHistoryPanel() {
  const [symbol, setSymbol] = useState('BTC/USD')
  const [hours, setHours] = useState('24')
  const [scores, setScores] = useState<JsonMap[]>([])

  useEffect(() => {
    const params = new URLSearchParams({ symbol, hours })
    void getJson<JsonMap[]>(`/api/analytics/scores?${params.toString()}`)
      .then((data) => setScores(Array.isArray(data) ? data : []))
      .catch(() => setScores([]))
  }, [symbol, hours])

  const selectedHours = Number(hours)
  const labelSpacingHours = selectedHours <= 12 ? 2 : selectedHours <= 24 ? 4 : selectedHours <= 72 ? 12 : 24
  const points: ScorePoint[] = useMemo(() => {
    const compactTimeOnly = selectedHours <= 24
    const rawPoints = [...scores]
      .sort((a, b) => {
        const left = new Date(asString(a.timestamp, '')).getTime()
        const right = new Date(asString(b.timestamp, '')).getTime()
        return (Number.isFinite(left) ? left : 0) - (Number.isFinite(right) ? right : 0)
      })
      .map((item) => {
        const date = new Date(asString(item.timestamp, ''))
        const timestamp = Number.isNaN(date.getTime()) ? 0 : date.getTime()
        const tooltipLabel = Number.isNaN(date.getTime()) ? '' : scoreTooltipLabel(date, compactTimeOnly)
        return {
          time: timestamp,
          tooltipLabel,
          score: Number(item.score ?? 0),
          rawScore: Number(item.score ?? 0),
          price: Number(item.price ?? 0),
        }
      })
      .filter((item) => item.time > 0)

    const windowSize = selectedHours <= 12 ? 3 : selectedHours <= 24 ? 5 : selectedHours <= 72 ? 7 : 9
    const half = Math.floor(windowSize / 2)
    return rawPoints.map((item, index) => {
      const slice = rawPoints.slice(Math.max(0, index - half), Math.min(rawPoints.length, index + half + 1))
      const smoothScore = slice.reduce((sum, point) => sum + point.score, 0) / Math.max(1, slice.length)
      return {
        ...item,
        score: Math.round(smoothScore * 10) / 10,
      }
    })
  }, [scores, selectedHours])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger aria-label="Symbole score crypto" className="min-w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            {pairs.map((pair) => (
              <SelectItem key={pair} value={pair}>{pair}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={hours} onValueChange={setHours}>
          <SelectTrigger aria-label="Période score crypto" className="min-w-[100px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="12">12 heures</SelectItem>
            <SelectItem value="24">24 heures</SelectItem>
            <SelectItem value="72">3 jours</SelectItem>
            <SelectItem value="168">7 jours</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="min-h-[240px] rounded-md bg-background p-4">
        {points.length >= 2 ? <ScoreHistoryChart data={points} intervalHours={labelSpacingHours} periodHours={selectedHours} /> : <EmptyAnalytics text="Pas assez de scores historisés pour cette période" />}
      </div>
    </div>
  )
}

function scoreTooltipLabel(date: Date, compactTimeOnly: boolean) {
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  if (compactTimeOnly) return `${hour}:${minute}`
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${month}/${day} ${hour}:${minute}`
}

function HeatmapList({ rows, labelKey, compact = false }: { rows: JsonMap[]; labelKey: string; compact?: boolean }) {
  if (!rows.length) return <EmptyAnalytics text="Aucune donnée" />
  return (
    <div className="space-y-2">
      {rows.map((row, index) => {
        const pnl = Number(row.total_pnl ?? row.pnl ?? 0)
        return (
          <div key={`${asString(row[labelKey])}-${index}`} className="flex items-center justify-between rounded-md border border-border bg-background p-3">
            <div>
              <strong className={compact ? 'text-xs' : 'text-sm'}>{asString(row[labelKey])}</strong>
              <div className="text-[10px] text-muted-foreground">{asString(row.trades ?? row.count ?? 0)} trades</div>
            </div>
            <div className={cn('font-black', pnl >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
              {pnl >= 0 ? '+' : ''}{num(pnl, 4)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function EmptyAnalytics({ text }: { text: string }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center rounded-md bg-background text-sm text-muted-foreground">
      {text}
    </div>
  )
}

type SortOrder = 'asc' | 'desc'

function TradesView() {
  const [activeTab, setActiveTab] = useState<'trades' | 'buys' | 'sells'>('trades')
  const [trades, setTrades] = useState<JsonMap[]>([])
  const [buys, setBuys] = useState<JsonMap[]>([])
  const [sells, setSells] = useState<JsonMap[]>([])
  const [symbol, setSymbol] = useState('')
  const intl = useIntl()

  // Pagination State
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [pageSize, setPageSize] = useState<number>(10)

  // Tri par défaut : par Date DESC (plus récent en haut)
  const [sortField, setSortField] = useState<string>('date')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  // Filtres par colonne
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({
    date: '',
    symbol: '',
    status: '',
    buy_price: '',
    sell_price: '',
    price: '',
    amount: '',
    usd_value: '',
    pnl: '',
  })

  // Réinitialiser la page à 1 dès qu'un filtre, le tri ou la taille de page change
  useEffect(() => {
    setCurrentPage(1)
  }, [activeTab, symbol, columnFilters, sortField, sortOrder, pageSize])

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      if (['date', 'buy_price', 'sell_price', 'price', 'amount', 'usd_value', 'pnl'].includes(field)) {
        setSortOrder('desc')
      } else {
        setSortOrder('asc')
      }
    }
  }

  const handleFilterChange = (field: string, value: string) => {
    setColumnFilters((prev) => ({ ...prev, [field]: value }))
  }

  const clearAllFilters = () => {
    setColumnFilters({
      date: '',
      symbol: '',
      status: '',
      buy_price: '',
      sell_price: '',
      price: '',
      amount: '',
      usd_value: '',
      pnl: '',
    })
    setSymbol('')
  }

  const hasActiveFilters = symbol !== '' || Object.values(columnFilters).some((v) => v.trim() !== '')

  useEffect(() => {
    const params = symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''
    void getJson<{ trades?: JsonMap[]; buys?: JsonMap[]; sells?: JsonMap[] }>(`/api/trades${params}`)
      .then((data) => {
        setTrades(data.trades || [])
        setBuys(data.buys || [])
        setSells(data.sells || [])
      })
      .catch(() => {
        setTrades([])
        setBuys([])
        setSells([])
      })
  }, [symbol])

  // Helper pour filtrer et trier
  const processItems = (rawItems: JsonMap[], tab: 'trades' | 'buys' | 'sells') => {
    let result = [...rawItems]

    // 1. Filtrage par colonne
    result = result.filter((item) => {
      // Date filter
      if (columnFilters.date) {
        const time = formatTradeTime(
          item.timestamp ?? item.buy_time ?? item.closed_at ?? item.sell_time,
          intl
        )
        const dateText = `${time.absolute} ${time.relative}`.toLowerCase()
        if (!dateText.includes(columnFilters.date.toLowerCase())) return false
      }

      // Symbol filter
      if (columnFilters.symbol) {
        const symStr = asString(item.symbol).toLowerCase()
        if (!symStr.includes(columnFilters.symbol.toLowerCase())) return false
      }

      // Statut filter
      if (columnFilters.status) {
        let statusStr = ''
        if (tab === 'trades') {
          statusStr = item.status === 'open' ? 'open' : 'closed'
        } else if (tab === 'sells') {
          statusStr = item.status === 'opened' ? 'open' : 'executed'
        } else {
          statusStr = asString(item.status || 'executed')
        }
        if (!statusStr.toLowerCase().includes(columnFilters.status.toLowerCase())) return false
      }

      // Price filter (buy_price or price)
      if (columnFilters.buy_price || columnFilters.price) {
        const query = (columnFilters.buy_price || columnFilters.price).toLowerCase()
        const px = String(item.buy_price ?? item.price ?? '')
        if (!px.toLowerCase().includes(query)) return false
      }

      // Sell Price filter
      if (columnFilters.sell_price) {
        const query = columnFilters.sell_price.toLowerCase()
        const px = String(item.sell_price ?? item.target_price ?? '')
        if (!px.toLowerCase().includes(query)) return false
      }

      // Amount filter
      if (columnFilters.amount) {
        const query = columnFilters.amount.toLowerCase()
        const amt = String(item.amount ?? '')
        if (!amt.toLowerCase().includes(query)) return false
      }

      // USD Value filter
      if (columnFilters.usd_value) {
        const query = columnFilters.usd_value.toLowerCase()
        const px = Number(item.price || 0)
        const amt = Number(item.amount || 0)
        const valStr = (px * amt).toFixed(2)
        if (!valStr.includes(query)) return false
      }

      // PnL filter
      if (columnFilters.pnl) {
        const query = columnFilters.pnl.toLowerCase()
        if (item.status === 'open') {
          if (!'en cours'.includes(query) && !'open'.includes(query)) return false
        } else {
          const pnlVal = String(item.pnl ?? item.pnl_net ?? '')
          if (!pnlVal.toLowerCase().includes(query)) return false
        }
      }

      return true
    })

    // 2. Tri par colonne (Date DESC par défaut)
    result.sort((a, b) => {
      let valA: any
      let valB: any

      switch (sortField) {
        case 'date': {
          const rawA = a.timestamp ?? a.buy_time ?? a.closed_at ?? a.sell_time
          const rawB = b.timestamp ?? b.buy_time ?? b.closed_at ?? b.sell_time
          valA = rawA ? new Date(asString(rawA)).getTime() : 0
          valB = rawB ? new Date(asString(rawB)).getTime() : 0
          break
        }
        case 'symbol': {
          valA = asString(a.symbol)
          valB = asString(b.symbol)
          break
        }
        case 'status': {
          valA = asString(a.status)
          valB = asString(b.status)
          break
        }
        case 'buy_price':
        case 'price': {
          valA = Number(a.buy_price ?? a.price ?? 0)
          valB = Number(b.buy_price ?? b.price ?? 0)
          break
        }
        case 'sell_price': {
          valA = Number(a.sell_price ?? a.target_price ?? 0)
          valB = Number(b.sell_price ?? b.target_price ?? 0)
          break
        }
        case 'amount': {
          valA = Number(a.amount ?? 0)
          valB = Number(b.amount ?? 0)
          break
        }
        case 'usd_value': {
          valA = Number(a.price || 0) * Number(a.amount || 0)
          valB = Number(b.price || 0) * Number(b.amount || 0)
          break
        }
        case 'pnl': {
          valA = a.status === 'open' ? -999999999 : Number(a.pnl ?? a.pnl_net ?? 0)
          valB = b.status === 'open' ? -999999999 : Number(b.pnl ?? b.pnl_net ?? 0)
          break
        }
        default: {
          valA = 0
          valB = 0
        }
      }

      if (valA < valB) return sortOrder === 'asc' ? -1 : 1
      if (valA > valB) return sortOrder === 'asc' ? 1 : -1
      return 0
    })

    return result
  }

  const filteredTrades = useMemo(() => processItems(trades, 'trades'), [trades, columnFilters, sortField, sortOrder, intl])
  const filteredBuys = useMemo(() => processItems(buys, 'buys'), [buys, columnFilters, sortField, sortOrder, intl])
  const filteredSells = useMemo(() => processItems(sells, 'sells'), [sells, columnFilters, sortField, sortOrder, intl])

  const activeItems = useMemo(() => {
    if (activeTab === 'trades') return filteredTrades
    if (activeTab === 'buys') return filteredBuys
    return filteredSells
  }, [activeTab, filteredTrades, filteredBuys, filteredSells])

  const totalCount = activeItems.length
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const startItem = totalCount === 0 ? 0 : (safePage - 1) * pageSize + 1
  const endItem = Math.min(totalCount, safePage * pageSize)

  const paginatedTrades = useMemo(() => {
    if (activeTab !== 'trades') return []
    const start = (safePage - 1) * pageSize
    return filteredTrades.slice(start, start + pageSize)
  }, [activeTab, filteredTrades, safePage, pageSize])

  const paginatedBuys = useMemo(() => {
    if (activeTab !== 'buys') return []
    const start = (safePage - 1) * pageSize
    return filteredBuys.slice(start, start + pageSize)
  }, [activeTab, filteredBuys, safePage, pageSize])

  const paginatedSells = useMemo(() => {
    if (activeTab !== 'sells') return []
    const start = (safePage - 1) * pageSize
    return filteredSells.slice(start, start + pageSize)
  }, [activeTab, filteredSells, safePage, pageSize])

  // Sub-component header avec bouton de tri
  const ThSortable = ({
    label,
    field,
    className = '',
  }: {
    label: string
    field: string
    className?: string
  }) => {
    const isSorted = sortField === field
    return (
      <th
        onClick={() => handleSort(field)}
        className={cn(
          'cursor-pointer select-none py-2.5 px-3 font-semibold transition-colors hover:text-foreground hover:bg-secondary/60 rounded-t',
          isSorted ? 'text-primary font-bold bg-secondary/40' : '',
          className
        )}
      >
        <div className="flex items-center gap-1.5">
          <span>{label}</span>
          {isSorted ? (
            sortOrder === 'asc' ? (
              <ArrowUp className="h-3.5 w-3.5 text-primary shrink-0" />
            ) : (
              <ArrowDown className="h-3.5 w-3.5 text-primary shrink-0" />
            )
          ) : (
            <ArrowUpDown className="h-3 w-3 opacity-30 shrink-0" />
          )}
        </div>
      </th>
    )
  }

  // Composant champ de filtre stylisé avec bouton d'effacement
  const RenderFilterInput = ({
    field,
    placeholder,
  }: {
    field: string
    placeholder: string
  }) => {
    const val = columnFilters[field] || ''
    return (
      <div className="relative flex items-center">
        <Input
          value={val}
          onChange={(e) => handleFilterChange(field, e.target.value)}
          placeholder={placeholder}
          className="h-7 w-full rounded border border-border/60 bg-background/90 px-2 pr-6 text-xs text-foreground placeholder:text-muted-foreground/60 transition-colors focus:border-primary focus:ring-1 focus:ring-primary/20"
        />
        {val && (
          <button
            onClick={() => handleFilterChange(field, '')}
            className="absolute right-1.5 text-muted-foreground hover:text-foreground transition-colors p-0.5 rounded"
            title="Effacer"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
    )
  }

  return (
    <Card className="border-border/60 shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-lg font-bold flex items-center gap-2">
              <CircleDollarSign className="h-5 w-5 text-primary" /> Trades & Ordres
            </CardTitle>
            <div className="flex rounded-lg border border-border/80 bg-secondary/40 p-1 text-xs">
              <button
                onClick={() => setActiveTab('trades')}
                className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'trades' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
              >
                📊 Trades & PnL ({filteredTrades.length})
              </button>
              <button
                onClick={() => setActiveTab('buys')}
                className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'buys' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
              >
                🛒 Achats ({filteredBuys.length})
              </button>
              <button
                onClick={() => setActiveTab('sells')}
                className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'sells' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
              >
                🏷️ Ventes ({filteredSells.length})
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearAllFilters} className="h-8 gap-1 px-2 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 transition-colors">
                <X className="h-3.5 w-3.5" /> Réinitialiser filtres
              </Button>
            )}
            <div className="relative flex items-center">
              <Search className="absolute left-2.5 h-3.5 w-3.5 text-muted-foreground/60 pointer-events-none" />
              <Input
                value={symbol}
                onChange={(event) => setSymbol(event.target.value)}
                placeholder="Rechercher symbole..."
                className="max-w-56 h-8 pl-8 pr-6 text-xs border-border/60 bg-background/80 focus:border-primary"
              />
              {symbol && (
                <button
                  onClick={() => setSymbol('')}
                  className="absolute right-2 text-muted-foreground hover:text-foreground p-0.5"
                  title="Effacer"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="overflow-auto rounded-lg border border-border/60 bg-background/50">
          {activeTab === 'trades' && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  <ThSortable label="Date" field="date" />
                  <ThSortable label="Symbole" field="symbol" />
                  <ThSortable label="Statut" field="status" />
                  <ThSortable label="Prix Entrée (Achat)" field="buy_price" />
                  <ThSortable label="Prix Vente" field="sell_price" />
                  <ThSortable label="Montant" field="amount" />
                  <ThSortable label="PnL Net" field="pnl" />
                </tr>
                {/* Filtres par colonne */}
                <tr className="border-b border-border/60 bg-secondary/15">
                  <th className="p-1.5"><RenderFilterInput field="date" placeholder="Filtrer date..." /></th>
                  <th className="p-1.5">
                    <select
                      value={columnFilters.symbol}
                      onChange={(e) => handleFilterChange('symbol', e.target.value)}
                      className="h-7 w-full rounded border border-border/60 bg-background/90 px-1.5 text-xs text-foreground outline-none transition-colors focus:border-primary"
                    >
                      <option value="">Tous</option>
                      <option value="BTC">BTC/USD</option>
                      <option value="ETH">ETH/USD</option>
                      <option value="SOL">SOL/USD</option>
                      <option value="ADA">ADA/USD</option>
                    </select>
                  </th>
                  <th className="p-1.5">
                    <select
                      value={columnFilters.status}
                      onChange={(e) => handleFilterChange('status', e.target.value)}
                      className="h-7 w-full rounded border border-border/60 bg-background/90 px-1.5 text-xs text-foreground outline-none transition-colors focus:border-primary"
                    >
                      <option value="">Tous</option>
                      <option value="open">OPEN</option>
                      <option value="closed">CLOSED</option>
                    </select>
                  </th>
                  <th className="p-1.5"><RenderFilterInput field="buy_price" placeholder="Filtrer prix..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="sell_price" placeholder="Filtrer prix..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="amount" placeholder="Filtrer montant..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="pnl" placeholder="Filtrer PnL..." /></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedTrades.length === 0 ? (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground font-medium">Aucun trade trouvé</td></tr>
                ) : (
                  paginatedTrades.map((trade, index) => {
                    const tradeSymbol = asString(trade.symbol)
                    const time = formatTradeTime(trade.timestamp ?? trade.buy_time ?? trade.closed_at ?? trade.sell_time, intl)
                    return (
                      <tr key={index} className="hover:bg-secondary/30 transition-colors">
                        <td className="py-2.5 px-3">
                          <span className="block font-semibold text-foreground">{time.absolute}</span>
                          <span className="block text-[11px] text-muted-foreground/80">{time.relative}</span>
                        </td>
                        <td className="px-3 font-semibold text-foreground">{tradeSymbol}</td>
                        <td className="px-3">
                          <span className={cn(
                            'rounded-full border px-2.5 py-0.5 text-[11px] font-black uppercase tracking-wide',
                            trade.status === 'open' ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300 shadow-sm' : 'border-border/80 bg-secondary/80 text-muted-foreground',
                          )}>
                            {trade.status === 'open' ? 'OPEN' : 'CLOSED'}
                          </span>
                        </td>
                        <td className="px-3 font-mono">{formatLivePrice(tradeSymbol, trade.buy_price ?? trade.price)}</td>
                        <td className="px-3 font-mono">{trade.sell_price ? formatLivePrice(tradeSymbol, trade.sell_price) : <span className="text-muted-foreground/60">--</span>}</td>
                        <td className="px-3 font-mono text-foreground">{formatCryptoAmount(trade.amount)}</td>
                        <td className="px-3 font-medium">{trade.status === 'open' ? <span className="text-emerald-400/90 font-semibold italic">En cours</span> : formatTradePnl(trade.pnl ?? trade.pnl_net)}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}

          {activeTab === 'buys' && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  <ThSortable label="Date" field="date" />
                  <ThSortable label="Symbole" field="symbol" />
                  <ThSortable label="Side" field="side" />
                  <ThSortable label="Prix Achat" field="price" />
                  <ThSortable label="Montant" field="amount" />
                  <ThSortable label="Valeur USD" field="usd_value" />
                  <ThSortable label="Statut" field="status" />
                </tr>
                {/* Filtres par colonne */}
                <tr className="border-b border-border/60 bg-secondary/15">
                  <th className="p-1.5"><RenderFilterInput field="date" placeholder="Filtrer date..." /></th>
                  <th className="p-1.5">
                    <select
                      value={columnFilters.symbol}
                      onChange={(e) => handleFilterChange('symbol', e.target.value)}
                      className="h-7 w-full rounded border border-border/60 bg-background/90 px-1.5 text-xs text-foreground outline-none transition-colors focus:border-primary"
                    >
                      <option value="">Tous</option>
                      <option value="BTC">BTC/USD</option>
                      <option value="ETH">ETH/USD</option>
                      <option value="SOL">SOL/USD</option>
                      <option value="ADA">ADA/USD</option>
                    </select>
                  </th>
                  <th className="p-1.5"></th>
                  <th className="p-1.5"><RenderFilterInput field="price" placeholder="Filtrer prix..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="amount" placeholder="Filtrer montant..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="usd_value" placeholder="Filtrer USD..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="status" placeholder="Filtrer statut..." /></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedBuys.length === 0 ? (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground font-medium">Aucun achat trouvé</td></tr>
                ) : (
                  paginatedBuys.map((buy, index) => {
                    const itemSymbol = asString(buy.symbol)
                    const time = formatTradeTime(buy.timestamp, intl)
                    const px = Number(buy.price || 0)
                    const amt = Number(buy.amount || 0)
                    return (
                      <tr key={index} className="hover:bg-secondary/30 transition-colors">
                        <td className="py-2.5 px-3">
                          <span className="block font-semibold text-foreground">{time.absolute}</span>
                          <span className="block text-[11px] text-muted-foreground/80">{time.relative}</span>
                        </td>
                        <td className="px-3 font-semibold text-foreground">{itemSymbol}</td>
                        <td className="px-3">
                          <span className="rounded-full border border-emerald-500/50 bg-emerald-500/15 px-2.5 py-0.5 text-[11px] font-black uppercase text-emerald-300">
                            BUY
                          </span>
                        </td>
                        <td className="px-3 font-mono">{formatLivePrice(itemSymbol, px)}</td>
                        <td className="px-3 font-mono text-foreground">{formatCryptoAmount(amt)}</td>
                        <td className="px-3 font-semibold">${(px * amt).toFixed(2)} USD</td>
                        <td className="px-3">
                          <span className="rounded-full border border-border/80 bg-secondary/80 px-2.5 py-0.5 text-[11px] font-semibold text-foreground uppercase">
                            {asString(buy.status || 'executed').toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}

          {activeTab === 'sells' && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  <ThSortable label="Date" field="date" />
                  <ThSortable label="Symbole" field="symbol" />
                  <ThSortable label="Side" field="side" />
                  <ThSortable label="Prix Vente Target" field="price" />
                  <ThSortable label="Montant" field="amount" />
                  <ThSortable label="Valeur USD" field="usd_value" />
                  <ThSortable label="Statut" field="status" />
                </tr>
                {/* Filtres par colonne */}
                <tr className="border-b border-border/60 bg-secondary/15">
                  <th className="p-1.5"><RenderFilterInput field="date" placeholder="Filtrer date..." /></th>
                  <th className="p-1.5">
                    <select
                      value={columnFilters.symbol}
                      onChange={(e) => handleFilterChange('symbol', e.target.value)}
                      className="h-7 w-full rounded border border-border/60 bg-background/90 px-1.5 text-xs text-foreground outline-none transition-colors focus:border-primary"
                    >
                      <option value="">Tous</option>
                      <option value="BTC">BTC/USD</option>
                      <option value="ETH">ETH/USD</option>
                      <option value="SOL">SOL/USD</option>
                      <option value="ADA">ADA/USD</option>
                    </select>
                  </th>
                  <th className="p-1.5"></th>
                  <th className="p-1.5"><RenderFilterInput field="price" placeholder="Filtrer prix..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="amount" placeholder="Filtrer montant..." /></th>
                  <th className="p-1.5"><RenderFilterInput field="usd_value" placeholder="Filtrer USD..." /></th>
                  <th className="p-1.5">
                    <select
                      value={columnFilters.status}
                      onChange={(e) => handleFilterChange('status', e.target.value)}
                      className="h-7 w-full rounded border border-border/60 bg-background/90 px-1.5 text-xs text-foreground outline-none transition-colors focus:border-primary"
                    >
                      <option value="">Tous</option>
                      <option value="opened">OPEN</option>
                      <option value="executed">EXECUTED</option>
                    </select>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedSells.length === 0 ? (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground font-medium">Aucune vente trouvée</td></tr>
                ) : (
                  paginatedSells.map((sell, index) => {
                    const itemSymbol = asString(sell.symbol)
                    const time = formatTradeTime(sell.timestamp, intl)
                    const px = Number(sell.price || 0)
                    const amt = Number(sell.amount || 0)
                    const isOpened = sell.status === 'opened'
                    return (
                      <tr key={index} className="hover:bg-secondary/30 transition-colors">
                        <td className="py-2.5 px-3">
                          <span className="block font-semibold text-foreground">{time.absolute}</span>
                          <span className="block text-[11px] text-muted-foreground/80">{time.relative}</span>
                        </td>
                        <td className="px-3 font-semibold text-foreground">{itemSymbol}</td>
                        <td className="px-3">
                          <span className="rounded-full border border-rose-500/50 bg-rose-500/15 px-2.5 py-0.5 text-[11px] font-black uppercase text-rose-300">
                            SELL
                          </span>
                        </td>
                        <td className="px-3 font-mono">{formatLivePrice(itemSymbol, px)}</td>
                        <td className="px-3 font-mono text-foreground">{formatCryptoAmount(amt)}</td>
                        <td className="px-3 font-semibold">${(px * amt).toFixed(2)} USD</td>
                        <td className="px-3">
                          <span className={cn(
                            'rounded-full border px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide',
                            isOpened ? 'border-amber-500/50 bg-amber-500/15 text-amber-300' : 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300'
                          )}>
                            {isOpened ? 'OPEN (EN ATTENTE)' : 'EXECUTED (VENDU)'}
                          </span>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Barre de Pagination & Sélecteur d'éléments par page */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-muted-foreground font-medium">
              Affichage de <span className="font-bold text-foreground">{startItem}</span> à <span className="font-bold text-foreground">{endItem}</span> sur <span className="font-bold text-foreground">{totalCount}</span> éléments
            </span>
            <div className="flex items-center gap-1.5 border-l border-border/60 pl-3">
              <span className="text-muted-foreground">Par page :</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setCurrentPage(1)
                }}
                className="h-7 rounded border border-border/80 bg-background/90 px-2 text-xs text-foreground font-bold transition-colors focus:border-primary outline-none"
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={safePage <= 1}
              onClick={() => setCurrentPage(1)}
              className="h-7 w-7 p-0 hover:bg-secondary border-border/80"
              title="Première page"
            >
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={safePage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              className="h-7 w-7 p-0 hover:bg-secondary border-border/80"
              title="Page précédente"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>

            <div className="flex items-center gap-1 px-1">
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - safePage) <= 1)
                .reduce<(number | string)[]>((acc, p, idx, arr) => {
                  if (idx > 0 && typeof arr[idx - 1] === 'number' && (p as number) - (arr[idx - 1] as number) > 1) {
                    acc.push('...')
                  }
                  acc.push(p)
                  return acc
                }, [])
                .map((item, idx) => (
                  typeof item === 'number' ? (
                    <Button
                      key={idx}
                      variant={item === safePage ? "default" : "outline"}
                      size="sm"
                      onClick={() => setCurrentPage(item)}
                      className={cn(
                        'h-7 w-7 p-0 text-xs font-bold transition-all border-border/80',
                        item === safePage ? 'bg-primary text-primary-foreground shadow-sm' : 'hover:bg-secondary'
                      )}
                    >
                      {item}
                    </Button>
                  ) : (
                    <span key={idx} className="px-1 text-muted-foreground text-xs select-none">...</span>
                  )
                ))}
            </div>

            <Button
              variant="outline"
              size="sm"
              disabled={safePage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              className="h-7 w-7 p-0 hover:bg-secondary border-border/80"
              title="Page suivante"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={safePage >= totalPages}
              onClick={() => setCurrentPage(totalPages)}
              className="h-7 w-7 p-0 hover:bg-secondary border-border/80"
              title="Dernière page"
            >
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function ConsoleView({ data, onRefresh }: { data: ConsolePayload; onRefresh: (lines?: string | number) => Promise<void> }) {
  const [limit, setLimit] = useState('500')
  const [pinned, setPinned] = useState(true)
  const [cleared, setCleared] = useState(false)
  const outputRef = useRef<HTMLDivElement>(null)
  const lines = cleared ? [] : data.lines || []

  useEffect(() => {
    if (pinned) {
      outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [lines.length, pinned])

  const handleLimitChange = (value: string) => {
    setLimit(value)
    setCleared(false)
    void onRefresh(value)
  }

  const handleScroll = () => {
    const el = outputRef.current
    if (!el) return
    setPinned(el.scrollTop + el.clientHeight >= el.scrollHeight - 40)
  }

  const pinToBottom = () => {
    setPinned(true)
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-4 w-4 text-primary" />
            Console Bot
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={limit} onValueChange={handleLimitChange}>
              <SelectTrigger aria-label="Nombre de lignes console" className="min-w-[126px]">
                <SelectValue placeholder="500 lignes" />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectItem value="500">500 lignes</SelectItem>
                <SelectItem value="1500">1 500 lignes</SelectItem>
                <SelectItem value="5000">5 000 lignes</SelectItem>
                <SelectItem value="all">Tout voir</SelectItem>
              </SelectContent>
            </Select>
            <Button variant={pinned ? 'secondary' : 'outline'} size="sm" onClick={pinToBottom}>
              <ChevronDown className="h-4 w-4" />
              {pinned ? 'Auto' : 'Bas'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCleared(true)}>Clear</Button>
            <Button variant="outline" size="sm" onClick={() => { setCleared(false); void onRefresh(limit) }}>
              <RefreshCw className="h-4 w-4" />
              Actualiser
            </Button>
            <span className="text-[11px] text-muted-foreground">{lines.length} lignes</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div
          ref={outputRef}
          onScroll={handleScroll}
          className="min-h-[500px] max-h-[calc(100vh-200px)] overflow-auto bg-[#060809] p-4 font-mono text-[11px] leading-[1.6] text-[#c8d6e5]"
        >
          {lines.length === 0 && <div className="text-muted-foreground">Aucune ligne console</div>}
          {lines.map((line, index) => (
            <div key={`${line}-${index}`} className={cn('whitespace-pre-wrap break-all', consoleLineClass(line))}>
              {stripAnsi(line)}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function stripAnsi(line: string) {
  return line.replace(/\x1b\[[0-9;]*m/g, '')
}

function consoleLineClass(line: string) {
  if (/❌|error|erreur|failed|échou/i.test(line)) return 'text-rose-300'
  if (/⚠️|warn|warning/i.test(line)) return 'text-amber-300'
  if (/✅|success|succès/i.test(line)) return 'text-emerald-300'
  if (/🎯|buy|achat|sell|vente/i.test(line)) return 'text-sky-300'
  return 'text-[#c8d6e5]'
}

function ConfigView({ config, setConfig, refresh }: { config: ConfigPayload; setConfig: (value: ConfigPayload) => void; refresh: () => Promise<void> }) {
  const fields = config.fields || []
  const values = config.values || Object.fromEntries(fields.map((field) => [field.name, field.value ?? '']))

  const save = async () => {
    const result = await postJson<ConfigPayload>('/api/config', { values })
    setConfig(result)
    await refresh()
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Configuration</CardTitle>
          <Button size="sm" onClick={() => void save()}>Sauver</Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {fields.map((field) => (
          <label key={field.name} className="space-y-1 rounded-md border border-border bg-background p-3">
            <span className="text-xs font-bold uppercase text-muted-foreground">{field.label || field.name}</span>
            <Input
              value={asString(values[field.name], '')}
              onChange={(event) => setConfig({ ...config, values: { ...values, [field.name]: event.target.value } })}
            />
          </label>
        ))}
      </CardContent>
    </Card>
  )
}

export default App
