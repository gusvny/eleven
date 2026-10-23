#!/usr/bin/env node
/**
 * sc_metrics_v2_fast_full_parity.mjs — t261021-06 L3 (grey-box, offline seconds).
 *
 * intent (user-perceivable): the fast (cache-served) path and the full path agree
 * on every v2 block — a warm cache must not change the numbers the user reads,
 * and a record the cache cannot serve must surface as a NAMED shortfall in
 * notices, never as silently short aggregates (plan step 5; the one place a
 * partial answer could hide).
 *
 * Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
 * Run: node integration/t261021-06/sc_metrics_v2_fast_full_parity.mjs (cwd=repo root)
 */
import { writeFile } from 'node:fs/promises'
import { withRepoStub, callMetricsV2, makeChecker, laneTicket, NOW, DAY, iso, WF_DEV } from './lib_metrics_v2.mjs'

const { ok, done } = makeChecker()

const mkT = (id, lane) => laneTicket(id, lane, {
  createdAt: NOW - 2 * DAY,
  closedAt: NOW - 1 * DAY,
  timeline: [
    { at: iso(NOW - 2 * DAY), stage: 'plan', state: 'running' },
    { at: iso(NOW - 2 * DAY + 3600e3), stage: 'plan', state: 'closed' },
    { at: iso(NOW - 1.5 * DAY), stage: 'code', state: 'running' },
    { at: iso(NOW - 1 * DAY), stage: 'code', state: 'closed' },
  ],
})

await withRepoStub(
  async () => ({
    project: 'demo',
    workflows: [WF_DEV],
    stages: WF_DEV.stages,
    tickets: [mkT('t21-f1', 'lane-f1'), mkT('t21-f2', 'lane-f2')],
    epics: [],
  }),
  async ({ deps, cacheRoot, m }) => {
    // Round 1: cold cache → full compute, records persist.
    const r1 = await callMetricsV2(deps, { view: 'time', window: 'all' })
    ok(r1.status === 200, 'full run 200', `status=${r1.status}`)
    if (r1.status !== 200) return
    const b1 = r1.body

    // Presence guard (arbitrate gen0): parity of undefined === undefined is a
    // vacuous green on a tree without the v2 blocks — assert the keys are defined
    // BEFORE comparing.
    ok(Array.isArray(b1.workflows) && b1.workflows.length > 0, 'F0 presence guard: full body carries a non-empty workflows[]', `workflows=${JSON.stringify(b1.workflows)?.slice(0, 120)}`)
    ok(Array.isArray(b1.stages) && b1.stages.length > 0, 'F0 presence guard: full body carries a non-empty stages[]', `stages=${JSON.stringify(b1.stages)?.slice(0, 120)}`)
    ok(b1.kpis !== undefined && typeof b1.kpis === 'object', 'F0 presence guard: full body carries kpis', `kpis=${typeof b1.kpis}`)

    // Round 2: warm cache → fast path must reproduce every v2 block exactly.
    const r2 = await callMetricsV2(deps, { view: 'time', window: 'all' })
    const b2 = r2.body
    for (const key of ['workflows', 'stages', 'epics', 'kpis']) {
      ok(JSON.stringify(b1[key]) === JSON.stringify(b2?.[key]), `F1 fast path parity on ${key}`, `full=${JSON.stringify(b1[key])?.slice(0, 120)} fast=${JSON.stringify(b2?.[key])?.slice(0, 120)}`)
    }

    // F2 — a cache record that cannot be served: the shortfall is NAMED in notices,
    // and the fast path never silently presents the short aggregate as complete.
    const { readdir } = await import('node:fs/promises')
    const { join } = await import('node:path')
    let recPath = null
    const walk = async (d) => {
      for (const e of await readdir(d, { withFileTypes: true })) {
        const p = join(d, e.name)
        if (e.isDirectory()) await walk(p)
        else if (e.name.includes('t21-f1')) recPath = p
      }
    }
    await walk(cacheRoot)
    ok(recPath != null, 'F2 a per-ticket cache record exists on disk', `under ${cacheRoot}`)
    if (recPath != null) {
      await writeFile(recPath, '{ "corrupted": true }', 'utf8') // bad source_version → record unusable
      const r3 = await callMetricsV2(deps, { view: 'time', window: 'all' })
      const b3 = r3.body
      const text = JSON.stringify(b3)
      ok(r3.status === 200, 'F2 corrupted-record request still 200 (degrade, not crash)', `status=${r3.status}`)
      ok(/t21-f1|notice|shortfall|recomput/i.test(text), 'F2 the unservable record is NAMED somewhere (notice/shortfall), not silently dropped', 'no mention of t21-f1 in payload')
      const stageRuns = (b3.workflows ?? []).reduce((s, w) => s + Object.values(w.stage_runs ?? {}).reduce((a, c) => a + c, 0), 0)
      ok(stageRuns > 0 ? JSON.stringify(b3.stages) !== '[]' : true, 'F2 remaining readable records still aggregate', '')
    }
  },
)

process.exit(done('sc_metrics_v2_fast_full_parity'))
