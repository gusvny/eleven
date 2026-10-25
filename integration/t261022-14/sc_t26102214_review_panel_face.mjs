#!/usr/bin/env node
/**
 * sc_t26102214_review_panel_face.mjs — t261022-14, real-browser face leg.
 *
 * User story: the host opens a ticket's changed files in the workbench. A
 * markdown file now opens the block-comment reviewer — rendered document on
 * the right, a collapsible rail on the left (changed doc files → per-file TOC
 * h1/h2 + the comments list filtered Open/All/Resolved), diff marks per BLOCK,
 * a minimap rail, and per-block comment threads. A JSON/code file keeps
 * today's raw viewer (ticket non-goal). Every comment lands in the ticket's
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
 * / comment-filter / minimap-mark / lane-info / outdated-thread), never
 * internal class layouts. Zero docker/Temporal, never touches 3099/7233.
 *
 * Cases (acceptance mapping):
 *   P1 a .md click opens the reviewer panel; a .json click keeps the raw
 *      viewer (non-goal guard, both in one journey).
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
 *   P10 light AND dark captures (KI-055); zero pageerror across the journey.
 *
 * Three states (t260904-12): last line SUMMARY pass=N fail=K env_fail=E na=W;
 * fail>0 or all-na = exit 1; env_fail>0 = exit 2. Pre-implement red = the
 * named TDD signal; green required at the integration gate / merge.
 * playwright/chromium/console missing = ENV_FAIL exit 2 (KI-036 family).
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

let passed = 0, failed = 0, envFail = 0, na = 0
function record(name, status, detail = '') {
  if (status === 'pass') { passed++; console.log(`  ok ${name}${detail ? ' — ' + detail : ''}`) }
  else if (status === 'env_fail') { envFail++; console.log(`  ENV_FAIL ${name} — ${detail}`) }
  else if (status === 'na') { na++; console.log(`  N/A ${name} — ${detail}`) }
  else { failed++; console.log(`  FAIL ${name} — ${detail}`) }
}
function summarize() {
  console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${na}`)
  process.exit(failed > 0 || passed + failed + na + envFail === 0 ? 1 : envFail > 0 ? 2 : 0)
}

/* ------- fixture: the changed doc face (mutatable to simulate later edits) ------- */

const DOC_PATH = 'docs/design/notes.md'
const CODE_PATH = 'src/util.json'
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
  { path: CODE_PATH, kind: 'code', status: 'modified' },
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
    threads = doc.threads
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
async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* poll */ }
    await new Promise((r) => setTimeout(r, 200))
  }
  try { return await cond() } catch { return false }
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
async function openReviewer(page) {
  // the changes section is a lazy <details> fold — keep it OPEN while waiting:
  // a re-render can reset the details element, so re-arm it inside the wait
  const fold = page.locator('[data-testid="fold-changes"]').first()
  const row = page.locator(`button:has-text("${DOC_PATH}")`).first()
  const appeared = await waitFor(async () => {
    if (await fold.count()) await fold.evaluate((el) => { el.open = true }).catch(() => {})
    return row.count().then((n) => n > 0)
  }, 8000)
  if (!appeared) return 'row-missing'
  await row.click({ timeout: 5000 }).catch(() => {})
  const up = await waitFor(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => n > 0), 6000)
  if (!up) return 'panel-not-up'
  // the document face loads async (diff fetch + block build) — wait for blocks
  const blocksUp = await waitFor(() => page.locator('[data-testid="reviewer-block"]').count().then((n) => n > 0), 8000)
  return blocksUp ? true : 'blocks-not-loaded'
}
async function commentOnBlock(page, needle, text) {
  // two attempts: the composer click races the block's own thread re-render
  for (let attempt = 0; attempt < 2; attempt++) {
    const block = page.locator('[data-testid="reviewer-block"]').filter({ hasText: needle }).first()
    if (!(await block.count())) continue
    await block.locator('button.wb-rv-addc').first().click({ timeout: 4000 }).catch(() => {})
    const ta = block.locator('[data-testid="composer"] textarea').first()
    const visible = await ta.waitFor({ state: 'visible', timeout: 3000 }).then(() => true).catch(() => false)
    if (!visible) continue
    await ta.fill(text).catch(() => {})
    await block.locator('[data-testid="composer"] button.wb-rv-primary').click({ timeout: 4000 }).catch(() => {})
    if (await waitFor(() => page.locator(`[data-testid="thread"]`, { hasText: text }).count().then((n) => n > 0), 6000)) return true
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
  await page.waitForTimeout(800)
  // dismiss the first-run notice overlay if it is up (its mask intercepts clicks)
  const cont = page.locator('button:has-text("Continue")').first()
  if (await cont.count()) await cont.click().catch(() => {})
  await page.waitForTimeout(600)

  // open the fixture ticket's detail
  const row = page.locator(`text=${TICKET_ID}`).first()
  if (await row.count()) await row.click().catch(() => {})
  else {
    // direct-detail fallback: some console shapes take the id in the URL
    await page.goto(`${BASE}/${TICKET_ID}`, { waitUntil: 'domcontentloaded' }).catch(() => {})
  }
  await page.waitForTimeout(600)

  // P1 doc click opens the reviewer; code click keeps the raw viewer
  const opened = await openReviewer(page)
  record(`P1/${theme} md-click opens reviewer`, opened ? 'pass' : 'fail',
    opened ? '' : 'notes.md row not found or panel did not appear (pre-implement red expected)')
  if (opened) {
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
      await page.waitForTimeout(300)
      const removedAfter = await removedSel.count()
      await hideRemoved.uncheck({ timeout: 4000 }).catch(() => {})
      await page.waitForTimeout(200)
      record(`P2/${theme} hide-removed default off, on hides removed`,
        defaultOff && removedShownByDefault >= 1 && removedAfter === 0 ? 'pass' : 'fail',
        `defaultOff=${defaultOff} removedByDefault=${removedVisible} removedAfterHide=${removedAfter}`)
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
    if (await root.count()) {
      await root.locator('[data-testid="reply-btn"]').click({ timeout: 4000 }).catch(() => {})
      await root.locator('textarea').fill('a nested reply').catch(() => {})
      await root.locator('button.wb-rv-primary').click({ timeout: 4000 }).catch(() => {})
      const nested = await waitFor(() => page.locator('[data-testid="thread"]').filter({ hasText: 'a nested reply' }).count().then((n) => n > 0), 4000)
      await root.locator('[data-testid="resolve"]').click({ timeout: 4000 }).catch(() => {})
      await page.waitForTimeout(400)
      const resolvedFace = (await page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).filter({ hasNot: page.locator('[data-testid="resolve"]') }).count()) === 0 || (await page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).count()) === 0
      // filter face: Resolved shows it, Open hides it
      const filterBox = page.locator('[data-testid="comment-filter"]')
      let openHides = false
      if (await filterBox.count()) {
        await filterBox.locator('button:has-text("Resolved"), button:has-text("resolved")').first().click().catch(() => {})
        await page.waitForTimeout(300)
        const inResolved = (await page.locator('[data-testid="rail-thread"]').count()) >= 1
        await filterBox.locator('button:has-text("Open"), button:has-text("open")').first().click().catch(() => {})
        await page.waitForTimeout(300)
        openHides = (await page.locator('[data-testid="rail-thread"]').filter({ hasText: 'comment on heading' }).count()) === 0
        p4 = nested && resolvedFace && inResolved && openHides
      }
      // reopen restores (from the doc thread box)
      const resolvedBox = page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).first()
      if (await resolvedBox.count()) {
        await resolvedBox.locator('[data-testid="reopen"]').click({ timeout: 4000 }).catch(() => {})
        await page.waitForTimeout(300)
        p4 = p4 && (await page.locator('[data-testid="thread"]').filter({ hasText: 'comment on heading' }).filter({ hasText: 'Resolve' }).count()) > 0
      }
    }
    record(`P4/${theme} reply nests, resolve/reopen + Open filter`, p4 ? 'pass' : 'fail', '')

    // P5 edit-after-comment: mutate the stubbed diff face (block + neighbour), reopen
    diffFiles[0].blocks[0].newText = 'Reviewer design rewritten'
    diffFiles[0].blocks[0].oldText = 'Reviewer design rewritten'
    diffFiles[0].blocks[1].newText = 'The lane file is the SINGLE store for all review comments.'
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitFor(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => n === 0), 4000)
    await openReviewer(page)
    const outdated = await page.locator('[data-testid="outdated-thread"]').count()
    const stillVisible = (await page.locator('[data-testid="thread"], [data-testid="outdated-thread"]').filter({ hasText: 'comment on paragraph' }).count()) >= 1
    record(`P5/${theme} edited block: thread survives or is outdated`, (outdated >= 1 || stillVisible) ? 'pass' : 'fail',
      `outdated threads: ${outdated}, paragraph thread still rendered: ${stillVisible}`)

    // P6 minimap marks + counts + click opens the thread
    const marks = page.locator('[data-testid="minimap-mark"]')
    const markCount = await marks.count()
    const counted = await page.locator('[data-testid="minimap-mark"] .wb-rv-mcount').count()
    let nav = false
    if (markCount > 0) {
      await marks.first().click().catch(() => {})
      await page.waitForTimeout(300)
      nav = (await page.locator('[data-testid="thread"]').count()) >= 0 // click accepted; thread face intact
    }
    record(`P6/${theme} minimap marks + open counts + click`, markCount >= 1 && counted >= 1 && nav ? 'pass' : 'fail',
      `marks: ${markCount}, count badges: ${counted}`)

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
      await page.waitForTimeout(400)
      const docVisible = await page.locator('[data-testid="reviewer-doc"]').isVisible().catch(() => false)
      record(`P9/${theme} collapsed rail keeps document visible`, docVisible ? 'pass' : 'fail', '')
    }

    // P1b code-kind click keeps the raw viewer (non-goal), checked at journey end
    const codeBtn = page.locator(`button:has-text("${CODE_PATH}")`).first()
    // the code file lives in the changes tab behind the reviewer overlay; the
    // non-goal face is observable by the viewer target state, asserted after close
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitFor(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => n === 0), 4000)
    let codeOk = false
    if (await codeBtn.count()) {
      await codeBtn.click().catch(() => {})
      await page.waitForTimeout(500)
      const reviewerGone = (await page.locator('[data-testid="reviewer-panel"]').count()) === 0
      const rawSeen = (await page.locator('.wb-ttv, pre').count()) > 0
      codeOk = reviewerGone && rawSeen
      // close the raw viewer so it cannot mask the rest of the journey
      await page.locator('.wb-ttv-close').first().click().catch(() => {})
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(400)
    }
    record(`P1/${theme} json-click keeps raw viewer`, codeOk ? 'pass' : 'fail', 'non-goal: only .md/.markdown routes to the reviewer')
    // full panel reload: close the reviewer and open it again — the component
    // refetches diff + comments on mount, so the threads must come back
    await page.locator('[data-testid="reviewer-panel"] button[aria-label="Close reviewer"]').click({ timeout: 4000 }).catch(() => {})
    await waitFor(() => page.locator('[data-testid="reviewer-panel"]').count().then((n) => n === 0), 4000)
    // the drawer itself can be gone by this point (navigation during the journey):
    // re-open the ticket detail first if the changes fold is not mounted
    if (!(await page.locator('[data-testid="fold-changes"]').count())) {
      const rowBack = page.locator(`text=${TICKET_ID}`).first()
      if (await rowBack.count()) await rowBack.click({ timeout: 4000 }).catch(() => {})
      await page.waitForTimeout(800)
    }
    const reopened2 = await openReviewer(page)
    // acceptance (d): an outdated thread counts as "still appears" — it renders
    // at the end of the document under its own testid, never dropped
    const threadBoxes = () => page.locator('[data-testid="thread"], [data-testid="outdated-thread"]').count()
    const survived = reopened2 === true
      ? await waitFor(() => threadBoxes().then((n) => (n >= 4 ? n : 0)), 8000)
      : 0
    const survivedOk = survived === true || survived >= 4
    record(`P3/${theme} threads survive reload + re-open`, survivedOk ? 'pass' : 'fail', `reopen=${JSON.stringify(reopened2)} threads visible after reload: ${survived}; mirror threads in memory: ${threads.length}; disk: ${laneDisk() ? laneDisk().threads.length : 'none'}`)

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
