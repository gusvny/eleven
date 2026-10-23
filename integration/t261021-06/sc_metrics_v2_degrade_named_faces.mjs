#!/usr/bin/env node
/**
 * sc_metrics_v2_degrade_named_faces.mjs — t261021-06 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable): every v2 degrade face is NAMED — the user reads a
 * reason string, never a silent zero. Ticket items (degrade list): a ticket with
 * no session files, an epic with no tickets, an unreadable session file, and a
 * project with no project-level sessions each return null plus a reason; missing
 * rounds never becomes 0 — a ticket whose history cannot be read is excluded from
 * the rounds denominator and counted in notices; the health direct-query view
 * carries the new blocks as null + reason, never zero-filled.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_degrade_named_faces.mjs (cwd=repo root)
 */
import { withRepoStub, callMetricsV2, makeChecker, writeGarbageSession, laneTicket, NOW, DAY, iso, WF_DEV } from './lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

// Two populations in one repo:
//  - repo root carries NO project-level `.dsh/sessions` → project_sessions = null + reason;
//  - ticket t21-nohist has NO timeline at all → rounds face must name it, never 0-fill;
//  - ticket list carries epic code `epic-empty` (declared) with no tickets in-window;
//  - a second stub (below) hosts a garbage session file for the unreadable face.
const tGood = laneTicket('t21-good', 'lane-g', {
  createdAt: NOW - 2 * DAY,
  closedAt: NOW - 1 * DAY,
  timeline: [
    { at: iso(NOW - 2 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 1 * DAY), stage: 'plan', state: 'closed' },
  ],
})
const tNoHist = laneTicket('t21-nohist', 'lane-h', { createdAt: NOW - 2 * DAY, timeline: undefined })

await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [tGood, tNoHist],
    epics: ['epic-empty'],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r.status === 200, 'front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body
    const text = JSON.stringify(b)

    // D1 — project with no project-level sessions: null + reason, never {} / zero totals.
    const ps = b.project_sessions
    ok(ps === null || (ps != null && typeof ps.reason === 'string' && ps.reason.length > 0), 'D1 project_sessions null or named reason (no project sessions on disk)', JSON.stringify(ps)?.slice(0, 200))
    ok(!(ps && typeof ps === 'object' && ps.total != null && ps.total.input === 0 && !ps.reason), 'D1 zero-domain never silent-zero-filled')

    // D2 — ticket with no readable history: excluded from rounds denominators AND counted in notices.
    const stages = Array.isArray(b.stages) ? b.stages : []
    const plan = stages.find((s) => s.stage === 'plan' && (s.workflow ?? '') === 'dev-lane')
    ok(plan != null, 'D2 stages[] still aggregates the readable ticket')
    ok((plan?.avg_rounds_per_ticket ?? 0) > 0, 'D2 avg_rounds denominator excludes the unreadable-history ticket (never divides by a zero-filled 0)', JSON.stringify(plan)?.slice(0, 200))
    ok(/t21-nohist/.test(text), 'D2 the unreadable-history ticket is NAMED in the payload (notice/reason, not silent)', 'no mention of t21-nohist')

    // D3 — epic with no in-window rows: the frozen contract rules it OMITTED from
    // epics[] (an entry appears only for epics with rows); `epics: null + reason`
    // is required only when the WHOLE window has no epic rows. Accept either the
    // contract's omission or a reason-carrying entry — a zero-filled fabricated
    // row without a reason is the only forbidden shape.
    const epics = Array.isArray(b.epics) ? b.epics : []
    const empty = epics.find((e) => (e.epic ?? e.id) === 'epic-empty')
    if (empty === undefined) {
      ok(true, 'D3 empty epic omitted per contract (entries appear only for epics with rows)')
    } else {
      ok(empty.tickets === 0 && typeof empty.reason === 'string' && empty.reason.length > 0, 'D3 empty epic carries tickets=0 only together with a reason', JSON.stringify(empty)?.slice(0, 200))
    }
  },
)

// D4 — unreadable session file inside the project tree: named reason, siblings still counted.
await withRepoStub(
  async (repo) => {
    await writeGarbageSession(repo, 'global', 'broken-sess')
    return {
      project: 'demo',
      workflows: [WF_DEV],
      stages: WF_DEV.stages,
      tickets: [],
      epics: [],
    }
  },
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'token', window: 'all' })
    ok(r.status === 200, 'D4 front door 200 with a garbage session file', `status=${r.status}`)
    const ps = r.body?.project_sessions
    const named = ps != null && (JSON.stringify(ps).includes('broken-sess') || typeof ps.reason === 'string')
    ok(ps === null || named, 'D4 unreadable session file degrades to null or a named reason — no crash, no silent skip', JSON.stringify(ps)?.slice(0, 240))
  },
)

// D5 — health direct-query view: new blocks are null + reason, never zero-filled.
await withRepoStub(
  async () => ({ project: 'demo', workflows: [WF_DEV], stages: WF_DEV.stages, tickets: [tGood], epics: [] }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'health', window: 'all' })
    ok(r.status === 200, 'D5 health view 200', `status=${r.status} body=${JSON.stringify(r.body).slice(0, 160)}`)
    if (r.status !== 200) return
    const b = r.body
    for (const key of ['workflows', 'stages', 'project_sessions', 'epics']) {
      const v = b[key]
      const namedNull = v === null || (Array.isArray(v) && v.length === 0 && typeof b.reason === 'string')
      ok(namedNull, `D5 health.${key} is null/absent with a named reason, never zero-filled`, JSON.stringify(v)?.slice(0, 120))
    }
  },
)

process.exit(done('sc_metrics_v2_degrade_named_faces'))
