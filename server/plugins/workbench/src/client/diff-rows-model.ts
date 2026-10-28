/**
 * diff-rows-model.ts — pure unified-diff row model for the file reviewer
 * (t261028-23). Zero React / DOM / node imports; unit-tested directly by
 * tests/t261028-23-diff-rows-model.mjs.
 *
 * Input is the `unified` string the diff face already carries for code files
 * (host changes.ts: `git diff <base> -- <path>`, or the synthesised all-`+`
 * form for an added file, or the degraded removed-then-added form when a JSON
 * file fails to parse). This model produces:
 *   - rows: one per diff line, carrying BOTH line numbers, the change kind,
 *     the hunk it belongs to and the row text;
 *   - hunks: the hunk list a view needs (header label + row range);
 *   - the anchor <-> row mapping a comment needs (side/line/hunk/contextHash).
 *
 * Anchor discipline (same family as the markdown reviewer's block anchor):
 * a thread records what the reviewer SAW, and resolution later requires it to
 * still match. `rowMatchesAnchor` is the exact match; `rowMatchesAnchorLoosely`
 * accepts the same side+line+text under a different hunk header (an insert
 * above shifts hunk boundaries, the line itself did not move).
 *
 * Malformed input NEVER throws and never invents rows: it returns a NAMED
 * empty state (`empty-diff` / `malformed-diff` / `no-unified-diff`) with a
 * reason the panel shows. A silently empty diff would read as "no changes".
 */

import { blockHash } from './review-panel-model.ts'

/* ------------------------------------------------------------- constants */

/** The diff carried no hunk header (added file / degraded view): one stable synthetic hunk. */
export const SYNTHETIC_HUNK_ID = '@@ synthetic @@'
export const SYNTHETIC_HUNK_LABEL = '@@ synthetic (no hunk header in this diff) @@'

/** Named empty states — the panel renders these by name, never as a blank view. */
export const DIFF_EMPTY = 'empty-diff'
export const DIFF_MALFORMED = 'malformed-diff'
export const DIFF_NO_UNIFIED = 'no-unified-diff'
export type DiffEmptyState = typeof DIFF_EMPTY | typeof DIFF_MALFORMED | typeof DIFF_NO_UNIFIED

/* ----------------------------------------------------------------- types */

export type DiffRowKind = 'context' | 'added' | 'removed'

/** One diff line: what a comment anchors to and what the view prints. */
export interface DiffRow {
  /** Dense position of this row in the parsed diff. */
  index: number
  /** Stable key for rendering: both line numbers (one of them null). */
  key: string
  kind: DiffRowKind
  /** 1-based base-side line number, null for an added line. */
  oldLine: number | null
  /** 1-based changed-side line number, null for a removed line. */
  newLine: number | null
  text: string
  /** Id of the owning hunk (`DiffHunk.id`). */
  hunk: string
  /** Hash of the row text — the anchor's context hash. */
  hash: string
}

export interface DiffHunk {
  /** Anchor key of the hunk: the header line, or SYNTHETIC_HUNK_ID. */
  id: string
  /** Display header. */
  label: string
  oldStart: number
  oldCount: number
  newStart: number
  newCount: number
  /** Index of the first row belonging to this hunk. */
  firstRow: number
  rowCount: number
}

/** A code-file line anchor, the client-side mirror of the store record shape. */
export interface DiffLineAnchor {
  kind: 'line'
  side: 'new' | 'old'
  line: number
  hunk: string
  contextHash: string
}

export interface DiffParseOk {
  ok: true
  rows: DiffRow[]
  hunks: DiffHunk[]
  added: number
  removed: number
  /** True when the diff had no hunk header (added-file / degraded form). */
  synthetic: boolean
  /** Unrecognised preamble/noise lines that were skipped (named, not hidden). */
  skipped: number
}

export interface DiffParseEmpty {
  ok: false
  state: DiffEmptyState
  reason: string
}

export type DiffParse = DiffParseOk | DiffParseEmpty

/* --------------------------------------------------------------- parsing */

interface OpenHunk {
  id: string
  label: string
  oldStart: number
  oldCount: number
  newStart: number
  newCount: number
  oldLeft: number
  newLeft: number
  firstRow: number
  /** Synthetic hunks have no declared counts: they consume to the end of the input. */
  synthetic: boolean
}

const HUNK_RE = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/

/** File-level preamble a `git diff` emits before the hunks. */
const PREAMBLE_RE = /^(diff --git |index |new file mode |deleted file mode |old mode |new mode |similarity index |dissimilarity index |rename from |rename to |Binary files .* differ$)/

/** Short, always-single-line snippet of a line for a named reason. */
function snippet(line: string, cap = 90): string {
  const s = line.length > cap ? line.slice(0, cap) + '…' : line
  return JSON.stringify(s)
}

/**
 * Parse the unified diff of ONE file into rows + hunks.
 * Never throws; unusable input yields a named empty state.
 */
export function parseUnifiedDiff(unified: unknown): DiffParse {
  if (typeof unified !== 'string') {
    return {
      ok: false,
      state: DIFF_NO_UNIFIED,
      reason: 'the diff face carries no unified diff for this file (structural view only)',
    }
  }
  const text = unified.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  if (text.trim() === '') {
    return { ok: false, state: DIFF_EMPTY, reason: 'the diff face returned an empty unified diff for this file' }
  }

  const lines = text.split('\n')
  const rows: DiffRow[] = []
  const hunks: DiffHunk[] = []
  let synthetic = false
  let skipped = 0
  let oldNo = 0
  let newNo = 0
  let cur: OpenHunk | null = null
  let firstSkipped = ''
  /** A `diff --git`/`--- …`/`+++ …` header was seen: later `--- `/`+++ ` lines are headers too. */
  let sawFileHeader = false

  const closeHunk = (): void => {
    if (cur === null) return
    hunks.push({
      id: cur.id,
      label: cur.label,
      oldStart: cur.oldStart,
      oldCount: cur.oldCount,
      newStart: cur.newStart,
      newCount: cur.newCount,
      firstRow: cur.firstRow,
      rowCount: rows.length - cur.firstRow,
    })
    cur = null
  }

  const openHunk = (line: string): void => {
    const m = HUNK_RE.exec(line)
    if (m === null) return // a malformed '@@' line is noise, not a hunk
    closeHunk()
    const oldStart = Number(m[1])
    const oldCount = m[2] === undefined ? 1 : Number(m[2])
    const newStart = Number(m[3])
    const newCount = m[4] === undefined ? 1 : Number(m[4])
    cur = {
      id: line.trim(),
      label: line.trim(),
      oldStart,
      oldCount,
      newStart,
      newCount,
      oldLeft: oldCount,
      newLeft: newCount,
      firstRow: rows.length,
      synthetic: false,
    }
    oldNo = oldStart
    newNo = newStart
  }

  const openSyntheticHunk = (): void => {
    closeHunk()
    synthetic = true
    // No header shipped: numbering restarts at 1 on both sides and every row
    // is consumed to the end of the input.
    oldNo = 1
    newNo = 1
    cur = {
      id: SYNTHETIC_HUNK_ID,
      label: SYNTHETIC_HUNK_LABEL,
      oldStart: 0,
      oldCount: 0,
      newStart: 0,
      newCount: 0,
      oldLeft: Number.POSITIVE_INFINITY,
      newLeft: Number.POSITIVE_INFINITY,
      firstRow: rows.length,
      synthetic: true,
    }
  }

  const pushRow = (marker: string, body: string): void => {
    if (cur === null) return
    const kind: DiffRowKind = marker === '+' ? 'added' : marker === '-' ? 'removed' : 'context'
    const oldLine = kind === 'added' ? null : oldNo
    const newLine = kind === 'removed' ? null : newNo
    if (kind !== 'added') oldNo += 1
    if (kind !== 'removed') newNo += 1
    rows.push({
      index: rows.length,
      key: `L${oldLine === null ? '-' : oldLine}N${newLine === null ? '-' : newLine}`,
      kind,
      oldLine,
      newLine,
      text: body,
      hunk: cur.id,
      hash: blockHash(body),
    })
  }

  const countSkipped = (line: string): void => {
    skipped += 1
    if (firstSkipped === '') firstSkipped = line
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ''
    const marker = line === '' ? '' : line[0] ?? ''

    // Inside a hunk with declared counts still outstanding: every line is a row.
    if (cur !== null && (cur.oldLeft > 0 || cur.newLeft > 0)) {
      if (marker === '+' || marker === '-' || marker === ' ') {
        pushRow(marker, line.slice(1))
        if (cur !== null && !cur.synthetic) {
          if (marker !== '+') cur.oldLeft -= 1
          if (marker !== '-') cur.newLeft -= 1
        }
        continue
      }
      if (marker === '\\') continue // "\ No newline at end of file"
      // Unknown marker with counts outstanding (truncated/corrupt hunk): end the
      // hunk here and let the outer state machine see this line.
      closeHunk()
    }

    if (cur !== null && !HUNK_RE.test(line)) {
      // Counts satisfied: a new hunk header continues the diff; anything else
      // ends this hunk and is re-examined below as preamble/noise.
      closeHunk()
    }

    if (line === '' || marker === '\\') continue
    if (HUNK_RE.test(line)) { openHunk(line); continue }
    if (PREAMBLE_RE.test(line)) { sawFileHeader = true; continue }
    // `--- <path>` / `+++ <path>` file headers (git and plain `diff -u` forms).
    // Before any hunk they are unambiguous; later they are only headers when the
    // diff already declared itself with a `diff --git` line.
    if (cur === null && (sawFileHeader || (hunks.length === 0 && !synthetic && rows.length === 0))
      && line.startsWith('--- ') && (lines[i + 1] ?? '').startsWith('+++ ')) {
      sawFileHeader = true
      i += 1
      continue
    }
    if (marker === ' ' && cur === null && rows.length === 0) {
      // Indented preamble (e.g. a `--stat` summary): never a context row before
      // any hunk exists — a real context row always has a hunk header above it.
      countSkipped(line)
      continue
    }
    if (marker === '+' || marker === '-' || marker === ' ') {
      // No hunk has been opened at all (the added-file / degraded form): one
      // synthetic hunk owns the rest of the input.
      if (cur === null && !synthetic && hunks.length === 0) openSyntheticHunk()
      if (cur !== null) pushRow(marker, line.slice(1))
      else countSkipped(line)
      continue
    }
    countSkipped(line)
  }
  closeHunk()

  if (rows.length === 0) {
    return {
      ok: false,
      state: DIFF_MALFORMED,
      reason: firstSkipped === ''
        ? 'no hunk header and no +/- line in this diff'
        : `no hunk header and no +/- line in this diff (first unrecognised line: ${snippet(firstSkipped)})`,
    }
  }

  let added = 0
  let removed = 0
  for (const r of rows) {
    if (r.kind === 'added') added += 1
    else if (r.kind === 'removed') removed += 1
  }
  return { ok: true, rows, hunks, added, removed, synthetic, skipped }
}

/* ------------------------------------------------------- anchor <-> row */

/** The anchor a comment on this row records: removed rows anchor to the base side. */
export function rowAnchor(row: DiffRow): DiffLineAnchor | null {
  const side: 'new' | 'old' = row.kind === 'removed' ? 'old' : 'new'
  const line = side === 'old' ? row.oldLine : row.newLine
  if (line === null || line < 1) return null
  return { kind: 'line', side, line, hunk: row.hunk, contextHash: row.hash }
}

/** True when the row is the exact line the anchor recorded (all four fields match). */
export function rowMatchesAnchor(row: DiffRow, a: DiffLineAnchor): boolean {
  if (a.line < 1 || a.contextHash === '') return false
  const line = a.side === 'old' ? row.oldLine : row.newLine
  if (line === null || line !== a.line) return false
  if (row.hunk !== a.hunk) return false
  return row.hash === a.contextHash
}

/**
 * True when the row is the same line with the same text under a different hunk
 * id (an insert above shifts hunk boundaries; the line itself did not move).
 */
export function rowMatchesAnchorLoosely(row: DiffRow, a: DiffLineAnchor): boolean {
  if (a.line < 1 || a.contextHash === '') return false
  const line = a.side === 'old' ? row.oldLine : row.newLine
  if (line === null || line !== a.line) return false
  return row.hash === a.contextHash
}

/** The row a view prints for an anchor, or undefined when the anchor is gone. */
export function rowForAnchor(rows: DiffRow[], a: DiffLineAnchor): DiffRow | undefined {
  return rows.find((r) => rowMatchesAnchor(r, a)) ?? rows.find((r) => rowMatchesAnchorLoosely(r, a))
}

/** Human label for the line an anchor points at ("new line 42"). */
export function anchorLabel(a: DiffLineAnchor): string {
  return `${a.side === 'old' ? 'old' : 'new'} line ${a.line}`
}
