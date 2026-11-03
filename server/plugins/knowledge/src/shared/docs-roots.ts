/**
 * docs-roots.ts — the TypeScript side of the ONE documentation-root declaration and
 * resolution (design docs/design/project-docs-roots-v1.md; ticket t261103-12, the
 * index + presentation half).
 *
 * One declaration, one resolution, two runtimes. The declaration is `paths.docs_roots`
 * inside the project declaration the engine and the console already read
 * (`<projects root>/<key>/project.yaml`):
 *
 *   paths:
 *     docs_roots:
 *       - repository: .
 *         path: docs
 *         projections: entries,fulltext      # optional, per root, default none
 *
 * `repository` is a repository of the project, written relative to the project root
 * (the registry entry's first `dirs` item); `.` (or an empty value) is the project root
 * itself. `path` is the documentation root inside that repository: a relative posix
 * path, no `..`, no leading or trailing slash. The block lives inside `paths:` on
 * purpose: both registry loaders already pass that whole section through, so a
 * declaring project stays a loadable, visible project.
 *
 * The rules below are the same rules `server/engine/docs_roots.py` implements (the gate
 * half owns that module; this half extends it with the project-wide scope the console
 * needs). Same declaration bytes, same field names, same validation, same refusal codes
 * and wording — the engine reads the file through its resolver and the web views read
 * the same file through this module, so the gates and the console can never disagree
 * about where a project's documents live.
 *
 * Scope: a gate asks "which declared roots live in THIS repository"
 * (`docs_roots.resolve(tree=...)`); the documents view is per PROJECT and shows the
 * merged set of its roots (design goal 8), which is what `resolveDocsRoots` answers.
 *
 * The derived index states (design goal 6) and their copy live here too, spelled once
 * for both web consumers: absent / stale (with the last build time) / failed (with its
 * reason) / current. A reader never writes: this module only reads and stats.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { docTitleOf, isSafeDocRel, parseFrontmatter } from '../../../workbench/src/shared/docs-model.ts'

/* ---------------------------------------------------------------- the declaration */

/** The `paths:` key this face owns inside a project declaration. */
export const SECTION_KEY = 'docs_roots'
/** The fully qualified name used in refusal wording (what to go and edit). */
export const SECTION_LABEL = 'paths.docs_roots'
/** The implied default root: a project that declares nothing and owns this directory at
 *  its repository root behaves exactly as it did before the rule. */
export const IMPLIED_ROOT = 'docs'
/** The keys an entry must carry. */
export const ENTRY_KEYS: readonly string[] = ['repository', 'path']
/** The optional per-entry key declaring the LLM-facing projection for that root. */
export const ENTRY_OPTIONAL_KEYS: readonly string[] = ['projections']
/** The projection vocabulary; never an engine default. */
export const PROJECTION_VOCAB: readonly string[] = ['entries', 'fulltext']
export const PROJECTS_DIR_ENV = 'SANDBAR_PROJECTS_DIR'

/** The named refusal codes (identical to the engine resolver's). */
export const STOP = {
  declarationMalformed: 'docs_roots_declaration_malformed',
  declarationUnreadable: 'docs_roots_declaration_unreadable',
  duplicate: 'docs_roots_duplicate',
  absent: 'docs_roots_absent',
  rootAbsent: 'docs_roots_root_absent',
  rootUnreadable: 'docs_roots_root_unreadable',
  repositoryUnknown: 'docs_roots_repository_unknown',
  rootAmbiguous: 'docs_roots_root_ambiguous',
} as const

export type RootState = 'served' | 'empty'

export interface DocsRootEntry {
  repository: string
  path: string
  projections: string[]
}

export interface ResolvedRoot {
  /** Stable identity: repository + root path (two roots may hold the same rel path). */
  id: string
  /** The declared repository, relative to the project root ('.' = the project root). */
  repository: string
  /** The repository's absolute directory (what a git command or a walk starts from). */
  repoDir: string
  path: string
  /** The root's absolute directory. */
  directory: string
  state: RootState
  projections: string[]
}

export interface ServedResolution {
  state: 'served'
  project: string
  source: 'declared' | 'implied'
  declaration: string
  roots: ResolvedRoot[]
  projections: string[]
  reason: ''
  code: ''
  lookedFor: string[]
}

export interface RefusedResolution {
  state: 'refused'
  project: string
  code: string
  reason: string
  declaration: string
  lookedFor: string[]
}

export type RootsResolution = ServedResolution | RefusedResolution

/* ---------------------------------------------------------------- helpers */

const SEGMENT_RE = /^[A-Za-z0-9][A-Za-z0-9._\-/]*$/
const PROJECT_KEY_RE = /^[a-z0-9][a-z0-9-]*$/

/** Registry root: explicit > $SANDBAR_PROJECTS_DIR > ~/.sandbar/projects (the env value
 *  is read fresh on every call, same rule as the engine resolver). */
export function projectsRoot(override?: string): string {
  if (typeof override === 'string' && override !== '') return override
  const env = process.env[PROJECTS_DIR_ENV] ?? ''
  if (env !== '') return env
  return join(homedir(), '.sandbar', 'projects')
}

/** `<projects root>/<key>/project.yaml`, or null when the key is not a project key (no
 *  declaration can exist then — that is "absent", not "malformed"). */
export function declarationPath(projectKey: string, override?: string): string | null {
  if (!PROJECT_KEY_RE.test(String(projectKey ?? ''))) return null
  return join(projectsRoot(override), String(projectKey), 'project.yaml')
}

/** The derived documentation artefacts' home: the project's own data directory,
 *  outside every repository of the project. */
export function indexDir(projectKey: string, override?: string): string {
  return join(projectsRoot(override), String(projectKey), 'data', 'docs')
}

class DeclarationProblem extends Error {
  code: string
  declaration: string
  path: string

  constructor(code: string, message: string, declaration = '', path = '') {
    super(message)
    this.code = code
    this.declaration = declaration
    this.path = path
  }
}

function stripLine(raw: string): string | null {
  const line = raw.replace(/#.*$/, '').replace(/\s+$/, '')
  return line.trim() === '' ? null : line
}

function indentOf(raw: string): number {
  return raw.length - raw.trimStart().length
}

/** Validate one declared `repository`/`path` value: a relative posix path inside its
 *  repository; absolute, `..`, empty, trailing slash and `.` (the whole repository) are
 *  refused by name. */
function declPathValue(kind: string, value: string, label: string, lineno: number): string {
  const v = String(value ?? '').trim()
  const where = `${label}:${lineno} ${kind}`
  if (v === '') throw new DeclarationProblem(STOP.declarationMalformed, `${where}: empty value (a declared ${kind} needs a path)`, label)
  if (v.startsWith('{') || v.startsWith('[')) {
    throw new DeclarationProblem(STOP.declarationMalformed, `${where}: value is not a scalar: ${v.slice(0, 40)}`, label)
  }
  if (v.startsWith('/') || v.startsWith('~') || (v.length > 1 && v[1] === ':')) {
    throw new DeclarationProblem(STOP.declarationMalformed, `${where}: must be relative to its repository; found an absolute path: ${v.slice(0, 60)}`, label)
  }
  if (v.split('/').includes('..')) throw new DeclarationProblem(STOP.declarationMalformed, `${where}: forbids the .. escape: ${v}`, label)
  if (v.endsWith('/')) throw new DeclarationProblem(STOP.declarationMalformed, `${where}: must not end with a slash: ${v}`, label)
  if (v === '.') {
    // `repository: .` is the project root itself; a documentation ROOT of `.` would take
    // the whole repository (the false-green shape) and is refused.
    if (kind !== 'repository') {
      throw new DeclarationProblem(STOP.declarationMalformed,
        `${where}: a documentation root cannot be the whole repository ('.')`, label)
    }
    return ''
  }
  if (v.includes('\\') || !SEGMENT_RE.test(v)) {
    throw new DeclarationProblem(STOP.declarationMalformed, `${where}: not a posix path: ${v}`, label)
  }
  return v
}

function declProjections(value: string, label: string, lineno: number): string[] {
  const out: string[] = []
  for (const tok of String(value ?? '').replace(/,/g, ' ').split(/\s+/)) {
    if (tok === '') continue
    if (!PROJECTION_VOCAB.includes(tok)) {
      throw new DeclarationProblem(STOP.declarationMalformed,
        `${label}:${lineno} ${SECTION_LABEL}: unknown projection '${tok}' (vocabulary: ${PROJECTION_VOCAB.join(', ')})`, label)
    }
    if (!out.includes(tok)) out.push(tok)
  }
  return out
}

/** The registry entry's first `dirs` item (the project root, the base of every declared
 *  repository). "" when the entry carries none. */
export function projectRootOf(text: string): string {
  let section = ''
  for (const raw of String(text ?? '').split('\n')) {
    const line = stripLine(raw)
    if (line === null) continue
    if (!raw.startsWith(' ')) {
      const m = /^([a-z_]+):/.exec(line)
      section = m === null ? '' : m[1]
      continue
    }
    if (section !== 'project') continue
    const item = /^\s+-\s+(.+)$/.exec(line)
    if (item !== null && item[1].trim().startsWith('/')) return item[1].trim()
  }
  return ''
}

/**
 * Judge the `paths.docs_roots` block of one declaration text.
 *
 * Truth table (identical to the engine parser): block absent -> null (nothing
 * declared); one entry -> one root; several -> several; the same (repository, path)
 * twice -> `docs_roots_duplicate`; any other unusable shape (unknown key, missing key,
 * duplicate key, a line outside the block's grammar) -> `docs_roots_declaration_malformed`.
 * A broken declaration is never read as "nothing declared" — that would let a typo
 * silently move the documentation root back to the default.
 */
export function parseDeclaration(text: string, label = 'project.yaml'): DocsRootEntry[] | null {
  const lines = String(text ?? '').split('\n')
  let block: { lineno: number; raw: string }[] | null = null
  let inPaths = false
  let i = 0
  while (i < lines.length) {
    const raw = lines[i]
    const line = stripLine(raw)
    if (line === null) { i += 1; continue }
    if (!raw.startsWith(' ')) {
      inPaths = (line === 'paths:')
      i += 1
      continue
    }
    const stripped = line.trim()
    if (inPaths && stripped === `${SECTION_KEY}:`) {
      if (indentOf(raw) !== 2) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${i + 1} ${SECTION_LABEL}: must be two-space indented inside paths:`, label)
      }
      if (block !== null) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${i + 1} duplicate ${SECTION_LABEL}: block`, label)
      }
      block = []
      i += 1
      while (i < lines.length) {
        const inner = lines[i]
        const innerLine = stripLine(inner)
        if (innerLine === null) { i += 1; continue }
        if (indentOf(inner) <= 2) break       // the next paths key closes the block
        block.push({ lineno: i + 1, raw: inner })
        i += 1
      }
      continue
    }
    i += 1
  }
  if (block === null) return null

  const entries: DocsRootEntry[] = []
  let current: Record<string, string> = {}
  let currentLine = 0
  const seen = new Set<string>()

  const flush = (): void => {
    if (Object.keys(current).length === 0 && currentLine === 0) return
    for (const key of ENTRY_KEYS) {
      if (!(key in current)) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${currentLine} an entry is missing '${key}' (every root names its repository and its path)`, label)
      }
    }
    const pair = `${current.repository}\u0000${current.path}`
    if (seen.has(pair)) {
      throw new DeclarationProblem(STOP.duplicate,
        `${label}:${currentLine} duplicate root: repository '${current.repository || '.'}' path '${current.path}' is declared twice`,
        label, current.path)
    }
    seen.add(pair)
    entries.push({
      repository: current.repository,
      path: current.path,
      projections: current.__projections === undefined
        ? []
        : current.__projections.split(',').filter((x) => x !== ''),
    })
    current = {}
  }

  for (const { lineno, raw } of block) {
    const stripped = raw.trim()
    const item = /^-\s*([A-Za-z_]+):\s*(.*)$/.exec(stripped)
    if (item !== null) {
      flush()
      currentLine = lineno
      const key = item[1]
      if (!ENTRY_KEYS.includes(key) && !ENTRY_OPTIONAL_KEYS.includes(key)) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${lineno} unrecognized ${SECTION_LABEL} entry key: '${key}' (only ${ENTRY_KEYS.join(', ')}; optional: ${ENTRY_OPTIONAL_KEYS.join(', ')})`, label)
      }
      if (key === 'projections') {
        current.__projections = declProjections(item[2], label, lineno).join(',')
        continue
      }
      current[key] = declPathValue(key, item[2], label, lineno)
      continue
    }
    const cont = /^([A-Za-z_]+):\s*(.*)$/.exec(stripped)
    if (cont !== null && currentLine > 0) {
      const key = cont[1]
      if (!ENTRY_KEYS.includes(key) && !ENTRY_OPTIONAL_KEYS.includes(key)) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${lineno} unrecognized ${SECTION_LABEL} entry key: '${key}' (only ${ENTRY_KEYS.join(', ')}; optional: ${ENTRY_OPTIONAL_KEYS.join(', ')})`, label)
      }
      if (key === 'projections') {
        if (current.__projections !== undefined) {
          throw new DeclarationProblem(STOP.declarationMalformed,
            `${label}:${lineno} duplicate 'projections' in one entry`, label)
        }
        current.__projections = declProjections(cont[2], label, lineno).join(',')
        continue
      }
      if (key in current) {
        throw new DeclarationProblem(STOP.declarationMalformed,
          `${label}:${lineno} duplicate '${key}' in one entry`, label)
      }
      current[key] = declPathValue(key, cont[2], label, lineno)
      continue
    }
    throw new DeclarationProblem(STOP.declarationMalformed,
      `${label}:${lineno} ${SECTION_LABEL}: line is neither '- repository: ...' nor 'path: ...': '${stripped.slice(0, 60)}'`, label)
  }
  flush()
  if (entries.length === 0) {
    throw new DeclarationProblem(STOP.declarationMalformed,
      `${label}: ${SECTION_LABEL}: block carries no entry (declare at least one root or remove the block)`, label)
  }
  return entries
}

/* ---------------------------------------------------------------- the resolution */

/** Every `.md` file below `dir`, POSIX-relative, sorted; unreadable sub-directories are
 *  skipped (a read-only view never fails for a directory it cannot list). */
export function listMarkdown(dir: string, prefix = ''): string[] {
  const out: string[] = []
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return out
  }
  for (const e of entries) {
    if (e.name.startsWith('.')) continue
    const rel = prefix === '' ? e.name : `${prefix}/${e.name}`
    if (e.isDirectory()) out.push(...listMarkdown(join(dir, e.name), rel))
    else if (e.isFile() && e.name.endsWith('.md')) out.push(rel)
  }
  return out.sort()
}

/** Directory holds at least one `.md` page anywhere below it. */
function rootStateOf(directory: string): RootState {
  return listMarkdown(directory).length > 0 ? 'served' : 'empty'
}

function isDir(path: string): boolean {
  try { return statSync(path).isDirectory() } catch { return false }
}

function exists(path: string): boolean {
  try { statSync(path); return true } catch { return false }
}

function refusal(project: string, code: string, reason: string, lookedFor: string[] = [],
  declaration = ''): RefusedResolution {
  return { state: 'refused', project, code, reason, declaration, lookedFor }
}

/**
 * The roots in effect for the PROJECT (design goal 8: one documents view per project,
 * showing the merged set of its roots). Same declaration, same parser, same entry
 * validation and the same refusal codes as `server/engine/docs_roots.py`.
 *
 * `repos` are the project's registered repositories (the caller holds them from the
 * registry); `repos[0]` is the project root every declared `repository` is written
 * against — the same base the engine's resolver uses. `fallbackRepo` covers the
 * console's no-project default context. `declarationText` lets a test drive the parser
 * without a registry; `noDeclaration` says "this context has no registry entry".
 */
export function resolveDocsRoots(projectKey: string,
  opts: { repos?: readonly string[]; fallbackRepo?: string; projectsRootDir?: string;
    declarationText?: string; noDeclaration?: boolean } = {}): RootsResolution {
  const project = String(projectKey ?? '')
  const repos = (opts.repos ?? []).filter((r) => typeof r === 'string' && r !== '')
  const projectRoot = repos.length > 0
    ? repos[0]
    : (typeof opts.fallbackRepo === 'string' && opts.fallbackRepo !== '' ? opts.fallbackRepo : '')
  let text: string | null = null
  let label = ''
  if (typeof opts.declarationText === 'string') {
    text = opts.declarationText
    label = join(opts.projectsRootDir ?? projectsRoot(), project, 'project.yaml')
  } else if (opts.noDeclaration !== true) {
    const path = declarationPath(project, opts.projectsRootDir)
    label = path ?? ''
    if (path !== null) {
      try {
        text = readFileSync(path, 'utf8')
      } catch (err: any) {
        if (err?.code !== 'ENOENT') {
          return refusal(project, STOP.declarationUnreadable,
            `${path} is unreadable: ${String(err?.message ?? err)}`, [path], path)
        }
      }
    }
  }

  let entries: DocsRootEntry[] | null = null
  if (text !== null) {
    try {
      entries = parseDeclaration(text, label || 'project.yaml')
    } catch (err: any) {
      return refusal(project, String(err?.code ?? STOP.declarationMalformed),
        String(err?.message ?? err),
        [String(err?.path ?? '')].filter((x) => x !== ''),
        String(err?.declaration ?? label))
    }
  }

  if (entries === null) {
    // Undeclared: the implied default root of the project root (today's behaviour).
    if (projectRoot === '') {
      return refusal(project, STOP.absent,
        `project '${project}' declares no documentation root (${SECTION_LABEL}) and no repository root was given to look for the implied default directory '${IMPLIED_ROOT}'`,
        [], label)
    }
    const candidate = join(projectRoot, IMPLIED_ROOT)
    if (!isDir(candidate)) {
      return refusal(project, STOP.absent,
        `project '${project}' declares no documentation root (${SECTION_LABEL}) and no documentation directory exists at the repository root: looked for ${candidate}`,
        [candidate], label)
    }
    return {
      state: 'served', project, source: 'implied', declaration: label, reason: '', code: '',
      roots: [{
        id: `.:${IMPLIED_ROOT}`, repository: '.', repoDir: projectRoot, path: IMPLIED_ROOT,
        directory: candidate, state: rootStateOf(candidate), projections: [],
      }],
      projections: [],
      lookedFor: [candidate],
    }
  }

  if (projectRoot === '') {
    return refusal(project, STOP.declarationMalformed,
      `${label || 'project.yaml'}: ${SECTION_LABEL} is declared but the entry carries no usable first dirs item (the project root is unknown, so no declared repository can be resolved)`,
      [], label)
  }
  const roots: ResolvedRoot[] = []
  const lookedFor: string[] = []
  const projections: string[] = []
  for (let index = 0; index < entries.length; index++) {
    const entry = entries[index]
    const repoDir = entry.repository === '' ? projectRoot : join(projectRoot, entry.repository)
    if (entry.repository !== '' && !isDir(repoDir)) {
      return refusal(project, STOP.repositoryUnknown,
        `${label}: ${SECTION_LABEL} entry ${index + 1} names repository '${entry.repository}', which is not a directory of the project: looked for ${repoDir}`,
        [repoDir], label)
    }
    const directory = join(repoDir, entry.path)
    lookedFor.push(directory)
    if (!isDir(directory)) {
      const present = exists(directory)
      return refusal(project, present ? STOP.rootUnreadable : STOP.rootAbsent,
        `${label}: ${SECTION_LABEL} entry ${index + 1} declares repository '${entry.repository || '.'}' path '${entry.path}' but that root ${present ? 'is not readable' : 'does not exist'}: looked for ${directory}`,
        [directory], label)
    }
    roots.push({
      id: `${entry.repository || '.'}:${entry.path}`,
      repository: entry.repository || '.',
      repoDir,
      path: entry.path,
      directory,
      state: rootStateOf(directory),
      projections: entry.projections,
    })
    for (const name of entry.projections) if (!projections.includes(name)) projections.push(name)
  }
  return {
    state: 'served', project, source: 'declared', declaration: label, reason: '', code: '',
    roots, projections, lookedFor,
  }
}

/** Newest mtime (ms) of any page under these roots — the staleness measurement the
 *  readers use. `null` = no page at all (nothing can be newer than the build). */
export function newestDocMtime(roots: readonly { directory: string }[]): number | null {
  let newest: number | null = null
  for (const root of roots) {
    for (const rel of listMarkdown(root.directory)) {
      try {
        const m = statSync(join(root.directory, rel)).mtimeMs
        if (newest === null || m > newest) newest = m
      } catch { /* vanished between listing and stat: not a newer document */ }
    }
  }
  return newest
}

/* ---------------------------------------------------------------- derived index */

export type IndexState = 'absent' | 'current' | 'stale' | 'failed'

export interface IndexRead {
  state: IndexState
  project: string
  /** Time of the LAST SUCCESSFUL build (ISO); '' when never built. */
  builtAt: string
  /** Why a rebuild is due (state=stale). */
  staleReason: string
  /** The named failure (state=failed). */
  reason: string
  code: string
  /** Entries only when it is honest to show them (current or stale — never failed). */
  entries: any[]
  roots: any[]
  total: number
  review: { missing_frontmatter: string[]; deprecated: string[]; stale: string[] }
}

/** The reader-side states, spelled once for both consumers and the UI copy. */
export const INDEX_COPY = {
  absent: 'Index not built yet — the documentation inspection builds it on its own pass. Documents are listed from the declared roots.',
  stalePrefix: 'Index is stale — last built',
  staleSuffix: 'A rebuild is due; the documents below are read from the roots, not from that index.',
  failedPrefix: 'Index rebuild failed:',
  failedSuffix: 'The previous index is NOT shown as current. The documents below are read from the roots.',
  currentPrefix: 'Index up to date — built',
} as const

function parseIsoMs(text: unknown): number | null {
  if (typeof text !== 'string' || text === '') return null
  const ms = Date.parse(text)
  return Number.isFinite(ms) ? ms : null
}

/**
 * Read the derived index and state its freshness. READ ONLY: opens and parses files,
 * never creates, rewrites or locks one (the rebuild belongs to the documentation
 * inspection pass or to an explicit operator act).
 *
 * `newestMtime` lets a caller that already walked the roots pass its measurement;
 * otherwise this reads the roots itself. `newestMtime` = null means "no page at all".
 */
export function readIndexState(projectKey: string, resolution: RootsResolution,
  opts: { indexDir?: string; newestMtime?: number | null } = {}): IndexRead {
  const dir = opts.indexDir ?? indexDir(projectKey)
  const base: IndexRead = {
    state: 'absent', project: projectKey, builtAt: '', staleReason: '', reason: '', code: '',
    entries: [], roots: [], total: 0,
    review: { missing_frontmatter: [], deprecated: [], stale: [] },
  }
  const reviewOf = (payload: any): IndexRead['review'] => {
    const r = (payload ?? {}).review ?? {}
    const list = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => String(x)) : [])
    return {
      missing_frontmatter: list(r.missing_frontmatter),
      deprecated: list(r.deprecated),
      stale: list(r.stale),
    }
  }
  if (resolution.state === 'refused') {
    // A refused declaration is a named failure, never an empty library.
    return { ...base, state: 'failed', code: resolution.code, reason: resolution.reason }
  }
  let payload: any = null
  try {
    payload = JSON.parse(readFileSync(join(dir, 'index.json'), 'utf8'))
  } catch (err: any) {
    if (err?.code === 'ENOENT') return base
    return { ...base, state: 'failed', code: 'docs_index_unreadable', reason: `index unreadable at ${join(dir, 'index.json')} (${String(err?.message ?? err)})` }
  }
  if (payload === null || typeof payload !== 'object') {
    return { ...base, state: 'failed', code: 'docs_index_unreadable', reason: `index at ${join(dir, 'index.json')} is not a JSON object` }
  }
  const builtAt = typeof payload.built_at === 'string' ? payload.built_at : ''
  const rawTs = typeof payload.built_at_ts === 'number' ? payload.built_at_ts * 1000 : null
  const builtMs = rawTs ?? parseIsoMs(builtAt)
  let failure: any = null
  try {
    failure = JSON.parse(readFileSync(join(dir, 'rebuild-failed.json'), 'utf8'))
  } catch { failure = null }
  if (failure && typeof failure === 'object') {
    const failMs = typeof failure.failed_at_ts === 'number'
      ? failure.failed_at_ts * 1000
      : parseIsoMs(failure.failed_at)
    if (builtMs === null || failMs === null || failMs >= builtMs) {
      return {
        ...base, state: 'failed', builtAt,
        code: String(failure.code ?? 'docs_index_rebuild_failed'),
        reason: String(failure.reason ?? 'rebuild failed'),
      }
    }
  }
  const builtRoots = (Array.isArray(payload.roots) ? payload.roots : [])
    .map((r: any) => String(r?.identity ?? '')).sort()
  const nowRoots = resolution.roots.map((r) => r.id).sort()
  let staleReason = ''
  if (payload.schema !== 'v1') {
    staleReason = `index schema '${String(payload.schema)}' is not 'v1' — rebuild due`
  }
  if (staleReason === '' && JSON.stringify(builtRoots) !== JSON.stringify(nowRoots)) {
    staleReason = `the documentation roots in effect changed since the build (built from ${builtRoots.join(', ') || '(none)'}; now ${nowRoots.join(', ') || '(none)'})`
  }
  if (staleReason === '') {
    const newest = opts.newestMtime === undefined
      ? newestDocMtime(resolution.roots)
      : opts.newestMtime
    if (newest !== null && builtMs !== null && newest > builtMs) {
      staleReason = `a document is newer than the build (page mtime ${new Date(newest).toISOString()}, built ${builtAt})`
    }
  }
  const entries = Array.isArray(payload.docs) ? payload.docs : []
  return {
    state: staleReason === '' ? 'current' : 'stale',
    project: projectKey,
    builtAt,
    staleReason,
    reason: '',
    code: '',
    entries,
    roots: Array.isArray(payload.roots) ? payload.roots : [],
    total: typeof payload.total === 'number' ? payload.total : entries.length,
    review: reviewOf(payload),
  }
}

/** One line a view shows for the index state. Stale NEVER reads as current: it names
 *  the last build time and says a rebuild is due. */
export function indexBanner(read: IndexRead): string {
  if (read.state === 'absent') return INDEX_COPY.absent
  if (read.state === 'failed') return `${INDEX_COPY.failedPrefix} ${read.reason}. ${INDEX_COPY.failedSuffix}`
  if (read.state === 'stale') {
    return `${INDEX_COPY.stalePrefix} ${read.builtAt} (${read.staleReason}). ${INDEX_COPY.staleSuffix}`
  }
  return `${INDEX_COPY.currentPrefix} ${read.builtAt}.`
}

/* ---------------------------------------------------------------- live listing */

/** One page read live from a root (used when the index is absent or failed, so a
 *  project that HAS documents is never shown as empty). */
export interface LiveEntry {
  id: string
  root: string
  repository: string
  root_path: string
  path: string
  title: string
  category: string
  status: string
  updated: string
  tags: string[]
  has_frontmatter: boolean
}

/** Read every page of the resolved roots into entries (read-only, no index involved).
 *
 * Same admission rule as the console's tree (`isSafeDocRel`), same title derivation, and
 * the category comes from the page itself: the frontmatter `category`, else its own
 * directory relative to the root, else `root`. No fixed category vocabulary.
 */
export function liveEntries(resolution: ServedResolution): LiveEntry[] {
  const out: LiveEntry[] = []
  for (const root of resolution.roots) {
    for (const rel of listMarkdown(root.directory)) {
      if (!isSafeDocRel(rel)) continue
      let head = ''
      try {
        head = readFileSync(join(root.directory, rel), 'utf8').slice(0, 8192)
      } catch { continue }        // an unreadable page is skipped, never faked
      const parsed = parseFrontmatter(head)
      const meta = parsed.meta ?? {}
      const parent = rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : ''
      const category = (meta.category && meta.category !== '')
        ? meta.category
        : (parent !== '' ? parent.slice(parent.lastIndexOf('/') + 1) : 'root')
      out.push({
        id: `${root.id}:${rel}`,
        root: root.id,
        repository: root.repository,
        root_path: root.path,
        path: rel,
        title: docTitleOf(meta, rel),
        category,
        status: meta.status ?? '',
        updated: meta.updated ?? '',
        tags: [],
        has_frontmatter: parsed.hasFrontmatter,
      })
    }
  }
  return out.sort((a, b) => (a.category === b.category
    ? (a.id < b.id ? -1 : 1)
    : (a.category < b.category ? -1 : 1)))
}

/**
 * Which root holds a document path, for a consumer that carries no selection token.
 *
 * An explicit root id wins; otherwise the path itself decides: exactly one root that
 * holds the page wins, and zero or several are a NAMED ambiguity (never a silent pick —
 * two roots holding the same relative path must not open each other's file).
 */
export function locateRoot(resolution: ServedResolution, rel: string,
  rootId?: string | null): { root: ResolvedRoot } | { reason: string } {
  if (resolution.roots.length === 0) {
    return { reason: resolution.reason || 'no documentation root in effect' }
  }
  if (typeof rootId === 'string' && rootId !== '') {
    const named = resolution.roots.find((r) => r.id === rootId)
    return named !== undefined
      ? { root: named }
      : { reason: `unknown root '${rootId}' (in effect: ${resolution.roots.map((r) => r.id).join(', ')})` }
  }
  const holders = resolution.roots.filter((r) => {
    try { return statSync(join(r.directory, rel)).isFile() } catch { return false }
  })
  if (holders.length === 1) return { root: holders[0] }
  if (holders.length === 0) {
    return { reason: `'${rel}' exists under none of the documentation roots in effect (${resolution.roots.map((r) => r.id).join(', ')})` }
  }
  return { reason: `'${rel}' exists under ${holders.length} roots (${holders.map((r) => r.id).join(', ')}) — name one with root=` }
}

/** (root index | null, path) of a selection token; a plain path passes through. */
export function parseRootToken(selection: string): { rootIndex: number | null; rel: string } {
  const m = /^@(\d+)\/(.+)$/.exec(selection)
  return m === null ? { rootIndex: null, rel: selection } : { rootIndex: Number(m[1]), rel: m[2] }
}

/** The path a selection token carries (the transport prefix is not a path). */
export function splitRootToken(selection: string): string {
  return parseRootToken(selection).rel
}
