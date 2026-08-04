/**
 * views/LiveView.tsx — Vue principale "Live" du dashboard Aegis
 */

import { Activity, CircleDollarSign, EllipsisVertical, ListChecks, Power, RefreshCw, WalletCards } from 'lucide-react'
import { useMemo } from 'react'
import { useIntl } from 'react-intl'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  asString,
  abbreviateRegime,
  cooldownDurationText,
  decisionExplanation,
  decisionMetricChips,
  decisionReasonTitle,
  formatDateWithRelative,
  formatDecisionTime,
  formatLivePercent,
  formatLivePrice,
  formatLiveVolumeUsd,
  formatSignedPct,
  liveSymbolItem,
  num,
  pct,
  supportBySymbolMap,
} from '@/lib/formatters'
import { postJson } from '@/lib/api'
import { MetricCard, SplitMetricCard, EntryBox, MlAnalyticsTile, QuoteBox } from '@/components/ui/shared'
import type { JsonMap, MlStatus, StatusPayload } from '@/types/dashboard'

const pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD']

export function LiveView({ status, ml }: { status: StatusPayload; ml: MlStatus }) {
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
            const stale =
              item.last_tick_age_seconds === undefined || item.last_tick_age_seconds === null
                ? false
                : Number(item.last_tick_age_seconds) > 30
            return (
              <div
                key={symbol}
                className="min-w-0 rounded-lg border border-border bg-[linear-gradient(145deg,rgba(27,32,38,0.96),rgba(18,22,27,0.98))] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-transform hover:-translate-y-px hover:border-white/20"
              >
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
                  <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] font-semibold text-muted-foreground">
                    Spread {spread !== undefined ? formatLivePercent(spread, 2) : '--'}
                  </span>
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
            const pContinue = Number(
              mlExit.p_continue ??
                asString(exitRec.reason).match(/ml_continue_([\d.]+)%/)?.[1] ??
                0,
            )
            const rec = asString(item.recommendation, 'NEUTRAL')
            const exitDecision = asString(exitRec.decision, 'HOLD').toUpperCase()
            const variant = inSellMode
              ? exitDecision === 'FORCE_EXIT' ? 'danger' : 'success'
              : rec === 'BUY_HIGH_CONFIDENCE' ? 'success' : rec === 'REJECT_RISK' ? 'danger' : 'warning'
            const label = inSellMode
              ? exitDecision === 'FORCE_EXIT' ? 'VENTE ML' : 'POSITION OUVERTE'
              : rec === 'BUY_HIGH_CONFIDENCE'
                ? 'ACHAT RECOMMANDÉ'
                : rec === 'REJECT_RISK'
                  ? 'RISQUE ÉLEVÉ (<50%)'
                  : 'NEUTRE (50-65%)'
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
                  <span className="text-muted-foreground">
                    {inSellMode ? 'Probabilité de continuer (P_continue)' : 'Probabilité de Gain (P_win)'}
                  </span>
                  <span className="font-black" style={{ color }}>{pct(shownProbability, 1)}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full transition-all"
                    style={{ width: `${Math.max(0, Math.min(100, shownProbability))}%`, background: color }}
                  />
                </div>
                <div className="mt-3 flex justify-between text-[10px] text-muted-foreground">
                  <span>
                    {inSellMode
                      ? `Décision sortie: ${exitDecision}`
                      : `Seuil Requis: ${num(item.min_probability ?? ml.min_probability, 0)}%`}
                  </span>
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
              {status.support_touch?.last_run
                ? `Backtest ${formatDateWithRelative(status.support_touch.last_run)}`
                : 'Backtest --'}
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
          <p className="py-2 text-center text-[11px] text-muted-foreground">
            +{decisions.length - visible.length} décision(s) plus ancienne(s) masquée(s)
          </p>
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
          const tone =
            body.includes('Erreur') || body.includes('failed') || body.includes('bloqué')
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
