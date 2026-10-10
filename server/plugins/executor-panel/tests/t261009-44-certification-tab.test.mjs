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
import { buildCertificationCore, resultCell, verdictCell, CERT_COPIES } from '../src/host/certification-view.ts'
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

const routeAnswer = (face, line = 'develop-buffer') => ({
  ok: true, project: 'proj-x', line, lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
  face, raw: fixture, notes: [],
})

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
  // one bar, one boundary: the cap + exactly one boundary line
  assert(html.includes('class="linebar"'), 'the line bar is present')
  assert(html.includes('class="s cap"'), 'the delivered part is a fixed cap, not a segment')
  assert((html.match(/certified \d?\d:\d\d/g) ?? []).length === 1, 'exactly one boundary moment on the face')
  // counts inside segments only: the numbers live in .n spans and the promote button
  assert(html.includes('<span class="n">2</span>') && html.includes('<span class="n">3</span>'), 'segment counts render inside the segments')
  assert(!/Tally|tally/.test(html), 'no tally row exists (counts appear once)')
  // Promote disabled only at zero: promotable 2 stays alive through the freeze
  assert(html.includes('data-promotable="2"') && !html.includes('id="certPromote" disabled'), 'Promote stays alive through a freeze (promotable 2)')
  // trigger enum: only auto|manual in the trigger cells
  const triggers = [...html.matchAll(/title="[^"]*">(\w+)<\/td>/g)].map((m) => m[1]).filter((w) => w === 'auto' || w === 'manual')
  assert(triggers.length === frozenFace.rounds.length, 'every round renders a trigger word')
  assert(frozenFace.rounds.every((r) => r.trigger === 'auto' || r.trigger === 'manual'), 'trigger enum is auto|manual only')
  // labelled summing result + verdict cells
  assert(html.includes(resultCell(frozenFace.rounds[0].result)), 'the labelled summing result renders')
  assert(html.includes(verdictCell('red', 2)) && html.includes('red · 2 blockers'), 'red verdict names its blocker count')
  assert(html.includes(verdictCell('green', 0)), 'green verdict renders as the engine word')
  // line <sha>
  assert(/^line [0-9a-f]{8}$/.test(frozenFace.rounds[0].measured) && html.includes('line ' + frozenFace.rounds[0].measured.slice(5)), 'measured renders as line <sha>')
  // the one-line freeze banner naming its blockers
  assert(html.includes('id="certBanner"') && html.includes(frozenFace.frozenFace.blockers[0]), 'the freeze banner names its blockers')
  // every ticket row carries id, title and epic
  assert(html.includes('t261009-20') && html.includes('Guard the route change') && html.includes('engine-hardening'), 'waiting rows carry id, title, epic')
  assert(html.includes('t261009-23') && html.includes('Promote the certified part'), 'certified rows carry id, title (the promotable set: landed, covered, not delivered)')
  // the promote dialog is absent and named (the copy ships, hidden, on the face)
  assert(html.includes('data-wired="false"'), 'the promote note mount declares itself unwired')
  assert(CERT_COPIES.promoteAbsent.includes('record-signed promote stays an engine operation'), 'the named-absence sentence ships in the copies')
  assert(PANEL_PAGE_HTML.includes('record-signed promote stays an engine operation'), 'the page embeds the named-absence copy (CERT_TABLES)')
  n += 14
}

// ---- green render: no banner; promote disabled at zero only ----
{
  const zeroFace = { ...greenFace, promotable: 0, certified: [] }
  const zeroHtml = buildCertificationCore(routeAnswer(zeroFace))
  assert(zeroHtml.includes('id="certPromote" data-promotable="0" disabled'), 'Promote is disabled exactly at zero')
  assert(!zeroHtml.includes('id="certBanner"'), 'no freeze banner when not frozen')
  const aliveHtml = buildCertificationCore(routeAnswer(greenFace))
  assert(aliveHtml.includes('data-promotable="2"') && !aliveHtml.includes('id="certPromote" disabled'), 'Promote alive at promotable 2, unfrozen')
  n += 3
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
  assert(html.includes('auto rounds') && html.includes('id="certRoundState"'), 'the auto rounds face renders')
  assert(html.includes('>idle<') || html.includes('>running<'), 'the round state is the records word')
  assert(!html.includes('run now'), 'no run-now control (round chaining is another ticket)')
  n += 3
}

done(n)
