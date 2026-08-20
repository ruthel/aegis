/**
 * views/ConfigView.tsx — Vue Configuration du dashboard Aegis
 */

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getJson, postJson } from '@/lib/api'
import { asString } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import type { ConfigField, ConfigPayload } from '@/types/dashboard'
import axios from 'axios'
import { Award, BrainCircuit, CheckCircle2, Database, Loader2, Play, Rocket, ShieldAlert, SlidersHorizontal, Sparkles, Zap } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'

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
  const retrainingRunning = Boolean(retraining.running)
  const [manualCheckOnly, setManualCheckOnly] = useState(values.ML_AUTO_RETRAIN_CHECK_ONLY !== 'False')
  const [manualFast, setManualFast] = useState(values.ML_AUTO_RETRAIN_FAST === 'True')
  const [retrainBusy, setRetrainBusy] = useState(false)
  const [promoteBusy, setPromoteBusy] = useState(false)
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
