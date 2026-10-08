// sc_concurrency_overview_ui.mjs — t261006-17 (CL-2) scenario 3: the Overview
// block a person actually sees.
//
// intent: the executor-panel Overview shows ONE row (Limit [−] N [+] · X at
// work · Y waiting [Save]) with a three-state chip — and NO queue listing,
// NO explanation copy, NO running-ticket rows and NO audit stamp on this
// face. t261008-20 (host order 261008): the block is renamed 'Concurrent
// limit'; it must NOT list the running tickets (the console's left column
// already shows them — the holders face lives there, not here) and the
// 'set by <who> <when>' stamp is gone (the writer's audit record stays in
// the engine audit file, only this display goes). Switching project
// switches limit + numbers with it.
//
// Sub-cases (fixture face served at the page boundary, three chip states):
//  U1 room to start one  (limit 5, 2 at work, 1 waiting) — chip says so.
//  U2 at the limit       (limit 2, 2 at work, 1 waiting) — chip says so.
//  U3 over the limit     (limit 1, 2 at work, 2 waiting) — chip says so AND
//     carries the amber marking.
//  U4 t261008-20 (host order): the running-ticket list is removed — the face
//     renders NO ticket rows at all, holder or otherwise (no 't-hold-1', no
//     't-run-' markup anywhere on the page); the block carries the counts in
//     words instead ('2 at work · 1 waiting').
//  U5 one knob only: exactly one Save control in the block; the queue tickets
//     of the fixture NEVER render (no queue listing); no explanation copy
//     about queue semantics on the face.
//  U6 t261008-20 (host order): NO audit stamp — no 'set by '/'changed by'
//     text even when the audit record travels with the face (the display
//     goes; the engine audit file is out of scope).
//  U7 project switch: same page, beta fixture (different limit) — limit and
//     numbers switch together.
//  U8 UI capture: the Overview block is screenshotted in each of the three
//     chip states (the ticket's evidence requirement), flat into this
//     scenario's shots/ dir.
//
// intent split: numbers-agree-with-ledger and refusals =
// sc_concurrency_face_ledger_route; save/audit = sc_concurrency_save_gate;
// knob boundary arithmetic truth table (10→+ = Unlimited, Unlimited→− = 10) =
// developer L1 on the pure reducer. The page HTML comes from the real
// panel-page module (PANEL_PAGE_HTML seam, same as t260929-03); the
// concurrency face is stubbed at the page boundary — this scenario owns
// what renders, not what the engine serves.
//
// Three states: playwright/chromium missing = ENV_FAIL exit 2; page module or
// Overview block not landed = FAIL naming it (TDD-phase red expected); green
// at gate.
import { createServer } from 'node:http'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { makeCase } from '../t260929-03/lib_panel_harness.mjs'

const REPO = fileURLToPath(new URL('../..', import.meta.url))
const C = makeCase()
const SHOTS = join(REPO, 'integration', 't261006-17', 'shots')

async function loadPageModule() {
  const p = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
  if (!existsSync(p)) return null
  return import(pathToFileURL(p).href)
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(p) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

const mod = await loadPageModule()
if (!mod || typeof mod.PANEL_PAGE_HTML !== 'string') {
  C.case('page-module-present', false,
    'panel-page.ts PANEL_PAGE_HTML seam absent (TDD-phase red expected)')
  C.exit()
}
const html = mod.PANEL_PAGE_HTML
const pw = await loadPlaywright()
if (!pw) { C.envFail('playwright-core', 'not on the declared fallback chain'); C.exit() }

const FACES = {
  // Shape = the real read-face contract (sc_concurrency_face_ledger_route
  // pins it against the engine): at_work/waiting travel with the face.
  alpha: { ok: true, project: 'alpha', limit: 5, unlimited: false, at_work: 2, waiting: 1,
    holders: [{ ticket: 't-run-1', reason: 'running', held_s: 60 },
      { ticket: 't-hold-1', reason: 'human-hold', held_s: 600 }],
    queue: [{ ticket: 't-wait-1', position: 1, waited_s: 30 }] },
  // state switched per U1/U2/U3 by rewriting the stub reply for alpha.
  beta: { ok: true, project: 'beta', limit: 7, unlimited: false, at_work: 1, waiting: 0,
    holders: [{ ticket: 't-b-1', reason: 'running', held_s: 10 }], queue: [] },
}
const STATES = {
  'room to start one': { limit: 5, atWork: 2, waiting: 1 },
  'at the limit': { limit: 2, atWork: 2, waiting: 1 },
  'over the limit': { limit: 1, atWork: 2, waiting: 2 },
}

const srv = createServer((req, res) => {
  res.writeHead(200, { 'content-type': 'text/html' })
  res.end(html)
})
await new Promise(r => srv.listen(0, '127.0.0.1', r))
const base = 'http://127.0.0.1:' + srv.address().port

const { chromium } = pw
let browser
try { browser = await chromium.launch() } catch (e) {
  C.envFail('chromium-launch', String(e).slice(0, 200))
  C.exit()
}
const page = await browser.newPage()
await page.route('**/api/concurrency**', route => {
  const url = new URL(route.request().url())
  const key = url.searchParams.get('project') || 'alpha'
  const face = FACES[key]
  route.fulfill({ status: face ? 200 : 404,
    contentType: 'application/json',
    body: JSON.stringify(face || { ok: false, reason: 'no such project' }) })
})

try { mkdirSync(SHOTS, { recursive: true }) } catch { /* exists */ }

async function openProject(key) {
  // Point the panel at the project the way the console does (the
  // #project=<key> deep link is the page's own selection contract), then wait
  // until the concurrency face has actually rendered.
  // Cache-buster: the face stub replies differ per state under the same URL,
  // and chromium may serve the page's fetch from the memory cache across
  // reloads — a fresh page URL keeps every state a real network round trip.
  await page.goto(base + '?round=' + (round++) + '#project=' + encodeURIComponent(key),
    { waitUntil: 'load' })
  await page.waitForFunction(() => {
    const el = document.querySelector('#concCounts')
    return el && el.textContent && /at work/.test(el.textContent)
  }, { timeout: 5000 }).catch(() => { /* judged by the per-state cases below */ })
}

let idx = 0
let round = 0
for (const [chip, st] of Object.entries(STATES)) {
  FACES.alpha.limit = st.limit
  FACES.alpha.holders = Array.from({ length: st.atWork }, (_, i) => ({
    ticket: i === 1 ? 't-hold-1' : 't-run-' + i, reason: i === 1 ? 'human-hold' : 'running', held_s: 60 }))
  FACES.alpha.queue = Array.from({ length: st.waiting }, (_, i) => ({
    ticket: 't-wait-' + (i + 1), position: i + 1, waited_s: 30 }))
  FACES.alpha.at_work = st.atWork
  FACES.alpha.waiting = st.waiting
  await openProject('alpha')
  const body = (await page.locator('body').innerText()).toLowerCase()
  const blockAt = body.indexOf('concurrent limit')
  const block = blockAt >= 0 ? body.slice(blockAt, blockAt + 1200) : body

  C.case('U' + (idx + 1) + '.block-present[' + chip + ']', blockAt >= 0,
    'the CONCURRENT LIMIT block must render on Overview')
  C.case('U' + (idx + 1) + '.chip-text[' + chip + ']', body.includes(chip),
    'chip must say "' + chip + '", page had: ' + body.slice(0, 160).replace(/\n/g, ' '))
  C.case('U' + (idx + 1) + '.knob-row[' + chip + ']',
    block.includes('limit') && block.includes('at work') && block.includes('waiting') &&
      block.includes('save'),
    'one row: Limit [-] N [+] · X at work · Y waiting [Save]; got: ' + block.slice(0, 200).replace(/\n/g, ' '))
  C.case('U' + (idx + 1) + '.limit-shown[' + chip + ']',
    new RegExp('(−|-|–)\\s*\\n?\\s*' + st.limit).test(block) || block.includes(String(st.limit)),
    'the set limit number must be visible: ' + st.limit)

  if (chip === 'over the limit') {
    const amber = await page.evaluate(() => {
      // The chip whose text says 'over the limit' must carry an amber marking:
      // either an amber-named class or an amber-ish inline color.
      const chip = [...document.querySelectorAll('*')].find(n =>
        n.children.length === 0 && /over the limit/i.test(n.textContent || ''))
      if (!chip) return null
      const cand = [chip, ...chip.querySelectorAll('[class],[style]'),
        ...Array.from(chip.closest('[class]') ? [chip.closest('[class]')] : [])]
      for (const el of cand) {
        const s = (el.getAttribute && (el.getAttribute('class') || '')) + ' ' +
          (el.getAttribute && (el.getAttribute('style') || ''))
        if (/amber|warn|#(b45309|f59e0b|d97706|a16207)/i.test(s)) return s.trim()
      }
      return null
    })
    C.case('U3.amber-marking', !!amber,
      'the over-the-limit chip carries the amber marking, got: ' + String(amber))
  }
  if (chip === 'room to start one') {
    // t261008-20 (host order): the running-ticket list is gone from this
    // block — the fixture's holder and queue tickets must not leak onto the
    // page in any shape (row, markup, or id text).
    const htmlNow = (await page.content()).toLowerCase()
    C.case('U4.no-holder-rows', !htmlNow.includes('t-hold-1') && !htmlNow.includes('t-run-'),
      'no running-ticket rows render on this face (the left column owns that)')
    C.case('U4.counts-in-words', block.includes(st.atWork + ' at work') && block.includes(st.waiting + ' waiting'),
      'the block states the numbers in words: "' + st.atWork + ' at work · ' + st.waiting + ' waiting"; got: ' +
        block.slice(0, 160).replace(/\n/g, ' '))
    C.case('U5.no-queue-listing', !htmlNow.includes('t-wait-1'),
      'host ruling: no queue listing on this face — waiting tickets never render')
    C.case('U5.no-explanation-copy', !/queue (is|orders|reorders|semantics)|first in|fifo/i.test(block),
      'no explanation copy about queue semantics on the face')
    C.case('U5.one-save', (block.match(/save/g) || []).length === 1,
      'one knob, one Save: ' + (block.match(/save/g) || []).length)
    // t261008-20 (host order): the audit stamp display goes — no 'set by'
    // phrase anywhere in the block even though the face carries an ok audit
    // record shape; the engine audit file keeps the record (out of scope).
    C.case('U6.no-audit-stamp', !/set by|changed by|never changed/.test(block),
      'no audit stamp on the face: ' + block.slice(0, 160).replace(/\n/g, ' '))
  }
  await page.screenshot({ path: join(SHOTS, 'overview-chip-' + String(idx + 1) + '-' + chip.replace(/ /g, '-') + '.png'), fullPage: true })
  idx += 1
}

// U7 project switch
{
  FACES.alpha.limit = 5
  await openProject('beta')
  const body = (await page.locator('body').innerText()).toLowerCase()
  const blockAt = body.indexOf('concurrent limit')
  const block = blockAt >= 0 ? body.slice(blockAt, blockAt + 800) : ''
  C.case('U7.limit-switches', block.includes('7'),
    'switching project switches the limit with it (beta=7)')
  C.case('U7.numbers-switch', block.includes('at work') && !block.includes('t-run-1'),
    'the counts line belongs to beta now, and still no ticket rows')
}

await browser.close()
srv.close()
C.exit()
