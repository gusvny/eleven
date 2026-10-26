/**
 * metrics-tab-charts.ts — the Metrics tab's chart option factories
 * (t261021-07). The adapter layer for the panel: the ONLY place that shapes
 * echarts options. The functions stay closure-free pure factories returning
 * plain option objects (no echarts import — the browser side owns
 * echarts.init/dispose behind the page's one module script), so the unit
 * test and the page run ONE implementation via the String(fn) embed.
 *
 * Ruling kept (docs/design/metrics-panel-ui-plan.md §1/§8): ECharts behind
 * the metrics-charts adapter discipline; the view layer never sees echarts.
 *
 * Palette (host order, this ticket): developer teal #0f766e, integration
 * blue #2563eb, executor violet #7c3aed, executor session #c2255c, global
 * session #495057 — five distinct colours; series beyond five cycle.
 */

/** The five declared series colours, in ticket order. */
export const METRICS_SERIES_COLORS = ['#0f766e', '#2563eb', '#7c3aed', '#c2255c', '#495057']

export const GRID_LINE = '#dde3e6'
export const LABEL = '#5f7178'

export function colorAt(i: number): string {
  return METRICS_SERIES_COLORS[i % METRICS_SERIES_COLORS.length]
}

export function commonAxes(days: string[], axisTitle: string): Record<string, unknown> {
  return {
    xAxis: {
      type: 'category',
      data: days,
      axisLine: { lineStyle: { color: GRID_LINE } },
      axisTick: { show: false },
      axisLabel: { color: LABEL, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: axisTitle,
      nameTextStyle: { color: LABEL, fontSize: 11 },
      splitLine: { show: true, lineStyle: { color: GRID_LINE, type: 'dashed' } },
      axisLabel: { color: LABEL, fontSize: 11 },
    },
  }
}

export function commonGrid(): Record<string, unknown> {
  return { left: 56, right: 24, top: 40, bottom: 32 }
}

/**
 * Throughput: daily opened (line with markers) versus closed (columns),
 * value axis, gridlines, date ticks. spec = { days, opened, closed }.
 */
export function throughputOption(spec: { days: string[]; opened: unknown[]; closed: unknown[] }): Record<string, unknown> {
  return {
    animation: false,
    grid: commonGrid(),
    legend: { top: 0, left: 0, icon: 'roundRect', textStyle: { color: LABEL, fontSize: 12 } },
    tooltip: { show: false },
    ...commonAxes(spec.days, 'tickets / day'),
    series: [
      {
        name: 'closed', type: 'bar', data: spec.closed,
        itemStyle: { color: colorAt(0), borderRadius: 2 }, barMaxWidth: 30,
      },
      {
        name: 'opened', type: 'line', data: spec.opened, symbol: 'circle', symbolSize: 6,
        lineStyle: { color: colorAt(1), width: 2 }, itemStyle: { color: colorAt(1) },
      },
    ],
  }
}

/**
 * Where the tokens go: the payload's OWN charts.primary spec, verbatim
 * (t261026-05: doc winner is the server — today a per-stage bar whose title
 * the card carries; a stacked daily-by-model shape renders the same way).
 * stack = { title, categories, series:[{name,data}] }; the API's title (when
 * present) becomes the chart title so the card says what it draws. Series
 * stack only when there is more than one (a single-series bar stays a plain
 * bar). Colours assign in order from the declared palette; values scale to
 * millions here (the axis title says so).
 */
export function tokensOption(stack: { title?: string | null; categories: string[]; series: Array<{ name: string; data: unknown[] }> }): Record<string, unknown> {
  const axes = commonAxes(stack.categories, 'tokens (M)')
  const stacked = stack.series.length > 1
  return {
    animation: false,
    grid: commonGrid(),
    legend: { top: 0, left: 0, type: 'scroll', textStyle: { color: LABEL, fontSize: 12 } },
    tooltip: { show: false },
    ...(stack.title ? { title: { text: stack.title, left: 'center', bottom: 0, textStyle: { color: LABEL, fontSize: 11, fontWeight: 'normal' } } } : {}),
    ...axes,
    series: stack.series.map(function (s, i) {
      return {
        name: s.name, type: 'bar', ...(stacked ? { stack: 'tokens' } : {}),
        data: (s.data as unknown[]).map(function (v) {
          const n = (typeof v === 'number' && Number.isFinite(v)) ? v : null
          return n === null ? null : Math.round((n / 1e6) * 100) / 100
        }),
        itemStyle: { color: colorAt(i) },
        barMaxWidth: 30,
      }
    }),
  }
}
