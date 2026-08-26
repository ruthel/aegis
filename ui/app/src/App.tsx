import {
  BarChart3,
  Bot,
  Cog,
  CircleDollarSign,
  LayoutDashboard,
  ReceiptText,
  Play,
  RotateCcw,
  Server,
  Square,
  Terminal,
  Wifi,
  Zap,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { asString } from '@/lib/formatters'
import { useDashboardStore } from '@/store/dashboard-store'
import type { DataViewMode, StatusPayload, MlStatus, View } from '@/types/dashboard'

// ─── Vues (refactorisées dans leur propre fichier) ────────────────────────
import { LiveView } from '@/views/LiveView'
import { AnalyticsView } from '@/views/AnalyticsView'
import { TradesView } from '@/views/TradesView'
import { LedgerView } from '@/views/LedgerView'
import { ConsoleView } from '@/views/ConsoleView'
import { ConfigView } from '@/views/ConfigView'

// ─── Navigation ───────────────────────────────────────────────────────────

const views: Array<{ id: View; path: string; label: string; icon: typeof LayoutDashboard }> = [
  { id: 'live', path: '/', label: 'Live', icon: LayoutDashboard },
  { id: 'analytics', path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'trades', path: '/trades', label: 'Trades', icon: CircleDollarSign },
  { id: 'ledger', path: '/ledger', label: 'Ledger', icon: ReceiptText },
  { id: 'console', path: '/console', label: 'Console', icon: Terminal },
  { id: 'config', path: '/config', label: 'Config', icon: Cog },
]

function dataRevision(status: StatusPayload): string {
  const stats = status.stats || {}
  const positions = status.positions || []
  const positionRevision = positions
    .map((item) => [
      asString(item.symbol),
      asString(item.side),
      asString(item.status),
      asString(item.timestamp ?? item.buy_time ?? item.sell_time ?? item.closed_at),
      asString(item.amount),
      asString(item.price ?? item.buy_price ?? item.sell_price),
    ].join(':'))
    .join('|')

  return [
    asString(stats.total_trades),
    asString(stats.wins),
    asString(stats.losses),
    asString(stats.total_pnl_net ?? stats.total_pnl),
    asString(status.balance?.paper_balance),
    asString(status.bot?.view_mode),
    String(positions.length),
    positionRevision,
  ].join('~')
}

// ─── App principale ───────────────────────────────────────────────────────

function App() {
  const {
    setView,
    status,
    viewMode,
    setViewMode,
    ml,
    consoleData,
    config,
    analytics,
    setStatus,
    setMl,
    setConfig,
    loading,
    bootstrap,
    refreshConsole,
    refreshConfig,
    refreshStatus,
    refreshMl,
    refreshAnalytics,
    refreshTrades,
    refreshLedger,
    refreshLoadedData,
  } = useDashboardStore()
  const location = useLocation()
  const activeView = views.find((item) => item.path === location.pathname)?.id || 'live'
  const bot = status.bot
  const running = Boolean(bot?.control?.running)
  const lastDataRevision = useRef<string>('')

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    setView(activeView)
    if (activeView === 'console') void refreshConsole()
    if (activeView === 'config') void refreshConfig()
  }, [activeView, refreshConfig, refreshConsole, setView])

  useEffect(() => {
    void refreshStatus()
    void refreshMl()
    if (activeView === 'analytics') void refreshAnalytics({ force: true })
    if (activeView === 'trades') void refreshTrades({ force: true })
    if (activeView === 'ledger') void refreshLedger({ force: true })
  }, [activeView, refreshAnalytics, refreshLedger, refreshMl, refreshStatus, refreshTrades, viewMode])

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/live?view_mode=${encodeURIComponent(viewMode)}`)
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { __type?: string; payload?: unknown; live?: unknown }
        if (payload.__type === 'status') {
          const nextStatus = payload.payload as StatusPayload
          const nextRevision = dataRevision(nextStatus)
          if (lastDataRevision.current && nextRevision !== lastDataRevision.current) {
            void refreshLoadedData()
          }
          lastDataRevision.current = nextRevision
          setStatus(nextStatus)
        }
        if (payload.__type === 'ml_status') setMl(payload.payload as MlStatus)
        if (payload.__type === 'live')
          setStatus((current) => ({ ...current, live: payload.live as StatusPayload['live'] }))
      } catch {
        // Ignore malformed websocket payloads.
      }
    }
    return () => ws.close()
  }, [refreshLoadedData, setMl, setStatus, viewMode])

  useEffect(() => {
    const consoleTimer = window.setInterval(() => {
      if (activeView === 'console') void refreshConsole()
    }, 5000)
    return () => {
      window.clearInterval(consoleTimer)
    }
  }, [activeView, refreshConsole])

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Sidebar desktop */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-border bg-card/70 p-5 lg:block">
        <div className="mb-6 flex items-center gap-3">
          <img src="/public/brand/aegis-mark-transparent-512.png" alt="" className="h-9 w-9" />
          <div>
            <div className="font-['Outfit'] text-lg font-black">Aegis</div>
            <div className="text-[13px] uppercase text-muted-foreground">Trading Bot</div>
          </div>
        </div>
        <nav className="space-y-1">
          {views.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.id}
                to={item.path}
                className={({ isActive }) =>
                  cn(
                    'flex w-full items-center gap-2 rounded-md px-3 py-2 text-[13px] font-semibold text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                    isActive && 'bg-accent text-foreground',
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </aside>

      <main className="lg:pl-60">
        <TopToolbar status={status} running={running} viewMode={viewMode} onViewModeChange={setViewMode} />

        {/* Navigation mobile */}
        <div className="border-b border-border p-2 lg:hidden">
          <div className="grid grid-cols-6 gap-1">
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
          {loading && <div className="text-[13px] text-muted-foreground">Chargement...</div>}
          <Routes>
            <Route path="/" element={<LiveView status={status} ml={ml} />} />
            <Route path="/analytics" element={<AnalyticsView ml={ml} analytics={analytics} />} />
            <Route path="/trades" element={<TradesView />} />
            <Route path="/ledger" element={<LedgerView />} />
            <Route path="/console" element={<ConsoleView data={consoleData} onRefresh={refreshConsole} />} />
            <Route path="/config" element={<ConfigView config={config} setConfig={setConfig} refresh={refreshConfig} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </section>
      </main>
    </div>
  )
}

// ─── TopToolbar ───────────────────────────────────────────────────────────

function TopToolbar({
  status,
  running,
  viewMode,
  onViewModeChange,
}: {
  status: StatusPayload
  running: boolean
  viewMode: DataViewMode
  onViewModeChange: (mode: DataViewMode) => void
}) {
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
              bot {asString(bot?.mode, 'mode')}
            </span>
            <span className="h-4 w-px bg-border" />
            <span className="inline-flex items-center gap-1 px-3">
              <Server className="h-3.5 w-3.5" />
              {asString(bot?.exchange, 'exchange')}
            </span>
          </div>
          <Select value={viewMode} onValueChange={(value) => onViewModeChange(value as DataViewMode)}>
            <SelectTrigger className="h-[30px] w-[118px] rounded-full border-border bg-secondary px-3 text-[11px] font-bold">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="paper">Vue paper</SelectItem>
              <SelectItem value="live">Vue live</SelectItem>
              <SelectItem value="all">Vue tous</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <BotActions running={running} />
      </div>
    </header>
  )
}

// ─── BotActions ───────────────────────────────────────────────────────────

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
      <Button
        variant={running ? 'destructive' : 'default'}
        size="sm"
        disabled={pending}
        onClick={() => void runAction(running ? 'stop' : 'start')}
      >
        {running ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        {running ? 'Arrêter' : 'Démarrer'}
      </Button>
      <Button
        variant="outline"
        size="icon"
        disabled={pending}
        onClick={() => void runAction('restart')}
        title="Redémarrer"
      >
        <RotateCcw className="h-4 w-4" />
      </Button>
    </div>
  )
}

export default App
