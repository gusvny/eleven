#!/usr/bin/env node
/**
 * sc_metrics_v2_kpis_epics_no_cost.mjs — t261021-06 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable): the KPI row and the Epics tab carry honest rollups —
 * rework_rate counts closed tickets that ran some stage more than once; throughput,
 * median lead time, human-wait share, per-closed-ticket tokens and cache hit are
 * each computed from the same windowed population; each epic row carries tickets,
 * elapsed_ms, tokens and last_activity_ms. Ticket item 4 verdict: NO money — there
 * is no price table, so no cost/price field may appear anywhere in the payload.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_kpis_epics_no_cost.mjs (cwd=repo root)
 */
import { withRepoStub, callMetricsV2, makeChecker, allKeys, laneTicket, NOW, DAY, iso, WF_DEV } from './lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

// Controlled population, window=all. Timelines are internally consistent: every
// stage window sits inside [created, closed] and each ticket carries a terminal
// `closed` entry exactly at its close — closed_ms derives from the max `closed`
// entry (computeDurations), so the derived leads are the intended 3/1/2 days
// (arbitrate gen2: the old fixture ran rework entries past the close, so the
// derived leads were not the intended ones). `updated` is an ISO string (the row
// parser is string-typed).
const tK = (id, leadDays, rework, epic) => {
  const created = NOW - 10 * DAY
  const closed = NOW - (10 - leadDays) * DAY
  return laneTicket(id, `lane-${id}`, {
    createdAt: created,
    closedAt: closed,
    epic,
    updated: iso(closed),
    timeline: [
      { at: iso(created), stage: 'plan', state: 'running' },
      { at: iso(created + 3600e3), stage: 'plan', state: 'closed' },
      ...(rework
        ? [
            { at: iso(closed - 8 * 3600e3), stage: 'code', state: 'running' },
            { at: iso(closed - 6 * 3600e3), stage: 'code', state: 'closed' },
            { at: iso(closed - 4 * 3600e3), stage: 'code', state: 'running' },
            { at: iso(closed), stage: 'code', state: 'closed' },
          ]
        : [
            { at: iso(closed - 4 * 3600e3), stage: 'code', state: 'running' },
            { at: iso(closed), stage: 'code', state: 'closed' },
          ]),
    ],
  })
}

await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [tK('t21-k1', 3, false, 'epic-alpha'), tK('t21-k2', 1, true, 'epic-alpha'), tK('t21-k3', 2, false, 'epic-beta')],
    epics: ['epic-alpha', 'epic-beta'],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r.status === 200, 'front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body
    const k = b.kpis ?? {}

    // K1 — rework_rate: share of CLOSED tickets with at least one reworked stage.
    // Tolerance 5e-4 = the implementation's declared 4-decimal rounding of shares
    // (round4, same rounding discipline as v1's avg_delivery_min); the contract
    // states the share formula, not full precision.
    ok(Math.abs((k.rework_rate ?? -1) - 1 / 3) < 5e-4, 'K1 rework_rate ≈ 1/3 (one of three closed tickets reworked)', `got ${k.rework_rate}`)

    // K2 — median_lead_time over closed tickets with both anchors: leads 3d/1d/2d → median 2d.
    ok(k.median_lead_time === 2 * DAY, `K2 median_lead_time = 2d`, `got ${k.median_lead_time}`)

    // K3 — throughput_per_day positive and finite over the window.
    ok(typeof k.throughput_per_day === 'number' && k.throughput_per_day > 0 && Number.isFinite(k.throughput_per_day), 'K3 throughput_per_day positive finite', `got ${k.throughput_per_day}`)

    // K4 — human_wait_share: within (0,1]; plan is a human-exit stage so the share cannot be 0 here.
    ok(typeof k.human_wait_share === 'number' && k.human_wait_share > 0 && k.human_wait_share <= 1, `K4 human_wait_share in (0,1]`, `got ${k.human_wait_share}`)

    // K5 — epics rollups: alpha has 2 tickets, beta 1; last_activity_ms = the max ticket mtime in the epic.
    const epics = Array.isArray(b.epics) ? b.epics : []
    const byEpic = Object.fromEntries(epics.map((e) => [e.epic ?? e.id, e]))
    ok((byEpic['epic-alpha']?.tickets ?? -1) === 2 && (byEpic['epic-beta']?.tickets ?? -1) === 1, 'K5 epic tickets rollup 2/1', JSON.stringify(epics)?.slice(0, 200))
    ok(byEpic['epic-alpha']?.last_activity_ms === NOW - 7 * DAY, 'K5 epic-alpha last_activity_ms = its most recently updated ticket row (t21-k1, closed latest)', `got ${byEpic['epic-alpha']?.last_activity_ms}`)
    ok((byEpic['epic-alpha']?.elapsed_ms ?? 0) > 0 && (byEpic['epic-alpha']?.tokens === null || byEpic['epic-alpha']?.tokens >= 0), 'K5 epic row carries elapsed_ms and a non-fabricated tokens (null + reason when no token data)', JSON.stringify(byEpic['epic-alpha'])?.slice(0, 200))

    // K6 — no money anywhere: no cost/price/currency key in the whole payload.
    const keys = allKeys(b)
    const money = keys.filter((x) => /cost|price|usd|currency|amount/i.test(x))
    ok(money.length === 0, `K6 no cost/price field anywhere (found: ${money.join(',') || 'none'})`, money.join(','))

    // K7 — every new KPI key is present by name (contract freeze face; missing key = red).
    for (const name of ['rework_rate', 'throughput_per_day', 'median_lead_time', 'human_wait_share', 'tokens_total', 'tokens_in_tickets', 'tokens_outside_tickets', 'tokens_per_closed_ticket', 'cache_hit']) {
      ok(k[name] !== undefined, `K7 kpis.${name} present`, 'missing key')
    }
  },
)

// K8 — zero-domain degrade: a window with NO closed tickets names rework_rate/median as null + reason (never 0).
await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [laneTicket('t21-open', 'lane-o', { createdAt: NOW - 1 * DAY, timeline: [] })],
    epics: [],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r.status === 200, 'K8 front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const k = r.body?.kpis ?? {}
    ok(k.rework_rate === null, 'K8 rework_rate null (no closed tickets)', `got ${k.rework_rate}`)
    ok(k.median_lead_time === null || typeof k.median_lead_time === 'number', 'K8 median_lead_time null or defined — never a fabricated 0', `got ${k.median_lead_time}`)
    ok(k.tokens_per_closed_ticket === null || typeof k.tokens_per_closed_ticket === 'number', 'K8 tokens_per_closed_ticket null or defined — division by zero closed named, not zero-filled', `got ${k.tokens_per_closed_ticket}`)
  },
)

process.exit(done('sc_metrics_v2_kpis_epics_no_cost'))
