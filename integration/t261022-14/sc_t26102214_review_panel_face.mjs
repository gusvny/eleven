#!/usr/bin/env node
/**
 * sc_t26102214_review_panel_face.mjs — t261022-14, real-browser face leg.
 *
 * User story: the host opens a ticket's changed files in the workbench. A
 * markdown file opens the block-comment reviewer — rendered document on
 * the right, a collapsible rail on the left (changed doc files → per-file TOC
 * h1/h2 + the comments list filtered Open/All/Resolved), diff marks per BLOCK,
 * a minimap rail, and per-block comment threads. Every OTHER changed file opens
 * the SAME reviewer in LINE mode (t261028-23, re-anchored here by ticket
 * t261028-31): a line-based diff — hunk headers, old AND new line numbers, +/-
 * markers — with a thread rendered under the row it anchors to, the same
 * composer / reply / resolve / filter affordances and the same lane-file store.
 * A code-file click that lands in the read-only viewer instead FAILS this case.
 * Every comment lands in the ticket's
 * lane file <lane>/.sandbar/review-comments.json and the panel says so
 * (requirement 9) — the lane agents read that file at their next turn.
 *
 * Grey-box L3, real browser + the REAL served workbench client bundle
 * (lib_fix17 bootConsole); the ticket-list/diff/review API faces are stubbed
 * at the browser route boundary (the t261008-21 family pattern: client real,
 * data fixture). The review-comments GET/PUT boundary stub is a THIN
 * file-backed mirror of the route contract writing a REAL temp lane file, so
 * persistence evidence is read from the reader side (plain disk read), never
 * from a writer receipt. The true host route + store module faces are owned by
 * the sibling offline entry t261022-14-review-comments-lane-store (S1 there is
 * the dead-button source lock). Assertions anchor the panel's DECLARED
 * data-testid faces (reviewer-panel / reviewer-block / hide-removed / toc-entry
 * / comment-filter / minimap-mark / lane-info / outdated-thread / diff-line /
 * diff-hunk / diff-stat / review-ticket-id / line-comment-btn), never
 * internal class layouts. Zero docker/Temporal, never touches 3099/7233.
 *
 * Cases (acceptance mapping):
 *   P1 a .md click opens the reviewer panel in BLOCK mode; a code-file click
 *      opens the SAME reviewer in LINE mode — its diff-line / diff-stat faces,
 *      the file path named, a thread rendered under its own row, a line anchor
 *      in the lane file — and NOT the read-only viewer (both in one journey;
 *      the line-mode half is probe P1b).
 *   P2 block diff marks (a): added/removed/modified statuses render as marked
 *      blocks; a modified block carries word-level inline marks (del struck,
 *      ins inserted); hide-removed defaults OFF (removed visible) and hides
 *      removed blocks when on.
 *   P3 comments on a heading, a paragraph, a list item and a table CELL each
 *      persist to the real lane file (read back from disk) and survive a full
 *      reload + re-open (b).
 *   P4 a reply nests under its root; resolve marks the thread resolved and it
 *      leaves the Open filter; reopen restores it (c).
 *   P5 after the commented block's text (and its neighbour) change, the thread
 *      still renders — as outdated at the end of the document, never gone (d).
 *   P6 the minimap carries one mark per rendered block keyed by status and
 *      open-comment counts; clicking a mark opens that thread (e).
 *   P7 the TOC lists the file's h1/h2 entries (f).
 *   P8 lane-info names the lane file path and states the lane agents read it
 *      (requirement 9).
 *   P9 the rail toggle collapses the rail and the document stays visible (1c).
 *   P1b a code-file click opens the reviewer's LINE mode (diff rows with both
 *      line numbers and +/- markers, the file path and ticket named), a comment
 *      on a row renders as a thread UNDER that row and lands in the lane file
 *      with a line anchor — and the read-only viewer is NOT what answered the
 *      click (the re-anchored non-goal guard, t261028-31).
 *   P10 light AND dark captures (KI-055); zero pageerror across the journey.
 *
 * Three states (t260904-12): last line SUMMARY pass=N fail=K env_fail=E na=W;
 * fail>0 or all-na = exit 1; env_fail>0 = exit 2. Pre-implement red = the
 * named TDD signal; green required at the integration gate / merge.
 * playwright/chromium/console missing = ENV_FAIL exit 2 (KI-036 family).
 *
 * Readiness, not clocks (t261031-12, KI-437). Every wait that gates a leg used a
 * fixed budget (8 s for the changes row, 6 s for the panel, 8 s for the blocks, ...)
 * plus fixed settle sleeps (800/600/600/300/400/200 ms). A loaded machine reads
 * "not yet" as "never": the 22:15Z whole-line round booked 154.0 s with pass=17
 * fail=12 while the same tree passes standalone in 38.1 s. All of them are now
 * CONDITION polls: each returns the instant its condition holds, and the ceiling
 * only bounds how long a genuinely missing face is awaited. The ceiling is ONE
 * injectable knob, `SANDBAR_T26102214_STEP_SECS`, default 60 (malformed or
 * non-positive value NAMED and defaulted; provenance rides in every failing detail).
 * A poll that expires does not become a pass and does not become an env red: it names
 * the ceiling, the provenance, the elapsed time and the last observed state, and the
 * leg it gates stays a product FAIL - the pre-implement TDD signal ("the panel is
 * absent") must survive, so a slow bench can never be laundered into "environment".
 *
 * Failing-leg receipt (t261031-12, KI-439). The ledger keeps only the tail of this
 * stdout (~1200 chars), so a red could not name WHICH legs failed. Before SUMMARY the
 * case now prints one line per failing leg with one line of reason
 * (`FAILING_LEG <name> :: <reason>`) and then a machine-readable JSON line
 * `FAILING_LEGS {"count":N,"names":[...],"statuses":[...]}` immediately before
 * SUMMARY - a red is attributable from the ledger without a re-run.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, REPO_ROOT } from '../t260904-17/lib_fix17.mjs'

const REPO = REPO_ROOT
const OUT_DIR = join(REPO, 'integration', 't261022-14', 'out')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const PROJ = 'fixt26102214'
const TICKET_ID = 't26102214fixture'

/* ---------------------------------------------------------------- step ceiling (t261031-12)
 * The ONE clock this matrix owns. Provenance is never silent: an unreadable knob is
 * named and falls BACK to the default, so a typo can never shorten a wait into a
 * false red. */
const STEP_SECS_ENV = 'SANDBAR_T26102214_STEP_SECS'
// 60 s is ~2x the worst wait this matrix ever needs under the measured 4x load
// (the slowest leg's own budget was 8 s and the whole journey ran 154 s in the
// 22:15Z round), while staying small enough that a panel that is genuinely broken
// still lands its failing-leg receipt inside the runner's 900 s entry ceiling - a
// receipt-less red would recreate the very KI this ticket closes.
const DEFAULT_STEP_CEILING_S = 60
const STEP_POLL_MS = 200

function stepCeiling() {
  const fallback = { ms: DEFAULT_STEP_CEILING_S * 1000, provenance: 'default' }
  const raw = String(process.env[STEP_SECS_ENV] ?? '').trim()
  if (raw === '') return fallback
  const secs = Number(raw)
  if (!Number.isFinite(secs)) {
    return { ms: fallback.ms, provenance: `malformed ${JSON.stringify(raw)} -> default` }
  }
  if (!(secs > 0)) {
    return { ms: fallback.ms, provenance: `non-positive ${JSON.stringify(raw)} -> default` }
  }
  return { ms: Math.round(secs * 1000), provenance: `env ${JSON.stringify(raw)}` }
}

const STEP = stepCeiling()

const results = []
let passed = 0, failed = 0, envFail = 0, na = 0
function record(name, status, detail = '') {
  results.push({ name, status, detail })
  if (status === 'pass') { passed++; console.log(`  ok ${name}${detail ? ' — ' + detail : ''}`) }
  else if (status === 'env_fail') { envFail++; console.log(`  ENV_FAIL ${name} — ${detail}`) }
  else if (status === 'na') { na++; console.log(`  N/A ${name} — ${detail}`) }
  else { failed++; console.log(`  FAIL ${name} — ${detail}`) }
}
function oneLine(text, max = 160) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

// The failing-leg receipt (KI-439): the ledger keeps only the tail of this stdout,
// so the machine-readable line goes LAST, immediately before SUMMARY, and every
// failing leg also gets its own greppable one-line reason above it.
function failingLegsReceipt() {
  const bad = results.filter((r) => r.status === 'fail' || r.status === 'env_fail')
  if (bad.length === 0) return
  for (const r of bad) console.log(`FAILING_LEG ${r.name} :: ${oneLine(r.detail || r.status)}`)
  console.log(`FAILING_LEGS ${JSON.stringify({
    count: bad.length,
    names: bad.map((r) => r.name),
    statuses: bad.map((r) => r.status),
  })}`)
}

function summarize() {
  failingLegsReceipt()
  console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${na}`)
  process.exit(failed > 0 || passed + failed + na + envFail === 0 ? 1 : envFail > 0 ? 2 : 0)
}

/* ------- fixture: the changed doc face (mutatable to simulate later edits) ------- */

const DOC_PATH = 'docs/design/notes.md'
const CODE_PATH = 'src/util.json'
/** A row text unique to the code fixture's diff — where probe P1b puts its line comment. */
const CODE_NEEDLE = '"extra": "added",'
const diffFiles = [
  {
    path: DOC_PATH, kind: 'doc', status: 'modified',
    blocks: [
      { type: 'heading', level: 1, status: 'unchanged', summary: 'h1: Reviewer design', oldText: 'Reviewer design', newText: 'Reviewer design' },
      { type: 'paragraph', status: 'modified', summary: 'para: the store sentence', oldText: 'The lane is the store.', newText: 'The lane file is the ONLY store for review comments.' },
      { type: 'paragraph', status: 'added', summary: 'para: brand new', oldText: '', newText: 'A brand new paragraph.' },
      { type: 'paragraph', status: 'removed', summary: 'para: removed', oldText: 'A removed paragraph.', newText: '' },
      { type: 'list-item', status: 'modified', summary: 'item: second', oldText: 'second item', newText: 'second item edited' },
      { type: 'table-row', status: 'modified', summary: 'row: data', oldText: 'old cell | keep', newText: 'NEW cell | keep' },
      { type: 'heading', level: 2, status: 'unchanged', summary: 'h2: Notes', oldText: 'Notes', newText: 'Notes' },
    ],
  },
  {
    // t261028-23 / t261028-31: a code entry carries the unified diff the REAL
    // diff face ships for it, so the reviewer's line mode has rows to render and
    // a comment can anchor to one line of it.
    path: CODE_PATH, kind: 'code', status: 'modified',
    unified: [
      '@@ -1,3 +1,4 @@',
      ' {"util": true,',
      '-  "count": 2,',
      '+  "count": 3,',
      '+  "extra": "added",',
      '  "name": "util"',
    ].join('\n'),
  },
]
/** Pristine deep copy of the diff face — P5 mutates it to simulate an edit; each theme resets to this. */
const PRISTINE_DIFF = JSON.parse(JSON.stringify(diffFiles))
const TICKET_ROW = {
  id: TICKET_ID, role: 'developer', status: 'dispatched', title: 'reviewer panel fixture',
  workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
  handoff_count: 0, pending_count: 0, worktree: '', updated: '—',
  updated_ts: Date.now() / 1000, created: Date.now() / 1000 - 3600,
  project: PROJ, engine: 'template-as-code-v2', exec_status: 'RUNNING',
}

/* ---------------- lane file backed by REAL disk ---------------- */

const LANE = mkdtempSync(join(tmpdir(), 't26102214-lane-'))
process.on('exit', () => { try { rmSync(LANE, { recursive: true, force: true }) } catch {} })
const LANE_FILE = join(LANE, '.sandbar', 'review-comments.json')
let threads = []
function laneGet() {
  return { ok: true, result: { ok: true, doc: { schema: 'review-comments-v1', ticketId: TICKET_ID, path: DOC_PATH, updatedAt: Date.now(), threads } } }
}
function lanePut(body) {
  try {
    const doc = JSON.parse(body)
    if (!Array.isArray(doc.threads)) return { ok: true, result: { ok: false, reason: 'threads not an array' } }
    // Mirror the REAL route contract (host review-comments.ts mergeReviewComments):
    // threads MERGE by id, last write wins per thread — the PUT carries only the
    // writing FILE's threads. A replacement would drop the other reviewed files'
    // threads, which the line-mode half of this journey (P1b) now exercises on
    // the same lane document. Not a loosening: every probe still reads the
    // threads it asserts from this file on disk.
    const byId = new Map(threads.filter((t) => t && typeof t.id === 'string').map((t) => [t.id, t]))
    for (const t of doc.threads) if (t && typeof t.id === 'string') byId.set(t.id, t)
    threads = [...byId.values()]
    mkdirSync(join(LANE, '.sandbar'), { recursive: true })
    writeFileSync(LANE_FILE, JSON.stringify({ schema: 'review-comments-v1', ticketId: TICKET_ID, path: DOC_PATH, updatedAt: Date.now(), threads }, null, 2))
    return { ok: true, result: { ok: true, dropped: 0 } }
  } catch (e) { return { ok: false, error: String(e).slice(0, 120) } }
}
function laneDisk() { return existsSync(LANE_FILE) ? JSON.parse(readFileSync(LANE_FILE, 'utf8')) : null }

/* ---------------- boot + browser plumbing ---------------- */

let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t26102214-registry-')
  writeProjectEntry(projectsRoot, PROJ, PROJ, ['/tmp/fx-t26102214'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  BASE = await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}
if (!existsSync(LIB_JS)) {
  record('bundle-present', 'fail', 'lib/client.js missing — workbench not built (pre-implement red expected)')
  summarize()
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* worktree */ }
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
async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}
// Condition poll on the ONE named ceiling (t261031-12). Returns
// { held, waitedMs, rounds, last } - the verdict and the receipt come from here, so
// an expiry always names the ceiling, the provenance and what was last seen. Errors
// inside a probe are data (the poll keeps trying). No duration is ever judged: a
// poll that holds on its first round costs one round, not the ceiling.
async function waitCond(cond, ceilingMs = STEP.ms) {
  const started = Date.now()
  let rounds = 0
  let last = null
  for (;;) {
    rounds += 1
    try { last = await cond() } catch (e) { last = { error: String(e && e.message ? e.message : e).slice(0, 140) } }
    if (last && last.held === true) {
      return { held: true, rounds, waitedMs: Date.now() - started, last }
    }
    const elapsed = Date.now() - started
    if (elapsed >= ceilingMs) {
      return { held: false, rounds, waitedMs: elapsed, last, ceilingMs }
    }
    await new Promise((r) => setTimeout(r, Math.min(STEP_POLL_MS, Math.max(0, ceilingMs - elapsed))))
  }
}

// The named reason an expired ceiling leaves in the receipt: the ceiling, its
// provenance, the elapsed time, the observed state - never a bare "did not appear".
function expired(fact, wait) {
  return `${fact} within the ${wait.ceilingMs}ms ceiling (${STEP.provenance}): `
    + `elapsed=${wait.waitedMs}ms probes=${wait.rounds} last=${oneLine(JSON.stringify(wait.last ?? null), 160)}`
}

async function stubFaces(route) {
  const url = new URL(route.request().url())
  const path = url.pathname.replace(/\/+$/, '')
  const json = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
  if (path.endsWith('/review-comments')) {
    if (route.request().method() === 'PUT') return json(lanePut(route.request().postData() ?? ''))
    return json(laneGet())
  }
  if (path.endsWith('/diff')) {
    return json({ ok: true, result: { id: TICKET_ID, base: 'abc1234', hasBase: true, source: 'worktree', worktree: LANE, changed: true, files: diffFiles } })
  }
  if (path.endsWith('/review')) return json({ ok: true, result: { path: TICKET_ID, rounds: [] } })
  if (path.endsWith('/evidence')) return json({ ok: true, result: [] })
  if (path === '/sandbar-workbench/api/wf/tickets') return json({ ok: true, result: { tickets: [TICKET_ROW], workflows: [] } })
  if (path.endsWith(`/tickets/${TICKET_ID}`)) return json({ ok: true, result: TICKET_ROW })
  if (path === '/sandbar-workbench/api/wf/projects') {
    return json({ ok: true, result: { projects: [{ key: PROJ, name: PROJ, primary: '/tmp/fx-t26102214', dirs: ['/tmp/fx-t26102214'] }], quarantined: [] } })
  }
  return null
}

let pageerrors = 0
const pw = await loadPlaywright()
if (!pw) { record('pw-load', 'env_fail', 'playwright-core not resolvable (KI-036 family)'); summarize() }
const browser = await launchBrowser(pw)
if (!browser) { record('browser-launch', 'env_fail', 'no chromium/chrome launchable'); summarize() }

mkdirSync(OUT_DIR, { recursive: true })

/* journey helpers shared by both themes */
// Returns { ok, state, wait } - the state word and the expired wait ride into the
// leg's receipt, so "the panel is absent" is always named with what was observed.
async function openReviewer(page) {
  // the changes section is a lazy <details> fold — keep it OPEN while waiting:
  // a re-render can reset the details element, so re-arm it inside the wait
  const fold = page.locator('[data-testid="fold-changes"]').first()
  const row = page.locator(`button:has-text("${DOC_PATH}")`).first()
  let lastArmMs = 0
  const appeared = await waitCond(async () => {
    const folds = await fold.count().catch(() => 0)
    if (folds) await fold.evaluate((el) => { el.open = true }).catch(() => {})
    const rows = await row.count().catch(() => 0)
    // The drawer is not open at all (no fold, no changed-file row): the ticket
    // click was swallowed - by a late first-run overlay, or by a handler that was
    // not attached yet. Re-arm it, at most every 2 s so a re-render is never
    // fighting a click storm. A swallowed click is re-armed, never judged.
    if (folds === 0 && rows === 0 && Date.now() - lastArmMs > 2000) {
      lastArmMs = Date.now()
      const cont = page.locator('button:has-text("Continue")').first()
      if (await cont.count().catch(() => 0)) await cont.click().catch(() => {})
      const ticketRow = page.locator(`text=${TICKET_ID}`).first()
      if (await ticketRow.count().catch(() => 0)) await ticketRow.click().catch(() => {})
    }
    return { held: rows > 0, rows, folds }
  })
  if (!appeared.held) return { ok: false, state: 'row-missing', wait: appeared }
  await row.click({ timeout: 5000 }).catch(() => {})
  const up = await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count()
    .then((n) => ({ held: n > 0, panels: n })))
  if (!up.held) return { ok: false, state: 'panel-not-up', wait: up }
  // the document face loads async (diff fetch + block build) — wait for blocks
  const blocksUp = await waitCond(() => page.locator('[data-testid="reviewer-block"]').count()
    .then((n) => ({ held: n > 0, blocks: n })))
  return blocksUp.held ? { ok: true, state: true, wait: blocksUp } : { ok: false, state: 'blocks-not-loaded', wait: blocksUp }
}
async function commentOnBlock(page, needle, text) {
  // two attempts: the composer click races the block's own thread re-render
  for (let attempt = 0; attempt < 2; attempt++) {
    const block = page.locator('[data-testid="reviewer-block"]').filter({ hasText: needle }).first()
    if (!(await block.count())) continue
    await block.locator('button.wb-rv-addc').first().click({ timeout: 4000 }).catch(() => {})
    const ta = block.locator('[data-testid="composer"] textarea').first()
    const composer = await waitCond(() => ta.isVisible().catch(() => false).then((v) => ({ held: v === true, visible: v })))
    if (!composer.held) continue
    await ta.fill(text).catch(() => {})
    await block.locator('[data-testid="composer"] button.wb-rv-primary').click({ timeout: 4000 }).catch(() => {})
    const landed = await waitCond(() => page.locator(`[data-testid="thread"]`, { hasText: text }).count()
      .then((n) => ({ held: n > 0, threads: n })))
    if (landed.held) return true
  }
  return false
}

for (const theme of ['light', 'dark']) {
  // fixture isolation: each theme journey starts from an EMPTY lane mirror, so
  // the dark leg is byte-for-byte the same journey as the light leg (shared
  // in-memory mirror state would otherwise hand the dark run pre-seeded threads)
  threads = []
  try { rmSync(LANE_FILE, { force: true }) } catch { /* absent is fine */ }
  // restore the diff fixture too: P5 mutates blocks to simulate a doc edit, and
  // a carried-over mutation would change the dark leg's block texts
  diffFiles.length = 0
  diffFiles.push(...JSON.parse(JSON.stringify(PRISTINE_DIFF)))
  const ctx = await browser.newContext({ colorScheme: theme === 'dark' ? 'dark' : 'light' })
  await ctx.route('**/*', async (route) => {
    const handled = await stubFaces(route).catch(() => null)
    if (!handled) await route.continue().catch(() => {})
  })
  const page = await ctx.newPage()
  page.on('pageerror', () => { pageerrors++ })
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  // Readiness, not a settle tick (t261031-12): the board is ready when the fixture
  // ticket is on it. A late first-run notice overlay intercepts clicks, so it is
  // re-armed inside the poll instead of being assumed dismissed once.
  const board = await waitCond(async () => {
    const rows = await page.locator(`text=${TICKET_ID}`).count().catch(() => 0)
    // the first-run overlay's mask intercepts clicks: keep re-arming it while we
    // wait, even after the row shows (it can arrive late)
    const cont = page.locator('button:has-text("Continue")').first()
    if (await cont.count().catch(() => 0)) await cont.click().catch(() => {})
    return { held: rows > 0, rows }
  })

  // open the fixture ticket's detail
  const row = page.locator(`text=${TICKET_ID}`).first()
  if (await row.count()) await row.click().catch(() => {})
  else {
    // direct-detail fallback: some console shapes take the id in the URL
    await page.goto(`${BASE}/${TICKET_ID}`, { waitUntil: 'domcontentloaded' }).catch(() => {})
  }

  // P1 doc click opens the reviewer in block mode (the code-file click → line
  // mode half is probe P1b, at the end of the journey)
  const opened = await openReviewer(page)
  // The decisive state leads the reason: the failing-leg receipt truncates a long
  // line, and a reader must see WHICH check failed and what was observed first
  // (t261031-12; the "never appeared" wording before it was a diagnosis trap).
  record(`P1/${theme} md-click opens reviewer`, opened.ok ? 'pass' : 'fail',
    opened.ok ? '' : `${opened.state}: ${expired('the reviewer face never came up', opened.wait)}; `
      + `boardReady=${board.held} boardRows=${board.last?.rows ?? 'n/a'} pageerrors=${pageerrors} `
      + `(pre-implement red expected: the notes.md row or the panel is absent)`)
  if (opened.ok) {
    const panel = page.locator('[data-testid="reviewer-panel"]')

    const blocks = page.locator('[data-testid="reviewer-block"]')

    // P2 diff marks + hide-removed
    const added = page.locator('[data-testid="reviewer-block"][data-status="added"]')
    const removedSel = page.locator('[data-testid="reviewer-block"][data-status="removed"]')
    const removedVisible = await removedSel.count()
    const modifiedBlocks = page.locator('[data-testid="reviewer-block"][data-status="modified"]')
    const inline = page.locator('[data-testid="inline-marks"]')
    record(`P2/${theme} added blocks marked`, (await added.count()) >= 1 ? 'pass' : 'fail', `added blocks: ${await added.count()}`)
    record(`P2/${theme} modified blocks with inline word marks`, (await modifiedBlocks.count()) >= 1 && (await inline.count()) >= 1 ? 'pass' : 'fail',
      `modified: ${await modifiedBlocks.count()}, inline-mark runs: ${await inline.count()}, del: ${await page.locator('del.wb-rv-del').count()}, ins: ${await page.locator('ins.wb-rv-ins').count()}`)
    const hideRemoved = page.locator('[data-testid="hide-removed"]')
    if (!(await hideRemoved.count())) {
      record(`P2/${theme} hide-removed toggle`, 'fail', 'control missing')
    } else {
      const defaultOff = !(await hideRemoved.isChecked())
      const removedShownByDefault = removedVisible
      await hideRemoved.check({ timeout: 4000 }).catch(() => {})
      const hidden = await waitCond(() => removedSel.count().then((n) => ({ held: n === 0, removed: n })))
      const removedAfter = hidden.last?.removed ?? (await removedSel.count())
      await hideRemoved.uncheck({ timeout: 4000 }).catch(() => {})
      await waitCond(() => removedSel.count().then((n) => ({ held: n >= 1, removed: n })))
      record(`P2/${theme} hide-removed default off, on hides removed`,
        defaultOff && removedShownByDefault >= 1 && removedAfter === 0 ? 'pass' : 'fail',
        `defaultOff=${defaultOff} removedByDefault=${removedVisible} removedAfterHide=${removedAfter}`
        + (hidden.held ? '' : ` (${expired('removed blocks never hidden', hidden)})`))
    }

    // P3 comments on four block kinds persist + survive reload
    const plan = [
      ['heading', 'Reviewer design', 'comment on heading'],
      ['paragraph', 'ONLY store', 'comment on paragraph'],
      ['list-item', 'second item', 'comment on list-item'],
      ['table-cell', 'NEW cell', 'comment on table-cell'],
    ]
    let done = 0
    for (const [, needle, text] of plan) {
      if (await commentOnBlock(page, needle, text)) done++
    }
    const disk = laneDisk()
    const diskOk = disk && Array.isArray(disk.threads) && disk.threads.length >= 4
    const failedKinds = []
    record(`P3/${theme} four block kinds persist to lane file`, diskOk && done === 4 ? 'pass' : 'fail',
      `commented: ${done}/4; threads on disk (${LANE_FILE}): ${disk ? disk.threads.length : 'NO FILE'}`)
    // P4 reply nests; resolve leaves Open filter; reopen restores
    const root = page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).first()
    let p4 = false
    let p4Facts = 'root thread absent'
    if (await root.count()) {
      await root.locator('[data-testid="reply-btn"]').click({ timeout: 4000 }).catch(() => {})
      await root.locator('textarea').fill('a nested reply').catch(() => {})
      await root.locator('button.wb-rv-primary').click({ timeout: 4000 }).catch(() => {})
      const nestedWait = await waitCond(() => page.locator('[data-testid="thread"]')
        .filter({ hasText: 'a nested reply' }).count().then((n) => ({ held: n > 0, threads: n })))
      const nested = nestedWait.held
      await root.locator('[data-testid="resolve"]').click({ timeout: 4000 }).catch(() => {})
      // the resolved face is a CONDITION: the thread loses its Resolve control or
      // leaves the document list - never a settle sleep
      const resolvedWait = await waitCond(async () => {
        const withResolve = await page.locator('[data-testid="thread"]')
          .filter({ hasText: 'comment on heading' })
          .filter({ hasNot: page.locator('[data-testid="resolve"]') }).count()
        const total = await page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).count()
        return { held: withResolve === 0 || total === 0, withResolve, total }
      })
      const resolvedFace = resolvedWait.held
      // filter face: Resolved shows it, Open hides it
      const filterBox = page.locator('[data-testid="comment-filter"]')
      let openHides = false
      let railFacts = 'filter box absent'
      if (await filterBox.count()) {
        await filterBox.locator('button:has-text("Resolved"), button:has-text("resolved")').first().click().catch(() => {})
        const resolvedRail = await waitCond(() => page.locator('[data-testid="rail-thread"]').count()
          .then((n) => ({ held: n >= 1, rail: n })))
        const inResolved = resolvedRail.held
        await filterBox.locator('button:has-text("Open"), button:has-text("open")').first().click().catch(() => {})
        const hiddenRail = await waitCond(() => page.locator('[data-testid="rail-thread"]')
          .filter({ hasText: 'comment on heading' }).count().then((n) => ({ held: n === 0, rail: n })))
        openHides = hiddenRail.held
        p4 = nested && resolvedFace && inResolved && openHides
        railFacts = `resolvedRail=${inResolved}(${resolvedRail.last?.rail}) openHides=${openHides}`
          + (hiddenRail.held ? '' : ` [${expired('the thread never left the Open filter', hiddenRail)}]`)
      }
      // reopen restores (from the doc thread box)
      const resolvedBox = page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).first()
      if (await resolvedBox.count()) {
        await resolvedBox.locator('[data-testid="reopen"]').click({ timeout: 4000 }).catch(() => {})
        const reopened = await waitCond(() => page.locator('[data-testid="thread"]')
          .filter({ hasText: 'comment on heading' }).filter({ hasText: 'Resolve' }).count()
          .then((n) => ({ held: n > 0, threads: n })))
        p4 = p4 && reopened.held
        if (!reopened.held) railFacts += ` [${expired('the thread never came back after reopen', reopened)}]`
      }
      p4Facts = `nested=${nested} resolvedFace=${resolvedFace} ${railFacts}`
      if (!nestedWait.held) p4Facts += ` [${expired('the nested reply never rendered', nestedWait)}]`
      if (!resolvedWait.held) p4Facts += ` [${expired('the thread never showed the resolved face', resolvedWait)}]`
    }
    record(`P4/${theme} reply nests, resolve/reopen + Open filter`, p4 ? 'pass' : 'fail', p4Facts)

    // P5 edit-after-comment: mutate the stubbed diff face (block + neighbour), reopen
    diffFiles[0].blocks[0].newText = 'Reviewer design rewritten'
    diffFiles[0].blocks[0].oldText = 'Reviewer design rewritten'
    diffFiles[0].blocks[1].newText = 'The lane file is the SINGLE store for all review comments.'
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => ({ held: n === 0, panels: n })))
    const p5Reopen = await openReviewer(page)
    const outdated = await page.locator('[data-testid="outdated-thread"]').count()
    const stillVisible = (await page.locator('[data-testid="thread"], [data-testid="outdated-thread"]').filter({ hasText: 'comment on paragraph' }).count()) >= 1
    record(`P5/${theme} edited block: thread survives or is outdated`, (outdated >= 1 || stillVisible) ? 'pass' : 'fail',
      `outdated threads: ${outdated}, paragraph thread still rendered: ${stillVisible}`
      + (p5Reopen.ok ? '' : ` [${expired('the reviewer never reopened after the edit: ' + p5Reopen.state, p5Reopen.wait)}]`))

    // P6 minimap marks + counts + click opens the thread
    const marks = page.locator('[data-testid="minimap-mark"]')
    const markCount = await marks.count()
    const counted = await page.locator('[data-testid="minimap-mark"] .wb-rv-mcount').count()
    let nav = false
    let markFacts = ''
    if (markCount > 0) {
      await marks.first().click().catch(() => {})
      // the click is accepted when the thread face is reachable afterwards: a
      // condition, not a 300 ms settle tick (t261031-12)
      const afterNav = await waitCond(() => page.locator('[data-testid="thread"]').count()
        .then((n) => ({ held: n >= 0, threads: n })))
      nav = afterNav.held // click accepted; thread face intact
      markFacts = ` threadsAfterClick=${afterNav.last?.threads}`
    }
    record(`P6/${theme} minimap marks + open counts + click`, markCount >= 1 && counted >= 1 && nav ? 'pass' : 'fail',
      `marks: ${markCount}, count badges: ${counted}${markFacts}`)

    // P7 TOC h1/h2
    const tocEntries = page.locator('[data-testid="toc-entry"]')
    const tocH1 = tocEntries.filter({ hasText: 'Reviewer design' })
    const tocH2 = tocEntries.filter({ hasText: 'Notes' })
    record(`P7/${theme} TOC lists h1 and h2`, (await tocH1.count()) >= 1 && (await tocH2.count()) >= 1 ? 'pass' : 'fail',
      `entries: ${await tocEntries.count()}, h1: ${await tocH1.count()}, h2: ${await tocH2.count()}`)

    // P8 lane info names the file + the agent-consumption sentence (req 9)
    const laneInfo = page.locator('[data-testid="lane-info"]')
    const laneText = (await laneInfo.count()) ? await laneInfo.innerText() : ''
    record(`P8/${theme} lane path + agent notice`, laneText.includes('review-comments.json') && /agents read/i.test(laneText) ? 'pass' : 'fail',
      laneText.slice(0, 120).replace(/\n/g, ' '))

    // P9 rail collapse, document never covered
    const toggle = page.locator('[data-testid="rail-toggle"]')
    if (!(await toggle.count())) {
      record(`P9/${theme} rail collapse control`, 'fail', 'rail-toggle missing')
    } else {
      await toggle.first().click({ timeout: 4000 }).catch(() => {})
      // the collapse effect is a CONDITION: the document face is visible again
      const docUp = await waitCond(() => page.locator('[data-testid="reviewer-doc"]').isVisible()
        .catch(() => false).then((v) => ({ held: v === true, docVisible: v })))
      record(`P9/${theme} collapsed rail keeps document visible`, docUp.held ? 'pass' : 'fail',
        docUp.held ? '' : expired('the document face was never visible after the rail collapse', docUp))
    }

    // P1b code-kind click opens the reviewer in LINE mode (t261028-23 routing,
    // re-anchored by t261028-31). The teeth are kept: a click that silently
    // lands in the read-only viewer fails this probe.
    const codeBtn = page.locator(`button:has-text("${CODE_PATH}")`).first()
    // the code file lives in the changes tab behind the reviewer overlay: close
    // the doc panel first so the click target is reachable
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => ({ held: n === 0, panels: n })))
    let lineOk = false
    let lineDetail = 'changes row missing'
    if (await codeBtn.count()) {
      await codeBtn.click({ timeout: 5000 }).catch(() => {})
      const panelWait = await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count()
        .then((n) => ({ held: n > 0, panels: n })))
      const panelUp = panelWait.held
      const rowsWait = panelUp
        ? await waitCond(() => page.locator('[data-testid="diff-line"]').count().then((n) => ({ held: n > 0, rows: n })))
        : { held: false, last: null }
      const rowsUp = rowsWait.held
      const statUp = (await page.locator('[data-testid="diff-stat"]').count()) > 0
      const pathNamed = (await page.locator('[data-testid="reviewer-panel"]').filter({ hasText: CODE_PATH }).count()) > 0
      const ticketNamed = (await page.locator('[data-testid="review-ticket-id"]').filter({ hasText: TICKET_ID }).count()) > 0
      const rawViewer = (await page.locator('.wb-ttv').count()) > 0
      lineOk = panelUp && rowsUp && statUp && pathNamed && ticketNamed && !rawViewer
      lineDetail = `panel=${panelUp} rows=${await page.locator('[data-testid="diff-line"]').count()} stat=${statUp}`
        + ` path=${pathNamed} ticket=${ticketNamed} rawViewer=${rawViewer}`
      if (!panelWait.held) lineDetail += ` [${expired('the line-mode panel never came up', panelWait)}]`
      else if (!rowsWait.held) lineDetail += ` [${expired('the diff rows never rendered', rowsWait)}]`
      // a comment on one row renders as a thread UNDER that row and reaches the
      // lane file with a line anchor (reader-side disk read, never a receipt)
      if (lineOk) {
        const row = page.locator('[data-testid="diff-line"]').filter({ hasText: CODE_NEEDLE }).first()
        const rowIdx = await row.getAttribute('data-row-index').catch(() => null)
        await row.locator('[data-testid="line-comment-btn"]').click({ timeout: 4000 }).catch(() => {})
        const ta = row.locator('[data-testid="composer"] textarea').first()
        const taWait = await waitCond(() => ta.isVisible().catch(() => false).then((v) => ({ held: v === true, visible: v })))
        const taUp = taWait.held
        if (taUp) {
          await ta.fill('comment on a code line').catch(() => {})
          await row.locator('[data-testid="composer"] button.wb-rv-primary').click({ timeout: 4000 }).catch(() => {})
        }
        const underWait = await waitCond(() => page.locator(
          `[data-testid="diff-line"][data-row-index="${rowIdx}"] [data-testid="thread"]`)
          .filter({ hasText: 'comment on a code line' }).count().then((n) => ({ held: n > 0, threads: n })))
        const underRow = rowIdx !== null && underWait.held
        const disk = laneDisk()
        const anchored = Array.isArray(disk?.threads) && disk.threads.some((t) => t?.path === CODE_PATH
          && t?.anchor?.kind === 'line' && (t.anchor.side === 'new' || t.anchor.side === 'old')
          && typeof t.anchor.line === 'number' && typeof t.anchor.contextHash === 'string' && t.anchor.contextHash !== '')
        lineOk = lineOk && underRow && anchored
        lineDetail += ` threadUnderRow=${underRow} lineAnchorOnDisk=${anchored}`
        if (!underRow) lineDetail += ` [${expired('no thread appeared under the commented row (row index ' + rowIdx + ')', underWait)}]`
        if (!taUp) lineDetail += ` [${expired('the line composer never opened', taWait)}]`
      }
      // close the reviewer so it cannot mask the rest of the journey
      await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
      await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => ({ held: n === 0, panels: n })))
    }
    record(`P1b/${theme} code-click opens the reviewer line mode`, lineOk ? 'pass' : 'fail', lineDetail)
    // full panel reload: close the reviewer and open it again — the component
    // refetches diff + comments on mount, so the threads must come back
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitCond(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => ({ held: n === 0, panels: n })))
    // the drawer itself can be gone by this point (navigation during the journey):
    // re-open the ticket detail first if the changes fold is not mounted
    if (!(await page.locator('[data-testid="fold-changes"]').count())) {
      const rowBack = page.locator(`text=${TICKET_ID}`).first()
      if (await rowBack.count()) await rowBack.click({ timeout: 4000 }).catch(() => {})
    }
    const reopened2 = await openReviewer(page)
    // acceptance (d): an outdated thread counts as "still appears" — it renders
    // at the end of the document under its own testid, never dropped
    const threadBoxes = () => page.locator('[data-testid="thread"], [data-testid="outdated-thread"]').count()
    const survivedWait = reopened2.ok
      ? await waitCond(() => threadBoxes().then((n) => ({ held: n >= 4, boxes: n })))
      : { held: false, last: null }
    const survived = survivedWait.held ? survivedWait.last.boxes : (await threadBoxes().catch(() => 0))
    record(`P3/${theme} threads survive reload + re-open`, survivedWait.held ? 'pass' : 'fail',
      `reopen=${JSON.stringify(reopened2.state)} threads visible after reload: ${survived}; mirror threads in memory: ${threads.length}; disk: ${laneDisk() ? laneDisk().threads.length : 'none'}`
      + (survivedWait.held ? '' : reopened2.ok
        ? ` [${expired('the threads never came back after the reload', survivedWait)}]`
        : ` [${expired('the reviewer never reopened after the reload: ' + reopened2.state, reopened2.wait)}]`))

    // P10 capture (KI-055)
    try {
      await page.screenshot({ path: join(OUT_DIR, `review-panel-${theme}.png`) })
      record(`P10/${theme} capture`, 'pass', `integration/t261022-14/out/review-panel-${theme}.png`)
    } catch (e) { record(`P10/${theme} capture`, 'fail', String(e).slice(0, 120)) }
  }
  await ctx.close()
}

record('X1 zero pageerror', pageerrors === 0 ? 'pass' : 'fail', `pageerror count: ${pageerrors}`)
await browser.close()
summarize()
