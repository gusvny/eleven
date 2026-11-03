#!/usr/bin/env node
/**
 * t261102-09-file-pane-ui.mjs — render-face source locks for the middle-column file
 * sheet (same family as t261005-04-overlay-ui.mjs).
 *
 * These are SENTINELS, not testimony: "the click really lands in the middle column" is
 * proven by the integration stage's L3 case. What is pinned here is the wiring that
 * fails silently when it drifts. Two real review findings live here:
 *
 *   R2  .wb-right-content must gain no position: it is an ancestor of the ticket drawer,
 *       so positioning it would move the drawer's box out of .wb-sb-right.
 *   R10 the collapse condition must include isExpanded(): active() is also undefined
 *       with no seat mounted, so the missing term would EXPAND an empty column.
 *   R6  one endpoint constant for both halves, and the route is really registered on the
 *       mock webServer (see section A of t261102-09-file-read.mjs).
 *
 * Section H loads the built bundle once. It exists because the CSS constant is a template
 * literal: one backtick in a comment truncates it, the rest of the text becomes an
 * expression, the build still "succeeds", and only an actual evaluation throws. Source
 * text assertions cannot see that class.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const HERE = new URL('.', import.meta.url).pathname
const src = (rel) => readFileSync(join(HERE, '..', rel), 'utf8')
const indexSrc = src('src/client/index.tsx')
const sidebarSrc = src('src/client/sidebar.tsx')
const bridgeSrc = src('src/client/file-bridge.tsx')
const paneSrc = src('src/client/file-pane.tsx')
const modelSrc = src('src/client/file-pane-model.ts')
const storeSrc = src('src/client/file-open-request.ts')
const routeSrc = src('src/client/file-route.ts')
const nodeSrc = src('node.ts')
const libSrc = src('lib/client.cjs')

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) {
    pass += 1
    console.log(`  ok ${label}`)
  } else {
    fail += 1
    console.error(`  FAIL ${label}`)
  }
}
function section(t) {
  console.log(`\n== ${t}`)
}

/** One CSS rule body: the text between `<selector> {` and its closing brace. */
function ruleBody(text, selector) {
  const at = text.indexOf(`${selector} {`)
  if (at === -1) return null
  const end = text.indexOf('}', at)
  return end === -1 ? null : text.slice(at, end)
}

section('A. Type and body registration (extension band, keyed by the implementation id)')
{
  ok(indexSrc.includes("const FILE_TAB_ID = 'sandbar-workbench/file-bridge'"), 'the implementation id is a constant')
  ok(indexSrc.includes("const FILE_TAB_KIND = 'sandbar-workbench.file-bridge'"), 'the kind is a constant')
  ok(indexSrc.includes("patterns: ['dsh-resource://file/**']"), 'it claims file addresses only')
  ok(indexSrc.includes("priority: 'extension'"), 'extension band (it outranks the builtin fallback)')
  ok(indexSrc.includes('canOpen: claimsTextFile'), 'the claim predicate is the pure model, not an inline test')
  ok(indexSrc.includes('title: fileTitleOf'), 'the chip text comes from the pure model')
  ok(indexSrc.includes("name: 'sidebar.right.pane.tab'"), 'the body registers in the keyed tab slot')
  ok(indexSrc.includes('key: FILE_TAB_ID'), 'the slot key is the implementation id')
  ok(indexSrc.includes('hooks: { tabInfo: (_standard: unknown, useTabInfo: unknown) => useTabInfo }'),
    'tab info uses the pass-through factory (the platform types connect it the same way)')
  ok(indexSrc.includes("getService?.('sidebarRightTabs')"), 'the service is probed through ctx.get')
  ok(!/ctx\.sidebarRightTabs/.test(indexSrc), 'no property access for sidebarRightTabs (it throws without inject)')
  ok(/file claim skipped/.test(indexSrc), 'a missing service is a declared degradation with one warn line')
}

section('B. Bridge (forward first, close itself second, collapse only when expanded and empty)')
{
  const closeAt = bridgeSrc.indexOf('tab?.actions?.close?.()')
  const forwardAt = bridgeSrc.indexOf('requestFileOpen({')
  ok(forwardAt !== -1 && closeAt !== -1 && forwardAt < closeAt, 'the forward happens before the close')
  ok(bridgeSrc.includes('right.isExpanded() === true && right.active() === undefined'), 'the collapse condition keeps isExpanded() (R10)')
  ok(bridgeSrc.includes('right.toggleExpanded()'), 'an empty column collapses through toggleExpanded')
  ok(bridgeSrc.includes('parseFileAddress(address)'), 'the address goes through the model parser')
  ok(bridgeSrc.includes('bindBridgeService') && indexSrc.includes('bindBridgeService(getService)'),
    'the service probe is bound once at apply time (the seat hands only hooks as props)')
  ok(indexSrc.includes('}, FileBridgeBody))'), 'the registered component IS the body (the seat renders one level)')
  ok(bridgeSrc.includes('the address cannot be parsed'), 'a parse failure renders a named banner (no throw)')
  ok(bridgeSrc.includes('the tab-info hook is missing'), 'a missing injected hook renders a named banner')
  ok((bridgeSrc.match(/console\.warn\(/g) || []).length >= 2, 'a failed close and a failed collapse each log one line')
}

section('C. Mount point and geometry (R2: the drawer box does not move)')
{
  const mountAt = sidebarSrc.indexOf('{fileOpen !== null && <FilePane />}')
  const contentAt = sidebarSrc.indexOf('className="wb-right-content"')
  const footAt = sidebarSrc.indexOf('className="wb-sb-foot"')
  ok(mountAt !== -1, 'the sheet is mounted')
  ok(contentAt !== -1 && mountAt > contentAt, 'it mounts after the middle-column container')
  ok(footAt !== -1 && mountAt < footAt, 'it mounts before the foot strip (a sibling inside .wb-sb-right)')
  ok(sidebarSrc.includes('useSyncExternalStore(subscribeFileOpen, readFileOpenRequest, readFileOpenRequest)'),
    'the sidebar subscribes to the one-slot store')
  const contentRule = ruleBody(sidebarSrc, '.wb-right-content')
  ok(contentRule !== null, 'the .wb-right-content rule is present')
  ok(contentRule !== null && !/position\s*:/.test(contentRule), '.wb-right-content gains no position (R2: the drawer ancestor stays put)')
  ok(sidebarSrc.includes('.wb-sb-right {') && /position:relative/.test(ruleBody(sidebarSrc, '.wb-sb-right') ?? ''),
    '.wb-sb-right is still the containing block')
  const paneRule = ruleBody(sidebarSrc, '.wb-file-pane')
  ok(paneRule !== null && /position:absolute/.test(paneRule), 'the sheet is absolutely positioned')
  ok(paneRule !== null && /z-index:91/.test(paneRule), 'z-index 91 (above the drawer 90, below the modal 99)')
}

section('D. The sheet (title bar / line target / keys / full end-state cleanup)')
{
  for (const anchor of ['data-file-pane-back', 'data-file-pane-copy', 'data-file-pane-path',
    'data-file-pane-retry', 'data-file-pane-refused', 'data-file-line-hit', 'data-file-pane-src', 'data-file-pane-md']) {
    ok(paneSrc.includes(anchor), `anchor present: ${anchor}`)
  }
  ok(paneSrc.includes('renderMarkdown') && paneSrc.includes('knowledge/src/client/markdown.ts'), 'markdown goes through the existing renderer')
  ok(paneSrc.includes('FILE_READ_PATH'), 'the read uses the shared constant (R6)')
  ok(paneSrc.includes('const controller = new AbortController()'), 'the read is abortable')
  ok(paneSrc.includes('controller.abort()'), 'unmount and a new request abort it (full end-state cleanup)')
  ok(paneSrc.includes('if (copyTimer.current !== null) clearTimeout(copyTimer.current)'), 'the copy label timer is cleared')
  ok(paneSrc.includes("window.addEventListener('keydown', onKey, true)"), 'the key listener runs in the capture phase (before the drawer window listener)')
  ok(paneSrc.includes("window.removeEventListener('keydown', onKey, true)"), 'the key listener is removed in pairs')

  const escAt = paneSrc.indexOf("ev.key === 'Escape'")
  const escBlock = escAt === -1 ? '' : paneSrc.slice(escAt, escAt + 220)
  ok(escBlock.includes('preventDefault()') && escBlock.includes('stopPropagation()'), 'Escape: preventDefault plus stopPropagation (closes this layer only)')
  const arrowLine = paneSrc.split('\n').find((l) => l.includes("ev.key === 'ArrowUp'")) ?? ''
  ok(arrowLine.includes('stopPropagation()'), 'arrow keys stop propagation (the drawer walk stays off)')
  ok(!arrowLine.includes('preventDefault'), 'arrow keys do not preventDefault (the file body still scrolls)')
  ok(paneSrc.includes("data-file-line-hit={hit ? '' : undefined}"), 'the target row carries a marker')
  ok(paneSrc.includes("scrollIntoView({ block: 'center' })"), 'the target row scrolls into view')
  ok(paneSrc.includes('planSourceRows(') && paneSrc.includes('plan.clipped') && paneSrc.includes('data-file-pane-row-clip'),
    'the clip note is driven by the model rule (rows dropped), not by a line count')
  ok(!paneSrc.includes('result.lines'), 'the pane does not compare its rows with the host line count (the false-clip defect)')
  ok(paneSrc.includes('lineNoteOf(') && paneSrc.includes('lineNote.text'),
    'the line note comes from the model rule (a past-the-end request says so)')
}

section('E. Pure model and store shape')
{
  ok(/export function claimsTextFile/.test(modelSrc), 'the claim predicate is exported by the model')
  ok(/export function describeReadFailure/.test(modelSrc), 'the read-failure translation is exported (route-not-served included)')
  ok(modelSrc.includes('route-missing') && modelSrc.includes('restart'), 'a route that is not served is named and points at the restart (KI-052 window)')
  ok(/Symbol\.for\('sandbar\.workbench\.fileOpen\.v1'\)/.test(storeSrc), 'the store is anchored on a globalThis symbol (a re-register keeps it)')
  ok(storeSrc.includes('held.address === address'), 'the same address takes the reuse branch (acceptance 5)')
  ok(!/^import /m.test(routeSrc), 'the route constant module has zero imports (both halves may import it)')
  ok(routeSrc.includes("export const FILE_READ_PATH = '/sandbar-workbench/api/wf/file'"), 'the constant value')
}

section('F. Host half (guards and route wiring)')
{
  ok(nodeSrc.includes('file-route.ts') && nodeSrc.includes('FILE_READ_PATH'), 'node.ts imports the shared constant')
  ok(nodeSrc.includes("ws.register({ kind: 'exact', path: FILE_READ_PATH, handler: handleFileRead })"), 'the route registers the constant')
  ok(nodeSrc.includes('const FILE_READ_MAX_BYTES = 1024 * 1024'), 'the size cap is in place')
  ok(nodeSrc.includes('function withinRoot('), 'the separator-bounded containment test is in place')
  ok(nodeSrc.includes('await realpath(abs)'), 'the real path resolution is in place (the symlink gate)')
  ok(nodeSrc.includes("new TextDecoder('utf-8', { fatal: true })"), 'strict UTF-8 decoding is in place')
  ok(nodeSrc.includes("'session-workspace-unknown'"), 'an unknown session workspace is a named refusal')
  ok(nodeSrc.includes('session?.header?.cwd'), 'the workspace is read from header.cwd (R15)')
  ok(!nodeSrc.includes('session?.meta?.cwd'), 'meta.cwd is never read (it is not a Session field)')
  ok(nodeSrc.includes("reason: 'bad-session'"), 'a malformed session is a named 400 (S5)')
  ok(nodeSrc.includes('lexical.some((root) => withinRoot(root, abs))'), 'the lexical test runs first (S1)')
  ok(nodeSrc.includes("reason: 'method-not-allowed'"), 'a write verb never returns file content (405, read-only)')
  ok(storeSrc.includes('const HOLDER_KEY = Symbol.for(') && storeSrc.includes('FileOpenStore'),
    'the published anchor is the store API object, not private state')
}

section('G. Artifact parity (a forgotten rebuild fails here)')
{
  ok(libSrc.includes('wb-file-pane') && libSrc.includes('data-file-pane-back'), 'lib/client.cjs carries the sheet markers (rebuilt)')
  ok(libSrc.includes('sandbar-workbench/file-bridge'), 'lib/client.cjs carries the claim type id')
  ok(libSrc.includes('sandbar.workbench.fileOpen.v1'), 'lib/client.cjs carries the store anchor')
  ok(/\.wb-file-pane \{ position:absolute;[^}]*z-index:91/.test(libSrc), 'the sheet rule in the bundle is still absolute with z-index 91')
}

section('H. The artifact loads (React surface shapes + the template-literal truncation gate)')
{
  // Why a shape matrix: the artifact evaluates `class SlotErrorBoundary extends <base>` at
  // module scope, so ANY host whose module table hands a partial React kills the whole
  // bundle before a single assertion runs — the send-back's "Class extends value undefined
  // is not a constructor or null". The three shapes below are the ones that occur: a
  // hooks-only surface (the integration harness's fake), a non-constructible stand-in, and
  // a real class base. All three must load; only the last one keeps the boundary active.
  const jsx = { jsx: (_t, p) => p, jsxs: (_t, p) => p, Fragment: Symbol('harness.fragment') }
  const hooksOnly = {
    useState: () => [null, () => {}],
    useEffect: () => {},
    useRef: () => ({ current: null }),
    useMemo: (f) => f(),
    useCallback: (f) => f,
    useSyncExternalStore: (_s, g) => g(),
    memo: (c) => c,
  }
  const load = (makeReact) => {
    let loaded = null
    let error = null
    const savedWindow = globalThis.window
    try {
      globalThis.window = { __ModuleLoader__: { load: (e) => { loaded = e } } }
      new Function('require', libSrc)((name) => (name === 'react' ? makeReact() : jsx))
      if (loaded === null) return { loaded: null, error: new Error('the module loader entry was never called') }
      const exports = loaded.factory((name) => (name === 'react' ? makeReact() : jsx))
      return { loaded, exports, error: null }
    } catch (err) {
      error = err
      return { loaded, exports: null, error }
    } finally {
      if (savedWindow === undefined) delete globalThis.window
      else globalThis.window = savedWindow
    }
  }

  const plain = load(() => hooksOnly)
  ok(plain.error === null && typeof plain.exports?.apply === 'function',
    `a hooks-only React surface still boots the artifact${plain.error === null ? '' : ` (measured: ${String(plain.error.message)})`}`)
  ok(plain.loaded?.id === 'sandbar-workbench', 'the artifact registers as sandbar-workbench')

  const fakeBase = load(() => ({ ...hooksOnly, Component: () => ({}) }))
  ok(fakeBase.error === null && typeof fakeBase.exports?.apply === 'function',
    `a non-constructible class base still boots the artifact${fakeBase.error === null ? '' : ` (measured: ${String(fakeBase.error.message)})`}`)

  const realBase = load(() => ({ ...hooksOnly, Component: class { constructor(p) { this.props = p } } }))
  ok(realBase.error === null && typeof realBase.exports?.apply === 'function',
    `a real class base boots the artifact (the production shape)${realBase.error === null ? '' : ` (measured: ${String(realBase.error.message)})`}`)

  ok(indexSrc.includes('isConstructibleBase(Component)'), 'the boundary base is chosen by a constructibility probe, not by typeof')
  ok(indexSrc.includes('class SlotBoundaryPassThrough'), 'a missing class base degrades to a declared pass-through')
}

console.log(`\nt261102-09-file-pane-ui: pass=${pass} fail=${fail}`)
assert.equal(fail, 0, `${fail} assertion(s) failed`)
process.exit(fail === 0 ? 0 : 1)
