/**
 * artifact-face.ts — host half of the console artifact face (epic artifact-face,
 * slice 2, ticket t261030-35). It answers two questions for the console:
 *
 *   1. what metadata does each declared artifact row have (size, mtime, and the
 *      named state when the bytes cannot be used)?
 *   2. the original bytes of ONE row, addressed by `<stage>/<id>` — never by a
 *      path the client supplied.
 *
 * The row list itself comes from `src/client/artifact-face-model.ts` (one reader:
 * the console panel and this module derive rows through the same function). A
 * second derivation here would let the panel list a row the byte route cannot
 * find, or the reverse.
 *
 * Roots (D5a). A row belongs to the ticket workspace: `workspace.path || worktree`
 * resolved against the project anchor. A row that declares `repo` belongs to
 * `<ticket workspace>/<repo>`, located through the ticket's `repo_worktrees`
 * through `changes.ts::sanitizeRepoWorktrees` (the same guard the diff face uses,
 * so a malformed ticket field has one meaning on both faces: no member root).
 * Every root and every candidate is realpath-checked against the project anchor;
 * an escape is refused, never served.
 *
 * Read-only by construction: the only `node:fs` verbs here are `realpath`, `stat`
 * and `readFile`, and every path closes what it opens (no timers, no listeners,
 * no handles held across an await that can reject). The route layer owns the HTTP
 * method lock and the status codes.
 *
 * Response contract (D6b): the caller gets a content type, a disposition and a
 * filename; text kinds are UTF-8 validated (invalid bytes are refused by name,
 * never served as mojibake), image kinds are served under their own image type
 * EXCEPT SVG, which is forced to a download because an SVG opened as a page runs
 * script on the console origin. `nosniff` and `no-store` are the route's job.
 */

import { readFile, realpath, stat } from 'node:fs/promises'
import { isAbsolute, join, resolve, sep } from 'node:path'
import {
  ARTIFACT_KINDS,
  artifactInlineCap,
  deriveArtifactRows,
  selectArtifactRowForBytes,
  type ArtifactRow,
  type ArtifactRowState,
  type ArtifactStat,
  type DeriveResult,
} from '../client/artifact-face-model.ts'
import { sanitizeRepoWorktrees, type RepoWorktreeEntry } from './changes.ts'

/** Concurrent byte reads the console allows (saturation is a named refusal). */
export const ARTIFACT_BYTES_SLOTS = 4

const TEXT_KINDS = new Set(['text', 'structure', 'diff', 'ledger'])

const IMAGE_TYPE_BY_SUFFIX: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
}

export interface ArtifactByteResult {
  ok: true
  contentType: string
  disposition: 'inline' | 'attachment'
  filename: string
  body: Buffer
  sizeBytes: number
}

export type ArtifactByteFailureCode =
  | 'not_found'
  | 'ambiguous'
  | 'refused'
  | 'too_large'
  | 'not_utf8'
  | 'busy'

export interface ArtifactByteFailure {
  ok: false
  code: ArtifactByteFailureCode
  reason: string
}

export type ArtifactByteAnswer = ArtifactByteResult | ArtifactByteFailure

export interface ArtifactInventory {
  rows: ArtifactRow[]
  stats: Record<string, ArtifactStat>
  refusals: string[]
  listSource: 'aggregate' | 'handoffs' | 'handoffs+receipts' | 'receipts'
  /** Named root facts, so a reader can tell "no workspace" from "no file". */
  roots: { workspaceRoot: string | null; repos: string[]; note: string }
}

/** Active byte reads (module-local counter; one process, no shared state). */
let activeSlots = 0

/**
 * Run `fn` inside one byte-read slot. Saturation answers `busy` immediately: the
 * route never waits silently and never drops the request.
 */
export async function withArtifactSlot<T>(fn: () => Promise<T>): Promise<T | ArtifactByteFailure> {
  if (activeSlots >= ARTIFACT_BYTES_SLOTS) {
    return {
      ok: false,
      code: 'busy',
      reason: `All ${ARTIFACT_BYTES_SLOTS} artifact read slots are in use; try again`,
    }
  }
  activeSlots += 1
  try {
    return await fn()
  } finally {
    activeSlots -= 1
  }
}

/** Test-only visibility of the counter (never a control surface). */
export function activeArtifactSlots(): number {
  return activeSlots
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null
}

function isInside(root: string, candidate: string): boolean {
  return candidate === root || candidate.startsWith(root + sep)
}

/** `workspace.path || worktree`, resolved against the anchor and contained. */
export function ticketWorkspaceRoot(anchorRoot: string, detailRaw: unknown): { root: string | null; note: string } {
  const detail = asRecord(detailRaw) ?? {}
  const wsPath = asRecord(detail.workspace) !== null ? asString((asRecord(detail.workspace) as Record<string, unknown>).path) : ''
  const raw = (wsPath.trim() !== '' ? wsPath : asString(detail.worktree)).trim()
  const anchorAbs = resolve(anchorRoot)
  if (raw === '') return { root: anchorAbs, note: 'main tree (this ticket has no separate workspace)' }
  const abs = resolve(anchorAbs, raw)
  if (!isInside(anchorAbs, abs)) {
    return { root: null, note: `the ticket workspace '${raw}' is outside the project root` }
  }
  return { root: abs, note: '' }
}

/** The member-repo roots this ticket declares (sanitized by the diff face's guard). */
export function ticketRepoRoots(detailRaw: unknown): RepoWorktreeEntry[] | undefined {
  const detail = asRecord(detailRaw) ?? {}
  return sanitizeRepoWorktrees(detail.repo_worktrees)
}

interface ResolvedSource {
  state: ArtifactRowState
  abs?: string
  reason?: string
}

function sourceIsExternal(source: string): boolean {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(source) || source.startsWith('//')
}

/**
 * Resolve one row's declared source to an absolute path inside the ticket
 * workspace. Every refusal carries the name of the check that failed.
 */
async function resolveSource(
  anchorRoot: string,
  workspaceRoot: string | null,
  repoRoots: RepoWorktreeEntry[] | undefined,
  row: ArtifactRow,
): Promise<ResolvedSource> {
  const source = row.source
  if (sourceIsExternal(source)) {
    return { state: 'external', reason: 'the source is a URL' }
  }
  // The declared source is a path (not a URL). Two shapes exist by design (design 3.1):
  // a workspace-relative path, and an absolute path. An ABSOLUTE path is usable only
  // when it stays inside the project anchor (the KI-057 containment rule); otherwise it
  // keeps the `external` reading the design gives "an absolute path outside the project".
  let base: string
  let candidate: string
  if (isAbsolute(source)) {
    base = resolve(anchorRoot)
    candidate = resolve(source)
    if (!isInside(base, candidate)) {
      return { state: 'external', reason: 'the absolute source is outside the project root' }
    }
  } else {
    if (workspaceRoot === null) {
      return { state: 'outside_root', reason: 'the ticket workspace is outside the project root' }
    }
    base = workspaceRoot
    if (row.repo !== '') {
      const entry = (repoRoots ?? []).find(e => e.repo === row.repo)
      if (entry === undefined) {
        return {
          state: 'repo_root_unknown',
          reason: `repo '${row.repo}' is not on this ticket's workspace list`,
        }
      }
      base = entry.repo === '' ? workspaceRoot : join(workspaceRoot, entry.repo)
    }
    candidate = resolve(base, source)
    if (!isInside(base, candidate)) {
      return { state: 'outside_root', reason: `'${source}' escapes the declared root` }
    }
  }
  let realBase: string
  let realCandidate: string
  try {
    realBase = await realpath(base)
  } catch {
    return { state: 'missing', reason: 'the ticket workspace is not present on disk' }
  }
  try {
    realCandidate = await realpath(candidate)
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { state: 'missing', reason: 'no file at the declared source' }
    return { state: 'unreadable', reason: `resolve failed: ${String(err?.code ?? err?.message ?? err)}` }
  }
  if (!isInside(realBase, realCandidate) && realCandidate !== realBase) {
    return { state: 'outside_root', reason: 'the resolved path leaves the declared root (symlink)' }
  }
  return { state: 'ok', abs: realCandidate }
}

/** Metadata for one row: state, size and mtime. A row is never removed. */
export async function statArtifact(
  anchorRoot: string,
  workspaceRoot: string | null,
  repoRoots: RepoWorktreeEntry[] | undefined,
  row: ArtifactRow,
): Promise<ArtifactStat> {
  const r = await resolveSource(anchorRoot, workspaceRoot, repoRoots, row)
  if (r.state !== 'ok' || r.abs === undefined) {
    return { state: r.state, reason: r.reason ?? '' }
  }
  try {
    const st = await stat(r.abs)
    if (!st.isFile()) return { state: 'not_a_file', reason: 'the source is not a regular file' }
    const cap = artifactInlineCap(row.kind)
    if (st.size > cap) {
      return {
        state: 'too_large',
        sizeBytes: st.size,
        mtimeMs: st.mtimeMs,
        reason: `${st.size} bytes, over the ${cap} byte in-page limit`,
      }
    }
    // A text row must not claim to be openable when its bytes cannot be shown: the
    // panel would offer a link that fails on click. The read is bounded by the cap
    // already enforced above, so this costs at most one cap per text row.
    if (TEXT_KINDS.has(row.kind)) {
      if (!(await textIsUtf8(r.abs))) {
        return {
          state: 'not_utf8',
          sizeBytes: st.size,
          mtimeMs: st.mtimeMs,
          reason: 'the text is not valid UTF-8',
        }
      }
    }
    return { state: 'ok', sizeBytes: st.size, mtimeMs: st.mtimeMs }
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { state: 'missing', reason: 'no file at the declared source' }
    return { state: 'unreadable', reason: `stat failed: ${String(err?.code ?? err?.message ?? err)}` }
  }
}

/**
 * The inventory payload: derived rows plus one stat per row. `stageOrder` comes
 * from the caller (the console passes the selected template's stage order).
 */
export async function buildArtifactInventory(
  anchorRoot: string,
  detailRaw: unknown,
  stageOrder?: string[],
): Promise<ArtifactInventory> {
  const derived: DeriveResult = deriveArtifactRows(detailRaw, stageOrder)
  const ws = ticketWorkspaceRoot(anchorRoot, detailRaw)
  const repoRoots = ticketRepoRoots(detailRaw)
  const stats: Record<string, ArtifactStat> = {}
  for (const row of derived.rows) {
    // Keyed by the LISTING identity: the canonical list carries one entry per round,
    // so two rounds of the same artifact share `<stage>/<id>` but must keep two stats.
    stats[row.rowKey] = await statArtifact(anchorRoot, ws.root, repoRoots, row)
  }
  const repoNote = repoRoots === undefined
    ? 'no member repositories on this ticket'
    : repoRoots.map(e => e.repo || '(root)').join(', ')
  return {
    rows: derived.rows,
    stats,
    refusals: derived.refusals,
    listSource: derived.listSource,
    roots: {
      workspaceRoot: ws.root,
      repos: repoRoots === undefined ? [] : repoRoots.map(e => e.repo),
      note: ws.root === null ? ws.note : repoNote,
    },
  }
}

/** The file name a download is offered under: the declared basename, control-stripped. */
export function artifactFilename(source: string): string {
  const base = source.replace(/\\/g, '/').replace(/\/+$/, '')
  const name = base.slice(base.lastIndexOf('/') + 1)
  const clean = name.replace(/[\u0000-\u001f\u007f"\\]/g, '_').trim()
  return clean === '' ? 'artifact' : clean
}

/** Content type + disposition for one row (D6b). SVG is never served inline. */
export function artifactContentType(kind: string, source: string): { contentType: string; disposition: 'inline' | 'attachment' } {
  if (TEXT_KINDS.has(kind)) return { contentType: 'text/plain; charset=utf-8', disposition: 'inline' }
  if (kind === 'image') {
    const name = source.replace(/\\/g, '/').toLowerCase()
    const dot = name.lastIndexOf('.')
    const suffix = dot > 0 ? name.slice(dot) : ''
    const type = IMAGE_TYPE_BY_SUFFIX[suffix]
    if (type !== undefined) return { contentType: type, disposition: 'inline' }
    // Unknown image suffix (notably .svg): an SVG opened as a page runs script on
    // the console origin, so it leaves as a download.
    return { contentType: 'application/octet-stream', disposition: 'attachment' }
  }
  return { contentType: 'application/octet-stream', disposition: 'attachment' }
}

/**
 * Is this file valid UTF-8 text?
 *
 * Node's utf8 decode is lossy: an invalid byte sequence becomes U+FFFD. Re-reading
 * the file as text and looking for a replacement character is therefore the whole
 * test (a file that genuinely contains U+FFFD is indistinguishable, and refused —
 * the conservative direction: never show mojibake as content).
 *
 * The read uses the shim-declared `readFile(path, 'utf8')` overload on purpose; the
 * plugin carries no @types/node and `node-shims.d.ts` is outside this ticket's write
 * set (the missing `realpath` / raw-`readFile` / `stat().isFile` declarations are
 * booked in the ticket report).
 */
async function textIsUtf8(abs: string): Promise<boolean> {
  try {
    const s = await readFile(abs, 'utf8')
    return !s.includes('\uFFFD')
  } catch {
    return false
  }
}

/**
 * Read the original bytes of ONE declared row.
 *
 * Address is `<stage>` + `<id>`; the source comes from the snapshot, never from
 * the request. Zero match and more-than-one match are both refusals (the engine
 * enforces no id uniqueness), and a row whose key is ambiguous is refused even
 * when the caller names the stage.
 */
export async function readArtifactBytes(
  anchorRoot: string,
  detailRaw: unknown,
  stage: string,
  id: string,
): Promise<ArtifactByteAnswer> {
  const derived = deriveArtifactRows(detailRaw)
  // The same rule the inventory used to decide whether to offer the link: the NEWEST
  // round wins; two disagreeing newest-round sources are refused by name.
  const lookup = selectArtifactRowForBytes(derived.rows, stage, id)
  if (lookup.ok === false) {
    return { ok: false, code: lookup.code, reason: lookup.reason }
  }
  const row = lookup.row
  const ws = ticketWorkspaceRoot(anchorRoot, detailRaw)
  const repoRoots = ticketRepoRoots(detailRaw)
  const r = await resolveSource(anchorRoot, ws.root, repoRoots, row)
  if (r.state !== 'ok' || r.abs === undefined) {
    return { ok: false, code: 'refused', reason: r.reason ?? 'the declared source cannot be used' }
  }
  const cap = artifactInlineCap(row.kind)
  let size = 0
  try {
    const st = await stat(r.abs)
    if (!st.isFile()) return { ok: false, code: 'refused', reason: 'the source is not a regular file' }
    size = st.size
  } catch (err: any) {
    return { ok: false, code: 'not_found', reason: `stat failed: ${String(err?.code ?? err?.message ?? err)}` }
  }
  if (size > cap) {
    return {
      ok: false,
      code: 'too_large',
      reason: `${size} bytes, over the ${cap} byte in-page limit; open it from the workspace instead`,
    }
  }
  let body: Buffer
  try {
    body = await readFile(r.abs)
  } catch (err: any) {
    return { ok: false, code: 'refused', reason: `read failed: ${String(err?.code ?? err?.message ?? err)}` }
  }
  if (body.length > cap) {
    return {
      ok: false,
      code: 'too_large',
      reason: `${body.length} bytes, over the ${cap} byte in-page limit`,
    }
  }
  if (TEXT_KINDS.has(row.kind) && !(await textIsUtf8(r.abs))) {
    return { ok: false, code: 'not_utf8', reason: 'the text is not valid UTF-8' }
  }
  const { contentType, disposition } = artifactContentType(
    ARTIFACT_KINDS.includes(row.kind as never) ? row.kind : 'external',
    row.source,
  )
  return {
    ok: true,
    contentType,
    disposition,
    filename: artifactFilename(row.source),
    body,
    sizeBytes: body.length,
  }
}
