import * as am5 from '@amcharts/amcharts5'
import * as am5xy from '@amcharts/amcharts5/xy'
import am5themes_Dark from '@amcharts/amcharts5/themes/Dark'
import { memo, useLayoutEffect, useRef } from 'react'

export type ScorePoint = {
  time: number
  tooltipLabel: string
  score: number
  rawScore?: number
  price: number
}

function ScoreHistoryChartBase({ data, intervalHours, periodHours }: { data: ScorePoint[]; intervalHours: number; periodHours: number }) {
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

    const firstTime = data[0]?.time
    const lastTime = data[data.length - 1]?.time
    const xRenderer = am5xy.AxisRendererX.new(root, {
      minGridDistance: periodHours <= 24 ? 110 : 95,
    })
    xRenderer.labels.template.setAll({
      centerY: am5.p50,
      paddingTop: 8,
    })

    const xAxis = chart.xAxes.push(
      am5xy.DateAxis.new(root, {
        baseInterval: { timeUnit: 'minute', count: 1 },
        gridIntervals: [
          { timeUnit: 'hour', count: intervalHours },
          { timeUnit: 'day', count: 1 },
        ],
        dateFormats: {
          hour: 'HH:mm',
          day: 'dd/MM',
        },
        periodChangeDateFormats: {
          hour: 'HH:mm',
          day: 'dd/MM',
        },
        min: firstTime,
        max: lastTime,
        strictMinMax: true,
        renderer: xRenderer,
      }),
    )

    const yAxis = chart.yAxes.push(
      am5xy.ValueAxis.new(root, {
        min: 0,
        max: 100,
        strictMinMax: true,
        renderer: am5xy.AxisRendererY.new(root, {}),
      }),
    )

    const series = chart.series.push(
      am5xy.SmoothedXLineSeries.new(root, {
        name: 'Score Crypto (0-100)',
        xAxis,
        yAxis,
        valueYField: 'score',
        valueXField: 'time',
        stroke: am5.color('#3b82f6'),
        fill: am5.color('#3b82f6'),
        tooltip: (() => {
          const tt = am5.Tooltip.new(root, {
            labelText: '[#ffffff]{tooltipLabel}\nScore lissé: {score.formatNumber("#.0")}/100\nScore brut: {rawScore.formatNumber("#.0")}/100\nPrix: {price.formatNumber("#,###.00")} USD[/]',
          })
          tt.label.setAll({ fill: am5.color(0xffffff), fontSize: 12 })
          return tt
        })(),
      }),
    )

    series.strokes.template.setAll({ strokeWidth: 2.75, strokeOpacity: 0.95 })
    series.fills.template.setAll({ fillOpacity: 0.08, visible: true })
    if (data.length <= 48) {
      series.bullets.push(() =>
        am5.Bullet.new(root, {
          sprite: am5.Circle.new(root, {
            radius: 2.5,
            fill: am5.color('#3b82f6'),
            stroke: am5.color('#0f172a'),
            strokeWidth: 1,
          }),
        }),
      )
    }

    xAxis.data.setAll(data)
    series.data.setAll(data)
    chart.set('cursor', am5xy.XYCursor.new(root, { behavior: 'none' }))

    return () => root.dispose()
  }, [data, intervalHours, periodHours])

  return <div ref={ref} className="h-[240px] w-full" />
}

export const ScoreHistoryChart = memo(ScoreHistoryChartBase)
