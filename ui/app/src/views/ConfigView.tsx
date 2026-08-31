/**
 * views/ConfigView.tsx — Vue Configuration du dashboard Aegis
 */

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getJson, postJson } from '@/lib/api'
import { asString } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import type { ConfigField, ConfigPayload } from '@/types/dashboard'
import axios from 'axios'
import { Award, BrainCircuit, CheckCircle2, Database, Loader2, Play, RefreshCw, Rocket, ShieldAlert, SlidersHorizontal, Sparkles, Square, Zap } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'

type ReplayStatus = {
  running?: boolean
  exit_code?: number | null
  total_rejected?: number
  replayed?: number
  pending?: number
  remaining?: number
  last_run_at?: string | null
  last_run_replayed?: number | null
  interval_seconds?: number
  next_run_at?: string | null
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function formatCountdown(iso?: string | null): string {
  if (!iso) return ''
  const target = new Date(iso).getTime()
  if (Number.isNaN(target)) return ''
  const diffMs = target - Date.now()
  if (diffMs <= 0) return 'imminent (au prochain cycle du bot)'
  const mins = Math.round(diffMs / 60000)
  if (mins < 60) return `dans ~${mins} min`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return `dans ~${hours}h${rem > 0 ? String(rem).padStart(2, '0') : ''}`
}

export function ConfigView({
  config,
  setConfig,
  refresh,
}: {
  config: ConfigPayload
  setConfig: (value: ConfigPayload) => void
  refresh: () => Promise<void>
}) {
  const fields = (config.fields || []).filter((field) => field.name !== 'PAPER_TRADING')
  const values =
    config.values ||
    Object.fromEntries((config.fields || []).map((field) => [field.name, field.value ?? '']))
  const paperEnabled = values.PAPER_TRADING !== 'False'
  const liveReady = Boolean(config.trading_mode?.live_ready)
  const errors = config.errors || {}
  const retraining = config.ml_retraining || {}
  const evaluations = config.ml_model_evaluations || []
  const riskSizing = config.risk_sizing || {}
  const sizingRecommendations = config.ml_sizing_recommendations || []
  const sizingBacktests = config.ml_sizing_backtests || []
  const retrainingRunning = Boolean(retraining.running)
  const [manualCheckOnly, setManualCheckOnly] = useState(values.ML_AUTO_RETRAIN_CHECK_ONLY !== 'False')
  const [manualFast, setManualFast] = useState(values.ML_AUTO_RETRAIN_FAST === 'True')
  const [retrainBusy, setRetrainBusy] = useState(false)
  const [promoteBusy, setPromoteBusy] = useState(false)
  const [replayBusy, setReplayBusy] = useState(false)
  const [replayStatus, setReplayStatus] = useState<ReplayStatus>({})
  const [replayLogs, setReplayLogs] = useState<string[]>([])
  const tradingFields = fields.filter((field) => ['Trading', 'Risque', 'Support Touch', 'Bear Mode', 'Scoring'].includes(field.section || ''))
  const mlFields = fields.filter((field) => field.section === 'ML Retraining')

  useEffect(() => {
    if (!retrainingRunning) return
    const id = window.setInterval(async () => {
      try {
        const result = await getJson<{ ok: boolean; status?: ConfigPayload['ml_retraining'] }>('/api/ml/retrain/status')
        setConfig({ ...config, ml_retraining: result.status })
      } catch {
        // Le polling est informatif; la vue Config se rafraichira aussi au prochain passage.
      }
    }, 3000)
    return () => window.clearInterval(id)
  }, [config, retrainingRunning, setConfig])

  // Charger le statut + les logs dédiés du replay au montage, puis poller.
  useEffect(() => {
    let active = true
    const fetchStatus = async () => {
      try {
        const result = await getJson<ReplayStatus & { ok: boolean }>('/api/ml/replay/status')
        if (active) setReplayStatus(result)
      } catch {
        // informatif
      }
      try {
        const logs = await getJson<{ ok: boolean; lines: string[] }>('/api/ml/replay/logs?lines=200')
        if (active) setReplayLogs(logs.lines || [])
      } catch {
        // informatif
      }
    }
    void fetchStatus()
    const id = window.setInterval(fetchStatus, 3000)
    return () => {
      active = false
      window.clearInterval(id)
    }
  }, [])

  const replayRunning = Boolean(replayStatus.running)

  const startReplay = async (fullCatchup = false) => {
    if (replayRunning) return
    setReplayBusy(true)
    try {
      const body = fullCatchup ? { max_replay: 5000 } : {}
      const result = await postJson<ReplayStatus & { ok: boolean; error?: string }>('/api/ml/replay/start', body)
      setReplayStatus(result)
    } finally {
      setReplayBusy(false)
    }
  }

  const stopReplay = async () => {
    setReplayBusy(true)
    try {
      const result = await postJson<ReplayStatus & { ok: boolean }>('/api/ml/replay/stop', {})
      setReplayStatus(result)
    } finally {
      setReplayBusy(false)
    }
  }

  const save = async () => {
    try {
      const result = await postJson<ConfigPayload>('/api/config', { values })
      setConfig(result)
      await refresh()
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.data) setConfig(error.response.data as ConfigPayload)
      else throw error
    }
  }

  const setTradingMode = async (nextPaper: boolean) => {
    if (!nextPaper) {
      const confirmed = window.confirm(
        'Activer le mode LIVE enverra de vrais ordres sur l’exchange configuré. Le bot doit être arrêté et les clés API doivent être configurées. Continuer ?',
      )
      if (!confirmed) return
    }
    const nextValues = { ...values, PAPER_TRADING: nextPaper ? 'True' : 'False' }
    try {
      const result = await postJson<ConfigPayload>('/api/config', { values: nextValues })
      setConfig(result)
      await refresh()
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.data) setConfig(error.response.data as ConfigPayload)
      else throw error
    }
  }

  const startRetraining = async () => {
    setRetrainBusy(true)
    try {
      const result = await postJson<{ ok: boolean; status?: ConfigPayload['ml_retraining']; reason?: string }>(
        '/api/ml/retrain/start',
        { check_only: manualCheckOnly, fast: manualFast },
      )
      setConfig({ ...config, ml_retraining: result.status })
    } finally {
      setRetrainBusy(false)
    }
  }

  const startPromotion = async () => {
    const confirmed = window.confirm(
      'Lancer une promotion manuelle va entraîner/évaluer le Challenger et promouvoir seulement si les garde-fous passent. Continuer ?',
    )
    if (!confirmed) return
    setPromoteBusy(true)
    try {
      const result = await postJson<{ ok: boolean; status?: ConfigPayload['ml_retraining']; reason?: string }>(
        '/api/ml/promote/start',
        { fast: manualFast },
      )
      setConfig({ ...config, ml_retraining: result.status })
    } finally {
      setPromoteBusy(false)
    }
  }

  const renderConfigFields = (items: ConfigField[]) => (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {items.map((field) => (
        <label
          key={field.name}
          className={cn(
            'group block rounded-lg border bg-background/70 p-3 transition-colors',
            errors[field.name] ? 'border-rose-500/45 bg-rose-500/[0.04]' : 'border-border/80 hover:border-primary/35',
          )}
        >
          <span className="flex min-h-9 items-start justify-between gap-3">
            <span>
              <span className="block text-[13px] font-black leading-snug text-foreground">
                {field.label || field.name}
              </span>
              <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">
                {field.name}
              </span>
            </span>
            {errors[field.name] ? (
              <span className="rounded-full border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 text-[11px] font-black text-rose-200">
                erreur
              </span>
            ) : null}
          </span>
          <Input
            className="mt-3 h-9 border-border/70 bg-card/80 font-mono"
            value={asString(values[field.name], '')}
            onChange={(event) =>
              setConfig({
                ...config,
                values: { ...values, [field.name]: event.target.value },
              })
            }
          />
          {errors[field.name] && <span className="mt-2 block text-[13px] font-bold text-rose-300">{errors[field.name]}</span>}
        </label>
      ))}
    </div>
  )

  return (
    <div className="space-y-4">
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex flex-col gap-4 border-b border-border px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary">
                <SlidersHorizontal className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-[16px] font-black leading-none">Configuration</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  Paramètres de trading, moteur ML et gouvernance du modèle.
                </p>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[520px]">
            <StatusTile label="Mode" value={paperEnabled ? 'Paper' : 'Live'} tone={paperEnabled ? 'info' : 'good'} />
            <StatusTile label="Live ready" value={liveReady ? 'Oui' : 'Non'} tone={liveReady ? 'good' : 'warn'} />
            <StatusTile label="ML job" value={retrainingRunning ? 'Actif' : 'Repos'} tone={retrainingRunning ? 'good' : 'muted'} />
            <StatusTile label="Évals" value={String(evaluations.length)} tone="info" />
          </div>
        </div>
      </section>

      <Tabs defaultValue="trading" className="space-y-4">
        <TabsList className="flex w-full flex-wrap justify-start rounded-lg bg-card">
          <TabsTrigger value="trading" className="gap-2"><Rocket className="h-4 w-4" />Trading</TabsTrigger>
          <TabsTrigger value="ml" className="gap-2"><BrainCircuit className="h-4 w-4" />ML</TabsTrigger>
          <TabsTrigger value="evaluations" className="gap-2"><Award className="h-4 w-4" />Évaluations</TabsTrigger>
          <TabsTrigger value="advanced" className="gap-2"><Database className="h-4 w-4" />Avancé</TabsTrigger>
        </TabsList>

      <TabsContent value="trading" className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Mode trading</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4 rounded-lg border border-border/80 bg-background/70 p-4 md:flex-row md:items-center md:justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-[13px] font-black">
                  {paperEnabled ? <ShieldAlert className="h-4 w-4 text-sky-300" /> : <Zap className="h-4 w-4 text-emerald-300" />}
                  {paperEnabled ? 'Paper trading' : 'Live trading'}
                </div>
                <p className="max-w-2xl text-[13px] leading-6 text-muted-foreground">
                  {paperEnabled
                    ? 'Simulation active. Les ordres restent dans la couche comptable interne.'
                    : 'Mode live actif. Les prochains ordres peuvent être envoyés à l’exchange configuré après redémarrage du bot.'}
                </p>
                {!liveReady && (
                  <p className="text-[13px] font-bold text-amber-300">Clés API exchange non détectées: le passage en live sera refusé.</p>
                )}
                {errors.PAPER_TRADING && <p className="text-[13px] font-bold text-rose-300">{errors.PAPER_TRADING}</p>}
              </div>
              <div className="flex min-h-11 items-center gap-3 rounded-full border border-border bg-card px-4">
                <span className="text-[13px] font-bold text-muted-foreground">Paper</span>
                <Switch checked={!paperEnabled} onCheckedChange={(checked) => void setTradingMode(!checked)} />
                <span className="text-[13px] font-bold text-muted-foreground">Live</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <ConfigFieldsCard title="Paramètres trading" onSave={save}>
          {renderConfigFields(tradingFields)}
        </ConfigFieldsCard>
      </TabsContent>

      <TabsContent value="ml" className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              Sizing ML & garde-fous
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <MetricPill label="Taille trade base" value={`${formatNumber(riskSizing.trade_amount_usd)} USD`} />
              <MetricPill label="Max / position" value={`${formatNumber(riskSizing.max_position_size_usd)} USD`} />
              <MetricPill label="Expo capital max" value={`${formatNumber(riskSizing.max_total_capital_exposure_pct)}%`} />
              <MetricPill label="Positions max" value={`${asString(riskSizing.max_total_positions, '--')} total · ${asString(riskSizing.max_positions_per_crypto, '--')} / crypto`} />
            </div>
            <div className="rounded-lg border border-border/80 bg-background/70">
              <div className="grid grid-cols-[1fr_80px_110px_1fr] gap-2 border-b border-border px-3 py-2 text-[11px] font-black uppercase text-muted-foreground">
                <span>Symbole</span>
                <span>Facteur</span>
                <span>Taille</span>
                <span>Raison</span>
              </div>
              {sizingRecommendations.length === 0 ? (
                <div className="px-3 py-3 text-[13px] text-muted-foreground">Aucune recommandation sizing enregistrée.</div>
              ) : (
                sizingRecommendations.slice(0, 6).map((item, index) => (
                  <div key={`${asString(item.sizing_id || item.symbol)}-${index}`} className="grid grid-cols-[1fr_80px_110px_1fr] gap-2 border-b border-border/60 px-3 py-2 text-[12.5px] last:border-b-0">
                    <strong>{asString(item.symbol)}</strong>
                    <span className="font-black text-emerald-300">{formatNumber(item.sizing_factor)}x</span>
                    <span>{formatNumber(item.final_position_size_usd)} USD</span>
                    <span className="truncate text-muted-foreground" title={asString(item.reason)}>{asString(item.reason, '--')}</span>
                  </div>
                ))
              )}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {sizingBacktests.length === 0 ? (
                <div className="rounded-lg border border-border bg-background/70 p-3 text-[13px] text-muted-foreground md:col-span-3">
                  Aucun replay sizing enregistré.
                </div>
              ) : sizingBacktests.slice(0, 3).map((item, index) => (
                <div key={`${asString(item.run_id)}-${index}`} className="rounded-lg border border-border bg-background/70 p-3">
                  <div className="text-[12px] font-bold uppercase text-muted-foreground">Replay sizing</div>
                  <div className="mt-1 text-[13px] font-black">{asString(item.samples, '0')} samples</div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
                    <span className="text-muted-foreground">Fixe</span>
                    <strong>{formatNumber(item.baseline_pnl_usd)} USD</strong>
                    <span className="text-muted-foreground">ML</span>
                    <strong>{formatNumber(item.sizing_pnl_usd)} USD</strong>
                    <span className="text-muted-foreground">Delta</span>
                    <strong className={Number(item.pnl_delta_usd) >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                      {Number(item.pnl_delta_usd) >= 0 ? '+' : ''}{formatNumber(item.pnl_delta_usd)} USD
                    </strong>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <BrainCircuit className="h-4 w-4 text-emerald-300" />
                ML Retraining
              </CardTitle>
              <span
                className={
                  retrainingRunning
                    ? 'rounded-full border border-emerald-500/50 bg-emerald-500/15 px-3 py-1 text-[13px] font-black text-emerald-200'
                    : 'rounded-full border border-border bg-background px-3 py-1 text-[13px] font-black text-muted-foreground'
                }
              >
                {retrainingRunning ? 'En cours' : 'Inactif'}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 lg:grid-cols-[1fr_auto_auto] lg:items-end">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">Déclencheur</div>
                  <div className="mt-1 font-black">{asString(retraining.trigger || 'aucun')}</div>
                </div>
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">PID</div>
                  <div className="mt-1 font-black">{asString(retraining.pid || '--')}</div>
                </div>
                <label className="flex items-center justify-between gap-3 rounded-lg border border-border/80 bg-background/70 p-3">
                  <span>
                    <span className="block text-[13px] font-bold uppercase text-muted-foreground">Check-only</span>
                    <span className="text-[13px] text-muted-foreground">Valide sans promotion directe</span>
                  </span>
                  <Switch checked={manualCheckOnly} onCheckedChange={setManualCheckOnly} />
                </label>
                <label className="flex items-center justify-between gap-3 rounded-lg border border-border/80 bg-background/70 p-3">
                  <span>
                    <span className="block text-[13px] font-bold uppercase text-muted-foreground">Fast</span>
                    <span className="text-[13px] text-muted-foreground">Mode rapide si disponible</span>
                  </span>
                  <Switch checked={manualFast} onCheckedChange={setManualFast} />
                </label>
              </div>
              <Button className="min-w-44" disabled={retrainingRunning || retrainBusy} onClick={() => void startRetraining()}>
                {retrainingRunning || retrainBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                Réentraîner
              </Button>
              <Button className="min-w-52" variant="outline" disabled={retrainingRunning || promoteBusy} onClick={() => void startPromotion()}>
                {retrainingRunning || promoteBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Award className="mr-2 h-4 w-4" />}
                Promouvoir challenger
              </Button>
            </div>
            <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
              La promotion manuelle lance le pipeline sans check-only: le Challenger est promu seulement si les garde-fous passent.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-primary" />
                Replay des refus ML
              </CardTitle>
              <span
                className={
                  replayRunning
                    ? 'rounded-full border border-emerald-500/50 bg-emerald-500/15 px-3 py-1 text-[13px] font-black text-emerald-200'
                    : 'rounded-full border border-border bg-background px-3 py-1 text-[13px] font-black text-muted-foreground'
                }
              >
                {replayRunning ? 'En cours' : 'Inactif'}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 lg:grid-cols-[1fr_auto_auto] lg:items-end">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">Refus total</div>
                  <div className="mt-1 font-black">{asString(replayStatus.total_rejected ?? '--')}</div>
                </div>
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">Rejoués</div>
                  <div className="mt-1 font-black text-emerald-400">{asString(replayStatus.replayed ?? '--')}</div>
                </div>
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">Restants</div>
                  <div className="mt-1 font-black text-amber-300">{asString(replayStatus.remaining ?? '--')}</div>
                </div>
                <div className="rounded-lg border border-border/80 bg-background/70 p-3">
                  <div className="text-[13px] font-bold uppercase text-muted-foreground">Prochain replay auto</div>
                  <div className="mt-1 font-black">{formatDateTime(replayStatus.next_run_at)}</div>
                  <div className="text-[11px] text-muted-foreground">{formatCountdown(replayStatus.next_run_at)}</div>
                </div>
              </div>
              {replayRunning ? (
                <Button className="min-w-44" variant="destructive" disabled={replayBusy} onClick={() => void stopReplay()}>
                  {replayBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Square className="mr-2 h-4 w-4" />}
                  Arrêter le replay
                </Button>
              ) : (
                <Button className="min-w-44" disabled={replayBusy} onClick={() => void startReplay(false)}>
                  {replayBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                  Lancer le replay
                </Button>
              )}
              <Button className="min-w-52" variant="outline" disabled={replayRunning || replayBusy} onClick={() => void startReplay(true)}>
                {replayRunning || replayBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                Rattraper tout le backlog
              </Button>
            </div>

            {(() => {
              const total = Number(replayStatus.total_rejected ?? 0)
              const done = Number(replayStatus.replayed ?? 0)
              const pctDone = total > 0 ? Math.min(100, (done / total) * 100) : 0
              return (
                <div className="mt-4">
                  <div className="mb-1 flex items-center justify-between text-[12px] text-muted-foreground">
                    <span>Progression du rattrapage</span>
                    <span className="font-bold">{done} / {total} rejoués ({pctDone.toFixed(1)}%)</span>
                  </div>
                  <Progress value={pctDone} />
                  {replayRunning && (
                    <div className="mt-2 flex items-center gap-2 text-[12px] text-emerald-300">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Replay en cours...
                    </div>
                  )}
                </div>
              )
            })()}

            {replayLogs.length > 0 && (
              <div className="mt-4">
                <div className="mb-1 text-[12px] font-bold uppercase text-muted-foreground">Logs du replay</div>
                <pre className="max-h-56 overflow-auto rounded-lg border border-border bg-black/40 p-3 font-mono text-[11px] leading-5 text-emerald-200/90">
                  {replayLogs.join('\n')}
                </pre>
              </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
              <span>Dernier run : <strong className="text-foreground">{formatDateTime(replayStatus.last_run_at)}</strong>{replayStatus.last_run_replayed != null ? ` (+${replayStatus.last_run_replayed} rejoués)` : ''}</span>
              <span>·</span>
              <span>Prochain replay auto : <strong className="text-foreground">{formatDateTime(replayStatus.next_run_at)}</strong> {formatCountdown(replayStatus.next_run_at)}</span>
            </div>
            <p className="mt-3 text-[13px] leading-6 text-muted-foreground">
              Le replay rejoue les refus ML passés avec les bougies futures réelles pour vérifier s'ils auraient été gagnants, puis les prépare pour le prochain réentraînement. « Lancer le replay » traite un lot (plafond configuré) ; « Rattraper tout le backlog » force un plafond élevé pour tout traiter en un run. La progression détaillée s'affiche ci-dessus (logs dédiés, non mélangés avec le bot). Le replay tourne aussi automatiquement selon l'intervalle configuré (par défaut toutes les 6h).
            </p>
          </CardContent>
        </Card>

        <ConfigFieldsCard title="Paramètres ML automatiques" onSave={save}>
          {renderConfigFields(mlFields)}
        </ConfigFieldsCard>
      </TabsContent>

      <TabsContent value="evaluations" className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Évaluations Champion / Challenger</CardTitle>
          </CardHeader>
          <CardContent>
            {evaluations.length === 0 ? (
              <div className="rounded-lg border border-border bg-background p-4 text-[13px] text-muted-foreground">
                Aucune comparaison enregistrée.
              </div>
            ) : (
              <div className="space-y-2">
                {evaluations.map((item, index) => (
                  <ModelEvaluationItem key={`${item.timestamp || 'eval'}-${index}`} item={item} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="advanced" className="space-y-4">
        <ConfigFieldsCard title="Configuration complète" onSave={save}>
        {renderConfigFields(fields)}
      </ConfigFieldsCard>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ConfigFieldsCard({ title, onSave, children }: { title: string; onSave: () => Promise<void>; children: ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          <Button size="sm" onClick={() => void onSave()}>Sauver</Button>
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function ModelEvaluationItem({ item }: { item: NonNullable<ConfigPayload['ml_model_evaluations']>[number] }) {
  const metrics = item.metrics || {}
  const guardrails = typeof metrics.guardrails === 'object' && metrics.guardrails ? metrics.guardrails as Record<string, unknown> : null
  const event = asString(item.event_type, 'evaluation')
  const promoted = event === 'promotion'
  const rejected = event === 'promotion_rejected'
  const badgeClass = promoted
    ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-200'
    : rejected
      ? 'border-rose-500/50 bg-rose-500/15 text-rose-200'
      : 'border-amber-500/50 bg-amber-500/15 text-amber-200'

  return (
    <div className="rounded-lg border border-border bg-background/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[13px] font-black">{formatEventLabel(event)}</div>
          <div className="text-[13px] text-muted-foreground">{asString(item.timestamp || '--')} · {asString(item.trigger_type || 'auto')}</div>
        </div>
        <span className={`rounded-full border px-3 py-1 text-[13px] font-black ${badgeClass}`}>
          {promoted ? 'Promu' : rejected ? 'Rejeté' : 'Évalué'}
        </span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <MetricPill label="Precision champ." value={formatPct(metrics.champion_precision)} />
        <MetricPill label="Precision chall." value={formatPct(metrics.challenger_precision)} />
        <MetricPill label="Accuracy champ." value={formatPct(metrics.champion_accuracy)} />
        <MetricPill label="Accuracy chall." value={formatPct(metrics.challenger_accuracy)} />
      </div>
      {item.reason && <div className="mt-3 text-[13px] leading-6 text-muted-foreground">{item.reason}</div>}
      {guardrails && (
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(guardrails).slice(0, 8).map(([name, passed]) => (
            <span
              key={name}
              className={
                passed
                  ? 'rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-bold text-emerald-200'
                  : 'rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] font-bold text-rose-200'
              }
            >
              {name}: {passed ? 'OK' : 'NON'}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card/40 px-3 py-2">
      <div className="text-[12px] font-bold uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 font-black">{value}</div>
    </div>
  )
}

function formatNumber(value: unknown, digits = 2) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--'
}

function StatusTile({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: 'good' | 'warn' | 'info' | 'muted'
}) {
  const toneClass =
    tone === 'good'
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
      : tone === 'warn'
        ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
        : tone === 'info'
          ? 'border-blue-500/30 bg-blue-500/10 text-blue-200'
          : 'border-border bg-background text-muted-foreground'
  return (
    <div className={cn('rounded-lg border px-3 py-2', toneClass)}>
      <div className="flex items-center gap-1.5 text-[11px] font-black uppercase opacity-80">
        {tone === 'good' ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
        {label}
      </div>
      <div className="mt-1 text-[13px] font-black text-foreground">{value}</div>
    </div>
  )
}

function formatPct(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '--'
  return `${n.toFixed(1)}%`
}

function formatEventLabel(event: string) {
  if (event === 'promotion') return 'Promotion challenger'
  if (event === 'promotion_rejected') return 'Promotion rejetée'
  if (event === 'promotion_checked') return 'Validation sans promotion'
  if (event === 'promotion_guardrails_evaluated') return 'Garde-fous évalués'
  return event
}
