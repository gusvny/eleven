/**
 * sc_metrics_machine_timestamps.mjs — t261025-13 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable, host report 261025): no metrics face ever shows a
 * timestamp that was INVENTED from a display string. The live API returned every
 * epic's last_activity_ms in October 2001 because the read path parsed the
 * DISPLAY `updated` column ("10-25 22:17" → V8 resolves to year 2001) instead
 * of the machine `updated_ts` (epoch SECONDS). The same display-column parse
 * silently emptied the health view's bounded-window counts and made the
 * silent-running detector unfireable. Contract (v2 §epics): last_activity_ms
 * degrades to null — never to an invented value.
 *
 * Family sweep discipline (review_plan gen0): this entry owns ALL THREE
 * display-column consumers — the epics block (:866 family), the health
 * bounded-window anchor, and the silent-running gate — not just the reported
 * symptom.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261025-13/sc_metrics_machine_timestamps.mjs (cwd=repo root)
 * node missing = ENV_FAIL exit 2.
 */
import { withRepoStub, callMetricsV2, makeChecker, laneTicket, NOW, DAY, WF_DEV } from '../t261021-06/lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

// V8's year-2001 trap, computed here so the assertion names the exact invented
// value family (no hardcoded magic): a display string without a year parses to 2001.
const DISPLAY = '10-25 22:17'
const TRAP_MS = new Date(DISPLAY).getTime()
const isTrap = (v) => v !== null && typeof v === 'number' && v > 0 && new Date(v).getUTCFullYear() === 2001

const sec = (ms) => Math.round(ms / 1000)
// Live-shaped row: BOTH columns present, exactly as the engine's ticket list writes them.
const liveRow = (id, epic, updatedTsSec, extra = {}) => laneTicket(id, `lane-${id}`, {
  createdAt: NOW - 10 * DAY,
  closedAt: NOW - 1 * DAY,
  epic,
  updated: DISPLAY,
  timeline: [
    { at: new Date(NOW - 10 * DAY).toISOString(), stage: 'plan', state: 'running' },
    { at: new Date(NOW - 1 * DAY).toISOString(), stage: 'code', state: 'closed' },
  ],
  extra: { updated_ts: updatedTsSec, updated_display_note: 'display column, never a timestamp', ...extra },
})

// ---- T1/T2: the epics block reads the machine field, never the display string ----
await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [
      liveRow('t13-a1', 'epic-alpha', sec(NOW - 1 * DAY)),
      liveRow('t13-a2', 'epic-alpha', sec(NOW - 2 * DAY)),
      liveRow('t13-b1', 'epic-beta', sec(NOW - 3 * DAY)),
      // T2 family: `updated` present, machine field broken in every declared way.
      liveRow('t13-bad1', 'epic-gamma', sec(NOW - 1 * DAY), { updated_ts: undefined }),
      liveRow('t13-bad2', 'epic-delta', sec(NOW - 1 * DAY), { updated_ts: 'garbage' }),
      liveRow('t13-bad3', 'epic-eps', sec(NOW - 1 * DAY), { updated_ts: -5 }),
      liveRow('t13-bad4', 'epic-zet', sec(NOW - 1 * DAY), { updated_ts: 0 }),
    ],
    epics: ['epic-alpha', 'epic-beta', 'epic-gamma', 'epic-delta', 'epic-eps', 'epic-zet'],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r.status === 200, 'front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const epics = Array.isArray(r.body?.epics) ? r.body.epics : []
    const byEpic = Object.fromEntries(epics.map((e) => [e.epic, e]))

    // T1 — healthy epics: last_activity_ms IS updated_ts*1000 (max over the epic's rows).
    ok(byEpic['epic-alpha']?.last_activity_ms === sec(NOW - 1 * DAY) * 1000,
      'T1 epic-alpha last_activity_ms = machine updated_ts (ms), not the display parse',
      `got ${byEpic['epic-alpha']?.last_activity_ms}`)
    ok(byEpic['epic-beta']?.last_activity_ms === sec(NOW - 3 * DAY) * 1000,
      'T1 epic-beta last_activity_ms = its row updated_ts in ms', `got ${byEpic['epic-beta']?.last_activity_ms}`)

    // T1b — the invented-value family is absent from EVERY epic row: the V8 2001
    // parse of the display string must not appear, in any form.
    const payload = JSON.stringify(r.body)
    ok(!payload.includes(String(TRAP_MS)), `T1b the display-string 2001 parse (${TRAP_MS}) appears nowhere in the payload`, 'found')
    for (const e of epics) {
      ok(!isTrap(e.last_activity_ms), `T1b epic ${e.epic} last_activity_ms is not a year-2001 value`, `got ${e.last_activity_ms}`)
    }

    // T2 — every broken-machine-field epic degrades to null WITH a reason, never 2001.
    for (const epic of ['epic-gamma', 'epic-delta', 'epic-eps', 'epic-zet']) {
      const e = byEpic[epic]
      ok(e?.last_activity_ms === null, `T2 ${epic}: missing/garbage/negative/0 updated_ts degrades to null`, `got ${e?.last_activity_ms}`)
      ok(typeof e?.reason === 'string' && e.reason.length > 0, `T2 ${epic}: the degrade is named (reason present)`, `reason=${e?.reason}`)
    }
  },
)

// ---- T3: the health view's bounded-window counts anchor on updated_ts ----
await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [
      liveRow('t13-h1', '', sec(NOW - 1 * DAY)),
      liveRow('t13-h2', '', sec(NOW - 6 * DAY)),
      liveRow('t13-old', '', sec(NOW - 200 * DAY)),
      // display column only, no machine field — excluded, never fabricated into the window
      laneTicket('t13-noT', 'lane-nt', { createdAt: NOW - 1 * DAY, updated: DISPLAY, timeline: [] }),
    ],
    epics: [],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'health', window: '7d' })
    ok(r.status === 200, 'T3 health front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const k = r.body?.kpis ?? {}
    ok(k.tickets === 2, `T3 bounded window counts the two updated_ts-anchored rows (got ${k.tickets})`, `tickets=${k.tickets}`)
    ok(k.closed === 2, `T3 closed count follows the same machine anchor (got ${k.closed})`, `closed=${k.closed}`)
  },
)

// ---- T4: silent-running fires on the machine field, never on a fabricated 2001 value ----
process.env.SANDBAR_METRICS_SILENT_MIN = '1'
await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [
      // running, machine field says 3h ago (over the 1min threshold) → silent, named
      // health view buckets by stage_state — a running lane ticket carries it
      laneTicket('t13-silent', 'lane-s', {
        createdAt: NOW - 1 * DAY,
        updated: DISPLAY,
        extra: { stage_state: 'running', updated_ts: sec(NOW - 3 * 3600e3) },
      }),
      laneTicket('t13-noT', 'lane-nt', { createdAt: NOW - 1 * DAY, updated: DISPLAY, timeline: [], extra: { stage_state: 'running' } }),
    ],
    epics: [],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'health', window: 'all' })
    ok(r.status === 200, 'T4 health front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const body = JSON.stringify(r.body)
    ok(body.includes('"t13-silent"') || body.includes('t13-silent'),
      'T4 a running ticket silent by updated_ts is named in the charts face', 'not found')
    ok(!body.includes('"t13-noT"'),
      'T4 a display-only running row never fabricates a silent entry (the 2001 anchor is dead)', 'found — fabrication')
  },
)

process.exit(done('sc_metrics_machine_timestamps'))
