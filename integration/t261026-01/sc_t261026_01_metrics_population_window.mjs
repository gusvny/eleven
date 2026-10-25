#!/usr/bin/env node
/**
 * sc_t261026_01_metrics_population_window.mjs — t261026-01, grey-box L3 (the
 * ticket's headline invariant over the metrics face), offline seconds, zero
 * docker/Temporal-server/browser, never touches 3099/7233.
 *
 * intent (user-perceivable; host challenge 261025 — 'sandbar had only 41 tickets
 * in the last 31 days - are you sure?'): the metrics ticket totals are a WINDOW
 * count of the project, not a template-filter artifact. The user moves the
 * window and the number moves; every era of the store is counted; the chain
 * really unknown is degraded BY NAME, never dropped, never invented:
 *   B1 window=all: kpis.tickets counts EVERY listed row — legacy era, chain-less
 *      and other-template rows included (project-level totals, round-2 c2);
 *   B2 window moves the count: the 40-day-old legacy row is counted at 30d/all
 *      and not at 7d (the cut is no longer made before the window);
 *   B3 chain-less rows are excluded from the chain-based blocks and the
 *      exclusion is NAMED in the face's notices (counted degrade);
 *   B4 the template filter lives only in the chain blocks: with template=dev-lane
 *      the totals still include the quickmanual-lane row;
 *   B5 the delta vs the on-disk archive store is NAMED in notices (the ticket's
 *      invariant alternative branch; ghost archive outside list+cache universe);
 *   B6 the invariant is scoped: with epic=<code> the totals are that epic's
 *      window subset, with epic=all the whole project (round-2 Delta 2);
 *   B7 a malformed archive in the store degrades the population path by name —
 *      the face still answers, totals unchanged, no throw/5xx;
 *   B8 nothing is invented: no chain block ever grows an entry for the
 *      chain-less rows.
 *
 * Pre-implement tree red (TDD signal): B1..B8 red while the face still filters
 * the population by template. Green required at the integration gate / merge.
 * Workbench metrics sources absent = ENV_FAIL exit 2.
 */
import {
  DAY, NOW, iso, WORKFLOWS, ticketRow, withStub, callMetrics, makeChecker,
} from '../t260903-09/lib_integration.mjs'
import { writeArchive, withTicketsRoot, freshTmp, rmRf } from './lib_t261026.mjs'

const { ok, envFail, done } = makeChecker()
const NAME = 't261026-01-metrics-population-window'

// Population design (created anchors, days before NOW):
//   t-leg-old  legacy dev-lane, 40d   (outside 7d, inside 30d/all)
//   t-leg-new  legacy dev-lane, 1d
//   t-chainless  no workflow anywhere, 2d   (the named-degrade row)
//   t-quick    quickmanual-lane, 3d     (other template — totals, not dev chain)
//   t-dev      dev-lane, 5d
//   t-noarch   dev-lane row, 6d, NO archive on disk (listed side of the universe)
//   t-ghost    archive ONLY (2d), not listed, no cache record -> store-side delta 1
const ts = (d) => NOW - d * DAY
const legacyExtra = { workflow: '', created: null, updated: '', lane_version: '' }
const stub = {
  project: 'demo',
  epics: ['ep-a', 'ep-b'],
  workflows: [...WORKFLOWS, { id: 'quickmanual-lane', name: 'quickmanual-lane', stages: [{ id: 'plan', exit: 'human' }] }],
  tickets: [
    ticketRow('t-leg-old', { createdAt: ts(40), closedAt: ts(39), extra: { ...legacyExtra, timeline: [], epic: 'ep-b' } }),
    ticketRow('t-leg-new', { createdAt: ts(1), closedAt: null, extra: { ...legacyExtra, timeline: [], epic: 'ep-b' } }),
    ticketRow('t-chainless', { createdAt: ts(2), closedAt: ts(2), extra: { ...legacyExtra, timeline: [], epic: 'ep-b' } }),
    ticketRow('t-quick', { createdAt: ts(3), closedAt: ts(3), extra: { workflow: 'quickmanual-lane', epic: 'ep-a' } }),
    ticketRow('t-dev', { createdAt: ts(5), closedAt: null, extra: { epic: 'ep-a' } }),
    ticketRow('t-noarch', { createdAt: ts(20), closedAt: null, extra: { epic: 'ep-a' } }),
  ],
}

let metrics = null
try {
  metrics = await import(new URL('../../server/plugins/workbench/src/host/metrics.ts', import.meta.url).href)
} catch (e) {
  envFail('B0 production metrics module importable', String(e).slice(0, 160))
}
if (metrics) {
  const root = await freshTmp('t261026b')
  try {
    // Store: 7 archives (6 matching listed ids except t-noarch, plus t-ghost), 1 malformed.
    await writeArchive(root, 'demo', 't-leg-old', { created: Math.floor(ts(40) / 1000), workflow_id: 'dev-lane', lane_version: 'legacy-v1' })
    await writeArchive(root, 'demo', 't-leg-new', { created: Math.floor(ts(1) / 1000), workflow_id: 'dev-lane', lane_version: 'legacy-v1' })
    await writeArchive(root, 'demo', 't-chainless', { created: Math.floor(ts(2) / 1000), workflow_id: '', lane_version: 'legacy-v1' })
    await writeArchive(root, 'demo', 't-quick', { created: Math.floor(ts(3) / 1000), workflow_id: 'quickmanual-lane', lane_version: null })
    await writeArchive(root, 'demo', 't-dev', { created: Math.floor(ts(5) / 1000), workflow_id: 'dev-lane', lane_version: null })
    await writeArchive(root, 'demo', 't-ghost', { created: Math.floor(ts(2) / 1000), workflow_id: 'dev-lane', lane_version: null })
    await writeArchive(root, 'demo', 't-bad', null, '{"meta": {"created"')

    await withStub(stub, ({ deps }) => withTicketsRoot(root, async () => {
      const all = await callMetrics(deps, { view: 'time', window: 'all' })
      ok(all.status === 200, 'B0 window=all answers 200 (fixture sanity)', `status ${all.status}`)
      const kAll = all.body?.kpis?.tickets
      ok(kAll === 6, 'B1 window=all totals count EVERY listed row (legacy + chain-less + other template), project-level', `got ${kAll}`)

      const w7 = await callMetrics(deps, { view: 'time', window: '7d' })
      const w30 = await callMetrics(deps, { view: 'time', window: '30d' })
      ok(w7.body?.kpis?.tickets === 4, 'B2 window=7d counts the 4 rows created inside 7d (the 20d and 40d rows out)', `got ${w7.body?.kpis?.tickets}`)
      ok(w30.body?.kpis?.tickets === 5, 'B2b window=30d counts 5 (the 20d row in, the 40d row still out; window MOVES the count)', `got ${w30.body?.kpis?.tickets}`)
      ok(!(kAll === w7.body?.kpis?.tickets && w7.body?.kpis?.tickets === w30.body?.kpis?.tickets),
        'B2c the three windows no longer answer one frozen number (the reported artifact)', '')

      const notices = String(all.body?.reason ?? '')
      ok(notices.length > 0 && /exclud/i.test(notices),
        'B3 the chain-less exclusion is named in the face notices', notices.slice(0, 200))
      ok(/1 tickets? in the ticket store \(data\/tickets\) are absent/.test(notices),
        'B5 the delta vs the archive store is named (store holds t-ghost, universe holds 6 -> delta 1)', notices.slice(0, 300))

      const wfDump = JSON.stringify(all.body?.workflows ?? all.body?.blocks ?? {})
      ok(!/"workflow"\s*:\s*""/.test(wfDump), 'B8 no chain block grows an entry for the chain-less rows (nothing invented)', wfDump.slice(0, 160))
      ok(wfDump.includes('quickmanual-lane'), 'B4b chain blocks still see the quickmanual chain on its own entry', '')
      const devEntry = (all.body?.workflows ?? []).find?.((w) => String(w?.workflow ?? w?.id ?? '') === 'dev-lane') ?? null
      ok(devEntry !== null, 'B4a the dev-lane chain block stays present with template=dev-lane (default)', '')

      const devOnly = await callMetrics(deps, { view: 'time', window: 'all', template: 'dev-lane' })
      ok(devOnly.body?.kpis?.tickets === 6,
        'B4 the template filter no longer cuts the TOTALS (quickmanual row still counted under template=dev-lane)', `got ${devOnly.body?.kpis?.tickets}`)

      const epA = await callMetrics(deps, { view: 'time', window: 'all', epic: 'ep-a' })
      ok(epA.body?.kpis?.tickets === 3, 'B6 epic=<code> scopes the totals to that epic subset (3 rows in ep-a)', `got ${epA.body?.kpis?.tickets}`)
      ok(kAll === 6 && epA.body?.kpis?.tickets !== kAll, 'B6b the invariant is scoped, never read as unconditional across epic filters', '')

      const afterBad = await callMetrics(deps, { view: 'time', window: 'all' })
      ok(afterBad.status === 200 && afterBad.body?.kpis?.tickets === 6,
        'B7 a malformed archive degrades by name: face answers, totals unchanged, no throw', `status ${afterBad.status} tickets ${afterBad.body?.kpis?.tickets}`)
    }))
  } finally {
    await rmRf(root)
  }
}
process.exit(done(NAME))
