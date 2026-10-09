/**
 * sc_wake_route_receipt.mjs — t261004-29, watchdog wake-route mount + input
 * contract (grey-box L3, offline, zero docker, never touches 3099/7233).
 *
 * Intent (user-perceivable; ticket requirement "both must reach the executor
 * without the host doing anything else ... a receipt that says whether a wake
 * was attempted and why"): the watchdog exposes a POST wake route beside the
 * existing read-only status route, it validates its input with named errors,
 * and it degrades like the rest of the KI-079 family — no webServer, no route,
 * never a silent swallow. Concretely:
 *   B1 headless profile (no webServer, none arriving): apply() must not register
 *      any wake route and must not crash — the core keeps running headless;
 *   B2 web profile (webServer arrives after apply): both routes register — the
 *      pre-existing GET status route AND the new POST wake route — and both
 *      disposers actually unregister (full teardown unchanged);
 *   B3 POST with a non-JSON body → 4xx with a named error (which check failed),
 *      never a 500, never a fabricated receipt;
 *   B4 POST with a valid body for an undeclared project (no watchdog.json
 *      anywhere) → explicit 4xx (or an explicit attempted:false receipt) with a
 *      named reason — never a silent 200 that pretends a wake happened.
 *
 * The happy-path receipt (woke / guard-silent / refused) is judged against the
 * public Watchdog.requestWake face in sc_wake_self_feed_guard.mjs — the route is
 * a thin body-checking wrapper over that seam, so this file does not duplicate it.
 *
 * Seam: plugin `apply(ctx, config)` + the webServer `register` mount contract
 * (public plugin face, same one plugin-load UTs use). A stub ctx delivers the
 * webServer service via 'internal/service' (the late-mount path) or holds it
 * up front (the headless path never delivers). Request/response are minimal
 * Node-shaped fakes; TDD-phase red (route missing) is expected.
 *
 * Run directly: node integration/t261004-29/sc_wake_route_receipt.mjs (cwd = repo root).
 */
import { join } from 'node:path'
import { Watchdog } from '../../server/plugins/watchdog/src/host/core.ts'
import * as plugin from '../../server/plugins/watchdog/node.ts'
import { makeResults, freshDir, reclaimDir, fakeCtx, fakeWebServer, fakeReq, fakeRes } from './lib_wake_fixture.mjs'

const r = makeResults()
const HOME = freshDir('sc-t261004-29-route-')
const WAKE_PATH = '/sandbar-watchdog/api/wake'
// apply() resolves declarations from the real process env — pin it to the empty
// isolated home for the whole run (restored in finally), so no real project and
// no real ~/.sandbar data is touched.
const REAL_DSH_HOME = process.env.DSH_HOME
process.env.DSH_HOME = join(HOME, 'dsh-home')

// t261008-33 arbitration (20261008): make THIS scenario hermetic to the repo
// anchor chain. This scenario tests the wake route's input contract, not anchor
// discipline; a host-shell SANDBAR_REPO leaking in (this machine hand-exports
// the main checkout) made the t261008-33 escape guard correctly refuse the
// plugin apply here. Unset it so the plugin takes the location-derived branch
// (the normal state); the anchor contract itself is owned by
// integration/t261008-33/sc_t26100833_anchor_guard_named_failure.mjs.
delete process.env.SANDBAR_REPO

/** A Watchdog stub stand-in seam: apply() resolves per-project watchdogs through
 *  declaredProjects(); with an empty DSH_HOME no real project starts, so apply is
 *  cheap and side-effect free. The wake route's project validation must consult
 *  the same declaration face (undeclared = explicit refusal). */
const emptyEnv = { DSH_HOME: join(HOME, 'dsh-home'), SANDBAR_REPO: process.env.SANDBAR_REPO }

try {
  if (plugin.name !== 'sandbar-watchdog' || typeof plugin.apply !== 'function') {
    r.record('plugin-face', 'fail', `unexpected plugin export shape: name=${plugin.name}`)
    r.summarize()
  }

  // B1 headless: no webServer, none arriving → no wake route, no crash.
  {
    const h = fakeCtx()
    let threw = null
    try { plugin.apply(h.ctx, {}) } catch (e) { threw = String((e && e.message) || e) }
    r.check(threw === null, 'B1-headless-apply-no-crash', threw ? `apply threw: ${threw.slice(0, 200)}` : '')
    // nothing delivers 'webServer' → nothing mounted; wake route must be absent.
    const ws = fakeWebServer()
    h.deliverService('unrelated-service', ws)
    r.check(ws.routes.length === 0, 'B1-headless-no-route-registered', `routes=${JSON.stringify(ws.routes.map(x => x.path))}`)
    h.disposeAll()
  }

  // B2 web profile: webServer arrives → status + wake routes both mount; disposers work.
  {
    const ws = fakeWebServer()
    const h = fakeCtx({ services: { webServer: ws } })
    let threw = null
    try { plugin.apply(h.ctx, {}) } catch (e) { threw = String((e && e.message) || e) }
    r.check(threw === null, 'B2-web-apply-no-crash', threw ? `apply threw: ${threw.slice(0, 200)}` : '')
    const paths = ws.routes.map(x => x.path)
    r.check(paths.includes('/sandbar-watchdog/api/status'), 'B2-status-route-still-mounted', `paths=${JSON.stringify(paths)}`)
    r.check(paths.includes(WAKE_PATH), 'B2-wake-route-mounted', `paths=${JSON.stringify(paths)} (TDD red expected until implement lands)`)
    if (paths.includes(WAKE_PATH)) {
      const wakeEntry = ws.find(WAKE_PATH)
      r.check(typeof wakeEntry.handler === 'function', 'B2-wake-handler-is-function', '')
      const before = ws.routes.length
      h.disposeAll()
      r.check(ws.routes.length < before && ws.routes.every(x => x.path !== WAKE_PATH),
        'B2-disposers-unregister-both-routes', `routesAfterDispose=${ws.routes.length}`)
    } else {
      r.check(false, 'B2-wake-handler-is-function', 'wake route absent — cannot judge handler')
      h.disposeAll()
    }
  }

  // B3/B4: input contract of the mounted wake route (re-mount a fresh instance).
  {
    const ws = fakeWebServer()
    const h = fakeCtx({ services: { webServer: ws } })
    plugin.apply(h.ctx, {})
    const wakeEntry = ws.find(WAKE_PATH)
    if (!wakeEntry) {
      r.check(false, 'B3-non-json-body-4xx-named', 'wake route not mounted (TDD red expected)')
      r.check(false, 'B4-undeclared-project-explicit', 'wake route not mounted (TDD red expected)')
    } else {
      // B3 non-JSON body → 4xx, named error.
      const res1 = fakeRes()
      await wakeEntry.handler(fakeReq({ url: WAKE_PATH, body: '{oops', headers: { host: 'console.test' } }), res1)
      const named1 = res1.body && typeof res1.body.error === 'string' && res1.body.error.length > 0
      r.check(res1.statusCode >= 400 && res1.statusCode < 500 && named1,
        'B3-non-json-body-4xx-named', `status=${res1.statusCode} body=${JSON.stringify(res1.body).slice(0, 160)}`)

      // B3b missing fields (no project / no request id) → 4xx, named.
      const res2 = fakeRes()
      await wakeEntry.handler(fakeReq({ url: WAKE_PATH, body: JSON.stringify({ detail: 'no project, no id' }), headers: { host: 'console.test' } }), res2)
      const named2 = res2.body && typeof res2.body.error === 'string' && res2.body.error.length > 0
      r.check(res2.statusCode >= 400 && res2.statusCode < 500 && named2,
        'B3-missing-fields-4xx-named', `status=${res2.statusCode} body=${JSON.stringify(res2.body).slice(0, 160)}`)

      // B4 undeclared project (empty DSH_HOME): explicit 4xx or explicit
      // attempted:false receipt — never a bare 200 ok without a wake verdict.
      const res3 = fakeRes()
      await wakeEntry.handler(fakeReq({
        url: WAKE_PATH,
        body: JSON.stringify({ project: 'alpha', request_id: 'req-1', detail: 'host answered' }),
        headers: { host: 'console.test' },
      }), res3)
      const j3 = res3.body || {}
      const explicit4xx = res3.statusCode >= 400 && res3.statusCode < 500 && typeof j3.error === 'string' && j3.error.length > 0
      const explicitNoWake = res3.statusCode === 200
        && j3.receipt && j3.receipt.attempted === false
        && typeof j3.receipt.reason === 'string' && j3.receipt.reason.length > 0
      r.check(explicit4xx || explicitNoWake,
        'B4-undeclared-project-explicit', `status=${res3.statusCode} body=${JSON.stringify(j3).slice(0, 200)}`)
    }
    h.disposeAll()
  }

  // Guard: the fixture's Watchdog import is exercised only to prove the module
  // face used by sc_wake_self_feed_guard.mjs loads in this environment too
  // (same engine, same strip mode) — no behavior asserted here.
  void Watchdog
} finally {
  if (REAL_DSH_HOME === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = REAL_DSH_HOME
  reclaimDir(HOME)
}
r.summarize()
