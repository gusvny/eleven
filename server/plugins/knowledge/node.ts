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
 *                                        path 白名单 design|content|ops|reference/*.md，
 *                                        防穿路径）
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
import { existsSync } from 'node:fs'
import { appendFile, readFile, stat } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'
import { findProject, primaryDir, type ProjectEntry } from '../../project-registry.ts'
import { diffBlocks } from './src/shared/blocks.ts'
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

/** 允许直读的 docs 相对路径（四分类目录下的一层 .md），防穿路径。 */
const DOC_PATH_RE = /^(design|content|ops|reference)\/[^/]+\.md$/

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
  const repo = config?.repo ?? process.env.SANDBAR_REPO ?? DEFAULT_REPO
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

  /** index.json 缓存：按项目分键、按 mtime 失效，避免每次请求都读盘解析。 */
  const indexCache = new Map<string, { mtimeMs: number; data: unknown }>()

  /** 读项目 docs/index.json；缺失返回 null（调用方走人话降级，不再 502）。 */
  async function readIndex(proj: ProjectEntry): Promise<unknown | null> {
    const indexJson = join(primaryDir(proj), 'docs', 'index.json')
    let st
    try {
      st = await stat(indexJson)
    } catch {
      return null
    }
    const hit = indexCache.get(proj.key)
    if (hit && hit.mtimeMs === st.mtimeMs) return hit.data
    const data = JSON.parse(await readFile(indexJson, 'utf8'))
    indexCache.set(proj.key, { mtimeMs: st.mtimeMs, data })
    return data
  }

  /** 重建 index（spawn 项目自己的 build_index.py，幂等）。 */
  async function rebuildIndex(proj: ProjectEntry): Promise<{ ok: true; result: unknown; stdout: string } | { ok: boolean; error: string }> {
    const primary = primaryDir(proj)
    const script = join(primary, 'docs', 'scripts', 'build_index.py')
    if (!existsSync(script)) {
      return { ok: false, error: `项目 ${proj.key} 没有 docs/scripts/build_index.py（期望路径：${script}）` }
    }
    try {
      const { stdout } = await execFileP(python, [script], { cwd: primary, timeout: timeoutMs })
      // 重建后 index 内容变了，清缓存让下次 readIndex 重读。
      indexCache.delete(proj.key)
      return { ok: true, result: await readIndex(proj), stdout: stdout.trim() }
    } catch (err: any) {
      return { ok: false, error: String(err?.message ?? err) }
    }
  }

  /** 项目 docs 目录 + path 白名单 + 防穿路径，三合一；不合法已回错误并返回 null。 */
  function checkedDocs(req: IncomingMessage, res: ServerResponse, proj: ProjectEntry): { p: string; abs: string; docsDir: string } | null {
    const url = new URL(req.url ?? '/', 'http://x')
    const p = url.searchParams.get('path') ?? ''
    if (!DOC_PATH_RE.test(p)) {
      sendJson(res, 404, { ok: false, error: 'path 不合法（只允许 design|content|ops|reference/<文件>.md）' })
      return null
    }
    const docsDir = join(primaryDir(proj), 'docs')
    const abs = resolve(docsDir, p)
    if (!abs.startsWith(docsDir + sep)) {
      sendJson(res, 404, { ok: false, error: 'path 越界（穿路径拒绝）' })
      return null
    }
    return { p, abs, docsDir }
  }

  async function handleIndex(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const proj = projOf(req, res)
    if (!proj) return
    try {
      const data = await readIndex(proj)
      if (data === null) {
        sendJson(res, 200, {
          ok: true,
          result: { empty: true, reason: `项目 ${proj.name}（${proj.key}）还没有 docs 知识库（期望路径：${join(primaryDir(proj), 'docs', 'index.json')}）` },
        })
        return
      }
      sendJson(res, 200, { ok: true, result: data })
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
        // 注意：git 里的真路径带 docs/ 前缀（DOC_PATH_RE 的 p 是相对 docs/ 的）。
        const r = await execFileP('git', ['-C', primaryDir(proj), 'show', `${base}:docs/${checked.p}`], { timeout: timeoutMs })
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
    const docsDir = join(primaryDir(proj), 'docs')
    // run-id 先定，审计与响应同号（成功失败都留痕）。
    const runId = randomUUID().replace(/-/g, '').slice(0, 12)
    const p = typeof body?.path === 'string' ? body.path : ''
    if (!DOC_PATH_RE.test(p)) {
      await audit(runId, 'review.save', { project: proj.key, path: p }, false, 'path 不合法')
      sendJson(res, 404, { ok: false, run_id: runId, error: 'path 不合法（只允许 design|content|ops|reference/<文件>.md）' })
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
