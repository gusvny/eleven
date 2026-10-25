/**
 * review-panel-model.ts — pure model for the changed-files markdown reviewer
 * (t261022-14). Zero React / DOM / node imports; unit-tested directly by
 * tests/t26102214-review-panel-model.mjs.
 *
 * Block model (ticket requirement 2): the document is split into blocks — one
 * heading, one paragraph, one list item, ONE TABLE CELL each. The diff face
 * (host changes.ts → knowledge blocks.ts) ships ROW-level blocks for tables,
 * so this model subdivides every table-head/table-row block into per-cell
 * child blocks; the cell becomes the unit of diff mark, comment anchor and
 * navigation (plan §0 — knowledge/ stays untouched, outside the write set).
 *
 * Anchoring (requirement 7): a thread records { index, hash, neighbour }.
 * Resolution: exact hash match first → index + neighbour fallback → outdated
 * at the end of the document. A thread is NEVER silently dropped.
 *
 * Malformed-input discipline (external data is untrusted, same family as
 * lane-map-model): nothing throws on hostile shapes; unusable entries are
 * skipped with a count the panel face surfaces.
 */

/* ---------------------------------------------------------------- helpers */

/** Tolerant string (everything else → ''). */
function asStr(v: unknown, cap = 4000): string {
  return typeof v === 'string' ? v.slice(0, cap) : ''
}

function asNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** djb2-style hex hash over the block text — the anchor hash on both write and resolve sides. */
export function blockHash(text: string): string {
  let h = 5381
  for (let i = 0; i < text.length; i++) h = ((h * 33) ^ text.charCodeAt(i)) >>> 0
  return h.toString(16).padStart(8, '0')
}

/* -------------------------------------------------------------- word diff */

/** One inline run: optional struck-out old text and/or inserted new text. */
export interface WordOp { del?: string; add?: string }

/**
 * Word-level diff of a modified block's text (requirement 3: the exact changed
 * text carries word-level marks). Tokenize on whitespace-boundary words, align
 * with an LCS DP (documents are small, O(n·m) is fine), emit runs.
 */
export function wordDiff(oldText: string, newText: string): WordOp[] {
  const a = oldText.split(/(\s+)/).filter((t) => t !== '')
  const b = newText.split(/(\s+)/).filter((t) => t !== '')
  const n = a.length, m = b.length
  // dp[i][j] = LCS length of a[i..] vs b[j..]
  const dp: Uint32Array[] = []
  for (let i = 0; i <= n; i++) dp.push(new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const ops: WordOp[] = []
  let pendDel = '', pendAdd = ''
  const flush = () => {
    if (pendDel !== '' || pendAdd !== '') { ops.push({ del: pendDel || undefined, add: pendAdd || undefined }); pendDel = ''; pendAdd = '' }
  }
  let i = 0, j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { flush(); ops.push({ add: b[j] }); i++; j++; continue }
    if (dp[i + 1][j] >= dp[i][j + 1]) { pendDel += a[i]; i++ } else { pendAdd += b[j]; j++ }
  }
  while (i < n) pendDel += a[i++]
  while (j < m) pendAdd += b[j++]
  flush()
  return ops
}

/* ----------------------------------------------------------------- blocks */

export type PanelBlockStatus = 'added' | 'removed' | 'modified' | 'unchanged'

/** One renderable block = unit of diff mark, comment anchor, navigation. */
export interface PanelBlock {
  index: number
  /** knowledge block type, or 'table-cell' for a subdivided cell. */
  type: string
  level: number
  text: string
  status: PanelBlockStatus
  /** For table cells: row block index + column index within the row. */
  cell?: { row: number; col: number }
  /** modified blocks only: word-level runs (del = struck out, add = inserted). */
  inlineOps?: WordOp[]
  /** Anchor hash of the block text (both sides compute it the same way). */
  hash: string
  /** Snippet of the previous block — the neighbour fallback of requirement 7. */
  neighbour: string
}

/** One row of the diff face's doc-file blocks (host changes.ts BlockDiff shape). */
interface RawBlock {
  type?: unknown
  status?: unknown
  level?: unknown
  newText?: unknown
  oldText?: unknown
  summary?: unknown
}

const STATUSES: PanelBlockStatus[] = ['added', 'removed', 'modified', 'unchanged']

function cleanStatus(v: unknown): PanelBlockStatus {
  return STATUSES.includes(v as PanelBlockStatus) ? (v as PanelBlockStatus) : 'unchanged'
}

/** Split one markdown table row's text into cell texts (pipes trimmed; separator rows collapse to their head cell count). */
function splitCells(text: string): string[] {
  const line = text.split('\n')[0] ?? ''
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim())
}

/**
 * Build the panel blocks of one doc file from the diff face's blocks.
 * Table rows become per-cell blocks; a row whose cells differ between old and
 * new marks exactly the changed cells (unchanged cells stay unmarked), via the
 * same word-diff used for modified paragraphs.
 */
export function buildBlocks(rawBlocks: unknown): PanelBlock[] {
  if (!Array.isArray(rawBlocks)) return []
  const out: PanelBlock[] = []
  let neighbour = ''
  for (const raw of rawBlocks) {
    if (raw === null || typeof raw !== 'object') continue
    const r = raw as RawBlock
    const type = asStr(r.type, 40)
    if (type === '') continue
    const status = cleanStatus(r.status)
    // A heading without a level field defaults to h1 (malformed but usable);
    // non-headings keep level 0.
    const level = asNum(r.level) ?? (type === 'heading' ? 1 : 0)
    const oldText = asStr(r.oldText)
    const newText = asStr(r.newText)
    const text = status === 'removed' ? oldText : newText
    if (type === 'table-head' || type === 'table-row') {
      // Per-cell subdivision (ticket requirement 2). The parent row index is
      // the anchor index of the row block; cells carry their column.
      const oldCells = splitCells(oldText)
      const newCells = splitCells(newText)
      const cols = Math.max(oldCells.length, newCells.length)
      for (let c = 0; c < cols; c++) {
        const oc = oldCells[c] ?? ''
        const nc = newCells[c] ?? ''
        const cellStatus: PanelBlockStatus =
          status === 'added' ? 'added'
            : status === 'removed' ? 'removed'
              : oc !== nc ? 'modified' : 'unchanged'
        out.push({
          index: out.length,
          type: 'table-cell',
          level: 0,
          text: status === 'removed' ? oc : nc,
          status: cellStatus,
          cell: { row: out.length, col: c },
          inlineOps: cellStatus === 'modified' ? wordDiff(oc, nc) : undefined,
          hash: blockHash(status === 'removed' ? oc : nc),
          neighbour,
        })
      }
    } else {
      const ops = status === 'modified' && oldText !== '' ? wordDiff(oldText, newText) : undefined
      out.push({
        index: out.length,
        type,
        level,
        text,
        status,
        inlineOps: ops,
        hash: blockHash(text),
        neighbour,
      })
    }
    const summary = asStr(r.summary, 200)
    neighbour = summary !== '' ? summary : (out[out.length - 1]?.text ?? '').slice(0, 80)
  }
  return out
}

/* ---------------------------------------------------------------- threads */

/** One thread: root comment (parentId null) plus nested replies. */
export interface Thread {
  id: string
  parentId: string | null
  blockIndex: number
  hash: string
  neighbour: string
  author: string
  at: number
  text: string
  resolved: boolean
  replies: { author: string; at: number; text: string }[]
}

/**
 * Normalize whatever the lane file (or the network) carried into threads.
 * Unusable entries are skipped and counted — the count is surfaced, not silent.
 */
export function normalizeThreads(raw: unknown): { threads: Thread[]; dropped: number } {
  const threads: Thread[] = []
  let dropped = 0
  const arr = Array.isArray(raw) ? raw : []
  const seen = new Set<string>()
  for (const item of arr) {
    if (item === null || typeof item !== 'object') { dropped++; continue }
    const r = item as Record<string, unknown>
    const id = asStr(r.id, 200)
    const anchor = (r.anchor ?? {}) as Record<string, unknown>
    const blockIndex = asNum(anchor.index)
    if (id === '' || blockIndex === null || blockIndex < 0 || seen.has(id)) { dropped++; continue }
    seen.add(id)
    const replies: Thread['replies'] = []
    if (Array.isArray(r.replies)) {
      for (const rep of r.replies) {
        if (rep === null || typeof rep !== 'object') continue
        const rr = rep as Record<string, unknown>
        const text = asStr(rr.text)
        if (text === '') continue
        replies.push({ author: asStr(rr.author, 200), at: asNum(rr.at) ?? 0, text })
      }
    }
    threads.push({
      id,
      parentId: r.parentId === null || r.parentId === undefined ? null : asStr(r.parentId, 200) || null,
      blockIndex: Math.trunc(blockIndex),
      hash: asStr(anchor.hash, 200),
      neighbour: asStr(anchor.neighbour, 400),
      author: asStr(r.author, 200),
      at: asNum(r.at) ?? 0,
      text: asStr(r.text),
      resolved: r.resolved === true,
      replies,
    })
  }
  return { threads, dropped }
}

/** Threads whose anchor points at this block (resolved ones included — the badge needs both counts). */
export function threadsForBlock(threads: Thread[], blockIndex: number): Thread[] {
  return threads.filter((t) => t.blockIndex === blockIndex)
}

export function openCount(threads: Thread[], blockIndex: number): number {
  return threadsForBlock(threads, blockIndex).filter((t) => !t.resolved).length
}

/** Badge-grey rule (requirement 5): commented but every thread resolved. */
export function hasOnlyResolved(threads: Thread[], blockIndex: number): boolean {
  const ts = threadsForBlock(threads, blockIndex)
  return ts.length > 0 && ts.every((t) => t.resolved)
}

export type CommentFilter = 'open' | 'all' | 'resolved'

export function filterThreads(threads: Thread[], f: CommentFilter): Thread[] {
  if (f === 'open') return threads.filter((t) => !t.resolved)
  if (f === 'resolved') return threads.filter((t) => t.resolved)
  return threads
}

/* ----------------------------------------------------------- anchor logic */

export type AnchorResolution =
  | { kind: 'exact'; index: number }
  | { kind: 'neighbour'; index: number }
  | { kind: 'outdated' }

/**
 * Requirement 7: exact hash match first; otherwise index + neighbour fallback;
 * otherwise outdated. Never drops the thread — the caller renders outdated
 * threads at the end of the document.
 */
export function resolveAnchor(blocks: PanelBlock[], thread: Thread): AnchorResolution {
  for (const b of blocks) {
    if (b.hash !== '' && b.hash === thread.hash) return { kind: 'exact', index: b.index }
  }
  const at = blocks[thread.blockIndex]
  if (at !== undefined && thread.neighbour !== '' && at.neighbour === thread.neighbour) {
    return { kind: 'neighbour', index: at.index }
  }
  // neighbour snippet may also sit on the block ADJACENT to the recorded one
  // (an insert above shifts the index): probe ±1.
  const prev = blocks[thread.blockIndex - 1]
  const next = blocks[thread.blockIndex + 1]
  if (prev !== undefined && thread.neighbour !== '' && prev.neighbour === thread.neighbour) return { kind: 'neighbour', index: prev.index }
  if (next !== undefined && thread.neighbour !== '' && next.neighbour === thread.neighbour) return { kind: 'neighbour', index: next.index }
  return { kind: 'outdated' }
}

/** Resolve every thread against the current blocks; outdated ones go to the end, in order (requirement 7). */
export function placeThreads(blocks: PanelBlock[], threads: Thread[]): { index: number; thread: Thread; resolution: AnchorResolution }[] {
  const placed = threads.map((thread) => ({ thread, resolution: resolveAnchor(blocks, thread) }))
  const rank = (r: AnchorResolution) => (r.kind === 'exact' ? 0 : r.kind === 'neighbour' ? 1 : 2)
  return placed
    .map(({ thread, resolution }) => ({
      index: resolution.kind === 'outdated' ? blocks.length + rank(resolution) : resolution.index,
      thread,
      resolution,
    }))
    .sort((a, b) => a.index - b.index || (a.thread.at - b.thread.at))
}

/* ------------------------------------------------- store-record serialize */

/**
 * Serialize a model Thread into the STORE record shape the lane file carries
 * (arbitrate gen0 CF2: the panel must PUT `anchor:{index,hash,neighbour}` —
 * the model's flat `blockIndex/hash/neighbour` shape is model-internal and the
 * store's sanitizer rightly refuses it). This is the ONLY serialization seam:
 * persist() goes through it, so a panel write can never diverge from the
 * schema the lane agents read.
 */
export function toStoreThread(t: Thread): Record<string, unknown> {
  return {
    id: t.id,
    parentId: t.parentId,
    anchor: { index: t.blockIndex, hash: t.hash, neighbour: t.neighbour },
    author: t.author,
    at: t.at,
    text: t.text,
    resolved: t.resolved,
    replies: t.replies.map((r) => ({ at: r.at, author: r.author, text: r.text })),
  }
}

/* -------------------------------------------------------------- TOC + map */

export interface TocEntry { index: number; level: number; text: string }

/** h1/h2 entries in document order (requirement 1a / acceptance f). */
export function buildToc(blocks: PanelBlock[]): TocEntry[] {
  return blocks
    .filter((b) => b.type === 'heading' && (b.level === 1 || b.level === 2))
    .map((b) => ({ index: b.index, level: b.level, text: b.text.replace(/^#+\s*/, '').slice(0, 200) }))
}

/** One minimap mark (requirement 4): changed-block colour + open-comment count. */
export interface MinimapMark {
  index: number
  status: PanelBlockStatus
  open: number
  /** true when commented but every thread resolved → grey badge. */
  onlyResolved: boolean
}

export function buildMinimap(blocks: PanelBlock[], threads: Thread[]): MinimapMark[] {
  const marks: MinimapMark[] = []
  for (const b of blocks) {
    const open = openCount(threads, b.index)
    const commented = threadsForBlock(threads, b.index).length > 0
    if (b.status === 'unchanged' && !commented) continue
    marks.push({ index: b.index, status: b.status, open, onlyResolved: commented && open === 0 })
  }
  return marks
}
