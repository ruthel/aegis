import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronsLeft,
  ChevronLeft,
  ChevronRight,
  ChevronsRight,
  Filter,
  ReceiptText,
  Search,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useIntl } from 'react-intl'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { asString, formatTradeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/store/dashboard-store'

type SortOrder = 'asc' | 'desc'

const SOURCE_OPTIONS = [
  { value: 'kraken_ledger', label: 'Kraken ledger' },
  { value: 'paper_trade', label: 'Paper trade' },
  { value: 'state_accounting', label: 'State accounting' },
]

const TYPE_OPTIONS = [
  { value: 'trade', label: 'Trade' },
  { value: 'fee', label: 'Frais' },
  { value: 'deposit', label: 'Depot' },
  { value: 'withdrawal', label: 'Retrait' },
  { value: 'transfer', label: 'Transfert' },
  { value: 'adjustment', label: 'Ajustement' },
]

const ASSET_OPTIONS = ['USD', 'CAD', 'BTC', 'ETH', 'SOL', 'ADA'].map((asset) => ({ value: asset, label: asset }))

function formatAssetAmount(value: unknown, asset?: string | null): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '--'
  const sign = parsed > 0 ? '+' : ''
  const isFiat = asset === 'USD' || asset === 'CAD'
  const digits = isFiat ? 2 : Math.abs(parsed) < 0.01 ? 8 : 6
  return `${sign}${new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: isFiat ? 2 : 0,
    maximumFractionDigits: digits,
  }).format(parsed)} ${asset || ''}`.trim()
}

function parseMode(accountId?: string | null): string {
  const raw = asString(accountId, '')
  const mode = raw.split(':')[0]
  return mode || '--'
}

function cleanDescription(value?: string | null): string {
  const raw = asString(value, '')
  if (!raw) return '--'
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>
    if (parsed && typeof parsed === 'object') {
      const parts: string[] = []
      
      // Type d'opération
      const exchangeType = asString(parsed.exchange_type || parsed.type, '')
      if (exchangeType) {
        const typeLabels: Record<string, string> = {
          trade: 'Trade',
          deposit: 'Dépôt',
          withdrawal: 'Retrait',
          fee: 'Frais',
          transfer: 'Transfert',
        }
        parts.push(typeLabels[exchangeType.toLowerCase()] || exchangeType)
      }
      
      // Direction (in/out)
      const direction = asString(parsed.direction, '')
      if (direction) {
        parts.push(direction === 'in' ? '↓ Entrée' : direction === 'out' ? '↑ Sortie' : direction)
      }
      
      // Référence courte
      const refId = asString(parsed.reference_id || parsed.refid || parsed.ref, '')
      if (refId) {
        const shortRef = refId.length > 12 ? `${refId.slice(0, 6)}...${refId.slice(-4)}` : refId
        parts.push(`Ref: ${shortRef}`)
      }
      
      return parts.length > 0 ? parts.join(' · ') : '--'
    }
  } catch {
    // Description texte normale
  }
  return raw.replaceAll('_', ' ')
}

function typeVariant(type?: string | null): 'success' | 'warning' | 'danger' | 'secondary' {
  const normalized = asString(type, '').toLowerCase()
  if (normalized === 'deposit') return 'success'
  if (normalized === 'withdrawal' || normalized === 'fee') return 'danger'
  if (normalized === 'trade') return 'warning'
  return 'secondary'
}

export function LedgerView() {
  const intl = useIntl()
  const ledgerPayload = useDashboardStore((state) => state.ledger)
  const refreshLedger = useDashboardStore((state) => state.refreshLedger)
  const entries = ledgerPayload.entries || []

  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [entryType, setEntryType] = useState('')
  const [asset, setAsset] = useState('')
  const [pageSize, setPageSize] = useState(25)
  const [currentPage, setCurrentPage] = useState(1)
  const [sortField, setSortField] = useState<'entry_ts' | 'asset' | 'amount' | 'balance_after' | 'entry_type' | 'source'>('entry_ts')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  useEffect(() => {
    void refreshLedger()
  }, [refreshLedger])

  useEffect(() => {
    setCurrentPage(1)
  }, [query, source, entryType, asset, pageSize, sortField, sortOrder])

  const hasFilters = Boolean(query.trim() || source || entryType || asset)

  const filteredEntries = useMemo(() => {
    const q = query.trim().toLowerCase()
    const result = entries.filter((entry) => {
      if (source && asString(entry.source).toLowerCase() !== source.toLowerCase()) return false
      if (entryType && asString(entry.entry_type).toLowerCase() !== entryType.toLowerCase()) return false
      if (asset && asString(entry.asset).toUpperCase() !== asset.toUpperCase()) return false
      if (!q) return true
      const haystack = [
        entry.ledger_id,
        entry.account_id,
        entry.entry_type,
        entry.asset,
        entry.symbol,
        entry.source,
        entry.description,
        entry.order_id,
        entry.fill_id,
      ].map((item) => asString(item, '').toLowerCase()).join(' ')
      return haystack.includes(q)
    })

    result.sort((a, b) => {
      let valA: string | number = 0
      let valB: string | number = 0
      if (sortField === 'entry_ts') {
        valA = a.entry_ts ? new Date(a.entry_ts).getTime() : 0
        valB = b.entry_ts ? new Date(b.entry_ts).getTime() : 0
      } else if (sortField === 'amount' || sortField === 'balance_after') {
        valA = Number(a[sortField] ?? 0)
        valB = Number(b[sortField] ?? 0)
      } else {
        valA = asString(a[sortField], '')
        valB = asString(b[sortField], '')
      }
      if (valA < valB) return sortOrder === 'asc' ? -1 : 1
      if (valA > valB) return sortOrder === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [asset, entries, entryType, query, sortField, sortOrder, source])

  const totalCount = filteredEntries.length
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const startItem = totalCount === 0 ? 0 : (safePage - 1) * pageSize + 1
  const endItem = Math.min(totalCount, safePage * pageSize)
  const paginatedEntries = filteredEntries.slice((safePage - 1) * pageSize, safePage * pageSize)

  const handleSort = (field: typeof sortField) => {
    if (field === sortField) {
      setSortOrder((current) => (current === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortOrder(field === 'entry_ts' || field === 'amount' || field === 'balance_after' ? 'desc' : 'asc')
    }
  }

  const clearFilters = () => {
    setQuery('')
    setSource('')
    setEntryType('')
    setAsset('')
  }

  const renderSortIcon = (field: typeof sortField) => {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 opacity-30" />
    return sortOrder === 'asc' ? <ArrowUp className="h-3.5 w-3.5 text-primary" /> : <ArrowDown className="h-3.5 w-3.5 text-primary" />
  }

  const th = (label: string, field: typeof sortField, className = '') => (
    <th
      className={cn('cursor-pointer select-none px-3 py-2.5 text-left font-semibold hover:bg-secondary/50 hover:text-foreground', sortField === field && 'bg-secondary/40 text-primary', className)}
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center gap-1.5 whitespace-nowrap">
        {label}
        {renderSortIcon(field)}
      </div>
    </th>
  )

  return (
    <Card className="border-border/60 shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-lg font-bold">
              <ReceiptText className="h-5 w-5 text-primary" /> Ledger entries
            </CardTitle>
            <Badge variant="secondary" className="normal-case">{ledgerPayload.view_mode || '--'}</Badge>
            <span className="text-[13px] text-muted-foreground">{filteredEntries.length} / {ledgerPayload.total ?? entries.length} lignes</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {hasFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="h-8 gap-1 px-2 text-xs text-rose-300 hover:bg-rose-500/10 hover:text-rose-200">
                <X className="h-3.5 w-3.5" /> Effacer
              </Button>
            )}
            <Popover>
              <PopoverTrigger asChild>
                <Button variant={hasFilters ? 'default' : 'outline'} size="sm" className="h-8 gap-2">
                  <Filter className="h-3.5 w-3.5" /> Filtres
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-[360px]" align="end">
                <div className="mb-3">
                  <div className="text-xs font-black uppercase text-foreground">Filtres ledger</div>
                  <div className="text-[11px] text-muted-foreground">Recherche dans les mouvements importés et comptables.</div>
                </div>
                <div className="grid gap-3">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground/70" />
                    <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Rechercher ref, symbole, description..." className="pl-8" />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <Select value={source || '__all__'} onValueChange={(value) => setSource(value === '__all__' ? '' : value)}>
                      <SelectTrigger className="w-full min-w-0"><SelectValue placeholder="Source" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__all__">Toutes sources</SelectItem>
                        {SOURCE_OPTIONS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={entryType || '__all__'} onValueChange={(value) => setEntryType(value === '__all__' ? '' : value)}>
                      <SelectTrigger className="w-full min-w-0"><SelectValue placeholder="Type" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__all__">Tous types</SelectItem>
                        {TYPE_OPTIONS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={asset || '__all__'} onValueChange={(value) => setAsset(value === '__all__' ? '' : value)}>
                      <SelectTrigger className="w-full min-w-0"><SelectValue placeholder="Actif" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__all__">Tous actifs</SelectItem>
                        {ASSET_OPTIONS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="overflow-auto rounded-lg border border-border/60 bg-background/50">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="bg-secondary/30 text-xs uppercase text-muted-foreground">
              <tr>
                {th('Date', 'entry_ts', 'min-w-[180px]')}
                <th className="px-3 py-2.5 font-semibold">Mode</th>
                {th('Type', 'entry_type')}
                {th('Actif', 'asset')}
                {th('Montant', 'amount')}
                {th('Solde apres', 'balance_after')}
                {th('Source', 'source')}
                <th className="px-3 py-2.5 font-semibold">Reference</th>
                <th className="px-3 py-2.5 font-semibold">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {paginatedEntries.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center font-medium text-muted-foreground">Aucune ligne ledger trouvee</td>
                </tr>
              ) : (
                paginatedEntries.map((entry, index) => {
                  const time = formatTradeTime(entry.entry_ts ?? entry.created_at, intl)
                  const amount = Number(entry.amount)
                  const reference = asString(entry.order_id || entry.fill_id || entry.ledger_id)
                  return (
                    <tr key={entry.ledger_id || `${entry.entry_ts}-${index}`} className="hover:bg-secondary/30">
                      <td className="min-w-[180px] whitespace-nowrap px-3 py-2.5">
                        <span className="block whitespace-nowrap font-semibold text-foreground">{time.absolute}</span>
                        <span className="block whitespace-nowrap text-[11px] text-muted-foreground/80">{time.relative}</span>
                      </td>
                      <td className="px-3">
                        <Badge variant={parseMode(entry.account_id) === 'live' ? 'success' : 'secondary'}>{entry.mode || parseMode(entry.account_id)}</Badge>
                      </td>
                      <td className="px-3">
                        <Badge variant={typeVariant(entry.entry_type)}>{asString(entry.entry_type).replaceAll('_', ' ')}</Badge>
                      </td>
                      <td className="px-3 font-bold text-foreground">{asString(entry.asset)}</td>
                      <td className={cn('px-3 font-mono font-semibold', amount > 0 ? 'text-emerald-300' : amount < 0 ? 'text-rose-300' : 'text-muted-foreground')}>
                        {formatAssetAmount(entry.amount, entry.asset)}
                      </td>
                      <td className="px-3 font-mono font-semibold text-foreground">{formatAssetAmount(entry.balance_after, entry.asset)}</td>
                      <td className="px-3 text-muted-foreground">{asString(entry.source).replaceAll('_', ' ')}</td>
                      <td className="max-w-[260px] truncate px-3 font-mono text-[12px] text-muted-foreground" title={reference}>{reference}</td>
                      <td className="max-w-[320px] truncate px-3 text-muted-foreground" title={asString(entry.description)}>{cleanDescription(entry.description)}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-3 pt-2 text-xs sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium text-muted-foreground">
              Affichage de <span className="font-bold text-foreground">{startItem}</span> a <span className="font-bold text-foreground">{endItem}</span> sur <span className="font-bold text-foreground">{totalCount}</span> lignes
            </span>
            <div className="flex items-center gap-1.5 border-l border-border/60 pl-3">
              <span className="text-muted-foreground">Par page :</span>
              <Select value={String(pageSize)} onValueChange={(value) => { setPageSize(Number(value)); setCurrentPage(1) }}>
                <SelectTrigger className="h-7 min-w-[76px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[10, 25, 50, 100, 200].map((value) => <SelectItem key={value} value={String(value)}>{value}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage(1)} className="h-7 w-7 p-0"><ChevronsLeft className="h-3.5 w-3.5" /></Button>
            <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} className="h-7 w-7 p-0"><ChevronLeft className="h-3.5 w-3.5" /></Button>
            <span className="px-2 font-bold text-foreground">{safePage} / {totalPages}</span>
            <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} className="h-7 w-7 p-0"><ChevronRight className="h-3.5 w-3.5" /></Button>
            <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage(totalPages)} className="h-7 w-7 p-0"><ChevronsRight className="h-3.5 w-3.5" /></Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
