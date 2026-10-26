/**
 * degrade_metrics_kpi_tiles.mjs — the degrade matrix on the metrics KPI
 * strip (t261026-11). Face under judgement: kpiTilesOf over the REAL
 * buildMetricsResponse payload (producer capture, regenerated every run).
 *
 * KNOWN RED (filed, NOT registered in run_scenarios.py): the real payload
 * still headlines 'FRESH TOKENS PER COVERED TICKET' — the caliber the host
 * ruled out; t261026-05 owns the fix. A red registered scenario blocks every
 * line round, so this file stays a direct-run diagnostic until that ticket
 * lands; re-run then, expect green, and register.
 *
 * Run: node integration/t261026-11/degrade_metrics_kpi_tiles.mjs
 * zstd missing or the producer refusing = ENV_FAIL exit 2.
 */
import { runDegradeMatrix } from '../lib_degrade_matrix.mjs'
import { realMetricsBody } from './lib_metrics_real.mjs'

const MODEL = new URL('../../server/plugins/executor-panel/src/host/metrics-tab-model.ts', import.meta.url).pathname
const model = await import(MODEL)

const real = await realMetricsBody()
if (real.env_fail) { console.log(`ENV_FAIL: ${real.env_fail}`); process.exit(2) }

const tiles = (payload) => model.kpiTilesOf(model.metricsV2Of(payload))

const r = runDegradeMatrix({
  face: 'metrics-kpi-tiles',
  // Faithful adapter: the face's entry chain is metricsV2Of (payload → view
  // model) then kpiTilesOf (view model → the tile list). No reinterpreting.
  call: tiles,
  real: real.body,
  copiesKey: 'sub',
  expect: (out) => {
    const by = (t) => (out.find((x) => x.title === t) ?? {})
    return {
      six_tiles_render: Array.isArray(out) && out.length === 6,
      throughput_value: by('THROUGHPUT').value !== undefined && by('THROUGHPUT').value !== '—',
      lead_time_value: by('MEDIAN LEAD TIME').value !== undefined && by('MEDIAN LEAD TIME').value !== '—',
      tokens_sub_calibers: String(by('TOKENS').sub ?? '').includes('in tickets'),
    }
  },
})

process.exit(r.ok ? 0 : 1)
