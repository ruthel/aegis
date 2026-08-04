/**
 * HourlyBarChart.tsx — Graphique amCharts 5 : PnL par heure (00h-23h UTC)
 */

import * as am5 from '@amcharts/amcharts5'
import * as am5xy from '@amcharts/amcharts5/xy'
import am5themes_Dark from '@amcharts/amcharts5/themes/Dark'
import { memo, useEffect, useLayoutEffect, useRef } from 'react'

type HourRow = {
  hour: number
  hourLabel: string
  trades: number
  wins: number
  winRate: number
  totalPnl: number
}

function HourlyBarChartBase({ data }: { data: HourRow[] }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const xAxisRef = useRef<am5xy.CategoryAxis<am5xy.AxisRenderer> | null>(null)
  const seriesRef = useRef<am5xy.ColumnSeries | null>(null)

  useLayoutEffect(() => {
    if (!ref.current) return
    const root = am5.Root.new(ref.current)
    root.setThemes([am5themes_Dark.new(root)])
    root._logo?.dispose()

    const chart = root.container.children.push(
      am5xy.XYChart.new(root, {
        panX: false,
        panY: false,
        wheelX: 'none',
        wheelY: 'none',
        paddingLeft: 10,
        paddingRight: 10,
        paddingBottom: 8,
      }),
    )

    const xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 28, cellStartLocation: 0.1, cellEndLocation: 0.9 })
    xRenderer.labels.template.setAll({
      fill: am5.color(0x94a3b8),
      fontSize: 10,
      fontFamily: 'monospace',
    })
    xRenderer.grid.template.setAll({ stroke: am5.color(0x1e293b), strokeWidth: 1 })

    const xAxis = chart.xAxes.push(
      am5xy.CategoryAxis.new(root, {
        categoryField: 'hourLabel',
        renderer: xRenderer,
      }),
    )

    const yRenderer = am5xy.AxisRendererY.new(root, {})
    yRenderer.labels.template.setAll({ fill: am5.color(0x94a3b8), fontSize: 10 })
    yRenderer.grid.template.setAll({ stroke: am5.color(0x1e293b), strokeWidth: 1 })

    const yAxis = chart.yAxes.push(
      am5xy.ValueAxis.new(root, {
        renderer: yRenderer,
        numberFormat: "+$#,###.0000|$#,###.0000",
      }),
    )

    // Zero line
    const range = yAxis.createAxisRange(yAxis.makeDataItem({ value: 0 }))
    range.get('grid')?.setAll({ stroke: am5.color(0x475569), strokeWidth: 1.5, strokeDasharray: [4, 3] })

    const tooltip = am5.Tooltip.new(root, {
      getFillFromSprite: false,
      labelText: '[bold #ffffff]{hourLabel}:00 UTC[/]\nP&L: [bold]{valueY.formatNumber("+$#,###.0000|$#,###.0000")} USD[/]\n{trades} trade(s) · {winRate}% win',
    })
    tooltip.label.setAll({ fill: am5.color(0xffffff), fontSize: 12 })
    tooltip.get('background')?.setAll({
      fill: am5.color(0x0f172a),
      fillOpacity: 0.95,
      stroke: am5.color(0x334155),
      strokeWidth: 1,
    })

    const series = chart.series.push(
      am5xy.ColumnSeries.new(root, {
        xAxis,
        yAxis,
        valueYField: 'totalPnl',
        categoryXField: 'hourLabel',
        tooltip,
      }),
    )

    series.columns.template.setAll({
      cornerRadiusTL: 3,
      cornerRadiusTR: 3,
      strokeOpacity: 0,
      width: am5.percent(85),
    })

    series.columns.template.adapters.add('fill', (_fill, target) => {
      const dataItem = target.dataItem
      const val = Number((dataItem?.dataContext as any)?.totalPnl ?? 0)
      return val >= 0 ? am5.color(0x10b981) : am5.color(0xf43f5e)
    })

    series.columns.template.adapters.add('stroke', (_stroke, target) => {
      const dataItem = target.dataItem
      const val = Number((dataItem?.dataContext as any)?.totalPnl ?? 0)
      return val >= 0 ? am5.color(0x10b981) : am5.color(0xf43f5e)
    })

    xAxisRef.current = xAxis
    seriesRef.current = series

    return () => {
      xAxisRef.current = null
      seriesRef.current = null
      root.dispose()
    }
  }, [])

  useEffect(() => {
    xAxisRef.current?.data.setAll(data)
    seriesRef.current?.data.setAll(data)
  }, [data])

  return <div ref={ref} className="h-[260px] w-full" />
}

export const HourlyBarChart = memo(HourlyBarChartBase)
