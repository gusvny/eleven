// t261008-21 sidebar dwell window pinned at 24 h (host order 261008 option A):
//   Settings popover retired; window rule survives in sandbar-dwell.ts as the
//   single reader; legacy stored value ignored + removed (chosen over clamp —
//   with the knob gone, hidden stored state must not steer the window).
// Independent (node ≥22 type-stripping, cwd=repo root; exit 0 = pass).
// Rendering assertions (footer without gear/popover, light+dark) belong to the
// integration capture family; this file pins pure logic + source/bundle anchors.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { inSandbar, sandbarHours, SANDBAR_DEFAULT_H } from '../src/client/sandbar-dwell.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

/* ---- localStorage stub (fresh per group; module reads storage at call time) ---- */
let store = new Map()
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
}
const CLOSED = 'closed'
const hourOld = h => Math.floor(Date.now() / 1000) - h * 3600

/* ---- window truth table (the surviving 24 h rule) ---- */
ok(SANDBAR_DEFAULT_H === 24, 'pin = 24 (named constant)')
ok(inSandbar({ status: 'dispatched', close_ts: hourOld(999) }, Date.now() / 1000), 'open row always rendered')
ok(inSandbar({ status: CLOSED, close_ts: hourOld(1) }, Date.now() / 1000), 'closed 1h ago -> rendered (inside 24h)')
ok(inSandbar({ status: CLOSED, close_ts: hourOld(23) }, Date.now() / 1000), 'closed 23h ago -> rendered')
ok(!inSandbar({ status: CLOSED, close_ts: hourOld(24) }, Date.now() / 1000), 'closed exactly 24h ago -> left (strict <)')
ok(!inSandbar({ status: CLOSED, close_ts: hourOld(25) }, Date.now() / 1000), 'closed 25h ago -> filtered')
ok(!inSandbar({ status: CLOSED, close_ts: hourOld(999) }, Date.now() / 1000), 'closed 999h ago -> filtered')
ok(inSandbar({ status: CLOSED, created: hourOld(1) }, Date.now() / 1000), 'close_ts missing -> created fallback, inside window')
ok(!inSandbar({ status: CLOSED, created: hourOld(25) }, Date.now() / 1000), 'close_ts missing -> created fallback, outside window')
ok(!inSandbar({ status: CLOSED }, Date.now() / 1000), 'close_ts and created missing -> filtered (ts=0 guard)')

/* ---- stale localStorage must not steer the window (chosen policy: ignore + remove) ---- */
store = new Map([['sandbar-workbench-sandbar-v1', '999']])
ok(sandbarHours() === 24, 'stored 999 ignored -> pin 24')
ok(!store.has('sandbar-workbench-sandbar-v1'), 'legacy key removed by the read (one-shot, idempotent)')
ok(!inSandbar({ status: CLOSED, close_ts: hourOld(25) }, Date.now() / 1000), 'stale 999 does NOT widen the window')
ok(inSandbar({ status: CLOSED, close_ts: hourOld(1) }, Date.now() / 1000), 'stale 999 does not break rendering either')
for (const bad of ['abc', '-5', '0', 'NaN', '']) {
  store = new Map([['sandbar-workbench-sandbar-v1', bad]])
  ok(sandbarHours() === 24, `malformed stored value ${JSON.stringify(bad)} ignored -> pin 24`)
}
store = new Map()
ok(sandbarHours() === 24 && sandbarHours() === 24, 'idempotent: repeated reads stable, no storage')
// storage throwing must not break the read (guard path)
globalThis.localStorage = { getItem: () => { throw new Error('denied') }, removeItem: () => { throw new Error('denied') } }
ok(sandbarHours() === 24, 'storage unavailable -> pin 24, no throw')
globalThis.localStorage = undefined
ok(sandbarHours() === 24, 'no localStorage at all -> pin 24, no throw')

/* ---- source + bundle anchors (src, lib/client.js, lib/client.cjs) ---- */
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
const src = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
const dwell = readFileSync(join(repo, 'server/plugins/workbench/src/client/sandbar-dwell.ts'), 'utf8')
const bundles = ['lib/client.js', 'lib/client.cjs'].map(rel =>
  readFileSync(join(repo, 'server/plugins/workbench', rel), 'utf8'))
for (const [name, text] of [['sidebar.tsx', src], ['lib/client.js', bundles[0]], ['lib/client.cjs', bundles[1]]]) {
  for (const gone of ['wb-sb-setpop', 'Sandbar dwell', 'Quiet in-progress threshold',
    'setSandbarHours', 'settingsOpen', 'wb-sb-foot-btn']) {
    ok(!text.includes(gone), `${name}: retired anchor absent: ${gone}`)
  }
  ok(text.includes('inSandbar'), `${name}: window rule still wired (inSandbar present)`)
}
ok(dwell.includes('sandbar-workbench-sandbar-v1'), 'SANDBAR_KEY literal survives once in sandbar-dwell (remover side)')
ok(dwell.split('SANDBAR_KEY').length - 1 === 2, 'SANDBAR_KEY appears only in sandbar-dwell (2 refs: decl + remove)')
ok(!src.includes('sandbar-workbench-sandbar-v1'), 'sidebar no longer touches the storage key')
ok(src.includes('wb-sb-foot-sp') && src.includes('wb-sb-foot'), 'footer keeps its original shape (foot + spacer)')
ok(src.includes('驻留窗分工'), 'two-window split anchor kept verbatim (inspection rows exempt, t260916-15/t260915-19 pins)')

console.log(`ok ${n} assertions (t261008-21 sidebar dwell pinned)`)
