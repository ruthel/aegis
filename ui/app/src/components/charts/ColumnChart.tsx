import * as am5 from '@amcharts/amcharts5'
import * as am5xy from '@amcharts/amcharts5/xy'
import am5themes_Dark from '@amcharts/amcharts5/themes/Dark'
import { useLayoutEffect, useRef } from 'react'

type Point = {
  label: string
  value: number
}

export function ColumnChart({ data, color = '#60a5fa' }: { data: Point[]; color?: string }) {
  const ref = useRef<HTMLDivElement | null>(null)

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
        paddingLeft: 0,
        paddingRight: 10,
      }),
    )
    const xAxis = chart.xAxes.push(
      am5xy.CategoryAxis.new(root, {
        categoryField: 'label',
        renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 35 }),
      }),
    )
    const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { renderer: am5xy.AxisRendererY.new(root, {}) }))
    const series = chart.series.push(
      am5xy.ColumnSeries.new(root, {
        xAxis,
        yAxis,
        valueYField: 'value',
        categoryXField: 'label',
        fill: am5.color(color),
        stroke: am5.color(color),
        tooltip: am5.Tooltip.new(root, { labelText: '{categoryX}: {valueY}' }),
      }),
    )
    series.columns.template.setAll({ cornerRadiusTL: 4, cornerRadiusTR: 4, fillOpacity: 0.8 })
    xAxis.data.setAll(data)
    series.data.setAll(data)

    return () => root.dispose()
  }, [data, color])

  return <div ref={ref} className="h-[260px] w-full" />
}
