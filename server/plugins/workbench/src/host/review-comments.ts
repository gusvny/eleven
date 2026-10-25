/**
 * review-comments.ts — the lane-file comment store for the changed-files
 * markdown reviewer (t261022-14).
 *
 * The lane is the store (ticket requirement 6): every reviewer comment lives in
 * `<lane>/.sandbar/review-comments.json`, one document per (ticket, file path).
 * Nothing is written to any server-side store; this module is plain file IO
 * that the console host half performs on the browser's behalf (a browser cannot
 * touch the filesystem).
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
const TEMP_SUFFIX = '.tmp'

/* ---------------------------------------------------------------- schema */

/** One comment (root or reply) inside a thread. */
export interface ReviewCommentRecord {
  /** Millisecond epoch of the write. */
  at: number
  author: string
  text: string
}

/**
 * One thread: a root comment plus nested replies (ticket requirement 5).
 * parentId === null marks the root; replies carry their parent thread id.
 */
export interface ReviewThreadRecord {
  id: string
  parentId: string | null
  /** The block this thread is anchored to: index + text hash + neighbour snippet (requirement 7). */
  anchor: {
    index: number
    hash: string
    neighbour: string
  }
  author: string
  at: number
  text: string
  resolved: boolean
  replies: ReviewCommentRecord[]
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
  const index = asInt(anchorRaw.index)
  const hash = asStr(anchorRaw.hash, 200)
  if (index === null || index < 0) return null
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
  return {
    id,
    parentId,
    anchor: { index, hash, neighbour: asStr(anchorRaw.neighbour, 400) },
    author: asStr(r.author, 200),
    at,
    text: asStr(r.text),
    resolved,
    replies,
  }
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
    for (const raw of incThreads) {
      const s = sanitizeThread(raw)
      if (s === null) { dropped += 1; continue }
      byId.set(s.id, s)
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
