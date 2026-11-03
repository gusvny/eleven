#!/usr/bin/env node
// sc_t26110209_takeover_seam.mjs — t261102-09 L2 component-contract case: the chat's
// file tab is CLAIMED and FORWARDED to the middle column.
//
// Intent (grey-box, user-perceivable, anchored on the dsh public contracts the ticket
// names — never on our private structure):
//   T1 the SERVED workbench bundle registers a tab type for dsh-resource://file/** at the
//      EXTENSION band, with a canOpen veto and a title; the takeover is therefore in force
//      in the page the console serves, not only in source.
//   T2 the veto claims text-like files (markdown / plain / data / source / log / csv) and
//      refuses images, PDF and HTML, so the builtin right-column preview keeps those
//      addresses exactly as today (the builtin still wins them).
//   T3 the tab body, rendered by the seat, forwards one middle-column request
//      {sessionId, path, line} through the plugin's documented cross-evaluation anchor,
//      closes its own tab, and never re-opens the right column (openResource is never
//      called — the whole point of option a).
//   T4 the column is collapsed only when it is expanded AND no tab is left; an open chat
//      tab keeps it open, and a collapsed column is never expanded by a hijack.
//   T5 an address that cannot be parsed never throws in the seat: it renders a named
//      banner carrying the address and the tab is NOT closed.
//   T6 a second click on the same file keeps ONE middle request (line/revision updated);
//      a different file replaces it — never two layers.
//   T7 failure containment: a throwing close()/toggleExpanded() cannot undo the forward
//      and cannot crash the render.
//   T8 the takeover is owned by the plugin lifetime: disposing the registration gives the
//      address back to the builtin (no leaked claim).
//
// Why this is L2 and not L3: the property is the routing decision and the seat's command
// sequence — a cross-component contract at the platform seam. No browser, no stage, no
// docker, offline seconds. The browser-only residue (real layout / scroll of the middle
// sheet, a real click in the chat) is named as an uncovered surface in the ticket result.
//
// Tier: contract seam (platform registry + seat commands). Cost: seconds.
// Environment: absent served bundle = ENV_FAIL exit 2; the case needs no browser/stage.

import {
  loadServedWorkbench,
  makeTabRegistry,
  builtinTextType,
  makeFakeCtx,
  makeSidebarRightSpy,
  findBodyRegistration,
  renderBody,
  makeTabInfo,
  findFileOpenStore,
  treeText,
  renderComponent,
  reactSurface,
  h,
  FILE_OPEN_REQUIRED_API,
} from './lib_bundle_harness.mjs'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { makeResults } from './lib_case_results.mjs'

const REPO = process.cwd()
const results = makeResults()

const SESSION = 'it-session-1'
const TEXT_PATH = 'docs/notes.md'
const TEXT_ADDRESS = `dsh-resource://file/session/${SESSION}/${TEXT_PATH}`
const OTHER_TEXT_ADDRESS = `dsh-resource://file/session/${SESSION}/docs/other.ts`
const LINE = 12

const CLAIMED = [
  ['markdown', `dsh-resource://file/session/${SESSION}/a.md`],
  ['markdown long ext', `dsh-resource://file/session/${SESSION}/a.markdown`],
  ['plain text', `dsh-resource://file/session/${SESSION}/a.txt`],
  ['log', `dsh-resource://file/session/${SESSION}/a.log`],
  ['csv', `dsh-resource://file/session/${SESSION}/a.csv`],
  ['json', `dsh-resource://file/session/${SESSION}/a.json`],
  ['yaml', `dsh-resource://file/session/${SESSION}/a.yaml`],
  ['toml', `dsh-resource://file/session/${SESSION}/a.toml`],
  ['source ts', `dsh-resource://file/session/${SESSION}/a.ts`],
  ['source py', `dsh-resource://file/session/${SESSION}/a.py`],
  ['absolute scope text', 'dsh-resource://file/absolute/tmp/fixture/notes.md'],
]
const REFUSED = [
  ['image png', `dsh-resource://file/session/${SESSION}/a.png`],
  ['image jpg', `dsh-resource://file/session/${SESSION}/a.jpg`],
  ['image svg', `dsh-resource://file/session/${SESSION}/a.svg`],
  ['pdf', `dsh-resource://file/session/${SESSION}/a.pdf`],
  ['html', `dsh-resource://file/session/${SESSION}/a.html`],
  ['htm', `dsh-resource://file/session/${SESSION}/a.htm`],
  ['other resource type', 'dsh-resource://other/x.md'],
  ['not an address', 'notes.md'],
  ['empty', ''],
]

// --- H0 harness control ------------------------------------------------------
// The case must be able to reach PASS on a minimal correct takeover, so a red below is
// attributable to the artifact and not to this harness. The control uses the same
// registry model, the same column spy and the same render plumbing as the real legs.
{
  const reg = makeTabRegistry()
  reg.register(builtinTextType())
  const right = makeSidebarRightSpy({ expanded: true })
  reg.register({
    id: 'control/type', kind: 'control', patterns: ['dsh-resource://file/**'], priority: 'extension',
    canOpen: (a) => /\.md$/i.test(a), title: () => 'control',
  })
  results.check(reg.candidates('dsh-resource://file/session/it/docs/a.md')[0]?.id === 'control/type',
    'H0 control: a correct extension-band claim wins a text address')
  results.check(reg.candidates('dsh-resource://file/session/it/docs/a.png')[0]?.id === builtinTextType().id,
    'H0 control: the builtin keeps an image address')
  let closedControl = 0
  const ControlBody = (props) => {
    const { tab } = props.useTabInfo()
    reactSurface.useEffect(() => {
      tab.actions.close()
      if (right.isExpanded() === true && right.active() === undefined) right.toggleExpanded()
    }, [])
    return h('div', null, 'control body')
  }
  const info = makeTabInfo({ address: 'dsh-resource://file/session/it/docs/a.md', onClose: () => { closedControl += 1 } })
  const renderedControl = renderComponent(ControlBody, { useTabInfo: () => info })
  results.check(renderedControl.errors.length === 0 && closedControl === 1 &&
    right.calls.some((c) => c[0] === 'toggleExpanded'),
  'H0 control: the seat run closes the tab and collapses an emptied column',
  `errors=${renderedControl.errors.length} closed=${closedControl} calls=${right.calls.map((c) => c[0]).join(',')}`)
}

const BUNDLE = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
let bundle
if (!existsSync(BUNDLE)) {
  results.env('the served workbench bundle is present (run bash server/plugins/workbench/build-client.sh)', BUNDLE)
  results.summarize()
}
// Boot contract, both React surfaces: the real platform provides a class-component base,
// and a hooks-only surface must also boot the artifact (the slot error boundary picks a
// constructible base). A bundle that only loads on one of them is a named red here.
for (const mode of ['full', 'partial']) {
  try {
    loadServedWorkbench({ repoRoot: REPO, reactSurface: mode })
    results.pass(`the served bundle evaluates on a ${mode} React surface`)
  } catch (e) {
    results.fail(`the served bundle evaluates on a ${mode} React surface`,
      `${String(e?.message ?? e).slice(0, 200)} — the console plugin cannot boot on this surface`)
  }
}
try {
  bundle = loadServedWorkbench({ repoRoot: REPO, reactSurface: 'full' })
} catch (e) {
  // A bundle that exists but cannot be evaluated is a PRODUCT red: the console would fail
  // to load the sidebar plugin (this is the t260916-26 class: the whole column falls back
  // to the dsh default UI). Only an absent artifact is an environment gap.
  results.fail('the served bundle evaluates through the platform module loader',
    `${String(e?.message ?? e).slice(0, 200)} — the shipped artifact is not loadable, so the console plugin cannot boot`)
  results.summarize()
}

// --- platform assembly -------------------------------------------------------
// One plugin evaluation, like the page has. apply(ctx) hands its registrations to the
// registry and the slot seat; every later assertion drives what was handed over.
const registry = makeTabRegistry()
registry.register(builtinTextType()) // the product's builtin, registered first
const holder = { right: makeSidebarRightSpy() }
const columnFacade = {
  openResource: (...a) => holder.right.openResource(...a),
  close: (...a) => holder.right.close(...a),
  active: () => holder.right.active(),
  isExpanded: () => holder.right.isExpanded(),
  toggleExpanded: () => holder.right.toggleExpanded(),
}
const fake = makeFakeCtx({ registry, sidebarRight: columnFacade })
try {
  bundle.apply(fake.ctx)
} catch (e) {
  results.fail('apply(ctx) completes without throwing', String(e?.message ?? e).slice(0, 200))
  results.summarize()
}

const ourType = registry.entries().filter((d) => d.id !== builtinTextType().id)
  .find((d) => (d.patterns ?? []).some((p) => String(p).includes('dsh-resource://file')))
if (!ourType) {
  results.fail('T1 the served bundle registers a file tab type',
    'no registration for dsh-resource://file/** besides the builtin — implement the takeover and rebuild lib/client.js (TDD signal)')
  results.summarize()
}

results.check(registry.candidates(TEXT_ADDRESS)[0]?.id === ourType.id,
  'T1 the takeover outranks the builtin for a text file address',
  `candidates: ${registry.candidates(TEXT_ADDRESS).map((d) => `${d.id}(${d.priority ?? 'extension'})`).join(', ') || '(none)'}`)
results.check(typeof ourType.canOpen === 'function', 'T1 the type declares a canOpen veto')
results.check(typeof ourType.title === 'function', 'T1 the type declares a title(address)')
results.check(typeof ourType.kind === 'string' && ourType.kind !== '', 'T1 the type declares a kind')

// --- T2 claim matrix ---------------------------------------------------------
for (const [label, address] of CLAIMED) {
  const claimed = typeof ourType.canOpen === 'function' ? ourType.canOpen(address) === true : false
  results.check(claimed, `T2 claims ${label}`, `${address} → canOpen !== true`)
  if (claimed) {
    results.check(registry.candidates(address)[0]?.id === ourType.id,
      `T2 the takeover wins ${label} in the registry`,
      `winner: ${registry.candidates(address)[0]?.id ?? '(none)'}`)
  }
}
for (const [label, address] of REFUSED) {
  const refused = typeof ourType.canOpen === 'function' ? ourType.canOpen(address) === false : false
  results.check(refused, `T2 refuses ${label}`, `${address} → canOpen !== false`)
}
for (const [label, address] of REFUSED.slice(0, 6)) {
  const winner = registry.candidates(address)[0]
  results.check(winner?.id === builtinTextType().id,
    `T2 the builtin keeps ${label} exactly as today`,
    `winner: ${winner?.id ?? '(nothing claims it — the column would refuse the click)'}`)
}

// --- T3/T4/T7 the seat: forward, close, collapse ------------------------------
const bodyReg = findBodyRegistration(fake.slots, ourType.id)
if (!bodyReg) {
  results.fail('T3 the type body is registered in the keyed pane-tab seat',
    `no 'sidebar.right.pane.tab' registration with key '${ourType.id}' (the tab would render nothing)`)
} else {
  const mount = ({ expanded = true, activeTab = undefined, address = TEXT_ADDRESS, params = { line: LINE }, closeThrows = false, toggleThrows = false }) => {
    holder.right = makeSidebarRightSpy({ expanded, activeTab })
    if (toggleThrows) holder.right.toggleExpanded = () => { throw new Error('toggleExpanded exploded (injected)') }
    let closed = 0
    const info = makeTabInfo({ address, params, revision: 1, onClose: () => { closed += 1 } })
    if (closeThrows) info.tab.actions.close = () => { throw new Error('close exploded (injected)') }
    const rendered = renderBody(bodyReg, info)
    return { rendered, closed, right: holder.right }
  }

  // T3 main mount (expanded column, the chat tab still open is the real-world case too)
  const main = mount({ expanded: true, activeTab: undefined })
  results.check(main.rendered.errors.length === 0,
    'T3 the body renders without throwing', main.rendered.errors.map((e) => String(e?.message ?? e)).join(' | ').slice(0, 200))
  results.check(main.closed === 1, 'T3 the body closes its own tab', `close calls: ${main.closed}`)
  results.check(main.right.calls.every((c) => c[0] !== 'openResource'),
    'T3 the hijack never re-opens the right column',
    `commands: ${main.right.calls.map((c) => c[0]).join(', ')}`)

  const store = findFileOpenStore()
  if (!store || !store.api) {
    results.fail('T3 the middle-column request is published at the documented anchor',
      'no globalThis symbol starting with sandbar.workbench.fileOpen exposes readFileOpenRequest — the forward has no reader')
  } else {
    const missing = FILE_OPEN_REQUIRED_API.filter((k) => typeof store.api[k] !== 'function')
    results.check(missing.length === 0,
      'T3 the request store exposes the declared API',
      `missing: ${missing.join(', ')}`)
    const req = readRequest(store.api)
    results.check(req !== null, 'T3 one middle-column request exists after the mount')
    if (req) {
      results.check(req.sessionId === SESSION, 'T3 the request carries the session id', `sessionId=${String(req.sessionId)}`)
      results.check(req.path === TEXT_PATH || String(req.path).endsWith(TEXT_PATH), 'T3 the request carries the file path', `path=${String(req.path)}`)
      results.check(Number(req.line) === LINE, 'T3 the request carries the line', `line=${String(req.line)}`)
      results.check(String(req.address ?? '').includes(TEXT_ADDRESS), 'T3 the request carries the address it came from', `address=${String(req.address)}`)
    }
    // T6 one slot: same address updates, another address replaces
    store.api.requestFileOpen({ sessionId: SESSION, path: TEXT_PATH, line: 20, revision: 2, address: TEXT_ADDRESS })
    const same = readRequest(store.api)
    results.check(Array.isArray(same) ? same.length === 1 : same !== null,
      'T6 a second click on the same file keeps ONE middle request', Array.isArray(same) ? `entries: ${same.length}` : 'single slot expected')
    results.check(same !== null && Number((Array.isArray(same) ? same[0] : same).line) === 20,
      'T6 the second click updates the line', `line=${String(same && (Array.isArray(same) ? same[0] : same).line)}`)
    store.api.requestFileOpen({ sessionId: SESSION, path: 'docs/other.ts', line: 1, revision: 3, address: OTHER_TEXT_ADDRESS })
    const other = readRequest(store.api)
    const entries = Array.isArray(other) ? other : other === null ? [] : [other]
    results.check(entries.length === 1 && String(entries[0]?.address ?? '').includes('other.ts'),
      'T6 a different file replaces the sheet instead of stacking', `entries: ${entries.map((e) => e.address).join(', ')}`)
  }

  // T4 collapse matrix
  const t4a = mount({ expanded: true, activeTab: undefined })
  results.check(t4a.right.calls.some((c) => c[0] === 'toggleExpanded'),
    'T4 an expanded, emptied column is collapsed after the hijack', `commands: ${t4a.right.calls.map((c) => c[0]).join(', ')}`)
  const closeAt = t4a.right.calls.findIndex((c) => c[0] === 'toggleExpanded')
  results.check(t4a.closed === 1 && closeAt >= 0, 'T4 the tab is closed before the collapse')

  const t4b = mount({ expanded: true, activeTab: { id: 'chat-tab' } })
  results.check(!t4b.right.calls.some((c) => c[0] === 'toggleExpanded'),
    'T4 an open chat tab keeps the column open (not collapsed)', `commands: ${t4b.right.calls.map((c) => c[0]).join(', ')}`)

  const t4c = mount({ expanded: false, activeTab: undefined })
  results.check(!t4c.right.calls.some((c) => c[0] === 'toggleExpanded'),
    'T4 a collapsed column is never expanded by a hijack', `commands: ${t4c.right.calls.map((c) => c[0]).join(', ')}`)

  // T5 unparseable address (a restored tab): named banner, tab stays
  const bad = mount({ address: 'not-an-address', params: undefined })
  const badText = treeText(bad.rendered.tree).join(' ')
  results.check(bad.rendered.errors.length === 0, 'T5 a bad address never throws in the seat',
    bad.rendered.errors.map((e) => String(e?.message ?? e)).join(' | ').slice(0, 160))
  results.check(badText.includes('not-an-address'), 'T5 the banner names the address', `rendered: ${badText.slice(0, 160)}`)
  results.check(bad.closed === 0, 'T5 the tab is not closed when the address cannot be parsed', `close calls: ${bad.closed}`)

  // T7 failure containment
  const t7a = mount({ closeThrows: true })
  results.check(t7a.rendered.errors.length === 0, 'T7 a throwing close() does not crash the seat',
    t7a.rendered.errors.map((e) => String(e?.message ?? e)).join(' | ').slice(0, 160))
  const storeAfter = findFileOpenStore()
  results.check(storeAfter?.api ? readRequest(storeAfter.api) !== null : false,
    'T7 the forward survives a throwing close()')
  const t7b = mount({ toggleThrows: true })
  results.check(t7b.rendered.errors.length === 0, 'T7 a throwing collapse() does not crash the seat',
    t7b.rendered.errors.map((e) => String(e?.message ?? e)).join(' | ').slice(0, 160))
}

// --- T8 lifecycle ------------------------------------------------------------
const claimAfterDispose = (() => {
  // The registration is owned by the plugin's effect: dispose every effect the plugin
  // registered, then the address must fall back to the builtin (no leaked claim).
  for (const d of fake.effects) { if (typeof d === 'function') { try { d() } catch { /* idempotent */ } } }
  const winner = registry.candidates(TEXT_ADDRESS)[0]
  return winner
})()
results.check(claimAfterDispose === undefined || claimAfterDispose.id === builtinTextType().id,
  'T8 disposing the plugin returns the address to the builtin (no leaked claim)',
  `winner after dispose: ${claimAfterDispose?.id ?? '(none)'}`)

results.summarize()

function readRequest(api) {
  try {
    const v = api.readFileOpenRequest()
    if (Array.isArray(v)) return v.length === 0 ? null : v
    return v ?? null
  } catch {
    return null
  }
}
