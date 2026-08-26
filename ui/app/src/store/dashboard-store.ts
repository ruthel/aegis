import { create } from 'zustand'
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

const VIEW_MODE_STORAGE_KEY = 'aegis:viewMode:v2'

const isDataViewMode = (value: unknown): value is DataViewMode =>
  value === 'live' || value === 'all' || value === 'paper'

const initialViewMode = (): DataViewMode => {
  if (typeof window === 'undefined') return 'paper'
  const value = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY)
  return isDataViewMode(value) ? value : 'paper'
}

export const useDashboardStore = create<DashboardState>((set, get) => ({
  view: 'live',
  viewMode: initialViewMode(),
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
  setViewMode: (viewMode) => {
    if (typeof window !== 'undefined') window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode)
    set({
      viewMode,
      analyticsLoaded: false,
      tradesLoaded: false,
      ledgerLoaded: false,
      scoreHistory: {},
    })
  },
  setStatus: (status) => set((current) => ({
    status: typeof status === 'function' ? status(current.status) : status,
  })),
  setMl: (ml) => set({ ml }),
  setConsoleData: (consoleData) => set({ consoleData }),
  setConfig: (config) => set({ config }),
  setAnalytics: (analytics) => set({ analytics, analyticsLoaded: true }),
  setTrades: (trades) => set({ trades, tradesLoaded: true }),
  setLedger: (ledger) => set({ ledger, ledgerLoaded: true }),
  refreshStatus: async () => {
    const status = await getJson<StatusPayload>(`/api/status?view_mode=${encodeURIComponent(get().viewMode)}`)
    set({ status })
  },
  refreshMl: async () => {
    const ml = await getJson<MlStatus>(`/api/ml_status?view_mode=${encodeURIComponent(get().viewMode)}`)
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
    const analytics = await getJson<AnalyticsPayload>(`/api/analytics?view_mode=${encodeURIComponent(get().viewMode)}`)
    set({ analytics, analyticsLoaded: true })
  },
  refreshTrades: async (options) => {
    if (!options?.force && get().tradesLoaded) return
    const trades = await getJson<TradesPayload>(`/api/trades?view_mode=${encodeURIComponent(get().viewMode)}`)
    set({ trades, tradesLoaded: true })
  },
  refreshLedger: async (options) => {
    if (!options?.force && get().ledgerLoaded) return
    const ledger = await getJson<LedgerPayload>(`/api/ledger?view_mode=${encodeURIComponent(get().viewMode)}`)
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
      const hasManualViewMode =
        typeof window !== 'undefined' && isDataViewMode(window.localStorage.getItem(VIEW_MODE_STORAGE_KEY))
      if (!hasManualViewMode) {
        const status = await getJson<StatusPayload>('/api/status')
        const serverMode = status.bot?.view_mode ?? status.bot?.mode
        const nextViewMode = isDataViewMode(serverMode) ? serverMode : get().viewMode
        set({ status, viewMode: nextViewMode })
        const ml = await getJson<MlStatus>(`/api/ml_status?view_mode=${encodeURIComponent(nextViewMode)}`)
        set({ ml })
      } else {
        await Promise.all([get().refreshStatus(), get().refreshMl()])
      }
    } finally {
      set({ loading: false })
    }
  },
  runBotAction: async (action) => {
    await postJson<JsonMap>(`/api/bot/${action}`)
    await get().refreshStatus()
  },
}))
