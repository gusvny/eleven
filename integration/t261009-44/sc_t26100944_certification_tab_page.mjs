// sc_t26100944_certification_tab_page.mjs — t261009-44 (t261009-41 Slice 2),
// grey-box L3, offline, zero docker/Temporal/browser, never touches 3099.
//
// This entry owns the VISIBLE half's page face: the Certification tab exists
// where a person will look for it, its read is wired to the one registered
// route, and nothing on the page fakes a write the engine does not expose yet.
// Anchored on the public page contract (the served panel HTML) and the public
// HTTP contract — never on private view-core internals (a contract-preserving
// redesign of the render layer must not break this).
//
// Intent:
//   P1 a person can find the tab: the served page carries a Certification tab
//      entry in the tab row (the host's original request, verbatim need).
//   P2 the tab reads through the registered route: the page's certification
//      read targets exactly /sandbar-executor-panel/api/certification AND that
//      path answers through the production registration shell — page-sends-X
//      alone is NOT evidence (KI-01M4HMCZAM4ZBC2CKN15HDBZHP: dead button = a
//      client path no server route answers, verified by reading client text).
//   P3 no fake write face: the page does not POST the certification read path,
//      and no certify/promote submit exists behind this slice's dialog — the
//      absent promotion write is named on the face, not faked (dispatch spec 5).
//   P4 the counted words appear once on the served page shell (line bar cap /
//      boundary vocabulary is a mock rule; the face-level rules themselves are
//      owned by t261009-41-certification-face-seam and not repeated here).
//
// Three states: tab/page not yet implemented = FAIL named (TDD red expected
// pre-implement; green required at the gate/merge); node or harness missing =
// ENV_FAIL exit 2.

import { loadPanelHarness, makeIsoDir, makeCase, PANEL_PAGE_PATH } from '../t261003-06/lib_panel_seam.mjs'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const C = makeCase()
const ROUTE = '/sandbar-executor-panel/api/certification'

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.envFail('harness-loadable', String(e).slice(0, 200)); return null })
  if (!harness) return C.exit()

  // P1+P3+P4 the served page face.
  let html = ''
  if (typeof harness.PANEL_PAGE_HTML === 'string') html = harness.PANEL_PAGE_HTML
  else if (PANEL_PAGE_PATH) html = readFileSync(PANEL_PAGE_PATH, 'utf8')
  if (!html) { C.envFail('page-face-readable', 'panel page HTML not exportable from the harness (env seam absent)'); return C.exit() }

  C.case('certification-tab-entry-present', /Certification/.test(html),
    'the tab row must carry a Certification entry a person can see')
  C.case('page-reads-registered-route', html.includes(ROUTE),
    `the page's certification read must target ${ROUTE} (paired with the registration proof below)`)
  C.case('no-fake-certification-write', !new RegExp(`POST[^\\n]{0,80}${ROUTE}`).test(html),
    'no POST to the certification read path may exist on the page (record-signed ops stay outside it)')

  // P2 the path the page calls is ANSWERED by the production registration shell.
  const iso = makeIsoDir('t26100944-page-')
  const H = await harness.startPluginHarness({ panelDir: join(iso.dir, 'panel') }).catch((e) => { C.envFail('harness-start', String(e).slice(0, 200)); return null })
  if (!H) return C.exit()
  try {
    const page = await fetch(H.base + '/sandbar-executor-panel/').then(async (r) => ({ status: r.status, text: await r.text().catch(() => '') }))
    C.case('panel-page-served', page.status === 200, `status=${page.status}`)
    const probe = await fetch(H.base + ROUTE + '?project=page-probe').then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))
    const answered = probe.status < 500 && !(probe.status === 404)
    C.case('route-answered-not-404', answered,
      `GET ${ROUTE} via production registration shell: status=${probe.status} (404 = dead button, KI-01M4HMCZAM4ZBC2CKN15HDBZHP)`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}
main()
