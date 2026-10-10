#!/usr/bin/env node
// sc_t26100968_lane_map_binds_scene.mjs —— shipped bundle binding face (t261009-68).
//
// intent (grey-box L2, browser-free pool, zero docker, never touches 3099):
// ticket t261009-68, host report 261010: the shipped client bundle kept a CALL
// to `laneMapScene` while the component module only TYPE-imported it, so the
// type-stripping tsdown build shipped a dangling reference and the ticket
// detail crashed at first render (ReferenceError in the host browser). The
// build does not type-check, so the only place this defect class is visible
// without a browser is the bundle itself: a called identifier with no binding.
// This scenario pins the bundle-level face of that class:
//   C1 probe sanity — the lane-map render call (`laneMapScene(`) is present in
//      lib/client.js (if the component ever stops calling it, C1 fails and the
//      C2 verdict below is meaningless — the probe must not rot silently);
//   C2 binding face — for EVERY value export of lane-map-model.ts that appears
//      as a call site `NAME(` in the shipped bundle, BOTH twin bundles
//      (client.js / client.cjs, KI-052 family) must also carry a binding for
//      that name (declaration / assignment / import binding form). On the
//      broken bundle measured 261010 this is RED (call present, binding
//      absent) — the pre-implement red is the expected TDD signal; it must be
//      green at arbitrate/merge.
//   C3 FIRST-RENDER MOUNT (t261009-68 rework, steward order: "make it actually
//      mount the component so a ReferenceError at first render fails it") —
//      the bundle factory is evaluated in node with minimal react /
//      react/jsx-runtime stubs (hook-free components only, element objects
//      walked not painted), and LaneMap itself is mounted by invoking it on a
//      shape-minimal model and walking the returned element tree through every
//      nested function component. Honesty contract of the harness: the bytes
//      under test are the committed bundle EXCEPT one appended export-hook
//      line (`exports.__t26100968LaneMap = LaneMap;` spliced before the
//      factory's `return module.exports;`) — the hook adds an export, touches
//      no original statement, and LaneMap still runs in its ORIGINAL factory
//      closure scope, so a dangling `laneMapScene` reference throws the host's
//      exact ReferenceError at this exact call. On disk the committed artifact
//      is never modified. Why not drive the app instead: LaneMap is not an
//      export; its only reach is sidebar -> panel -> detail drawer, which
//      needs DOM + ClientContext — that true-browser face stays with
//      sc_t26100968_lane_map_mount_receipt.mjs (named env-red until the stage
//      console boots). Verdict split: ReferenceError naming laneMapScene =
//      fail (the shipped crash class reproduced); any OTHER throw = na
//      (harness fixture shape, not the defect class — never laundered as
//      pass); clean element tree = pass.
// intent split: the SOURCE-level defect class (value referenced but only
// type-imported) is owned by the developer L1 type-check over src/client
// (tests/t261009-68-client-typecheck.mjs); the crash-free render receipt in a
// real browser is sc_t26100968_lane_map_mount_receipt.mjs; the lane map's
// geometry faces stay with sc_t26100953_lane_map_pipe. Twin-bundle sync as a
// generic face is owned by the existing S0 build-contract legs of the
// t261008-02/-21/-07 family — re-asserted here only as the substrate of C2,
// not as a duplicate contract. Anchored to the bundle's user-visible property
// (the reference resolves), not to line numbers (KI-051 family).
// Three-state (t260904-12): fail>0 or all-na = exit 1; env_fail>0 = exit 2.
// Missing workbench source = ENV_FAIL (nothing to judge); missing BUILT bundle
// = fail (the bundle is the product under test — a stale/unbuilt tree is a
// defect, named, never a skip).

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'lane-map-model.ts')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

const { record, summarize } = (() => {
  const rows = []
  return {
    record: (name, verdict, detail) => {
      rows.push({ name, verdict })
      console.log(`[${verdict}] ${name} :: ${detail}`)
    },
    summarize: () => {
      const pass = rows.filter((r) => r.verdict === 'pass').length
      const fail = rows.filter((r) => r.verdict === 'fail').length
      const env = rows.filter((r) => r.verdict === 'env_fail').length
      const na = rows.filter((r) => r.verdict === 'na').length
      console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${env} na=${na}`)
      if (env > 0) process.exit(2)
      if (fail > 0 || pass === 0) process.exit(1)
      process.exit(0)
    },
  }
})()

// Source face: the model's value exports (the callee family this defect
// belongs to). Source unreadable = nothing to judge = ENV_FAIL, named.
let src = null
try {
  src = readFileSync(SRC, 'utf8')
} catch (e) {
  record('S0 workbench source', 'env_fail', `lane-map-model.ts unreadable: ${String(e).slice(0, 160)}`)
  summarize()
}

const exportsRe = /^export (?:async )?(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)/gm
const names = []
for (let m; (m = exportsRe.exec(src)); ) names.push(m[1])
if (names.length === 0 || !names.includes('laneMapScene')) {
  // The callee family must at least contain the named defect's identifier;
  // otherwise the sweep below would silently guard nothing real.
  record('S0 workbench source', 'env_fail', `export sweep found ${names.length} names; laneMapScene missing — source layout drifted, sweep would be vacuous`)
  summarize()
}
record('S0 workbench source', 'pass', `${names.length} value exports in lane-map-model.ts (family incl. laneMapScene)`)

// Bundle face. Missing bundle = the product under test is absent = fail (the
// reader-side tree must ship a built client; unbuilt/stale is a named defect).
if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
  record('B1 bundles present', 'fail', 'lib/client.js or lib/client.cjs missing — workbench client not built (run bash server/plugins/workbench/build-client.sh)')
  summarize()
}
const js = readFileSync(LIB_JS, 'utf8')
const cjs = readFileSync(LIB_CJS, 'utf8')
record('B1 bundles present', 'pass', 'twin bundles readable')

// C1 probe sanity: the defect's own call site is still the thing we guard.
const callPresent = /\blaneMapScene\s*\(/.test(js)
record('C1 laneMapScene call site shipped', callPresent ? 'pass' : 'fail',
  callPresent ? 'client.js still carries the LaneMap -> laneMapScene call' : 'call site absent from client.js — component face changed; C2 verdict is vacuous until re-based')

// C2 family guard: every exported name CALLED in the bundle must be BOUND.
// Binding form kept deliberately wide (declaration, assignment, import/as
// binding) so a legal bundler rename/hoist never trips it — only a true
// dangling reference (the shipped defect) goes red.
const bindingRe = (n) =>
  new RegExp(`(?:\\b(?:function|const|let|var)\\s+${n}\\b|\\b${n}\\s*=[^=]|\\bas\\s+${n}\\b)`)
const offenders = []
for (const n of names) {
  const callRe = new RegExp(`(?<![\\w$.])${n}\\s*\\(`)
  if (!callRe.test(js)) continue
  const boundJs = bindingRe(n).test(js)
  const boundCjs = bindingRe(n).test(cjs)
  if (!boundJs || !boundCjs) offenders.push(`${n} (js:${boundJs ? 'bound' : 'DANGLING'} cjs:${boundCjs ? 'bound' : 'DANGLING'})`)
}
record(
  'C2 every called export is bound in both bundles',
  offenders.length === 0 ? 'pass' : 'fail',
  offenders.length === 0
    ? `all called value exports of lane-map-model.ts resolve in client.js and client.cjs (${names.length}-name sweep)`
    : `dangling references in the SHIPPED bundle (the t261009-68 crash class): ${offenders.join('; ')} — rebuild via bash server/plugins/workbench/build-client.sh after fixing the source import`,
)

// C3 first-render mount (real LaneMap invocation, node-only; see header note).
try {
  // Minimal react surface: hook-free components only, so the stub needs no
  // renderer — jsx() returns a plain element object and the walker below
  // invokes nested function components itself.
  const stubModules = {
    react: {
      Component: class Component { setState() {} render() {} },
      useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
      useMemo: (f) => f(),
      useRef: (v) => ({ current: v }),
      useEffect: () => {},
      useCallback: (f) => f,
      createElement: (type, props, ...kids) => ({ type, props: { ...props, children: kids } }),
      Fragment: Symbol.for('react.fragment'),
      default: {},
    },
    'react/jsx-runtime': {
      jsx: (type, props) => ({ type, props: props ?? {} }),
      jsxs: (type, props) => ({ type, props: props ?? {} }),
      Fragment: Symbol.for('react.fragment'),
    },
  }
  const raw = readFileSync(LIB_CJS, 'utf8')
  const HOOK = 'return module.exports;'
  const HOOK_LINE = 'exports.__t26100968LaneMap = LaneMap;\n'
  if (!raw.includes(HOOK)) {
    record('C3a factory hook point', 'env_fail', 'bundle tail lost `return module.exports;` — harness splice point drifted, mount face cannot be built honestly')
    summarize()
  }
  const patched = raw.replace(HOOK, HOOK_LINE + HOOK)
  // Evaluate the factory with our stub `require`; capture LaneMap from the
  // appended hook. window/ModuleLoader stubs mirror the bundle's own header.
  const captured = {}
  const sandboxWindow = { __ModuleLoader__: { load: ({ factory }) => { captured.exports = factory((name) => { if (!(name in stubModules)) throw new Error(`harness stub lacks module ${name}`); return stubModules[name] }) } } }
  const fn = new Function('window', patched)
  fn(sandboxWindow)
  const LaneMap = captured.exports && captured.exports.__t26100968LaneMap
  record('C3a LaneMap reachable from factory scope', typeof LaneMap === 'function' ? 'pass' : 'fail',
    typeof LaneMap === 'function' ? 'export hook exposed LaneMap from its original closure (one appended line, no original byte touched)' : 'hook missing — bundle shape drifted')
  if (typeof LaneMap !== 'function') summarize()

  // Shape-minimal model: every field LaneMap reads at first render; laneMapScene
  // is defensive by design (malformed input never throws), so this mounts the
  // real component without importing the real model builder.
  const model = {
    topology: { template: 'mount-probe', name: 'mount probe', nodes: [], groups: [] },
    items: [],
    groups: {},
    header: { elapsedText: '0m', nowLabel: '—', waitingForYou: false, startClock: '', endClock: '' },
  }
  let rendered = 0
  const walk = (el, depth) => {
    if (el == null || typeof el !== 'object' || depth > 24) return
    const { type, props } = el
    if (typeof type === 'function') {
      rendered++
      walk(type(props ?? {}), depth + 1)
      return
    }
    const kids = props && props.children
    for (const k of Array.isArray(kids) ? kids : [kids]) {
      if (Array.isArray(k)) for (const k2 of k) walk(k2, depth + 1)
      else walk(k, depth + 1)
    }
  }
  let mountErr = null
  try {
    walk(LaneMap({ model }), 0)
  } catch (e) {
    mountErr = e
  }
  if (!mountErr) {
    record('C3b LaneMap first render', 'pass', `mounted the bundle's LaneMap on a minimal model and walked ${rendered} component frames to a full element tree — zero ReferenceError`)
  } else if (/ReferenceError/.test(String(mountErr)) && /laneMapScene|not defined/.test(String(mountErr))) {
    record('C3b LaneMap first render', 'fail', `the shipped crash class REPRODUCED at first render: ${String(mountErr).slice(0, 200)}`)
  } else {
    record('C3b LaneMap first render', 'na', `non-defect-class throw (harness fixture shape, not laundered as pass): ${String(mountErr).slice(0, 200)}`)
  }
} catch (e) {
  record('C3 mount harness', 'env_fail', `harness could not evaluate the bundle factory: ${String(e).slice(0, 200)}`)
}

summarize()
