/**
 * formatters.ts — Fonctions utilitaires partagées de formatage
 * Extraites de App.tsx pour être réutilisables dans toutes les vues.
 */

import type { IntlShape } from 'react-intl'
import type { JsonMap } from '@/types/dashboard'

// ─── Formatage numérique basique ───────────────────────────────────────────

export function num(value: unknown, digits = 2): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--'
}

export function pct(value: unknown, digits = 1): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : '--'
}

export function asString(value: unknown, fallback = '--'): string {
  return value === null || value === undefined || value === '' ? fallback : String(value)
}

// ─── Formatage prix/volumes live ───────────────────────────────────────────

export function formatLivePrice(symbol: string, value: unknown): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const digits = symbol.startsWith('ADA') || parsed < 1 ? 4 : parsed < 100 ? 3 : 2
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed)
}

export function formatLiveVolumeUsd(value: unknown, price: unknown): string {
  const parsed = Number(value)
  const parsedPrice = Number(price)
  if (!Number.isFinite(parsed) || !Number.isFinite(parsedPrice) || parsedPrice <= 0) return '--'
  const usdValue = parsed * parsedPrice
  return new Intl.NumberFormat('fr-FR', {
    notation: Math.abs(usdValue) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: Math.abs(usdValue) >= 1000 ? 1 : 2,
  }).format(usdValue)
}

export function formatLivePercent(value: unknown, digits = 4, signed = false): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const normalized = Math.abs(parsed) < 0.005 && digits === 2 ? 0 : parsed
  const sign = signed && normalized > 0 ? '+' : ''
  const formatted = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(normalized)
  return `${sign}${formatted}%`
}

export function formatSignedPct(value: unknown, digits = 2): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const sign = parsed > 0 ? '+' : ''
  return `${sign}${pct(parsed, digits)}`
}

// ─── Formatage dates et temps ──────────────────────────────────────────────

export function formatDateWithRelative(value: unknown): string {
  const raw = asString(value, '')
  if (!raw) return '--'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  const diffSeconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000))
  const relative =
    diffSeconds < 60
      ? `${diffSeconds}s`
      : diffSeconds < 3600
        ? `${Math.floor(diffSeconds / 60)}min`
        : `${Math.floor(diffSeconds / 3600)}h ${Math.floor((diffSeconds % 3600) / 60)}min`
  return `Aujourd'hui · ${parsed.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} · il y a ${relative}`
}

export function formatDecisionTime(
  value: unknown,
  intl: IntlShape,
): { absolute: string; relative: string } {
  const raw = asString(value, '')
  if (!raw) return { absolute: 'Date inconnue', relative: '--' }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return { absolute: raw, relative: '--' }

  const absolute = intl.formatDate(parsed, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSeconds)
  const unit = abs < 60 ? 'second' : abs < 3600 ? 'minute' : abs < 86400 ? 'hour' : 'day'
  const divisor =
    unit === 'second' ? 1 : unit === 'minute' ? 60 : unit === 'hour' ? 3600 : 86400
  const relative = intl.formatRelativeTime(Math.round(diffSeconds / divisor), unit, {
    numeric: 'auto',
  })
  return { absolute, relative }
}

export function formatTradeTime(
  value: unknown,
  intl: IntlShape,
): { absolute: string; relative: string } {
  const raw = asString(value, '')
  if (!raw) return { absolute: 'Date inconnue', relative: '--' }
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return { absolute: raw, relative: '--' }

  const now = new Date()
  const sameDay = parsed.toDateString() === now.toDateString()
  const time = intl.formatTime(parsed, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const date = sameDay
    ? "Aujourd'hui"
    : intl.formatDate(parsed, {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      })

  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000)
  const abs = Math.abs(diffSeconds)
  const unit = abs < 60 ? 'second' : abs < 3600 ? 'minute' : abs < 86400 ? 'hour' : 'day'
  const divisor =
    unit === 'second' ? 1 : unit === 'minute' ? 60 : unit === 'hour' ? 3600 : 86400
  const relative = intl.formatRelativeTime(Math.round(diffSeconds / divisor), unit, {
    numeric: 'auto',
  })

  return { absolute: `${date} · ${time}`, relative }
}

// ─── Formatage PnL History — axe X temporel ───────────────────────────────

/**
 * Formate un timestamp ISO en label lisible pour l'axe X du graphique PnL,
 * adapté selon la durée sélectionnée dans le dropdown.
 */
export function formatPnlDateLabel(
  rawTime: string,
  range: '24h' | '7d' | '30d' | '90d' | 'all',
): string {
  if (!rawTime || rawTime === 'start') return 'Début'
  const d = new Date(rawTime)
  if (isNaN(d.getTime())) return rawTime
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const month = String(d.getMonth() + 1).padStart(2, '0')
  if (range === '24h') return `${hh}:${mm}`
  if (range === '7d') return `${day}/${month} ${hh}h`
  return `${day}/${month}`
}

// ─── Formatage crypto/trade ────────────────────────────────────────────────

export function formatCryptoAmount(value: unknown): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: parsed < 0.01 ? 8 : 4,
    maximumFractionDigits: 8,
  }).format(parsed)
}

export function formatTradePnl(value: unknown): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const sign = parsed > 0 ? '+' : ''
  return `${sign}${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} USD`
}

export function formatUsdValue(value: unknown): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed === 0) return '--'
  return `${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} USD`
}

// ─── Régime marché ─────────────────────────────────────────────────────────

export function abbreviateRegime(value: unknown): string {
  const clean = asString(value).replaceAll('_', ' ')
  return clean
    .replace(/\bSIDEWAYS DOWN\b/g, 'SIDE. DO.')
    .replace(/\bSIDEWAYS UP\b/g, 'SIDE. UP')
    .replace(/\bSIDEWAYS\b/g, 'SIDE')
    .replace(/\bDOWN\b/g, 'DO.')
}

// ─── Parsing objets métriques ──────────────────────────────────────────────

export function parseMetricObject(value: unknown): JsonMap {
  if (!value) return {}
  if (typeof value === 'object') return value as JsonMap
  if (typeof value !== 'string') return {}
  try {
    return JSON.parse(value) as JsonMap
  } catch {
    try {
      return JSON.parse(
        value
          .replaceAll("'", '"')
          .replaceAll('True', 'true')
          .replaceAll('False', 'false')
          .replaceAll('None', 'null'),
      ) as JsonMap
    } catch {
      return {}
    }
  }
}

export function normalizeDecisionMetrics(metrics: unknown): JsonMap {
  const raw = parseMetricObject(metrics)
  return {
    ...raw,
    ml_decision: parseMetricObject(raw.ml_decision),
    ml_inputs: parseMetricObject(raw.ml_inputs),
    ml_exit_entry_forecast: parseMetricObject(raw.ml_exit_entry_forecast),
    market_context: parseMetricObject(raw.market_context),
  }
}

export function decisionReasonTitle(reason: unknown): string {
  const labels: Record<string, string> = {
    score_below_dynamic_threshold: 'Score marché insuffisant',
    technical_signal_below_threshold: 'Signal technique trop faible',
    technical_signal_not_buy: 'Signal technique sans achat',
    technical_signal_confidence_below_threshold: 'Confiance technique trop faible',
    technical_signal_not_buy_soft: 'Signal technique transmis au ML',
    technical_signal_confidence_below_threshold_soft: 'Confiance technique transmise au ML',
    support_touch_disabled_in_bear_mode: 'Support Touch désactivé en bear mode',
    insufficient_trades: 'Backtest insuffisant',
    total_pnl_below_threshold: 'Profit backtest trop faible',
    avg_pnl_below_threshold: 'Moyenne backtest trop faible',
    winrate_below_threshold: 'Win rate backtest trop faible',
    symbol_cooldown_active: 'Cooldown actif',
    htf_bias_rejected: 'Tendance haute période défavorable',
    outside_optimal_trading_time: 'Hors plage de trading',
    analysis_error: "Erreur d'analyse",
    order_failed: 'Ordre échoué',
    buy_executed: 'Achat exécuté',
  }
  const key = String(reason || '').split(':')[0]
  return labels[key] || key.replaceAll('_', ' ') || '--'
}

export function metricNumber(value: unknown, digits = 1): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--'
}

export function durationText(seconds: unknown): string {
  const total = Number(seconds) || 0
  const minutes = Math.floor(total / 60)
  const rest = Math.floor(total % 60)
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`
}

export function cooldownDurationText(seconds: unknown): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes > 0 && rest > 0) return `${minutes} min ${rest} s`
  if (minutes > 0) return `${minutes} min`
  return `${rest} s`
}

export function decisionExplanation(item: JsonMap): string {
  const reason = String(item.reason || '')
  const key = reason.split(':')[0]
  const metrics = normalizeDecisionMetrics(item.metrics)
  const mlDecision = metrics.ml_decision as JsonMap
  const mlInputs = metrics.ml_inputs as JsonMap

  if (key.startsWith('ml_filter_rejected') || key.startsWith('support_touch_ml_entry_rejected')) {
    return `ML refuse l'entrée: P_win ${metricNumber(mlDecision.p_win)}% < seuil ${metricNumber(mlDecision.min_p_win)}%. Signal ${asString(mlInputs.technical_action)} ${metricNumber(mlInputs.technical_confidence)}%, score ${metricNumber(mlInputs.crypto_score)}, support ${mlInputs.support_touch ? 'oui' : 'non'}.`
  }
  if (key.startsWith('ml_exit_entry_rejected') || key.startsWith('support_touch_ml_exit_rejected')) {
    return `ML refuse l'entrée car la sortie prévue est fragile: P_continue ${metricNumber(mlDecision.p_continue)}% < seuil ${metricNumber(mlDecision.min_p_continue)}%.`
  }
  if (key === 'symbol_cooldown_active') {
    return `Le bot attend avant de retrader cette paire. Temps restant: ${durationText(metrics.cooldown_remaining_seconds)}.`
  }
  if (key === 'technical_signal_below_threshold') {
    return `Le signal technique ne confirme pas assez l'achat. Confiance ${metricNumber(metrics.confidence)}% / seuil ${metricNumber(metrics.min_confidence)}%.`
  }
  if (item.allowed) {
    if (Object.keys(mlDecision).length) {
      return `Achat autorisé par le ML: P_win ${metricNumber(mlDecision.p_win)}% / seuil ${metricNumber(mlDecision.min_p_win)}%. Signal ${asString(mlInputs.technical_action)}, score ${metricNumber(mlInputs.crypto_score)}, support ${mlInputs.support_touch ? 'oui' : 'non'}.`
    }
    return 'Décision finale enregistrée par le bot.'
  }
  return decisionReasonTitle(reason)
}

export function decisionMetricChips(item: JsonMap): string[] {
  const metrics = normalizeDecisionMetrics(item.metrics)
  const mlDecision = metrics.ml_decision as JsonMap
  const mlInputs = metrics.ml_inputs as JsonMap
  const chips: string[] = []
  if (metrics.price !== undefined)
    chips.push(`Prix ${num(metrics.price, Number(metrics.price) > 100 ? 2 : 4)}`)
  if (metrics.score !== undefined || metrics.min_score !== undefined)
    chips.push(`Score ${metricNumber(metrics.score)} / ${metricNumber(metrics.min_score)}`)
  if (metrics.confidence !== undefined || metrics.min_confidence !== undefined)
    chips.push(
      `Confiance ${metricNumber(metrics.confidence)}% / ${metricNumber(metrics.min_confidence)}%`,
    )
  if (mlDecision.p_win !== undefined)
    chips.push(`P_win ${metricNumber(mlDecision.p_win)}% / ${metricNumber(mlDecision.min_p_win)}%`)
  if (mlDecision.p_continue !== undefined)
    chips.push(
      `P_continue ${metricNumber(mlDecision.p_continue)}% / ${metricNumber(mlDecision.min_p_continue)}%`,
    )
  if (mlInputs.technical_action) chips.push(`Signal ${asString(mlInputs.technical_action)}`)
  if (mlInputs.support_touch) chips.push('Support ML')
  if (metrics.reject_cooldown_seconds !== undefined)
    chips.push(`Cooldown ${durationText(metrics.reject_cooldown_seconds)}`)
  return chips
}

// ─── Helpers de mapping symboles ───────────────────────────────────────────

export function liveSymbolItem(
  symbols: Record<string, JsonMap>,
  symbol: string,
): JsonMap {
  const compact = symbol.replace('/', '')
  return (
    symbols[symbol] ||
    symbols[compact] ||
    symbols[compact.replace('USDT', 'USD')] ||
    {}
  )
}

export function supportBySymbolMap(support: JsonMap): Record<string, JsonMap> {
  const mapped: Record<string, JsonMap> = {}
  const pairsList = Array.isArray(support.pairs) ? (support.pairs as JsonMap[]) : []
  pairsList.forEach((item) => {
    const symbol = asString(item.symbol, '')
    if (!symbol) return
    mapped[symbol] = item
    mapped[symbol.replace('/', '')] = item
  })
  Object.entries(support).forEach(([key, value]) => {
    if (value && typeof value === 'object' && key !== 'pairs' && key !== 'settings') {
      mapped[key] = value as JsonMap
      mapped[key.replace('/', '')] = value as JsonMap
    }
  })
  return mapped
}
