import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { getJson, postJson } from '@/lib/api'
import type { AnalyticsPayload, ConfigPayload, ConsolePayload, DataViewMode, JsonMap, LedgerPayload, MlStatus, StatusPayload, TradesPayload, View } from '@/types/dashboard'

type DashboardState = {
  view: View
  viewMode: DataViewMode
  status: StatusPayload
  ml: MlStatus
  consoleData: ConsolePayload
  config: ConfigPayload
  analytics: AnalyticsPayload
  analyticsLoaded: boolean
  trades: TradesPayload
  tradesLoaded: boolean
  ledger: LedgerPayload
  ledgerLoaded: boolean
  scoreHistory: Record<string, JsonMap[]>
  loading: boolean
  setView: (view: View) => void
  setViewMode: (mode: DataViewMode) => void
  setStatus: (status: StatusPayload | ((current: StatusPayload) => StatusPayload)) => void
  setMl: (ml: MlStatus) => void
  setConsoleData: (consoleData: ConsolePayload) => void
  setConfig: (config: ConfigPayload) => void
  setAnalytics: (analytics: AnalyticsPayload) => void
  setTrades: (trades: TradesPayload) => void
  setLedger: (ledger: LedgerPayload) => void
  refreshStatus: () => Promise<void>
  refreshMl: () => Promise<void>
  refreshConsole: (lines?: string | number) => Promise<void>
  refreshConfig: () => Promise<void>
  refreshAnalytics: (options?: { force?: boolean }) => Promise<void>
  refreshTrades: (options?: { force?: boolean }) => Promise<void>
  refreshLedger: (options?: { force?: boolean }) => Promise<void>
  refreshScoreHistory: (symbol: string, hours: string, options?: { force?: boolean }) => Promise<void>
  refreshLoadedData: () => Promise<void>
  bootstrap: () => Promise<void>
  runBotAction: (action: 'start' | 'stop' | 'restart') => Promise<void>
}

const isDataViewMode = (value: unknown): value is DataViewMode =>
  value === 'live' || value === 'paper'

const serverViewMode = (status: StatusPayload, fallback: DataViewMode = 'paper'): DataViewMode => {
  const value = status.bot?.view_mode ?? status.bot?.mode
  return isDataViewMode(value) ? value : fallback
}

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set, get) => ({
      view: 'live',
      viewMode: 'paper',
      status: {},
      ml: {},
      consoleData: {},
      config: {},
      analytics: {},
      analyticsLoaded: false,
      trades: {},
      tradesLoaded: false,
      ledger: {},
      ledgerLoaded: false,
      scoreHistory: {},
      loading: true,
      setView: (view) => set({ view }),
      setViewMode: (viewMode) => set({
        viewMode,
        analyticsLoaded: false,
        tradesLoaded: false,
        ledgerLoaded: false,
        scoreHistory: {},
      }),
      setStatus: (status) => set((current) => {
        const nextStatus = typeof status === 'function' ? status(current.status) : status
        const nextMode = serverViewMode(nextStatus, current.viewMode)
        const modeChanged = nextMode !== current.viewMode
        return {
          status: nextStatus,
          viewMode: nextMode,
          analyticsLoaded: modeChanged ? false : current.analyticsLoaded,
          tradesLoaded: modeChanged ? false : current.tradesLoaded,
          ledgerLoaded: modeChanged ? false : current.ledgerLoaded,
          scoreHistory: modeChanged ? {} : current.scoreHistory,
        }
      }),
      setMl: (ml) => set({ ml }),
      setConsoleData: (consoleData) => set({ consoleData }),
      setConfig: (config) => set({ config }),
      setAnalytics: (analytics) => set({ analytics, analyticsLoaded: true }),
      setTrades: (trades) => set({ trades, tradesLoaded: true }),
      setLedger: (ledger) => set({ ledger, ledgerLoaded: true }),
      refreshStatus: async () => {
        const status = await getJson<StatusPayload>('/api/status')
        const nextMode = serverViewMode(status, get().viewMode)
        const modeChanged = nextMode !== get().viewMode
        set({
          status,
          viewMode: nextMode,
          analyticsLoaded: modeChanged ? false : get().analyticsLoaded,
          tradesLoaded: modeChanged ? false : get().tradesLoaded,
          ledgerLoaded: modeChanged ? false : get().ledgerLoaded,
          scoreHistory: modeChanged ? {} : get().scoreHistory,
        })
      },
      refreshMl: async () => {
        const ml = await getJson<MlStatus>('/api/ml_status')
        set({ ml })
      },
      refreshConsole: async (lines = 500) => {
        const consoleData = await getJson<ConsolePayload>(`/api/bot/console?lines=${encodeURIComponent(String(lines))}`)
        set({ consoleData })
      },
      refreshConfig: async () => {
        const config = await getJson<ConfigPayload>('/api/config')
        set({ config })
      },
      refreshAnalytics: async (options) => {
        if (!options?.force && get().analyticsLoaded) return
        const analytics = await getJson<AnalyticsPayload>('/api/analytics')
        set({ analytics, analyticsLoaded: true })
      },
      refreshTrades: async (options) => {
        if (!options?.force && get().tradesLoaded) return
        const trades = await getJson<TradesPayload>('/api/trades')
        set({ trades, tradesLoaded: true })
      },
      refreshLedger: async (options) => {
        if (!options?.force && get().ledgerLoaded) return
        const ledger = await getJson<LedgerPayload>('/api/ledger')
        set({ ledger, ledgerLoaded: true })
      },
      refreshScoreHistory: async (symbol, hours, options) => {
        const key = `${symbol}|${hours}`
        if (!options?.force && get().scoreHistory[key]) return
        const params = new URLSearchParams({ symbol, hours })
        const scores = await getJson<JsonMap[]>(`/api/analytics/scores?${params.toString()}`)
        set((current) => ({
          scoreHistory: {
            ...current.scoreHistory,
            [key]: Array.isArray(scores) ? scores : [],
          },
        }))
      },
      refreshLoadedData: async () => {
        const { analyticsLoaded, tradesLoaded, ledgerLoaded, scoreHistory } = get()
        const tasks: Array<Promise<void>> = []
        if (analyticsLoaded) tasks.push(get().refreshAnalytics({ force: true }))
        if (tradesLoaded) tasks.push(get().refreshTrades({ force: true }))
        if (ledgerLoaded) tasks.push(get().refreshLedger({ force: true }))
        for (const key of Object.keys(scoreHistory)) {
          const [symbol, hours] = key.split('|')
          if (symbol && hours) tasks.push(get().refreshScoreHistory(symbol, hours, { force: true }))
        }
        await Promise.all(tasks)
      },
      bootstrap: async () => {
        try {
          const status = await getJson<StatusPayload>('/api/status')
          const nextViewMode = serverViewMode(status, get().viewMode)
          set({
            status,
            viewMode: nextViewMode,
            analyticsLoaded: false,
            tradesLoaded: false,
            ledgerLoaded: false,
            scoreHistory: {},
          })
          const ml = await getJson<MlStatus>('/api/ml_status')
          set({ ml })
        } finally {
          set({ loading: false })
        }
        // Preload all data in background so pages are instant
        void Promise.all([
          get().refreshTrades({ force: false }),
          get().refreshLedger({ force: false }),
          get().refreshConfig(),
          get().refreshAnalytics({ force: false }),
        ])
      },
      runBotAction: async (action) => {
        await postJson<JsonMap>(`/api/bot/${action}`)
        await get().refreshStatus()
      },
    }),
    {
      name: 'aegis:dashboard:v1',
      partialize: (state) => ({
        status: state.status,
        ml: state.ml,
        analytics: state.analytics,
        trades: state.trades,
        ledger: state.ledger,
      }),
    }
  )
)
