// sc_open_ticket_panel_section.mjs — t261004-19: the Grants page carries the
// host-only "Open tickets in these epics" section, its save goes through the
// audited grants save path, and the actions list shows which epic authorized
// each executor-opened ticket.
//
// Grey-box L3, real browser + page-boundary API stubs, zero docker, never
// touches 3099 (same architecture seam as t261004-14 / t261003-06).
//
// Intent (user-perceivable; ticket requirements 3 + 6 + review condition C3):
//   G1 the Grants page renders a section titled "Open tickets in these epics"
//      listing every epic (code + the status line as written in the epic
//      file) with a switch per epic;
//   G2 the switches reflect the current declaration: the authorized epic's
//      switch is on, the unauthorized epic's switch is off;
//   G3 toggling a switch and saving sends the audited grants save payload —
//      it carries the updated open_ticket_epics AND the existing grants (a
//      save must never drop keys); the page then reflects the new state;
//   G4 the recent-actions list shows the epic for an executor open-ticket row
//      that carries one, and the refused row's named reason stays reachable
//      (title attribute per the t261004-11 contract);
//   G5 a legacy action row without an epic must not throw and must not wipe
//      the list — zero pageerror across the journey (external-input
//      discipline, review condition C3);
//   G6 an epic without a status line keeps its row with the graceful
//      "(no status line)" fallback instead of a vanished row (req. 8).
//
// Stub shapes follow the panel's real read faces (arbitration fix: the first
// draft guessed an /api/epics endpoint and input-checkbox switches; the
// implemented contract is GET /api/grants carrying an open_ticket_epics face
// {ok, epics:[{code,status,authorized}]} + open_ticket_cap, div-based
// .sw.grant[data-epic] switches, and an actions feed of
// {ok, actions:[{at,action,ticket,permission,session,result,reason?,epic?}]}).
// playwright-core missing = ENV_FAIL exit 2 (KI-036 family); missing page
// module / section = FAIL with the name (TDD-phase red is expected until the
// implement lands; arbitrate/merge must be green).
// Intent split: gate verdicts, cap, no-self-widening and the ledger rows
// belong to sc_open_ticket_epic_gate_verdicts.py (same ticket, engine layer);
// pure-core matrices are developer L1.
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()

async function loadPlaywright() {
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(REPO, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

// GET /api/grants read face: the epic-authorization section reads
// open_ticket_epics (all epics + status line as written + authorized now)
// and open_ticket_cap straight off the grants payload (requirement 8: prose
// stays prose — the panel displays it, does not judge on it).
const GRANTS = {
  ok: true,
  version: 1,
  grants: { 'open-ticket': true, sign: true },
  granted_ops: ['open-ticket', 'sign'],
  open_ticket_cap: 3,
  open_ticket_epics: {
    ok: true,
    epics: [
      { code: 'engine-hardening', status: '| 状态 | active |', authorized: true },
      { code: 'localization', status: null, authorized: false },
    ],
  },
  executor_sessions: ['exec-1'],
  session_state: 'granted',
  granted_count: 4,
  total: 6,
  note: 'Permissions: 4 of 6',
}
// Recent-actions feed face (t261004-11 shape + this ticket's epic field):
// an allowed open-ticket row carries epic; a refused row carries its named
// reason; a legacy row carries no epic at all.
const ACTIONS = {
  ok: true,
  source: 'projects/alpha/ledger/executor-actions.jsonl',
  gaps_recent: 0,
  older_rows: 0,
  actions: [
    { at: Date.now() - 60_000, action: 'Open ticket', ticket: 't-new-1', permission: 'open-ticket', session: 'exec-1', result: 'done', epic: 'engine-hardening' },
    { at: Date.now() - 120_000, action: 'Open ticket', ticket: 't-new-2', permission: 'open-ticket', session: 'exec-1', result: 'refused', reason: 'epic localization is not in open_ticket_epics' },
    { at: Date.now() - 180_000, action: 'Sign', ticket: 't-old-9', permission: 'sign', session: 'exec-1', result: 'done' },
  ],
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts lacks named export PANEL_PAGE_HTML (seam contract)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }

  let savedBody = null
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/grants') && req.method === 'POST') {
      let body = ''
      req.on('data', (c) => { body += c })
      req.on('end', () => {
        try { savedBody = JSON.parse(body) } catch { savedBody = { _raw: body } }
        json({ saved: true })
      })
      return
    }
    if (u.pathname.endsWith('/api/grants')) return json(GRANTS)
    if (u.pathname.endsWith('/api/actions')) return json(ACTIONS)
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname === '/') {
      // Serve the real panel page (this was the first draft's silent killer:
      // the stub answered / with the default {ok:true} JSON, so every journey
      // below asserted against a body that was never the panel).
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
      res.end(pageMod.PANEL_PAGE_HTML)
      return
    }
    json({ ok: true })
  })
  await new Promise((r) => stub.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${stub.address().port}`

  const browser = await pw.chromium.launch({ headless: true }).catch(() => null)
  if (!browser) { C.envFail('chromium-launch', 'playwright chromium failed to launch'); stub.close(); return C.exit() }
  const page = await browser.newPage()
  const pageErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e)))

  try {
    // Reach the project through the deep link (t261003-06 seam): without
    // ?project= the panel renders its no-project wait face and never loads
    // grants/actions, so the journey below would assert against a blank page.
    await page.goto(`${base}/?project=alpha`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(300)
    // navigate to the grants surface if the panel is multi-view
    const grantsNav = page.locator('label[for="t-grants"]')
    if (await grantsNav.count().catch(() => 0)) await grantsNav.click().catch(() => {})
    await page.waitForTimeout(300)

    const body = (await page.locator('body').innerText().catch(() => '')) || ''

    // G1 section present, lists both epics with the status line as written
    const sec = page.locator('#openEpics')
    const secText = (await sec.innerText().catch(() => '')) || ''
    C.case('G1-section-present', /open tickets in these epics/i.test(body),
      'grants page lacks the "Open tickets in these epics" section')
    C.case('G1-epic-codes-listed', secText.includes('engine-hardening') && secText.includes('localization'),
      `section does not list both epic codes (section text: ${secText.slice(0, 120)})`)
    C.case('G1-status-line-as-written', secText.includes('active'),
      'the epic status line (as written in the file) is not shown')

    // G2 switches reflect the declaration (div switches: .sw.grant[data-epic])
    const switches = sec.locator('.sw.grant[data-epic]')
    const n = await switches.count().catch(() => 0)
    C.case('G2-switch-per-epic', n >= 2, `expected >=2 epic switches, found ${n}`)
    let onCount = 0
    for (let i = 0; i < n; i++) {
      const on = await switches.nth(i).getAttribute('data-on').catch(() => null)
      if (on === 'true') onCount++
    }
    C.case('G2-switch-states-match-declaration', n >= 2 && onCount === 1,
      `expected exactly 1 on-switch (engine-hardening), found ${onCount} of ${n}`)
    // G6 the epic without a status line keeps its row with the fallback label
    const noStatusRow = sec.locator('.sw.grant[data-epic="localization"]').locator('..')
    const noStatusText = (await noStatusRow.innerText().catch(() => '')) || ''
    C.case('G6-missing-status-line-fallback',
      (await noStatusRow.count().catch(() => 0)) > 0 && /no status line/i.test(noStatusText),
      `an epic without a status line lost its row or lacks the graceful fallback (row: ${noStatusText.slice(0, 80)})`)

    // G3 toggle + save through the audited endpoint, no dropped keys
    savedBody = null
    if (n >= 2) {
      await sec.locator('.sw.grant[data-epic="localization"]').click().catch(() => {})
      await page.locator('#grantsSave').click().catch(() => {})
      await page.waitForTimeout(300)
    }
    const g3ok = savedBody && typeof savedBody === 'object'
      && Array.isArray(savedBody.open_ticket_epics)
      && savedBody.open_ticket_epics.includes('localization')
      && savedBody.open_ticket_epics.includes('engine-hardening')
      && savedBody.grants && savedBody.grants.sign === true
    C.case('G3-save-carries-whole-declaration', !!g3ok,
      `save payload missing open_ticket_epics update or dropped existing grants: ${JSON.stringify(savedBody).slice(0, 200)}`)

    // G4/G5 actions list: epic shown, refused reason reachable, legacy row safe.
    // The recent-actions list lives on the Overview tab (hidden panes are
    // display:none, so innerText does not see them until the tab is shown).
    const overviewNav = page.locator('label[for="t-overview"]')
    if (await overviewNav.count().catch(() => 0)) await overviewNav.click().catch(() => {})
    await page.waitForTimeout(300)
    const afterText = (await page.locator('body').innerText().catch(() => '')) || ''
    const afterHtml = (await page.content().catch(() => '')) || ''
    C.case('G4-actions-show-epic', /epic\s+engine-hardening/.test(afterText),
      'recent actions do not show the epic that authorized the open-ticket row')
    C.case('G4-refused-reason-visible', /not in open_ticket_epics/i.test(afterHtml),
      'the refused row\'s named reason is not reachable (title attribute) in the actions list')
    const legacySafe = pageErrors.length === 0
      && (afterText.match(/t-old-9/g) || []).length >= 1
    C.case('G5-legacy-row-safe', legacySafe,
      `legacy no-epic row lost or pageerror(s): ${pageErrors.slice(0, 2).join(' | ')}`)
  } finally {
    await browser.close().catch(() => {})
    stub.close()
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
