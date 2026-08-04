/**
 * components/ui/shared.tsx — Composants UI génériques partagés entre les vues
 */

import type { LayoutDashboard } from 'lucide-react'
import { cn } from '@/lib/utils'
import { asString } from '@/lib/formatters'

// ─── MetricCard ────────────────────────────────────────────────────────────

export function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof LayoutDashboard
  label: string
  value: string
}) {
  return (
    <div className="rounded-lg border border-indigo-500/20 bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[10px] font-bold uppercase text-muted-foreground">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-muted text-primary">
          <Icon className="h-4 w-4" />
        </span>
        {label}
      </div>
      <div className="mt-3 text-lg font-black leading-tight">{value}</div>
    </div>
  )
}

// ─── SplitMetricCard ───────────────────────────────────────────────────────

export function SplitMetricCard({
  label,
  leftLabel,
  leftValue,
  rightLabel,
  rightValue,
}: {
  label: string
  leftLabel: string
  leftValue: string
  rightLabel: string
  rightValue: string
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase text-muted-foreground">{label}</div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-[9px] font-bold uppercase text-muted-foreground">{leftLabel}</div>
          <div className="text-base font-black leading-tight">{leftValue}</div>
        </div>
        <div className="h-8 w-px bg-border" />
        <div className="text-right">
          <div className="text-[9px] font-bold uppercase text-muted-foreground">{rightLabel}</div>
          <div className="text-base font-black leading-tight">{rightValue}</div>
        </div>
      </div>
    </div>
  )
}

// ─── QuoteBox ─────────────────────────────────────────────────────────────

export function QuoteBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="mb-0.5 block text-[10px] text-muted-foreground">{label}</span>
      <strong className="block break-words text-[13px] font-black">{value}</strong>
    </div>
  )
}

// ─── EntryBox ─────────────────────────────────────────────────────────────

export function EntryBox({
  label,
  value,
  tone,
}: {
  label: string
  value: unknown
  tone?: 'good'
}) {
  return (
    <div className="rounded-md border border-white/[0.04] bg-white/[0.018] px-2 py-1.5">
      <div className="text-[9px] uppercase text-muted-foreground">{label}</div>
      <strong className={cn('block text-[13px] font-black leading-tight', tone === 'good' && 'text-emerald-300')}>
        {asString(value)}
      </strong>
    </div>
  )
}

// ─── Metric (simple) ──────────────────────────────────────────────────────

export function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-border bg-card p-2">
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="text-sm font-black">{asString(value)}</div>
    </div>
  )
}

// ─── MlAnalyticsTile ──────────────────────────────────────────────────────

export function MlAnalyticsTile({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'good' | 'warn' | 'info'
}) {
  const color =
    tone === 'good'
      ? 'text-emerald-300'
      : tone === 'warn'
        ? 'text-amber-300'
        : tone === 'info'
          ? 'text-blue-300'
          : 'text-foreground'
  return (
    <div className="rounded-md border border-border bg-white/[0.03] p-2.5">
      <span className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">{label}</span>
      <span className={cn('text-[13px] font-black', color)}>{value}</span>
    </div>
  )
}

// ─── EmptyAnalytics ───────────────────────────────────────────────────────

export function EmptyAnalytics({ text }: { text: string }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center rounded-md bg-background text-sm text-muted-foreground">
      {text}
    </div>
  )
}
