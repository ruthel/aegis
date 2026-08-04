/**
 * views/TradesView.tsx — Vue Trades & Ordres du dashboard Aegis
 */

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CircleDollarSign,
  Filter,
  Search,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useIntl } from 'react-intl'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/store/dashboard-store'
import {
  asString,
  formatCryptoAmount,
  formatLivePrice,
  formatTradePnl,
  formatTradeTime,
  formatUsdValue,
} from '@/lib/formatters'
import type { JsonMap } from '@/types/dashboard'

type SortOrder = 'asc' | 'desc'
type FilterDefinition = {
  field: string
  label: string
  placeholder?: string
  select?: Array<{ value: string; label: string }>
}

export function TradesView() {
  const [activeTab, setActiveTab] = useState<'trades' | 'buys' | 'sells'>('trades')
  const [symbol, setSymbol] = useState('')
  const intl = useIntl()
  const tradesPayload = useDashboardStore((state) => state.trades)
  const refreshTrades = useDashboardStore((state) => state.refreshTrades)
  const trades = tradesPayload.trades || []
  const buys = tradesPayload.buys || []
  const sells = tradesPayload.sells || []

  const [currentPage, setCurrentPage] = useState<number>(1)
  const [pageSize, setPageSize] = useState<number>(10)
  const [sortField, setSortField] = useState<string>('date')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({
    date: '', symbol: '', status: '', buy_price: '', sell_price: '',
    price: '', amount: '', usd_value: '', ml_buy_prob: '', ml_sell_prob: '',
    pnl_gross: '', pnl: '',
  })

  useEffect(() => { setCurrentPage(1) }, [activeTab, symbol, columnFilters, sortField, sortOrder, pageSize])

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortOrder(
        ['date', 'buy_price', 'sell_price', 'price', 'amount', 'usd_value', 'ml_buy_prob', 'ml_sell_prob', 'pnl_gross', 'pnl'].includes(field)
          ? 'desc'
          : 'asc',
      )
    }
  }

  const handleFilterChange = (field: string, value: string) => {
    setColumnFilters((prev) => ({ ...prev, [field]: value }))
  }

  const clearAllFilters = () => {
    setColumnFilters({ date: '', symbol: '', status: '', buy_price: '', sell_price: '', price: '', amount: '', usd_value: '', ml_buy_prob: '', ml_sell_prob: '', pnl_gross: '', pnl: '' })
    setSymbol('')
  }

  const hasActiveFilters = symbol !== '' || Object.values(columnFilters).some((v) => v.trim() !== '')

  useEffect(() => {
    void refreshTrades()
  }, [refreshTrades])

  const processItems = (rawItems: JsonMap[], tab: 'trades' | 'buys' | 'sells') => {
    let result = [...rawItems]

    result = result.filter((item) => {
      if (symbol.trim()) {
        if (!asString(item.symbol).toLowerCase().includes(symbol.trim().toLowerCase())) return false
      }
      if (columnFilters.date) {
        const time = formatTradeTime(item.timestamp ?? item.buy_time ?? item.closed_at ?? item.sell_time, intl)
        if (!`${time.absolute} ${time.relative}`.toLowerCase().includes(columnFilters.date.toLowerCase())) return false
      }
      if (columnFilters.symbol) {
        if (!asString(item.symbol).toLowerCase().includes(columnFilters.symbol.toLowerCase())) return false
      }
      if (columnFilters.status) {
        let statusStr = ''
        if (tab === 'trades') statusStr = item.status === 'open' ? 'open' : 'closed'
        else if (tab === 'sells') statusStr = item.status === 'opened' ? 'open' : 'executed'
        else statusStr = asString(item.status || 'executed')
        if (!statusStr.toLowerCase().includes(columnFilters.status.toLowerCase())) return false
      }
      if (columnFilters.buy_price || columnFilters.price) {
        const query = (columnFilters.buy_price || columnFilters.price).toLowerCase()
        if (!String(item.buy_price ?? item.price ?? '').toLowerCase().includes(query)) return false
      }
      if (columnFilters.sell_price) {
        if (!String(item.sell_price ?? item.target_price ?? '').toLowerCase().includes(columnFilters.sell_price.toLowerCase())) return false
      }
      if (columnFilters.amount) {
        if (!String(item.amount ?? '').toLowerCase().includes(columnFilters.amount.toLowerCase())) return false
      }
      if (columnFilters.usd_value) {
        const usdVal = Number(item.usd_value ?? item.entry_value ?? (Number(item.buy_price ?? item.price ?? 0) * Number(item.amount ?? 0)))
        if (!usdVal.toFixed(2).includes(columnFilters.usd_value) && !formatUsdValue(usdVal).toLowerCase().includes(columnFilters.usd_value.toLowerCase())) return false
      }
      if (columnFilters.ml_buy_prob) {
        const valStr = item.ml_buy_prob != null ? `${Number(item.ml_buy_prob).toFixed(1)}%` : ''
        if (!valStr.toLowerCase().includes(columnFilters.ml_buy_prob.toLowerCase())) return false
      }
      if (columnFilters.ml_sell_prob) {
        const valStr = item.ml_sell_prob != null ? `${Number(item.ml_sell_prob).toFixed(1)}%` : ''
        if (!valStr.toLowerCase().includes(columnFilters.ml_sell_prob.toLowerCase())) return false
      }
      if (columnFilters.pnl_gross) {
        if (item.status === 'open') { if (!'en cours'.includes(columnFilters.pnl_gross) && !'open'.includes(columnFilters.pnl_gross)) return false }
        else if (!String(item.pnl_gross ?? '').toLowerCase().includes(columnFilters.pnl_gross.toLowerCase()) && !formatTradePnl(item.pnl_gross).toLowerCase().includes(columnFilters.pnl_gross.toLowerCase())) return false
      }
      if (columnFilters.pnl) {
        if (item.status === 'open') { if (!'en cours'.includes(columnFilters.pnl) && !'open'.includes(columnFilters.pnl)) return false }
        else if (!String(item.pnl ?? item.pnl_net ?? '').toLowerCase().includes(columnFilters.pnl.toLowerCase()) && !formatTradePnl(item.pnl ?? item.pnl_net).toLowerCase().includes(columnFilters.pnl.toLowerCase())) return false
      }
      return true
    })

    result.sort((a, b) => {
      let valA: any, valB: any
      switch (sortField) {
        case 'date': {
          const rA = a.timestamp ?? a.buy_time ?? a.closed_at ?? a.sell_time
          const rB = b.timestamp ?? b.buy_time ?? b.closed_at ?? b.sell_time
          valA = rA ? new Date(asString(rA)).getTime() : 0; valB = rB ? new Date(asString(rB)).getTime() : 0; break
        }
        case 'symbol': valA = asString(a.symbol); valB = asString(b.symbol); break
        case 'status': valA = asString(a.status); valB = asString(b.status); break
        case 'buy_price': case 'price': valA = Number(a.buy_price ?? a.price ?? 0); valB = Number(b.buy_price ?? b.price ?? 0); break
        case 'sell_price': valA = Number(a.sell_price ?? a.target_price ?? 0); valB = Number(b.sell_price ?? b.target_price ?? 0); break
        case 'amount': valA = Number(a.amount ?? 0); valB = Number(b.amount ?? 0); break
        case 'usd_value': valA = Number(a.usd_value ?? a.entry_value ?? (Number(a.buy_price ?? a.price ?? 0) * Number(a.amount ?? 0))); valB = Number(b.usd_value ?? b.entry_value ?? (Number(b.buy_price ?? b.price ?? 0) * Number(b.amount ?? 0))); break
        case 'ml_buy_prob': valA = a.ml_buy_prob != null ? Number(a.ml_buy_prob) : -1; valB = b.ml_buy_prob != null ? Number(b.ml_buy_prob) : -1; break
        case 'ml_sell_prob': valA = a.ml_sell_prob != null ? Number(a.ml_sell_prob) : -1; valB = b.ml_sell_prob != null ? Number(b.ml_sell_prob) : -1; break
        case 'pnl_gross': valA = a.status === 'open' ? -999999999 : Number(a.pnl_gross ?? 0); valB = b.status === 'open' ? -999999999 : Number(b.pnl_gross ?? 0); break
        case 'pnl': valA = a.status === 'open' ? -999999999 : Number(a.pnl ?? a.pnl_net ?? 0); valB = b.status === 'open' ? -999999999 : Number(b.pnl ?? b.pnl_net ?? 0); break
        default: valA = 0; valB = 0
      }
      if (valA < valB) return sortOrder === 'asc' ? -1 : 1
      if (valA > valB) return sortOrder === 'asc' ? 1 : -1
      return 0
    })
    return result
  }

  const filteredTrades = useMemo(() => processItems(trades, 'trades'), [trades, symbol, columnFilters, sortField, sortOrder, intl])
  const filteredBuys = useMemo(() => processItems(buys, 'buys'), [buys, symbol, columnFilters, sortField, sortOrder, intl])
  const filteredSells = useMemo(() => processItems(sells, 'sells'), [sells, symbol, columnFilters, sortField, sortOrder, intl])

  const activeItems = useMemo(() => {
    if (activeTab === 'trades') return filteredTrades
    if (activeTab === 'buys') return filteredBuys
    return filteredSells
  }, [activeTab, filteredTrades, filteredBuys, filteredSells])

  const totalCount = activeItems.length
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const startItem = totalCount === 0 ? 0 : (safePage - 1) * pageSize + 1
  const endItem = Math.min(totalCount, safePage * pageSize)

  const paginatedTrades = useMemo(() => {
    if (activeTab !== 'trades') return []
    const start = (safePage - 1) * pageSize
    return filteredTrades.slice(start, start + pageSize)
  }, [activeTab, filteredTrades, safePage, pageSize])

  const paginatedBuys = useMemo(() => {
    if (activeTab !== 'buys') return []
    const start = (safePage - 1) * pageSize
    return filteredBuys.slice(start, start + pageSize)
  }, [activeTab, filteredBuys, safePage, pageSize])

  const paginatedSells = useMemo(() => {
    if (activeTab !== 'sells') return []
    const start = (safePage - 1) * pageSize
    return filteredSells.slice(start, start + pageSize)
  }, [activeTab, filteredSells, safePage, pageSize])

  const renderFilterInput = (field: string, placeholder: string) => {
    const val = columnFilters[field] || ''
    return (
      <div className="relative flex items-center">
        <Input value={val} onChange={(e) => handleFilterChange(field, e.target.value)} placeholder={placeholder} className="h-7 w-full rounded border border-border/60 bg-background/90 px-2 pr-6 text-xs text-foreground placeholder:text-muted-foreground/60 transition-colors focus:border-primary focus:ring-1 focus:ring-primary/20" />
        {val && (
          <button onClick={() => handleFilterChange(field, '')} className="absolute right-1.5 text-muted-foreground hover:text-foreground transition-colors p-0.5 rounded" title="Effacer">
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
    )
  }

  const renderFilterSelect = (field: string, options: Array<{ value: string; label: string }>) => (
    <Select value={columnFilters[field] || '__all__'} onValueChange={(value) => handleFilterChange(field, value === '__all__' ? '' : value)}>
      <SelectTrigger className="h-8 w-full min-w-0 bg-background/90" aria-label={`Filtre ${field}`}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectItem value="__all__">Tous</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  const filterDefinitions: FilterDefinition[] = activeTab === 'trades'
    ? [
        { field: 'date', label: 'Date', placeholder: 'Filtrer date...' },
        { field: 'symbol', label: 'Symbole', select: [{ value: 'BTC', label: 'BTC/USD' }, { value: 'ETH', label: 'ETH/USD' }, { value: 'SOL', label: 'SOL/USD' }, { value: 'ADA', label: 'ADA/USD' }] },
        { field: 'status', label: 'Statut', select: [{ value: 'open', label: 'OPEN' }, { value: 'closed', label: 'CLOSED' }] },
        { field: 'buy_price', label: 'Prix entrée', placeholder: 'Filtrer prix...' },
        { field: 'sell_price', label: 'Prix vente', placeholder: 'Filtrer prix...' },
        { field: 'amount', label: 'Montant', placeholder: 'Filtrer montant...' },
        { field: 'usd_value', label: 'Valeur USD', placeholder: 'Filtrer USD...' },
        { field: 'ml_buy_prob', label: 'ML % achat', placeholder: 'ML % Achat...' },
        { field: 'ml_sell_prob', label: 'ML % vente', placeholder: 'ML % Vente...' },
        { field: 'pnl_gross', label: 'PnL brut', placeholder: 'Filtrer PnL...' },
        { field: 'pnl', label: 'PnL net', placeholder: 'Filtrer PnL...' },
      ]
    : [
        { field: 'date', label: 'Date', placeholder: 'Filtrer date...' },
        { field: 'symbol', label: 'Symbole', select: [{ value: 'BTC', label: 'BTC/USD' }, { value: 'ETH', label: 'ETH/USD' }, { value: 'SOL', label: 'SOL/USD' }, { value: 'ADA', label: 'ADA/USD' }] },
        { field: 'price', label: activeTab === 'buys' ? 'Prix achat' : 'Prix vente', placeholder: 'Filtrer prix...' },
        { field: 'amount', label: 'Montant', placeholder: 'Filtrer montant...' },
        { field: 'usd_value', label: 'Valeur USD', placeholder: 'Filtrer USD...' },
        activeTab === 'sells'
          ? { field: 'status', label: 'Statut', select: [{ value: 'opened', label: 'OPEN' }, { value: 'executed', label: 'EXECUTED' }] }
          : { field: 'status', label: 'Statut', placeholder: 'Filtrer statut...' },
      ]

  const renderColumnFilterButton = (field: string) => {
    const item = filterDefinitions.find((filter) => filter.field === field)
    if (!item) return null

    const active = Boolean((columnFilters[field] || '').trim())
    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'ml-0.5 h-6 w-6 shrink-0 rounded border border-transparent p-0 hover:border-border hover:bg-background/80',
              active && 'border-primary/40 bg-primary/10 text-primary',
            )}
            title={`Filtrer ${item.label}`}
            aria-label={`Filtrer ${item.label}`}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <Filter className="h-3.5 w-3.5" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-72 p-0"
          align="start"
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <div className="border-b border-border px-3 py-2">
            <div className="text-xs font-black uppercase text-foreground">{item.label}</div>
            <div className="text-[11px] text-muted-foreground">Filtre de colonne</div>
          </div>
          <div className="space-y-2 p-3">
            {item.select ? (
              renderFilterSelect(item.field, item.select)
            ) : (
              renderFilterInput(item.field, item.placeholder || 'Filtrer...')
            )}
            {active && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleFilterChange(item.field, '')}
                className="h-7 w-full justify-start px-2 text-xs text-rose-300 hover:bg-rose-500/10 hover:text-rose-200"
              >
                <X className="h-3.5 w-3.5" /> Effacer ce filtre
              </Button>
            )}
          </div>
        </PopoverContent>
      </Popover>
    )
  }

  const renderSortableTh = (label: string, field: string, className = '') => {
    const isSorted = sortField === field
    return (
      <th
        key={field}
        onClick={() => handleSort(field)}
        className={cn('cursor-pointer select-none py-2.5 px-3 font-semibold hover:text-foreground hover:bg-secondary/60 rounded-t', isSorted ? 'text-primary font-bold bg-secondary/40' : '', className)}
      >
        <div className="flex items-center gap-1.5">
          <span className="whitespace-nowrap">{label}</span>
          {isSorted ? (sortOrder === 'asc' ? <ArrowUp className="h-3.5 w-3.5 text-primary shrink-0" /> : <ArrowDown className="h-3.5 w-3.5 text-primary shrink-0" />) : <ArrowUpDown className="h-3 w-3 opacity-30 shrink-0" />}
          {renderColumnFilterButton(field)}
        </div>
      </th>
    )
  }

  const rowKey = (item: JsonMap, index: number, scope: string) => {
    const stableId = item.order_id ?? item.id ?? item.entry_id ?? item.event_id ?? item.timestamp ?? item.buy_time ?? item.sell_time ?? item.closed_at ?? index
    return `${scope}-${asString(item.symbol)}-${asString(item.side ?? item.status ?? '')}-${asString(stableId)}`
  }

  return (
    <Card className="border-border/60 shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-lg font-bold flex items-center gap-2">
              <CircleDollarSign className="h-5 w-5 text-primary" /> Trades & Ordres
            </CardTitle>
            <div className="flex rounded-lg border border-border/80 bg-secondary/40 p-1 text-xs">
              <button onClick={() => setActiveTab('trades')} className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'trades' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>📊 Trades & PnL ({filteredTrades.length})</button>
              <button onClick={() => setActiveTab('buys')} className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'buys' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>🛒 Achats ({filteredBuys.length})</button>
              <button onClick={() => setActiveTab('sells')} className={cn('rounded px-3 py-1 font-semibold transition-all', activeTab === 'sells' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>🏷️ Ventes ({filteredSells.length})</button>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearAllFilters} className="h-8 gap-1 px-2 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 transition-colors">
                <X className="h-3.5 w-3.5" /> Réinitialiser filtres
              </Button>
            )}
            <div className="relative flex items-center">
              <Search className="absolute left-2.5 h-3.5 w-3.5 text-muted-foreground/60 pointer-events-none" />
              <Input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="Rechercher symbole..." className="max-w-56 h-8 pl-8 pr-6 text-xs border-border/60 bg-background/80 focus:border-primary" />
              {symbol && <button onClick={() => setSymbol('')} className="absolute right-2 text-muted-foreground hover:text-foreground p-0.5" title="Effacer"><X className="h-3 w-3" /></button>}
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="overflow-auto rounded-lg border border-border/60 bg-background/50">
          {activeTab === 'trades' && (
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  {renderSortableTh('Date', 'date', 'min-w-[170px] whitespace-nowrap')}
                  {renderSortableTh('Symbole', 'symbol')}
                  {renderSortableTh('Statut', 'status')}
                  {renderSortableTh('Prix Entrée', 'buy_price')}
                  {renderSortableTh('Prix Vente', 'sell_price')}
                  {renderSortableTh('Montant', 'amount')}
                  {renderSortableTh('Valeur USD', 'usd_value')}
                  {renderSortableTh('ML % Achat', 'ml_buy_prob')}
                  {renderSortableTh('ML % Vente', 'ml_sell_prob')}
                  {renderSortableTh('PnL Brut', 'pnl_gross')}
                  {renderSortableTh('PnL Net', 'pnl')}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedTrades.length === 0 ? (
                  <tr><td colSpan={11} className="py-8 text-center text-muted-foreground font-medium">Aucun trade trouvé</td></tr>
                ) : (
                  paginatedTrades.map((trade, index) => {
                    const tradeSymbol = asString(trade.symbol)
                    const time = formatTradeTime(trade.timestamp ?? trade.buy_time ?? trade.closed_at ?? trade.sell_time, intl)
                    const usdVal = Number(trade.usd_value ?? trade.entry_value ?? (Number(trade.buy_price ?? trade.price ?? 0) * Number(trade.amount ?? 0)))
                    const pnlGross = trade.pnl_gross
                    const pnlNet = trade.pnl ?? trade.pnl_net
                    return (
                      <tr key={rowKey(trade, index, 'trade')} className="hover:bg-secondary/30">
                        <td className="min-w-[170px] whitespace-nowrap py-2.5 px-3"><span className="block whitespace-nowrap font-semibold text-foreground">{time.absolute}</span><span className="block whitespace-nowrap text-[11px] text-muted-foreground/80">{time.relative}</span></td>
                        <td className="px-3 font-semibold text-foreground">{tradeSymbol}</td>
                        <td className="px-3"><span className={cn('rounded-full border px-2.5 py-0.5 text-[11px] font-black uppercase tracking-wide', trade.status === 'open' ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300 shadow-sm' : 'border-border/80 bg-secondary/80 text-muted-foreground')}>{trade.status === 'open' ? 'OPEN' : 'CLOSED'}</span></td>
                        <td className="px-3 font-mono">{formatLivePrice(tradeSymbol, trade.buy_price ?? trade.price)}</td>
                        <td className="px-3 font-mono">{trade.sell_price ? formatLivePrice(tradeSymbol, trade.sell_price) : <span className="text-muted-foreground/60">--</span>}</td>
                        <td className="px-3 font-mono text-foreground"><div>{formatCryptoAmount(trade.amount)}</div><div className="text-[11px] text-muted-foreground/75 font-sans font-medium">{formatUsdValue(usdVal)}</div></td>
                        <td className="px-3 font-mono text-foreground font-semibold"><div>{formatUsdValue(usdVal)}</div>{Boolean(trade.sizing_reason) && <div className="text-[10px] text-amber-300/90 font-sans font-normal truncate max-w-[150px]" title={String(trade.sizing_reason)}>{String(trade.sizing_reason)}</div>}</td>
                        <td className="px-3 font-mono text-xs">
                          {trade.ml_buy_prob != null ? (
                            <span className={cn('rounded border px-2 py-0.5 font-bold font-mono text-xs inline-block', Number(trade.ml_buy_prob) >= 65 ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300' : Number(trade.ml_buy_prob) >= 50 ? 'border-amber-500/40 bg-amber-500/15 text-amber-300' : 'border-rose-500/40 bg-rose-500/15 text-rose-300')}>{Number(trade.ml_buy_prob).toFixed(1)}%</span>
                          ) : <span className="text-muted-foreground/40 font-mono text-xs">--</span>}
                        </td>
                        <td className="px-3 font-mono text-xs">
                          {trade.ml_sell_prob != null ? (
                            <span className={cn('rounded border px-2 py-0.5 font-bold font-mono text-xs inline-block', Number(trade.ml_sell_prob) >= 50 ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300' : 'border-indigo-500/40 bg-indigo-500/15 text-indigo-300')}>{Number(trade.ml_sell_prob).toFixed(1)}%</span>
                          ) : <span className="text-muted-foreground/40 font-mono text-xs">--</span>}
                        </td>
                        <td className="px-3 font-medium font-mono">{trade.status === 'open' ? <span className="text-emerald-400/90 font-semibold italic">En cours</span> : <span className={cn(Number(pnlGross ?? 0) > 0 ? 'text-emerald-400 font-semibold' : Number(pnlGross ?? 0) < 0 ? 'text-rose-400 font-semibold' : 'text-muted-foreground')}>{formatTradePnl(pnlGross)}</span>}</td>
                        <td className="px-3 font-medium font-mono">{trade.status === 'open' ? <span className="text-emerald-400/90 font-semibold italic">En cours</span> : <span className={cn(Number(pnlNet ?? 0) > 0 ? 'text-emerald-400 font-semibold' : Number(pnlNet ?? 0) < 0 ? 'text-rose-400 font-semibold' : 'text-muted-foreground')}>{formatTradePnl(pnlNet)}</span>}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}

          {activeTab === 'buys' && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  {renderSortableTh('Date', 'date', 'min-w-[170px] whitespace-nowrap')}{renderSortableTh('Symbole', 'symbol')}{renderSortableTh('Side', 'side')}
                  {renderSortableTh('Prix Achat', 'price')}{renderSortableTh('Montant', 'amount')}{renderSortableTh('Valeur USD', 'usd_value')}{renderSortableTh('Statut', 'status')}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedBuys.length === 0 ? (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground font-medium">Aucun achat trouvé</td></tr>
                ) : (
                  paginatedBuys.map((buy, index) => {
                    const itemSymbol = asString(buy.symbol)
                    const time = formatTradeTime(buy.timestamp, intl)
                    const px = Number(buy.price || 0)
                    const amt = Number(buy.amount || 0)
                    return (
                      <tr key={rowKey(buy, index, 'buy')} className="hover:bg-secondary/30">
                        <td className="min-w-[170px] whitespace-nowrap py-2.5 px-3"><span className="block whitespace-nowrap font-semibold text-foreground">{time.absolute}</span><span className="block whitespace-nowrap text-[11px] text-muted-foreground/80">{time.relative}</span></td>
                        <td className="px-3 font-semibold text-foreground">{itemSymbol}</td>
                        <td className="px-3"><span className="rounded-full border border-emerald-500/50 bg-emerald-500/15 px-2.5 py-0.5 text-[11px] font-black uppercase text-emerald-300">BUY</span></td>
                        <td className="px-3 font-mono">{formatLivePrice(itemSymbol, px)}</td>
                        <td className="px-3 font-mono text-foreground">{formatCryptoAmount(amt)}</td>
                        <td className="px-3 font-semibold">${(px * amt).toFixed(2)} USD</td>
                        <td className="px-3"><span className="rounded-full border border-border/80 bg-secondary/80 px-2.5 py-0.5 text-[11px] font-semibold text-foreground uppercase">{asString(buy.status || 'executed').toUpperCase()}</span></td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}

          {activeTab === 'sells' && (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground bg-secondary/30">
                <tr>
                  {renderSortableTh('Date', 'date', 'min-w-[170px] whitespace-nowrap')}{renderSortableTh('Symbole', 'symbol')}{renderSortableTh('Side', 'side')}
                  {renderSortableTh('Prix Vente Target', 'price')}{renderSortableTh('Montant', 'amount')}{renderSortableTh('Valeur USD', 'usd_value')}{renderSortableTh('Statut', 'status')}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {paginatedSells.length === 0 ? (
                  <tr><td colSpan={7} className="py-8 text-center text-muted-foreground font-medium">Aucune vente trouvée</td></tr>
                ) : (
                  paginatedSells.map((sell, index) => {
                    const itemSymbol = asString(sell.symbol)
                    const time = formatTradeTime(sell.timestamp, intl)
                    const px = Number(sell.price || 0)
                    const amt = Number(sell.amount || 0)
                    const isOpened = sell.status === 'opened'
                    return (
                      <tr key={rowKey(sell, index, 'sell')} className="hover:bg-secondary/30">
                        <td className="min-w-[170px] whitespace-nowrap py-2.5 px-3"><span className="block whitespace-nowrap font-semibold text-foreground">{time.absolute}</span><span className="block whitespace-nowrap text-[11px] text-muted-foreground/80">{time.relative}</span></td>
                        <td className="px-3 font-semibold text-foreground">{itemSymbol}</td>
                        <td className="px-3"><span className="rounded-full border border-rose-500/50 bg-rose-500/15 px-2.5 py-0.5 text-[11px] font-black uppercase text-rose-300">SELL</span></td>
                        <td className="px-3 font-mono">{formatLivePrice(itemSymbol, px)}</td>
                        <td className="px-3 font-mono text-foreground">{formatCryptoAmount(amt)}</td>
                        <td className="px-3 font-semibold">${(px * amt).toFixed(2)} USD</td>
                        <td className="px-3"><span className={cn('rounded-full border px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide', isOpened ? 'border-amber-500/50 bg-amber-500/15 text-amber-300' : 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300')}>{isOpened ? 'OPEN (EN ATTENTE)' : 'EXECUTED (VENDU)'}</span></td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-muted-foreground font-medium">
              Affichage de <span className="font-bold text-foreground">{startItem}</span> à <span className="font-bold text-foreground">{endItem}</span> sur <span className="font-bold text-foreground">{totalCount}</span> éléments
            </span>
            <div className="flex items-center gap-1.5 border-l border-border/60 pl-3">
              <span className="text-muted-foreground">Par page :</span>
              <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setCurrentPage(1) }} className="h-7 rounded border border-border/80 bg-background/90 px-2 text-xs text-foreground font-bold transition-colors focus:border-primary outline-none">
                <option value={5}>5</option><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage(1)} className="h-7 w-7 p-0 hover:bg-secondary border-border/80" title="Première page"><ChevronsLeft className="h-3.5 w-3.5" /></Button>
            <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} className="h-7 w-7 p-0 hover:bg-secondary border-border/80" title="Page précédente"><ChevronLeft className="h-3.5 w-3.5" /></Button>
            <div className="flex items-center gap-1 px-1">
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - safePage) <= 1)
                .reduce<(number | string)[]>((acc, p, idx, arr) => {
                  if (idx > 0 && typeof arr[idx - 1] === 'number' && (p as number) - (arr[idx - 1] as number) > 1) acc.push('...')
                  acc.push(p); return acc
                }, [])
                .map((item, idx) =>
                  typeof item === 'number' ? (
                    <Button key={`page-${item}`} variant={item === safePage ? 'default' : 'outline'} size="sm" onClick={() => setCurrentPage(item)} className={cn('h-7 w-7 p-0 text-xs font-bold transition-all border-border/80', item === safePage ? 'bg-primary text-primary-foreground shadow-sm' : 'hover:bg-secondary')}>{item}</Button>
                  ) : (
                    <span key={`ellipsis-${idx}`} className="px-1 text-muted-foreground text-xs select-none">...</span>
                  ),
                )}
            </div>
            <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))} className="h-7 w-7 p-0 hover:bg-secondary border-border/80" title="Page suivante"><ChevronRight className="h-3.5 w-3.5" /></Button>
            <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage(totalPages)} className="h-7 w-7 p-0 hover:bg-secondary border-border/80" title="Dernière page"><ChevronsRight className="h-3.5 w-3.5" /></Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
