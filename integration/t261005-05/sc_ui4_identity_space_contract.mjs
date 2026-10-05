#!/usr/bin/env node
/**
 * UI-4 scenario 1 — the declared identity space holds (t261005-05, grey-box L3,
 * offline seconds, zero docker / Temporal / browser / network, never touches 3099).
 *
 * User-visible contract under test (host order 261005, epic console-ui item UI-4):
 * every project gets an identity a person can recognise at a glance — a badge
 * from the DECLARED space (12 colours × 6 uncommon outlines × 3 structures) —
 * and a project with no declaration still gets a stable, distinct identity,
 * deterministically (same project, same badge, across restarts).
 *
 * Legs:
 *   A  the palette is the declared 12 (exact hex values from the design note /
 *      mock v11), outlines are the declared 6 uncommon shapes, structures the
 *      declared 3 — the implementation inherits the declaration, never invents.
 *   B  determinism: the same key yields the identical identity across repeated
 *      calls, and the badge SVG carries no random ingredient (the mock's
 *      Math.random() clip id must not survive the port — restart = same bytes).
 *   C  malformed keys (empty / non-string / overlong / control chars) fall back
 *      to a neutral identity without throwing — a bad key must never take the
 *      page down.
 *   D  distinctness: over the real declared project set AND an undeclared
 *      directory set (what the panel lists), no two projects share the same
 *      full identity (colour + outline + structure) — dedupe is the declared
 *      mechanism, a collision defeats "recognise at a glance".
 *   E  space bounds: every produced identity lands inside 12 × 6 × 3.
 *
 * Intent split: per-function truth tables (hash streams, offset walk) belong to
 * the developer L1 battery on the module; the panel-face constants equality
 * belongs to sc_ui4_identity_cross_surface; this entry pins only the declared
 * space, determinism, malformed-input, and distinctness faces from outside.
 *
 * Pre-implement = FAIL naming the missing module (TDD-phase red expected);
 * must be green at arbitrate/merge.
 */
import assert from 'node:assert/strict'

const REPO = new URL('../..', import.meta.url).pathname.replace(/\/$/, '')

let results = []
function check(name, cond, detail = '') {
  results.push([name, Boolean(cond)])
  console.log((cond ? 'PASS' : 'FAIL') + ' :: ' + name
    + (cond ? '' : ' :: ' + String(detail).slice(0, 200)))
  if (!cond) process.exitCode = 1
}

const MOD = REPO + '/server/plugins/workbench/src/shared/project-identity.ts'

let m = null
try {
  m = await import(MOD)
  check('A0 identity module exists and loads', true)
} catch (e) {
  check('A0 identity module exists and loads', false, String(e))
  console.log('FAIL :: pre-implement: ' + MOD + ' missing — TDD-phase red expected')
  process.exit(1)
}

const PALETTE12 = ['#e76a6a', '#e7936a', '#e7c36a', '#c6e76a', '#8ae76a', '#6ae79c',
  '#6ae7d4', '#6aabe7', '#7f6ae7', '#b56ae7', '#e76ad0', '#e76a92']
const OUTLINES = ['pentagon', 'hexagon', 'octagon', 'shield', 'sparkle', 'tag']
const STRUCTURES = ['solid', 'ring', 'half']

// Resolve exported names leniently but visibly (naming is contract, not detail).
const palette = m.PROJECT_PALETTE_12 || m.PROJECT_PALETTE
const idFn = m.projectIdentity || m.projectIdentityFor
const svgFn = m.identityBadgeSvg || m.identityBadge
check('A0b module exports palette, identity fn and badge svg fn',
  Array.isArray(palette) && typeof idFn === 'function' && typeof svgFn === 'function',
  'exports: ' + Object.keys(m).join(','))

// --- A: declared space ---
check('A1 palette is exactly the declared 12 hex values in order',
  Array.isArray(palette) && palette.length === 12 &&
  JSON.stringify(palette) === JSON.stringify(PALETTE12),
  JSON.stringify(palette))
check('A2 outline vocabulary is the declared 6 uncommon shapes',
  Array.isArray(m.IDENTITY_OUTLINES) &&
  JSON.stringify(m.IDENTITY_OUTLINES) === JSON.stringify(OUTLINES),
  JSON.stringify(m.IDENTITY_OUTLINES))
check('A3 structure vocabulary is the declared 3',
  Array.isArray(m.IDENTITY_STRUCTURES) &&
  JSON.stringify(m.IDENTITY_STRUCTURES) === JSON.stringify(STRUCTURES),
  JSON.stringify(m.IDENTITY_STRUCTURES))
check('A4 declared space multiplies out to 216',
  PALETTE12.length * OUTLINES.length * STRUCTURES.length === 216)

// --- helpers ---
function ident(key, known) {
  const r = idFn(key, known)
  return { color: r.color, outline: r.outline, structure: r.structure }
}
function sameId(a, b) {
  return a.color === b.color && a.outline === b.outline && a.structure === b.structure
}
function inSpace(r) {
  return PALETTE12.includes(r.color) && OUTLINES.includes(r.outline) &&
    STRUCTURES.includes(r.structure)
}

// --- B: determinism ---
const probes = ['sandbar', 'suyou', 'nusuyou', 'console-ui', 'no-such-declared-project',
  'a'.repeat(63), 'dir-with-dashes', 'UPPER', 'digits12345']
let det = true
for (const k of probes) {
  if (!sameId(ident(k), ident(k))) { det = false; break }
}
check('B1 same key twice gives the identical identity (pure, no drift)', det)

let svgDet = true
let svgSample = ''
try {
  const first = svgFn(ident('sandbar'), 14)
  const second = svgFn(ident('sandbar'), 14)
  svgDet = first === second && typeof first === 'string' && first.includes('<svg')
  svgSample = String(first)
} catch (e) {
  svgDet = false
  svgSample = String(e)
}
check('B2 badge SVG is byte-identical across calls (no random ids — restart = same badge)',
  svgDet, svgSample.slice(0, 120))
check('B3 badge SVG carries no Math.random-shaped id',
  svgDet && !/id="g[a-z0-9]{6}"/.test(svgSample) && !svgSample.includes('random'),
  svgSample.slice(0, 160))

// --- C: malformed keys → fallback, never throw ---
// The neutral fallback is deliberately OUTSIDE the 12-colour palette (a grey
// that reads "undefined identity"); it is exported as FALLBACK_IDENTITY.
const fb = m.FALLBACK_IDENTITY
check('C0 the fallback identity is exported', fb !== undefined,
  'exports: ' + Object.keys(m).join(','))
const isFine = (r) => inSpace(r) ||
  (fb && r.color === fb.color && r.outline === fb.outline && r.structure === fb.structure)
const bad = ['', null, undefined, 42, {}, 'x'.repeat(200), 'bad\u0000key', 'tab\tkey']
let mal = true, malDetail = ''
for (const k of bad) {
  try {
    const r = ident(k)
    if (!isFine(r)) { mal = false; malDetail = 'bad result for ' + JSON.stringify(k) + ': ' + JSON.stringify(r); break }
  } catch (e) {
    mal = false; malDetail = 'threw for ' + JSON.stringify(k) + ': ' + e; break
  }
}
check('C1 malformed keys fall back to the neutral fallback identity without throwing',
  mal, malDetail)
check('C2 malformed keys share ONE neutral fallback identity (recognisably undefined)',
  (() => {
    try {
      return sameId(ident(''), ident('y'.repeat(300)))
    } catch { return false }
  })())

// --- D: distinctness over real + undeclared sets ---
// Declared set = the registry the projects API already serves (reader-side
// truth via the same loader, not a hand-copied list). The per-key root lives
// outside the repo (~/.sandbar/projects), so an empty home registry falls
// back to the documented seed keys — the distinctness property is what is
// under test, not this machine's registry contents.
async function declaredKeys() {
  try {
    const reg = await import(REPO + '/server/project-registry.ts')
    const entries = reg.loadProjects()
    const keys = entries.map(e => e.key).filter(Boolean)
    if (keys.length) return keys
  } catch (e) {
    console.log('NOTE :: registry loader unavailable, seed keys: ' + e)
  }
  return ['sandbar', 'suyou', 'nusuyou']
}
function dupCheck(keys, label) {
  const seen = new Map()
  for (const k of keys) {
    const id = JSON.stringify(ident(k, keys))
    if (seen.has(id)) {
      check('D ' + label, false, 'collision: ' + k + ' vs ' + seen.get(id))
      return
    }
    seen.set(id, k)
  }
  check('D ' + label + ' (' + keys.length + ' keys, no full-identity collision)', true)
}
dupCheck(await declaredKeys(), 'declared registry set distinct')
const undeclared = ['ghost-dir', 'another-dir', 'third-dir', 'fourth', 'fifth', 'sixth',
  'seventh', 'eighth']
dupCheck([...await declaredKeys(), ...undeclared], 'declared + undeclared set distinct')

// --- E: space bounds over a broad probe sweep ---
let bounded = true, boundDetail = ''
for (let i = 0; i < 300; i++) {
  const r = ident('probe-' + i)
  if (!inSpace(r)) { bounded = false; boundDetail = 'probe-' + i + ' → ' + JSON.stringify(r); break }
}
check('E1 300 swept keys all land inside the declared 12×6×3 space', bounded, boundDetail)

const failed = results.filter(r => !r[1]).length
console.log((failed ? 'FAIL' : 'PASS') + ' :: summary ' + (results.length - failed)
  + '/' + results.length + ' checks green')
process.exit(failed ? 1 : 0)
