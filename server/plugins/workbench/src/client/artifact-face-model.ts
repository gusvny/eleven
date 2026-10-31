/**
 * artifact-face-model.ts — the console's artifact inventory and frame (epic
 * artifact-face, slice 2, ticket t261030-35).
 *
 * One reader for the declared artifact list. This module is pure: no IO, no DOM,
 * no node built-ins. The host half (`src/host/artifact-face.ts`) imports it to
 * resolve a row for the byte route, and the console panel imports it to draw the
 * frame. Two copies of these rules would be two readers of one rule.
 *
 * Data source (verified against the engine on `main`):
 *   - the engine normalizes a stage's declared list into descriptors
 *     (`{id,title,kind,kind_known,source,repo,stage,note,open,shape,optional,legacy,round}`)
 *     and writes them per receipt as `results[stage].artifact_descriptors`
 *     (+ `_shape` / `_dropped`), plus `handoffs[].artifact_descriptors`;
 *   - `server/tools/ticket.py::_v2_query` carries `results` into `ticket show`
 *     but does NOT carry the snapshot's flat top-level `artifact_descriptors`.
 *     The model therefore prefers that key when it appears (forward compatible)
 *     and otherwise reads the per-receipt lists. It never re-runs the engine's
 *     aggregation: only what a receipt declared is listed, and a row's round is
 *     the receipt's own `gen` when the descriptor carries no round.
 *
 * The canonical list comes from the HANDOFF history (the engine's own rule,
 * `shared.snapshot_artifact_descriptors`): one entry per round, a declaring handoff
 * trusted (its legacy paths not mirrored), a handoff that declared nothing contributing
 * its `artifacts` paths as guessed descriptors. Reading only the latest receipt lost
 * two things on a live ticket (walkthrough 1): the legacy paths of every stage whose
 * receipt carried the engine's empty list with shape `absent`, and the declarations of
 * an earlier round of a reworked stage. The per-receipt path therefore stays only as
 * the fallback for data with no handoff history, and there it obeys the receipt's
 * `artifact_descriptors_shape`: a non-empty list is trusted; empty/absent/malformed
 * falls back to `deliverables` (the same fallback the canonical rule gives), with the
 * malformed shape named as well.
 *
 * Two rules complete the canonical read (walkthrough 1, A2/A3):
 *   - A stage whose handoff history yields no rows (a mechanical stage such as
 *     `ui_evidence`, which writes a receipt and no handoff, or an entry with no paths) is
 *     read from its receipt, shape rule included. A stage the history already produced
 *     rows for is never also read from its receipt: one stage, one source, no twins.
 *   - Rows are ordered by stage order (the template's), then by the order the source
 *     declared them. The history is chronological, so the raw handoff order interleaves
 *     stages when a reworked stage runs again after the next stage started; the frame
 *     keeps each stage in one block (plan D4/A2).
 *
 * Frame ownership (epic ruling 3): a project view may never decide whether an
 * artifact is listed, in which order, or what the machine verdict is. In this
 * slice no view channel exists yet; the guard is structural: the frame takes
 * only the host payload and the gate receipts, and descriptor keys that could
 * shrink or reorder the list (`hidden`, `visible`, `order`, `view`, `render`)
 * are ignored and named as refused.
 */

import { buildChecksDetail } from './lane-map-model.ts'
import { artifactKindLabel, stageDisplayLabel } from './ui-labels.ts'

/** Re-exported so a caller (and the battery) reads the frame's kind vocabulary here. */
export { artifactKindLabel }

/** Descriptor fields the engine owns. Values are used verbatim (D2a). */
export interface ArtifactDescriptor {
  id: string
  title: string
  kind: string
  kindKnown: boolean
  source: string
  repo: string
  stage: string
  note: string
  open: string
  shape: string
  optional: boolean
  legacy: boolean
  round: number | null
}

/** Why a row's bytes cannot be used. Every state is named on the face. */
export type ArtifactRowState =
  | 'ok'
  | 'missing'
  | 'not_a_file'
  | 'unreadable'
  | 'outside_root'
  | 'repo_root_unknown'
  | 'too_large'
  | 'not_utf8'
  | 'external'
  | 'id_not_servable'

/** One inventory row. `key` is `<stage>/<id>` — the engine enforces no id uniqueness,
 *  and the same artifact legitimately appears once per round.
 *  `rowKey` is the LISTING identity (`<key>@r<round>#<n>`), used for the stats map and the
 *  React key so two rounds of one artifact never collide. */
export interface ArtifactRow extends ArtifactDescriptor {
  key: string
  rowKey: string
  /** The byte route cannot pick a single source for `key` (declared twice with different
   *  sources in the newest round). */
  ambiguous: boolean
  /** The id can address the byte route (charset + a unique newest-round source). */
  servable: boolean
  /** Why the byte route will refuse this row (empty when it will serve it). */
  byteRefusal: string
  /** Per-row refusals: refused descriptor keys, non-addressable id, ambiguous key. */
  refusals: string[]
}

/** Host-side metadata for one row (size, mtime, resolved state). */
export interface ArtifactStat {
  state: ArtifactRowState
  sizeBytes?: number
  mtimeMs?: number
  /** Plain reason for a non-ok state. Empty for `ok`. */
  reason?: string
}

export interface ArtifactViewRow {
  /** The byte address (`<stage>/<id>`). */
  key: string
  /** The listing identity (`<key>@r<round>#<n>`): unique even across rounds. */
  rowKey: string
  id: string
  stage: string
  title: string
  kindLabel: string
  kindKnown: boolean
  sourceLabel: string
  repoLabel: string
  stageLabel: string
  /** The declared round, and its display text. */
  round: number | null
  roundText: string
  sizeText: string
  timeText: string
  note: string
  openHint: string
  optionalText: string
  legacyText: string
  state: ArtifactRowState
  stateText: string
  /** 'degrade' = metadata-only card (unknown kind, or bytes not usable). */
  card: 'row' | 'degrade'
  /** Byte link when the row is servable, else null and `bytesRefusal` says why. */
  bytesHref: string | null
  bytesRefusal: string
  /** Per-row refusals the derivation named (refused display keys, ambiguous key, id). */
  refusals: string[]
}

export interface ArtifactFrameVerdict {
  text: string
  /** null = nothing was written; never fabricate green. */
  green: boolean | null
  /** Which receipt field the verdict came from, or 'none'. */
  source: string
  /** The run header carries data its own verdict contradicts (shown verbatim). */
  disagreement: boolean
}

export interface ArtifactFrame {
  title: string
  countText: string
  listSourceText: string
  rows: ArtifactViewRow[]
  refusals: string[]
  emptyText: string
  verdict: ArtifactFrameVerdict
  qcText: string
}

/** Display keys a project could try to use to shrink or reorder the frame. */
export const FRAME_OWNED_KEYS = ['hidden', 'visible', 'order', 'view', 'render'] as const

/** The id charset the byte route accepts (one path segment after percent-decoding). */
const ARTIFACT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,120}$/

/** Suffix table for the pre-slice-1 compat path (no descriptor list on the receipt).
 *  It mirrors the engine's guess table on purpose and says so on the face. */
const KIND_BY_SUFFIX: Record<string, string> = {
  '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.webp': 'image',
  '.gif': 'image', '.svg': 'image', '.bmp': 'image',
  '.md': 'text', '.txt': 'text', '.rst': 'text',
  '.json': 'structure', '.yaml': 'structure', '.yml': 'structure',
  '.toml': 'structure', '.csv': 'structure',
  '.patch': 'diff', '.diff': 'diff',
}

/** The console's built-in kinds (epic ruling). The engine's list is the truth source. */
export const ARTIFACT_KINDS = ['image', 'text', 'structure', 'diff', 'ledger', 'external'] as const

function asString(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

function basename(p: string): string {
  const s = p.replace(/\\/g, '/').replace(/\/+$/, '')
  const i = s.lastIndexOf('/')
  return i >= 0 ? s.slice(i + 1) : s
}

function suffixOf(p: string): string {
  const name = basename(p)
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i).toLowerCase() : ''
}

/** Stable id from a path: the engine's rule, re-stated for the legacy path only. */
export function legacyIdFromPath(path: unknown): string {
  const raw = String(path ?? '').replace(/\\/g, '/').trim().toLowerCase()
  let out = ''
  for (const ch of raw) {
    if (/[a-z0-9]/.test(ch)) out += ch
    else if (out !== '' && !out.endsWith('-')) out += '-'
  }
  return out.replace(/^-+|-+$/g, '')
}

/** Kind guess from a path suffix; unknown → `external` (the degrade card). */
export function legacyKindFromPath(path: unknown): string {
  return KIND_BY_SUFFIX[suffixOf(String(path ?? ''))] ?? 'external'
}

/** Positive integer or null (a round is 1-based; 0 and negatives are not rounds). */
function positiveInt(v: unknown): number | null {
  return typeof v === 'number' && Number.isSafeInteger(v) && v > 0 ? v : null
}

/** `<stage>/<id>`, the row key. */
export function artifactRowKey(stage: unknown, id: unknown): string {
  return `${asString(stage)}/${asString(id)}`
}

/** Can this id address the byte route at all? (charset only; ambiguity is per row.) */
export function artifactIdAddressable(id: unknown): boolean {
  const s = asString(id)
  if (s === '' || s === '.' || s === '..') return false
  if (s.includes('/') || s.includes('\\') || s.includes('%')) return false
  return ARTIFACT_ID_RE.test(s)
}

/** Read one descriptor object into the model's field names. Declared values win. */
export function readDescriptor(raw: unknown, fallbackStage: string, fallbackRound: number | null): {
  descriptor: ArtifactDescriptor
  refusals: string[]
} | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const o = raw as Record<string, unknown>
  const source = asString(o.source)
  if (source.trim() === '') return null
  const refusals: string[] = []
  for (const k of FRAME_OWNED_KEYS) {
    if (Object.prototype.hasOwnProperty.call(o, k)) {
      refusals.push(`descriptor ${asString(o.id) || basename(source)}: '${k}' is owned by the frame and was ignored`)
    }
  }
  const declaredKind = asString(o.kind)
  const kind = declaredKind.trim() !== '' ? declaredKind : legacyKindFromPath(source)
  const known = typeof o.kind_known === 'boolean' ? o.kind_known : ARTIFACT_KINDS.includes(kind as never)
  const title = asString(o.title).trim() !== '' ? asString(o.title) : basename(source)
  const id = asString(o.id).trim() !== '' ? asString(o.id) : legacyIdFromPath(source)
  const stage = asString(o.stage).trim() !== '' ? asString(o.stage) : fallbackStage
  return {
    descriptor: {
      id,
      title,
      kind,
      kindKnown: known,
      source,
      repo: asString(o.repo),
      stage,
      note: asString(o.note),
      open: asString(o.open),
      shape: asString(o.shape),
      optional: o.optional === true,
      legacy: o.legacy === true,
      round: positiveInt(o.round) ?? fallbackRound,
    },
    refusals,
  }
}

/** One legacy descriptor from a bare path (pre-slice-1 receipt). */
function legacyDescriptor(path: string, stage: string, round: number | null): ArtifactDescriptor {
  return {
    id: legacyIdFromPath(path),
    title: basename(path),
    kind: legacyKindFromPath(path),
    kindKnown: true,
    source: path,
    repo: '',
    stage,
    note: '',
    open: '',
    shape: '',
    optional: false,
    legacy: true,
    round,
  }
}

export interface DeriveResult {
  rows: ArtifactRow[]
  refusals: string[]
  /** 'aggregate' = the snapshot's flat list; 'handoffs' = the handoff history (the
   *  engine's canonical rule); 'handoffs+receipts' = that history plus the receipts of
   *  the stages the history never names (a mechanical stage such as `ui_evidence`
   *  writes a receipt and no handoff); 'receipts' = per-stage receipts only (data with
   *  no handoff history at all). */
  listSource: 'aggregate' | 'handoffs' | 'handoffs+receipts' | 'receipts'
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null
}

function stageSeq(detail: Record<string, unknown>, stageOrder: string[] | undefined): string[] {
  const results = asRecord(detail.results) ?? {}
  const keys = Object.keys(results)
  const out: string[] = []
  for (const s of stageOrder ?? []) {
    if (keys.includes(s) && !out.includes(s)) out.push(s)
  }
  for (const s of keys) if (!out.includes(s)) out.push(s)
  return out
}

/**
 * The round of one handoff entry, mirroring the engine's `shared._artifact_round`:
 * the entry's own `gen` when it is a positive integer; otherwise the stage's current
 * counter (`detail.gens`) labels it only when the stage has exactly ONE handoff entry
 * (one counter cannot label several entries) — else unknown (null), never a guess.
 */
function handoffRound(
  entry: Record<string, unknown>,
  stage: string,
  rounds: Record<string, unknown>,
  counts: Record<string, number>,
): number | null {
  const gen = positiveInt(entry.gen)
  if (gen !== null) return gen
  if ((counts[stage] ?? 0) === 1) {
    const cur = positiveInt(rounds[stage])
    if (cur !== null) return cur
  }
  return null
}

/** The lookup result the byte route acts on. ONE rule, used by the host route and by the
 *  per-row flags, so a row never offers a link the route refuses (or the reverse). */
export type ByteLookup =
  | { ok: true; row: ArtifactRow }
  | { ok: false; code: 'not_found' | 'ambiguous' | 'refused'; reason: string }

/**
 * Pick the row the byte route serves for `<stage>/<id>`.
 *
 * The canonical list carries one entry per round, so the same key can appear several
 * times: the NEWEST round wins. Entries of the newest round that disagree on the source
 * are a genuine ambiguity (refused by name, never the first match). Identical entries
 * (the same declaration recorded twice by the engine) are harmless.
 */
export function selectArtifactRowForBytes(rows: ArtifactRow[], stage: string, id: string): ByteLookup {
  const matches = rows.filter(r => r.stage === stage && r.id === id)
  if (matches.length === 0) {
    return {
      ok: false,
      code: 'not_found',
      reason: `No artifact '${id}' is declared in stage '${stage || '(unnamed)'}'`,
    }
  }
  if (!artifactIdAddressable(id)) {
    return {
      ok: false,
      code: 'refused',
      reason: `Artifact id '${id}' is not addressable in the byte route; the row is still listed`,
    }
  }
  const newest = matches.reduce((m, r) => Math.max(m, r.round ?? 0), 0)
  const top = matches.filter(r => (r.round ?? 0) === newest)
  const sources = new Set(top.map(r => r.source))
  if (sources.size > 1) {
    return {
      ok: false,
      code: 'ambiguous',
      reason: `Artifact '${id}' is declared ${sources.size} times with different sources in stage '${stage}'`
        + (newest > 0 ? ` (round ${newest})` : '') + '; refusing instead of guessing',
    }
  }
  return { ok: true, row: top[0] }
}

/**
 * The frame's row order (plan A2/D4): stage order first, then the order the source
 * declared the rows. The sort is stable, so a stage's own rows never swap. A stage the
 * caller did not name keeps its first-appearance order, after the named stages, and an
 * empty or absent `stageOrder` leaves the source order alone.
 */
function orderRows(rows: ArtifactRow[], stageOrder?: string[]): ArtifactRow[] {
  if (stageOrder === undefined || stageOrder.length === 0) return rows
  const rank = new Map<string, number>()
  for (const s of stageOrder) if (!rank.has(s)) rank.set(s, rank.size)
  const firstSeen = new Map<string, number>()
  for (let i = 0; i < rows.length; i++) {
    if (!firstSeen.has(rows[i].stage)) firstSeen.set(rows[i].stage, i)
  }
  const unknownBase = rank.size
  const rankOf = (stage: string): number => {
    const named = rank.get(stage)
    if (named !== undefined) return named
    return unknownBase + (firstSeen.get(stage) ?? 0)
  }
  return rows
    .map((row, i) => ({ row, i, rank: rankOf(row.stage) }))
    .sort((a, b) => (a.rank - b.rank) || (a.i - b.i))
    .map(x => x.row)
}

/**
 * Build the canonical row list from the ticket detail snapshot.
 *
 * Order of sources (one reader, mirroring the engine):
 *   1. the snapshot's flat `artifact_descriptors` when it carries one (forward compatible;
 *      `ticket show` does not carry it today — plan R2);
 *   2. the HANDOFF history — the engine's canonical rule (`shared.snapshot_artifact_descriptors`):
 *      a handoff that declares descriptors is trusted and its legacy paths are NOT mirrored;
 *      a handoff that declares nothing contributes its `artifacts` paths as guessed descriptors;
 *      every entry keeps its own round. This is why an earlier round's declarations stay
 *      visible after a rework, and why a stage that declared nothing still lists what it
 *      produced (the live-ticket defect the walkthrough found in the receipt-only reading).
 *      A stage the history never names is read from its receipt (step 3's rule), because a
 *      mechanical stage records no handoff;
 *   3. the per-receipt lists, for shapes that carry no handoff history (tests, old data).
 *      `artifact_descriptors_shape` decides: a non-empty list is trusted; anything else
 *      (`absent`, `malformed`, or an empty list) falls back to that receipt's `deliverables`,
 *      with a named refusal for the malformed shape — the same fallback the canonical rule
 *      gives a handoff without descriptors.
 *
 * The returned rows are in stage order then declaration order, whatever the source order.
 *
 * Never throws on malformed input: every refusal is named, and a stage that yields nothing
 * contributes nothing (the empty face says so, it is not blank).
 */
export function deriveArtifactRows(detailRaw: unknown, stageOrder?: string[]): DeriveResult {
  const detail = asRecord(detailRaw) ?? {}
  const rows: ArtifactRow[] = []
  const refusals: string[] = []

  const finish = (list: ArtifactRow[], listSource: DeriveResult['listSource']): DeriveResult => {
    const seq = new Map<string, number>()
    for (const r of list) {
      const n = (seq.get(r.key) ?? 0) + 1
      seq.set(r.key, n)
      r.rowKey = `${r.key}@${r.round === null ? '?' : 'r' + r.round}#${n}`
    }
    for (const r of list) {
      const lookup = selectArtifactRowForBytes(list, r.stage, r.id)
      r.ambiguous = lookup.ok === false && lookup.code === 'ambiguous'
      // The link is offered ONLY on the row the byte route actually serves. The address
      // carries `<stage>/<id>` with no round, so an older round of a re-declared artifact
      // would otherwise promise its own bytes and serve the newest round's file
      // (walkthrough 2, A8). Rows that share the served round AND the served source are
      // identical records, so they keep the link (nothing can be confused).
      const servesThisRow = lookup.ok
        && lookup.row.source === r.source
        && (lookup.row.round ?? 0) === (r.round ?? 0)
      r.servable = servesThisRow
      r.byteRefusal = lookup.ok
        ? (servesThisRow
          ? ''
          : `round ${lookup.row.round ?? 0} is what the byte route serves for this artifact; this row is round ${r.round ?? 0}`)
        : lookup.reason
      if (r.ambiguous) r.refusals.push(lookup.ok === false ? lookup.reason : '')
      else if (!r.servable && !artifactIdAddressable(r.id)) {
        r.refusals.push(`artifact id '${r.id}' is not addressable in the byte route; the row is still listed`)
      } else if (!r.servable && lookup.ok) {
        // The lookup served another round: the row names the round it does NOT serve.
        r.refusals.push(r.byteRefusal)
      }
      r.refusals = r.refusals.filter(x => x !== '')
    }
    return { rows: list, refusals, listSource }
  }

  const pushRead = (
    item: unknown, stage: string, round: number | null, label: string,
  ): boolean => {
    const read = readDescriptor(item, stage, round)
    if (read === null) {
      refusals.push(`${label}: declared entry is not an object with a non-blank source - refused`)
      return false
    }
    rows.push({
      ...read.descriptor,
      key: artifactRowKey(read.descriptor.stage, read.descriptor.id),
      rowKey: '',
      ambiguous: false,
      servable: true,
      byteRefusal: '',
      refusals: read.refusals,
    })
    return true
  }

  const pushLegacy = (path: unknown, stage: string, round: number | null, label: string): boolean => {
    if (typeof path !== 'string' || path.trim() === '') {
      refusals.push(`${label}: path entry is not a non-blank string - refused`)
      return false
    }
    const d = legacyDescriptor(path, stage, round)
    rows.push({
      ...d,
      key: artifactRowKey(d.stage, d.id),
      rowKey: '',
      ambiguous: false,
      servable: true,
      byteRefusal: '',
      refusals: [],
    })
    return true
  }

  /** Read one stage receipt. Returns the number of rows it added. The receipt's
   *  `artifact_descriptors_shape` decides the list: a non-empty list is trusted;
   *  an empty list, `absent`, or `malformed` falls back to `deliverables` (the
   *  canonical rule), and a malformed declaration is named as well. */
  const readReceipt = (stage: string, receipt: Record<string, unknown>): number => {
    let added = 0
    const round = positiveInt(receipt.gen)
    const declared = receipt.artifact_descriptors
    if (Array.isArray(declared) && declared.length > 0) {
      for (let i = 0; i < declared.length; i++) {
        if (pushRead(declared[i], stage, round, `[${stage}] ${i}`)) added += 1
      }
    } else {
      if (declared !== undefined && declared !== null && !Array.isArray(declared)) {
        refusals.push(`[${stage}] artifact_descriptors is not a list - the declared list was refused`)
      } else if (receipt.artifact_descriptors_shape === 'malformed') {
        refusals.push(`[${stage}] the declared list was refused as a whole (shape malformed)`)
      }
      const deliverables = receipt.deliverables
      if (Array.isArray(deliverables)) {
        for (let i = 0; i < deliverables.length; i++) {
          if (pushLegacy(deliverables[i], stage, round, `[${stage}] ${i}`)) added += 1
        }
      }
    }
    const dropped = receipt.artifact_descriptors_dropped
    if (Array.isArray(dropped)) {
      for (const d of dropped) if (typeof d === 'string' && d.trim() !== '') refusals.push(`[${stage}] ${d}`)
    }
    return added
  }

  /* ---- 1. the snapshot's flat list (forward compatible) ---- */
  const aggregate = detail.artifact_descriptors
  if (Array.isArray(aggregate) && aggregate.length > 0) {
    const roundHint = positiveInt(detail.gen)
    for (let i = 0; i < aggregate.length; i++) pushRead(aggregate[i], '', roundHint, `${i}`)
    const dropped = detail.artifact_descriptors_dropped
    if (Array.isArray(dropped)) {
      for (const d of dropped) if (typeof d === 'string' && d.trim() !== '') refusals.push(d)
    }
    return finish(orderRows(rows, stageOrder), 'aggregate')
  }

  /* ---- 2. the handoff history (the engine's canonical rule) ---- */
  const handoffs = Array.isArray(detail.handoffs)
    ? detail.handoffs.filter(h => h !== null && typeof h === 'object' && !Array.isArray(h)) as Record<string, unknown>[]
    : []
  if (handoffs.length > 0) {
    const gens = asRecord(detail.gens) ?? {}
    const counts: Record<string, number> = {}
    for (const h of handoffs) {
      const st = asString(h.stage)
      counts[st] = (counts[st] ?? 0) + 1
    }
    /** Read one handoff entry (never throws; every refusal is named). */
    const readHandoff = (h: Record<string, unknown>, stage: string, round: number | null): void => {
      const declared = h.artifact_descriptors
      if (Array.isArray(declared) && declared.length > 0) {
        for (let i = 0; i < declared.length; i++) pushRead(declared[i], stage, round, `[${stage}] ${i}`)
        return // a declaring handoff's legacy paths are NOT mirrored
      }
      if (declared !== undefined && declared !== null && !Array.isArray(declared)) {
        refusals.push(`[${stage}] artifact_descriptors is not a list - refused`)
        return
      }
      const paths = h.artifacts
      if (paths === undefined || paths === null) return
      if (!Array.isArray(paths)) {
        refusals.push(`[${stage}] artifacts is not a list - no path descriptors read`)
        return
      }
      for (let i = 0; i < paths.length; i++) pushLegacy(paths[i], stage, round, `[${stage}] ${i}`)
    }
    // Rows each stage's handoff entries contributed (0 = the history says nothing usable
    // for that stage, so its receipt is the only record).
    const contributed = new Map<string, number>()
    for (const h of handoffs) {
      const stage = asString(h.stage)
      const before = rows.length
      readHandoff(h, stage, handoffRound(h, stage, gens, counts))
      contributed.set(stage, (contributed.get(stage) ?? 0) + (rows.length - before))
    }
    // The history yields nothing for a mechanical stage such as `ui_evidence` (it writes
    // a receipt and no handoff, so the receipt is the only record of what it produced),
    // and nothing for a stage whose entry carried no paths at all. Those receipts are read
    // here. A stage the history already produced rows for is never also read from its
    // receipt: one stage, one source, no twins.
    let supplemented = false
    for (const stage of stageSeq(detail, stageOrder)) {
      const receipt = asRecord((asRecord(detail.results) ?? {})[stage])
      if (receipt === null) continue
      if ((contributed.get(stage) ?? 0) > 0) {
        // Receipt-level refusals stay named (the engine's per-receipt channel).
        const dropped = receipt.artifact_descriptors_dropped
        if (Array.isArray(dropped)) {
          for (const d of dropped) if (typeof d === 'string' && d.trim() !== '') refusals.push(`[${stage}] ${d}`)
        }
        continue
      }
      if (readReceipt(stage, receipt) > 0) supplemented = true
    }
    return finish(orderRows(rows, stageOrder), supplemented ? 'handoffs+receipts' : 'handoffs')
  }

  /* ---- 3. per-receipt fallback (no handoff history) ---- */
  for (const stage of stageSeq(detail, stageOrder)) {
    const receipt = asRecord((asRecord(detail.results) ?? {})[stage])
    if (receipt === null) continue
    readReceipt(stage, receipt)
  }
  return finish(orderRows(rows, stageOrder), 'receipts')
}

/* ---------------------------------------------------------------- frame view */

/** Inline byte caps per kind (D6). */
export const ARTIFACT_INLINE_MAX_BYTES = 1_048_576
export const ARTIFACT_IMAGE_MAX_BYTES = 8_388_608

export function artifactInlineCap(kind: unknown): number {
  return kind === 'image' ? ARTIFACT_IMAGE_MAX_BYTES : ARTIFACT_INLINE_MAX_BYTES
}

/** Human size. Deterministic, no locale formatting. */
export function formatBytes(n: unknown): string {
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** `YYYY-MM-DD HH:MM` in UTC — the console shows one clock, and tests can pin it. */
export function formatArtifactTime(ms: unknown): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms <= 0) return ''
  const d = new Date(ms)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`
}

/** The named sentence for each non-ok state. English, short (host order 260925). */
export function artifactStateText(state: ArtifactRowState, reason?: string): string {
  const r = (reason ?? '').trim()
  switch (state) {
    case 'ok': return ''
    case 'missing': return `File not found at the declared source${r === '' ? '' : ` (${r})`}`
    case 'not_a_file': return `The declared source is not a regular file${r === '' ? '' : ` (${r})`}`
    case 'unreadable': return `The file cannot be read${r === '' ? '' : ` (${r})`}`
    case 'outside_root': return `The resolved path is outside the ticket workspace; the console does not serve it${r === '' ? '' : ` (${r})`}`
    case 'repo_root_unknown': return `Declared in another repository, and this ticket has no workspace for it${r === '' ? '' : ` (${r})`}`
    case 'too_large': return `Too large to open in the page${r === '' ? '' : ` (${r})`}`
    case 'not_utf8': return `The text is not valid UTF-8, so the console does not show it${r === '' ? '' : ` (${r})`}`
    case 'external': return `Outside the project, so the console shows metadata only${r === '' ? '' : ` (${r})`}`
    case 'id_not_servable': return r === '' ? 'This row cannot be fetched by id' : r
    default: return r
  }
}

/**
 * The frame view. `stats` is the host's metadata map keyed by row key.
 *
 * A row is never removed and never reordered: the order is the derivation order
 * (stage order, then declaration order), whatever the stats say.
 */
export function buildArtifactFaceView(
  derived: DeriveResult,
  stats?: Record<string, ArtifactStat> | null,
  detailRaw?: unknown,
): ArtifactFrame {
  const statOf = (key: string): ArtifactStat => {
    const s = stats ? stats[key] : undefined
    if (s !== undefined && s !== null && typeof s.state === 'string') return s
    return { state: 'unreadable', reason: 'no metadata was read for this row' }
  }
  const rows: ArtifactViewRow[] = derived.rows.map((r) => {
    const st = statOf(r.rowKey)
    const state: ArtifactRowState = st.state
    const stateText = artifactStateText(state, st.reason)
    const unknownKind = !r.kindKnown || !ARTIFACT_KINDS.includes(r.kind as never)
    const servable = r.servable && state === 'ok'
    const bytesRefusal = servable ? '' : (r.byteRefusal !== '' ? r.byteRefusal : stateText)
    return {
      key: r.key,
      rowKey: r.rowKey,
      id: r.id,
      stage: r.stage,
      title: r.title,
      kindLabel: unknownKind ? `${artifactKindLabel(r.kind)} (not recognized)` : artifactKindLabel(r.kind),
      kindKnown: !unknownKind,
      sourceLabel: r.source,
      repoLabel: r.repo === '' ? '' : `repo ${r.repo}`,
      stageLabel: stageDisplayLabel(r.stage, r.stage),
      round: r.round,
      roundText: r.round === null ? 'round unknown' : `round ${r.round}`,
      sizeText: typeof st.sizeBytes === 'number' ? formatBytes(st.sizeBytes) : '',
      timeText: formatArtifactTime(st.mtimeMs),
      note: r.note,
      openHint: r.open,
      optionalText: r.optional ? 'optional' : '',
      legacyText: r.legacy ? 'legacy path (kind guessed)' : '',
      state,
      stateText,
      card: unknownKind || state !== 'ok' ? 'degrade' : 'row',
      bytesHref: servable ? `bytes` : null,
      bytesRefusal,
      refusals: r.refusals,
    }
  })

  const checks = buildChecksDetail(detailRaw)
  const newest = checks.length > 0 ? checks[0] : undefined
  const verdict: ArtifactFrameVerdict = newest === undefined
    ? { text: 'Machine verdict: no gate run yet', green: null, source: 'none', disagreement: false }
    : {
        text: `Machine verdict: ${newest.label || newest.stage} ${newest.green ? 'green' : 'red'}`
          + (newest.disagreement ? ' (the receipt verdict and its rows disagree; both shown verbatim)' : ''),
        green: newest.green,
        source: newest.verdictSource,
        disagreement: newest.disagreement,
      }

  return {
    title: 'Artifacts',
    countText: `${rows.length} declared`,
    listSourceText: derived.listSource === 'aggregate'
      ? 'read from the snapshot artifact list'
      : (derived.listSource === 'handoffs'
        ? 'read from the handoff history (one entry per round)'
        : (derived.listSource === 'handoffs+receipts'
          ? 'read from the handoff history, plus the stage receipts it does not name'
          : 'read from the stage receipts')),
    rows,
    refusals: derived.refusals,
    emptyText: 'This ticket declares no artifacts.',
    verdict,
    qcText: 'QC red/green: no data face on this ticket yet.',
  }
}
