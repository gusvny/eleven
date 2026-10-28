#!/usr/bin/env node
/**
 * capture_crowded_map.mjs — the isolated stage that produces this ticket's UI
 * evidence (t261028-32; the ticket's second plumbing red: a UI ticket must hand
 * the gate TOP-LEVEL screenshots under <lane>/.sandbar/screenshots).
 *
 * WHY THIS FILE EXISTS. `server/ui-check/capture-lane.mjs` is the sanctioned
 * bench, but it hardwires its own fixture package (`server/ui-check/fixtures/`,
 * outside this ticket's write set) whose ticket maps are the ordinary ten-stage
 * dev-lane shape, and it named-skips the detail view when the bench holds no
 * ticket. The host's evidence for THIS report needs a CROWDED lane map in the
 * detail drawer, so this driver assembles the same bench with the fixture
 * package that ships with this ticket (integration/t261009-53/capture-fixtures:
 * sixteen quick stages, three rounds each - sixteen captions on one map, which
 * the retired two-level placement smears and the new placement stacks).
 *
 * It reuses capture-lane's own exported steps instead of copying them: the lane
 * build freshness refusal, the temporary profile whose sandbar-workbench points
 * at THIS lane, the bench registry (a fresh home that cannot replay retired
 * projects), the preset materialization, the port pick, and the auth-surface
 * readiness verdict. `server/ui-check/capture.mjs` stays the producer of every
 * PNG (this file draws nothing).
 *
 * SAFETY. Never touches port 3099: the port comes from freePort() and a hit on
 * 3099 is refused by name. Read-only towards the product: the browser only opens
 * pages and clicks a row card (capture.mjs's own contract). Every piece of state
 * lives in temporary directories; the console process group, the log fd and the
 * temp home are reclaimed on the normal, error, SIGINT and SIGTERM paths.
 *
 * PRECONDITION (refusal, not a warning): the lane build must exist and must not
 * be older than the newest workbench client source - a screenshot of a stale
 * bundle is fabricated evidence. Rebuild with
 * `cd server/plugins/workbench && bash build-client.sh`.
 *
 * Usage: node integration/t261009-53/capture_crowded_map.mjs
 *        (exit 0 = every view captured; capture.mjs's own exit code otherwise)
 */
import { spawn } from 'node:child_process'
import { closeSync, existsSync, openSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { copyFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { freePort, mainRoot } from '../t260904-17/lib_fix17.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const LANE = path.resolve(HERE, '..', '..')
const OUT = path.join(LANE, '.sandbar', 'screenshots')
const FIXTURES = path.join(HERE, 'capture-fixtures')
const UI_CHECK = path.join(LANE, 'server', 'ui-check')
const CAPTURE = path.join(UI_CHECK, 'capture.mjs')
const LANE_WB = path.join(LANE, 'server', 'plugins', 'workbench')
const LIB = path.join(LANE_WB, 'lib', 'client.js')
const SRC = path.join(LANE_WB, 'src', 'client')

/** Refusal reason when the lane build is missing or older than its sources. */
function buildRefusal() {
  if (!existsSync(LIB)) return `lane build missing: ${LIB} (run: cd server/plugins/workbench && bash build-client.sh)`
  const libMs = statSync(LIB).mtimeMs
  let newest = 0
  let newestName = ''
  for (const f of readdirSync(SRC)) {
    const p = path.join(SRC, f)
    const st = statSync(p)
    if (st.isFile() && st.mtimeMs > newest) { newest = st.mtimeMs; newestName = f }
  }
  if (newest > libMs) {
    return `lane build is older than src/client/${newestName} (a screenshot of a stale bundle is fabricated evidence;`
      + ' rebuild: cd server/plugins/workbench && bash build-client.sh)'
  }
  return ''
}

const refusal = buildRefusal()
if (refusal) {
  console.error(`[capture-crowded] REFUSED: ${refusal}`)
  process.exit(2)
}
if (!existsSync(CAPTURE)) {
  console.error(`[capture-crowded] REFUSED: capture tool missing at ${CAPTURE}`)
  process.exit(2)
}

/* capture-lane's exported bench steps (this lane's copy: its REPO_ROOT is the
 * lane, so the temporary profile shows THIS lane's workbench build). */
const cl = await import(pathToFileURL(path.join(UI_CHECK, 'capture-lane.mjs')).href)
const { resolveCredentialsSource } = await import(pathToFileURL(path.join(UI_CHECK, 'creds-source.mjs')).href)

/** playwright-core lives in the main tree's ui-check (a lane installs nothing). */
function playwrightModuleDir() {
  const candidates = [
    process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK
      && path.join(process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK, 'node_modules', 'playwright-core'),
    path.join(UI_CHECK, 'node_modules', 'playwright-core'),
    // a lane installs no node_modules: borrow the main tree's ui-check (read-only)
    path.join(mainRoot(), 'server', 'ui-check', 'node_modules', 'playwright-core'),
  ].filter(Boolean)
  for (const c of candidates) if (existsSync(c)) return c
  return ''
}

/**
 * The fixture package, materialized into a temporary directory with its
 * timestamps shifted so the captured map reads like a live ticket (the last
 * timeline mark lands one minute before now; the static files would otherwise
 * show a drifting "elapsed" figure). The reviewed source files stay untouched.
 */
async function materializeFixtures() {
  const dir = await mkdtemp(path.join(tmpdir(), 'sandbar-crowded-fixtures-'))
  const nowMs = Date.now()
  const files = readdirSync(FIXTURES).filter((f) => f.endsWith('.json'))
  const title = 'Crowded fixture: 16 quick stages, 3 rounds each (t261028-32)'
  const shift = (detail) => {
    const rows = Array.isArray(detail?.timeline) ? detail.timeline : []
    const last = rows.map((r) => Date.parse(String(r?.at ?? ''))).filter((n) => Number.isFinite(n)).pop()
    if (!last) return detail
    const delta = nowMs - 60_000 - last
    for (const r of rows) {
      const t = Date.parse(String(r?.at ?? ''))
      if (Number.isFinite(t)) r.at = new Date(t + delta).toISOString()
    }
    return detail
  }
  for (const f of files) {
    const raw = JSON.parse(readFileSync(path.join(FIXTURES, f), 'utf8'))
    let out = raw
    if (f.startsWith('ticket-show-')) out = Object.assign(shift(raw), { title })
    if (f === 'tickets-list.json') {
      for (const row of [...(out.tickets || []), ...(out.result?.tickets || [])]) row.title = title
    }
    await writeFile(path.join(dir, f), JSON.stringify(out, null, 1), 'utf8')
  }
  return dir
}

/**
 * Phase B: open the bench console with this ticket's fixture package, click the
 * first ticket row and shoot the crowded lane map (full page + a close-up).
 * Returns {ok, why}. Read-only: navigation, the notice button, one row click.
 */
async function shootCrowdedLaneMap(entryUrl, pwDir) {
  const capMod = await import(pathToFileURL(path.join(UI_CHECK, 'capture.mjs')).href)
  let fixtures
  let fixtureDir = ''
  try {
    fixtureDir = await materializeFixtures()
    fixtures = capMod.loadFixtures(fixtureDir)
  } catch (e) {
    return { ok: false, why: `fixture package rejected: ${e.message}` }
  }
  const pw = await import(pathToFileURL(path.join(pwDir, 'index.mjs')).href)
  const browser = await pw.chromium.launch({ headless: true })
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await ctx.newPage()
    const pageErrors = []
    page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))
    await page.route('**/api/wf/**', (route) => {
      const req = route.request()
      const d = capMod.routeDecision(req.method(), req.url(), fixtures)
      if (d.fulfill) return route.fulfill(d.fulfill)
      return route.continue()
    })
    await page.goto(entryUrl, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1500)
    for (const label of ['Continue', 'Configure later']) {
      const b = page.locator(`button:has-text("${label}")`).first()
      if (await b.count()) { try { await b.click({ timeout: 2000 }) } catch { /* optional */ } }
    }
    const row = page.locator('.wb-card[data-ticket-id]').first()
    await row.waitFor({ state: 'visible', timeout: 15000 })
    await row.click({ timeout: 5000 })
    await page.waitForSelector('[data-testid="detail-lane-map"] text.wb-lm-label', { timeout: 15000 })
    await page.waitForTimeout(600)
    const mapEl = await page.$('[data-testid="detail-lane-map"]')
    if (!mapEl) return { ok: false, why: 'lane map vanished before the shot' }
    await mapEl.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    // The shot is evidence only if the contract holds on THIS page: measure the
    // real glyph boxes and refuse to call an overlapping map evidence.
    const measured = await page.evaluate(() => {
      const lm = document.querySelector('[data-testid="detail-lane-map"]')
      const svg = lm && lm.querySelector('svg')
      if (!svg) return { ok: false, why: 'no svg' }
      const vb = (svg.getAttribute('viewBox') || '').split(/\s+/).map(Number)
      const sr = svg.getBoundingClientRect()
      const scale = vb[2] > 0 && sr.width > 0 ? sr.width / vb[2] : 0
      const boxes = [...svg.querySelectorAll('text.wb-lm-label')].map((el) => {
        const r = el.getBoundingClientRect()
        return {
          s: (el.textContent || '').trim(),
          x0: (r.left - sr.left) / scale, x1: (r.right - sr.left) / scale,
          y0: (r.top - sr.top) / scale, y1: (r.bottom - sr.top) / scale,
          row: Number(el.getAttribute('y')),
        }
      }).filter((b) => b.s !== '' && b.x1 > b.x0)
      return { ok: true, vbw: vb[2], vbh: vb[3], boxes }
    })
    if (!measured.ok) return { ok: false, why: `measure failed: ${measured.why}` }
    const { boxes, vbw, vbh } = measured
    const bad = []
    for (const b of boxes) {
      if (b.x0 < -1 || b.x1 > vbw + 1 || b.y0 < -1 || b.y1 > vbh + 1) bad.push(`"${b.s}" leaves the canvas`)
    }
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i]
        const b = boxes[j]
        if (a.x0 < b.x1 - 0.5 && b.x0 < a.x1 - 0.5 && a.y0 < b.y1 - 0.5 && b.y0 < a.y1 - 0.5) {
          bad.push(`caption boxes intersect: "${a.s}" x "${b.s}"`)
        }
      }
    }
    const rows = [...new Set(boxes.map((b) => b.row))].sort((a, b) => a - b)
    await page.screenshot({ path: path.join(OUT, 'console-lane-map-crowded.png'), fullPage: true })
    await mapEl.screenshot({ path: path.join(OUT, 'console-lane-map-crowded-closeup.png') })
    console.log(`[capture-crowded] phase B: crowded map captured (captions=${boxes.length}`
      + ` rows=${rows.length} canvas=${vbw}x${vbh} overlaps/violations=${bad.length}`
      + ` pageerrors=${pageErrors.length})`)
    if (bad.length) return { ok: false, why: `${bad.length} violation(s): ${bad[0]}` }
    return { ok: boxes.length >= 6, why: `captions=${boxes.length}` }
  } finally {
    await browser.close()
  }
}

const consoleCmd = (process.env.SANDBAR_CONSOLE_CMD || 'dsh --profile sandbar').split(' ')
const bootTimeoutMs = Number(process.env.SANDBAR_CAPTURE_LANE_BOOT_MS || 45000)
const tmpHome = await mkdtemp(path.join(tmpdir(), 'sandbar-capture-crowded-'))
const logPath = path.join(tmpHome, 'console.log')
let proc = null
let logFd = null
let code = 1
let tornDown = false
const teardown = () => {
  if (tornDown) return
  tornDown = true
  if (proc && proc.pid && proc.exitCode === null && proc.signalCode === null) {
    try { process.kill(-proc.pid, 'SIGTERM') } catch { try { proc.kill('SIGKILL') } catch { /* gone */ } }
  }
  if (logFd !== null) { try { closeSync(logFd) } catch { /* closed */ } }
  // synchronous removal: the exit hook may run after the loop stopped (capture-lane precedent)
  try { rmSync(tmpHome, { recursive: true, force: true }) } catch { /* left for the operator */ }
}
process.on('exit', teardown)
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130) })

try {
  const credSrc = resolveCredentialsSource(cl.BENCH_PROJECT_KEY)
  if (credSrc) await copyFile(credSrc, path.join(tmpHome, '.credentials.yaml')).catch(() => {})
  await cl.buildTempProfile(tmpHome, LANE_WB)
  const benchRegistryRoot = await cl.buildBenchRegistry(tmpHome)
  const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
    || path.join(process.env.HOME || '', '.dsh', '.agent-presets', 'sandbar-integration')
  const presetReject = cl.presetMaterializeRejectReason(presetSrc)
  if (presetReject) {
    console.error(`[capture-crowded] REFUSED: ${presetReject}`)
    process.exit(2)
  }
  await cl.materializePresets(tmpHome, presetSrc)
  const port = await freePort()
  if (port === 3099) {
    console.error('[capture-crowded] REFUSED: the picked port is 3099 (the user console) - not touching it')
    process.exit(2)
  }
  logFd = openSync(logPath, 'a')
  // The profile pins the webserver port; this patch layer moves it to our own port.
  const portPatch = path.join(tmpHome, 'port_patch.yml')
  await writeFile(portPatch, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, 'utf8')
  proc = spawn(consoleCmd[0], [...consoleCmd.slice(1), '--patch', portPatch,
    '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
    cwd: LANE,
    env: {
      ...process.env,
      DSH_HOME: tmpHome,
      // the bench registry: a fresh home that cannot replay retired projects
      SANDBAR_PROJECTS_DIR: benchRegistryRoot,
      SANDBAR_TARGET_HOST: process.env.SANDBAR_CAPTURE_TARGET_HOST
        || process.env.SANDBAR_TARGET_HOST || '127.0.0.1:17233',
    },
    detached: true,
    stdio: ['ignore', logFd, logFd],
  })
  const fingerprint = cl.dshAuthFingerprint({ bin: consoleCmd[0] })
  const ready = await cl.waitReady(port, bootTimeoutMs, logPath, fingerprint)
  console.log(`[capture-crowded] bench ready on 127.0.0.1:${port} (DSH_HOME=${tmpHome},`
    + ` auth surface=${ready.authMode}) shots=${OUT} fixtures=${FIXTURES}`)
  await mkdir(OUT, { recursive: true })
  const pwDir = playwrightModuleDir()
  if (!pwDir) {
    console.error('[capture-crowded] REFUSED: playwright-core not found (lane ui-check installs nothing);'
      + ' set SANDBAR_CAPTURE_MAIN_UI_CHECK to the main tree\'s server/ui-check')
    process.exit(2)
  }
  // Phase A: the standard view set, produced by capture.mjs exactly as the
  // evidence gate expects. No fixture injection here: the bench owns one project
  // and no tickets, so the board renders its empty state and the drawer view is a
  // named skip (data absent, not a rendering fault).
  const env = { ...process.env, SANDBAR_UI_CAPTURE_ALLOW_SEED: '1', SANDBAR_PLAYWRIGHT_MODULE: pwDir }
  code = await new Promise((resolve) => {
    const cap = spawn(process.execPath, [CAPTURE, '--url', ready.entryUrl, '--out', OUT, '--allow-seed'],
      { cwd: LANE, env, stdio: 'inherit' })
    cap.on('close', (c) => resolve(c === null ? 1 : c))
  })
  console.log(`[capture-crowded] phase A (capture.mjs standard views) exit=${code}`)

  // Phase B: the host's evidence - a CROWDED lane map in the detail drawer, shot
  // through the same bench with this ticket's fixture package. capture.mjs has no
  // lane-map view, and its drawer anchor `.wb-d2-steps` is the retired stepper
  // (a ticket whose template declares a topology draws the lane map INSTEAD of the
  // stepper), so this one shot is taken here and named after what it shows. The
  // page work is read-only: open the console, close the notice, click the row.
  const shot = await shootCrowdedLaneMap(ready.entryUrl, pwDir)
  if (!shot.ok) {
    console.error(`[capture-crowded] phase B failed: ${shot.why}`)
    code = code === 0 ? 1 : code
  }
} finally {
  teardown()
  console.log('[capture-crowded] bench torn down (process group killed, temp home removed)')
}
const shots = existsSync(OUT) ? readdirSync(OUT).filter((f) => f.endsWith('.png')).sort() : []
console.log(`[capture-crowded] top-level PNGs: ${shots.length}${shots.length ? ' — ' + shots.join(' ') : ''}`)
process.exit(code)
