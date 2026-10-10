#!/usr/bin/env node
// sc_t26100968_lane_map_mount_receipt.mjs —— the lane map mounts without the
// shipped-bundle crash (t261009-68, host report 261010).
//
// intent (grey-box L3, browser-free pool per registry convention: real browser
// + page-boundary API stubs, zero docker, never touches the 3099 red line):
// after t261009-53 merged, clicking a ticket detail threw
// `ReferenceError: laneMapScene is not defined at LaneMap (client.js:1352)`
// inside the host's browser, contained by the SlotErrorBoundary — the user's
// lane map was gone. This scenario is the ONE real rendering receipt the
// ticket demands: open a ticket detail in a real browser against the BUILT
// artifact and assert the user-perceivable faces:
//   M1 the detail drawer opens;
//   M2 zero pageerror anywhere in the journey whose text names laneMapScene
//      (the reported stack) — and zero pageerror at all while the drawer is
//      open;
//   M3 the lane map itself mounts: [data-testid="detail-lane-map"] present
//      with an svg inside (semantic anchor, KI-051);
//   M4 no slot-crash containment: no console line of the
//      'sidebar slot entry crashed' family (the boundary swallowing the
//      ReferenceError would satisfy M2's pageerror probe while the user still
//      sees nothing — the containment channel must be quiet too).
// intent split: the bundle-level binding face is
// sc_t26100968_lane_map_binds_scene (static, always runnable); the lane map's
// geometry faces (slim-pipe bars, labels, diamonds) stay with
// sc_t26100953_lane_map_pipe — this entry pins ONLY crash-free mount, so the
// two never fight over tolerances. Fixture and boot helpers are shared with
// the t261008-23 lib (shared fixture code, not duplicated scenarios).
// Three-state (t260904-12): console/playwright unavailable = ENV_FAIL exit 2
// with the verbatim boot failure line (KI-036 family; the 16/16 env_fail
// streak on the t261009-53 scenario is exactly the face this receipt must
// finally close — a named boot failure here is the honest receipt, never a
// silent skip).

import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  PROJ, TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from '../t261008-23/lib_fix23.mjs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null
try {
  const b = await bootFixture(REPO, 't26100968-lanemap-mount')
  bench = b.bench
  bench.teardownOnExit = b.teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

let pw = null, browser = null
try { pw = await loadPlaywright(REPO) } catch { /* handled below */ }
browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  try { await bench.teardown() } catch { /* already down */ }
  process.exit(2)
}

const ctx = await browser.newContext()
const pageErrors = []
const slotCrashes = []
const page = await ctx.newPage()
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))
page.on('console', (msg) => {
  const t = msg.text ? msg.text() : ''
  if (/crashed/i.test(t) && /slot/i.test(t)) slotCrashes.push(t.slice(0, 200))
})

const detail = fixtureTicketDetail(fixtureTimeline())
await routeDetail(page, detail)
await bench.goto(page, { waitUntil: 'networkidle' })
await dismissIntroModal(page)
await page.waitForTimeout(2000)

// M1 the detail drawer opens at all (if the crash fires on mount this fails
// together with M2/M3 — recorded separately so the failure mode is named).
const opened = await waitFor(async () => {
  const row = await page.$(`[data-ticket-id="${TID}"]`)
  if (!row) return false
  await row.click()
  await page.waitForTimeout(1200)
  return !!(await page.$('[data-testid="detail-columns"]'))
}, 10000)
rec('M1 detail drawer opens', opened, opened ? 'drawer open for ' + TID : 'detail drawer never opened for ' + TID)

// M2 no laneMapScene ReferenceError — and no pageerror at all post-open.
const lmErrors = pageErrors.filter((e) => /lanemapscene/i.test(e))
rec('M2 no laneMapScene pageerror', pageErrors.length === 0,
  lmErrors.length > 0
    ? `the reported crash still reproduces: ${lmErrors.join(' | ').slice(0, 200)}`
    : pageErrors.length === 0 ? 'zero pageerror in the journey' : `other pageerrors: ${pageErrors.join(' | ').slice(0, 200)}`)

// M3 the lane map mounts through the BUILT artifact (svg present).
const probe = await page.evaluate(`(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"]')
  if (!lm) return { found: false }
  return { found: true, svg: !!lm.querySelector('svg'), nodes: lm.querySelectorAll('g[data-id]').length }
})()`.replace(/\n/g, ' '))
rec('M3 lane map mounts', probe.found && probe.svg,
  probe.found ? `svg present, ${probe.nodes} node groups` : '[data-testid="detail-lane-map"] absent from the opened drawer')

// M4 the SlotErrorBoundary containment channel is quiet (a swallowed crash
// would hide from the pageerror probe but still tell the user nothing).
rec('M4 no slot-crash containment log', slotCrashes.length === 0,
  slotCrashes.length === 0 ? 'no "slot entry crashed" console line' : slotCrashes.join(' | ').slice(0, 240))

// Theme captures (KI-055 evidence face; best-effort, never a red).
const outDir = join(REPO, 'integration', 't261009-68', 'out')
try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
for (const scheme of ['light', 'dark']) {
  try {
    await page.emulateMedia({ colorScheme: scheme })
    await page.waitForTimeout(300)
    const lmEl = await page.$('[data-testid="detail-lane-map"]')
    if (lmEl) { await lmEl.scrollIntoViewIfNeeded(); await page.waitForTimeout(200) }
    const shot = lmEl || page
    await shot.screenshot({ path: join(outDir, `lane-map-mount-${scheme}.png`) })
    record(`C capture-${scheme}`, 'pass', `out/lane-map-mount-${scheme}.png`)
  } catch (e) {
    record(`C capture-${scheme}`, 'na', String(e).slice(0, 120))
  }
}

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()
