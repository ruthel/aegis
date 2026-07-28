import { create } from 'zustand'
import { getJson, postJson } from '@/lib/api'
import type { AnalyticsPayload, ConfigPayload, ConsolePayload, JsonMap, MlStatus, StatusPayload, View } from '@/types/dashboard'

type DashboardState = {
  view: View
  status: StatusPayload
  ml: MlStatus
  consoleData: ConsolePayload
  config: ConfigPayload
  analytics: AnalyticsPayload
  loading: boolean
  setView: (view: View) => void
  setStatus: (status: StatusPayload | ((current: StatusPayload) => StatusPayload)) => void
  setMl: (ml: MlStatus) => void
  setConsoleData: (consoleData: ConsolePayload) => void
  setConfig: (config: ConfigPayload) => void
  setAnalytics: (analytics: AnalyticsPayload) => void
  refreshStatus: () => Promise<void>
  refreshMl: () => Promise<void>
  refreshConsole: (lines?: string | number) => Promise<void>
  refreshConfig: () => Promise<void>
  refreshAnalytics: () => Promise<void>
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
  loading: true,
  setView: (view) => set({ view }),
  setStatus: (status) => set((current) => ({
    status: typeof status === 'function' ? status(current.status) : status,
  })),
  setMl: (ml) => set({ ml }),
  setConsoleData: (consoleData) => set({ consoleData }),
  setConfig: (config) => set({ config }),
  setAnalytics: (analytics) => set({ analytics }),
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
  refreshAnalytics: async () => {
    const analytics = await getJson<AnalyticsPayload>('/api/analytics')
    set({ analytics })
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
