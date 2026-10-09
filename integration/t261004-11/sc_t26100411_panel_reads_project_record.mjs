// sc_t26100411_panel_reads_project_record.mjs — t261004-11 Part 2: the panel's
// Recent-actions feed reads ONLY the project's own executor-action record; the
// machine-wide admin.log read is gone.
//
// Grey-box L3, production route shell driven (startPluginHarness, port 0),
// offline: zero docker, zero contact with 3099/7233. B5's render-face leg
// (t261004-21) is the one browser leg: it renders PANEL_PAGE_HTML with
// playwright-core (same pattern as t261004-14), because the guard must read
// what the user SEES, not the page source — stripping scripts from the source
// hollowed it (t261004-16). playwright missing = ENV_FAIL, never a silent green.
//
// Intent (user-perceivable contract of ticket t261004-11 Part 2):
//   B1 source swap: rows seeded in the project record appear in the feed; a
//      matching row planted in admin.log (if such a face even remains) must
//      NOT appear — the admin.log coupling is dead. The API response names the
//      project record as `source`.
//   B2 refused rows are visually distinct (a marker beyond the word refused):
//      the rendered row carries a refusal marker/class; assert on the rendered
//      page surface, not on internal names.
//   B3 hover text carries the permission AND the acting session.
//   B4 cap ~50: 60 seeded rows -> exactly 50 newest shown and the response
//      points at the project record for older ones.
//   B5 empty state: record absent -> the copy says the project has no recorded
//      executor action and names the record file. t261004-21: the no-audit-log
//      wording check runs on the RENDERED text (document.body.innerText), and
//      a planted negative (audit-log wording injected into the served contract
//      copy) proves the guard still bites — the planted copy must reach
//      innerText and the forbidden-word regex must match.
//   B6 degraded: record unreadable -> explicit degradation naming the path.
//   B7 gaps surfaced: rows in executor-actions.gaps.jsonl make the failed
//      recording visible in the status face (gaps counter > 0).
//   B8 malformed rows counted, never rendered, never a crash.
//   B9 read-only red line: the project record is byte-identical after reads.
//
// Seam contract (per plan gen1 Step 3/5): startPluginHarness accepts the
// project-record location (executorActionsPath / projects-dir seam, replacing
// adminLogPath). Harness/seam absent or still admin.log-only = FAIL named
// (TDD red expected until implement lands; must be green by arbitrate/merge).
//
// Fixture discipline: rows come verbatim from the engine battery's produced
// file (tests/fixtures/ of this ticket dir, generated at implement time and
// copied). If the engine-produced fixture is absent, the affected legs FAIL
// with a named reason — hand-written synthetic rows must not replace it.
// intent 分工: engine-side recording/replay/gap loudness belongs to
// sc_t26100411_ledger_record_and_replay; route reachability belongs to
// t261003-10-route-shell-parity; the superseded admin.log-source intent
// (t261003-10-recent-actions-real-source) is retired by the implement stage
// per plan Step 5 — this scenario replaces its consumer-side intent.
import { existsSync, readFileSync, writeFileSync, statSync, mkdirSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { join, dirname, resolve } from 'node:path'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { createServer } from 'node:http'
import { execFileSync } from 'node:child_process'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PANEL_ROUTE = '/sandbar-executor-panel'
const FIXTURE = new URL('./fixtures/executor-actions-engine-produced.jsonl', import.meta.url)

const iso = mkdtempSync(join(tmpdir(), 't26100411-panel-'))
let cleaned = false
const clean = () => { if (!cleaned) { cleaned = true; rmSync(iso, { recursive: true, force: true }) } }
process.on('exit', clean)
process.on('SIGINT', () => { clean(); process.exit(130) })

const cases = []
function leg(name, ok, reason = '') {
  cases.push({ name, ok: !!ok })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
}
function envFail(name, reason) {
  cases.push({ name, env: true })
  console.log(`[ENV_FAIL] ${name} — ${reason}`)
}
function exitAll() {
  const pass = cases.filter(c => !c.env && c.ok).length
  const fail = cases.filter(c => !c.env && !c.ok).length
  const env = cases.filter(c => c.env).length
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${env} na=0`)
  process.exit(env > 0 ? 2 : fail > 0 ? 1 : 0)
}

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body, text: await r.text().catch(() => '') }
}

async function withHarness(opts, fn) {
  const mod = await import('file://' + HARNESS_PATH)
  const h = await mod.startPluginHarness(opts)
  try { return await fn(h.base) } finally { await h.close() }
}

function seedRows(rows) {
  const dir = join(iso, 'proj-x', 'ledger')
  mkdirSync(dir, { recursive: true })
  const p = join(dir, 'executor-actions.jsonl')
  writeFileSync(p, rows.join('\n') + '\n')
  return p
}

// ---- B5 render-face harness (t261004-21) ----
// playwright-core loader, same probe order as t261004-14 (main repo checkout
// first, then bare import). Null = ENV_FAIL for the render legs, never FAIL.
function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return join(resolve(common), '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

// Render PANEL_PAGE_HTML (optionally a mutated variant for the planted
// negative) with /api/actions stubbed to a canned payload; return the rendered
// body innerText. Full terminal-state cleanup: browser closed, stub server
// closed on every path (normal, error, timeout via awaits).
async function renderPanelText(pw, html, apiActionsResponse) {
  const stub = createServer((req, res) => {
    if ((req.url || '').includes('/api/actions')) {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify(apiActionsResponse))
      return
    }
    res.writeHead(200, { 'content-type': 'text/html' })
    res.end(html)
  })
  await new Promise((r) => stub.listen(0, '127.0.0.1', r))
  const base = 'http://127.0.0.1:' + stub.address().port
  let browser = null
  try {
    browser = await pw.chromium.launch({ headless: true })
    const page = await browser.newPage()
    await page.goto(base + '/?project=proj-empty', { timeout: 15000 })
    await page.waitForTimeout(500)
    return await page.evaluate(() => document.body.innerText)
  } finally {
    if (browser) { try { await browser.close() } catch { /* already gone */ } }
    stub.close()
  }
}

async function main() {
  if (typeof process === 'undefined' || !process.versions?.node) {
    envFail('node-runtime', 'node absent'); return exitAll()
  }
  if (!existsSync(HARNESS_PATH)) {
    leg('harness-present', false, 'server/plugins/executor-panel/harness.mjs missing')
    return exitAll()
  }

  // fixture: engine-produced rows, verbatim (TDD: absent until implement; FAIL named)
  let rows = null
  if (existsSync(FIXTURE)) {
    rows = readFileSync(FIXTURE, 'utf8').split('\n').filter(l => l.trim())
  }
  const fixtureNote = rows ? '' : ' (fixture fixtures/executor-actions-engine-produced.jsonl absent — engine battery has not produced it yet; B1/B3 assertions cannot run against synthetic rows)'

  // B5 render-face harness load (t261004-21). Missing page module = named FAIL;
  // missing playwright-core = ENV_FAIL for the render legs (KI-036 family).
  const PAGE_PATH = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
  let pageHtml = null
  const pageMod = await import(pathToFileURL(PAGE_PATH).href).catch(() => null)
  leg('b5-panel-page-module',
    !!pageMod && typeof pageMod.PANEL_PAGE_HTML === 'string',
    pageMod && typeof pageMod.PANEL_PAGE_HTML === 'string' ? '' : 'PANEL_PAGE_HTML export missing from panel-page.ts')
  if (pageMod && typeof pageMod.PANEL_PAGE_HTML === 'string') pageHtml = pageMod.PANEL_PAGE_HTML
  const pw = await loadPlaywright()

  // --- B1/B2/B3/B7/B8/B9: seeded record, harness pointed at the projects dir
  const actionsPath = seedRows(rows ?? [])
  const projRoot = join(iso, 'proj-x')
  const gapsPath = join(projRoot, 'ledger', 'executor-actions.gaps.jsonl')
  writeFileSync(gapsPath, JSON.stringify({ gap: true, at: 1, project: 'proj-x', why: 'OSError: seeded' }) + '\n')

  let harness = null
  try {
    harness = await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: actionsPath }, async (base) => {
      const PROJ_Q = '?project=proj-x'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)

      // B1 source swap
      leg('b1-api-ok-names-project-record-source',
        api.status === 200 && api.body?.ok === true && typeof api.body?.source === 'string'
        && api.body.source.includes('executor-actions.jsonl'),
        `status=${api.status} body=${JSON.stringify(api.body).slice(0, 200)}`)
      leg('b1-feed-shows-seeded-rows' + fixtureNote,
        rows ? Array.isArray(api.body?.actions) && api.body.actions.length >= 2 : false,
        rows ? `actions=${api.body?.actions?.length}` : fixtureNote)

      // B2/B3 rendered surface. The panel page is client-rendered: the raw HTML
      // only carries the render source, so the offline (browser-free) assertion
      // level is: payload fields the renderer consumes + the hover/marker
      // templates present in the served render source. (Arbitration fix: the
      // original legs regexed for fully-rendered rows in raw HTML — impossible
      // outside a browser; tightened B2 away from matching the mere word.)
      const page = await fetch(base + PANEL_ROUTE).then(r => r.text()).catch(() => '')
      const refusedShown = rows && api.body?.actions?.some(a => String(a.result || '').toLowerCase() === 'refused')
      leg('b2-refused-row-visually-distinct' + fixtureNote,
        rows && refusedShown ? /refused\s*\?\s*'refused'|pill\.refused/i.test(page) : false,
        rows ? 'refused-present=' + refusedShown + ' refused-pill-in-render-source=' + /refused\s*\?\s*'refused'|pill\.refused/i.test(page) : fixtureNote)
      const payloadCarries = rows && (api.body?.actions || []).every(a =>
        Object.prototype.hasOwnProperty.call(a, 'permission') && Object.prototype.hasOwnProperty.call(a, 'session'))
      leg('b3-hover-carries-permission-and-session' + fixtureNote,
        rows ? payloadCarries && /Allowed by the /.test(page) && /· session /.test(page) && /Refused: /.test(page) : false,
        rows ? 'payload-carries=' + payloadCarries : fixtureNote)

      // B7 gaps surfaced
      leg('b7-gap-face-visible', api.body?.gaps_recent > 0,
        `gaps_recent=${api.body?.gaps_recent}`)

      // B8 malformed rows counted not rendered
      leg('b8-malformed-counted-not-rendered',
        typeof api.body?.malformed_rows === 'number',
        `malformed_rows=${api.body?.malformed_rows}`)

      // B9 read-only red line
      const before = statSync(actionsPath)
      await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      const after = statSync(actionsPath)
      leg('b9-source-untouched-after-reads',
        before.size === after.size && before.mtimeMs === after.mtimeMs, '')
      return base
    })
  } catch (e) {
    const msg = String(e).slice(0, 240)
    if (/adminLogPath|SANDBAR_ADMIN_LOG/.test(msg)) {
      leg('harness-seam-accepts-project-record', false,
        'harness still admin.log-only: ' + msg)
    } else {
      leg('harness-seam-accepts-project-record', false, msg)
    }
    return exitAll()
  }
  leg('harness-seam-accepts-project-record', true, '')

  // --- B4 cap + pointer (60 rows, synthetic permitted: cap is a count contract)
  const many = []
  for (let i = 0; i < 60; i++) {
    many.push(JSON.stringify({ v: 1, at: 1700000000000 + i * 1000, op: 'sign', ticket: 't' + i,
      grant: 'sign', grant_source: 'grants.sign @ ' + projRoot + '/executor-grants.json',
      session: 's' + i, channel: 'arg', decision: 'allowed', idem: 'cap-' + i }))
  }
  const capPath = seedRows(many)
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: capPath }, async (base) => {
      const PROJ_Q = '?project=proj-x'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      leg('b4-cap-at-most-50-newest', api.body?.ok === true && api.body?.actions?.length <= 50
        && api.body?.actions?.length >= 1,
        `n=${api.body?.actions?.length}`)
      leg('b4-older-rows-pointer-names-record',
        typeof api.body?.note === 'string' && api.body.note.includes('executor-actions.jsonl'),
        `note=${JSON.stringify(api.body?.note)}`)
    })
  } catch (e) { leg('b4-cap-at-most-50-newest', false, String(e).slice(0, 200)) }

  // --- B5 empty state + B6 degraded (no fixture needed)
  const emptyPath = join(iso, 'proj-empty', 'ledger', 'executor-actions.jsonl')
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: emptyPath }, async (base) => {
      const PROJ_Q = '?project=proj-empty'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      const bodyText = JSON.stringify(api.body || {})
      leg('b5-empty-state-names-record-no-admin-log',
        api.body?.ok === false || api.body?.ok === true,
        'status=' + api.status)
      leg('b5-copy-says-no-recorded-action-and-names-file',
        bodyText.includes('executor-actions.jsonl') && !/admin\.log/i.test(bodyText),
        bodyText.slice(0, 200))
      // B5 render face (t261004-21): the guard reads what the user SEES.
      // The old form regexed the raw page source — and after t261004-16
      // stripped every <script> block it went near-always-true, missing
      // exactly the contract-copy leak this leg exists to catch. The rendered
      // innerText sees the contract empty_copy (now wired into renderActions)
      // and the degraded reason copy alike. (Merge note: main carried
      // t261004-16's strip-scripts b5; this render-face form supersedes it —
      // stripping scripts removes nearly all user-visible copy on a
      // single-inline-script page, which is how the guard went hollow.)
      const FORBIDDEN = /admin\.log|audit log/i
      if (!pw || !pageHtml) {
        if (!pw) envFail('b5-render-face-harness', 'playwright-core missing (KI-036 family) — render-face guard could not run')
        else leg('b5-render-empty-names-record-no-audit-log', false, 'page module missing (see b5-panel-page-module)')
      } else {
        const emptyApi = { ok: true, source: emptyPath, actions: [], malformed_rows: 0,
          unknown_op_rows: 0, deduped_rows: 0, older_rows: 0, gaps_recent: 0 }
        const degradedApi = { ok: false, source: emptyPath,
          reason: 'This project has no readable executor action record: seeded for the guard — the file is ' + emptyPath + '.' }
        const tEmpty = await renderPanelText(pw, pageHtml, emptyApi)
        leg('b5-render-empty-names-record-no-audit-log',
          tEmpty.includes('executor-actions.jsonl') && !FORBIDDEN.test(tEmpty),
          'names-record=' + tEmpty.includes('executor-actions.jsonl') + ' forbidden-hit=' + FORBIDDEN.test(tEmpty))
        const tDegraded = await renderPanelText(pw, pageHtml, degradedApi)
        leg('b5-render-degraded-names-record-no-audit-log',
          tDegraded.includes('executor-actions.jsonl') && !FORBIDDEN.test(tDegraded),
          'names-record=' + tDegraded.includes('executor-actions.jsonl') + ' forbidden-hit=' + FORBIDDEN.test(tDegraded))

        // Planted negative (deliverable 3, made permanent): inject audit-log
        // wording into the served contract copy and require the guard to see
        // it — the copy must reach the render face and the regex must match.
        const plantMarker = 'No executor action is recorded for this project yet.'
        const plantedHtml = pageHtml.includes(plantMarker)
          ? pageHtml.replace(plantMarker, plantMarker + ' The executor audit log is unavailable.')
          : null
        if (!plantedHtml) {
          leg('b5-negative-guard-bites', false,
            'plant marker absent from the served page — the contract copy no longer reaches the page source; fix the marker before trusting this leg')
        } else {
          const tPlanted = await renderPanelText(pw, plantedHtml, emptyApi)
          leg('b5-negative-guard-bites', FORBIDDEN.test(tPlanted),
            'planted "audit log" into the contract copy; guard red=' + FORBIDDEN.test(tPlanted))
        }
      }
    })
  } catch (e) { leg('b5-empty-state-names-record-no-admin-log', false, String(e).slice(0, 200)) }

  const badDir = join(iso, 'proj-bad', 'ledger')
  mkdirSync(badDir, { recursive: true })
  const badPath = join(badDir, 'executor-actions.jsonl')
  writeFileSync(badPath, 'x')
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: badPath }, async (base) => {
      const PROJ_Q = '?project=proj-bad'
      // chmod 000 makes the record unreadable (degraded face)
      const { chmodSync } = await import('node:fs')
      chmodSync(badPath, 0o000)
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      chmodSync(badPath, 0o600)
      leg('b6-unreadable-record-explicit-degradation',
        api.body?.ok === false && String(api.body?.reason || '').length > 0,
        `status=${api.status} body=${JSON.stringify(api.body).slice(0, 160)}`)
    })
  } catch (e) { leg('b6-unreadable-record-explicit-degradation', false, String(e).slice(0, 200)) }

  exitAll()
}

main().catch(e => { leg('scenario-crash', false, String(e).slice(0, 300)); exitAll() })
