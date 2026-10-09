// t261009-03 CL-3 reorder write face landed + refused reorder visible:
// source-lock + pure-function UT (independently runnable, cwd=repo root;
// exit 0 = pass). Distinct faces from the queue-model battery (t26100618):
// this one locks the WRITE path seams — ticket.py routes `order` to the
// engine's single reorder implementation; node.ts's 409 anomaly text is
// neutral (names no unverified cause, never fakes success); the sidebar
// guard refusal (null face / stale face) sets the visible notice line
// instead of a silent return (the "drag looked inert" fix).
// Malformed-input discipline: the refusal shapes are inlined stubs here;
// the live CLI behaviour face is the offline scenario
// integration/sc_check_concurrency_reorder_face.py (mechanical gate runs it).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { permutationOf } from '../src/client/queue-model.ts'

let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${name}`) }

const ROOT = process.cwd()
const ticketSrc = readFileSync(`${ROOT}/server/tools/ticket.py`, 'utf8')
const nodeSrc = readFileSync(`${ROOT}/server/plugins/workbench/node.ts`, 'utf8')
const sidebarSrc = readFileSync(`${ROOT}/server/plugins/workbench/src/client/sidebar.tsx`, 'utf8')

/* --------------------------------------- ticket.py order face (write seam) */

ok('ticket.py op=concurrency routes order to the engine reorder (single implementation)', () => {
  assert.match(ticketSrc, /args\.get\('order'\) is not None/)
  assert.match(ticketSrc, /conc\.reorder\(project, args\.get\('order'\)\)/)
  assert.match(ticketSrc, /return conc\.read_state\(project\)/)
})

ok('ticket.py shell adds no second permutation validation (engine-only check)', () => {
  // The shell body between the order route and the engine call must not
  // sort/set-compare the order list (no re-implemented permutation check).
  const m = ticketSrc.match(/if args\.get\('order'\) is not None:\n([\s\S]*?)\n    if not args\.get\('reconcile'\)/)
  assert.ok(m)
  assert.doesNotMatch(m[1], /sorted\(|set\(|permutation/i)
})

ok('reconcile+order combined: order wins (review conditional 4a, documented)', () => {
  // The order branch sits BEFORE the reconcile branch in _concurrency.
  assert.ok(ticketSrc.indexOf("args.get('order') is not None")
    < ticketSrc.indexOf("if not args.get('reconcile')"))
  assert.match(ticketSrc, /order 胜/)
})

ok('identity gate named honestly: admin-CLI spawn boundary + KI-193 debt', () => {
  assert.match(ticketSrc, /runAdminCli/)
  assert.match(ticketSrc, /KI-193/)
  assert.match(ticketSrc, /set_limit/)
})

/* --------------------------------------- node.ts 409 anomaly text (neutral) */

ok('node.ts 409 anomaly text is neutral and never fakes success', () => {
  assert.match(nodeSrc, /concurrency reorder not applied: the engine\\?'s returned queue /)
  assert.match(nodeSrc, /differs from the requested order — refusing to fake success/)
  // The stale "write face not landed" claim is retired with the face landed.
  assert.doesNotMatch(nodeSrc, /ignored the order key/)
  assert.match(nodeSrc, /ok: false/) // still a refusal, never {ok:true}
})

ok('engine permutation refusal rides the 502 verbatim path (not swallowed)', () => {
  // The ok!==true branch forwards r.error verbatim (502), which the client
  // renders in the notice line.
  assert.match(nodeSrc, /String\(r\?\.error \?\? 'concurrency reorder failed'\)/)
})

/* ------------------------------- sidebar guard refusal is VISIBLE (outcome 3) */

ok('sidebar: the null/stale face guard sets the notice line (no silent inert drag)', () => {
  assert.match(sidebarSrc, /the queue face is unavailable or stale — no move made/)
  assert.match(sidebarSrc, /setOrderNotice\(m => \(\{ \.\.\.m, \[projectKey\]:\n/)
  // The old bare silent return is gone.
  assert.doesNotMatch(sidebarSrc, /if \(want === null\) return /)
})

ok('sidebar notice element still renders the refusal (role=alert, no dev tools)', () => {
  assert.match(sidebarSrc, /wb-order-notice/)
  assert.match(sidebarSrc, /role="alert"/)
})

/* ------------------------------------- pure guard: permutationOf still gates */

ok('permutationOf refuses a stale order (the client-side no-round-trip guard)', () => {
  assert.equal(permutationOf(['a', 'b', 'c'], ['a', 'b']), null)
  assert.equal(permutationOf(['a', 'b', 'c'], ['a', 'b', 'x']), null)
  assert.deepEqual(permutationOf(['a', 'b', 'c'], ['c', 'a', 'b']), ['c', 'a', 'b'])
  assert.equal(permutationOf([], 'not an array'), null)
})

console.log(`\n${n} checks passed`)
