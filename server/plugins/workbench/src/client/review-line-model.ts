/**
 * review-line-model.ts — line-anchored comment model for the code-file
 * reviewer (t261028-23). Zero React / DOM / node imports; unit-tested directly
 * by tests/t261028-23-review-line-anchor.mjs and t261028-23-line-reviewer-face.mjs.
 *
 * It is the line-mode twin of review-panel-model.ts's block model, and it
 * carries the same discipline:
 *   - a thread resolves by (side, line, hunk, contextHash); when it no longer
 *     matches it becomes OUTDATED and is still shown — never dropped, never
 *     re-placed on a different line;
 *   - the store record shape is produced by ONE serialization seam
 *     (toStoreLineThread), so a panel write can never diverge from what the
 *     lane agents read;
 *   - hostile input is normalised, never thrown on; unusable entries are
 *     COUNTED, and the count is surfaced by the panel.
 *
 * The render grouping (buildLineRender) is the model half of the rendering
 * leg: it decides which thread sits under which row, the panel only prints it.
 */

import { blockHash } from './review-panel-model.ts'
import {
  rowMatchesAnchor,
  rowMatchesAnchorLoosely,
  type DiffHunk,
  type DiffLineAnchor,
  type DiffRow,
} from './diff-rows-model.ts'

/* ---------------------------------------------------------------- helpers */

function asStr(v: unknown, cap = 4000): string {
  return typeof v === 'string' ? v.slice(0, cap) : ''
}

function asNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/* ----------------------------------------------------------------- threads */

export interface LineReply { author: string; at: number; text: string }

/** One line-anchored thread: root comment plus nested replies. */
export interface LineThread {
  id: string
  parentId: string | null
  anchor: DiffLineAnchor
  author: string
  at: number
  text: string
  resolved: boolean
  replies: LineReply[]
}

/** Read the line anchor out of a raw store record; null when it is not one. */
export function readLineAnchor(raw: unknown): DiffLineAnchor | null {
  if (raw === null || typeof raw !== 'object') return null
  const a = raw as Record<string, unknown>
  if (a.kind !== 'line') return null
  const side = a.side
  if (side !== 'new' && side !== 'old') return null
  const line = asNum(a.line)
  if (line === null || !Number.isInteger(line) || line < 1) return null
  return {
    kind: 'line',
    side,
    line,
    hunk: asStr(a.hunk, 200),
    contextHash: asStr(a.contextHash, 200),
  }
}

/**
 * Normalize whatever the lane file (or the network) carried into line threads.
 * Records that are not line-anchored are counted as dropped — the panel names
 * the count (the markdown reviewer's "never silent" rule).
 */
export function normalizeLineThreads(raw: unknown): { threads: LineThread[]; dropped: number } {
  const threads: LineThread[] = []
  let dropped = 0
  const arr = Array.isArray(raw) ? raw : []
  const seen = new Set<string>()
  for (const item of arr) {
    if (item === null || typeof item !== 'object') { dropped += 1; continue }
    const r = item as Record<string, unknown>
    const id = asStr(r.id, 200)
    if (id === '' || seen.has(id)) { dropped += 1; continue }
    const anchor = readLineAnchor(r.anchor)
    if (anchor === null) { dropped += 1; continue }
    seen.add(id)
    const replies: LineReply[] = []
    if (Array.isArray(r.replies)) {
      for (const rep of r.replies) {
        if (rep === null || typeof rep !== 'object') continue
        const rr = rep as Record<string, unknown>
        const text = asStr(rr.text)
        if (text === '') continue
        replies.push({ author: asStr(rr.author, 200), at: asNum(rr.at) ?? 0, text })
        if (replies.length >= 200) break
      }
    }
    threads.push({
      id,
      parentId: r.parentId === null || r.parentId === undefined ? null : asStr(r.parentId, 200) || null,
      anchor,
      author: asStr(r.author, 200),
      at: asNum(r.at) ?? 0,
      text: asStr(r.text),
      resolved: r.resolved === true,
      replies,
    })
  }
  return { threads, dropped }
}

/**
 * The single serialization seam of line mode: model thread -> store record.
 * `path` stamps the owning file so one lane document can hold threads of
 * several files without mixing them.
 */
export function toStoreLineThread(t: LineThread, path = ''): Record<string, unknown> {
  const out: Record<string, unknown> = {
    id: t.id,
    parentId: t.parentId,
    anchor: {
      kind: 'line',
      side: t.anchor.side,
      line: t.anchor.line,
      hunk: t.anchor.hunk,
      contextHash: t.anchor.contextHash,
    },
    author: t.author,
    at: t.at,
    text: t.text,
    resolved: t.resolved,
    replies: t.replies.map((r) => ({ at: r.at, author: r.author, text: r.text })),
  }
  if (path !== '') out.path = path
  return out
}

/* ------------------------------------------------------------ resolution */

export type LineAnchorResolution =
  /** The recorded line is there with the same text in the same hunk. */
  | { kind: 'exact'; row: number }
  /** Same side + line + text, but the hunk header changed (an insert above). */
  | { kind: 'relocated'; row: number }
  /** The line is gone or its text changed: the thread is outdated, never moved. */
  | { kind: 'outdated'; row: null }

/** Resolve one anchor against the current rows (exact, then same-line/same-text). */
export function resolveLineAnchor(rows: DiffRow[], anchor: DiffLineAnchor): LineAnchorResolution {
  for (const r of rows) if (rowMatchesAnchor(r, anchor)) return { kind: 'exact', row: r.index }
  for (const r of rows) if (rowMatchesAnchorLoosely(r, anchor)) return { kind: 'relocated', row: r.index }
  return { kind: 'outdated', row: null }
}

export interface PlacedLineThread {
  thread: LineThread
  resolution: LineAnchorResolution
}

/** Place every thread; nothing is ever dropped from the result. */
export function placeLineThreads(rows: DiffRow[], threads: LineThread[]): PlacedLineThread[] {
  return threads
    .map((thread) => ({ thread, resolution: resolveLineAnchor(rows, thread.anchor) }))
    .sort((a, b) => a.thread.at - b.thread.at)
}

/** Threads the panel prints under one row (resolved ones included: the badge needs both). */
export function threadsForRow(placed: PlacedLineThread[], row: number): LineThread[] {
  return placed.filter((p) => p.resolution.row === row).map((p) => p.thread)
}

export function openCountForRow(placed: PlacedLineThread[], row: number): number {
  return threadsForRow(placed, row).filter((t) => !t.resolved).length
}

/** Badge-grey rule carried over from the markdown reviewer. */
export function hasOnlyResolvedForRow(placed: PlacedLineThread[], row: number): boolean {
  const ts = threadsForRow(placed, row)
  return ts.length > 0 && ts.every((t) => t.resolved)
}

export type CommentFilter = 'open' | 'all' | 'resolved'

export function filterLineThreads(threads: LineThread[], f: CommentFilter): LineThread[] {
  if (f === 'open') return threads.filter((t) => !t.resolved)
  if (f === 'resolved') return threads.filter((t) => t.resolved)
  return threads
}

/* ------------------------------------------------------- render grouping */

export type LineRender =
  | { kind: 'hunk'; hunk: DiffHunk }
  | { kind: 'row'; row: DiffRow; threads: LineThread[] }
  | { kind: 'outdated'; thread: LineThread }

/**
 * Flatten rows + hunks + threads into what the view prints, in order:
 * each hunk header, then its rows (each row followed by its threads), then the
 * outdated threads at the end of the diff. The record id of an outdated thread
 * never changes and no row is invented for it.
 */
export function buildLineRender(rows: DiffRow[], hunks: DiffHunk[], threads: LineThread[]): LineRender[] {
  const placed = placeLineThreads(rows, threads)
  const out: LineRender[] = []
  const hunkAt = new Map<number, DiffHunk>()
  for (const h of hunks) hunkAt.set(h.firstRow, h)
  for (const row of rows) {
    const h = hunkAt.get(row.index)
    if (h !== undefined) out.push({ kind: 'hunk', hunk: h })
    out.push({ kind: 'row', row, threads: threadsForRow(placed, row.index) })
  }
  for (const p of placed) {
    if (p.resolution.kind === 'outdated') out.push({ kind: 'outdated', thread: p.thread })
  }
  return out
}

/* --------------------------------------------------------------- TOC face */

/** Sidebar entry per hunk: its display header and the row it jumps to. */
export function hunkToc(hunks: DiffHunk[]): { id: string; label: string; row: number }[] {
  return hunks.map((h) => ({ id: h.id, label: h.label, row: h.firstRow }))
}

/** The line text hash a comment records (exposed so views and tests agree). */
export function lineContextHash(text: string): string {
  return blockHash(text)
}
