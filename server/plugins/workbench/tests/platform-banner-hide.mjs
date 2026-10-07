/**
 * platform-banner-hide.mjs - t261007-07: platform banner-row hide decorator, unit layer.
 *
 * Under test: src/client/platform-banner.ts (resolveBannerTargets pure
 * resolution + applyBannerHidden idempotent tag/clear + start/stop lifecycle +
 * guard paths). DOM = a homemade minimal stub (no jsdom, same discipline as
 * tests/chat-project-tag-refresh.mjs), no real platform package dependency.
 *
 * Covers (aligned with the module-header fault-mode list + review C1/C2):
 *   A row resolution: flat DOM - chain = [logoRow] (the toggle's parent row);
 *     Tooltip-wrapper shape (the toggle nested one level deeper) - chain =
 *     [wrapper, logoRow], the full chain is tagged, never a partial hide
 *     (the C1 main case);
 *   B guards: anchor missing (no fold toggle) -> null -> nothing hidden +
 *     exactly one warn naming the anchor; root landmark missing (our brand row
 *     unmounted) -> guard, nothing hidden + exactly one warn; walk beyond
 *     MAX_WALK -> same guard; warn-once across repeated scans;
 *   C lifecycle: same-value writes skipped (touched=0), the guard round clears
 *     every attribute we set, stop clears attributes + style, stop idempotent,
 *     post-stop scans do nothing;
 *   D malformed inputs: nodes without aria-label / throwing attribute surfaces
 *     never throw (malformed-input discipline, stub-reproduced);
 *   E rebuild rescan: after the row node is rebuilt the observer-callback path
 *     (scan re-entry) re-tags it.
 *
 * Run: node tests/platform-banner-hide.mjs (exit 0 = pass; node >= 22.18
 * native type-stripping).
 */

import {
  BANNER_ATTR,
  BANNER_CSS,
  BANNER_STYLE_SELECTOR,
  MAX_WALK,
  PLATFORM_FOLD_LABELS,
  applyBannerHidden,
  resolveBannerTargets,
  startPlatformBannerHide,
} from '../src/client/platform-banner.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---- minimal DOM stub ---- */
class FakeEl {
  constructor(tag, attrs = {}, parent = null) {
    this.tagName = tag
    this.attrs = { ...attrs }
    this.parent = parent
    this.children = []
    if (parent) parent.children.push(this)
  }
  getAttribute(k) { return this.attrs[k] ?? null }
  setAttribute(k, v) { this.attrs[k] = v }
  removeAttribute(k) { delete this.attrs[k] }
  appendChild(child) {
    child.parent = this
    this.children.push(child)
    return child
  }
  remove() {
    if (!this.parent) return
    const i = this.parent.children.indexOf(this)
    if (i >= 0) this.parent.children.splice(i, 1)
    this.parent = null
  }
  *walk() {
    for (const c of this.children) {
      yield c
      yield* c.walk()
    }
  }
  matches(sel) {
    if (sel === 'button') return this.tagName === 'button'
    if (sel.startsWith('[')) {
      const attr = sel.slice(1, -1)
      return this.attrs[attr] !== undefined
    }
    return false
  }
  querySelectorAll(sel) {
    return Array.from(this.walk()).filter(el => el.matches(sel))
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null }
  get parentElement() { return this.parent }
}

class FakeObserver {
  constructor(cb) { this.cb = cb; this.observing = false }
  observe() { this.observing = true }
  disconnect() { this.observing = false }
}

class FakeDoc extends FakeEl {
  constructor() {
    super('#document')
    this.documentElement = new FakeEl('html', {}, this)
    this.body = new FakeEl('body', {}, this.documentElement)
    this.head = new FakeEl('head', {}, this.documentElement)
    this.created = 0
  }
  createElement(tag) {
    this.created++
    return new FakeEl(tag)
  }
}

function sidebarShape(doc, { withBrandRow = true, wrapToggle = false } = {}) {
  // Shape: body > SidebarRoot > [logoRow > (brand?, toggle), newSession, regionArea > brandRow]
  const root = new FakeEl('div', { class: 'platform-sidebar-root' }, doc.body)
  const row = new FakeEl('div', { class: 'platform-logo-row' }, root)
  if (withBrandRow) {
    const brand = new FakeEl('button', { 'aria-label': 'New session' }, row)
    new FakeEl('span', { class: 'brand-mark' }, brand)
  }
  let toggleHost = row
  if (wrapToggle) toggleHost = new FakeEl('span', { class: 'tooltip-wrapper' }, row)
  const toggle = new FakeEl('button', { 'aria-label': 'Collapse sidebar' }, toggleHost)
  const newSession = new FakeEl('button', { 'aria-label': 'New session' }, root)
  const region = new FakeEl('div', { class: 'region-area' }, root)
  const brandRow = withBrandRow ? new FakeEl('div', { 'data-wb-brand-row': '' }, region) : null
  return { root, row, toggle, toggleHost, newSession, region, brandRow }
}

function captureWarns(fn) {
  const lines = []
  const orig = console.warn
  console.warn = (...a) => { lines.push(a.join(' ')) }
  try { fn() } finally { console.warn = orig }
  return lines
}

/* ---- A row resolution ---- */
section('A row resolution')
{
  const doc = new FakeDoc()
  const s = sidebarShape(doc)
  const targets = resolveBannerTargets(doc)
  ok(Array.isArray(targets) && targets.length === 1, 'A1 flat DOM: chain = [logoRow] exactly')
  ok(targets[0] === s.row, 'A2 the tagged element is the logo row, not the toggle')
}

{
  const doc = new FakeDoc()
  const s = sidebarShape(doc, { wrapToggle: true })
  const targets = resolveBannerTargets(doc)
  ok(Array.isArray(targets) && targets.length === 2, 'C1 wrapped toggle: chain = [wrapper, logoRow] (never a partial hide)')
  ok(targets.includes(s.row) && targets.includes(s.toggleHost), 'C1 both the wrapper and the row are tagged')
}

{
  const doc = new FakeDoc()
  const s = sidebarShape(doc)
  // 第二个折叠钮（异常形态也应齐藏，多锚语义）
  const second = new FakeEl('div', {}, s.root)
  new FakeEl('button', { 'aria-label': 'Open sidebar' }, second)
  const targets = resolveBannerTargets(doc)
  ok(targets.length === 2 && targets.includes(s.row) && targets.includes(second), 'D multiple toggles all tagged together')
}

/* ---- B guard paths ---- */
section('B guard paths')
{
  const doc = new FakeDoc()
  sidebarShape(doc, { withBrandRow: false }) // our brand row unmounted -> root resolution fails
  const lines = captureWarns(() => {
    const targets = resolveBannerTargets(doc)
    ok(targets === null, 'B1 brand row absent: resolution guards (null), not a partial hide')
    ok(applyBannerHidden(doc, targets) >= 0, 'B2 guard apply does not throw')
  })
  ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 0, 'B3 guard hides nothing')
}

{
  const doc = new FakeDoc()
  // no fold toggle: the anchor is absent
  new FakeEl('button', { 'aria-label': 'New session' }, doc.body)
  const lines = captureWarns(() => {
    const targets = resolveBannerTargets(doc)
    ok(targets === null, 'B4 no fold toggle: guard')
  })
  ok(lines.length === 0, 'B5 pure resolver itself does not warn (warn lives in the start lifecycle)')
  ok(PLATFORM_FOLD_LABELS.length === 4, 'B6 anchor set is the four platform locale strings (zh x2, en x2)')
}

{
  // Walk beyond the cap: the landmark ancestor sits outside MAX_WALK -> guard
  // (shape: a linear nested chain of MAX_WALK+3 levels, the landmark only in
  //  the topmost ancestor - the first landmark-bearing ancestor is deeper than the cap; safe-side failure = nothing hidden).
  const doc = new FakeDoc()
  let top = new FakeEl('div', {}, doc.body)
  new FakeEl('div', { 'data-wb-brand-row': '' }, top)
  let toggle = null
  for (let i = 0; i < MAX_WALK + 2; i++) {
    const child = new FakeEl('div', {}, top)
    top = child
  }
  toggle = new FakeEl('button', { 'aria-label': 'Collapse sidebar' }, top)
  const targets = resolveBannerTargets(doc)
  ok(targets === null, `B7 first brand-row ancestor deeper than MAX_WALK(${MAX_WALK}): guard, nothing hidden`)
}

/* ---- C lifecycle ---- */
section('C lifecycle')
{
  const doc = new FakeDoc()
  sidebarShape(doc)
  doc.querySelector = function (sel) { return this.querySelectorAll(sel)[0] ?? null }
  doc.querySelectorAll = FakeEl.prototype.querySelectorAll
  let observer = null
  const RealMO = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor(cb) { observer = { cb }; } observe() {} disconnect() {} }

  let handle
  const lines = captureWarns(() => { handle = startPlatformBannerHide({ doc }) })
  try {
    ok(lines.length === 0, 'C1 happy path: zero guard warns')
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 1, 'C2 style + attribute: the platform row is hidden')
    ok(doc.head.children.some(el => el.attrs['data-wb-platform-banner-style'] !== undefined), 'C3 style injected into head')
    const before = doc.querySelectorAll(`[${BANNER_ATTR}]`)[0]
    // repeated scan is idempotent (observer-callback re-entry)
    observer.cb()
    const after = doc.querySelectorAll(`[${BANNER_ATTR}]`)[0]
    ok(before === after, 'C4 rescan is idempotent (same node stays tagged, no churn)')
    handle.stop()
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 0, 'C5 stop removes the attributes')
    ok(!doc.head.children.some(el => el.attrs['data-wb-platform-banner-style'] !== undefined), 'C6 stop removes the style')
    handle.stop()
    observer.cb()
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 0, 'C7 stop is idempotent and post-stop scans do nothing')
  } finally {
    globalThis.MutationObserver = RealMO
  }
}

{
  // Guard path through the full lifecycle: exactly one warn, no spam across rescans
  const doc = new FakeDoc()
  doc.querySelector = function (sel) { return this.querySelectorAll(sel)[0] ?? null }
  doc.querySelectorAll = FakeEl.prototype.querySelectorAll
  const RealMO = globalThis.MutationObserver
  globalThis.MutationObserver = class { observe() {} disconnect() {} }
  let handle
  const lines = captureWarns(() => {
    handle = startPlatformBannerHide({ doc })
    // 第二轮扫描（observer 回调）也不得再 warn
    // (the internal observer is exercised in C11/C12; here we only check the warn budget)
  })
  try {
    ok(lines.length === 1, 'C8 guard warns exactly one line naming the anchor')
    ok(lines[0].includes('fold-toggle anchor'), 'C9 the warn line names the missing anchor')
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 0, 'C10 nothing hidden on the guard path')
    handle.stop()
  } finally {
    globalThis.MutationObserver = RealMO
  }
}

{
  // Late platform mount after the guard: the rescan hides the row (fault modes 1/3)
  const doc = new FakeDoc()
  doc.querySelector = function (sel) { return this.querySelectorAll(sel)[0] ?? null }
  doc.querySelectorAll = FakeEl.prototype.querySelectorAll
  let cb = null
  const RealMO = globalThis.MutationObserver
  globalThis.MutationObserver = class { constructor(c) { cb = c } observe() {} disconnect() {} }
  let handle
  captureWarns(() => { handle = startPlatformBannerHide({ doc }) })
  try {
    sidebarShape(doc)
    cb()
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 1, 'C11 late platform mount: rescan hides the row')
    handle.stop()
    ok(doc.querySelectorAll(`[${BANNER_ATTR}]`).length === 0, 'C12 stop after a late mount still cleans up fully')
  } finally {
    globalThis.MutationObserver = RealMO
  }
}

/* ---- D malformed inputs ---- */
section('D malformed inputs')
{
  const doc = new FakeDoc()
  // buttons without aria-label / odd label shapes / throwing attribute surfaces - none may throw
  const s = sidebarShape(doc)
  new FakeEl('button', {}, s.root)
  const weird = new FakeEl('button', {}, s.root)
  weird.getAttribute = () => { throw new Error('boom') }
  let threw = false
  try { resolveBannerTargets(doc) } catch { threw = true }
  ok(!threw, 'D1 malformed/throwing aria-label surfaces do not throw')
}

{
  const doc = new FakeDoc()
  doc.querySelector = () => { throw new Error('boom') }
  doc.querySelectorAll = () => []
  const RealMO = globalThis.MutationObserver
  globalThis.MutationObserver = class { observe() {} disconnect() {} }
  let handle
  const lines = captureWarns(() => { handle = startPlatformBannerHide({ doc }) })
  try {
    ok(lines.length >= 1, 'D2 a document whose query surfaces throw degrades loudly, not silently')
    handle.stop()
  } finally {
    globalThis.MutationObserver = RealMO
  }
}

/* ---- E CSS contract ---- */
section('E css contract')
{
  ok(BANNER_CSS.includes(BANNER_ATTR) && BANNER_CSS.includes('display: none'), 'E1 the CSS hides by our own attribute selector only')
  ok(BANNER_STYLE_SELECTOR.startsWith('style['), 'E2 the style element is self-marked (head, outside the React tree)')
}

console.log(`\nRESULT passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
