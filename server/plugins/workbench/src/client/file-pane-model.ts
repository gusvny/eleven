/**
 * file-pane-model.ts — pure rules for the middle-column file pane (t261102-09).
 *
 * The ticket takes over text-file links from the right-column chat: an
 * extension-band tab type claims `dsh-resource://file/**` for text-like paths,
 * its body forwards the file to the middle column, and the pane reads the bytes
 * through one guarded route. This module holds every rule that decision needs,
 * so the rules run under plain node (type stripping), with no React and no DOM:
 *
 *   - the address grammar (a mirror, see the note below);
 *   - the claim rule (which paths the extension band takes over);
 *   - the text kind, the title, line numbering and line clamping;
 *   - the refusal wording (a failure always names the path and the reason);
 *   - the structural shapes of the two dsh faces the plugin reads through
 *     `ctx.get`, kept here so no module augmentation is needed.
 *
 * Address grammar note: `@deepseek-ai/dsh-util-workspace-path` owns the grammar,
 * but this build externalizes every `@deepseek-ai/*` package and dsh inlines
 * that helper into its own bundles, so it is not on the platform module table.
 * The grammar is mirrored here, and the claim test pins both scopes, the
 * percent-encoded segments, the drive letter, the UNC form and the malformed
 * inputs.
 */

/* ------------------------------------------------------------ address */

/** Scheme and type every file address opens with (mirrors the dsh helper). */
const FILE_ADDRESS_PREFIX = 'dsh-resource://file/'

/** One parsed file address. `sessionId` is empty for the absolute scope. */
export interface FileAddress {
  scope: 'session' | 'absolute'
  sessionId: string
  /** Absolute, or relative to the session workspace root when the scope is session. */
  path: string
}

/**
 * Read a `dsh-resource://file/…` address into its parts.
 * @param address - a candidate address (untrusted: it arrives from a tab record).
 * @returns the parts, or null when the string is not a file address in a known
 *   scope, has no path, or carries a segment that is not validly encoded.
 */
export function parseFileAddress(address: unknown): FileAddress | null {
  if (typeof address !== 'string') return null
  if (!address.startsWith(FILE_ADDRESS_PREFIX)) return null
  const end = address.search(/[?#]/)
  const segments = address.slice(FILE_ADDRESS_PREFIX.length, end === -1 ? undefined : end).split('/')
  const scope = segments[0]
  try {
    if (scope === 'session') {
      const id = segments[1]
      const rest = segments.slice(2)
      if (id === undefined || id === '' || rest.length === 0) return null
      return { scope: 'session', sessionId: decodeURIComponent(id), path: rest.map(decodeURIComponent).join('/') }
    }
    if (scope === 'absolute') {
      const tail = segments.slice(1)
      const unc = tail[0] === '' && tail.length > 1
      const parts = (unc ? tail.slice(1) : tail).map(decodeURIComponent)
      if (parts.length === 0 || parts[0] === '') return null
      if (unc) return { scope: 'absolute', sessionId: '', path: `//${parts.join('/')}` }
      const joined = parts.join('/')
      return { scope: 'absolute', sessionId: '', path: /^[A-Za-z]:$/.test(parts[0]) ? joined : `/${joined}` }
    }
  } catch {
    // A segment that is not validly encoded is not an address this pane opens.
    return null
  }
  return null
}

/** Last path segment of a path or address, decoded when possible. */
function baseNameOf(path: string): string {
  const cut = path.replace(/\\/g, '/')
  const name = cut.slice(cut.lastIndexOf('/') + 1)
  if (name === '') return ''
  try {
    return decodeURIComponent(name)
  } catch {
    return name
  }
}

/**
 * The tab chip text for one address.
 * @param address - a candidate address (untrusted).
 * @returns the decoded basename, or the address itself when it has none.
 */
export function fileTitleOf(address: unknown): string {
  const parsed = parseFileAddress(address)
  if (parsed === null) return typeof address === 'string' ? address : 'file'
  const name = baseNameOf(parsed.path)
  return name === '' ? (typeof address === 'string' ? address : 'file') : name
}

/* ------------------------------------------------------------ claim rule */

/** Lower-case extension of a path, without the dot; '' when the path has none. */
export function extensionOf(path: unknown): string {
  if (typeof path !== 'string') return ''
  const name = path.replace(/\\/g, '/').slice(path.replace(/\\/g, '/').lastIndexOf('/') + 1)
  const dot = name.lastIndexOf('.')
  if (dot <= 0 || dot === name.length - 1) return ''
  return name.slice(dot + 1).toLowerCase()
}

const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown', 'mdx'])

const PLAIN_EXTENSIONS = new Set(['txt', 'log', 'csv', 'tsv', 'ini', 'conf', 'rst'])

const DATA_EXTENSIONS = new Set(['json', 'jsonc', 'jsonl', 'yaml', 'yml', 'toml'])

const SOURCE_EXTENSIONS = new Set([
  'ts', 'tsx', 'mts', 'cts', 'js', 'jsx', 'mjs', 'cjs', 'py', 'sh', 'bash', 'zsh',
  'go', 'rs', 'java', 'c', 'h', 'cpp', 'hpp', 'cs', 'kt', 'kts', 'rb', 'php', 'sql',
  'css', 'scss', 'patch', 'diff',
])

/** Every extension the extension band takes over (the claim table of the plan). */
export const CLAIMED_EXTENSIONS: readonly string[] = [
  ...MARKDOWN_EXTENSIONS, ...PLAIN_EXTENSIONS, ...DATA_EXTENSIONS, ...SOURCE_EXTENSIONS,
]

/**
 * Whether the extension band takes over one address (the tab type's `canOpen`).
 *
 * Text-like paths only. An image, PDF or HTML path returns false, which leaves
 * the address to the builtin preview exactly as it is today. An address the
 * grammar rejects returns false too, so it falls back instead of throwing in the
 * tab slot.
 * @param address - the address a caller wants opened.
 * @returns whether this type claims it.
 */
export function claimsTextFile(address: unknown): boolean {
  const parsed = parseFileAddress(address)
  if (parsed === null) return false
  if (parsed.path === '') return false
  const ext = extensionOf(parsed.path)
  return ext !== '' && CLAIMED_EXTENSIONS.includes(ext)
}

/** How a claimed path renders: rendered markdown, or plain source text. */
export type TextKind = 'markdown' | 'plain'

/**
 * The render kind of one path.
 * @param path - a path inside an address, or a plain path.
 * @returns 'markdown' for a markdown suffix, 'plain' for everything else.
 */
export function textKindOf(path: unknown): TextKind {
  return MARKDOWN_EXTENSIONS.has(extensionOf(path)) ? 'markdown' : 'plain'
}

/* ------------------------------------------------------------ lines */

/**
 * Rows the source view renders at most.
 *
 * The read face caps a file at 1 MiB, which can still be tens of thousands of rows;
 * rendering them all would freeze the column. The pane renders this many and NAMES the
 * clip on screen, so a long file is never silently cut.
 */
export const SOURCE_ROW_LIMIT = 5000

/**
 * Split file content into display rows, without one trailing empty row.
 * @param content - the file text.
 * @returns the rows; an empty file has one empty row, so a number still shows.
 */
export function numberedLines(content: unknown): string[] {
  const text = typeof content === 'string' ? content : ''
  const rows = text.split('\n')
  if (rows.length > 1 && rows[rows.length - 1] === '') rows.pop()
  return rows.length === 0 ? [''] : rows
}

/**
 * What the source view shows for one file: the rows, the true row count, and whether the
 * row cap actually dropped anything.
 *
 * The clip note is driven by THIS decision, not by a byte or line count from the read
 * face: the host counts physical lines (`content.split('\n').length`, which counts the
 * empty tail a file ending in a newline produces), while the view drops that tail — so
 * comparing the two numbers announced "showing the first 2 of 3 lines" for an ordinary
 * two-line file. Rows dropped is the only question the note answers.
 * @param content - the file text (untrusted).
 * @returns the rendered rows, the true row count, and whether rows were dropped.
 */
export interface SourceRows {
  rows: string[]
  total: number
  clipped: boolean
}

export function planSourceRows(content: unknown): SourceRows {
  const all = numberedLines(content)
  const total = all.length
  if (total > SOURCE_ROW_LIMIT) {
    return { rows: all.slice(0, SOURCE_ROW_LIMIT), total, clipped: true }
  }
  return { rows: all, total, clipped: false }
}

/**
 * Clamp a requested line to a row that exists.
 * @param line - the requested line (untrusted: a tab param).
 * @param lineCount - the number of rows the content produced.
 * @returns a 1-based row, or 0 for "no line" (absent, malformed, or no content).
 */
export function clampLine(line: unknown, lineCount: unknown): number {
  const wanted = typeof line === 'number' ? line : typeof line === 'string' && line.trim() !== '' ? Number(line) : NaN
  const total = typeof lineCount === 'number' && Number.isFinite(lineCount) ? Math.floor(lineCount) : 0
  if (!Number.isFinite(wanted) || total < 1) return 0
  const row = Math.floor(wanted)
  if (row < 1) return 0
  return row > total ? total : row
}

/**
 * The line note the sheet shows, and the row to reveal.
 *
 * Same truthfulness rule as the clip note: a request past the last row says so ("line 999
 * is past the end of this file (2 lines)") instead of quietly presenting the last row as
 * if it were the requested one.
 */
export interface LineNote {
  /** The 1-based row to reveal. */
  row: number
  /** The text the title area shows. */
  text: string
}

/**
 * Decide the line note for one request.
 * @param requested - the requested line (untrusted).
 * @param rowCount - the rows the view actually rendered.
 * @returns the note and the row to reveal, or null when no line applies.
 */
export function lineNoteOf(requested: unknown, rowCount: unknown): LineNote | null {
  const row = clampLine(requested, rowCount)
  if (row < 1) return null
  const total = typeof rowCount === 'number' && Number.isFinite(rowCount) ? Math.floor(rowCount) : 0
  const wanted = typeof requested === 'number' ? requested : typeof requested === 'string' && requested.trim() !== '' ? Number(requested) : NaN
  if (Number.isFinite(wanted) && Math.floor(wanted) > total) {
    return { row: total, text: `line ${Math.floor(wanted)} is past the end of this file (${total} line${total === 1 ? '' : 's'})` }
  }
  return { row, text: `line ${row}` }
}

/**
 * The line a tab navigation carries.
 * @param params - `tab.navigation.params` (untrusted).
 * @returns the line when it is a positive integer, else 0.
 */
export function lineOfParams(params: unknown): number {
  if (typeof params !== 'object' || params === null) return 0
  const raw = (params as { line?: unknown }).line
  return typeof raw === 'number' && Number.isFinite(raw) && raw >= 1 ? Math.floor(raw) : 0
}

/**
 * Which view a request opens in.
 *
 * A line-carrying request opens the SOURCE view for every claimed kind, so the
 * line always lands somewhere visible; markdown without a line opens rendered.
 * @param kind - the render kind of the path.
 * @param line - the requested line, 0 for none.
 * @returns the view to open.
 */
export function initialViewKind(kind: TextKind, line: number): 'rendered' | 'source' {
  if (line >= 1) return 'source'
  return kind === 'markdown' ? 'rendered' : 'source'
}

/* ------------------------------------------------------------ refusal wording */

const REASON_TEXT: Record<string, string> = {
  'outside-roots': 'the path is outside every registered project directory',
  'not-found': 'the file does not exist',
  'is-directory': 'the path is a directory, not a file',
  'too-large': 'the file is larger than the 1 MiB read limit',
  'not-utf8': 'the file is not UTF-8 text',
  unreadable: 'the file could not be read',
  'no-registered-roots': 'no registered project directory is available',
  'session-workspace-unknown': 'the session workspace cannot be resolved',
  'bad-path': 'the path parameter is missing or malformed',
  'bad-session': 'the session parameter is malformed',
  address: 'the address cannot be parsed',
}

/**
 * One refusal line: the path, then the reason. Never an empty pane.
 * @param reason - the stable reason code the route answered.
 * @param path - the path the person asked for.
 * @param detail - optional extra words from the server (its own message).
 * @returns a single human line naming both facts.
 */
export function fileRefusalLine(reason: unknown, path: unknown, detail?: unknown): string {
  const code = typeof reason === 'string' && Object.prototype.hasOwnProperty.call(REASON_TEXT, reason) ? reason : 'unreadable'
  const shown = typeof path === 'string' && path !== '' ? path : '(no path)'
  const text = REASON_TEXT[code]
  const extra = typeof detail === 'string' && detail !== '' ? ` — ${detail}` : ''
  return `Cannot open ${shown}: ${text}${extra}`
}

/**
 * Turn a failed read answer into a named reason and message.
 *
 * A route that is not served at all answers with something that is not JSON
 * (the console runs old code after a client rebuild: KI-052). That case gets its
 * own name and its own hint, never a generic network error.
 * @param status - the HTTP status the fetch resolved with.
 * @param bodyText - the raw response text.
 * @param path - the requested path, for the message.
 * @returns the reason code and the message to show.
 */
export function describeReadFailure(status: unknown, bodyText: unknown, path: unknown): { reason: string; message: string } {
  const code = typeof status === 'number' && Number.isFinite(status) ? status : 0
  let body: unknown = null
  try {
    body = typeof bodyText === 'string' && bodyText !== '' ? JSON.parse(bodyText) : null
  } catch {
    body = null
  }
  const answer = typeof body === 'object' && body !== null ? body as Record<string, unknown> : null
  if (answer !== null && answer.ok === false) {
    const reason = typeof answer.reason === 'string' && answer.reason !== '' ? answer.reason : 'unreadable'
    const detail = typeof answer.error === 'string' ? answer.error : ''
    return { reason, message: fileRefusalLine(reason, typeof answer.path === 'string' && answer.path !== '' ? answer.path : path, detail) }
  }
  if (code === 404) {
    return {
      reason: 'route-missing',
      message: `Cannot open ${typeof path === 'string' && path !== '' ? path : '(no path)'}: the file route is not served — the console may run old code, restart it.`,
    }
  }
  return {
    reason: code === 0 ? 'network' : `http-${code}`,
    message: `Cannot open ${typeof path === 'string' && path !== '' ? path : '(no path)'}: the read answered ${code === 0 ? 'nothing' : `HTTP ${code}`}.`,
  }
}

/* ------------------------------------------------------------ dsh faces (structural) */

/** One tab type registration, as `ctx.sidebarRightTabs.register` takes it. */
export interface TabKindDefinition {
  id: string
  kind: string
  patterns?: readonly string[]
  priority?: 'extension' | 'builtin' | 'fallback'
  canOpen?: (address: string) => boolean
  title?: (address: string) => string
}

/** The tab-type registry face, reached through `ctx.get('sidebarRightTabs')`. */
export interface TabKindRegistry {
  register(definition: TabKindDefinition): () => void
}

/** The column navigation face, reached through `ctx.get('sidebarRight')`. */
export interface SidebarColumnFace {
  isExpanded(): boolean
  active(): { id?: unknown } | undefined
  toggleExpanded(): void
}

/** What a tab body reads about its own tab. */
export interface TabInfoLike {
  tab?: {
    id?: unknown
    contentId?: unknown
    navigation?: { params?: unknown; revision?: number }
    actions?: { close?: () => void }
  }
}

/** The injected tab-info hook (a pass-through of the slot framework's own). */
export type TabInfoHook = () => TabInfoLike
