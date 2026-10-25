/**
 * sc_metrics_panel_degrade_faces.mjs — t261025-13 items 2-3 face half, L3
 * (grey-box, offline seconds, browser-free: the panel model is a pure module).
 *
 * intent (user-perceivable, host report 261025): a degraded Metrics tile NAMES
 * its degrade instead of showing a bare dash. Today tokens_outside_tickets = null
 * renders '28.1M' with a bare dash sub-line, and MEDIAN LEAD TIME carries a
 * hardcoded 'P90 —' even when the payload can compute the P90. Host ruling: a
 * permanent dash is a control-shaped lie of the t261019-23 F2 family.
 *
 * Assertions anchor to the public model functions (the same seam the page embeds
 * via String(fn)), never to field names or class names — KI-051 discipline.
 *
 * Intent split: the p90 COMPUTATION contract = t261025-13-p90-lead-time; the
 * workbench-side named degrades = t261021-06-degrade-named-faces; this entry owns
 * the panel tile faces when data is degraded.
 *
 * Pre-implement red on F1/F3 is the expected TDD signal (the executor-panel face
 * fix rides a write-set extension); arbitrate/merge must be green.
 * Run: node integration/t261025-13/sc_metrics_panel_degrade_faces.mjs (cwd=repo root)
 * node missing = ENV_FAIL exit 2.
 */
import { kpiTilesOf, metricsV2Of, DASH, fmtMs } from '../../server/plugins/executor-panel/src/host/metrics-tab-model.ts'

const { ok, done } = (await import('../t261021-06/lib_metrics_v2.mjs')).makeChecker()

const tiles = (kpis) => kpiTilesOf(metricsV2Of({ kpis }))
const byTitle = (tiles_, title) => tiles_.find((t) => t.title === title)

const HAPPY = {
  tickets: 191, closed: 168, throughput_per_day: 5.86, median_lead_time: 42919000,
  p90_lead_time: 90000000, tokens_total: 28.1e6, tokens_in_tickets: 21e6,
  tokens_outside_tickets: 7.1e6, human_wait_share: 0.5612,
  tokens_cache_read: 4.2e6, tickets_with_usage: 38, closed_with_usage: 31,
}

// F0 — happy path sanity: both sub-lines carry the real split (regression floor;
// the mock's split the host asked for must keep rendering when data exists).
{
  const tok = byTitle(tiles(HAPPY), 'TOKENS')
  ok(tok && tok.sub.includes('in tickets') && tok.sub.includes('outside'),
    'F0 TOKENS sub renders the in/outside split when both values exist', `sub=${tok?.sub}`)
  const med = byTitle(tiles(HAPPY), 'MEDIAN LEAD TIME')
  ok(med && med.sub.includes(fmtMs(HAPPY.p90_lead_time)),
    'F0 MEDIAN LEAD TIME sub renders the computed P90 when it exists', `sub=${med?.sub}`)
}

// F0b — token-coverage ruling: the three token tiles carry an over-N-of-M
// coverage line and actual traffic includes cache; the rework-rate tile is gone.
{
  const all = tiles(HAPPY)
  ok(all.length === 6 && !all.some((t) => t.title === 'REWORK RATE'),
    'F0b six tiles, rework-rate tile removed', JSON.stringify(all.map((t) => t.title)))
  ok(byTitle(all, 'TOKENS').sub.includes('38 of 191 tickets with usage'),
    'F0b TOKENS sub carries the coverage line', `sub=${byTitle(all, 'TOKENS')?.sub}`)
  ok(byTitle(all, 'FRESH TOKENS PER COVERED TICKET') !== undefined
    && byTitle(all, 'CACHE SHARE').sub.includes('38 of 191'),
    'F0b fresh-per-covered and cache-share tiles carry the coverage line')
}

// F1 — item 2: tokens_outside_tickets null (project block missing) → the sub-line
// NAMES the degrade; a bare dash is the defect.
{
  const k = { ...HAPPY, tokens_outside_tickets: null }
  const tok = byTitle(tiles(k), 'TOKENS')
  ok(tok && tok.sub !== DASH, `F1 degraded TOKENS sub is not a bare dash`, `sub=${tok?.sub}`)
  ok(tok && !tok.sub.endsWith(DASH) && !tok.sub.includes(`· ${DASH}`),
    'F1 no dangling dash fragment after the split separator', `sub=${tok?.sub}`)
  ok(tok && /outside/i.test(tok.sub),
    'F1 the degraded sub still speaks the outside-tokens language (names what is unavailable)', `sub=${tok?.sub}`)
}

// F2 — item 3: p90 null (empty window) → named degrade, never a permanent 'P90 —'.
{
  const k = { ...HAPPY, p90_lead_time: null }
  const med = byTitle(tiles(k), 'MEDIAN LEAD TIME')
  ok(med && med.sub !== 'P90 ' + DASH, `F2 the hardcoded 'P90 ${DASH}' sub is gone`, `sub=${med?.sub}`)
  ok(med && !med.sub.endsWith(DASH),
    'F2 a null P90 degrades to a NAMED face, never a bare dash', `sub=${med?.sub}`)
}

// F3 — malformed payload three-state: garbage/missing kpis never crash the tiles
// and never fabricate a P90 value or a token split.
{
  let threw = false
  let ts
  try { ts = tiles({}) } catch { threw = true }
  ok(!threw && Array.isArray(ts) && ts.length === 6, 'F3 empty kpis: six tiles, no throw', `threw=${threw}`)
  const med = byTitle(ts ?? [], 'MEDIAN LEAD TIME')
  ok(med && !String(med.sub).match(/P90\s*$/) && String(med.sub).length > 0,
    'F3 no bare/empty P90 face on a garbage payload', `sub=${med?.sub}`)
}

process.exit(done('sc_metrics_panel_degrade_faces'))
