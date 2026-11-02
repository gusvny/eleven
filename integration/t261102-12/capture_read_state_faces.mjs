#!/usr/bin/env node
/**
 * t261102-18 UI evidence: real screenshots of the delivered named-read-state faces.
 *
 * Why this script exists: the merge gate demands top-level `*.png` under
 * `<lane>/.sandbar/screenshots` when a change touches UI paths. `server/ui-check/capture.mjs`
 * cannot shoot these two faces: its `--fixtures` mode only serves SUCCESS bodies
 * (`{ok:true,result}`), while the whole point of this ticket is the ERROR receipt
 * (`{ok:false, kind:'workflow_task_failed', read_face:{...}}`). So this script boots the
 * same isolated bench capture-lane.mjs builds and drives the page itself.
 *
 * What it proves with pixels (the two faces the fix delivers):
 *   read-state-row-chip.png    the LEFT COLUMN row of an inspection ticket whose read is
 *                              deterministic, carrying the NAMED chip
 *                              (`data-read-state="workflow_task_failed"`) instead of a
 *                              "query timed out, refresh to retry" title;
 *   read-state-panel.png       the ticket drawer rendering `ReadStatePanel` for that same
 *                              state: the located cause from the execution history, the
 *                              queue the execution really polls, and the words that say
 *                              no further read is scheduled.
 *
 * How the data reaches the page (no product code is stubbed out): the REAL console boots
 * the LANE's workbench build (`lib/client.js` symlinked by `buildTempProfile`), and this
 * script intercepts only the two host read endpoints in the browser
 * (`/wf/inspection/tickets`, `/wf/tickets`, `/wf/tickets/<id>`) to deliver the very
 * receipt shapes the engine now produces. Everything the panel renders comes from those
 * receipts.
 *
 * Hard rules honoured:
 *   - never port 3099 (free-port pick + explicit refusal if it resolves to 3099);
 *   - the bench is temporary (temp DSH_HOME/profile/registry), torn down in every
 *     terminal state (normal / error / timeout / signal), no orphan chromium;
 *   - screenshots are written FRESH each run (unlink first), asserted PNG + >5 kB, and
 *     land FLAT in the output dir (the gate reads top-level only);
 *   - no network, no docker, no product write.
 *
 * Usage: node integration/t261102-12/capture_read_state_faces.mjs [--lane <dir>] [--out <dir>]
 *   defaults: --lane = the repo root this script lives in, --out = <lane>/.sandbar/screenshots
 * Exit: 0 = both PNGs written and asserted; 2 = environment refusal (named); 1 = red.
 */
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, statSync, unlinkSync } from 'node:fs'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '..', '..')
const CAPTURE_LANE = path.join(REPO, 'server', 'ui-check', 'capture-lane.mjs')
// playwright-core is test tooling, not product code: use this tree's install, else the
// main checkout's (a lane worktree lives at <main>/.lane/<ticket>, so the main tree is two
// levels up). No machine-absolute path is baked in.
const MAIN_TREE = process.env.SANDBAR_MAIN_TREE || path.resolve(REPO, '..', '..')
const PLAYWRIGHT_DIRS = [
  path.join(REPO, 'server', 'ui-check', 'node_modules', 'playwright-core'),
  path.join(MAIN_TREE, 'server', 'ui-check', 'node_modules', 'playwright-core'),
]
const FORBIDDEN_PORT = 3099
const MIN_PNG_BYTES = 5000

function arg(name, fallback) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const LANE = path.resolve(arg('--lane', REPO))
const OUT = path.resolve(arg('--out', path.join(LANE, '.sandbar', 'screenshots')))
const LANE_WB = path.join(LANE, 'server', 'plugins', 'workbench')

let failures = 0
function ok(cond, label, detail = '') {
  if (cond) { console.log(`ok    ${label}`); return true }
  failures += 1
  console.log(`FAIL  ${label}${detail ? ` :: ${detail}` : ''}`)
  return false
}
function envFail(label, detail) {
  console.log(`ENV_FAIL ${label}${detail ? `: ${detail}` : ''}`)
  process.exit(2)
}

/* ---------------------------------------------------------------- the fixtures */

// One inspection period row whose read is deterministic: the engine names it
// `workflow_task_failed`, the state the measured incident produced.
const TICKET_ID = 't261101-25'
const ROW = {
  id: TICKET_ID, project: 'capture-bench', epic: '', kind: 'inspection', role: null,
  status: 'failed', stage: null, stage_state: 'failed',
  title: 'Inspection integration-tests · period 20261101',
  workflow: '', proposal_id: '', paused: false, paused_phase: '',
  handoff_count: 0, pending_count: 0, worktree: '', workspace: null,
  template: 'inspection-lite', instance_id: 'integration-tests', period: '20261101',
  match_via: 'sa', legacy_unowned: false, legacy_id: false,
  findings: { high: 0, med: 0, low: 0, total: 0 }, heartbeat: false, report_path: '',
  awaiting_gate: false, human_gate: null, blocked_reason: '', gate_error: '',
  created: 1793575800, updated: '11-01 09:30', updated_ts: 1793575800,
  engine: 'inspection', exec_status: 'RUNNING',
  close_health: '', close_health_reason: '', authz_active: 0, close_ts: 0,
  read_state: 'workflow_task_failed',
  read_state_note:
    'workflow task failed (deterministic, not a timeout): RestrictedWorkflowAccessError: '
    + 'Cannot access os.path.join from inside a workflow.',
}

// The engine receipt the host answers with (client.py _augment_read_failure_receipt):
// kind + wording + the read face (durable facts + the retained cause).
const DETAIL_RECEIPT = {
  ok: false,
  error:
    'workflow_task_failed: the snapshot of ticket t261101-25 (queue sandbar) cannot be '
    + 'read - the server reports its workflow task in a failed state; this is '
    + 'deterministic, not a transient timeout; retrying the read cannot help',
  kind: 'workflow_task_failed',
  read_face: {
    ticket: TICKET_ID, queue: 'sandbar', queue_source: 'describe',
    deterministic: true, retryable: false, face_state: 'workflow_task_failed',
    durable: {
      status: 'RUNNING', queue: 'sandbar', queue_source: 'describe',
      live_pollers: 1, face_state: 'workflow_task_failed',
      unavailable: 'unavailable(workflow_task_failed @ queue=sandbar ticket=t261101-25)',
      deterministic: true, retryable: false,
      last_stage: null, last_stage_available: false,
      last_stage_note: 'last known stage unavailable: this ticket left no stage in the memo',
      retained: {
        source: 'execution history (WorkflowTaskFailed event)', available: true,
        failure_type: 'RestrictedWorkflowAccessError',
        failure_message: 'Cannot access os.path.join from inside a workflow.',
        event_id: 36, reason: 'last WorkflowTaskFailed event in the execution history',
      },
    },
  },
}

const TICKETS_BODY = {
  ok: true,
  result: { count: 0, tickets: [], line_frozen: false, line_face_error: '' },
  workflows: [{
    id: 'inspection-lite', name: 'Inspection', phases: [], stages: [
      { id: 'setup', name: 'Setup' }, { id: 'suite', name: 'Suite' },
      { id: 'inspect', name: 'Inspect' }, { id: 'report', name: 'Report' },
      { id: 'close', name: 'Close' },
    ],
  }],
}
const INSPECTION_BODY = {
  ok: true,
  result: {
    count: 1, tickets: [ROW],
    inspection_filter: {
      kind: 'inspection', enabled_instances: ['integration-tests'],
      degraded: false, note: '', scan_mode: 'starts_with',
    },
  },
}
const WORKFLOWS_BODY = { ok: true, result: TICKETS_BODY.workflows }

/** The browser-side routes this script serves (pathname -> handler). */
function routeFor(pathname) {
  if (pathname === '/sandbar-workbench/api/wf/tickets') return { body: TICKETS_BODY }
  if (pathname === '/sandbar-workbench/api/wf/inspection/tickets') return { body: INSPECTION_BODY }
  if (pathname === '/sandbar-workbench/api/wf/workflows') return { body: WORKFLOWS_BODY }
  const m = pathname.match(/^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/)
  if (m && decodeURIComponent(m[1]) === TICKET_ID) {
    return { body: DETAIL_RECEIPT, status: 409 }
  }
  return null
}

/* ---------------------------------------------------------------- helpers */

async function pickFreePort() {
  for (let i = 0; i < 40; i++) {
    const port = await new Promise((resolve, reject) => {
      const srv = createServer()
      srv.once('error', reject)
      srv.listen(0, '127.0.0.1', () => {
        const p = srv.address().port
        srv.close(() => resolve(p))
      })
    })
    if (port !== FORBIDDEN_PORT) return port
  }
  envFail('no-free-port', 'could not pick a port other than the console red line 3099')
}

async function loadPlaywright() {
  for (const dir of PLAYWRIGHT_DIRS) {
    if (!existsSync(dir)) continue
    try {
      const mod = await import(pathToFileURL(path.join(dir, 'index.mjs')).href)
      return mod.default ?? mod
    } catch {
      try {
        const mod = await import(pathToFileURL(path.join(dir, 'index.js')).href)
        return mod.default ?? mod
      } catch { /* try next */ }
    }
  }
  return null
}

function assertPng(file) {
  const st = statSync(file)
  const head = readFileSync(file).subarray(0, 8)
  const magic = head.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
  ok(magic, `${path.basename(file)} carries the PNG magic`)
  ok(st.size > MIN_PNG_BYTES, `${path.basename(file)} is a real capture (${st.size} bytes > ${MIN_PNG_BYTES})`)
  return st.size
}


/**
 * Clear the shell's first-run overlays (the "Internal Testing Notice" and the "Add an API
 * key" admission modal). Both mount LATE on a fresh DSH_HOME and each one covers the
 * board/drawer, so the clearer is called before every screenshot. The recipe is
 * capture.mjs's own (dismissNotice / dismissAdmissionModal / forceClick): click Continue,
 * click "Configure later", else the first enabled dialog button, else Escape. Read-only
 * navigation: no key is entered, no form is submitted, nothing is written.
 * Returns the number of passes it took (0 = the surface was already clear).
 */
async function clearOverlays(page, passes = 6) {
  for (let i = 0; i < passes; i++) {
    let acted = false
    const noticeBtn = page.locator('button', { hasText: /continue|继续/i }).first()
    if (await noticeBtn.isVisible().catch(() => false)) {
      try { await noticeBtn.click({ timeout: 3000 }) } catch { await noticeBtn.evaluate((el) => el.click()) }
      await noticeBtn.waitFor({ state: 'hidden', timeout: 4000 }).catch(() => {})
      acted = true
    }
    if (await page.locator('[role="dialog"]').count() > 0) {
      const later = page.locator('button:has-text("Configure later")').first()
      try {
        if (await later.isVisible()) await later.click({ timeout: 3000 })
        else throw new Error('no Configure later')
      } catch {
        const dlg = page.locator('[role="dialog"]').first()
        const btn = dlg.locator('button:enabled').first()
        if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
        else await page.keyboard.press('Escape').catch(() => {})
      }
      acted = true
    }
    await page.waitForTimeout(acted ? 400 : 250)
    const masks = await page.locator('div[aria-hidden="true"][class*="_mask_"]').count()
    const dialogs = await page.locator('[role="dialog"]').count()
    const noticeLeft = await page.locator('button', { hasText: /continue|继续/i }).first()
      .isVisible().catch(() => false)
    if (masks === 0 && dialogs === 0 && !noticeLeft) return i
    if (!acted) return i + 1   // nothing left to click; report the pass count
  }
  return passes
}

/* ---------------------------------------------------------------- main */

async function main() {
  ok(LANE !== '' && existsSync(path.join(LANE_WB, 'lib', 'client.js')),
    'the lane carries a built workbench bundle', path.join(LANE_WB, 'lib', 'client.js'))

  const C = await import(pathToFileURL(CAPTURE_LANE).href).catch((e) => {
    envFail('capture-lane-unimportable', String(e?.message ?? e))
  })
  const reject = C.laneBuildRejectReason(LANE_WB)
  if (reject) envFail('lane-build', reject)
  const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
    || path.join(process.env.HOME || '', '.dsh', '.agent-presets', 'sandbar-integration')
  const presetReject = C.presetMaterializeRejectReason(presetSrc)
  if (presetReject) envFail('preset-source', presetReject)

  const pw = await loadPlaywright()
  if (!pw) envFail('playwright-absent', 'playwright-core not found (server/ui-check/node_modules)')

  mkdirSync(OUT, { recursive: true })
  const rowPng = path.join(OUT, 'read-state-row-chip.png')
  const panelPng = path.join(OUT, 'read-state-panel.png')
  for (const f of [rowPng, panelPng]) { try { unlinkSync(f) } catch { /* fresh run */ } }

  const tmpHome = await mkdtemp(path.join(tmpdir(), 't261102-18-capture-'))
  let child = null
  let logFd = null
  let browser = null
  let tornDown = false
  const teardown = () => {
    if (tornDown) return
    tornDown = true
    try { if (child?.pid) process.kill(-child.pid, 'SIGTERM') } catch { /* already gone */ }
    try { if (logFd !== null) closeSync(logFd) } catch { /* already closed */ }
    try { rmSync(tmpHome, { recursive: true, force: true }) } catch { /* best effort */ }
  }
  process.on('exit', teardown)
  for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130) })

  try {
    await C.buildTempProfile(tmpHome, LANE_WB)
    const benchRegistryRoot = await C.buildBenchRegistry(tmpHome)
    await C.materializePresets(tmpHome, presetSrc)
    const port = await pickFreePort()
    ok(port !== FORBIDDEN_PORT, `bench port ${port} is not the console red line ${FORBIDDEN_PORT}`)
    const portPatch = path.join(tmpHome, 'port_patch.yml')
    await writeFile(portPatch,
      `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, 'utf8')
    logFd = openSync(path.join(tmpHome, 'console.log'), 'a')
    const consoleCmd = (process.env.SANDBAR_CONSOLE_CMD || 'dsh --profile sandbar').split(' ')
    child = spawn(consoleCmd[0],
      [...consoleCmd.slice(1), '--patch', portPatch,
        '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
        cwd: REPO,
        env: { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: benchRegistryRoot },
        detached: true,
        stdio: ['ignore', logFd, logFd],
      })
    const fingerprint = C.dshAuthFingerprint({ bin: consoleCmd[0] })
    const ready = await C.waitReady(port, 180000, path.join(tmpHome, 'console.log'), fingerprint)
    if (!ready?.ok) envFail('bench-not-ready', ready?.refusal ?? 'console did not become ready')
    console.log(`ok    bench ready at 127.0.0.1:${port} (auth ${ready.authMode})`)

    browser = await pw.chromium.launch({ channel: 'chrome', headless: true }).catch(() =>
      pw.chromium.launch({ headless: true }))
    const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } })
    let served = 0
    await page.route('**/sandbar-workbench/api/wf/**', async (route) => {
      const req = route.request()
      const hit = req.method() === 'GET'
        ? routeFor(new URL(req.url()).pathname)
        : null
      if (hit === null) return route.continue()
      served += 1
      return route.fulfill({
        status: hit.status ?? 200,
        contentType: 'application/json',
        body: JSON.stringify(hit.body),
      })
    })
    await page.goto(ready.entryUrl, { waitUntil: 'domcontentloaded', timeout: 60000 })
    // A fresh temp DSH_HOME greets the first page load with shell overlays (the
    // "Internal Testing Notice" and the "Add an API key" admission modal). Both mount
    // late and both cover the faces this evidence must show, so they are cleared before
    // the board is read and again before each capture.
    const firstPass = await clearOverlays(page)
    console.log(`ok    shell overlays cleared (${firstPass} pass(es) needed)`)
    // The left column must show OUR row with the NAMED chip — the face the host reported.
    // The chip is a child span of the row card (data-read-state lives on the chip, the row
    // keeps its own data-state), so the row is located through the chip.
    const chip = page.locator('.wb-card-read-state[data-read-state="workflow_task_failed"]')
    try {
      await chip.first().waitFor({ state: 'visible', timeout: 60000 })
    } catch (e) {
      const cards = await page.locator('.wb-card').count()
      const diag = path.join(tmpHome, 'not-ready.png')
      await page.screenshot({ path: diag, fullPage: true }).catch(() => {})
      const body = (await page.innerText('body').catch(() => '')).slice(0, 700)
      console.log(`[t261102-18] row not found: .wb-card count=${cards}; diag=${diag}`)
      console.log(`[t261102-18] page text: ${body.replace(/\s+/g, ' ')}`)
      throw e
    }
    const chipText = (await chip.first().innerText()).trim()
    ok(chipText.length > 0, 'the left-column row carries the named chip text', chipText)
    const card = page.locator('.wb-card', { has: chip }).first()
    await card.scrollIntoViewIfNeeded()
    await clearOverlays(page)
    ok((await page.locator('div[aria-hidden="true"][class*="_mask_"]').count()) === 0
      && (await page.locator('[role="dialog"]').count()) === 0,
    'no shell overlay is over the board at capture time')
    await page.screenshot({ path: rowPng, fullPage: true })
    const rowBytes = assertPng(rowPng)

    // Open the ticket: the drawer must render ReadStatePanel for the same state, with the
    // located cause and the queue the execution really polls.
    try {
      await card.click({ timeout: 5000 })
    } catch {
      // The modal mask may still intercept pointer events (capture.mjs forceClick recipe):
      // a DOM click is the same read-only navigation act, dispatched on the real card.
      await card.evaluate((el) => el.click())
    }
    const panel = page.locator('[data-testid="read-state-panel"][data-read-state="workflow_task_failed"]')
    await panel.first().waitFor({ state: 'visible', timeout: 30000 })
    const panelText = await panel.first().innerText()
    ok(/Workflow task failed/i.test(panelText), 'the panel names the state', panelText.slice(0, 120))
    ok(/RestrictedWorkflowAccessError/.test(panelText),
      'the panel shows the located cause from the execution history')
    ok(/not re-polled/i.test(panelText), 'the panel states that no further read is scheduled')
    ok((await page.getAttribute('[data-testid="read-state-panel"]', 'data-read-retry')) === 'never',
      'the panel carries the never-retry rule on its face')
    await clearOverlays(page)
    ok((await page.locator('[role="dialog"]').count()) === 0,
      'no shell overlay is over the drawer at capture time')
    await page.screenshot({ path: panelPng, fullPage: true })
    const panelBytes = assertPng(panelPng)

    ok(served >= 3, `the browser served the intercepts (${served} wf reads routed)`)
    ok(Object.keys(DETAIL_RECEIPT).includes('read_face'),
      'the detail receipt is the engine shape (kind + read_face), not a success body')
    // Evidence manifest: what each PNG proves, so a reviewer reads pixels against it.
    const manifest = {
      ticket: 't261102-18',
      produced_by: 'integration/t261102-12/capture_read_state_faces.mjs',
      bench: 'server/ui-check/capture-lane.mjs helpers (temp DSH_HOME + profile + registry)',
      lane_build: path.join(LANE_WB, 'lib', 'client.js'),
      port, files: [
        { file: 'read-state-row-chip.png', bytes: rowBytes,
          proves: 'the left column shows an inspection row with read_state=workflow_task_failed '
            + 'as a NAMED chip (not a "query timed out, refresh to retry" title)' },
        { file: 'read-state-panel.png', bytes: panelBytes,
          proves: 'ReadStatePanel renders the deterministic state with its history cause, the '
            + 'queue the execution polls (sandbar), and the never-retry rule' },
      ],
    }
    await writeFile(path.join(OUT, 'read-state-faces.manifest.json'),
      JSON.stringify(manifest, null, 2) + '\n', 'utf8')
    console.log(`[t261102-18] evidence written: ${rowPng} (${rowBytes} B), ${panelPng} (${panelBytes} B)`)
  } finally {
    try { await browser?.close() } catch { /* collected */ }
    teardown()
  }
  console.log(failures === 0 ? 'SUMMARY pass' : `SUMMARY fail=${failures}`)
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((err) => {
  console.error(`[t261102-18] capture failed: ${err?.stack ?? err}`)
  process.exit(1)
})
