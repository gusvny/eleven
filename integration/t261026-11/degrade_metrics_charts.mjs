/**
 * degrade_metrics_charts.mjs — the degrade matrix on the metrics secondary
 * charts (throughput line + tokens stack) (t261026-11). Face under judgement:
 * throughputSpecOf/tokensStackOf + the two option builders over the REAL
 * buildMetricsResponse payload (producer capture, regenerated every run).
 *
 * This incident's origin face: the panel expected a daily opened/closed
 * series and the API sent a blocked leaderboard — the chart went silently
 * empty. The matrix's five shapes make that answer speak.
 *
 * Registered in run_scenarios.py only while green (green-before-register).
 * Run: node integration/t261026-11/degrade_metrics_charts.mjs
 * zstd missing or the producer refusing = ENV_FAIL exit 2.
 */
import { runDegradeMatrix } from '../lib_degrade_matrix.mjs'
import { realMetricsBody } from './lib_metrics_real.mjs'

const CHARTS = new URL('../../server/plugins/executor-panel/src/host/metrics-tab-charts.ts', import.meta.url).pathname
const MODEL = new URL('../../server/plugins/executor-panel/src/host/metrics-tab-model.ts', import.meta.url).pathname
const charts = await import(CHARTS)
const model = await import(MODEL)

const real = await realMetricsBody()
if (real.env_fail) { console.log(`ENV_FAIL: ${real.env_fail}`); process.exit(2) }

// Faithful adapter: the page draws throughputOption(throughputSpecOf(body))
// and tokensOption(tokensStackOf(body)). The adapter answers with exactly
// what the page would hand the chart library — since t261026-11 the spec
// faces answer as funnel values, so an absent face passes through verbatim
// (its reason travels), never dressed.
const call = (payload) => {
  const spec = model.throughputSpecOf(payload)
  const stack = model.tokensStackOf(payload)
  return {
    throughput: (spec && spec.kind === 'absent') ? spec : charts.throughputOption(spec.v),
    tokens: (stack && stack.kind === 'absent') ? stack : charts.tokensOption(stack.v),
  }
}

const r = runDegradeMatrix({
  face: 'metrics-secondary-charts',
  call,
  real: real.body,
  expect: (out) => ({
    throughput_days: Array.isArray(out?.throughput?.xAxis?.data) && out.throughput.xAxis.data.length > 0,
    throughput_series: Array.isArray(out?.throughput?.series) && out.throughput.series.length >= 2,
    tokens_series: Array.isArray(out?.tokens?.series) && out.tokens.series.length > 0,
  }),
})

process.exit(r.ok ? 0 : 1)
