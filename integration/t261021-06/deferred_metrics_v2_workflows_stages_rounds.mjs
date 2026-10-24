#!/usr/bin/env node
/**
 * sc_metrics_v2_workflows_stages_rounds.mjs — t261021-06 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable): the Metrics tab's new per-workflow and per-stage rows
 * answer "how many times did each stage run" without mixing workflow chains.
 * Contract (ticket item 1/2): workflows[] carries per-workflow tickets, elapsed_ms
 * (the same stage windows the time view sums), stage_runs and rounds_per_ticket;
 * stages[] is keyed (workflow, stage) — a stage id shared by two workflows must
 * produce two independent rows, never one merged row. rounds_per_ticket counts
 * every execution of a stage for one ticket (rework re-entry included).
 *
 * Fault surfaces: KI-019 (timeline entries carry no generation dimension and may
 * arrive out of order) — an out-of-order timeline must not change the counts.
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_workflows_stages_rounds.mjs (cwd=repo root)
 */
import { withRepoStub, callMetricsV2, makeChecker, laneTicket, NOW, DAY, iso, WF_DEV, WF_HOTFIX } from './lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

// Population: dev-lane tA reaches code twice (rework re-entry); tB stops at plan.
// hotfix tC runs plan and code once each. Stage id `plan` exists in BOTH workflows.
const tA = laneTicket('t21-a', 'lane-a', {
  createdAt: NOW - 3 * DAY,
  closedAt: NOW - 1 * DAY,
  timeline: [
    { at: iso(NOW - 3 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 3 * DAY + 3600e3), stage: 'plan', state: 'closed' },
    { at: iso(NOW - 2 * DAY), stage: 'code', state: 'running' },
    { at: iso(NOW - 2 * DAY + 3600e3), stage: 'code', state: 'closed' },
    { at: iso(NOW - 1.5 * DAY), stage: 'code', state: 'running' }, // rework re-entry
    { at: iso(NOW - 1 * DAY), stage: 'code', state: 'closed' },
  ],
})
const tB = laneTicket('t21-b', 'lane-a', {
  createdAt: NOW - 2 * DAY,
  timeline: [
    { at: iso(NOW - 2 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 2 * DAY + 1800e3), stage: 'plan', state: 'closed' },
  ],
})
const tC = laneTicket('t21-c', 'lane-c', {
  workflow: 'hotfix',
  createdAt: NOW - 1 * DAY,
  timeline: [
    { at: iso(NOW - 1 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 1 * DAY + 900e3), stage: 'plan', state: 'closed' },
    { at: iso(NOW - 1 * DAY + 3600e3), stage: 'code', state: 'running' },
  ],
})
// KI-019 injection: same history as tA but entries in scrambled order — counts must not move.
const tD = laneTicket('t21-d', 'lane-d', {
  createdAt: NOW - 3 * DAY,
  closedAt: NOW - 1 * DAY,
  timeline: [
    { at: iso(NOW - 1 * DAY), stage: 'code', state: 'closed' },
    { at: iso(NOW - 3 * DAY + 3600e3), stage: 'plan', state: 'closed' },
    { at: iso(NOW - 1.5 * DAY), stage: 'code', state: 'running' },
    { at: iso(NOW - 3 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 2 * DAY + 3600e3), stage: 'code', state: 'closed' },
    { at: iso(NOW - 2 * DAY), stage: 'code', state: 'running' },
  ],
})

process.exitCode = await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV, WF_HOTFIX],
    stages: WF_DEV.stages,
    tickets: [tA, tB, tC, tD],
    epics: [],
  }),
  async ({ deps }) => {
    const r = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r.status === 200, 'front door 200', `status=${r.status}`)
    if (r.status !== 200) return
    const b = r.body

    const wf = Array.isArray(b.workflows) ? b.workflows : []
    const byWf = Object.fromEntries(wf.map((w) => [w.workflow ?? w.id, w]))
    const stages = Array.isArray(b.stages) ? b.stages : []
    const byPair = Object.fromEntries(stages.map((s) => [`${s.workflow ?? s.id?.[0] ?? '?'}|${s.stage ?? s.id?.[1] ?? '?'}`, s]))

    // W1 — per-workflow rows exist for both workflows, tickets counted per chain.
    ok(wf.length >= 2, `W1 workflows[] carries both chains (${wf.map((w) => w.workflow ?? w.id).join(',')})`)
    ok((byWf['dev-lane']?.tickets ?? -1) === 3, 'W1 dev-lane tickets=3', `got ${byWf['dev-lane']?.tickets}`)
    ok((byWf['hotfix']?.tickets ?? -1) === 1, 'W1 hotfix tickets=1', `got ${byWf['hotfix']?.tickets}`)

    // W2 — workflows[].stage_runs is the workflow's TOTAL execution count (a scalar
    // sum over records — the per-stage split lives in stages[]). dev-lane: plan 3
    // (tA,tB,tD) + code 4 (tA x2 rework, tD x2) = 7.
    ok(byWf['dev-lane']?.stage_runs === 7, 'W2 dev-lane stage_runs total = 7 (plan 3 + code 4, rework re-entry counts)', JSON.stringify(byWf['dev-lane']?.stage_runs))
    ok((byPair['dev-lane|plan']?.runs ?? -1) === 3 && (byPair['dev-lane|code']?.runs ?? -1) === 4, 'W2 stages[] splits the runs per stage (plan 3 / code 4)', `${byPair['dev-lane|plan']?.runs}/${byPair['dev-lane|code']?.runs}`)

    // W3 — rounds_per_ticket = total stage_runs / tickets with readable history (7/3).
    ok(Math.abs((byWf['dev-lane']?.rounds_per_ticket ?? -1) - 7 / 3) < 5e-3, 'W3 dev-lane rounds_per_ticket = 7/3', JSON.stringify(byWf['dev-lane']?.rounds_per_ticket))

    // W4 — stages[] keyed (workflow, stage): shared stage id stays two rows, never mixed.
    ok((byPair['dev-lane|plan']?.runs ?? -1) === 3, 'W4 stages[dev-lane,plan].runs=3', JSON.stringify(byPair['dev-lane|plan']))
    ok((byPair['hotfix|plan']?.runs ?? -1) === 1, 'W4 stages[hotfix,plan].runs=1 (chain not mixed into dev-lane)', JSON.stringify(byPair['hotfix|plan']))

    // W5 — avg_rounds_per_ticket denominator = tickets that REACHED the stage (tB never reached code).
    ok(Math.abs((byPair['dev-lane|code']?.avg_rounds_per_ticket ?? -1) - 2) < 1e-9, 'W5 avg_rounds[dev-lane,code]=2 (runs 4 / 2 tickets reached)', JSON.stringify(byPair['dev-lane|code']))

    // W6 — elapsed_ms is the same stage-window sum the time view uses: workflows elapsed equals the sum of its stage rows.
    const devElapsed = (byPair['dev-lane|plan']?.elapsed_ms ?? 0) + (byPair['dev-lane|code']?.elapsed_ms ?? 0) + (byPair['dev-lane|review']?.elapsed_ms ?? 0)
    ok((byWf['dev-lane']?.elapsed_ms ?? -1) === devElapsed, 'W6 workflows.elapsed_ms = sum of its stages[].elapsed_ms', `wf=${byWf['dev-lane']?.elapsed_ms} sum=${devElapsed}`)

    // W7 — KI-019: out-of-order timeline yields identical counts (deterministic across calls).
    const dPair = stages.find((s) => (s.workflow ?? s.id?.[0]) === 'dev-lane' && s.stage === 'code')
    ok((dPair?.runs ?? 0) === 4, 'W7 out-of-order timeline (KI-019) counts identically (dev-lane code total still 4)', `runs=${dPair?.runs}`)
    const r2 = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(JSON.stringify(r2.body?.stages) === JSON.stringify(b.stages), 'W7 two calls agree byte-for-byte on stages[]')
  },
)

process.exit(done('sc_metrics_v2_workflows_stages_rounds'))
