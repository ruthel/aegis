/**
 * views/ConfigView.tsx — Vue Configuration du dashboard Aegis
 */

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { postJson } from '@/lib/api'
import { asString } from '@/lib/formatters'
import type { ConfigPayload } from '@/types/dashboard'
import axios from 'axios'
import { ShieldAlert, Zap } from 'lucide-react'

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

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Mode trading</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 rounded-md border border-border bg-background p-4 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-sm font-black">
                {paperEnabled ? <ShieldAlert className="h-4 w-4 text-sky-300" /> : <Zap className="h-4 w-4 text-emerald-300" />}
                {paperEnabled ? 'Paper trading' : 'Live trading'}
              </div>
              <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
                {paperEnabled
                  ? 'Simulation active. Les ordres restent dans la couche comptable interne.'
                  : 'Mode live actif. Les prochains ordres peuvent être envoyés à l’exchange configuré après redémarrage du bot.'}
              </p>
              {!liveReady && (
                <p className="text-xs font-bold text-amber-300">Clés API exchange non détectées: le passage en live sera refusé.</p>
              )}
              {errors.PAPER_TRADING && <p className="text-xs font-bold text-rose-300">{errors.PAPER_TRADING}</p>}
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-muted-foreground">Paper</span>
              <Switch checked={!paperEnabled} onCheckedChange={(checked) => void setTradingMode(!checked)} />
              <span className="text-xs font-bold text-muted-foreground">Live</span>
            </div>
          </div>
        </CardContent>
      </Card>

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
              <span className="text-xs font-bold uppercase text-muted-foreground">
                {field.label || field.name}
              </span>
              <Input
                value={asString(values[field.name], '')}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    values: { ...values, [field.name]: event.target.value },
                  })
                }
              />
              {errors[field.name] && <span className="text-xs font-bold text-rose-300">{errors[field.name]}</span>}
            </label>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
