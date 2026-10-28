/**
 * review-comments.ts — the lane-file comment store for the changed-files
 * reviewer (t261022-14 markdown blocks; t261028-23 line anchors for code).
 *
 * ANCHOR SHAPES (t261028-23, additive):
 *   - block anchor (markdown reviewer, unchanged): {index, hash, neighbour}
 *   - line anchor (code file line diff, new):
 *       {kind:'line', side:'new'|'old', line, hunk, contextHash}
 *   A line anchor carries no `index`; the sanitizer accepts a thread when ONE
 *   of the two shapes is structurally usable. Documents written before this
 *   change (block anchors only) load byte-identically: every new field is
 *   optional and is omitted when absent, never defaulted into the record.
 *   A thread may also carry the owning file `path` (also additive) so one
 *   lane document can hold threads of several files without mixing them.
 *
 * The lane is the store (ticket requirement 6): every reviewer comment lives in
 * `<lane>/.sandbar/review-comments.json` — ONE document per lane whose threads
 * each name their owning file (`path`), so every changed file of the ticket is
 * reviewed from the same small file and nothing is written to a server-side
 * store; this module is plain file IO that the console host half performs on
 * the browser's behalf (a browser cannot touch the filesystem).
 *
 * Precedent copied (fault-mode tradeoff table in the ticket plan §F):
 *   - the `ticket show → t.worktree → anchorGuard` chain from
 *     `handleTicketTimeFile` (node.ts) — copied verbatim at the route layer;
 *   - path containment guard adapted to the lane root (was repo root);
 *   - `anchorGuard` reuse on a WRITE path accepted: the guard is containment,
 *     direction-agnostic, and the write path re-verifies containment of the
 *     resolved lane root after resolution (defense in depth, unit-tested).
 * Genuinely new write-path handling (not in the GET-only precedent): per-file
 * in-process mutex around every read-modify-write; temp file + atomic rename;
 * full-tail temp cleanup on every path; recursive mkdir of `.sandbar/`;
 * corrupt JSON never silently overwritten (GET reports it, PUT refuses 409);
 * body size cap with the existing file never truncated on over-cap.
 *
 * Cross-process races are out of scope by the single-owner assumption (one
 * console process owns a lane), stated in
 * docs/design/markdown-reviewer-panel-design.md.
 *
 * Browser half does not import this file (node:fs/promises).
 */

import { mkdir, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve, sep } from 'node:path'

/* ------------------------------------------------------------- constants */

/** File-size cap for the persisted document (merged result must not exceed it). */
export const REVIEW_COMMENTS_MAX_BYTES = 512 * 1024
/** Request-body cap applied at the module layer too (route also caps at 64KB). */
export const REVIEW_COMMENTS_MAX_THREADS = 500
/** Highest accepted 1-based line number of a line anchor (garbage-shaped input is refused). */
export const REVIEW_COMMENTS_MAX_LINE = 10_000_000
const TEMP_SUFFIX = '.tmp'

/* ---------------------------------------------------------------- schema */

/** One comment (root or reply) inside a thread. */
export interface ReviewCommentRecord {
  /** Millisecond epoch of the write. */
  at: number
  author: string
  text: string
}

/** Which side of the diff a line anchor points at: the changed file ('new') or its base ('old'). */
export type ReviewLineSide = 'new' | 'old'

/** Markdown reviewer anchor (t261022-14): block index + text hash + neighbour snippet. */
export interface ReviewBlockAnchorRecord {
  index: number
  hash: string
  neighbour: string
}

/** Line reviewer anchor (t261028-23): side + 1-based line + hunk id + row text hash. */
export interface ReviewLineAnchorRecord {
  kind: 'line'
  side: ReviewLineSide
  line: number
  hunk: string
  contextHash: string
}

export type ReviewAnchorRecord = ReviewBlockAnchorRecord | ReviewLineAnchorRecord

/**
 * One thread: a root comment plus nested replies (ticket requirement 5).
 * parentId === null marks the root; replies carry their parent thread id.
 */
export interface ReviewThreadRecord {
  id: string
  parentId: string | null
  /** What this thread is anchored to: a markdown block or a diff line. */
  anchor: ReviewAnchorRecord
  /** Owning file (repo-relative). Absent in legacy documents: such a thread
   *  belongs to the document's own `path`. */
  path?: string
  author: string
  at: number
  text: string
  resolved: boolean
  replies: ReviewCommentRecord[]
}

/** True when the anchor is the line-anchored shape (code files, t261028-23). */
export function isLineAnchor(a: ReviewAnchorRecord): a is ReviewLineAnchorRecord {
  return (a as ReviewLineAnchorRecord).kind === 'line'
}

/** The whole persisted document (one ticket × one file path). */
export interface ReviewCommentsDoc {
  schema: 'review-comments-v1'
  ticketId: string
  path: string
  updatedAt: number
  threads: ReviewThreadRecord[]
}

export type ReviewCommentsRead =
  | { ok: true; file: string; doc: ReviewCommentsDoc | null }
  | { ok: false; reason: string; file: string }

/* --------------------------------------------------------------- sanitize */

function asStr(v: unknown, cap = 4000): string {
  return typeof v === 'string' ? v.slice(0, cap) : ''
}

function asInt(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? Math.trunc(v) : null
}

/** Structural sanitize of one thread; returns null for unusable entries (caller counts the drops). */
export function sanitizeThread(raw: unknown): ReviewThreadRecord | null {
  if (raw === null || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const id = asStr(r.id, 200)
  if (id === '') return null
  const anchorRaw = (r.anchor ?? {}) as Record<string, unknown>
  const anchor = sanitizeAnchor(anchorRaw)
  if (anchor === null) return null
  const resolved = r.resolved === true
  const parentId = r.parentId === null || r.parentId === undefined ? null : asStr(r.parentId, 200) || null
  const at = asInt(r.at) ?? 0
  const replies: ReviewCommentRecord[] = []
  if (Array.isArray(r.replies)) {
    for (const rep of r.replies) {
      if (rep === null || typeof rep !== 'object') continue
      const rr = rep as Record<string, unknown>
      const text = asStr(rr.text)
      if (text === '') continue
      replies.push({ at: asInt(rr.at) ?? 0, author: asStr(rr.author, 200), text })
      if (replies.length >= 200) break
    }
  }
  const out: ReviewThreadRecord = {
    id,
    parentId,
    anchor,
    author: asStr(r.author, 200),
    at,
    text: asStr(r.text),
    resolved,
    replies,
  }
  // Additive: only carried when present, so legacy records keep their exact shape.
  const owner = asStr(r.path, 1000)
  if (owner !== '') out.path = owner
  return out
}

/**
 * Sanitize one anchor object. Line anchors (kind:'line') need a valid side and
 * a 1-based line; block anchors need a non-negative index. Anything else is
 * unusable — the caller names the drop instead of guessing a position.
 */
export function sanitizeAnchor(raw: Record<string, unknown>): ReviewAnchorRecord | null {
  if (raw.kind === 'line') {
    const sideRaw = raw.side
    if (sideRaw !== 'new' && sideRaw !== 'old') return null
    const line = asInt(raw.line)
    if (line === null || line < 1 || line > REVIEW_COMMENTS_MAX_LINE) return null
    return {
      kind: 'line',
      side: sideRaw,
      line,
      hunk: asStr(raw.hunk, 200),
      contextHash: asStr(raw.contextHash, 200),
    }
  }
  // Legacy / implicit block anchor: `kind` absent or 'block'.
  if (raw.kind !== undefined && raw.kind !== 'block') return null
  const index = asInt(raw.index)
  if (index === null || index < 0) return null
  return { index, hash: asStr(raw.hash, 200), neighbour: asStr(raw.neighbour, 400) }
}

/**
 * Sanitize a raw document (whatever JSON.parse produced). Entries that cannot
 * be structurally repaired are DROPPED WITH A COUNT — the count is surfaced by
 * the caller/panel face, never silently (ticket rule 7: a thread is never
 * silently dropped; structurally unusable entries are the one exception and
 * they are named, not hidden).
 */
export function sanitizeDoc(raw: unknown, ticketId: string, path: string): { doc: ReviewCommentsDoc; dropped: number } {
  const threads: ReviewThreadRecord[] = []
  let dropped = 0
  const seen = new Set<string>()
  if (Array.isArray((raw as Record<string, unknown>)?.threads)) {
    for (const t of (raw as Record<string, unknown>).threads as unknown[]) {
      const s = sanitizeThread(t)
      if (s === null || seen.has(s.id)) { dropped += 1; continue }
      seen.add(s.id)
      threads.push(s)
    }
  } else if (raw !== null && typeof raw === 'object' && Array.isArray((raw as any).threads) === false) {
    dropped += 1
  }
  const updatedAt = asInt((raw as Record<string, unknown>)?.updatedAt) ?? 0
  return {
    doc: { schema: 'review-comments-v1', ticketId: asStr(ticketId, 200), path: asStr(path, 1000), updatedAt, threads },
    dropped,
  }
}

/* ------------------------------------------------------------------ paths */

/** True when `p` is a safe repo-relative file path (no absolute, no `..`, no drive tricks). */
export function isSafeRelPath(p: string): boolean {
  if (p === '' || p.length > 1000) return false
  if (isAbsolute(p) || p.startsWith('~') || p.includes('..')) return false
  if (p.includes('\0')) return false
  return true
}

/**
 * Resolve and verify the store file path for a lane root.
 * The lane root must resolve INSIDE `repoRoot` (anchor containment re-check on
 * the write path, plan §F). Returns null when the lane root or the path is
 * unsafe — the caller answers a named 4xx.
 */
export function reviewCommentsFilePath(repoRoot: string, laneRoot: string, relPath: string): string | null {
  if (!isSafeRelPath(relPath)) return null
  if (laneRoot === '') return null
  const laneAbs = resolve(repoRoot, laneRoot)
  if (laneAbs !== repoRoot && !laneAbs.startsWith(repoRoot + sep)) return null
  return join(laneAbs, '.sandbar', 'review-comments.json')
}

/* ------------------------------------------------------------------ mutex */

/** Per-file in-process mutex: every read-modify-write cycle serializes per file. */
const locks = new Map<string, Promise<unknown>>()

async function withLock<T>(file: string, fn: () => Promise<T>): Promise<T> {
  const prev = locks.get(file) ?? Promise.resolve()
  let release!: () => void
  const gate = new Promise<void>((r) => { release = r })
  locks.set(file, prev.then(() => gate))
  await prev
  try {
    return await fn()
  } finally {
    // The settled chain entry stays in the map (bounded by the number of files
    // this process touches) — deleting it here would race a queued waiter.
    release()
  }
}

/* ------------------------------------------------------------------- read */

/**
 * Read the store document. A missing file is a NORMAL state (ok, doc=null) —
 * no comments yet. Corrupt/unreadable JSON is reported by name (ok:false) and
 * is NEVER silently treated as empty (a silent empty would let the next PUT
 * overwrite evidence).
 */
export async function readReviewComments(file: string): Promise<ReviewCommentsRead> {
  let raw: string
  try {
    raw = await readFile(file, 'utf8')
  } catch {
    return { ok: true, file, doc: null }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (err) {
    return { ok: false, file, reason: `review comments file is not valid JSON: ${String(err instanceof Error ? err.message : err)}` }
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, file, reason: 'review comments file is not a JSON object' }
  }
  const { doc } = sanitizeDoc(parsed, asStr((parsed as Record<string, unknown>).ticketId, 200), asStr((parsed as Record<string, unknown>).path, 1000))
  return { ok: true, file, doc }
}

/* ------------------------------------------------------------------ merge */

export type ReviewCommentsMerge =
  | { ok: true; file: string; doc: ReviewCommentsDoc; dropped: number }
  | { ok: false; file: string; reason: string; code?: 'corrupt' | 'oversize' | 'io' | 'unsafe' }

/**
 * Merge `incoming` threads into the store and persist atomically
 * (temp file + rename; temp always unlinked, on every path).
 * Threads merge by id (last write wins per thread). The existing file is never
 * truncated by a failure: an over-cap result refuses the write (oversize), a
 * corrupt existing file refuses the merge (409 at the route layer).
 */
export async function mergeReviewComments(
  file: string,
  ticketId: string,
  relPath: string,
  incoming: unknown,
): Promise<ReviewCommentsMerge> {
  return withLock(file, async () => {
    const read = await readReviewComments(file)
    if (!read.ok) {
      return { ok: false, file, reason: read.reason, code: 'corrupt' as const }
    }
    const base = read.doc ?? { schema: 'review-comments-v1' as const, ticketId, path: relPath, updatedAt: 0, threads: [] }
    const byId = new Map<string, ReviewThreadRecord>()
    for (const t of base.threads) byId.set(t.id, t)
    let dropped = 0
    const incThreads = Array.isArray((incoming as Record<string, unknown>)?.threads)
      ? (incoming as Record<string, unknown>).threads as unknown[]
      : []
    if (incThreads.length > REVIEW_COMMENTS_MAX_THREADS) {
      return { ok: false, file, reason: `too many threads in one request (max ${REVIEW_COMMENTS_MAX_THREADS})`, code: 'oversize' as const }
    }
    const incomingIds = new Set<string>()
    for (const raw of incThreads) {
      const s = sanitizeThread(raw)
      if (s === null) { dropped += 1; continue }
      incomingIds.add(s.id)
      byId.set(s.id, s)
    }
    // Backfill the owning file on threads written before the field existed: at
    // write time the document's own `path` is still the file they were created
    // for (a legacy client always wrote its own path). Without the stamp a
    // legacy thread would drift to whichever file wrote last.
    if (base.path !== '') {
      for (const t of byId.values()) {
        if (t.path === undefined && !incomingIds.has(t.id)) t.path = base.path
      }
    }
    const doc: ReviewCommentsDoc = {
      schema: 'review-comments-v1',
      ticketId: ticketId !== '' ? ticketId : base.ticketId,
      path: relPath !== '' ? relPath : base.path,
      updatedAt: Date.now(),
      threads: [...byId.values()],
    }
    const text = JSON.stringify(doc, null, 2)
    if (Buffer.byteLength(text, 'utf8') > REVIEW_COMMENTS_MAX_BYTES) {
      return { ok: false, file, reason: `merged document would exceed ${REVIEW_COMMENTS_MAX_BYTES} bytes — refusing (existing file untouched)`, code: 'oversize' as const }
    }
    const tmp = `${file}${TEMP_SUFFIX}`
    try {
      await mkdir(dirname(file), { recursive: true })
      await writeFile(tmp, text, 'utf8')
      await rename(tmp, file)
    } catch (err) {
      // Full-tail cleanup: the temp file never survives an error path.
      try { await unlink(tmp) } catch { /* already gone */ }
      try { await stat(file) } catch { /* target absent is fine */ }
      return { ok: false, file, reason: `write failed: ${String(err instanceof Error ? err.message : err)}`, code: 'io' as const }
    }
    return { ok: true, file, doc, dropped }
  })
}
