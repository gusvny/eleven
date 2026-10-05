/**
 * project-identity.ts — single-source pure module for the project identity badge
 * (console-ui epic item UI-4, t261005-05). One project = one badge
 * (12 colours x 6 uncommon outlines x 3 structures) + one project colour, and the
 * left column and the panel render the SAME identity for that project.
 *
 * Declared truth (this module implements declared values, invents nothing):
 * - palette / outlines / structures = the settled spec (§2.4) in the 261004 chat
 *   identity design note under notes/discussions/ (filename carries CJK by design);
 * - geometry is ported verbatim from mock `261004-concurrency-limit-mock.html` v11
 *   (`glyphPath` / `shapeSVG`, including the ring's centre-scaled hole and half's
 *   right-side clip).
 *
 * Two declared deviations from the mock (borrowed-implementation tradeoffs, auditable):
 * (a) the mock builds mask/clip ids with `Math.random()` — this module derives a
 *     deterministic id from identity+size (SSR/snapshot safe; equal ids always carry
 *     byte-equal content, so duplicate references in one document have no visual drift);
 * (b) the mock hardcodes per-project `PROJ_SHAPE`/`PROJ_COLOR` maps — this module
 *     replaces them with the deterministic rule "two hash streams pick the preferred
 *     triple + dedupe over the known project set" (ticket requirement: an undeclared
 *     project still gets a stable, distinct identity, unchanged across restarts).
 *     The `projects.yaml` `color`/`shape` override is an approved upgrade path whose
 *     parser lives in server/project-registry.ts (outside this ticket's write set) —
 *     recorded as debt for a follow-up ticket, not implemented here.
 *
 * Tradeoffs vs project-color.ts:
 * - the hash REUSES fnv1a (FNV-1a + murmur3 finalizer; plain FNV lacked low-bit
 *   avalanche and collided the first real pair suyou/sandbar — see that module's old
 *   header; this module does not regress to a plain FNV stream);
 * - the palette upgrades to the declared 12 colours (PROJECT_PALETTE_12);
 *   project-color.ts re-exports from here — single-source rule: the palette is
 *   declared exactly once, in this file.
 *
 * Malformed-input fallback follows the existing discipline: a non-key gets the grey
 * pentagon-solid identity, never a throw.
 */

/**
 * This module is self-contained (zero module imports): project-color.ts re-exports
 * this module's palette/hash/fallback colour, and the panel page embeds these same
 * functions via String(fn) — one source, no drift, no import cycle.
 */

/** Palette: 12 colours (verbatim from mock v11 `PALETTE12`; hues about 30 degrees
 *  apart, s about 0.72 / l about 0.66). Declared values win: their measured minimum
 *  pairwise hue-ring gap is 19.2 degrees, so the old 10-colour palette's >=20 degree
 *  criterion is re-anchored (see smoke/project-color.mjs) rather than bending the
 *  declared values to keep a derived number. */
export const PROJECT_PALETTE_12: readonly string[] = [
  '#e76a6a', '#e7936a', '#e7c36a', '#c6e76a', '#8ae76a', '#6ae79c',
  '#6ae7d4', '#6aabe7', '#7f6ae7', '#b56ae7', '#e76ad0', '#e76a92',
]

/** Fallback colour for malformed input / unattributable projects (neutral grey;
 *  true source moved here, project-color.ts re-exports it). */
export const FALLBACK_COLOR = '#9ca3af'

/** Outline set (uncommon shapes; deliberately avoids dots/squares/triangles that
 *  read as controls — design note §2.4). */
export const IDENTITY_OUTLINES = ['pentagon', 'hexagon', 'octagon', 'shield', 'sparkle', 'tag'] as const
export type IdentityOutline = (typeof IDENTITY_OUTLINES)[number]

/** Structure set: solid / ring (centre-scaled hole) / half (55% base + right half at 100%). */
export const IDENTITY_STRUCTURES = ['solid', 'ring', 'half'] as const
export type IdentityStructure = (typeof IDENTITY_STRUCTURES)[number]

/** The three channels of one badge. */
export interface ProjectIdentity {
  color: string
  outline: IdentityOutline
  structure: IdentityStructure
}

/** Fallback identity for malformed keys (neutral grey + plainest shape = "unset"). */
export const FALLBACK_IDENTITY: ProjectIdentity = {
  color: FALLBACK_COLOR,
  outline: 'pentagon',
  structure: 'solid',
}

/** Salt for the second hash stream (independent of the first; changing it reshuffles
 *  every identity — think before changing). */
const STREAM2_SALT = '\u0000wb-identity'

/** Key length cap (longer is treated as malformed; project keys are short ids). */
const KEY_MAX_LEN = 64

/** FNV-1a 32bit hash + murmur3 finalizer (moved here from project-color.ts in
 *  t261005-05: plain FNV lacked low-bit avalanche and the first real registry pair
 *  suyou/sandbar landed in one slot — the finalizer separates them). Known vectors
 *  are locked by smoke/project-color.mjs; do not hand-tune. */
export function fnv1a(input: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b)
  h ^= h >>> 13
  h = Math.imul(h, 0xc2b2ae35)
  h ^= h >>> 16
  return h >>> 0
}

/** Project key validity face (loose whitelist: non-empty, <=64, no control chars —
 *  the UI renders this text, so it stays display-safe). */
export function isProjectKeyLike(key: unknown): key is string {
  return typeof key === 'string' && key.length > 0 && key.length <= KEY_MAX_LEN
    && !/[\u0000-\u001f\u007f]/.test(key)
}

/** Preferred triple for one key, no dedupe (set dedupe lives in projectIdentity).
 *  Exported only as the panel page's String(fn) embed seam, not a standalone API. */
export function baseIdentity(key: string): ProjectIdentity {
  const h1 = fnv1a(key)
  const h2 = fnv1a(key + STREAM2_SALT)
  return {
    color: PROJECT_PALETTE_12[h1 % PROJECT_PALETTE_12.length],
    outline: IDENTITY_OUTLINES[h2 % IDENTITY_OUTLINES.length],
    structure: IDENTITY_STRUCTURES[(h1 >>> 9) % IDENTITY_STRUCTURES.length],
  }
}

/** Dedupe key of a triple (a collision needs all three channels equal).
 *  Export reason same as baseIdentity (embed seam). */
export function identityId(id: ProjectIdentity): string {
  return `${id.color}|${id.outline}|${id.structure}`
}

/**
 * Project key -> identity. Same key, same value, always (pure function; the
 * "unchanged across restarts" acceptance object).
 *
 * @param key project key (malformed -> FALLBACK_IDENTITY, never throws).
 * @param knownKeys known project set (optional). When passed, dedupe runs in sorted
 *        order, first come first served: a later colliding project walks the ring
 *        (colour+1, outline+1, structure+1) to the first free slot — the deterministic
 *        implementation of design-note §2.4 "preferred pair + dedupe over the known
 *        project set". The two consumers (sidebar registry / panel project root) each
 *        pass their own set; the extreme divergence that different sets could cause is
 *        watched by the collision assertions in tests/project-identity.mjs.
 */
export function projectIdentity(key: unknown, knownKeys?: readonly unknown[]): ProjectIdentity {
  if (!isProjectKeyLike(key)) return FALLBACK_IDENTITY
  const k = key as string
  const base = baseIdentity(k)
  if (!Array.isArray(knownKeys) || knownKeys.length === 0) return base
  const valid = Array.from(new Set(knownKeys)).filter(isProjectKeyLike).sort() as string[]
  if (!valid.includes(k)) return base
  // First come first served in sorted order: replay the walk key by key — each
  // earlier key occupies its FINAL identity (possibly already offset by its own
  // dedupe), and the current key keeps its base unless that final set contains it.
  const taken = new Set<string>()
  let result = base
  for (const v of valid) {
    const cand = baseIdentity(v)
    result = taken.has(identityId(cand)) ? walkOffset(cand, taken) : cand
    taken.add(identityId(result))
    if (v === k) break
  }
  return result
}

/** Ring walk from a triple to the first slot not in `taken` (colour+1, outline+1,
 *  structure+1 per step; the 216 space cannot fill for a <=41-char key set).
 *  Export reason same as baseIdentity (panel page embed seam). */
export function walkOffset(base: ProjectIdentity, taken: Set<string>): ProjectIdentity {
  const ci = PROJECT_PALETTE_12.indexOf(base.color)
  const oi = IDENTITY_OUTLINES.indexOf(base.outline)
  const si = IDENTITY_STRUCTURES.indexOf(base.structure)
  for (let n = 1; n < PROJECT_PALETTE_12.length * IDENTITY_OUTLINES.length; n++) {
    const cand: ProjectIdentity = {
      color: PROJECT_PALETTE_12[(ci + n) % PROJECT_PALETTE_12.length],
      outline: IDENTITY_OUTLINES[(oi + n) % IDENTITY_OUTLINES.length],
      structure: IDENTITY_STRUCTURES[(si + n) % IDENTITY_STRUCTURES.length],
    }
    if (!taken.has(identityId(cand))) return cand
  }
  return base // defensive: unreachable for real key sets
}

/**
 * SVG path for an outline (mock `glyphPath` ported verbatim; size = viewBox edge).
 * An unknown outline name falls back to pentagon (malformed-enum fallback, no throw).
 */
export function identityOutlinePath(name: string, size: number): string {
  const S = size
  const c = S / 2
  const R = S * 0.47
  const R2 = S * 0.3
  const polyPath = (n: number, rot: number): string => {
    const pts: string[] = []
    for (let k = 0; k < n; k++) {
      const a = rot + k * 2 * Math.PI / n
      pts.push(`${(c + R * Math.cos(a)).toFixed(2)},${(c + R * Math.sin(a)).toFixed(2)}`)
    }
    return `M${pts.join(' L')} Z`
  }
  if (name === 'hexagon') return polyPath(6, -Math.PI / 2 + Math.PI / 6)
  if (name === 'octagon') return polyPath(8, -Math.PI / 2 + Math.PI / 8)
  if (name === 'shield') {
    const t = S * 0.08, b = S * 0.94
    return `M${S * 0.14} ${t} H${S * 0.86} V${S * 0.52} Q${S * 0.86} ${b} ${c} ${b} Q${S * 0.14} ${b} ${S * 0.14} ${S * 0.52} Z`
  }
  if (name === 'sparkle') {
    const p: string[] = []
    for (let k = 0; k < 8; k++) {
      const r = k % 2 === 0 ? R : R2
      const a = -Math.PI / 2 + k * Math.PI / 4
      p.push(`${(c + r * Math.cos(a)).toFixed(2)},${(c + r * Math.sin(a)).toFixed(2)}`)
    }
    return `M${p.join(' L')} Z`
  }
  if (name === 'tag') {
    return `M${S * 0.12} ${S * 0.12} H${S * 0.66} L${S * 0.88} ${S * 0.34} V${S * 0.88} H${S * 0.12} Z`
  }
  return polyPath(5, -Math.PI / 2 + Math.PI / 5) // pentagon + unknown-name fallback
}

/**
 * Badge SVG text (mock `shapeSVG` port). ring = centre-scaled 0.46 hole (mask);
 * half = same colour at 55% base + right half at 100% (clipPath). Design note §2.4:
 * thin-pointed shapes like sparkle degrade to solid below 12px (no hole that size
 * cannot hold).
 *
 * Deterministic id (deviation (a) in the header): derived from identity+size by
 * default. Two badges with the same identity and size in one document share an id —
 * their content is byte-equal, so either definition renders identically.
 */
export function identityBadgeSvg(identity: ProjectIdentity, size: number, uid?: string): string {
  const structure = identity.structure === 'ring' && size < 12 && identity.outline === 'sparkle'
    ? 'solid' : identity.structure
  const d = identityOutlinePath(identity.outline, size)
  const id = uid ?? `wbid${fnv1a(`${identity.color}|${identity.outline}|${structure}|${size}`).toString(36)}`
  const wrap = (inner: string): string =>
    `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="flex:0 0 auto;display:block" aria-hidden="true">${inner}</svg>`
  if (structure === 'ring') {
    const c = size / 2
    return wrap(
      `<mask id="${id}"><rect x="0" y="0" width="${size}" height="${size}" fill="#fff"/>` +
      `<g transform="translate(${c},${c}) scale(0.46) translate(${-c},${-c})"><path d="${d}" fill="#000"/></g></mask>` +
      `<path d="${d}" fill="${identity.color}" mask="url(#${id})"/>`,
    )
  }
  if (structure === 'half') {
    const c = size / 2
    return wrap(
      `<defs><clipPath id="${id}"><path d="${d}"/></clipPath></defs>` +
      `<path d="${d}" fill="${identity.color}" fill-opacity="0.55"/>` +
      `<rect x="${c}" y="0" width="${c}" height="${size}" fill="${identity.color}" clip-path="url(#${id})"/>`,
    )
  }
  return wrap(`<path d="${d}" fill="${identity.color}"/>`)
}

/**
 * Convenience entry: key -> badge SVG (malformed key -> fallback badge). Consumer
 * size rules (design note §2.4): sidebar project row 14, session row 11, panel chip 13.
 */
export function projectBadgeSvg(key: unknown, size: number, knownKeys?: readonly unknown[]): string {
  return identityBadgeSvg(projectIdentity(key, knownKeys), size)
}
