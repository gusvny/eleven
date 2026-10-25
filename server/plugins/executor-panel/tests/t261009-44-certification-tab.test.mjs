/**
 * t261009-44-certification-tab.test.mjs — the Certification tab's page-shape
 * and mock-reconcile UT (approved mock v15:
 * notes/discussions/261009-executor-certification-tab-mock.html).
 *
 * Review conditions carried here:
 *  - C2a (KI-01M4HMCZAM4ZBC2CKN15HDBZ, "dead button"): the tab's fetch target
 *    is asserted to be EXACTLY a path PANEL_API_ROUTES carries — the client
 *    source text alone is not evidence; the two sets are cross-checked here.
 *  - C3: the rendered-markup assertions sit on structural anchors (the bar's
 *    one boundary, disabled-only-at-zero, the trigger enum, the line <sha>
 *    shape), not on copy strings.
 *
 * The render core under test is the page's OWN implementation: the same
 * buildCertificationCore source the page embeds via String() (single
 * implementation discipline). The face fixtures come from the t261009-41
 * golden fixture through the real deriveCertificationFace.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { PANEL_API_ROUTES } from '../src/host/api.ts'
import { buildCertificationCore, countsCell, roundPill, roundTrigger, roundMeasured, CERT_COPIES } from '../src/host/certification-view.ts'
import { deriveCertificationFace } from '../../workbench/src/client/certification-model.ts'

let n = 0
const ROUTE = '/sandbar-executor-panel/api/certification'

// ---- the golden fixture drives both faces (green variant + the frozen fixture) ----
const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../../workbench/tests/fixtures/t261009-41-certification-fixture.json', import.meta.url)), 'utf8')).input
const frozenFace = deriveCertificationFace(fixture)
assert(frozenFace.ok === true && frozenFace.frozen === true && frozenFace.promotable === 2, 'fixture face: frozen, promotable 2')
const greenInput = { ...fixture, freeze: { frozen: false, episode: null, cause: null, culprit: null, closed_at: null } }
const greenFace = deriveCertificationFace(greenInput)
assert(greenFace.ok === true && greenFace.frozen === false, 'green variant derives')
n += 2

const routeAnswer = (face, line = 'develop-buffer', rf = null) => ({
  ok: true, project: 'proj-x', line, lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
  face, raw: { ...fixture, runs: RF_RUNS }, notes: [],
  round_faces: rf ?? { dir: '/tmp/rounds', rounds: [] },
})

// t261012-03: the rounds-faces fixture the table renders from (the runner's
// own face shape — lib_round_face's documented contract).
const RF_RUNS = [{ id: 'run-a', source: 'scheduled' }, { id: 'run-b', source: 'person' }]
const RF_SECTION = {
  dir: '/tmp/rounds',
  live: { ok: true, face: { run_id: 'run-live', state: 'running', started_at: '2026-10-11T22:13:09Z', counts: { ran: 4, pass: 4, fail: 0, env_fail: 0 }, revision: { sandbar: '353b2479' } } },
  rounds: [
    { run_id: 'run-a', face: { run_id: 'run-a', state: 'done', started_at: '2026-10-11T16:49:00Z', counts: { ran: 10, pass: 8, fail: 2, env_fail: 0 }, outcome: { verdict: 'red', reason: '2 failing scenarios' }, revision: { sandbar: '6efc7b3e' } } },
    { run_id: 'run-b', face: { run_id: 'run-b', state: 'done', started_at: '2026-10-11T14:46:00Z', counts: { ran: 5, pass: 5, fail: 0, env_fail: 0 }, outcome: { verdict: 'green', reason: '' }, revision: { sandbar: '6efc7b3e' } } },
    { run_id: 'run-x', absent: 'terminal face not written' },
  ],
}

// ---- C2a: the tab's fetch target is exactly a registered route path ----
{
  assert(PANEL_PAGE_HTML.includes("'/sandbar-executor-panel/api/certification?project='"),
    'the page fetches the certification route')
  // cross-check: every literal panel API path the page fetches is in the table
  const fetched = [...PANEL_PAGE_HTML.matchAll(/'(\/sandbar-executor-panel\/api\/[a-z/]+)\?/g)].map((m) => m[1])
  const table = new Set(PANEL_API_ROUTES.map((r) => r.path))
  assert(fetched.includes(ROUTE) && table.has(ROUTE),
    'the fetched certification path is in PANEL_API_ROUTES (not a dead button)')
  for (const p of fetched) assert(table.has(p), 'page-fetched path registered: ' + p)
  n += 2 + fetched.length
}

// ---- tab row and wiring anchors ----
{
  assert(PANEL_PAGE_HTML.includes('id="t-certification"'), 'tab radio present')
  assert(PANEL_PAGE_HTML.includes('for="t-certification"'), 'tab label present')
  assert(PANEL_PAGE_HTML.includes('data-tab="certification"'), 'data-tab anchor present')
  assert(PANEL_PAGE_HTML.includes('id="paneCert"'), 'pane section present')
  assert(PANEL_PAGE_HTML.includes("['t-certification','paneCert']"), 'pane is wired into PANES')
  assert(PANEL_PAGE_HTML.includes("'t-certification': loadCertification"), 'the tab carries a lazy loader')
  assert(PANEL_PAGE_HTML.includes('id="certBody"'), 'render mount present')
  n += 7
}

// ---- frozen render: the mock's layout law ----
{
  const html = buildCertificationCore(routeAnswer(frozenFace))
  // t261019-23 (F1): the count-proportional bar is gone; three labelled
  // figures replace it, and no segment scale exists anywhere.
  assert(html.includes('id="certBar"') && html.includes('id="certFigCertified"')
    && html.includes('id="certFigWaiting"') && html.includes('id="certDelivered"'),
    'the figure strip renders (certified / delivered / waiting)')
  assert(!html.includes('linebar') && !html.includes('style="flex:'), 'no proportional bar, no segment scale')
  assert((html.match(/certified \d{4}-\d{2}-\d{2} \d?\d:\d\d/g) ?? []).length === 1, 'exactly one boundary moment on the face (dated)')
  // figures render the numbers; t261019-23 (F7): promotable appears ONCE —
  // on the Promote button only (the certified-not-delivered set and the
  // promotable set are the same set).
  assert(html.includes('<b class="mono">4</b>') && html.includes('<b class="mono">3</b>'), 'the figure numbers render (certified 4 / waiting 3)')
  assert((html.match(/data-promotable=/g) ?? []).length === 1, 'promotable renders exactly once')
  // t261019-23 rework (F7): the WORD appears once too — no second occurrence
  // in ids, titles or copy (integration scenario F7.1 counts it verbatim).
  // Judged on a title-blanked face: ticket titles are DATA and may legally
  // contain the word.
  const bare = { ...frozenFace, certified: frozenFace.certified.map((c) => ({ ...c, title: '' })), waiting: frozenFace.waiting.map((w) => ({ ...w, title: '' })) }
  assert(buildCertificationCore(routeAnswer(bare)).split('Promote').length - 1 === 1, 'the word Promote appears exactly once on the chrome (data titles excluded)')
  assert(!/Tally|tally/.test(html), 'no tally row exists (counts appear once)')
  // Promote disabled only at zero: promotable 2 stays alive through the freeze
  assert(html.includes('data-promotable="2"') && !html.includes('id="certPromo" disabled'), 'Promote stays alive through a freeze (promotable 2)')
  // trigger enum: only auto|manual, joined from the headers the tab carries
  assert(roundTrigger(RF_RUNS, 'run-a') === 'auto' && roundTrigger(RF_RUNS, 'run-b') === 'manual', 'trigger joins the headers by run id')
  assert(roundTrigger(RF_RUNS, 'run-none') === '—', 'an unknown run renders the em-dash, never a guessed trigger')
  // t261012-03: the table renders the PUBLISHED FACES, not a projection
  const rfHtml = buildCertificationCore(routeAnswer(frozenFace, 'develop-buffer', RF_SECTION))
  assert(rfHtml.includes('data-round-link="run-live"') && rfHtml.includes('data-round-link="run-a"'), 'the live face leads and the terminal faces follow')
  assert(rfHtml.includes('<td>auto</td>') && rfHtml.includes('<td>manual</td>'), 'trigger words render per row')
  // t261019-23 (F5): the fixture's engine face says roundState idle, so the
  // live running face reads STALE with its (absent) write time named — never
  // a bare 'running'.
  assert(rfHtml.includes('>stale · no write since write time unreadable<'), 'a running face the engine does not back reads stale, never bare running')
  assert(!rfHtml.includes('>running<'), 'no bare running pill anywhere in the table')
  // ...and when the engine DOES report a running round, the pill carries the
  // face's own last-write moment.
  const liveHtml = buildCertificationCore(routeAnswer({ ...frozenFace, roundState: 'running' }, 'develop-buffer', RF_SECTION))
  assert(liveHtml.includes('>running · last write write time unreadable<'), 'a backed running pill names its last-write moment')
  assert(rfHtml.includes('data-k="red"') && rfHtml.includes('data-k="green"'), 'terminal verdicts render their own pill keys')
  assert(rfHtml.includes(countsCell({ pass: 8, fail: 2, env_fail: 0 }, '')), 'the labelled counts render')
  assert(rfHtml.includes('terminal face not written'), 'a run dir without its face names the absence, never zeros')
  assert(rfHtml.includes('2 failing scenarios'), 'a red round names its outcome reason')
  assert(roundPill({ state: 'failed', outcome: null }).text === 'could not run', 'a failed state never reads as an outcome word')
  assert(roundPill({ state: 'done', outcome: { verdict: 'no_proof', reason: 'ran nothing' } }).text === 'no proof', 'no_proof renders the none pill')
  assert(roundPill({ state: 'done', outcome: { verdict: 'weird' } }).text === 'unreadable outcome', 'an unknown verdict never reads green')
  // t261019-23 (F6): the measured cell is a labelled short revision
  assert(roundMeasured({ sandbar: '6efc7b3eabcd' }) === 'line sandbar:6efc7b3e' && rfHtml.includes('line sandbar:6efc7b3e'), 'measured renders as line repo:sha8')
  // the one-line freeze banner naming its blockers
  assert(html.includes('id="certBanner"') && html.includes(frozenFace.frozenFace.blockers[0]), 'the freeze banner names its blockers')
  // every ticket row carries id, title and epic
  assert(html.includes('t261009-20') && html.includes('Guard the route change') && html.includes('engine-hardening'), 'waiting rows carry id, title, epic')
  assert(html.includes('t261009-23') && html.includes('Promote the certified part'), 'certified rows carry id, title (the promotable set: landed, covered, not delivered)')
  // t261025-12 (ruling §5): the two controls are wired — the dialog mount
  // declares itself wired and the queue control rides the face.
  assert(html.includes('data-wired="true"'), 'the promote note mount declares itself wired')
  assert(html.includes('id="certQueue"') && html.includes('id="certQueueNote"'), 'the queue control + note mount render on the face')
  assert(html.includes('Queue round'), 'the queue control is labelled')
  n += 14
}

// ---- green render: no banner; promote disabled at zero only ----
{
  const zeroFace = { ...greenFace, promotable: 0, certified: [] }
  const zeroHtml = buildCertificationCore(routeAnswer(zeroFace))
  assert(zeroHtml.includes('id="certPromo" data-promotable="0" disabled'), 'Promote is disabled exactly at zero')
  assert(!zeroHtml.includes('id="certBanner"'), 'no freeze banner when not frozen')
  const aliveHtml = buildCertificationCore(routeAnswer(greenFace))
  assert(aliveHtml.includes('data-promotable="2"') && !aliveHtml.includes('id="certPromo" disabled'), 'Promote alive at promotable 2, unfrozen')
  // t261025-12: an unreadable count renders NO number and stays disabled —
  // a face the tab cannot read never renders a count (the host's 'Promote 1').
  const nullHtml = buildCertificationCore(routeAnswer({ ...greenFace, promotable: null, promoteBlock: 'preview unreadable: ledger malformed' }))
  assert(nullHtml.includes('disabled'), 'an unreadable count disables the control')
  assert(nullHtml.includes('preview unreadable: ledger malformed'), 'the unreadable count names why beside the control')
  assert(!nullHtml.includes('data-promotable="2"'), 'an unreadable count never renders the stale number')
  n += 5
}

// ---- the degrade face: a refusal renders its named reason, never a fake ----
{
  const html = buildCertificationCore({ ok: false, project: 'proj-x', reason: 'line declaration missing: x' })
  assert(html.includes('id="certDegrade"') && html.includes('line declaration missing: x'), 'degraded answer renders the named reason')
  n += 1
}

// ---- the switch renders records only (rule 9: no scheduler face) ----
{
  const html = buildCertificationCore(routeAnswer(frozenFace))
  // t261019-23 (F2): the dead switch is gone; only the records' state word renders
  assert(!html.includes('auto rounds') && html.includes('id="certRoundState"'), 'the auto-rounds switch is gone, the state word stays')
  assert(html.includes('>idle<') || html.includes('>running<'), 'the round state is the records word')
  assert(!html.includes('run now'), 'no run-now control (round chaining is another ticket)')
  n += 3
}

done(n)
