#!/usr/bin/env node
// t261008-02 scenario: a // comment must never render as visible text in the
// middle column (grey-box L3, browser-free pool, two-layer, mirrors
// t261007-07/sc_platform_banner_suppressed.mjs).
//
// User story (ticket t261008-02, host report 261007): a person clicks a project
// name; the middle column shows the machine-status head — and nothing else that
// is not UI. Today one raw code comment ("// t261005-10 (UI-2): the number stays
// machine-level; …") renders as visible text there, because it sits in JSX
// children position where `//` is text, not a comment (src/client/index.tsx,
// between the workers button and the Inspection-jump button).
//
// Layers:
//   S0 build-contract (pure node, seconds): twin shipped bundles in sync
//      (KI-052); the offending literal is ABSENT from the shipped bundles
//      (children-position text is fully determined by the bundles); source
//      family guard — no new bare `//` comment run in JSX children position
//      anywhere in the workbench client src (the host's family sweep made
//      machine-checkable, so the pattern cannot come back silently).
//   S1 real browser DOM: isolated stage console (lib_fix17 bootConsole, freePort
//      refuses 3099; teardownOnExit reclaims on every terminal state) +
//      playwright-core + chromium; any of them missing = ENV_FAIL exit 2.
//      Data is stubbed only at the API boundary (/wf/projects, /wf/tickets,
//      /wf/inspection/tickets); browser/bundle/React all real; the host console
//      on 3099 is never touched. The journey follows the host report: open the
//      console, click into the project (executor entry on the project row),
//      wait for the machine-status head, then assert the head's rendered text.
//      Runs under light AND dark (KI-055 theme-matrix discipline), each with a
//      screenshot into integration/t261008-02/out/ as the acceptance evidence
//      the ticket asks for.
//
// Three states (t260904-12): any fail>0 or all-na = exit 1; env_fail>0 = exit 2.
// Red before the implement stage lands is the expected TDD signal; arbitrate /
// merge must be green.
//
// Intent split: the machine-status head's own behaviour (buttons, counts, the
// workers panel) is out of scope here (ticket says so) — other entries own it.
// The bundle-src build contract faces overlap the developer L1 static test
// (tests/t261008-02-*) by design: L1 pins the files, this entry pins what a
// READER sees after a real render. This entry uniquely owns: the rendered head
// contains no `//` text and no comment literal, under both themes, with
// screenshot evidence.
// KI alignment: KI-052 (twin bundles in sync), KI-055 (light+dark matrix),
// KI-036 (playwright missing = ENV_FAIL), t260904-12 (three states, no SKIP).

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, REPO_ROOT } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = REPO_ROOT
const OUT_DIR = join(REPO, 'integration', 't261008-02', 'out')
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'index.tsx')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
// The offending comment's identity tokens. Anchor the ticket-visible literal,
// not the whole sentence (an em-dash re-word must not defeat the guard).
const BAD_LITERAL = 't261005-10 (UI-2): the number stays machine-level'
const HEAD_MARK = 'Inspection'

let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t261008-02-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', 'fixture-alpha', ['/tmp/fx-alpha'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  BASE = bench.base
  await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- fixtures

const PROJ_A = 'fixture-alpha'
const RUN_ID = 'devfixa1008run'
const T2 = 1789353600
const LEDGER_KEY = 'sandbar-workbench-opened-sessions-v1'

function devRow(id, stageState, title, ts) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
  }
}
const DEV_ROWS = [devRow(RUN_ID, 'running', 'alpha comment-leak ticket', T2)]
const WORKFLOWS = [{
  id: 'dev-lane', name: 'dev lane', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: 'plan', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
  ],
}]

// ---------------------------------------------------------------- S0 build-contract

// Family-sweep pattern, machine form of the host's sweep: a RUN of `//` comment
// lines whose previous non-blank line ends with > / ) / } and whose next
// non-blank line starts with < or { — i.e. a `//` comment block sitting in JSX
// children position, where it ships as text. The run is judged as one unit:
// within a multi-line comment the "next line" is another comment line, which
// must not defeat the detector. Binding note: this inspects SOURCE text (L1
// owns the file face); the reader-facing truth is S1.
function childrenPositionCommentLines(src) {
  const lines = src.split('\n')
  const isBlank = (s) => !s.trim()
  const isSlashComment = (s) => /^\s*\/\//.test(s)
  const endsOpen = (s) => /[>)}]\s*$/.test(s)
  const startsMark = (s) => /^\s*[<{]/.test(s)
  const prevNonBlank = (i) => { for (let j = i - 1; j >= 0; j--) if (!isBlank(lines[j])) return lines[j]; return null }
  const nextNonBlank = (i) => {
    for (let j = i + 1; j < lines.length; j++) {
      if (isBlank(lines[j]) || isSlashComment(lines[j])) continue  // inside the comment run
      return lines[j]
    }
    return null
  }
  const hits = []
  for (let i = 0; i < lines.length; i++) {
    if (!isSlashComment(lines[i])) continue
    if (i > 0 && isSlashComment(lines[i - 1])) continue            // not the head of a run
    const prev = prevNonBlank(i)
    const next = nextNonBlank(i)
    if (prev !== null && endsOpen(prev) && next !== null && startsMark(next)) hits.push(i + 1)
  }
  return hits
}

function buildContract() {
  if (!existsSync(SRC)) {
    record('S0 src-present', 'fail', 'workbench client src missing — nothing to guard')
    return
  }
  const src = readFileSync(SRC, 'utf8')
  const bare = childrenPositionCommentLines(src)
  record('S0 no-children-position-comment (family guard)', bare.length ? 'fail' : 'pass',
    bare.length ? `bare // lines in JSX children position at src lines ${bare.join(', ')}（pre-implement red expected）`
      : 'no bare // comment run in JSX children position anywhere in the workbench client src')
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 bundles-present', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 bundles-in-sync', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return
  }
  const leaks = js.includes(BAD_LITERAL)
  record('S0 bundle-free-of-comment-literal', leaks ? 'fail' : 'pass',
    leaks ? `shipped bundle still carries the comment literal "${BAD_LITERAL}" — it renders as text（pre-implement red expected）`
      : 'twin bundles in sync; comment literal absent from the shipped bundle')
}

// ---------------------------------------------------------------- S1 real browser

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const candidates = ['playwright-core']
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) candidates.push(pathToFileURL(p).href)
  }
  for (const c of candidates) {
    try { return await import(c) } catch { /* next */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await p.keyboard.press('Escape').catch(() => {})
    await p.waitForTimeout(600)
  }
}

function routeStubs(route) {
  const url = new URL(route.request().url())
  const path = url.pathname.replace(/\/+$/, '')
  if (path === '/sandbar-workbench/api/wf/projects') {
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { projects: [
        { key: PROJ_A, name: 'fixture-alpha', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
      ], quarantined: [] } }),
    })
  }
  if (path === '/sandbar-workbench/api/wf/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: DEV_ROWS, workflows: WORKFLOWS } }) })
  }
  if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: [], count: 0 } }) })
  }
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
}

// In-page read of the middle column's first-screen face and its column.
// t261008-18: the machine-status head is retired — the face this entry waits for
// is the executor view (`[data-wb-executor-view]`, the middle column's own head
// since the strip went away);
// the assertions fall on READER-visible text of the middle column as a whole
// (a superset of the head — if the literal leaks anywhere the user can see, it
// is a defect), never on internal names or execution order.
async function headFaces(page) {
  return page.evaluate((mark) => {
    const visible = (el) => {
      const r = el.getBoundingClientRect()
      if (r.width < 2 || r.height < 2) return false
      const cs = getComputedStyle(el)
      return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0.05
    }
    const head = document.querySelector('[data-wb-executor-view]')
    const headVisible = !!head && visible(head)
    const column = document.querySelector('.wb-right-content')
    const colText = column ? column.textContent : ''
    const headText = head ? head.textContent : ''
    return {
      headVisible,
      headText,
      hasMark: headText.includes(mark) || colText.includes(mark), // sanity: the machine-status face is up
      hasSlashSlash: colText.includes('//'),   // the defect face: a // comment rendering as text
      hasLiteral: colText.includes('t261005-10 (UI-2)'),
      diag: {
        headCount: document.querySelectorAll('[data-wb-executor-view]').length,
        headSnippet: headText ? headText.slice(0, 80) : null,
        colHasSlash: colText.includes('//'),
      },
    }
  }, HEAD_MARK)
}

async function settleLeftColumn(page) {
  const landed = await waitFor(async () => {
    return page.evaluate(() => !!document.querySelector('[data-wb-brand-row]')).catch(() => false)
  }, 15000)
  if (!landed) return false
  await page.waitForTimeout(2500)
  await dismissOverlays(page)
  return true
}

// The user journey from the host report: click into the project (the executor
// entry on the project row), wait until the middle column's own face shows
// (t261008-18: the executor view replaced the machine-status head). Bound to
// the entry contract (data-wb-executor-entry), not to coordinates or internals.
async function openMachineHead(page) {
  return waitFor(async () => {
    await page.evaluate(() => {
      const entry = document.querySelector('[data-wb-executor-entry]')
      if (entry) entry.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await page.waitForTimeout(600)
    const f = await headFaces(page)
    return f.headVisible && f.hasMark
  }, 10000)
}

async function runLeg(browser, colorScheme, shotName) {
  const ctx = await browser.newContext()
  try {
    await ctx.addInitScript(([key, val]) => { try { localStorage.setItem(key, val) } catch { /* fresh */ } },
      [LEDGER_KEY, JSON.stringify([])])
    const page = await ctx.newPage()
    const pageErrors = []
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    if (colorScheme) await page.emulateMedia({ colorScheme })
    await bench.goto(page, { waitUntil: 'networkidle' })
    if (!(await settleLeftColumn(page))) {
      record(`S1 ${shotName} precheck`, 'env_fail', `left column did not render (stub /wf/projects not consumed? stage=${BASE})`)
      return
    }
    const opened = await openMachineHead(page)
    if (!opened) {
      record(`S1 ${shotName} precheck`, 'env_fail', 'the middle-column face (executor view) did not appear after clicking the project entry — journey unreachable in this stage build')
      return
    }
    record(`S1 ${shotName} precheck`, 'pass', `middle-column face rendered (${colorScheme || 'light (default)'})`)

    const f = await headFaces(page)

    // H1 the ticket's reader-visible face: the middle column (the executor view
    // included) contains no '//' rendered text (a children-position comment is
    // the only way one lands as text here).
    const h1ok = f.headVisible && !f.hasSlashSlash
    record(`H1 head-has-no-comment-text (${shotName})`, h1ok ? 'pass' : 'fail',
      h1ok ? 'middle column / executor view contains no "//" '
        : `"//" still renders in the middle column (head visible=${f.headVisible}, diag=${JSON.stringify(f.diag)})（pre-implement red expected）`)

    // H2 the exact comment literal never reaches the DOM (regression lock on
    // the reported symptom, theme-independent).
    const h2ok = !f.hasLiteral
    record(`H2 head-free-of-comment-literal (${shotName})`, h2ok ? 'pass' : 'fail',
      h2ok ? `literal "${BAD_LITERAL}" absent from the rendered middle column`
        : `comment literal renders in the middle column: ${JSON.stringify((f.headText || '').slice(0, 160))}（pre-implement red expected）`)

    // Screenshot: the acceptance evidence the ticket names (middle column with
    // the machine-status head and no comment text). Failure to save the shot is
    // reported, never traded for a pass.
    try {
      mkdirSync(OUT_DIR, { recursive: true })
      await page.screenshot({ path: join(OUT_DIR, shotName), fullPage: false })
    } catch (e) {
      console.log(`[WARN] screenshot ${shotName} failed: ${String(e).slice(0, 120)}`)
    }

    record(`S1 page-health (${shotName})`, pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror ×${pageErrors.length}: ${pageErrors.slice(0, 3).join(' | ')}` : 'zero pageerror')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

buildContract()

const pw = await loadPlaywright()
if (!pw) {
  console.log('[ENV_FAIL] playwright-core unavailable (KI-036 family)')
  summarize()
}
const browser = await launchBrowser(pw)
if (!browser) {
  console.log('[ENV_FAIL] chromium unavailable (KI-036 family)')
  summarize()
}
try {
  await runLeg(browser, null, 'middle-column-light.png')
  await runLeg(browser, 'dark', 'middle-column-dark.png')
} finally {
  await browser.close().catch(() => {})
}
summarize()
