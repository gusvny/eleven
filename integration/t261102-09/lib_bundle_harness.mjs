// lib_bundle_harness.mjs — shared fixture for the t261102-09 integration cases
// (non-sc_ prefix = shared code, not a registered scenario).
//
// WHAT THIS IS
//   A model of the dsh client platform, small enough to run offline in seconds, that
//   loads the SERVED workbench bundle (server/plugins/workbench/lib/client.js) and
//   drives it through its public entry points only:
//     - window.__ModuleLoader__.load({id, factory})  (the platform's bundle contract)
//     - the exported apply(ctx)                       (the plugin's only entry)
//     - the right-Sidebar tab registry contract       (extension > builtin > fallback,
//                                                     a canOpen veto, claim() throws when
//                                                     nothing opens an address)
//     - the keyed slot seat 'sidebar.right.pane.tab'  (hook factories arrive as props
//                                                     named use<Name>)
//   The bundle's real module table today is exactly {react, react/jsx-runtime}; any other
//   runtime require is a NAMED failure, because the real console module table would not
//   provide it either.
//
// WHAT THIS IS NOT
//   It is not the platform. The ranker below implements the documented three-band order
//   read from dsh-client-ui-sidebar-right/lib/types/client/tab-registry.d.ts; it is the
//   case's fixture, not evidence about dsh itself. The case's job is to assert what OUR
//   registration hands to that contract, and what OUR body does when the seat renders it.
//
// BINDING DISCIPLINE
//   Assertions stay on the public contract: registration fields, the claim answers, the
//   column calls (close / collapse), the right column NOT being re-opened, and the
//   middle-column request the plugin publishes through its documented cross-evaluation
//   anchor (Symbol.for('sandbar.workbench.fileOpen*'), the same shape the repo already
//   uses for dismiss-pending-store). No class names, no private fields, no render order.

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

// ---------------------------------------------------------------------------
// React surface the bundle requires (hooks + jsx runtime). A tiny renderer that
// runs effects after render and honours setState-triggered re-renders; enough for
// a tab body, deliberately not a general React.
// ---------------------------------------------------------------------------

const JSX_FRAGMENT = Symbol.for('harness.fragment')

function makeNode(type, config, children) {
  const props = {}
  for (const [k, v] of Object.entries(config ?? {})) {
    if (k === 'children') continue
    props[k] = v
  }
  const kids = []
  if (config && config.children !== undefined) kids.push(config.children)
  for (const c of children ?? []) kids.push(c)
  if (kids.length === 1) props.children = kids[0]
  else if (kids.length > 1) props.children = kids
  return { type, props, children: kids }
}

let currentSession = null

const fakeReact = {
  createElement: (type, config, ...children) => makeNode(type, config, children),
  Fragment: JSX_FRAGMENT,
  memo: (c) => c,
  forwardRef: (c) => c,
  createContext: (defaultValue) => ({ Provider: null, defaultValue }),
  useContext: (ctx) => (ctx ? ctx.defaultValue : undefined),
  Children: {
    toArray: (x) => (x === undefined || x === null ? [] : Array.isArray(x) ? x : [x]),
    map: (x, fn) => (x === undefined || x === null ? [] : (Array.isArray(x) ? x : [x]).map(fn)),
  },
  useState(init) {
    const s = needSession('useState')
    const i = s.index++
    if (!(i in s.hooks)) s.hooks[i] = { kind: 'state', value: typeof init === 'function' ? init() : init }
    const slot = s.hooks[i]
    const set = (v) => {
      const next = typeof v === 'function' ? v(slot.value) : v
      if (!Object.is(next, slot.value)) {
        slot.value = next
        s.scheduled = true
      }
    }
    return [slot.value, set]
  },
  useRef(init) {
    const s = needSession('useRef')
    const i = s.index++
    if (!(i in s.hooks)) s.hooks[i] = { kind: 'ref', value: { current: init } }
    return s.hooks[i].value
  },
  useMemo(fn, deps) {
    const s = needSession('useMemo')
    const i = s.index++
    const prev = s.hooks[i]
    if (!prev || !sameDeps(prev.deps, deps)) {
      s.hooks[i] = { kind: 'memo', value: fn(), deps: deps ? [...deps] : null }
    }
    return s.hooks[i].value
  },
  useCallback(fn, deps) {
    const s = needSession('useCallback')
    const i = s.index++
    const prev = s.hooks[i]
    if (!prev || !sameDeps(prev.deps, deps)) s.hooks[i] = { kind: 'cb', value: fn, deps: deps ? [...deps] : null }
    return s.hooks[i].value
  },
  useEffect(fn, deps) { registerEffect('useEffect', fn, deps) },
  useLayoutEffect(fn, deps) { registerEffect('useLayoutEffect', fn, deps) },
  useSyncExternalStore(subscribe, getSnapshot) {
    const s = needSession('useSyncExternalStore')
    const i = s.index++
    const value = getSnapshot()
    if (!(i in s.hooks)) {
      const slot = { kind: 'store', value, unsubscribe: null }
      s.hooks[i] = slot
      slot.unsubscribe = subscribe(() => { s.scheduled = true })
    } else {
      s.hooks[i].value = getSnapshot()
    }
    return s.hooks[i].value
  },
  useId: () => 'harness-id',
  useTransition: () => [false, (fn) => fn()],
  useDeferredValue: (v) => v,
  useInsertionEffect: () => {},
}

const fakeJsx = {
  jsx: (type, props) => makeNode(type, props, []),
  jsxs: (type, props) => makeNode(type, props, []),
  Fragment: JSX_FRAGMENT,
}


/** The harness React surface, for a control component written by a case (self-test). */
export const reactSurface = fakeReact
/** Hyperscript helper for control components (the harness has no JSX toolchain). */
export const h = (type, props, ...children) => makeNode(type, props, children)

function needSession(hookName) {
  if (currentSession === null) throw new Error(`harness: ${hookName} called outside a render session`)
  return currentSession
}

function sameDeps(a, b) {
  if (!a || !b) return false
  if (a.length !== b.length) return false
  return a.every((v, i) => Object.is(v, b[i]))
}

function registerEffect(kind, fn, deps) {
  const s = needSession(kind)
  const i = s.index++
  const prev = s.hooks[i]
  const changed = !prev || !sameDeps(prev.deps, deps)
  if (!prev) s.hooks[i] = { kind, deps: deps ? [...deps] : null, cleanup: null }
  if (changed) {
    s.hooks[i].deps = deps ? [...deps] : null
    s.pendingEffects.push(i)
  }
  s.effects.push(fn)
}

/**
 * Render one component with the harness React surface and run its effects.
 * Re-renders while a setter or a store notification schedules work (bounded).
 * @param {(props: object) => any} Component - the component function.
 * @param {object} props - props handed to the component.
 * @param {{maxPasses?: number}} [opts]
 * @returns {{tree: any, passes: number, effectsRun: number, errors: Error[]}}
 */
export function renderComponent(Component, props, opts = {}) {
  const maxPasses = opts.maxPasses ?? 8
  const errors = []
  let tree = null
  let passes = 0
  let effectsRun = 0
  const session = { hooks: [], index: 0, effects: [], pendingEffects: [], scheduled: false }
  for (let pass = 0; pass < maxPasses; pass++) {
    passes++
    session.index = 0
    session.pendingEffects = []
    session.scheduled = false
    currentSession = session
    try {
      tree = Component(props)
    } finally {
      currentSession = null
    }
    for (const i of session.pendingEffects) {
      const fn = session.effects[i]
      const cleanup = session.hooks[i] ? session.hooks[i].cleanup : null
      if (typeof cleanup === 'function') {
        try { cleanup() } catch (e) { errors.push(e) }
      }
      try {
        const ret = fn()
        if (session.hooks[i]) session.hooks[i].cleanup = typeof ret === 'function' ? ret : null
        effectsRun++
      } catch (e) {
        errors.push(e)
      }
    }
    if (!session.scheduled) break
  }
  // Unmount cleanups (every effect ever registered gets one terminal call).
  currentSession = null
  return { tree, passes, effectsRun, errors, session }
}

/** Run the unmount cleanups the last render registered. */
export function unmountSession(rendered) {
  for (const hook of rendered.session.hooks) {
    if (hook && typeof hook.cleanup === 'function') {
      try { hook.cleanup() } catch { /* cleanup errors are not product red here */ }
      hook.cleanup = null
    }
  }
  for (const hook of rendered.session.hooks) {
    if (hook && hook.kind === 'store' && typeof hook.unsubscribe === 'function') {
      try { hook.unsubscribe() } catch { /* idempotent teardown */ }
    }
  }
}

/** Collect the visible text and attribute strings of a rendered tree. */
export function treeText(node, out = []) {
  if (node === null || node === undefined || node === false || node === true) return out
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return out }
  if (Array.isArray(node)) { for (const n of node) treeText(n, out); return out }
  if (typeof node === 'object' && node.props) {
    for (const [k, v] of Object.entries(node.props)) {
      if (k === 'children') continue
      if (typeof v === 'string' && (k === 'title' || k === 'alt' || k.startsWith('aria-') || k.startsWith('data-'))) {
        out.push(v)
      }
    }
    treeText(node.props.children, out)
    return out
  }
  return out
}

/** Every element in the tree, flattened. */
export function treeNodes(node, out = []) {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { for (const n of node) treeNodes(n, out); return out }
  if (node.props) {
    out.push(node)
    treeNodes(node.props.children, out)
  }
  return out
}

// ---------------------------------------------------------------------------
// Bundle loading
// ---------------------------------------------------------------------------

/**
 * Load the served workbench client bundle through the platform module-loader
 * contract and return its exported apply().
 * @param {{repoRoot: string}} opts
 */
export function loadServedWorkbench({ repoRoot, bundleText = null }) {
  const bundlePath = join(repoRoot, 'server', 'plugins', 'workbench', 'lib', 'client.js')
  if (bundleText === null && !existsSync(bundlePath)) {
    throw new Error(`served bundle missing: ${bundlePath} (run bash server/plugins/workbench/build-client.sh)`)
  }
  const text = bundleText === null ? readFileSync(bundlePath, 'utf8') : bundleText
  let loaded = null
  const moduleLoader = { load: (spec) => { loaded = spec } }
  const previousWindow = globalThis.window
  const previousLoader = globalThis.__ModuleLoader__
  globalThis.window = globalThis
  globalThis.__ModuleLoader__ = moduleLoader
  try {
    // The bundle is a CJS closure wrapped by the loader: evaluate it in the global
    // scope so `window.__ModuleLoader__.load(...)` fires exactly as in the browser.
    // eslint-disable-next-line no-new-func
    new Function('window', text)(globalThis)
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
    if (previousLoader === undefined) delete globalThis.__ModuleLoader__
    else globalThis.__ModuleLoader__ = previousLoader
  }
  if (loaded === null || typeof loaded.factory !== 'function') {
    throw new Error('served bundle did not call window.__ModuleLoader__.load({id, factory})')
  }
  const requireFn = (name) => {
    if (name === 'react') return fakeReact
    if (name === 'react/jsx-runtime') return fakeJsx
    throw new Error(
      `the served bundle requires '${name}' at runtime; the dsh browser module table provides react only, ` +
      'and this harness models exactly that table. Bundle the module instead of externalizing it.')
  }
  const exportsObj = loaded.factory(requireFn)
  if (typeof exportsObj.apply !== 'function') {
    throw new Error('served bundle exports no apply(ctx)')
  }
  return { apply: exportsObj.apply, exports: exportsObj, bundlePath, bundleText: text }
}

// ---------------------------------------------------------------------------
// Right-Sidebar tab registry model (documented contract, three bands)
// ---------------------------------------------------------------------------

const BAND_ORDER = { extension: 0, builtin: 1, fallback: 2 }

function globToRegExp(pattern, { matchPath }) {
  const src = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  const withStar = src
    .replace(/\*\*/g, '\u0000')
    .replace(/\*/g, '[^/]*')
    .replace(/\u0000/g, '.*')
  const body = matchPath ? `(?:.*/)?${withStar}` : withStar
  return new RegExp(`^${body}$`, 'i')
}

/** The documented rule: a pattern containing ':' matches the whole address; otherwise
 *  it matches the URI path at any depth (ignore case, dotfiles not hidden). */
export function addressMatchesPattern(pattern, address) {
  if (pattern.includes(':')) return globToRegExp(pattern, { matchPath: false }).test(address)
  let pathPart = address
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)(.*)$/i.exec(address)
  if (m) pathPart = m[2].replace(/[?#].*$/, '')
  return globToRegExp(pattern, { matchPath: true }).test(pathPart)
}

/** The 'file' resource scope: session | absolute (from the documented grammar). */
export function fileAddressScope(address) {
  const m = /^dsh-resource:\/\/file\/([^/]+)\//.exec(address)
  if (!m) return null
  return m[1] === 'session' || m[1] === 'absolute' ? m[1] : null
}

/**
 * The shipped builtin text preview's registration, modeled exactly as the installed
 * dsh-client-ui-sidebar-documentpreview text type: fallback band, the same glob, and
 * canOpen = (a session-scope file address). Register it first, like the product does.
 */
export function builtinTextType() {
  return {
    id: 'dsh-client-ui-sidebar-documentpreview/text',
    kind: 'dsh-resource://file',
    patterns: ['dsh-resource://file/**'],
    priority: 'fallback',
    canOpen: (address) => fileAddressScope(address) === 'session',
    title: (address) => String(address).split('/').pop() ?? address,
  }
}

/** A model of the tab-type registry: band, then matched-pattern length, then order. */
export function makeTabRegistry() {
  const entries = []
  const registry = {
    entries: () => entries.map((e) => e.def),
    register(definition) {
      if (!definition || typeof definition.id !== 'string' || definition.id === '') {
        throw new Error('tab registration rejected: id is required')
      }
      if (entries.some((e) => e.def.id === definition.id)) {
        throw new Error(`tab registration rejected: id already registered: ${definition.id}`)
      }
      if (typeof definition.title !== 'function') {
        throw new Error(`tab registration rejected: '${definition.id}' has no title(address)`)
      }
      const entry = { def: definition, band: definition.priority ?? 'extension', order: entries.length }
      entries.push(entry)
      return () => {
        const i = entries.indexOf(entry)
        if (i >= 0) entries.splice(i, 1)
      }
    },
    candidates(address) {
      return entries
        .filter((e) => (e.def.patterns ?? []).some((p) => addressMatchesPattern(p, address)))
        .filter((e) => (typeof e.def.canOpen === 'function' ? e.def.canOpen(address) : true))
        .map((e) => ({ e, len: Math.max(0, ...(e.def.patterns ?? []).map((p) => p.length)) }))
        .sort((a, b) => (BAND_ORDER[a.e.band] ?? 9) - (BAND_ORDER[b.e.band] ?? 9) || b.len - a.len || a.e.order - b.e.order)
        .map((x) => x.e.def)
    },
    claim(address) {
      const c = this.candidates(address)
      if (c.length === 0) throw new Error(`no tab type will open this address: ${address}`)
      return { kind: c[0].kind, contentId: address }
    },
  }
  return registry
}

// ---------------------------------------------------------------------------
// Fake client context + slot seat capture
// ---------------------------------------------------------------------------

/**
 * @param {{registry: object, sidebarRight?: object}} opts
 */
export function makeFakeCtx({ registry, sidebarRight = null } = {}) {
  const slots = []
  const effects = []
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ byId: {} }) } },
    workspaces: {},
    slots: {
      inject(name, factory) {
        const dispose = factory()
        return typeof dispose === 'function' ? dispose : () => {}
      },
      register(def, Component) {
        const record = { name: def?.name, def, Component }
        slots.push(record)
        return () => {
          const i = slots.indexOf(record)
          if (i >= 0) slots.splice(i, 1)
        }
      },
    },
    effect(fn) {
      const dispose = fn()
      effects.push(dispose)
      return dispose
    },
    get(name) {
      if (name === 'sidebarRightTabs') return registry
      if (name === 'sidebarRight') return sidebarRight
      return undefined
    },
  }
  return { ctx, slots, effects }
}

/** The fake right column: records every command the plugin issues. */
export function makeSidebarRightSpy({ expanded = true, activeTab = undefined } = {}) {
  const calls = []
  return {
    calls,
    openResource(address, options) { calls.push(['openResource', address, options]) },
    close(tabId) { calls.push(['close', tabId]) },
    active() { return activeTab },
    isExpanded() { return expanded },
    toggleExpanded() { calls.push(['toggleExpanded']); return undefined },
    setActive(tab) { activeTab = tab },
    setExpanded(v) { expanded = v },
  }
}

/** Find the body registration for one key in the captured slot registrations. */
export function findBodyRegistration(slots, key) {
  return slots.find((s) => s.name === 'sidebar.right.pane.tab' && s.def?.key === key) ?? null
}

/**
 * Render a captured body registration the way the slot framework does: the entry's
 * inject.hooks compartment arrives as props named use<Name>.
 * @param {{def: object, Component: Function}} registration
 * @param {object} tabInfo - what the platform's tab-info hook returns.
 */
export function renderBody(registration, tabInfo) {
  const hooks = registration.def?.inject?.hooks ?? {}
  const props = {}
  for (const [name, factory] of Object.entries(hooks)) {
    const prop = `use${name[0].toUpperCase()}${name.slice(1)}`
    props[prop] = typeof factory === 'function' ? factory({}, () => tabInfo) : () => tabInfo
  }
  return renderComponent(registration.Component, props)
}

/** A tab info record shaped like the platform's (address, params, revision, close). */
export function makeTabInfo({ id = 'tab-1', address, params, revision = 1, onClose } = {}) {
  return {
    sidebar: { expanded: true, fullscreen: false },
    panel: { id: 'pane-1' },
    tab: {
      id,
      contentId: address,
      kind: 'sandbar-workbench.file-bridge',
      visible: true,
      navigation: { address, params, revision },
      signal: new AbortController().signal,
      actions: { close: () => { if (onClose) onClose(); }, openResource: () => {}, openTab: () => {} },
    },
  }
}

// ---------------------------------------------------------------------------
// The middle-column request store: the plugin's documented cross-evaluation anchor
// ---------------------------------------------------------------------------

/**
 * Locate the middle-column request store the plugin publishes on globalThis.
 * The plan declares a versioned symbol anchor (Symbol.for('sandbar.workbench.fileOpen.v1')),
 * the same shape dismissal state already uses. Discovery is prefix-based so a version
 * bump does not silently pass: the anchor name itself is named on failure.
 */
export function findFileOpenStore() {
  const found = []
  for (const sym of Object.getOwnPropertySymbols(globalThis)) {
    const desc = typeof sym.description === 'string' ? sym.description : ''
    if (!desc.startsWith('sandbar.workbench.fileOpen')) continue
    const value = globalThis[sym]
    const api = fileOpenApiOf(value)
    found.push({ symbol: sym, description: desc, value, api })
  }
  return found.length > 0 ? found[0] : null
}

function fileOpenApiOf(value) {
  if (!value || typeof value !== 'object') return null
  const candidates = [value, value.api, value.current, value.store]
  for (const c of candidates) {
    if (c && typeof c === 'object' && typeof c.readFileOpenRequest === 'function') return c
  }
  return null
}

export const FILE_OPEN_REQUIRED_API = ['requestFileOpen', 'readFileOpenRequest', 'subscribeFileOpen', 'closeFileOpen']
