/**
 * docs.ts —— 「文档」视图宿主半（t260905-06；KI-070 起按项目根解析=t260910-10）：
 * docs/ 定稿库与 notes/ 观察窗的只读枚举/读取（node.ts docs 端点的实作单源，
 * 纯 fs 无进程/无监听，便于直测）。root 由调用方（node.ts docs 端点）按 ?project=
 * 项目锚解析后显式传入——本模块对项目语义无感，装载语义与单仓时代完全一致。
 *
 * 降级口径（R1 取舍清单 2 承接——精确报错，对照 KI-025「不许谎报没有」）：
 *   - scope 目录缺席 → { empty:true, reason:'<scope>/ 目录不存在（项目根=<root>）' }（真没有）；
 *   - rel 白名单拒 → 每类检查失败的 reason 各不相同（点了哪个检查就报哪个）；
 *   - 白名单允许但读不到（ENOENT）→ '文件不存在'（白名单真允许、读后确无）；
 *   - 超限 → '文件超过大小上限'；读失败 → '读取失败: <原文>'。
 *
 * 资源终态：readdir/readFile 一次性调用自回收，无长驻句柄/定时器/子进程；
 * 全路径（正常/目录缺/读失败）无遗留资源。
 */
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import {
  buildDocTree, docTitleOf, isSafeDocRel, parseFrontmatter,
  type DocMeta, type DocTreeGroup,
} from '../shared/docs-model.ts'
// t261103-12: the ONE documentation-root resolution (shared with the knowledge feature)
// plus the derived-index state — this view no longer derives a documentation directory
// from a name of its own.
import {
  indexBanner, locateRoot, newestDocMtime, parseRootToken, readIndexState, resolveDocsRoots,
  type RootsResolution, type ResolvedRoot,
} from '../../../knowledge/src/shared/docs-roots.ts'

/** 单篇大小上限（utf8 字符数；定稿库最大篇 ~60KB，2MB 上限=10 倍余量防误配大文件拖爆响应）。 */
export const DOC_MAX_CHARS = 2_000_000

export interface DocsTreeResult {
  empty: boolean
  reason?: string
  scope: 'docs' | 'notes'
  /** 白名单通过的篇（树形分组）。 */
  groups: DocTreeGroup[]
  /** 白名单拒收文件（可见性：计数+理由，C3——完整性可判定，不静默消失）。 */
  skipped: { path: string; reason: string }[]
}

/** 递归收集 root 下文件；root 不存在返回 null（=真没有）。links=符号链接条目（拒收可见）。 */
interface WalkResult { files: string[]; links: string[] }

async function walkMd(root: string): Promise<WalkResult | null> {
  const files: string[] = []
  const links: string[] = []
  let entries
  try {
    entries = await readdir(root, { withFileTypes: true })
  } catch (err: any) {
    if (err?.code === 'ENOENT') return null
    throw err
  }
  for (const e of entries) {
    const rel = e.name
    if (e.isDirectory()) {
      const sub = await walkMd(join(root, rel))
      if (sub === null) continue // 目录在读之间被删=空集，不放大为错
      files.push(...sub.files.map((s) => `${rel}/${s}`))
      links.push(...sub.links.map((s) => `${rel}/${s}`))
    } else if (e.isFile()) {
      files.push(rel) // 非 .md 也收集——进 skipped 可见（拒收面完整，不静默消失）
    } else if (e.isSymbolicLink()) {
      links.push(rel) // 符号链接不枚举进树（只读面防外指，验收登记项 C）：进 skipped 可见
    }
  }
  return { files, links }
}

/** 枚举 scope 目录：白名单内进树，白名单外进 skipped（拒收可见）。 */
export async function listDocs(root: string, scope: 'docs' | 'notes'): Promise<DocsTreeResult> {
  const walk = await walkMd(root)
  if (walk === null) {
    return { empty: true, reason: `${scope}/ 目录不存在（项目根=${root}）`, scope, groups: [], skipped: [] }
  }
  const files = walk.files.sort()
  const skipped: { path: string; reason: string }[] = walk.links.map((rel) => ({
    path: rel, reason: '符号链接不枚举（只读面防外指）',
  }))
  const ok: { rel: string; title: string }[] = []
  for (const rel of files) {
    if (isSafeDocRel(rel)) {
      // 树形条目需要 title：读每篇头 4KB 解 frontmatter（大文件不整读）。
      try {
        const head = await readFile(join(root, rel), { encoding: 'utf8', flag: 'r' })
          .then((t) => t.slice(0, 4096))
        ok.push({ rel, title: docTitleOf(parseFrontmatter(head).meta, rel) })
      } catch {
        ok.push({ rel, title: rel }) // 头部读不动不隐篇：回落路径名，标题读失败可见（正文端点再报精确错）
      }
    } else {
      skipped.push({ path: rel, reason: skipReason(rel) })
    }
  }
  return { empty: false, scope, groups: buildDocTree(ok), skipped }
}

/** 白名单拒收理由（逐检查点名，不笼统「不合法」）。 */
function skipReason(rel: string): string {
  if (!rel.endsWith('.md')) return '仅 .md 入视图'
  if (rel.includes('\\')) return '含反斜杠（非 POSIX 路径段）'
  if (rel.includes('%')) return '含 URL 编码残留字符 %'
  if (rel.split('/').some((seg) => seg.includes(' '))) return '路径段含空格'
  if (rel.split('/').includes('..')) return '含 .. 段（穿路径拒绝）'
  return '路径含白名单外字符（段仅允许字母/数字/下划线/中文/连字符）'
}

export interface DocReadResult {
  empty: boolean
  reason?: string
  rel: string
  title: string
  meta: DocMeta
  body: string
  truncated?: boolean
}

/**
 * 读单篇：白名单 → 越界 → 大小 → ENOENT → 读失败，每步失败 reason 点名该检查。
 * rel 已由调用方保证为字符串；本函数再做白名单判定（单源 isSafeDocRel）。
 */
export async function readDoc(root: string, rel: string): Promise<DocReadResult> {
  const fail = (reason: string): DocReadResult => ({ empty: true, reason, rel, title: '', meta: {}, body: '' })
  if (typeof rel !== 'string' || rel === '') return fail('path 参数缺失（?path=<scope 下相对路径>.md）')
  if (rel.includes('\\')) return fail('path 不合法：含反斜杠（POSIX 相对路径才接受）')
  if (rel.includes('%')) return fail('path 不合法：含 URL 编码残留字符 %（请传解码后的路径）')
  if (rel.startsWith('/')) return fail('path 不合法：不接受绝对路径（传 scope 下相对路径）')
  if (rel.split('/').includes('..')) return fail('path 不合法：含 .. 段（穿路径拒绝）')
  if (!isSafeDocRel(rel)) return fail(`path 不合法（${'<目录/'}<文件>.md，段字符限字母/数字/下划线/中文/连字符）: ${rel}`)
  // 越界防呆：isSafeDocRel 已拒 .. 段与绝对路径，abs 恒在 root 下；此处再显式判一次（fail-closed 双闸）。
  const abs = join(root, rel)
  if (!abs.startsWith(root)) return fail('path 越界（穿路径拒绝）')
  let text: string
  try {
    text = await readFile(abs, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return fail(`文件不存在: ${rel}`)
    return fail(`读取失败: ${String(err?.message ?? err)}`)
  }
  if (text.length > DOC_MAX_CHARS) return fail(`文件超过大小上限（${DOC_MAX_CHARS} 字符）: ${rel}`)
  const parsed = parseFrontmatter(text)
  return {
    empty: false,
    rel,
    title: docTitleOf(parsed.meta, rel),
    meta: parsed.meta,
    body: parsed.body,
    truncated: text.length >= DOC_MAX_CHARS ? true : undefined,
  }
}

/* ======================================================================
 * t261103-12 — the docs scope over the project's RESOLVED documentation roots
 *
 * Where the view used to read `<project root>/docs` and nothing else, it now asks the
 * ONE resolution (server/plugins/knowledge/src/shared/docs-roots.ts — the same module
 * the knowledge feature uses) and merges every root in effect into one view. The
 * derived index's state travels with the answer (absent / stale with the last build
 * time / failed with its reason / current), so the page can label it; the files
 * themselves are always read from the roots, never from a stale index.
 *
 * Selection token: with more than one root a file row's `rel` is a SELECTION TOKEN
 * `@<n>/<root-relative path>` (n = index in the resolution order). Single-root views
 * keep the plain relative path byte for byte, so today's projects see no change. The
 * token exists because the page sends back exactly one string (`?path=`), and two roots
 * may hold the same relative path — without it the second page would open the first
 * root's file.
 * ====================================================================== */

/** One root's contribution to the merged view. */
export interface DocsRootRow {
  id: string
  repository: string
  path: string
  state: string
  declared: boolean
  groups: number
  docs: number
}

export interface DocsIndexFace {
  state: string
  built_at: string
  stale_reason: string
  reason: string
  code: string
  banner: string
  total: number
}

export interface DocsRootsTreeResult {
  /** True only when a root is in effect and holds no page at all. */
  empty: boolean
  reason?: string
  state: 'served' | 'refused'
  declared: boolean
  declaration: string
  roots: DocsRootRow[]
  groups: DocTreeGroup[]
  skipped: { path: string; reason: string; root?: string }[]
  index: DocsIndexFace
  looked_for: string[]
  /** The refusal code a page can key on (empty when served). */
  code: string
}

export interface DocsRootsOpts {
  repos?: readonly string[]
  fallbackRepo?: string
  declarationText?: string
  projectsRootDir?: string
  noDeclaration?: boolean
}

/** Split a selection token into (root index | null, root-relative path). One
 *  implementation for both the host and the page: the shared module's parser. */
export function splitSelection(selection: string): { rootIndex: number | null; rel: string } {
  return parseRootToken(selection)
}

/** The value the page shows for a selection (the token prefix is transport, not a path). */
export function selectionDisplay(selection: string): string {
  return parseRootToken(selection).rel
}

/** The group label a merged view shows for one root: `<repository>/<rootPath>`, where a
 *  root in the project's own repository is named by that repository's directory name (a
 *  bare `.` would not tell a reader which repository the documents came from). */
function rootLabel(root: ResolvedRoot): string {
  const repoName = root.repository === '.'
    ? (root.repoDir.replace(/\/+$/, '').split('/').pop() || '.')
    : root.repository
  return `${repoName}/${root.path}`
}

/** Resolve the docs roots for one request (declaration -> roots in effect). */
export function resolveDocsFor(projectKey: string, opts: DocsRootsOpts = {}): RootsResolution {
  return resolveDocsRoots(projectKey, opts)
}

/** One request renders ONE merged view over the roots in effect. Read-only: it never
 *  rebuilds the index and never creates a directory. */
export async function docsRootsTree(projectKey: string,
  opts: DocsRootsOpts = {}): Promise<DocsRootsTreeResult> {
  const resolution: RootsResolution = resolveDocsRoots(projectKey, opts)
  const indexRead = readIndexState(projectKey, resolution, {
    newestMtime: resolution.state === 'served' ? newestDocMtime(resolution.roots) : null,
  })
  const index: DocsIndexFace = {
    state: indexRead.state,
    built_at: indexRead.builtAt,
    stale_reason: indexRead.staleReason,
    reason: indexRead.reason,
    code: indexRead.code,
    banner: indexBanner(indexRead),
    total: indexRead.total,
  }
  if (resolution.state === 'refused') {
    return {
      // `empty:true` is the legacy key the console page renders a named reason from;
      // `state:'refused'` keeps a refusal distinguishable from "present but empty".
      // The reason says the root was refused and names what was looked for, so this is
      // never a silent empty view.
      empty: true,
      state: 'refused',
      declared: resolution.declaration !== '',
      declaration: resolution.declaration,
      reason: resolution.reason,
      roots: [], groups: [], skipped: [], index,
      looked_for: resolution.lookedFor,
      code: resolution.code,
    }
  }
  const served: ServedResolution = resolution
  const multi = served.roots.length > 1
  const groups: DocTreeGroup[] = []
  const skipped: { path: string; reason: string; root?: string }[] = []
  const roots: DocsRootRow[] = []
  let docs = 0
  const trees: DocsTreeResult[] = []
  // A selection token is needed only when two roots hold the SAME relative path: every
  // other row keeps the plain path it always had (no cosmetic change on the page).
  const relCount = new Map<string, number>()
  for (const root of served.roots) {
    const tree = await listDocs(root.directory, 'docs')
    trees.push(tree)
    for (const g of tree.groups) {
      for (const f of g.files) relCount.set(f.rel, (relCount.get(f.rel) ?? 0) + 1)
    }
  }
  for (let i = 0; i < served.roots.length; i++) {
    const root = served.roots[i]
    const tree = trees[i]
    for (const s of tree.skipped) skipped.push({ ...s, root: root.id })
    let counted = 0
    for (const g of tree.groups) {
      counted += g.files.length
      // Group key: root + directory, so equal relative directories never collide.
      groups.push({
        dir: multi ? `${root.id}|${g.dir}` : g.dir,
        label: multi ? `${rootLabel(root)} / ${g.label}` : g.label,
        root: root.id,
        files: g.files.map((f) => ({
          rel: (relCount.get(f.rel) ?? 0) > 1 ? `@${i}/${f.rel}` : f.rel,
          title: f.title,
          root: root.id,
        })),
      })
    }
    docs += counted
    roots.push({ id: root.id, repository: root.repository, path: root.path,
      state: root.state, declared: served.source === 'declared', groups: tree.groups.length,
      docs: counted })
  }
  groups.sort((a, b) => (a.dir < b.dir ? -1 : a.dir > b.dir ? 1 : 0))
  return {
    empty: docs === 0,
    reason: docs === 0
      ? `no .md page under the documentation root(s) in effect: ${served.roots.map((r) => r.directory).join(', ')} (present but empty — a content finding, not a configuration refusal)`
      : undefined,
    state: 'served',
    declared: served.source === 'declared',
    declaration: served.declaration,
    roots,
    groups,
    skipped,
    index,
    looked_for: served.lookedFor,
    code: '',
  }
}

/** Read one page of the docs scope from the root it came from.
 *
 * The three refusal shapes stay distinct: a refused declaration, an unknown selection
 * token and a page the loader refuses each answer with their own reason. */
export async function readDocsSelection(projectKey: string, opts: DocsRootsOpts,
  selection: string): Promise<{ state: 'refused'; reason: string } |
    { state: 'served'; root: string; result: DocReadResult }> {
  const resolution = resolveDocsRoots(projectKey, opts)
  if (resolution.state === 'refused') {
    return { state: 'refused', reason: resolution.reason }
  }
  const { rootIndex, rel } = parseRootToken(selection)
  const located = rootIndex === null
    ? locateRoot(resolution, rel, null)
    : (resolution.roots[rootIndex] !== undefined
      ? { root: resolution.roots[rootIndex] }
      : { reason: `unknown root selection '@${rootIndex}' (roots in effect: ${resolution.roots.map((r, i) => `@${i}=${r.id}`).join(', ')})` })
  if ('reason' in located) {
    return { state: 'refused', reason: located.reason }
  }
  if (!isPlainDocRel(rel)) {
    return { state: 'refused', reason: `path not admitted (a safe .md path inside the root): ${rel}` }
  }
  return { state: 'served', root: located.root.id, result: await readDoc(located.root.directory, rel) }
}
