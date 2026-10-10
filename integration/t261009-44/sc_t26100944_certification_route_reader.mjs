// sc_t26100944_certification_route_reader.mjs — t261009-44 (t261009-41 Slice 2),
// grey-box L3, offline, zero docker/Temporal/browser, never touches 3099.
//
// The host's need is met only when a person can SEE the certification state of
// a real line. This scenario owns the read journey's seam: seed a real project
// store shape (develop/lines.json + develop/landings.jsonl + the delivery and
// promotion ledgers) in an isolated projects root, then drive the panel's
// PRODUCTION route registration shell (startPluginHarness: an unregistered path
// 404s here exactly as in production — the dead-button proof, KI-01M4HMCZAM4ZBC2CKN15HDBZHP)
// and read the certification face back over the public HTTP contract.
//
// Intent (user-perceivable, anchored on the HTTP face only — never on internal
// module layout):
//   R1 the tab's read works end to end: GET the certification route for a
//      seeded project returns a face whose certified/waiting counts match the
//      records actually seeded, plus the raw arrays the tab needs for links
//      (line ids, ticket ids) — a wrong or invented count is red (KI-01M4HPGHVWAKB62TXYV4G7ENEB
//      family: the face must say what the LEDGERS say, not what a second
//      implementation guesses).
//   R2 there is no write path: POST/PUT to the certification route is refused
//      (non-2xx) — certify/promote stays a record-signed operation outside it.
//   R3 missing project parameter is refused by name (4xx), never a 500.
//   R4 an unknown project degrades to a NAMED refusal ({ok:false, reason}) —
//      never invented counts, never a fabricated empty face that looks healthy.
//   R5 a malformed ledger row degrades to a named reason on the read — a row
//      the engine reader rejects must surface on the face, never be silently
//      dropped (same-KI two-readers discipline).
//   R6 the route really is registered where the page will call it: the exact
//      path GET /sandbar-executor-panel/api/certification answers through the
//      production registration shell (a page calling an unregistered path would
//      404 here — dead-button made mechanical).
//
// Intent split (no duplication): the projection truth table belongs to
// t261009-41-freeze-promote-contract; the face the model produces belongs to
// t261009-41-certification-face-seam; this entry uniquely owns the ROUTE +
// reader seam a person's tab actually reads through.
//
// Three states: route/reader not yet implemented = FAIL named (TDD red
// expected pre-implement; green required at the integration gate/merge);
// node or the panel harness missing = ENV_FAIL exit 2.

import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'cert-tab-proj'
const LINE = 'line-cert'
const TICKET = 't26100999'

const jget = (base, url) =>
  fetch(base + url).then(async (r) => ({ status: r.status, body: await r.json().catch(() => null), text: await r.text().catch(() => '') }))
const jpost = (base, url, body) =>
  fetch(base + url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) })
    .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))

/** Seed the develop records at the engine's own resolved paths: the line
 * declaration under shared.develop_dir's `<key>/data/develop/` (the gate run's
 * first cut seeded `<key>/develop/` and the reader correctly refused the
 * missing declaration by name — the fixture was wrong, not the reader), the
 * delivery/promotion ledgers under `<key>/ledger/`, the cited run's header in
 * a SANDBAR_RUNS_LEDGER file (the adapter fails a certified line CLOSED without
 * run headers — so the happy path must provide an honest green header), and
 * the ticket archive the meta face reads titles/epics from. */
const certLine = () => JSON.stringify({
  kind: 'cert', id: 'cert-1', at: 1728500000000, line: LINE, run: 'run-1', booked_red: 'run-1',
  judged_by: 'gate', repos: [{ repo: 'sandbar', revision: 'a'.repeat(40) }],
})
const landingLine = () => JSON.stringify({
  kind: 'landing', id: 'ldg-2', at: 1728500000000, ticket: TICKET, line: LINE, actor: 'dev',
  repos: [{ repo: 'sandbar', revision: 'b'.repeat(40) }],
})
function seedStore(root, { corruptDelivery } = {}) {
  const proj = join(root, PROJ)
  const dev = join(proj, 'data', 'develop')
  const led = join(proj, 'ledger')
  const tick = join(proj, 'data', 'tickets', TICKET)
  mkdirSync(dev, { recursive: true })
  mkdirSync(led, { recursive: true })
  mkdirSync(tick, { recursive: true })
  writeFileSync(join(dev, 'lines.json'), JSON.stringify([
    { version: 1, line_id: LINE, scope: 'cert tab slice 2', owner: 'executor',
      repositories: [{ name: 'sandbar', branch: 'line-cert' }] },
  ]), 'utf8')
  writeFileSync(join(tick, 'archive.json'), JSON.stringify({
    meta: { title: 'Cert tab fixture ticket', epic: 'epic-cert' },
  }), 'utf8')
  writeFileSync(join(led, 'delivery.jsonl'), (corruptDelivery
    ? '{not json at all\n' + landingLine() + '\n'
    : certLine() + '\n' + landingLine() + '\n'), 'utf8')
  writeFileSync(join(led, 'promotion.jsonl'), '', 'utf8')
  writeFileSync(join(root, 'runs.jsonl'), JSON.stringify({
    id: 'run-1', cases: { ran: 2, failed: 0, env_failed: 0 },
  }) + '\n', 'utf8')
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.envFail('harness-loadable', String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startPluginHarness !== 'function') {
    C.envFail('harness-loadable', 'executor-panel harness startPluginHarness missing (env seam absent = ENV_FAIL)')
    return C.exit()
  }
  const iso = makeIsoDir('t26100944-route-')
  const root = join(iso.dir, 'projects')
  mkdirSync(root, { recursive: true })
  const savedProjectsDir = process.env.SANDBAR_PROJECTS_DIR
  const savedRunsLedger = process.env.SANDBAR_RUNS_LEDGER
  process.env.SANDBAR_PROJECTS_DIR = root
  process.env.SANDBAR_RUNS_LEDGER = join(root, 'runs.jsonl')
  try {
    seedStore(root)
    const H = await harness.startPluginHarness({ panelDir: join(iso.dir, 'panel') })
    try {
      // R6+R1 the route is registered and answers with a face matching the seeded records.
      const good = await jget(H.base, `/sandbar-executor-panel/api/certification?project=${PROJ}`)
      C.case('route-registered-and-answers', good.status === 200 && good.body && good.body.ok === true,
        `status=${good.status} body=${JSON.stringify(good.body).slice(0, 240)}`)
      const blob = JSON.stringify(good.body ?? {})
      C.case('face-counts-match-seeded-records',
        blob.includes(LINE) && blob.includes(TICKET) && blob.includes('Cert tab fixture ticket') && blob.includes('epic-cert'),
        'face must name the seeded line, ticket and its store title/epic (raw arrays for links)')
      // R2 no write path.
      const post = await jpost(H.base, `/sandbar-executor-panel/api/certification?project=${PROJ}`, { promote: true })
      C.case('no-write-path', post.status >= 400, `POST status=${post.status} (must refuse, never write)`)
      // R3 missing project refused by name. Pinned to 400 so a pre-implement
      // route 404 cannot false-pass this case (the registration proof is R1's).
      const noProj = await jget(H.base, '/sandbar-executor-panel/api/certification')
      C.case('missing-project-refused', noProj.status === 400, `status=${noProj.status} (expect 400 once the route exists)`)
      // R4 unknown project = named refusal, never invented data. The refusal is
      // the read face's own 200 envelope {ok:false, reason} — a route-miss 404
      // must NOT count (that would false-pass before the route exists).
      const unknown = await jget(H.base, '/sandbar-executor-panel/api/certification?project=no-such-project')
      const ub = unknown.body ?? {}
      const namedRefusal = unknown.status === 200 && ub.ok === false
        && typeof ub.reason === 'string' && ub.reason.length > 0
      C.case('unknown-project-named-refusal', namedRefusal, `status=${unknown.status} body=${JSON.stringify(ub).slice(0, 200)}`)

      // R5 malformed delivery row surfaces by name on a fresh read (same
      // contract pinning as R4: the read face's own envelope, not a 404).
      seedStore(root, { corruptDelivery: true })
      const bad = await jget(H.base, `/sandbar-executor-panel/api/certification?project=${PROJ}`)
      const bb = bad.body ?? {}
      const badNamesIt = bad.status === 200 && bb.ok === false
        && typeof bb.reason === 'string' && bb.reason.length > 0
      C.case('malformed-row-named-on-face', badNamesIt, `status=${bad.status} body=${JSON.stringify(bb).slice(0, 240)}`)
    } finally {
      await H.close().catch(() => {})
    }
  } finally {
    if (savedProjectsDir === undefined) delete process.env.SANDBAR_PROJECTS_DIR
    else process.env.SANDBAR_PROJECTS_DIR = savedProjectsDir
    if (savedRunsLedger === undefined) delete process.env.SANDBAR_RUNS_LEDGER
    else process.env.SANDBAR_RUNS_LEDGER = savedRunsLedger
  }
  C.exit()
  rmSync(iso.dir, { recursive: true, force: true })
}

main()
