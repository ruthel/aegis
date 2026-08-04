import { create } from 'zustand'
import { getJson, postJson } from '@/lib/api'
import type { AnalyticsPayload, ConfigPayload, ConsolePayload, JsonMap, MlStatus, StatusPayload, TradesPayload, View } from '@/types/dashboard'

type DashboardState = {
  view: View
  status: StatusPayload
  ml: MlStatus
  consoleData: ConsolePayload
  config: ConfigPayload
  analytics: AnalyticsPayload
  analyticsLoaded: boolean
  trades: TradesPayload
  tradesLoaded: boolean
  scoreHistory: Record<string, JsonMap[]>
  loading: boolean
  setView: (view: View) => void
  setStatus: (status: StatusPayload | ((current: StatusPayload) => StatusPayload)) => void
  setMl: (ml: MlStatus) => void
  setConsoleData: (consoleData: ConsolePayload) => void
  setConfig: (config: ConfigPayload) => void
  setAnalytics: (analytics: AnalyticsPayload) => void
  setTrades: (trades: TradesPayload) => void
  refreshStatus: () => Promise<void>
  refreshMl: () => Promise<void>
  refreshConsole: (lines?: string | number) => Promise<void>
  refreshConfig: () => Promise<void>
  refreshAnalytics: (options?: { force?: boolean }) => Promise<void>
  refreshTrades: (options?: { force?: boolean }) => Promise<void>
  refreshScoreHistory: (symbol: string, hours: string, options?: { force?: boolean }) => Promise<void>
  refreshLoadedData: () => Promise<void>
  bootstrap: () => Promise<void>
  runBotAction: (action: 'start' | 'stop' | 'restart') => Promise<void>
}

export const useDashboardStore = create<DashboardState>((set, get) => ({
  view: 'live',
  status: {},
  ml: {},
  consoleData: {},
  config: {},
  analytics: {},
  analyticsLoaded: false,
  trades: {},
  tradesLoaded: false,
  scoreHistory: {},
  loading: true,
  setView: (view) => set({ view }),
  setStatus: (status) => set((current) => ({
    status: typeof status === 'function' ? status(current.status) : status,
  })),
  setMl: (ml) => set({ ml }),
  setConsoleData: (consoleData) => set({ consoleData }),
  setConfig: (config) => set({ config }),
  setAnalytics: (analytics) => set({ analytics, analyticsLoaded: true }),
  setTrades: (trades) => set({ trades, tradesLoaded: true }),
  refreshStatus: async () => {
    const status = await getJson<StatusPayload>('/api/status')
    set({ status })
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
    const { analyticsLoaded, tradesLoaded, scoreHistory } = get()
    const tasks: Array<Promise<void>> = []
    if (analyticsLoaded) tasks.push(get().refreshAnalytics({ force: true }))
    if (tradesLoaded) tasks.push(get().refreshTrades({ force: true }))
    for (const key of Object.keys(scoreHistory)) {
      const [symbol, hours] = key.split('|')
      if (symbol && hours) tasks.push(get().refreshScoreHistory(symbol, hours, { force: true }))
    }
    await Promise.all(tasks)
  },
  bootstrap: async () => {
    try {
      await Promise.all([get().refreshStatus(), get().refreshMl()])
    } finally {
      set({ loading: false })
    }
  },
  runBotAction: async (action) => {
    await postJson<JsonMap>(`/api/bot/${action}`)
    await get().refreshStatus()
  },
}))
