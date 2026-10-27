/**
 * t261028-18-metrics-chart-bridge.test.mjs — the Metrics tab's chart library
 * bridge, L1 (pure node, no browser, no network). The page embeds
 * createChartLibBridge via String(fn), so these tests drive THE page's
 * implementation, not a copy.
 *
 * Why this file exists: the host reported both charts as 'charts could not
 * load' while the vendor route answered 200. The reproduced cause was the
 * load guard: it was armed at PAGE LOAD (not at the first draw), it fired on an
 * empty queue four seconds later, and it latched — every later draw skipped
 * the import and flushed the chart to the dead empty state. Two properties are
 * locked here:
 *   - the guard belongs to ONE attempt and starts with the demand (a page that
 *     nobody asks for charts never arms a timer);
 *   - a failure is not a latch: a later draw retries, bounded, and the empty
 *     state names which class of failure happened (route / module / timeout).
 */
import { assert, done } from './lib.mjs'
import {
  createChartLibBridge, CHART_LIB_COPIES, CHART_LIB_LOAD, PANEL_PAGE_HTML,
} from '../src/host/panel-page.ts'

let n = 0
const tick = () => new Promise((r) => setTimeout(r, 0))

/** One bridge on fake timers + promise-returning stubs. `timers` is the armed
 *  guard set; fireTimers() runs them (the 4s no-report guard, deterministically). */
function bench({ importLib, probeRoute, onReady } = {}) {
  const timers = new Map()
  let nextId = 1
  const calls = { imports: 0, probes: 0, ready: [], fail: [], failures: [] }
  const bridge = createChartLibBridge({
    importLib: function () { calls.imports += 1; return importLib() },
    probeRoute: function () { calls.probes += 1; return probeRoute() },
    setTimer: function (fn, ms) { const id = nextId++; timers.set(id, { fn, ms }); return id },
    clearTimer: function (h) { timers.delete(h) },
    timeoutMs: CHART_LIB_LOAD.TIMEOUT_MS,
    maxAttempts: CHART_LIB_LOAD.MAX_ATTEMPTS,
    copies: CHART_LIB_COPIES,
    onReady: function (m) { calls.ready.push(m); if (onReady) onReady(m) },
    onFail: function (m) { calls.fail.push(m) },
  })
  return {
    bridge, calls,
    armed: () => timers.size,
    armedMs: () => [...timers.values()].map((t) => t.ms),
    fireTimers() { for (const [id, t] of [...timers]) { timers.delete(id); t.fn() } },
  }
}
const ok = (mod) => () => Promise.resolve(mod)
const rejected = () => () => Promise.reject(new Error('load failed'))
const routeDown = () => Promise.resolve(false)
const routeUp = () => Promise.resolve(true)

// ---- the copy contract: each failure class is named, and they differ ----
const CAUSES = ['unreachable', 'moduleError', 'timedOut']
assert(String(CHART_LIB_COPIES.failed) === 'charts could not load',
  'the base phrase the host reported stays the phrase (no copy drift)')
assert(CAUSES.every((k) => typeof CHART_LIB_COPIES[k] === 'string'
  && CHART_LIB_COPIES[k].startsWith('charts could not load: ')),
  'every named cause starts from the base phrase, then names the class')
assert(new Set(CAUSES.map((k) => CHART_LIB_COPIES[k])).size === CAUSES.length,
  'the three cause lines are distinct (a reader can tell them apart)')
assert(CHART_LIB_COPIES.unreachable.includes('could not be reached')
  && CHART_LIB_COPIES.moduleError.includes('failed to run')
  && CHART_LIB_COPIES.timedOut.includes('in time'),
  'the lines say route / module / timeout in plain words')
n += 4

// ---- the budget is bounded and the served page carries the source ----
assert(Number.isInteger(CHART_LIB_LOAD.MAX_ATTEMPTS) && CHART_LIB_LOAD.MAX_ATTEMPTS >= 2
  && CHART_LIB_LOAD.MAX_ATTEMPTS < 10, 'the retry budget is a small bounded number (2..9)')
assert(CHART_LIB_LOAD.TIMEOUT_MS === 4000, 'one attempt waits 4s before the guard reports a timeout')
assert(PANEL_PAGE_HTML.includes('createChartLibBridge({'),
  'the served page builds the bridge (one implementation with this test)')
assert(CAUSES.every((k) => PANEL_PAGE_HTML.includes(CHART_LIB_COPIES[k])),
  'the served page carries all three named cause lines')
n += 4

// ---- DEFECT 1: the guard must not be armed by page load ----
{
  const b = bench({ importLib: ok({ init() {} }), probeRoute: routeUp })
  assert(b.calls.imports === 0 && b.armed() === 0,
    'a page that never asks for charts arms no timer and imports nothing (the page-load guard is gone)')
  n += 1
}

// ---- the first demand arms exactly one guard for one attempt ----
{
  const b = bench({ importLib: () => new Promise(() => {}), probeRoute: routeUp })
  b.bridge.start()
  b.bridge.start()
  assert(b.calls.imports === 1 && b.armed() === 1 && b.armedMs()[0] === CHART_LIB_LOAD.TIMEOUT_MS,
    'two draws during one attempt share one import and one 4s guard (no double load)')
  n += 1
}

// ---- DEFECT 2 (fail once -> retry -> succeed): the latch is gone ----
{
  const mod = { init() {} }
  let attempt = 0
  const b = bench({
    importLib: () => { attempt += 1; return attempt === 1 ? Promise.reject(new Error('first load failed')) : Promise.resolve(mod) },
    probeRoute: routeDown,
  })
  b.bridge.start()
  await tick()
  assert(b.calls.fail.length === 1 && b.calls.fail[0] === CHART_LIB_COPIES.unreachable,
    'a first failure names the route class and does not report ready')
  assert(b.bridge.isReady() === false && b.bridge.attempts() === 1 && b.armed() === 0,
    'the failed attempt cleared its guard and is not ready')
  b.bridge.start()      // the later draw (a re-entry into the Metrics tab)
  await tick()
  assert(b.calls.imports === 2, 'a later draw retries the module load (one transient failure is survivable)')
  assert(b.bridge.isReady() === true && b.calls.ready.length === 1 && b.calls.ready[0] === mod,
    'the retry hands the loaded library to the page')
  assert(b.calls.fail.length === 1, 'the recovery did not report a second failure')
  b.bridge.start()
  assert(b.calls.imports === 2, 'once ready, a draw never re-imports')
  n += 6
}

// ---- the retry is BOUNDED: no loop, and the last named cause stands ----
{
  const b = bench({ importLib: rejected(), probeRoute: routeDown })
  for (let i = 0; i < 8; i++) { b.bridge.start(); await tick() }
  assert(b.calls.imports === CHART_LIB_LOAD.MAX_ATTEMPTS,
    'eight draws spend at most MAX_ATTEMPTS imports (no unbounded retry loop)')
  assert(b.calls.fail.length > CHART_LIB_LOAD.MAX_ATTEMPTS - 1
    && b.calls.fail.slice(-1)[0] === CHART_LIB_COPIES.unreachable,
    'after the budget is spent every draw re-reads the last named cause (never a silent blank)')
  n += 2
}

// ---- the cause is classified, not guessed ----
{
  const a = bench({ importLib: rejected(), probeRoute: routeUp })
  a.bridge.start(); await tick()
  assert(a.calls.fail[0] === CHART_LIB_COPIES.moduleError,
    'a rejected import with the file still served reports the module class (served, but failed to run)')
  const c = bench({ importLib: rejected(), probeRoute: () => Promise.reject(new Error('probe failed')) })
  c.bridge.start(); await tick()
  assert(c.calls.fail[0] === CHART_LIB_COPIES.unreachable,
    'an unreachable probe reports the route class (no false "module error")')
  n += 2
}

// ---- a build without init rejects through onReady (the page's check) ----
{
  const b = bench({ importLib: ok({ noInit: true }), probeRoute: routeUp, onReady: () => { throw new Error('echarts build has no init') } })
  b.bridge.start(); await tick()
  assert(b.calls.fail[0] === CHART_LIB_COPIES.moduleError && b.bridge.isReady() === false,
    'a library that cannot init reports the module class instead of claiming ready')
  b.bridge.start()
  assert(b.calls.imports === 2, 'a failed adoption is retried by the next draw, not latched')
  n += 2
}

// ---- the 4s guard: one attempt timed out, and the tab is not latched ----
{
  const b = bench({ importLib: () => new Promise(() => {}), probeRoute: routeUp })
  b.bridge.start()
  b.fireTimers()
  assert(b.calls.fail.length === 1 && b.calls.fail[0] === CHART_LIB_COPIES.timedOut,
    'a module that never reports names the timeout class')
  b.bridge.start()
  assert(b.calls.imports === 2, 'a timeout is retried by a later draw (not a latch)')
  n += 2
}

// ---- a late arrival after the timeout still lands (no second fetch needed) ----
{
  let resolveIt
  const mod = { init() {} }
  const b = bench({ importLib: () => new Promise((r) => { resolveIt = r }), probeRoute: routeUp })
  b.bridge.start()
  b.fireTimers()
  assert(b.calls.fail[0] === CHART_LIB_COPIES.timedOut, 'the slow first load names the timeout class')
  resolveIt(mod); await tick()
  assert(b.bridge.isReady() === true && b.calls.ready.length === 1 && b.calls.imports === 1,
    'a late arrival adopts the library without a second fetch (the tab recovers on its next draw)')
  n += 2
}

// ---- a stale attempt cannot overwrite a newer attempt's outcome ----
{
  let rejectFirst
  let attempt = 0
  const b = bench({
    importLib: () => {
      attempt += 1
      return attempt === 1 ? new Promise((_r, rej) => { rejectFirst = rej }) : Promise.resolve({ init() {} })
    },
    probeRoute: routeUp,
  })
  b.bridge.start()
  b.fireTimers()               // attempt 1 times out, attempt 2 may start
  b.bridge.start()
  await tick()                 // attempt 2 succeeds
  rejectFirst(new Error('late rejection from the timed-out attempt'))
  await tick()
  assert(b.calls.fail.length === 1 && b.calls.fail[0] === CHART_LIB_COPIES.timedOut,
    'a stale rejection from an older attempt does not report a fresh failure')
  assert(b.bridge.isReady() === true, 'the newer attempt stays ready')
  n += 2
}

// ---- a synchronous throw from an injected dependency is a failure, not a latch ----
{
  const b = bench({ importLib: () => { throw new Error('loader blew up') }, probeRoute: routeUp })
  b.bridge.start()
  assert(b.calls.fail.length === 1 && b.calls.fail[0] === CHART_LIB_COPIES.moduleError && b.armed() === 0,
    'a loader that throws instead of rejecting reports the module class and clears its guard')
  b.bridge.start()
  assert(b.calls.imports === 2, 'the next draw still retries after a synchronous loader throw')
  n += 2
}
{
  const b = bench({ importLib: rejected(), probeRoute: () => { throw new Error('probe blew up') } })
  b.bridge.start(); await tick()
  assert(b.calls.fail[0] === CHART_LIB_COPIES.unreachable,
    'a probe that throws reports the route class instead of hanging the attempt')
  n += 1
}

// ---- the two page seams keep working (they no longer own the load path) ----
{
  const b = bench({ importLib: rejected(), probeRoute: routeDown })
  const seamLib = { draw() {}, dispose() {} }
  b.bridge.adopt(seamLib)
  assert(b.bridge.isReady() === true && b.calls.ready.length === 1 && b.calls.imports === 0,
    '__metricsChartLibReady adopts an externally loaded library without fetching')
  const b2 = bench({ importLib: rejected(), probeRoute: routeDown })
  b2.bridge.failNow()
  assert(b2.calls.fail[0] === CHART_LIB_COPIES.moduleError, '__metricsChartLibFail names the module class')
  n += 2
}

done(n)
