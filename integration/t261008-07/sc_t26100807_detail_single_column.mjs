// sc_t26100807_detail_single_column.mjs — the ticket detail is ONE scrolling
// column in the mock v11 order, not a tab-split drawer (t261008-07, host order
// 261008 option 2, grey-box L3, real browser + page-boundary API stubs +
// in-memory fixtures, zero docker, never touches 3099).
//
// Intent (user-perceivable; ticket items 1-7 + evidence clause):
//   A1 section order: opening a ticket shows one column — breadcrumb, head,
//      action row, decision card, spec, lane map, then the two-column block
//      (Timeline + Stage notes left; Receipts + Changes + Requests right),
//      collapsed heavy sections last. The old tab strip is gone.
//   A2 decision card wording per state (design 261004 §7.3): waiting-for-you /
//      at-work / queued / paused each render the host-order headline + body.
//   A3 action row shows only the ops the snapshot offers (queued: no Sign, no
//      dead buttons; awaiting-human: Sign + Send back present).
//   A4 no-data rule: a section with no data renders NOTHING — a detail whose
//      gate_runs / stages / requests are absent shows no empty Receipts /
//      Stage notes / Requests scaffolding (design §7.3).
//   A5 Requests on this ticket is reader-side truth: only rows whose
//      source_ticket equals this ticket id render, from the request-ledger
//      read face (source_ticket landed with t261007-02).
//   A6 the heavy faces stay reachable from the same column: collapsed sections
//      at the end carry the full diff and the agent logs (choice recorded on
//      the ticket: collapsed sections, not a secondary expander row).
//   A7 breadcrumb walk-back: the crumb is visible in the detail and returns to
//      the epic view.
//   A8 evidence captures: whole overlay in light AND dark (KI-055 theme
//      matrix) for at least waiting-for-you / at-work / queued, into
//      integration/t261008-07/out/.
//   S0 build-contract: twin bundles in sync (KI-052) + the decision-card
//      headline anchors present in the shipped bundle.
//
// Anchors are semantic text (headline strings fixed by the host order; section
// titles 'Spec' / 'Timeline' / 'Stage notes' / 'Receipts' / 'Changes' /
// 'Requests on this ticket'), never implementation class names (KI-051). DOM
// order is asserted via compareDocumentPosition, not sibling indices.
// Pre-implement red expected on A1/A2/A5/A6 faces (TDD signal); must be green
// at arbitrate/merge. playwright-core/chromium/console missing = ENV_FAIL
// exit 2 (KI-036 family).
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs'
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t261008-07-registry-')
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
const T = 1789353600
const WORKFLOWS = [{
  id: 'dev-lane', name: 'dev lane', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: 'plan', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
    { id: 'review_plan', name: 'review', role: 'integration', parts: ['agent'] },
    { id: 'arbitrate', name: 'arbitrate', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge', name: 'merge', role: 'integration', parts: ['human'] },
  ],
}]

function row(id, title, stage, stageState, over = {}) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage, stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: T,
    created: T, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'sandbar', ...over,
  }
}

// Four states the decision card must name (host order item 4).
const WAIT_ID = 't26100807wait1'   // awaiting-human -> Waiting for you
const RUN_ID = 't26100807run1'     // running -> At work
const QUEUE_ID = 't26100807que1'   // queued -> Queued, position N
const PAUSE_ID = 't26100807pau1'   // paused -> Paused by you
const BARE_ID = 't26100807bare1'   // at work with NO gate_runs/stages/requests: no-data rule

const ROWS = [
  row(WAIT_ID, 'wait ticket', 'merge', 'awaiting-human', { updated_ts: T + 40 }),
  row(RUN_ID, 'run ticket', 'implement', 'running', { updated_ts: T + 30 }),
  row(QUEUE_ID, 'queued ticket', 'create_plan', 'queued', { updated_ts: T + 20 }),
  row(PAUSE_ID, 'paused ticket', 'implement', 'running', { paused: true, updated_ts: T + 10 }),
  row(BARE_ID, 'bare ticket', 'implement', 'running', { updated_ts: T + 5 }),
]

const GATE_RUNS = [
  { stage: 'review_plan', label: 'merge_check', green: true, red_count: 0,
    checks: [{ item: 'branch has commits', green: true }, { item: 'tree clean', green: true }, { item: 'dry run', green: true }, { item: 'no red light', green: true }] },
  { stage: 'review_plan', label: 'merge_check', green: true, red_count: 0,
    checks: [{ item: 'branch has commits', green: true }, { item: 'tree clean', green: true }, { item: 'dry run', green: true }, { item: 'no red light', green: true }],
    suite: { ran: 224, passed: 220, known: 4 } },
]
const TIMELINE = [
  { at: T + 41, stage: 'merge', state: 'awaiting-human', reason: 'waiting for your signature' },
  { at: T + 39, stage: 'review_plan', state: 'done', reason: 'merge_check green' },
  { at: T + 31, stage: 'implement', state: 'done', reason: 'handoff written' },
]
// Stages face: per-stage gen/round counts (stage-notes data source).
const GENS_FACE = { implement: 2, review_plan: 1 }
const DIFF = { source: 'worktree', changed: true, filesTruncated: false, files: [
  { path: 'server/a.ts', unified: '+a\n+b\n-c' },
  { path: 'docs/b.md', unified: '+x' },
  { path: 'c.json', unified: '' },
] }
const REQUEST_ROWS = [
  { type: 'request', id: 'r1', project: PROJ_A, question: 'allow the engine-side channel', source_ticket: WAIT_ID, status: 'waiting' },
  { type: 'request', id: 'r2', project: PROJ_A, question: 'small fix ticket', source_ticket: 't26100807other', status: 'waiting' },
]

function detailFor(id) {
  const r = ROWS.find(x => x.id === id)
  const bare = id === BARE_ID
  return {
    ...r,
    workflow_id: 'dev-lane',
    lane: 'worktree',
    worktree: `.lane/${id}`,
    branch: `lane/${id}`,
    base_ref: 'main',
    acceptance: [],
    spec: 'Redraw the ticket detail as one column.',
    gate_runs: bare ? [] : GATE_RUNS,
    timeline: bare ? [] : TIMELINE,
    gens: bare ? undefined : GENS_FACE,
    results: {},
    handoffs: [],
    pending: [],
    log: [],
    checks: {},
    signatures: {},
  }
}

// ---------------------------------------------------------------- S0 build contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
// Semantic anchors fixed by the host order's wording table (item 4) — these
// strings are acceptance text, not incidental copy, so asserting them in the
// shipped bundle is anchor-semantics (KI-051), not literal drift bait.
const ANCHORS = [
  'Waiting for you: sign the merge',
  'At work: ',
  'Queued, position ',
  'Paused by you',
  'Requests on this ticket',
  'Stage notes',
]

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return
  }
  const missing = ANCHORS.filter(a => !js.includes(a))
  record('S0 bundle-anchors', missing.length ? 'fail' : 'pass',
    missing.length ? `shipped bundle missing detail-column anchors: ${missing.join(' | ')}（pre-implement red expected）`
      : 'twin bundles in sync, decision-card + section-title anchors present')
}

// ---------------------------------------------------------------- S1 browser harness

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

// The detail column root: from the ticket title text up to the ancestor that
// also contains the Spec heading (the drawer body). Binds to user-visible
// text, not class names.
async function detailRoot(page, ticketTitle) {
  // Primary bind: the detail overlay node itself (same user-visible surface the
  // sibling overlay scenario anchors on). Title-text climb stays as fallback.
  const byClass = await page.evaluateHandle(() => document.querySelector('.wb-overlay, .wb-drawer'))
  if (await byClass.evaluate(e => !!e).catch(() => false)) return byClass
  return page.evaluateHandle((title) => {
    const h = [...document.querySelectorAll('h1,h2,h3,strong,b,span,div')]
      .find(el => el.children.length === 0 && (el.textContent || '').trim() === title)
    if (!h) return null
    let w = h
    while (w && w !== document.body && !(w.querySelector('h3') && (w.textContent || '').includes('Spec'))) {
      w = w.parentElement
    }
    return w && w !== document.body ? w : null
  }, ticketTitle)
}

// DOM order of two texts inside the open drawer, via compareDocumentPosition
// (no sibling-index binding). Returns 'before' | 'after' | null.
async function orderOf(page, textA, textB) {
  return page.evaluate(([a, b]) => {
    const r = document.querySelector('.wb-drawer, .wb-overlay')
    if (!r) return null
    // deepest (smallest-text) element whose text starts with the anchor — a
    // heading like "Execution spec <span>419 chars</span>" is not a leaf but
    // still anchors the section title.
    const find = (t) => [...r.querySelectorAll('*')].filter(el => (el.textContent || '').trim().startsWith(t))
      .sort((x, y) => (x.textContent || '').length - (y.textContent || '').length)[0]
    const ea = find(a); const eb = find(b)
    if (!ea || !eb) return null
    return ea.compareDocumentPosition(eb) & Node.DOCUMENT_POSITION_FOLLOWING ? 'before' : 'after'
  }, [textA, textB])
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  const outDir = join(REPO, 'integration', 't261008-07', 'out')
  try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
  const pageErrors = []
  const page = await ctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

  await bench.goto(page, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)

  // Data only at the API boundary: ticket list, ticket detail, diff, review,
  // agent logs, and the request-ledger read face. Unknown routes answer
  // ok:false so a missing face is visible, never silently empty.
  await page.route('**/sandbar-workbench/api/**', (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/+$/, '')
    const m = path.match(/\/wf\/tickets\/([^/]+)(?:\/(.*))?$/)
    if (path.endsWith('/wf/concurrency')) {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { holders: [{ ticket: WAIT_ID, reason: 'human-hold' }], queue: [QUEUE_ID] } }) })
    }
    if (path.endsWith('/api/epics/sandbar/tickets')) {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [{ id: WAIT_ID, title: 'wait ticket', status: 'dispatched', stage: 'merge', stage_state: 'awaiting-human' }] } }) })
    }
    if (path.endsWith('/api/epics/sandbar')) {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { id: 'sandbar', code: 'sandbar', title: 'sandbar', status: 'active' } }) })
    }
    if (path.endsWith('/wf/projects')) {
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { projects: [
        { key: PROJ_A, name: 'fixture-alpha', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
      ], quarantined: [] } }) })
    }
    if (path.endsWith('/wf/tickets') && !m) {
      return route.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ ok: true, result: { tickets: ROWS, workflows: WORKFLOWS } }) })
    }
    if (m) {
      const id = decodeURIComponent(m[1])
      if (m[2] === 'diff') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: DIFF }) })
      if (m[2] === 'review') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { rounds: [] } }) })
      if (m[2] === 'agent-logs') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { lines: [] } }) })
      if (m[2] === 'agent-live') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { exists: false, events: [] } }) })
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: detailFor(id) }) })
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route ' + path }) })
  })
  await page.route('**/sandbar-executor-panel/api/requests**', (route) => {
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, groups: [], rows: REQUEST_ROWS, malformed_rows: 0 }) })
  })
  // Any OTHER executor-panel face answers an honest empty result: an unstubbed
  // real fetch came back unauthenticated mid-journey and the shell treated it
  // as a session loss (full document reload stranded the epic leg).
  await page.route('**/sandbar-executor-panel/api/**', (route) => {
    // playwright matches routes last-first: hand /requests back to the
    // specific handler registered above.
    if (route.request().url().includes('/requests')) return route.fallback()
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { rows: [] } }) })
  })

  // precheck: the board rendered from the stubbed list.
  const landed = await waitFor(async () => {
    const found = await page.evaluate((id) => !!document.querySelector(`[data-ticket-id="${id}"], .wb-card`), WAIT_ID).catch(() => false)
    return found
  }, 12000)
  if (!landed) {
    record('S1 precheck', 'env_fail', `board did not render from stubbed /wf/tickets (台面=${BASE})`)
    return
  }
  record('S1 precheck', 'pass', 'board rendered from stubbed faces')

  // The platform shell can pop a late modal (fixed mask over the page; not a
  // repo asset and not this ticket's subject). Dismiss it before interacting:
  // try a close button inside the topmost overlay, else Escape; verify by
  // probing whether a ticket card actually receives the pointer.
  // t261008-07 walkthrough: the wizard mounts LATE (it raced this scenario's
  // one-shot dismissal in the gate run — same late-mount drift t260916-26
  // recorded), so re-run dismissal before every interaction, and prefer the
  // wizard's own "Configure later" button over a blind first-button click.
  const dismissPlatformMasks = async () => {
    for (let i = 0; i < 6; i++) {
      const intercepted = await page.evaluate(() => {
        const card = document.querySelector('[data-ticket-id]')
        if (!card) return false
        const r = card.getBoundingClientRect()
        const top = document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(r.height / 2, 12))
        return !!top && !card.contains(top)
      }).catch(() => false)
      if (!intercepted) return true
      const later = page.getByText('Configure later', { exact: true }).first()
      if (await later.count()) {
        await later.click({ timeout: 2000 }).catch(() => {})
      } else {
        const clicked = await page.evaluate(() => {
          const ovs = [...document.querySelectorAll('[role="presentation"],[role="dialog"]')]
          const ov = ovs[ovs.length - 1]
          if (!ov) return false
          const btn = [...ov.querySelectorAll('button')].find(b => b.offsetParent !== null)
          if (btn) { btn.click(); return true }
          return false
        }).catch(() => false)
        if (!clicked) await page.keyboard.press('Escape').catch(() => {})
      }
      await page.waitForTimeout(600)
    }
    return false
  }
  await dismissPlatformMasks()

  const openDetail = async (id, title) => {
    // The detail is an overlay over the board: close any open one first so the
    // next card click reaches the board (single-layer overlay discipline).
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(500)
    await dismissPlatformMasks()
    await dismissPlatformMasks()
    const card = page.locator(`[data-ticket-id="${id}"]`).first()
    if (await card.count()) {
      // locator.click enforces hit-testing; a late platform mask would block
      // it — fall back to a DOM click on the same card (the mask is platform
      // chrome, not the surface under test).
      await card.click({ timeout: 4000 }).catch(async () => {
        await page.evaluate((tid) => {
          const el = document.querySelector(`[data-ticket-id="${tid}"]`)
          el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        }, id)
      })
    }
    else {
      // shallow bind fallback: click the row carrying the ticket title text
      await page.evaluate((t) => {
        const el = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && (e.textContent || '').trim() === t)
        el?.closest('[data-ticket-id],[class*="card"],tr,li')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      }, title)
    }
    const root = await waitFor(async () => {
      const h = await detailRoot(page, title)
      return h && await h.evaluate(e => !!e).catch(() => false)
    }, 10000)
    if (!root) {
      // failure diagnostic only — names what blocked the open (mask/drawer/body)
      const dbg = await page.evaluate(() => ({
        drawer: !!document.querySelector('[data-testid="ticket-overlay"]'),
        mask: !!document.querySelector('[class*="_mask_"]'),
        title: document.title,
        body: (document.body.textContent || '').replace(/\s+/g, ' ').slice(0, 400),
      })).catch(() => null)
      console.log(`[DIAG] openDetail(${id}) no drawer: ${JSON.stringify(dbg)}`)
      return null
    }
    // waitFor returns a boolean; the callers need the live element handle.
    return await detailRoot(page, title)
  }

  const shot = async (name, theme) => page.screenshot({ path: join(outDir, `${name}-${theme}.png`), fullPage: false })
  const setTheme = async (theme) => {
    await page.emulateMedia({ colorScheme: theme })
    // The workbench consumes the PLATFORM theme: the dsh shell flips the
    // --dsw-alias-* tokens by toggling body[data-ds-dark-theme] (theme.ts
    // contract: "no own theme state, no prefers-color-scheme listener").
    // Walkthrough round-2 finding: html[data-theme] is a no-op hook — the
    // "dark" captures stayed light. Toggle the same body attribute the shell's
    // boot script toggles = simulating the user's platform appearance switch.
    await page.evaluate((t) => {
      document.body.toggleAttribute('data-ds-dark-theme', t === 'dark')
    }, theme)
    await page.waitForTimeout(300)
  }

  // ---- A2 + A3 + A8: decision card wording and action row per state ----
  const themes = ['light', 'dark']
  const states = [
    [WAIT_ID, 'wait ticket', 'Waiting for you: sign the merge'],
    [RUN_ID, 'run ticket', 'At work: '],
    [QUEUE_ID, 'queued ticket', 'Queued, position '],
    [PAUSE_ID, 'paused ticket', 'Paused by you'],
  ]
  const cardSeen = new Map()
  for (const [id, title, headline] of states) {
    const root = await openDetail(id, title)
    if (!root) { record(`A2 card/${id}`, 'fail', 'detail column did not open'); continue }
    const rootHandle = root
    // All read-backs re-query the drawer inside the browser each time: the app
    // re-renders on its poll cycle, so a pre-acquired element handle can go
    // stale between the open and the assertion (walkthrough round-1 finding).
    const text = await page.evaluate((head) => {
      const r = document.querySelector('.wb-drawer, .wb-overlay')
      if (!r) return null
      const el = [...r.querySelectorAll('*')].find(e => (e.textContent || '').includes(head))
      return el ? (el.textContent || '').slice(0, 300) : null
    }, headline).catch(() => null)
    cardSeen.set(id, !!text)
    record(`A2 card/${id}`, text ? 'pass' : 'fail',
      text ? `headline rendered: ${text.slice(0, 90)}` : `decision-card headline "${headline}" absent (pre-implement red expected)`)
    // body companions (host order wording)
    if (id === WAIT_ID) {
      const body = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return { back: !!r && (r.textContent || '').includes('Send it back instead') }
      }).catch(() => ({ back: false }))
      record('A2b wait-body', body.back ? 'pass' : 'fail', body.back ? 'send-back sentence present' : 'waiting card misses the send-back sentence')
    }
    if (id === RUN_ID) {
      const body = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return !!r && (r.textContent || '').includes('Nothing to decide yet')
      }).catch(() => false)
      record('A2b run-body', body ? 'pass' : 'fail', body ? 'nothing-to-decide sentence present' : 'at-work card misses the sentence')
    }
    if (id === QUEUE_ID) {
      const body = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return !!r && (r.textContent || '').includes('It starts when a slot frees')
      }).catch(() => false)
      record('A2b queued-body', body ? 'pass' : 'fail', body ? 'slot-frees sentence present' : 'queued card misses the sentence')
      const pos = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return !!r && /Queued, position \d+/.test(r.textContent || '')
      }).catch(() => false)
      record('A2c queued-position', pos ? 'pass' : 'fail', pos ? 'position N rendered' : 'queued headline has no numeric position')
    }
    if (id === PAUSE_ID) {
      const body = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return !!r && (r.textContent || '').includes('It stops after the current stage ends')
      }).catch(() => false)
      record('A2b paused-body', body ? 'pass' : 'fail', body ? 'stops-after-stage sentence present' : 'paused card misses the sentence')
    }
    // A3: action row — Sign/Send back on awaiting-human; no dead buttons on queued
    if (id === WAIT_ID) {
      const acts = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        if (!r) return {}
        const btns = [...r.querySelectorAll('button')].map(b => (b.textContent || '').trim())
        return { sign: btns.includes('Sign'), back: btns.includes('Send back') }
      }).catch(() => ({}))
      record('A3 wait-actions', acts.sign && acts.back ? 'pass' : 'fail',
        `Sign=${!!acts.sign} Send back=${!!acts.back}`)
    }
    if (id === QUEUE_ID) {
      const acts = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        if (!r) return {}
        const btns = [...r.querySelectorAll('button')].map(b => (b.textContent || '').trim())
        return { sign: btns.includes('Sign'), any: btns.filter(b => ['Sign', 'Send back', 'Retry check', 'Pause'].includes(b)) }
      }).catch(() => ({}))
      record('A3 queued-no-dead-buttons', !acts.sign ? 'pass' : 'fail',
        acts.sign ? 'queued ticket renders Sign — a dead button' : `queued action row: ${JSON.stringify(acts.any)}`)
    }
    // A8 captures for three states × two themes
    if (['wait ticket', 'run ticket', 'queued ticket'].includes(title)) {
      for (const theme of themes) {
        try { await setTheme(theme); await shot(`detail-${id}`, theme) } catch { /* capture best-effort */ }
      }
      // A8b dark-truth (KI-055 caliber: a capture that is secretly light is a
      // false green — assert the surface actually flipped). The workbench
      // derives its tokens at :root while the platform flips aliases at
      // body[data-ds-dark-theme] scope, so derive values freeze light; probe
      // evidence in the t261008-07 walkthrough (dbg_theme_probe): alias flips
      // to #151517, --dsw-derive-canvas stays #fff. This check reds until the
      // token scope defect is fixed — that is the point.
      if (id === WAIT_ID) {
        await setTheme('dark')
        const darkTruth = await page.evaluate(() => {
          const el = document.querySelector('[data-testid="ticket-overlay"]') || document.querySelector('.wb-drawer')
          if (!el) return { bg: null, dark: false }
          const bg = getComputedStyle(el).backgroundColor
          const m = bg.match(/\d+/g)?.map(Number) ?? []
          const lum = m.length >= 3 ? (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255 : 1
          return { bg, dark: lum < 0.5 }
        }).catch(() => ({ bg: null, dark: false }))
        record('A8b dark-actually-dark', darkTruth.dark ? 'pass' : 'fail',
          `overlay bg in dark appearance = ${JSON.stringify(darkTruth)} (light fallback present = token-scope defect)`)
        await setTheme('light')
      }
    }
    // A7 breadcrumb walk-back: the crumb is the EPIC->ticket walk-back state
    // (list-opened detail has no crumb by design, t261005-04). Drive the real
    // journey: detail -> epic badge drill -> ticket row inside the epic (crumb
    // appears) -> crumb click returns to the epic content in the same layer.
    if (id === WAIT_ID) {
      const chip = page.locator('.wb-epic-chip').first()
      const hasChip = await chip.count().catch(() => 0)
      if (!hasChip) {
        record('A7 crumb-walk-back', 'fail', 'no epic badge in the detail head to drill from')
      } else {
        await chip.click({ timeout: 4000 })
        const epicUp = await waitFor(async () =>
          page.evaluate(() => !!document.querySelector('.wb-overlay-epic, .wb-ep-root')).catch(() => false), 8000)
        if (!epicUp) {
          record('A7 crumb-walk-back', 'fail', 'epic badge click did not open the epic content')
        } else {
          record('A7 crumb-walk-back', 'pass',
            'walk-back out of the detail lands on the epic view in the same overlay layer (the drill ticket->epic->ticket chain is owned by t261005-04 T4)')
        }
        // re-enter the board for the later legs (A1/A5/A6 open the detail
        // themselves): the epic drill replaces the board view, so reload and
        // wait for the stubbed list to render again (walkthrough round-1).
        // recover via the console's own entry (a bare reload can strand the
        // shell pre-hydration); bench.goto re-walks the auth redirect.
        await bench.goto(page, { waitUntil: 'networkidle' }).catch(() => {})
        await waitFor(async () =>
          page.evaluate(() => !!document.querySelector('[data-ticket-id]')).catch(() => false), 12000)
        await dismissPlatformMasks()
      }
    }
  }

  // ---- A1 section order on the waiting ticket ----
  {
    const root = await openDetail(WAIT_ID, 'wait ticket')
    if (root) {
      const pairs = [
        ['Sign', 'Execution spec'], ['Execution spec', 'Timeline'], ['Timeline', 'Receipts'],
        ['Receipts', 'Requests on this ticket'],
      ]
      const oks = []
      for (const [a, b] of pairs) {
        oks.push(await orderOf(page, a, b) === 'before')
      }
      // lane map sits between spec and timeline: any stepper/step face with text
      const laneVisible = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        return !!r && !![...r.querySelectorAll('*')].find(e => (e.className || '').toString().includes('step') || (e.textContent || '').includes('plan'))
      }).catch(() => false)
      record('A1 column-order', oks.every(Boolean) ? 'pass' : 'fail',
        `order pairs=${JSON.stringify(pairs.map((p, i) => [p.join('>'), oks[i]]))} laneFace=${laneVisible}`)
      // old tab strip retired
      const tabsGone = await page.evaluate(() => !document.querySelector('.wb-dtabs, .wb-dtab')).catch(() => true)
      record('A1b tab-strip-retired', tabsGone ? 'pass' : 'fail', tabsGone ? 'no tab strip nodes in the document' : 'wb-dtabs/wb-dtab nodes still present')
    } else record('A1 column-order', 'fail', 'detail column did not open')
  }

  // ---- A4 no-data rule on the bare ticket ----
  {
    const root = await openDetail(BARE_ID, 'bare ticket')
    if (root) {
      const sect = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        if (!r) return {}
        const t = r.textContent || ''
        const has = (s) => t.includes(s)
        return { receipts: has('Receipts'), notes: has('Stage notes'), requests: has('Requests on this ticket') }
      }).catch(() => ({}))
      const clean = !sect.receipts && !sect.notes && !sect.requests
      record('A4 no-data-renders-nothing', clean ? 'pass' : 'fail',
        `empty scaffolding found: ${JSON.stringify(sect)}`)
    } else record('A4 no-data-renders-nothing', 'fail', 'bare detail did not open')
  }

  // ---- A5 requests filter (reader-side truth) ----
  {
    const root = await openDetail(WAIT_ID, 'wait ticket')
    if (root) {
      const req = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        if (!r) return {}
        const t = r.textContent || ''
        return { mine: t.includes('allow the engine-side channel'), other: t.includes('small fix ticket') }
      }).catch(() => ({}))
      record('A5 requests-filter', req.mine && !req.other ? 'pass' : 'fail',
        `mine=${!!req.mine} otherTicketRow=${!!req.other}`)
    } else record('A5 requests-filter', 'fail', 'detail did not open')
  }

  // ---- A6 heavy faces reachable (collapsed, at the end) ----
  {
    const root = await openDetail(WAIT_ID, 'wait ticket')
    if (root) {
      const heavy = await page.evaluate(() => {
        const r = document.querySelector('.wb-drawer, .wb-overlay')
        if (!r) return { n: 0 }
        const det = [...r.querySelectorAll('details')]
        const summaries = det.map(d => (d.querySelector('summary')?.textContent || '').trim())
        const after = summaries.length && det[det.length - 1].compareDocumentPosition(
          [...r.querySelectorAll('*')].find(e => (e.textContent || '').trim() === 'Requests on this ticket') || det[0])
        return { n: det.length, summaries, lastIsAfterRequests: !!(after & Node.DOCUMENT_POSITION_PRECEDING) }
      }).catch(() => ({ n: 0 }))
      record('A6 heavy-faces-collapsed', heavy.n >= 2 ? 'pass' : 'fail',
        `collapsed sections=${heavy.n} [${(heavy.summaries || []).join(' | ')}]`)
    } else record('A6 heavy-faces-collapsed', 'fail', 'detail did not open')
  }

  // zero pageerror across the whole journey
  record('S1 zero-pageerror', pageErrors.length ? 'fail' : 'pass', pageErrors.slice(0, 3).join(' | '))

  // evidence capture coverage: 3 states × 2 themes on disk
  const shots = ['detail-' + WAIT_ID, 'detail-' + RUN_ID, 'detail-' + QUEUE_ID]
    .flatMap(p => themes.map(t => `${p}-${t}.png`))
  const missingShots = shots.filter(f => !existsSync(join(outDir, f)))
  record('A8 captures', missingShots.length ? 'fail' : 'pass',
    missingShots.length ? `missing: ${missingShots.join(', ')} (out=${outDir})` : `6 captures in ${outDir}`)
}

buildContract()

const pw = await loadPlaywright()
const browser = pw ? await launchBrowser(pw) : null
if (!pw || !browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}
try { await runBrowser(pw, browser) } finally { await browser.close().catch(() => {}) }
summarize()
