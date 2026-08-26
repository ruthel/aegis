import * as am5 from '@amcharts/amcharts5'
import * as am5xy from '@amcharts/amcharts5/xy'
import am5themes_Dark from '@amcharts/amcharts5/themes/Dark'
import { memo, useEffect, useLayoutEffect, useRef } from 'react'

type Point = {
  label: string
  value: number
  event?: string
  balance?: number
  time?: string
}

type TimeRange = '24h' | '7d' | '30d' | '90d' | 'all'

interface LineChartProps {
  data: Point[]
  color?: string
  yAxisTitle?: string
  xAxisTitle?: string
  timeRange?: TimeRange
}

function gridIntervalForRange(range: TimeRange): am5.time.ITimeInterval {
  if (range === '24h') return { timeUnit: 'minute', count: 90 }
  if (range === '7d') return { timeUnit: 'hour', count: 12 }
  if (range === '30d') return { timeUnit: 'day', count: 2 }
  if (range === '90d') return { timeUnit: 'week', count: 1 }
  return { timeUnit: 'month', count: 1 }
}

function labelFormatForRange(range: TimeRange): string {
  if (range === '24h') return 'HH:mm'
  if (range === '7d') return 'dd/MM HH:mm'
  if (range === '30d') return 'dd/MM'
  if (range === '90d') return 'dd/MM'
  return 'MM/yyyy'
}

function LineChartBase({
  data,
  color = '#34d399',
  yAxisTitle = 'P&L Net Cumulé ($ USD)',
  xAxisTitle = 'Événements & Trades (N° Événement)',
  timeRange = '30d',
}: LineChartProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const rootRef = useRef<am5.Root | null>(null)
  const xAxisRef = useRef<am5xy.DateAxis<am5xy.AxisRenderer> | null>(null)
  const seriesRef = useRef<am5xy.LineSeries | null>(null)

  useLayoutEffect(() => {
    if (!ref.current) return
    const root = am5.Root.new(ref.current)
    rootRef.current = root
    root.setThemes([am5themes_Dark.new(root)])
    root._logo?.dispose()

    const chart = root.container.children.push(
      am5xy.XYChart.new(root, {
        panX: false,
        panY: false,
        wheelX: 'none',
        wheelY: 'none',
        paddingLeft: 10,
        paddingRight: 15,
        paddingBottom: 15,
      }),
    )

    const xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 80 })
    xRenderer.labels.template.setAll({ fill: am5.color(0x94a3b8), fontSize: 11 })

    const xAxis = chart.xAxes.push(
      am5xy.DateAxis.new(root, {
        baseInterval: { timeUnit: 'minute', count: 1 },
        dateFormats: {
          minute: labelFormatForRange(timeRange),
          hour: labelFormatForRange(timeRange),
          day: labelFormatForRange(timeRange),
          week: labelFormatForRange(timeRange),
          month: labelFormatForRange(timeRange),
        },
        gridIntervals: [gridIntervalForRange(timeRange)],
        renderer: xRenderer,
      }),
    )
    xAxisRef.current = xAxis

    // Titre axe X
    xAxis.children.push(
      am5.Label.new(root, {
        text: xAxisTitle,
        x: am5.p50,
        centerX: am5.p50,
        fill: am5.color(0x64748b),
        fontSize: 11,
        fontWeight: '700',
        paddingTop: 10,
      }),
    )

    const yRenderer = am5xy.AxisRendererY.new(root, {})
    yRenderer.labels.template.setAll({ fill: am5.color(0x94a3b8), fontSize: 11 })

    const yAxis = chart.yAxes.push(
      am5xy.ValueAxis.new(root, {
        renderer: yRenderer,
        numberFormat: "$#,###.00 USD",
      }),
    )

    // Titre axe Y
    yAxis.children.unshift(
      am5.Label.new(root, {
        text: yAxisTitle,
        rotation: -90,
        y: am5.p50,
        centerX: am5.p50,
        fill: am5.color(0x64748b),
        fontSize: 11,
        fontWeight: '700',
        paddingRight: 10,
      }),
    )

    const tooltip = am5.Tooltip.new(root, {
      getFillFromSprite: false,
      labelText: "[#ffffff][bold]{event}[/]\nP&L Net: [bold]{valueY} USD[/]\nSolde: [bold]{balance} USD[/][/]",
    })
    tooltip.label.setAll({
      fill: am5.color(0xffffff),
      fontSize: 12,
      oversizedBehavior: 'wrap',
    })
    tooltip.get("background")?.setAll({
      fill: am5.color(0x0f172a),
      fillOpacity: 0.95,
      stroke: am5.color(color),
      strokeWidth: 1.5,
    })
    tooltip.label.adapters.add('fill', () => am5.color(0xffffff))

    const series = chart.series.push(
      am5xy.LineSeries.new(root, {
        xAxis,
        yAxis,
        valueXField: 'valueX',
        valueYField: 'value',
        valueField: 'value',
        stroke: am5.color(color),
        tooltip,
      }),
    )
    seriesRef.current = series
    series.strokes.template.setAll({ strokeWidth: 2.5 })
    series.fills.template.setAll({ fillOpacity: 0.12, visible: true, fill: am5.color(color) })

    chart.set('cursor', am5xy.XYCursor.new(root, { behavior: 'none' }))

    return () => {
      root.dispose()
      rootRef.current = null
      xAxisRef.current = null
      seriesRef.current = null
    }
  }, [yAxisTitle, xAxisTitle, timeRange])

  useEffect(() => {
    const series = seriesRef.current
    const xAxis = xAxisRef.current
    if (!series || !xAxis) return
    const stroke = am5.color(color)
    series.set('stroke', stroke)
    series.set('fill', stroke)
    series.strokes.template.setAll({ stroke })
    series.fills.template.setAll({ fill: stroke })
    const chartData = data
      .map((point) => {
        const valueX = new Date(point.time || point.label).getTime()
        return { ...point, valueX }
      })
      .filter((point) => Number.isFinite(point.valueX))
      .sort((a, b) => a.valueX - b.valueX)
    xAxis.data.setAll(chartData)
    series.data.setAll(chartData)
  }, [data, color])

  return <div ref={ref} className="h-[280px] w-full" />
}

export const LineChart = memo(LineChartBase)
