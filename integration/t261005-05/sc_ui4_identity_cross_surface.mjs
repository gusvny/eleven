#!/usr/bin/env node
/**
 * UI-4 scenario 2 — the SAME identity appears on both surfaces (t261005-05,
 * grey-box L3, offline seconds, zero docker / Temporal / browser / network,
 * never touches 3099).
 *
 * User-visible contract under test (host order 261005, epic console-ui item
 * UI-4): the SAME identity appears in the left column (workbench sidebar) and
 * inside the executor panel for that project.
 *
 * Legs:
 *   A  single source: the panel page draws its identity from the workbench
 *      shared module, not from a drifted copy — a palette edit lands on both
 *      faces in one batch.
 *   B  cross-surface equality: the identity the workbench module computes for
 *      a key uses only values the panel face also carries (declared palette /
 *      outlines / structures), so both faces can only ever show the same
 *      badge vocabulary; the panel's embedded colours are exactly the module's
 *      exported palette (or the module itself, no third list).
 *   C  fallback: a missing/malformed project key resolves to the neutral
 *      fallback identity — the panel never crashes or invents an identity.
 *   D  colour is never the only channel: the key text renders next to the
 *      badge on the panel face (the design note's three-channel rule).
 *
 * Intent split: module-internal space bounds / determinism belong to
 * sc_ui4_identity_space_contract; per-render DOM truth tables belong to the
 * developer L1 battery; this entry pins only the two-surface same-identity
 * promise — the ticket's headline contract.
 *
 * Pre-implement = FAIL naming the missing seam (TDD-phase red expected); must
 * be green at arbitrate/merge.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const REPO = new URL('../..', import.meta.url).pathname.replace(/\/$/, '')
let failed = 0
let totalChecks = 0
function check(name, cond, detail = '') {
  totalChecks++
  if (!cond) failed++
  console.log((cond ? 'PASS' : 'FAIL') + ' :: ' + name
    + (cond ? '' : ' :: ' + String(detail).slice(0, 200)))
}

const MOD = REPO + '/server/plugins/workbench/src/shared/project-identity.ts'
const PANEL = REPO + '/server/plugins/executor-panel/src/host/panel-page.ts'

let m = null
try {
  m = await import(MOD)
  check('A0 workbench identity module loads', true)
} catch (e) {
  check('A0 workbench identity module loads', false, String(e))
  console.log('FAIL :: pre-implement: missing ' + MOD + ' — TDD-phase red expected')
  process.exit(1)
}

let panelSrc = ''
try {
  panelSrc = readFileSync(PANEL, 'utf8')
  check('A1 panel page source readable', true)
} catch (e) {
  check('A1 panel page source readable', false, String(e))
  process.exit(1)
}

const PALETTE12 = ['#e76a6a', '#e7936a', '#e7c36a', '#c6e76a', '#8ae76a', '#6ae79c',
  '#6ae7d4', '#6aabe7', '#7f6ae7', '#b56ae7', '#e76ad0', '#e76a92']
const declaredLower = PALETTE12.map(c => c.toLowerCase())
const idFn = m.projectIdentity || m.projectIdentityFor
const palette = m.PROJECT_PALETTE_12 || m.PROJECT_PALETTE
const fallback = m.FALLBACK_COLOR || m.FALLBACK_IDENTITY
check('A0b module exports identity fn, palette and fallback',
  typeof idFn === 'function' && Array.isArray(palette) && fallback !== undefined,
  'exports: ' + Object.keys(m).join(','))

// --- A: single source, not a drifted copy ---
check('A2 panel page references the shared identity module (not a copy)',
  /project-identity/.test(panelSrc),
  'no reference to project-identity in panel-page.ts')

// --- B: the two faces carry the same badge vocabulary ---
// Binding face = the RENDERED page the browser actually receives
// (PANEL_PAGE_HTML), not the TS source: the identity runtime and its constants
// are injected into the page, so the source text alone proves nothing.
const OUTLINES6 = ['pentagon', 'hexagon', 'octagon', 'shield', 'sparkle', 'tag']
const STRUCTURES3 = ['solid', 'ring', 'half']
let pageHtml = ''
try {
  const panel = await import(PANEL)
  pageHtml = panel.PANEL_PAGE_HTML || panel.PANEL_HTML || ''
  check('B0 rendered panel page obtainable', typeof pageHtml === 'string' && pageHtml.length > 0)
} catch (e) {
  check('B0 rendered panel page obtainable', false, String(e))
  process.exit(1)
}
const pageLower = pageHtml.toLowerCase()
const pageHexes = [...pageHtml.matchAll(/#([0-9a-fA-F]{6})/g)].map(x => '#' + x[1].toLowerCase())
const declaredOnPage = [...new Set(pageHexes.filter(c => declaredLower.includes(c)))]
check('B1 rendered page carries the full declared 12-colour palette',
  declaredOnPage.length === 12, 'declared colours found: ' + declaredOnPage.length)
// Scope note: the page's own chrome (backgrounds, inks, links) legitimately
// uses its own colours — the contract is about the BADGE palette, so B2 reads
// the identity runtime's embedded palette array, not the whole page.
check('B2 the badge runtime palette is exactly the declared 12 (no invented badge colour)',
  (() => {
    const i = pageLower.indexOf('identity_runtime')
    if (i < 0) return false
    const m2 = pageLower.slice(i, i + 4000).match(/project_palette_12"\s*:\s*\[([^\]]*)\]/)
    if (!m2) return false
    const cols = [...m2[1].matchAll(/#([0-9a-fA-F]{6})/g)].map(x => '#' + x[1].toLowerCase())
    return JSON.stringify(cols) === JSON.stringify(declaredLower)
  })(),
  'badge runtime palette mismatch')
check('B3 rendered page carries the declared 6 outline names',
  OUTLINES6.every(o => pageHtml.includes('"' + o + '"')),
  'missing some of ' + OUTLINES6.join('/'))
check('B4 rendered page carries the declared 3 structure names',
  STRUCTURES3.every(s => pageHtml.includes('"' + s + '"')),
  'missing some of ' + STRUCTURES3.join('/'))

// Cross-surface: for every declared project key, the workbench identity lands
// inside the vocabulary the panel face also carries — the same badge is the
// only possible render on both sides. Declared set = the registry loader the
// projects API serves (documented seed keys as fallback on an empty home
// registry — the vocabulary agreement is under test, not machine contents).
async function declaredKeys() {
  try {
    const reg = await import(REPO + '/server/project-registry.ts')
    const keys = reg.loadProjects().map(e => e.key).filter(Boolean)
    if (keys.length) return keys
  } catch (e) {
    console.log('NOTE :: registry loader unavailable, seed keys: ' + e)
  }
  return ['sandbar', 'suyou', 'nusuyou']
}
const keys = await declaredKeys()
let eq = true, eqDetail = ''
for (const k of keys) {
  const r = idFn(k)
  if (!declaredLower.includes(String(r.color).toLowerCase())) {
    eq = false; eqDetail = k + ' → colour outside declared palette: ' + r.color; break
  }
}
check('B5 every declared project\'s workbench identity stays inside the '
  + 'panel-carried vocabulary (' + keys.length + ' keys)', eq, eqDetail)

// --- C: fallback for missing/malformed key ---
let fb = true, fbDetail = ''
try {
  const a = idFn(''), b = idFn('z'.repeat(300)), c = idFn(null)
  const same = JSON.stringify([a.color, a.outline, a.structure])
    === JSON.stringify([b.color, b.outline, b.structure])
    && JSON.stringify([a.color, a.outline, a.structure])
      === JSON.stringify([c.color, c.outline, c.structure])
  fb = same
  fbDetail = JSON.stringify([a, b, c])
} catch (e) {
  fb = false; fbDetail = String(e)
}
check('C1 missing/malformed key resolves to ONE neutral fallback identity, no throw',
  fb, fbDetail)

// --- D: colour is never the only channel ---
// The panel chip renders the project key text alongside the badge (existing
// contract: projChip carries state.project as text; the badge is added before
// it, never instead of it).
check('D1 panel chip keeps the project key text (projChip text still assigned)',
  /projChip[\s\S]{0,80}=|textContent\s*=\s*state\.project/.test(panelSrc),
  'projChip text assignment not found in panel-page.ts')
check('D2 workbench sidebar keeps the key text too (title attribute on the row)',
  (() => {
    const src = readFileSync(REPO + '/server/plugins/workbench/src/client/sidebar.tsx',
      'utf8')
    return /title=/.test(src)
  })())

console.log((failed ? 'FAIL' : 'PASS') + ' :: summary '
  + (totalChecks - failed) + '/' + totalChecks + ' checks green')
process.exit(failed ? 1 : 0)
