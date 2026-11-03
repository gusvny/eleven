/**
 * sandbar-knowledge —— docs 知识库的 dsh UI 插件（宿主半 / node）。
 *
 * 职责：在 dsh 自己的 webServer 上挂 /sandbar-knowledge/api/*，供本插件的浏览器半
 * （lib/client.js，主会话视图「知识库」页签）同源 fetch 使用：
 *
 *   GET /sandbar-knowledge/api/index?project=<key>
 *                                     → <项目主目录>/docs/index.json（结构化索引 + review，
 *                                        标题/分类/标签/状态/更新时间/路径）；
 *                                        项目无 docs/index.json → {empty:true, reason} 人话降级
 *   GET /sandbar-knowledge/api/doc?project=<key>&path=design/平台架构设计.md
 *                                     → 直读 <项目主目录>/docs/<path> 的全文（纯只读，
 *                                        path 白名单 = docs/index.json 的五个分类目录
 *                                        （词表见 doc-path-rule.json，含 epics）下的一层
 *                                        .md，规则单源该文件，防穿路径）
 *   GET /sandbar-knowledge/api/refresh?project=<key>
 *                                     → 重建 index（spawn python3 <主目录>/docs/scripts/build_index.py；
 *                                        项目无该脚本 → 人话降级不可用）
 *   GET /sandbar-knowledge/api/diff?project=<key>&path=design/xx.md[&base=HEAD]
 *                                     → 该文档相对 base（git ref）的 block 级 diff：
 *                                        细粒度切块（标题/段落/列表项/表格行/代码块…，
 *                                        类型+相似度对齐），逐块 added/removed/modified/
 *                                        unchanged + 稳定 block key + 行级 ops（仅修改块），
 *                                        供浏览器半渲染态逐块 approve/reject/注释（M3）。
 *
 *   GET /sandbar-knowledge/api/review?project=<key>&path=design/xx.md
 *                                     → 读已存 review（<主目录>/docs/reviews/<path,/→__>.json，
 *                                        无则空 rounds）
 *   POST /sandbar-knowledge/api/review/save {project, path, base, conclude, blocks[], reviewer?}
 *                                     → 追加一轮 review 落盘（path 白名单同源校验），
 *                                        写 server/admin.log 同款 JSONL 审计 + 回 run-id。
 *
 * 多项目化（260823）：project 是逻辑概念（server/projects.yaml 注册表，1:N 目录），
 * 知识库 = 项目主目录（dirs 首个）的 docs/。**project 参数必传、无默认值**——缺/未知 key 一律 400。
 * 审计仍落 suyou 仓库 server/admin.log（单一审计真源不随项目分流）。
 * headless profile 没有 webServer：apply 静默待命不报错。
 */

import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { appendFile, readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'
import { resolveRepo } from '../repo-anchor.mjs'  // t261008-33: shared anchor chain + escape guard
import { findProject, primaryDir, type ProjectEntry } from '../../project-registry.ts'
import { diffBlocks } from './src/shared/blocks.ts'
// t261103-12: the ONE documentation-root resolution, shared with the console documents
// view (server/plugins/workbench). This feature no longer decides "where the documents
// are" on its own: the roots come from the project's declaration, and the derived index
// is read from the project's data directory with its state (absent / stale / failed /
// current) attached to every answer.
import {
  indexBanner, indexDir, liveEntries, locateRoot,
  readIndexState as readIndexStateFor, resolveDocsRoots,
  type ResolvedRoot, type RootsResolution, type ServedResolution,
} from './src/shared/docs-roots.ts'
import { isSafeDocRel } from '../workbench/src/shared/docs-model.ts'

/** Containment check for a root-relative document path: safe shape AND inside the root
 *  (the lexical gates already refuse `..`/absolute; this is the second, explicit
 *  fail-closed door — same discipline as the workbench read path). */
function admitsInRoot(root: ResolvedRoot, rel: string): boolean {
  if (!isSafeDocRel(rel)) return false
  const abs = `${root.directory}/${rel}`
  return abs === root.directory || abs.startsWith(`${root.directory}/`)
}
import {
  CONCLUDES, appendReviewRound, loadReview,
  type ReviewBlockEntry, type ReviewConclude, type ReviewRound,
} from './src/shared/review-store.ts'

const execFileP = promisify(execFile)

export const name = 'sandbar-knowledge'
// webServer 只存在于 web profile；headless 下本插件待机即可。
export const inject: string[] = []

/** 本文件固定落在 <repo>/server/plugins/knowledge/ 下，上三级即仓库根（审计落盘锚点用）。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface SuyouKnowledgeConfig {
  /** 溯游仓库根（审计日志锚点）。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 子进程超时（毫秒），默认 30000。 */
  timeoutMs?: number
}

/** The docs-relative paths this plugin may serve directly: one plain .md inside one of
 *  the index's category directories (traversal-proof).
 *
 * t261029-49: the rule is no longer hard-coded here — its one source is
 * doc-path-rule.json (this package root), the same file review_store.py reads.
 * docs/index.json now registers the `epics` category (docs/epics/, epic frontmatter
 * schema), so the docs list shows those rows while the path rule refused them — opening
 * one answered 404 'path 不合法'. Only the category vocabulary changed; the containment
 * does not: the path must start with a category name (so an absolute path cannot match),
 * the file segment is [^/]+ (so a traversal or a nested directory cannot match), and the
 * extension check stays .md. */
interface DocPathRule {
  /** Category vocabulary (for the error copy; the order is the index's categories order). */
  categories: string[]
  /** The one admission pattern source. */
  pattern: string
}

const RULE_FILE = join(dirname(fileURLToPath(import.meta.url)), 'doc-path-rule.json')

/** Read the rule file and self-check it (the pattern must equal the alternation of its
 *  categories, so the file cannot self-drift). Missing/malformed -> a named error: the
 *  plugin goes red at load time and never silently widens to "anything under docs/". */
function loadDocPathRule(): DocPathRule {
  let raw: any
  try {
    raw = JSON.parse(readFileSync(RULE_FILE, 'utf8'))
  } catch (err: any) {
    throw new Error(`doc-path-rule.json unreadable / not JSON (${RULE_FILE}): ${String(err?.message ?? err)}`)
  }
  const categories = Array.isArray(raw?.categories) ? raw.categories.filter((c: unknown) => typeof c === 'string' && c !== '') : []
  if (categories.length === 0) throw new Error(`doc-path-rule.json has no categories (${RULE_FILE})`)
  const expected = `^(${categories.join('|')})/[^/]+\\.md$`
  if (raw?.pattern !== expected) {
    throw new Error(`doc-path-rule.json contradicts itself (${RULE_FILE}): pattern ${JSON.stringify(raw?.pattern)} is not the alternation of its categories ${JSON.stringify(expected)}`)
  }
  const re = new RegExp(expected)
  if (!re.test(`${categories[0]}/probe.md`)) throw new Error(`doc-path-rule.json pattern rejects its own first category (${RULE_FILE})`)
  return { categories, pattern: expected }
}

const DOC_PATH_RULE = loadDocPathRule()

/** The admission pattern (one source = doc-path-rule.json; review_store.py reads it too). */
export const DOC_PATH_RE = new RegExp(DOC_PATH_RULE.pattern)

/** The category vocabulary (error copy and tests; same source as the pattern). */
export const DOC_PATH_CATEGORIES: readonly string[] = DOC_PATH_RULE.categories

/** Whitelist form for error copy (human-readable; the categories come from the rule file
 *  and are never listed in this file). */
const DOC_PATH_HINT = `${DOC_PATH_CATEGORIES.join('|')}/<文件>.md`

/* ------------------------------------------------------------ block diff（纯函数） */

// 细粒度切块 / 类型+相似度对齐 / 行级 ops 全部在 src/shared/blocks.ts
// （纯函数，浏览器半复用同一实现做渲染态 diff 与单元格级对齐）。
export { diffBlocks, parseBlocks } from './src/shared/blocks.ts'
export type { BlockDiff, BlockType } from './src/shared/blocks.ts'

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

/** 读 POST JSON body（256KB 封顶，review 含逐块注释比工具调用大），非法 JSON 抛错。 */
async function readJsonBody(req: IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += (chunk as Buffer).length
    if (size > 256 * 1024) throw new Error('body 超过 256KB')
    chunks.push(chunk as Buffer)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text === '' ? {} : JSON.parse(text)
}

export function apply(ctx: Context, config?: SuyouKnowledgeConfig): void {
  // t261008-33: shared anchor chain (config.repo -> SANDBAR_REPO -> DEFAULT_REPO) + escape
  // guard (SANDBAR_ANCHOR_MISMATCH before any write) — see repo-anchor.mjs.
  const repo = resolveRepo(config?.repo, DEFAULT_REPO)
  const python = config?.python ?? 'python3'
  const timeoutMs = config?.timeoutMs ?? 30_000

  /**
   * project 解析（全部路由共用）：?project=<key> 或 body.project，必传、无默认值。
   * 缺/形状不合法/未注册 → 回 400 并返回 null。注册表每请求现读（project-registry.ts）。
   */
  function projOf(req: IncomingMessage, res: ServerResponse, body?: any): ProjectEntry | null {
    const url = new URL(req.url ?? '/', 'http://x')
    const key = String(url.searchParams.get('project') ?? body?.project ?? '')
    if (!key) {
      sendJson(res, 400, { ok: false, error: '缺 project 参数（projects.yaml 注册表 key，无默认值）' })
      return null
    }
    let proj: ProjectEntry | undefined
    try {
      proj = findProject(key)
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return null
    }
    if (!proj) {
      sendJson(res, 400, { ok: false, error: `未知项目：${key}（projects.yaml 未注册）` })
      return null
    }
    return proj
  }

  /** t261103-12: the documentation roots in effect for one request (declaration →
   *  resolution; nothing here derives a directory name). */
  function resolutionOf(proj: ProjectEntry): RootsResolution {
    return resolveDocsRoots(proj.key, { repos: proj.dirs, fallbackRepo: primaryDir(proj) })
  }

  /** The review lists a live listing can state: no frontmatter block, status
   *  deprecated, and an `updated:` older than the engine's staleness window. */
  function reviewOfEntries(entries: any[]) {
    const missing: string[] = []
    const deprecated: string[] = []
    const stale: string[] = []
    const horizon = Date.now() - 180 * 24 * 3600 * 1000
    for (const d of entries) {
      if (d?.has_frontmatter === false) missing.push(String(d?.id ?? d?.path ?? ''))
      if (String(d?.status ?? '') === 'deprecated') deprecated.push(String(d?.id ?? d?.path ?? ''))
      const t = typeof d?.updated === 'string' && d.updated !== '' ? Date.parse(d.updated) : NaN
      if (Number.isFinite(t) && t < horizon) stale.push(String(d?.id ?? d?.path ?? ''))
    }
    return { missing_frontmatter: missing, deprecated, stale }
  }

  /**
   * The index answer every consumer gets: the three reader states are always named.
   * - current / stale: entries come from the derived index (stale is LABELLED stale
   *   and names the last build time; it is never passed off as current);
   * - absent / failed: entries are read live from the resolved roots, so a project
   *   that HAS documents is never shown as empty — and the state still says that the
   *   index is missing or that its rebuild failed, with the reason.
   */
  function indexAnswer(proj: ProjectEntry, res: ServedResolution) {
    const served = res
    const read = readIndexStateFor(proj.key, res)
    const live = read.state === 'absent' || read.state === 'failed'
    const docs = live ? liveEntries(res as ServedResolution) : read.entries
    const review = live ? reviewOfEntries(docs) : read.review
    return {
      // legacy keys the current page reads stay valid (generated_at/total/docs/review)
      generated_at: read.builtAt,
      total: docs.length,
      categories: [...new Set(docs.map((d: any) => String(d.category ?? '')))].filter((c) => c !== ''),
      docs,
      review,
      // t261103-12 state face
      state: read.state,
      banner: indexBanner(read),
      built_at: read.builtAt,
      stale_reason: read.staleReason,
      reason: read.reason,
      entries_source: live ? 'roots' : 'index',
      index_path: join(indexDir(proj.key), 'index.json'),
      roots: served.roots.map((r) => ({ id: r.id, repository: r.repository,
        path: r.path, directory: r.directory, state: r.state, projections: r.projections })),
      resolution: { state: served.state, source: served.source,
        declared: served.source === 'declared', declaration: served.declaration,
        reason: served.reason, projections: served.projections },
      empty: false,
    }
  }

  /** Explicit operator rebuild: the ONLY write entry in this plugin's docs face. It
   *  calls the engine builder, which writes into the project's data directory; the
   *  read path never triggers it. */
  async function rebuildIndex(proj: ProjectEntry): Promise<{ ok: boolean; result?: unknown; error?: string; stdout?: string }> {
    const script = join(repo, 'server', 'engine', 'docs_index.py')
    if (!existsSync(script)) {
      return { ok: false, error: `engine docs index builder missing (expected: ${script})` }
    }
    try {
      const { stdout } = await execFileP(
        python, [script, '--project', proj.key, '--trigger', 'operator'],
        { cwd: repo, timeout: timeoutMs })
      return { ok: true, result: await readIndexStateFor(proj.key, resolutionOf(proj)), stdout: stdout.trim() }
    } catch (err: any) {
      const out = String(err?.stdout ?? '').trim()
      return { ok: false, error: String(err?.message ?? err) + (out === '' ? '' : ` (${out})`) }
    }
  }

  /** The resolved root a request targets + the path admitted inside it. Every failure
   *  is answered here with its own named reason (no silent fallback to a default
   *  directory, no empty answer for a missing root). */
  function checkedDocs(req: IncomingMessage, res: ServerResponse,
    proj: ProjectEntry): { p: string; abs: string; docsDir: string; rootId: string;
      repo: string; rootPath: string } | null {
    const url = new URL(req.url ?? '/', 'http://x')
    const p = url.searchParams.get('path') ?? ''
    const res0 = resolutionOf(proj)
    if (res0.state === 'refused') {
      sendJson(res, 200, { ok: true, result: { empty: true, reason: res0.reason }, resolution: { state: res0.state, code: res0.code, reason: res0.reason, looked_for: res0.lookedFor } })
      return null
    }
    // Which root holds this page: an explicit root id wins, otherwise the path itself
    // decides (exactly one holder), and an ambiguous path is refused by name — two
    // roots holding the same relative path never open each other's file.
    const located = locateRoot(res0, p, url.searchParams.get('root'))
    if ('reason' in located) {
      sendJson(res, 404, { ok: false, error: located.reason })
      return null
    }
    const root = located.root
    // Admission is either the legacy category rule (unchanged for today's library) or a
    // safe root-relative path inside the resolved root (a declared root may hold any
    // directory layout). Containment is checked explicitly, never assumed.
    const legacy = DOC_PATH_RE.test(p)
    if (!legacy && !admitsInRoot(root, p)) {
      sendJson(res, 404, { ok: false, error: `path not admitted (allowed: ${DOC_PATH_HINT}, or a safe .md path inside root ${root.id}): ${p}` })
      return null
    }
    const abs = resolve(root.directory, p)
    if (!abs.startsWith(root.directory + sep)) {
      sendJson(res, 404, { ok: false, error: 'path escapes the root (traversal refused)' })
      return null
    }
    return { p, abs, docsDir: root.directory, rootId: root.id, repo: root.repoDir,
      rootPath: root.path }
  }

  async function handleIndex(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    try {
      const resolution = resolutionOf(proj)
      if (resolution.state === 'refused') {
        // A refusal is an ANSWER, not an empty view: the state and the named reason
        // travel with it, and the page must render them instead of "no documents".
        sendJson(res, 200, { ok: true, result: {
          // `empty:true` is the branch the page renders a named reason from; `state`
          // keeps a refusal distinguishable from a genuinely empty root.
          empty: true, state: 'refused', banner: resolution.reason, built_at: '',
          stale_reason: '', reason: resolution.reason, code: resolution.code,
          total: 0, docs: [], categories: [],
          review: { missing_frontmatter: [], deprecated: [], stale: [] },
          entries_source: 'none', roots: [], looked_for: resolution.lookedFor,
          resolution: {
            state: resolution.state, code: resolution.code,
            declaration: resolution.declaration, reason: resolution.reason } } })
        return
      }
      sendJson(res, 200, { ok: true, result: indexAnswer(proj, resolution) })
    } catch (err: any) {
      sendJson(res, 502, { ok: false, error: String(err?.message ?? err) })
    }
  }

  async function handleDoc(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    const checked = checkedDocs(req, res, proj)
    if (!checked) return
    try {
      const content = await readFile(checked.abs, 'utf8')
      sendJson(res, 200, { ok: true, result: { path: checked.p, content } })
    } catch (err: any) {
      if (err?.code === 'ENOENT') {
        sendJson(res, 404, { ok: false, error: `文档不存在: ${checked.p}` })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  async function handleRefresh(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    const r = await rebuildIndex(proj)
    sendJson(res, r.ok ? 200 : 502, r)
  }

  async function handleDiff(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    const checked = checkedDocs(req, res, proj)
    if (!checked) return
    const url = new URL(req.url ?? '/', 'http://x')
    const base = url.searchParams.get('base') ?? 'HEAD'
    // base 只允许 ref/commit 字符，防命令注入（作为单一 argv 传给 git，不加 shell）。
    if (!/^[A-Za-z0-9._~^/-]+$/.test(base) && base !== 'HEAD') {
      sendJson(res, 400, { ok: false, error: 'base 不合法' })
      return
    }
    try {
      let oldText = ''
      let hasBase = false
      try {
        // The path inside git carries the ROOT's repository-relative prefix
        // (t261103-12: the root is resolved, never assumed to be docs/).
        const relInRepo = `${checked.rootPath}/${checked.p}`
        const r = await execFileP('git', ['-C', checked.repo, 'show', `${base}:${relInRepo}`], { timeout: timeoutMs })
        oldText = r.stdout
        hasBase = true
      } catch (gitErr: any) {
        const msg = String(gitErr?.stderr ?? gitErr?.message ?? gitErr)
        if (/bad revision|unknown revision|bad object|invalid object|not a valid object/i.test(msg)) {
          sendJson(res, 400, { ok: false, error: `base 不存在或不是合法 ref: ${base}` })
          return
        }
        oldText = '' // base 下确无此文件 → 视为新增
      }
      const newText = await readFile(checked.abs, 'utf8')
      const blocks = diffBlocks(oldText, newText)
      const changed = blocks.some((b) => b.status !== 'unchanged')
      sendJson(res, 200, { ok: true, result: { path: checked.p, base, hasBase, changed, blocks } })
    } catch (err: any) {
      if (err?.code === 'ENOENT') {
        sendJson(res, 404, { ok: false, error: `文档不存在: ${checked.p}` })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  async function handleReviewGet(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    const checked = checkedDocs(req, res, proj)
    if (!checked) return
    try {
      sendJson(res, 200, { ok: true, result: await loadReview(checked.docsDir, checked.p) })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  async function handleReviewSave(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'POST only' })
      return
    }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err: any) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const proj = projOf(req, res, body)
    if (!proj) return
    const runId = randomUUID().replace(/-/g, '').slice(0, 12)
    const p = typeof body?.path === 'string' ? body.path : ''
    // t261103-12: the review store lives beside the RESOLVED root the document came
    // from (the declaration decides where; this route never assumes docs/).
    const resolution = resolutionOf(proj)
    if (resolution.state === 'refused') {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, resolution.reason)
      sendJson(res, 409, { ok: false, run_id: runId, error: resolution.reason })
      return
    }
    const located = locateRoot(resolution, p, typeof body?.root === 'string' ? body.root : null)
    if ('reason' in located) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, located.reason)
      sendJson(res, 404, { ok: false, run_id: runId, error: located.reason })
      return
    }
    const root = located.root
    const docsDir = root.directory
    if (!DOC_PATH_RE.test(p) && !admitsInRoot(root, p)) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'path not admitted')
      sendJson(res, 404, { ok: false, run_id: runId, error: `path not admitted (allowed: ${DOC_PATH_HINT}, or a safe .md path inside root ${root.id}): ${p}` })
      return
    }
    const base = typeof body?.base === 'string' ? body.base : 'HEAD'
    if (!/^[A-Za-z0-9._~^/-]+$/.test(base) && base !== 'HEAD') {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'base 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'base 不合法' })
      return
    }
    const conclude = body?.conclude as ReviewConclude
    if (!CONCLUDES.includes(conclude)) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'conclude 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: `conclude 必须是 ${CONCLUDES.join(' | ')}` })
      return
    }
    if (!Array.isArray(body?.blocks)) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'blocks 缺/非数组')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'blocks 必须是数组' })
      return
    }
    const blocks: ReviewBlockEntry[] = []
    for (const b of body.blocks as any[]) {
      if (typeof b?.block_key !== 'string' || b.block_key === '') {
        await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'block 缺 block_key')
        sendJson(res, 400, { ok: false, run_id: runId, error: '每个 block 必须带 block_key' })
        return
      }
      const decision = b.decision === 'approve' || b.decision === 'reject' ? b.decision : undefined
      blocks.push({
        block_key: b.block_key,
        summary: typeof b.summary === 'string' ? b.summary.slice(0, 120) : '',
        type: typeof b.type === 'string' ? b.type : '',
        status: typeof b.status === 'string' ? b.status : '',
        decision,
        comment: typeof b.comment === 'string' && b.comment !== '' ? b.comment.slice(0, 2000) : undefined,
      })
    }
    const reviewer = typeof body?.reviewer === 'string' && body.reviewer.trim() !== ''
      ? body.reviewer.trim().slice(0, 40) : 'user'
    const round: ReviewRound = { base, ts: Math.floor(Date.now() / 1000), reviewer, conclude, blocks }
    try {
      const saved = await appendReviewRound(docsDir, p, round)
      const summary = `${proj.key}:${p} 第 ${saved.rounds.length} 轮 conclude=${conclude} 块 ${blocks.length}`
      await audit(runId, 'review.save', { project: proj.key, path: p, base, conclude, blocks: blocks.length }, true, summary)
      ctx.logger.info('sandbar-knowledge: review.save %s（run-id %s）', summary, runId)
      sendJson(res, 200, { ok: true, run_id: runId, result: { path: p, rounds: saved.rounds.length, round } })
    } catch (err: any) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, String(err?.message ?? err))
      sendJson(res, 500, { ok: false, run_id: runId, error: String(err?.message ?? err) })
    }
  }

  /**
   * admin.log 同款审计：append-only JSONL，与 server/tools_registry.py 的
   * audit() 同形同文件（suyou 仓库 server/admin.log——单一审计真源不随项目分流）。
   * 取舍：插件是 node 进程接不到 python admin.py 的 call()，为一条文件写入去
   * spawn python 过重；直接按同一 JSONL schema 追加，响应另带 run-id 可对账。
   */
  async function audit(runId: string, name: string, args: unknown, ok: boolean, summary: string): Promise<void> {
    const rec = JSON.stringify({
      run_id: runId, ts: Math.floor(Date.now() / 1000), actor: 'sandbar-knowledge',
      name, args, ok, summary: summary.length > 800 ? summary.slice(0, 800) + '…' : summary,
    })
    try {
      await appendFile(join(repo, 'server', 'admin.log'), rec + '\n', 'utf8')
    } catch (err: any) {
      ctx.logger.warn('sandbar-knowledge: admin.log 审计写入失败（不影响主流程）：%s', String(err?.message ?? err))
    }
  }

  /** 把路由挂到 webServer（同一 effect，卸载随插件生命周期）。 */
  const attach = (ws: any): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/index', handler: handleIndex }),
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/doc', handler: handleDoc }),
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/refresh', handler: handleRefresh }),
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/diff', handler: handleDiff }),
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/review', handler: handleReviewGet }),
        ws.register({ kind: 'exact', path: '/sandbar-knowledge/api/review/save', handler: handleReviewSave }),
      ]
      return () => { for (const dispose of disposers) dispose() }
    }, 'sandbar-knowledge: api routes')
    ctx.logger.info('sandbar-knowledge: docs 知识库 API 已挂载 /sandbar-knowledge/api/*（project 必传，注册表=projects.yaml）')
  }

  const existing = ctx.get('webServer')
  if (existing !== undefined) {
    attach(existing)
    return
  }
  const dispose = ctx.on('internal/service', (serviceName: string, value: any) => {
    if (serviceName !== 'webServer') return
    dispose()
    attach(value)
  })
}
