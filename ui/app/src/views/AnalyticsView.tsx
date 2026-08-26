/**
 * views/AnalyticsView.tsx — Vue Analytics du dashboard Aegis
 */

import { Activity, BarChart3, CircleDollarSign, Power, Zap } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LineChart } from '@/components/charts/LineChart'
import { ScoreHistoryChart, type ScorePoint } from '@/components/charts/ScoreHistoryChart'
import { DailyBarChart } from '@/components/charts/DailyBarChart'
import { HourlyBarChart } from '@/components/charts/HourlyBarChart'
import { cn } from '@/lib/utils'
import { asString, formatPnlDateLabel, num, pct } from '@/lib/formatters'
import { useDashboardStore } from '@/store/dashboard-store'
import {
  MetricCard,
  SplitMetricCard,
  Metric,
  EmptyAnalytics,
  InfoTooltip,
} from '@/components/ui/shared'
import type { AnalyticsPayload, JsonMap, MlStatus } from '@/types/dashboard'

const pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']

type PnlTimeRange = '24h' | '7d' | '30d' | '90d' | 'all'

export function AnalyticsView({ ml, analytics }: { ml: MlStatus; analytics: AnalyticsPayload }) {
  const advanced = analytics.advanced_metrics || {}
  const capital = analytics.capital_breakdown || {}
  const pnlHistory = analytics.pnl_history || {}
  const heatmap = analytics.heatmap || {}
  const mlAnalytics = ml.analytics || {}

  const [pnlTimeRange, setPnlTimeRange] = useState<PnlTimeRange>('30d')
  const refreshAnalytics = useDashboardStore((state) => state.refreshAnalytics)

  useEffect(() => {
    void refreshAnalytics()
  }, [refreshAnalytics])

  const pnlPoints = useMemo(() => {
    const history = (pnlHistory.history || []) as JsonMap[]
    if (!history.length) return []

    const now = Date.now()
    const msMap: Record<string, number> = {
      '24h': 24 * 3600 * 1000,
      '7d': 7 * 86400 * 1000,
      '30d': 30 * 86400 * 1000,
      '90d': 90 * 86400 * 1000,
      all: Infinity,
    }
    const maxAgeMs = msMap[pnlTimeRange] ?? Infinity

    const filtered = history.filter((item) => {
      if (maxAgeMs === Infinity) return true
      const rawTime = asString(item.time)
      if (!rawTime || rawTime === 'start') return false
      const itemTs = new Date(rawTime).getTime()
      if (isNaN(itemTs)) return false
      return now - itemTs <= maxAgeMs
    })

    return filtered.map((item, index) => {
      const rawTime = asString(item.time ?? '')
      const dateLabel = formatPnlDateLabel(rawTime, pnlTimeRange)
      return {
        label: dateLabel,
        value: Number(item.pnl ?? 0),
        event: asString(item.event ?? `Événement #${index + 1}`),
        balance: Number(item.balance ?? 1000),
        time: rawTime,
      }
    })
  }, [pnlHistory.history, pnlTimeRange])

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard
          icon={BarChart3}
          label="Sharpe Ratio"
          value={num(advanced.sharpe_ratio, 2)}
          description="Mesure le rendement obtenu par rapport au risque pris. Plus il est élevé, plus le bot gagne de façon régulière pour la volatilité subie."
        />
        <MetricCard
          icon={CircleDollarSign}
          label="Profit Factor"
          value={num(advanced.profit_factor ?? mlAnalytics.profit_factor, 2)}
          description="Compare les gains bruts aux pertes brutes. Au-dessus de 1, le système gagne plus qu’il ne perd; au-dessus de 2, c’est généralement solide."
        />
        <MetricCard
          icon={Activity}
          label="Max Drawdown"
          value={pct(advanced.max_drawdown, 2)}
          description="Plus forte baisse observée depuis un sommet du capital. Plus ce chiffre est faible, mieux le bot protège le capital."
        />
        <MetricCard
          icon={Zap}
          label="Kelly %"
          value={pct(advanced.kelly_percent, 2)}
          description="Estimation théorique de la fraction de capital à risquer selon l’avantage statistique. À utiliser comme repère, pas comme ordre direct."
        />
        <MetricCard
          icon={Power}
          label="Expectancy"
          value={num(advanced.expectancy ?? mlAnalytics.expectancy, 2)}
          description="Gain moyen attendu par trade après prise en compte des trades gagnants et perdants. Positif veut dire que l’avantage statistique existe."
        />
        <SplitMetricCard
          label="Avg Win / Avg Loss"
          leftLabel="Avg Win"
          leftValue={pct(advanced.avg_win ?? mlAnalytics.avg_win, 2)}
          rightLabel="Avg Loss"
          rightValue={pct(advanced.avg_loss ?? mlAnalytics.avg_loss, 2)}
          description="Compare la taille moyenne des trades gagnants et perdants. Un bon système garde idéalement les gains moyens supérieurs aux pertes moyennes."
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Capital Breakdown</CardTitle>
            <InfoTooltip
              label="Capital Breakdown"
              description="Répartition du capital entre solde disponible, valeur immobilisée dans les positions ouvertes et ordres limit en attente."
            />
          </div>
        </CardHeader>
        <CardContent>
          <CapitalBreakdown capital={capital} />
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-12">
        {/* ─── Graphique PnL History ─── */}
        <Card className="xl:col-span-12 border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="text-lg font-bold flex items-center gap-2">
                  📈 Historique P&L Net (PnL History)
                </CardTitle>
                <div className="flex flex-wrap items-center gap-4 pt-1.5 text-xs">
                  <span className="flex items-center gap-1.5 font-semibold text-emerald-400">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" /> Axe Y : P&L Net Cumulé ($ USD)
                  </span>
                  <span className="flex items-center gap-1.5 font-semibold text-blue-400">
                    <span className="h-2 w-2 rounded-full bg-blue-400" /> Axe X : Chronologie Temporelle
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4 border-t sm:border-t-0 border-border/60 pt-2 sm:pt-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-muted-foreground">Durée :</span>
                  <Select value={pnlTimeRange} onValueChange={(v) => setPnlTimeRange(v as PnlTimeRange)}>
                    <SelectTrigger className="h-8 min-w-[200px] text-xs font-bold" aria-label="Durée du graphique PnL">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent align="end">
                      <SelectItem value="24h">⏱️ 24 Dernières Heures</SelectItem>
                      <SelectItem value="7d">📅 7 Derniers Jours</SelectItem>
                      <SelectItem value="30d">🗓️ 30 Derniers Jours (Défaut)</SelectItem>
                      <SelectItem value="90d">📊 90 Derniers Jours</SelectItem>
                      <SelectItem value="all">♾️ Historique Complet</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="text-left sm:text-right">
                  <span className="text-xs font-semibold text-muted-foreground block">
                    Solde initial : {num(pnlHistory.initial_balance, 2)} $ → Actuel : {num(pnlHistory.current_balance, 2)} $
                  </span>
                  <span className={cn('text-xs font-bold', Number(pnlHistory.total_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                    P&L Total : {Number(pnlHistory.total_pnl || 0) >= 0 ? '+' : ''}{num(pnlHistory.total_pnl, 2)} USD
                  </span>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {pnlPoints.length > 1 ? (
              <LineChart
                data={pnlPoints}
                color={Number(pnlHistory.total_pnl || 0) >= 0 ? '#34d399' : '#fb7185'}
                yAxisTitle="P&L Net Cumulé ($ USD)"
                xAxisTitle="Chronologie Temporelle (Date & Durée)"
                timeRange={pnlTimeRange}
              />
            ) : (
              <EmptyAnalytics text="Pas assez de trades enregistrés pour cette durée" />
            )}
          </CardContent>
        </Card>

        {/* ─── Score Historique ─── */}
        <Card className="xl:col-span-12">
          <CardHeader>
            <CardTitle>Historique des Scores Crypto</CardTitle>
          </CardHeader>
          <CardContent>
            <ScoreHistoryPanel />
          </CardContent>
        </Card>

        {/* ─── PnL par Heure ─── */}
        <Card className="xl:col-span-12 border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              ⏰ Performance & PnL par Heure de la Journée (00h - 23h UTC)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <HourlyPnLBarChart rows={heatmap.by_hour || []} />
          </CardContent>
        </Card>

        {/* ─── PnL par Jour ─── */}
        <Card className="xl:col-span-6 border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              📅 Performance par Jour de la Semaine
            </CardTitle>
          </CardHeader>
          <CardContent>
            <DailyPnLBarChart rows={heatmap.by_day || []} />
          </CardContent>
        </Card>

        {/* ─── Heatmap par Crypto ─── */}
        <Card className="xl:col-span-6 border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold flex items-center gap-2">
              🪙 Heatmap & PnL par Crypto-Actif
            </CardTitle>
          </CardHeader>
          <CardContent>
            <HeatmapList rows={heatmap.by_crypto || []} labelKey="symbol" />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ─── CapitalBreakdown ─────────────────────────────────────────────────────

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

// ─── ScoreHistoryPanel ────────────────────────────────────────────────────

function scoreTooltipLabel(date: Date, compactTimeOnly: boolean): string {
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  if (compactTimeOnly) return `${hour}:${minute}`
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${month}/${day} ${hour}:${minute}`
}

function ScoreHistoryPanel() {
  const [symbol, setSymbol] = useState('BTC/USD')
  const [hours, setHours] = useState('24')
  const scoreHistory = useDashboardStore((state) => state.scoreHistory)
  const refreshScoreHistory = useDashboardStore((state) => state.refreshScoreHistory)
  const scores = scoreHistory[`${symbol}|${hours}`] || []

  useEffect(() => {
    void refreshScoreHistory(symbol, hours)
  }, [symbol, hours, refreshScoreHistory])

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
      return { ...item, score: Math.round(smoothScore * 10) / 10 }
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
        {points.length >= 2 ? (
          <ScoreHistoryChart data={points} intervalHours={labelSpacingHours} periodHours={selectedHours} />
        ) : (
          <EmptyAnalytics text="Pas assez de scores historisés pour cette période" />
        )}
      </div>
    </div>
  )
}

// ─── HourlyPnLBarChart ────────────────────────────────────────────────────

function HourlyPnLBarChart({ rows }: { rows: JsonMap[] }) {
  if (!rows || !rows.length) return <EmptyAnalytics text="Aucun trade par heure à afficher" />

  const hourMap = new Map<number, JsonMap>()
  rows.forEach((r) => {
    const h = Number(r.hour)
    if (!isNaN(h)) hourMap.set(h, r)
  })

  const fullHours = Array.from({ length: 24 }, (_, i) => {
    const item = hourMap.get(i)
    return {
      hour: i,
      hourLabel: `${String(i).padStart(2, '0')}h`,
      trades: Number(item?.trades ?? 0),
      wins: Number(item?.wins ?? item?.winning_trades ?? 0),
      winRate: Number(item?.win_rate ?? 0),
      totalPnl: Number(item?.total_pnl ?? 0),
    }
  })

  const activeHours = fullHours.filter((h) => h.trades > 0)
  const bestHour = activeHours.length ? [...activeHours].sort((a, b) => b.totalPnl - a.totalPnl)[0] : null
  const worstHour = activeHours.length ? [...activeHours].sort((a, b) => a.totalPnl - b.totalPnl)[0] : null

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="flex items-center gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400 font-bold text-sm">🏆</div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Heure la Plus Profitable</div>
            <div className="text-xs font-bold text-emerald-400">
              {bestHour && bestHour.totalPnl > 0 ? (
                <>{bestHour.hourLabel} : +{num(bestHour.totalPnl, 4)} USD ({bestHour.trades} trade{bestHour.trades > 1 ? 's' : ''})</>
              ) : (
                'En attente de trades gagnants'
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-rose-500/20 text-rose-400 font-bold text-sm">⚠️</div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Heure la Moins Bonne</div>
            <div className="text-xs font-bold text-rose-400">
              {worstHour && worstHour.totalPnl < 0 ? (
                <>{worstHour.hourLabel} : {num(worstHour.totalPnl, 4)} USD ({worstHour.trades} trade{worstHour.trades > 1 ? 's' : ''})</>
              ) : (
                'Aucune perte horaire'
              )}
            </div>
          </div>
        </div>
      </div>

      <HourlyBarChart data={fullHours} />
    </div>
  )
}

// ─── DailyPnLBarChart ─────────────────────────────────────────────────────

function DailyPnLBarChart({ rows }: { rows: JsonMap[] }) {
  if (!rows || !rows.length) return <EmptyAnalytics text="Aucun trade par jour à afficher" />

  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
  const frDays: Record<string, string> = {
    Monday: 'Lun', Tuesday: 'Mar', Wednesday: 'Mer', Thursday: 'Jeu',
    Friday: 'Ven', Saturday: 'Sam', Sunday: 'Dim',
  }

  const dayMap = new Map<string, JsonMap>()
  rows.forEach((r) => dayMap.set(asString(r.day), r))

  const fullDays = dayNames.map((d) => {
    const item = dayMap.get(d)
    return {
      day: d,
      label: frDays[d] || d,
      trades: Number(item?.trades ?? 0),
      totalPnl: Number(item?.total_pnl ?? 0),
      winRate: Number(item?.win_rate ?? 0),
    }
  })

  return (
    <div className="pt-2">
      <DailyBarChart data={fullDays} />
    </div>
  )
}

// ─── HeatmapList ──────────────────────────────────────────────────────────

function HeatmapList({
  rows,
  labelKey,
  compact = false,
}: {
  rows: JsonMap[]
  labelKey: string
  compact?: boolean
}) {
  if (!rows.length) return <EmptyAnalytics text="Aucune donnée" />
  return (
    <div className="space-y-2">
      {rows.map((row, index) => {
        const pnl = Number(row.total_pnl ?? row.pnl ?? 0)
        return (
          <div
            key={`${asString(row[labelKey])}-${index}`}
            className="flex items-center justify-between rounded-md border border-border bg-background p-3"
          >
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
