/**
 * views/ConsoleView.tsx — Vue Console Bot du dashboard Aegis
 */

import { ChevronDown, RefreshCw, ScrollText } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { ConsolePayload } from '@/types/dashboard'

export function ConsoleView({
  data,
  onRefresh,
}: {
  data: ConsolePayload
  onRefresh: (lines?: string | number) => Promise<void>
}) {
  const [limit, setLimit] = useState('500')
  const [pinned, setPinned] = useState(true)
  const [cleared, setCleared] = useState(false)
  const outputRef = useRef<HTMLDivElement>(null)
  const lines = cleared ? [] : data.lines || []

  // Scroll to bottom instantly before paint
  useLayoutEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [lines.length])

  useEffect(() => {
    if (pinned && outputRef.current && lines.length > 0) {
      outputRef.current.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [lines.length, pinned])

  const handleLimitChange = (value: string) => {
    setLimit(value)
    setCleared(false)
    void onRefresh(value)
  }

  const handleScroll = () => {
    const el = outputRef.current
    if (!el) return
    setPinned(el.scrollTop + el.clientHeight >= el.scrollHeight - 40)
  }

  const pinToBottom = () => {
    setPinned(true)
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-4 w-4 text-primary" />
            Console Bot
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={limit} onValueChange={handleLimitChange}>
              <SelectTrigger aria-label="Nombre de lignes console" className="min-w-[126px]">
                <SelectValue placeholder="500 lignes" />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectItem value="500">500 lignes</SelectItem>
                <SelectItem value="1500">1 500 lignes</SelectItem>
                <SelectItem value="5000">5 000 lignes</SelectItem>
                <SelectItem value="all">Tout voir</SelectItem>
              </SelectContent>
            </Select>
            <Button variant={pinned ? 'secondary' : 'outline'} size="sm" onClick={pinToBottom}>
              <ChevronDown className="h-4 w-4" />
              {pinned ? 'Auto' : 'Bas'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCleared(true)}>Clear</Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { setCleared(false); void onRefresh(limit) }}
            >
              <RefreshCw className="h-4 w-4" />
              Actualiser
            </Button>
            <span className="text-[11px] text-muted-foreground">{lines.length} lignes</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div
          ref={outputRef}
          onScroll={handleScroll}
          className="min-h-[500px] max-h-[calc(100vh-200px)] overflow-auto bg-[#060809] p-4 font-mono text-[11px] leading-[1.6] text-[#c8d6e5]"
        >
          {lines.length === 0 && <div className="text-muted-foreground">Aucune ligne console</div>}
          {lines.map((line, index) => (
            <div key={`${line}-${index}`} className={cn('whitespace-pre-wrap break-all', consoleLineClass(line))}>
              {stripAnsi(line)}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function stripAnsi(line: string) {
  return line.replace(/\x1b\[[0-9;]*m/g, '')
}

function consoleLineClass(line: string) {
  if (/❌|error|erreur|failed|échou/i.test(line)) return 'text-rose-300'
  if (/⚠️|warn|warning/i.test(line)) return 'text-amber-300'
  if (/✅|success|succès/i.test(line)) return 'text-emerald-300'
  if (/🎯|buy|achat|sell|vente/i.test(line)) return 'text-sky-300'
  return 'text-[#c8d6e5]'
}
