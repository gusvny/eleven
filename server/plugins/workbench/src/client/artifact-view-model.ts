/**
 * artifact-view-model.ts — the six built-in artifact views (epic artifact-face, slice 3,
 * ticket t261030-36). ONE declared artifact, ONE body; the frame owns the row list, the
 * order, the byte link and the machine verdict.
 *
 * This module holds every decision. `artifact-view.tsx` is the React projection.
 * Pure: no React, no DOM, no node built-ins, so the L1 battery drives it directly.
 *
 * Reuse (one rule, one home):
 *   - the kind vocabulary is `ARTIFACT_KINDS` from the frame model (never a second list);
 *   - receipt-shaped ledger documents go through `buildChecksDetail` from `lane-map-model.ts`,
 *     the ONE gate-row reader (script `{check, level, count}` and agent `{item, by, done,
 *     green}` shapes; a conflicting row resolves red; no signal resolves red);
 *   - a unified diff goes through `parseUnifiedDiff` from `diff-rows-model.ts`; this module
 *     only splits a multi-file diff into files and clips the display.
 */

import {
  ARTIFACT_KINDS,
  type ArtifactViewRow,
} from './artifact-face-model.ts'
import { buildChecksDetail } from './lane-map-model.ts'
import { parseUnifiedDiff } from './diff-rows-model.ts'

/* ------------------------------------------------------------- view kinds */

/** The engine's built-in kind vocabulary, read from the frame model (one source). */
export type ViewKind = (typeof ARTIFACT_KINDS)[number]

export const VIEW_KINDS = ARTIFACT_KINDS

/** English titles (host order 260925: console copy is English). */
export const VIEW_TITLE: Record<ViewKind, string> = {
  image: 'Image',
  text: 'Text',
  structure: 'Structure',
  diff: 'Diff',
  ledger: 'Ledger',
  external: 'External',
}

/* --------------------------------------------------------------- body plan */

export type BodyRead = 'none' | 'image' | 'text'

export interface ArtifactBodyPlan {
  /** False = the frame's card stands alone; no view body, no read. */
  body: boolean
  /** 'text' = the body needs one byte read; 'image' = an <img> reads the link; 'none' = no read. */
  read: BodyRead
  /** The byte link (empty when the frame offers none). */
  href: string
  kind: ViewKind
  /** Metadata the plan was made from, carried so a face can label the body honestly. */
  title: string
  sizeText: string
  timeText: string
  state: string
  /** Why a body is not drawn, or why an image uses the external card. */
  why: string
}

/** One view: a single row (and the frame's byte link) in, one body plan out. */
export type ArtifactViewFn = (row: ArtifactViewRow, href?: string | null) => ArtifactBodyPlan

function blankPlan(kind: ViewKind, why: string): ArtifactBodyPlan {
  return { body: false, read: 'none', href: '', kind, title: '', sizeText: '', timeText: '', state: '', why }
}

function filledPlan(
  row: ArtifactViewRow, href: string | null | undefined, kind: ViewKind, read: BodyRead, why: string,
): ArtifactBodyPlan {
  return {
    body: true,
    read,
    href: typeof href === 'string' ? href : '',
    kind,
    title: row.title,
    sizeText: row.sizeText,
    timeText: row.timeText,
    state: row.state,
    why,
  }
}

/** The three refusals every view shares: a degraded row, no servable bytes, an unknown kind. */
function gate(row: ArtifactViewRow, kind: ViewKind): ArtifactBodyPlan | null {
  if (row === null || typeof row !== 'object') return blankPlan(kind, 'no row was supplied')
  if (row.card !== 'row') return blankPlan(kind, 'the frame marked this row degraded')
  if (row.bytesHref === null || row.bytesHref === '') {
    return blankPlan(kind, row.bytesRefusal || 'the frame offers no servable bytes')
  }
  if (row.kindKnown !== true) return blankPlan(kind, 'the kind is not recognized')
  return null
}

const viewImage: ArtifactViewFn = (row, href) => {
  const refused = gate(row, 'image')
  if (refused !== null) return refused
  return imageIsInline(row.source)
    ? filledPlan(row, href, 'image', 'image', '')
    : filledPlan(row, href, 'image', 'none', 'The host serves this image as a download, so the console shows its metadata.')
}
const viewText: ArtifactViewFn = (row, href) => gate(row, 'text') ?? filledPlan(row, href, 'text', 'text', '')
const viewStructure: ArtifactViewFn = (row, href) => gate(row, 'structure') ?? filledPlan(row, href, 'structure', 'text', '')
const viewDiff: ArtifactViewFn = (row, href) => gate(row, 'diff') ?? filledPlan(row, href, 'diff', 'text', '')
const viewLedger: ArtifactViewFn = (row, href) => gate(row, 'ledger') ?? filledPlan(row, href, 'ledger', 'text', '')
const viewExternal: ArtifactViewFn = (row, href) => gate(row, 'external') ?? filledPlan(row, href, 'external', 'none', '')

/** The built-in registry this slice ships; slice 6 will add project views beside it. */
export const ARTIFACT_VIEWS: Record<ViewKind, ArtifactViewFn> = {
  image: viewImage,
  text: viewText,
  structure: viewStructure,
  diff: viewDiff,
  ledger: viewLedger,
  external: viewExternal,
}

/**
 * Map a declared kind to its view. An unknown kind maps to the external view — the slice-6
 * registry contract. In this slice an unknown-kind row never reaches a view body: the frame
 * already drew its degrade card.
 */
export function resolveArtifactView(kind: unknown): ArtifactViewFn {
  const k = typeof kind === 'string' ? kind : ''
  return (VIEW_KINDS as readonly string[]).includes(k)
    ? ARTIFACT_VIEWS[k as ViewKind]
    : viewExternal
}

/**
 * THE render rule. `href` is the link the frame built for this row (the view never builds
 * one); it is optional because the rule also answers "does this row get a body at all",
 * which the frame's call site and this component both ask. Three row classes produce no
 * read at all: a degrade row, a row the frame marked `card === 'row'` but offered no
 * servable bytes for, and a non-inline image (the host serves SVG and unknown suffixes as a
 * download, so the image cannot be shown).
 */
export function planArtifactBody(row: ArtifactViewRow, href?: string | null): ArtifactBodyPlan {
  return resolveArtifactView(row === null || typeof row !== 'object' ? '' : row.kind)(row, href)
}

/** The gate the frame's call site and the component both use (defined from the plan). */
export function shouldRenderBody(row: ArtifactViewRow, href?: string | null): boolean {
  return planArtifactBody(row, href).body
}

/* ------------------------------------------------------------ suffix gates */

/** The suffixes the host serves inline as an image (mirrors `artifactContentType`). */
export const INLINE_IMAGE_SUFFIXES = ['.png', '.jpg', '.jpeg', '.webp', '.gif'] as const

/** Markdown documents (`classifyPath` in `src/host/changes.ts` uses the same set). */
export const MARKDOWN_SUFFIXES = ['.md', '.markdown'] as const

export function sourceSuffix(source: unknown): string {
  const s = typeof source === 'string' ? source.replace(/\\/g, '/') : ''
  const base = s.slice(s.lastIndexOf('/') + 1)
  const dot = base.lastIndexOf('.')
  return dot > 0 ? base.slice(dot).toLowerCase() : ''
}

export function imageIsInline(source: unknown): boolean {
  return (INLINE_IMAGE_SUFFIXES as readonly string[]).includes(sourceSuffix(source))
}

export function isMarkdownSource(source: unknown): boolean {
  return (MARKDOWN_SUFFIXES as readonly string[]).includes(sourceSuffix(source))
}

/* -------------------------------------------------------------- read path */

export interface ArtifactResponseLike {
  ok: boolean
  status: number
  headers?: { get(name: string): string | null }
  text(): Promise<string>
  json?(): Promise<unknown>
}

export type ArtifactFetch = (
  href: string,
  init: { method: string; signal?: AbortSignal; headers: Record<string, string> },
) => Promise<ArtifactResponseLike>

export type ReadFailureKind = 'http' | 'content-type' | 'network' | 'aborted'

export type ArtifactRead =
  | { ok: true; text: string }
  | { ok: false; kind: ReadFailureKind; status: number; message: string }

function errorText(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

function isAbort(err: unknown, signal?: AbortSignal): boolean {
  if (signal !== undefined && signal.aborted === true) return true
  return err instanceof Error && err.name === 'AbortError'
}

async function readErrorBody(res: ArtifactResponseLike): Promise<string> {
  if (typeof res.json !== 'function') return ''
  try {
    const body = await res.json()
    if (body !== null && typeof body === 'object') {
      const record = body as Record<string, unknown>
      const code = typeof record.code === 'string' ? record.code : ''
      const err = typeof record.error === 'string' ? record.error : ''
      if (code !== '' && err !== '') return `${code}: ${err}`
      if (code !== '') return code
      if (err !== '') return err
    }
  } catch { /* a non-JSON error body: the status line stands alone */ }
  return ''
}

/**
 * Read one artifact's text through the host's read-only route. Every failure is named:
 * an HTTP status (with the route's own `error` when it answers JSON), a non-text content
 * type, a network error, or an abort. Never throws.
 */
export async function readArtifactText(
  href: string,
  fetchImpl: ArtifactFetch,
  signal?: AbortSignal,
): Promise<ArtifactRead> {
  let res: ArtifactResponseLike
  try {
    res = await fetchImpl(href, { method: 'GET', signal, headers: { accept: 'text/plain' } })
  } catch (err) {
    if (isAbort(err, signal)) return { ok: false, kind: 'aborted', status: 0, message: 'The read was cancelled.' }
    return { ok: false, kind: 'network', status: 0, message: errorText(err) }
  }
  if (!res.ok) {
    const detail = await readErrorBody(res)
    return {
      ok: false,
      kind: 'http',
      status: res.status,
      message: `HTTP ${res.status}${detail === '' ? '' : `: ${detail}`}`,
    }
  }
  const contentType = (res.headers?.get('content-type') ?? '').toLowerCase()
  if (contentType !== '' && !contentType.startsWith('text/')) {
    return {
      ok: false,
      kind: 'content-type',
      status: res.status,
      message: `The host answered ${contentType}; the console reads text only.`,
    }
  }
  try {
    return { ok: true, text: await res.text() }
  } catch (err) {
    if (isAbort(err, signal)) return { ok: false, kind: 'aborted', status: 0, message: 'The read was cancelled.' }
    return { ok: false, kind: 'network', status: 0, message: errorText(err) }
  }
}

export type BodyReader = (href: string, signal?: AbortSignal) => Promise<ArtifactRead>

/**
 * The only read entry the component uses: a plan that does not need text returns null and
 * NEVER calls the reader (the zero-read rule for degrade, not-servable, external and image
 * rows).
 */
export async function runBodyRead(
  plan: ArtifactBodyPlan,
  read: BodyReader,
  signal?: AbortSignal,
): Promise<ArtifactRead | null> {
  if (plan === null || typeof plan !== 'object') return null
  if (plan.body !== true || plan.read !== 'text') return null
  return read(plan.href, signal)
}

/* ------------------------------------------------------------------ text */

export const TEXT_DISPLAY_MAX_CHARS = 200_000
export const TEXT_DISPLAY_MAX_LINES = 5_000
export const DIFF_DISPLAY_MAX_ROWS = 2_000
export const TABLE_DISPLAY_MAX_ROWS = 200
export const TABLE_DISPLAY_MAX_COLUMNS = 12
export const TREE_DISPLAY_MAX_NODES = 500
export const TREE_DISPLAY_MAX_DEPTH = 6
export const LEDGER_DISPLAY_MAX_ENTRIES = 500

export function textLooksBinary(text: unknown): boolean {
  if (typeof text !== 'string') return false
  // A NUL byte, or the decoder's replacement character: either way the console does not
  // print it as text.
  return text.includes('\u0000') || text.includes('\uFFFD')
}

export interface ClippedText {
  text: string
  lines: string[]
  truncated: boolean
  note: string
}

/** Clip text for the page and say that it is partial (the original stays one click away). */
export function clipText(
  text: string,
  maxChars: number = TEXT_DISPLAY_MAX_CHARS,
  maxLines: number = TEXT_DISPLAY_MAX_LINES,
): ClippedText {
  const src = typeof text === 'string' ? text : ''
  const totalLines = src === '' ? 0 : src.split('\n').length
  let shown = src
  let truncated = false
  if (shown.length > maxChars) { shown = shown.slice(0, maxChars); truncated = true }
  const lines = shown === '' ? [] : shown.split('\n')
  if (lines.length > maxLines) { lines.length = maxLines; truncated = true }
  return {
    text: lines.join('\n'),
    lines,
    truncated,
    note: truncated
      ? `Showing the first ${lines.length} of ${totalLines} lines; the original is one click away.`
      : '',
  }
}

export interface TextView {
  mode: 'markdown' | 'text'
  text: string
  note: string
}

export function buildTextView(text: string, source: unknown): TextView {
  const clip = clipText(text)
  return { mode: isMarkdownSource(source) ? 'markdown' : 'text', text: clip.text, note: clip.note }
}

/* ------------------------------------------------------------- structure */

export const STRUCTURE_KEYS = ['entries', 'items', 'rows', 'units', 'data'] as const

/** `units[]`, `data.items`, `$.rows[0].cells` -> path segments (a trailing `[]` is noise). */
export function parseShapePath(shape: unknown): string[] {
  const raw = typeof shape === 'string' ? shape.trim() : ''
  if (raw === '') return []
  const body = raw.startsWith('$.') ? raw.slice(2) : (raw.startsWith('$') ? raw.slice(1) : raw)
  return body.split('.')
    .map(seg => seg.replace(/\[\]$/, '').trim())
    .filter(seg => seg !== '')
}

export interface ShapeTarget {
  found: boolean
  value: unknown
}

export function readShapeTarget(doc: unknown, path: string[]): ShapeTarget {
  let cur: unknown = doc
  for (const seg of path) {
    if (cur === null || typeof cur !== 'object') return { found: false, value: undefined }
    if (Array.isArray(cur)) {
      const idx = /^\d+$/.test(seg) ? Number(seg) : -1
      if (idx < 0 || idx >= cur.length) return { found: false, value: undefined }
      cur = cur[idx]
    } else {
      const record = cur as Record<string, unknown>
      if (!Object.prototype.hasOwnProperty.call(record, seg)) return { found: false, value: undefined }
      cur = record[seg]
    }
  }
  return { found: true, value: cur }
}

export interface TreeNode {
  label: string
  value: string
  kind: 'scalar' | 'object' | 'array'
  depth: number
  children: TreeNode[]
}

export interface StructureTable {
  mode: 'table'
  columns: string[]
  rows: string[][]
  totalRows: number
  shownRows: number
  note: string
}

export interface StructureTree {
  mode: 'tree'
  nodes: TreeNode[]
  hidden: number
  note: string
}

export interface StructureLines {
  mode: 'lines'
  lines: string[]
  note: string
}

export interface StructureText {
  mode: 'text'
  text: string
  note: string
}

export type StructureBody = StructureTable | StructureTree | StructureLines | StructureText

function scalarText(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return ''
  if (typeof value === 'string') return value.length > 500 ? `${value.slice(0, 500)}…` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    const text = JSON.stringify(value)
    if (typeof text === 'string') return text.length > 200 ? `${text.slice(0, 200)}…` : text
  } catch { /* a value JSON cannot print (a cycle cannot come from JSON.parse) */ }
  return ''
}

function buildNode(
  label: string,
  value: unknown,
  depth: number,
  budget: { left: number },
): TreeNode | null {
  if (budget.left <= 0) return null
  budget.left -= 1
  if (value === null || typeof value !== 'object') {
    return { label, value: scalarText(value), kind: 'scalar', depth, children: [] }
  }
  const array = Array.isArray(value)
  const node: TreeNode = {
    label,
    value: array ? `[${(value as unknown[]).length}]` : '',
    kind: array ? 'array' : 'object',
    depth,
    children: [],
  }
  if (depth >= TREE_DISPLAY_MAX_DEPTH) return node
  const entries: ReadonlyArray<readonly [string, unknown]> = array
    ? (value as unknown[]).map((item, i) => [String(i), item] as const)
    : Object.entries(value as Record<string, unknown>)
  for (const [key, item] of entries) {
    const child = buildNode(key, item, depth + 1, budget)
    if (child === null) break
    node.children.push(child)
  }
  return node
}

function buildTree(value: unknown, note: string): StructureTree {
  if (value === null || typeof value !== 'object') {
    return {
      mode: 'tree',
      nodes: [{ label: 'value', value: scalarText(value), kind: 'scalar', depth: 0, children: [] }],
      hidden: 0,
      note,
    }
  }
  const budget = { left: TREE_DISPLAY_MAX_NODES }
  const entries: ReadonlyArray<readonly [string, unknown]> = Array.isArray(value)
    ? (value as unknown[]).map((item, i) => [String(i), item] as const)
    : Object.entries(value as Record<string, unknown>)
  const nodes: TreeNode[] = []
  let hidden = 0
  for (const [key, item] of entries) {
    const node = buildNode(key, item, 0, budget)
    if (node === null) { hidden += 1; continue }
    nodes.push(node)
  }
  return {
    mode: 'tree',
    nodes,
    hidden,
    note: note === ''
      ? (hidden > 0 ? `${hidden} more entries are not shown.` : '')
      : `${note}${hidden > 0 ? ` ${hidden} more entries are not shown.` : ''}`,
  }
}

function looksLikeRecord(value: unknown): boolean {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function buildTable(rows: unknown[], note: string): StructureTable {
  const totalRows = rows.length
  const records = rows.length > 0 && rows.every(looksLikeRecord)
  let columns: string[]
  if (records) {
    const seen: string[] = []
    for (const row of rows.slice(0, 20)) {
      for (const key of Object.keys(row as Record<string, unknown>)) {
        if (!seen.includes(key)) seen.push(key)
      }
    }
    columns = seen.slice(0, TABLE_DISPLAY_MAX_COLUMNS)
  } else {
    columns = ['value']
  }
  const shown = rows.slice(0, TABLE_DISPLAY_MAX_ROWS)
  const body = shown.map((row) => columns.map((column) => {
    if (!records) return scalarText(row)
    const record = row as Record<string, unknown>
    return Object.prototype.hasOwnProperty.call(record, column) ? scalarText(record[column]) : ''
  }))
  const notes: string[] = []
  if (note !== '') notes.push(note)
  if (records && rows.length > 0) {
    const seenCount = new Set(rows.slice(0, 20).flatMap(row => Object.keys(row as Record<string, unknown>))).size
    if (seenCount > TABLE_DISPLAY_MAX_COLUMNS) notes.push(`Showing the first ${columns.length} of ${seenCount} columns.`)
  }
  if (totalRows > shown.length) notes.push(`Showing the first ${shown.length} of ${totalRows} rows.`)
  return { mode: 'table', columns, rows: body, totalRows, shownRows: shown.length, note: notes.join(' ') }
}

function buildCsvTable(text: string): StructureBody {
  const parsed = parseCsvRows(text)
  if (parsed.ok !== true) {
    return { mode: 'text', text: clipText(text).text, note: `The CSV could not be read (${parsed.reason}); shown as text.` }
  }
  const rows = parsed.rows
  if (rows.length === 0) return { mode: 'text', text: '', note: 'The CSV is empty.' }
  const header = rows[0].map((cell, i) => cell.trim() !== '' ? cell.trim() : `column ${i + 1}`)
  const columns = header.slice(0, TABLE_DISPLAY_MAX_COLUMNS)
  const body = rows.slice(1)
  const ragged = body.filter(row => row.length !== header.length).length
  const shown = body.slice(0, TABLE_DISPLAY_MAX_ROWS).map(row => columns.map((_, i) => scalarText(row[i] ?? '')))
  const notes: string[] = []
  if (header.length > columns.length) notes.push(`Showing the first ${columns.length} of ${header.length} columns.`)
  if (body.length > shown.length) notes.push(`Showing the first ${shown.length} of ${body.length} rows.`)
  if (ragged > 0) notes.push(`${ragged} rows have a different column count; missing cells are blank.`)
  return { mode: 'table', columns, rows: shown, totalRows: body.length, shownRows: shown.length, note: notes.join(' ') }
}

export function parseCsvRows(text: string): { ok: true; rows: string[][] } | { ok: false; reason: string } {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  const src = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i]
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') { field += '"'; i += 1 }
        else inQuotes = false
      } else field += ch
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      row.push(field); field = ''
    } else if (ch === '\n') {
      row.push(field); rows.push(row); row = []; field = ''
    } else field += ch
  }
  if (inQuotes) return { ok: false, reason: 'the text ends inside a quoted field' }
  row.push(field)
  rows.push(row)
  if (rows.length > 1 && rows[rows.length - 1].length === 1 && rows[rows.length - 1][0] === '') rows.pop()
  return { ok: true, rows }
}

export function buildStructureView(text: string, source: unknown, shape: unknown): StructureBody {
  const src = typeof text === 'string' ? text : ''
  if (src.trim() === '') return { mode: 'text', text: '', note: 'The file is empty.' }
  const suffix = sourceSuffix(source)
  if (suffix === '.json') {
    let doc: unknown
    try {
      doc = JSON.parse(src)
    } catch (err) {
      return { mode: 'text', text: clipText(src).text, note: `Not valid JSON (${errorText(err)}); shown as text.` }
    }
    const path = parseShapePath(shape)
    if (path.length > 0) {
      const hit = readShapeTarget(doc, path)
      if (hit.found !== true) {
        return buildTree(doc, `Shape '${path.join('.')}' was not found; showing the whole document.`)
      }
      if (Array.isArray(hit.value)) return buildTable(hit.value, `Shape '${path.join('.')}' is the main table.`)
      if (looksLikeRecord(hit.value)) return buildTree(hit.value, `Shape '${path.join('.')}' resolved to an object; shown as a tree.`)
      return buildTree(doc, `Shape '${path.join('.')}' names a scalar; showing the whole document.`)
    }
    return buildTree(doc, '')
  }
  if (suffix === '.csv') return buildCsvTable(src)
  if (suffix === '.yaml' || suffix === '.yml' || suffix === '.toml') {
    const clip = clipText(src)
    return { mode: 'lines', lines: clip.lines, note: `Shown as indented text (the console has no ${suffix.slice(1).toUpperCase()} parser).${clip.note === '' ? '' : ` ${clip.note}`}` }
  }
  const clip = clipText(src)
  return { mode: 'text', text: clip.text, note: `The console cannot read this as structured data; shown as text.${clip.note === '' ? '' : ` ${clip.note}`}` }
}

/* ------------------------------------------------------------------ diff */

export interface DiffLineView {
  kind: 'context' | 'added' | 'removed'
  text: string
  oldLine: number | null
  newLine: number | null
}

export interface DiffHunkView {
  label: string
  lines: DiffLineView[]
  truncated: boolean
}

export interface DiffFileView {
  name: string
  hunks: DiffHunkView[]
  added: number
  removed: number
  note: string
}

export type DiffBody =
  | { mode: 'diff'; files: DiffFileView[]; added: number; removed: number; note: string }
  | { mode: 'text'; text: string; note: string }

function diffChunks(text: string): { name: string; text: string }[] {
  const lines = text.split('\n')
  const chunks: { name: string; lines: string[] }[] = []
  let current: { name: string; lines: string[] } | null = null
  for (const line of lines) {
    if (line.startsWith('diff --git ')) {
      current = { name: '', lines: [line] }
      chunks.push(current)
      continue
    }
    if (current === null) { current = { name: '', lines: [] }; chunks.push(current) }
    current.lines.push(line)
  }
  return chunks.map((chunk) => {
    let name = ''
    const header = chunk.lines.find(l => l.startsWith('diff --git '))
    if (header !== undefined) {
      const m = /\sb\/(.+)$/.exec(header)
      if (m !== null) name = m[1].trim()
    }
    if (name === '') {
      const plus = chunk.lines.find(l => l.startsWith('+++ '))
      if (plus !== undefined && !plus.startsWith('+++ /dev/null')) {
        name = plus.slice(4).replace(/^[ab]\//, '').trim()
      }
    }
    return { name: name === '' ? '(diff)' : name, text: chunk.lines.join('\n') }
  })
}

/**
 * Build the diff body. A multi-file diff is parsed one file at a time, so each file keeps
 * its own hunks and counts. A text that contains no readable hunk falls back to a named
 * text body (never a blank panel).
 */
export function buildDiffView(text: string): DiffBody {
  const src = typeof text === 'string' ? text : ''
  if (src.trim() === '') return { mode: 'text', text: '', note: 'The diff is empty.' }
  const chunks = diffChunks(src)
  const files: DiffFileView[] = []
  let added = 0
  let removed = 0
  let rowsLeft = DIFF_DISPLAY_MAX_ROWS
  let anyRow = false
  let truncationNoted = false
  const notes: string[] = []
  for (const chunk of chunks) {
    const parsed = parseUnifiedDiff(chunk.text)
    if (parsed.ok !== true) {
      files.push({ name: chunk.name, hunks: [], added: 0, removed: 0, note: `${parsed.state}: ${parsed.reason}` })
      continue
    }
    added += parsed.added
    removed += parsed.removed
    const hunks: DiffHunkView[] = []
    for (const hunk of parsed.hunks) {
      const slice = parsed.rows.slice(hunk.firstRow, hunk.firstRow + hunk.rowCount)
      const lines: DiffLineView[] = []
      let truncated = false
      for (const row of slice) {
        if (rowsLeft <= 0) { truncated = true; break }
        rowsLeft -= 1
        lines.push({ kind: row.kind, text: row.text, oldLine: row.oldLine, newLine: row.newLine })
      }
      if (lines.length > 0) anyRow = true
      if (truncated && !truncationNoted) {
        truncationNoted = true
        notes.push('Showing the first rows only; the original is one click away.')
      }
      hunks.push({ label: hunk.label, lines, truncated })
    }
    files.push({ name: chunk.name, hunks, added: parsed.added, removed: parsed.removed, note: parsed.skipped > 0 ? `${parsed.skipped} lines were skipped as preamble or noise.` : '' })
  }
  if (!anyRow) {
    const reason = files.map(f => `${f.name}: ${f.note}`).filter(x => x !== '').join('; ')
    return { mode: 'text', text: clipText(src).text, note: `Not a readable unified diff (${reason === '' ? 'no hunk and no changed line' : reason}); shown as text.` }
  }
  const head: string[] = []
  if (files.length > 1) head.push(`${files.length} files.`)
  head.push(...notes)
  return { mode: 'diff', files, added, removed, note: head.join(' ') }
}

/* ---------------------------------------------------------------- ledger */

export type LedgerColor = 'green' | 'red' | 'neutral'

export interface LedgerEntryView {
  name: string
  color: LedgerColor
  detail: string
  note: string
  count: string
}

export interface LedgerRunView {
  label: string
  verdict: 'green' | 'red' | 'none'
  disagreement: boolean
  redCount: number
  entries: LedgerEntryView[]
}

export type LedgerBody =
  | { mode: 'receipt'; runs: LedgerRunView[]; green: number; red: number; neutral: number; note: string }
  | { mode: 'generic'; entries: LedgerEntryView[]; green: number; red: number; neutral: number; note: string }
  | { mode: 'text'; text: string; note: string }

const GREEN_WORDS = new Set(['ok', 'pass', 'passed', 'green', 'success', 'succeeded', 'true', 'yes', 'done'])
const RED_WORDS = new Set(['fail', 'failed', 'red', 'error', 'false', 'no', 'blocked'])

/** Map a declared status to a color. An unknown or absent status is neutral, never green. */
export function ledgerColor(status: unknown): LedgerColor {
  if (status === true) return 'green'
  if (status === false) return 'red'
  if (typeof status !== 'string') return 'neutral'
  const word = status.trim().toLowerCase()
  if (GREEN_WORDS.has(word)) return 'green'
  if (RED_WORDS.has(word)) return 'red'
  return 'neutral'
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function statusOf(record: Record<string, unknown>): unknown {
  for (const key of ['status', 'state', 'result', 'ok', 'pass', 'green', 'done']) {
    if (Object.prototype.hasOwnProperty.call(record, key)) return record[key]
  }
  return undefined
}

const LEDGER_NOTE = 'Entries read from this artifact; the frame header carries the ticket machine verdict.'

/**
 * Receipt-shaped ledger documents go through the ONE gate-row reader
 * (`buildChecksDetail`): both real shapes, the conflict rule and the no-signal rule stay
 * in one place. The run label is the artifact's own; a run without a name is named
 * "artifact" for display only.
 */
function receiptBody(runsRaw: unknown[]): LedgerBody {
  const runs = runsRaw
    .filter((run): run is Record<string, unknown> => run !== null && typeof run === 'object' && !Array.isArray(run))
    .map(run => ({
      ...run,
      stage: asString(run.stage) || asString(run.label) || 'artifact',
    }))
  const views = buildChecksDetail({ gate_runs: runs })
  const out: LedgerRunView[] = []
  let green = 0
  let red = 0
  for (const view of views) {
    const entries: LedgerEntryView[] = view.rows.map((row) => {
      if (row.green) green += 1
      else red += 1
      return {
        name: row.item,
        color: row.green ? 'green' : 'red',
        detail: row.detail ?? '',
        note: row.note ?? '',
        count: row.count === undefined ? '' : String(row.count),
      }
    })
    const verdict: LedgerRunView['verdict'] = view.verdictSource === 'rows' && view.rows.length === 0
      ? 'none'
      : (view.green ? 'green' : 'red')
    out.push({ label: view.label, verdict, disagreement: view.disagreement, redCount: view.redCount, entries })
  }
  return { mode: 'receipt', runs: out, green, red, neutral: 0, note: LEDGER_NOTE }
}

function genericBody(list: unknown[]): LedgerBody {
  const shown = list.slice(0, LEDGER_DISPLAY_MAX_ENTRIES)
  let green = 0
  let red = 0
  let neutral = 0
  const entries: LedgerEntryView[] = shown.map((raw, i) => {
    const record = raw !== null && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : null
    const name = record === null
      ? scalarText(raw) || `entry ${i + 1}`
      : (asString(record.name) || asString(record.title) || asString(record.label)
        || asString(record.id) || asString(record.key) || `entry ${i + 1}`)
    const color = record === null ? 'neutral' : ledgerColor(statusOf(record))
    if (color === 'green') green += 1
    else if (color === 'red') red += 1
    else neutral += 1
    return {
      name,
      color,
      detail: record === null ? '' : (asString(record.detail) || asString(record.note) || asString(record.message)),
      note: record === null ? '' : asString(record.note),
      count: record !== null && typeof record.count === 'number' && Number.isFinite(record.count)
        ? String(record.count)
        : '',
    }
  })
  const hidden = list.length - shown.length
  return {
    mode: 'generic',
    entries,
    green,
    red,
    neutral,
    note: hidden > 0
      ? `${LEDGER_NOTE} Showing the first ${shown.length} of ${list.length} entries.`
      : LEDGER_NOTE,
  }
}

export function buildLedgerView(text: string, shape: unknown): LedgerBody {
  const src = typeof text === 'string' ? text : ''
  if (src.trim() === '') return { mode: 'text', text: '', note: 'The ledger is empty.' }
  let doc: unknown
  try {
    doc = JSON.parse(src)
  } catch (err) {
    return { mode: 'text', text: clipText(src).text, note: `Not valid JSON (${errorText(err)}); shown as text.` }
  }
  if (Array.isArray(doc)) return genericBody(doc)
  if (doc !== null && typeof doc === 'object') {
    const record = doc as Record<string, unknown>
    if (Array.isArray(record.checks)) return receiptBody([record])
    if (Array.isArray(record.runs)) return receiptBody(record.runs)
    const path = parseShapePath(shape)
    if (path.length > 0) {
      const hit = readShapeTarget(record, path)
      if (hit.found === true && Array.isArray(hit.value)) return genericBody(hit.value)
    }
    for (const key of STRUCTURE_KEYS) {
      const value = record[key]
      if (Array.isArray(value)) return genericBody(value)
    }
    return { mode: 'text', text: clipText(src).text, note: 'The ledger shape is not recognized; shown as text.' }
  }
  return { mode: 'text', text: clipText(src).text, note: 'The ledger is a scalar; shown as text.' }
}
