/**
 * views/ConfigView.tsx — Vue Configuration du dashboard Aegis
 */

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { postJson } from '@/lib/api'
import { asString } from '@/lib/formatters'
import type { ConfigPayload } from '@/types/dashboard'

export function ConfigView({
  config,
  setConfig,
  refresh,
}: {
  config: ConfigPayload
  setConfig: (value: ConfigPayload) => void
  refresh: () => Promise<void>
}) {
  const fields = config.fields || []
  const values =
    config.values ||
    Object.fromEntries(fields.map((field) => [field.name, field.value ?? '']))

  const save = async () => {
    const result = await postJson<ConfigPayload>('/api/config', { values })
    setConfig(result)
    await refresh()
  }

  return (
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
          </label>
        ))}
      </CardContent>
    </Card>
  )
}
