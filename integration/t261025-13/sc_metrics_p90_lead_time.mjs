/**
 * sc_metrics_p90_lead_time.mjs — t261025-13 item 3 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable, host report 261025): the MEDIAN LEAD TIME tile no
 * longer carries a hardcoded 'P90 —' sub-line. The window population that yields
 * the median can compute the P90, so the API carries a real `p90_lead_time`
 * computed from the same sorted closed-ticket leads — degrading to null (same
 * family as the median) when the window has no closed tickets. A permanent dash
 * is a control-shaped lie (t261019-23 F2 family).
 *
 * Intent split: the median formula and the other KPI formulas = existing
 * t261021-06-kpis-epics-no-cost / t260903-09; the panel sub-line rendering =
 * t261025-13 panel degrade faces. This entry owns the p90 rank contract.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261025-13/sc_metrics_p90_lead_time.mjs (cwd=repo root)
 * node missing = ENV_FAIL exit 2.
 */
import { withRepoStub, callMetricsV2, makeChecker, laneTicket, NOW, DAY, WF_DEV } from '../t261021-06/lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

// Deterministic closed ticket with lead = leadDays (created → closed, timeline
// consistent: the terminal `closed` entry sits exactly at close, same discipline
// as the t261021-06 kpis fixture).
const tLead = (id, leadDays) => {
  const created = NOW - 10 * DAY
  const closed = NOW - (10 - leadDays) * DAY
  return laneTicket(id, `lane-${id}`, {
    createdAt: created,
    closedAt: closed,
    updated: new Date(closed).toISOString(),
    timeline: [
      { at: new Date(created).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(closed).toISOString(), stage: 'code', state: 'closed' },
    ],
    extra: { updated_ts: Math.round(closed / 1000) },
  })
}

async function p90Of(tickets) {
  return withRepoStub(
    async () => ({
      project: 'demo',
      workflows: [WF_DEV],
      stages: WF_DEV.stages,
      tickets,
      epics: [],
    }),
    async ({ deps }) => {
      const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
      if (r.status !== 200) return { status: r.status }
      return { kpis: r.body?.kpis ?? {} }
    },
  )
}

// P1 — four leads 1/2/3/4 days: sorted, rank index ceil(0.9*(n-1)) = ceil(2.7) = 3 → 4d.
{
  const { kpis } = await p90Of([tLead('t13-p1', 1), tLead('t13-p2', 2), tLead('t13-p3', 3), tLead('t13-p4', 4)])
  ok(kpis?.p90_lead_time === 4 * DAY, `P1 even n=4: p90_lead_time = 4d (rank ceil(0.9*(n-1)))`, `got ${kpis?.p90_lead_time}`)
  ok(kpis?.median_lead_time === 2 * DAY + 12 * 3600e3 || typeof kpis?.median_lead_time === 'number',
    'P1 median stays a number on the same population (no re-derivation of the median contract here)', `got ${kpis?.median_lead_time}`)
}

// P2 — three leads 1/2/3 days: rank ceil(1.8) = 2 → 3d (odd n).
{
  const { kpis } = await p90Of([tLead('t13-q1', 1), tLead('t13-q2', 2), tLead('t13-q3', 3)])
  ok(kpis?.p90_lead_time === 3 * DAY, `P2 odd n=3: p90_lead_time = 3d`, `got ${kpis?.p90_lead_time}`)
}

// P3 — single closed ticket: the whole distribution is that one lead → 2d.
{
  const { kpis } = await p90Of([tLead('t13-r1', 2)])
  ok(kpis?.p90_lead_time === 2 * DAY, `P3 n=1: p90_lead_time = the single lead`, `got ${kpis?.p90_lead_time}`)
}

// P4 — empty domain (no closed tickets in the window): null degrade, never a fabricated 0.
{
  const { kpis } = await p90Of([laneTicket('t13-open', 'lane-o', { createdAt: NOW - 1 * DAY, timeline: [] })])
  ok(kpis?.p90_lead_time === null, `P4 empty window: p90_lead_time = null (never 0)`, `got ${kpis?.p90_lead_time}`)
}

process.exit(done('sc_metrics_p90_lead_time'))
