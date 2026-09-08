/**
 * sandbar-admin-ui —— 溯游管理台的 dsh UI 插件（宿主半 / node）。
 *
 * 职责：在 dsh 自己的 webServer 上挂管理台 API，供浏览器半与 sandbar-providers
 * 「模型」页签（lib/client.js）同源 fetch 使用：
 *
 *   GET  /sandbar-admin/api/tools   → admin.py tools 的工具表 + 需确认名单
 *   POST /sandbar-admin/api/call    → {name, args, confirm?} → admin.py call；
 *                                   命中 needsApproval（默认 params_set）且未带
 *                                   confirm:true 时回 409 {needsConfirm:true}，
 *                                   由 UI 弹人工确认后重发（面板通道的两阶段提交）
 *   GET  /sandbar-admin/api/audit?n → server/admin.log 末 n 行（JSONL 原样解析）
 *   GET  /sandbar-admin/api/routes?project=<key>
 *                                 → 模型路由视图（M12，只读）：解析 <项目主目录>/server/
 *                                   model-routes.yaml（真源）+ 扫生成 preset 的
 *                                   dispatch_* 烘焙实例（生效态）→ 路由表 + 查表
 *                                   结果 + 生效实例；本接口只读不改。
 *                                   多项目化（260823）：project 必传、无默认值（projects.yaml
 *                                   注册表 key），路由表按项目主目录解析；项目无该文件走
 *                                   {ok:false, error} 人话降级。
 *   POST /sandbar-admin/api/routes  → M13 保存：{project, table}（default/roles 的
 *                                   provider|model，schema 锁死可编辑槽位）→
 *                                   外科补丁写 <项目主目录> 的 model-routes.yaml（写前备份
 *                                   /tmp；保存即生效——运行时查表）。由 sandbar-providers
 *                                   「模型」页签「路由表」分区调用。
 *
 * M13（t260822-m13-model-routes-edit）：浏览器半不再注册 settings.section
 * （「溯游」子菜单消失），本文件 API 全部保留——GET /sandbar-admin/api/routes 供
 * providers「模型」页签消费，POST 承担保存。
 *
 * 每次调用仍经 runAdminCli spawn admin.py——run-id 审计单一真源保持在
 * python server/admin.log（与模型通道 sandbar-tools 一致）。
 *
 * headless profile 没有 webServer 服务：apply 静默待命（internal/service 事件
 * 等不到就什么都不挂），不报错不阻塞。
 *
 * repo 解析顺序：config.repo → SANDBAR_REPO → 按本文件位置推导
 * （<repo>/server/plugins/ui/node.ts 上三级）。无任何机器绝对路径写死。
 */

import { readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import { runAdminCli } from '../../sandbar-tools.ts'
import { findProject, primaryDir } from '../../project-registry.ts'
import { buildRoutesView, initRoutesTable, saveRoutesTable } from './src/host/routes.ts'

export const name = 'sandbar-admin-ui'
// webServer 只存在于 web profile；headless 下本插件待机即可，故不走 inject 硬依赖。
export const inject: string[] = []

/** 本文件固定落在 <repo>/server/plugins/ui/ 下，上三级即仓库根。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface SuyouAdminUiConfig {
  /** 溯游仓库根。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 子进程超时（毫秒），默认 300000。 */
  timeoutMs?: number
  /** 面板直调需人工确认的工具名单，默认 ['params_set']。 */
  needsApproval?: string[]
}

/** 读 POST JSON body（64KB 封顶），非法 JSON 抛错。 */
async function readJsonBody(req: IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += (chunk as Buffer).length
    if (size > 64 * 1024) throw new Error('body 超过 64KB')
    chunks.push(chunk as Buffer)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text === '' ? {} : JSON.parse(text)
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

export function apply(ctx: Context, config?: SuyouAdminUiConfig): void {
  const repo = config?.repo ?? process.env.SANDBAR_REPO ?? DEFAULT_REPO
  const cli = { repo, python: config?.python, timeoutMs: config?.timeoutMs }
  const needsApproval = new Set(config?.needsApproval ?? ['params_set'])
  const auditLog = join(repo, 'server', 'admin.log')

  /** 工具表缓存：启动后首取现取，失败重试不缓存。 */
  let toolsCache: any[] | undefined

  async function handleTools(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      if (toolsCache === undefined) {
        const tools = await runAdminCli(cli, ['tools'])
        if (!Array.isArray(tools)) throw new Error('admin.py tools 输出不是数组')
        toolsCache = tools
      }
      sendJson(res, 200, { ok: true, tools: toolsCache, needsApproval: [...needsApproval] })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleCall(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'POST only' })
      return
    }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const toolName = typeof body?.name === 'string' ? body.name : ''
    if (toolName === '') {
      sendJson(res, 400, { ok: false, error: '缺少工具名 name' })
      return
    }
    // 两阶段提交（面板通道）：破坏性工具须 UI 人工确认后带 confirm:true 重发。
    if (needsApproval.has(toolName) && body.confirm !== true) {
      sendJson(res, 409, {
        ok: false,
        needsConfirm: true,
        error: `${toolName} 是写操作，需人工确认后才会执行`,
      })
      return
    }
    try {
      const result = await runAdminCli(cli, ['call', toolName, JSON.stringify(body.args ?? {})])
      // ok:false 也是正常结构化结果（含 run_id），原样透传由 UI 展示。
      sendJson(res, 200, result)
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleAudit(req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const url = new URL(req.url ?? '/', 'http://x')
      const n = Math.max(1, Math.min(500, Number(url.searchParams.get('n')) || 100))
      let text = ''
      try {
        text = await readFile(auditLog, 'utf8')
      } catch (err: any) {
        if (err?.code === 'ENOENT') {
          sendJson(res, 200, { ok: true, path: auditLog, lines: [] })
          return
        }
        throw err
      }
      const lines = text.split('\n').filter(line => line.trim() !== '').slice(-n)
      const entries = lines.map(raw => {
        try {
          return JSON.parse(raw)
        } catch {
          return { raw }
        }
      })
      sendJson(res, 200, { ok: true, path: auditLog, lines: entries })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** project 解析（routes 两条路由共用）：?project=/body.project 必传、无默认值。 */
  function projOf(req: IncomingMessage, res: ServerResponse, body?: any): string | null {
    const url = new URL(req.url ?? '/', 'http://x')
    const key = String(url.searchParams.get('project') ?? body?.project ?? '')
    if (!key) {
      sendJson(res, 400, { ok: false, error: '缺 project 参数（projects.yaml 注册表 key，无默认值）' })
      return null
    }
    let proj
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
    return primaryDir(proj)
  }

  /** 模型路由视图（M12，只读）：解析 <项目主目录> 的 model-routes.yaml + 扫生成 preset 烘焙实例。
   *  解析失败/读取故障 → 200 {ok:false, error}（UI 显示原因不渲染空表），不抛 500；
   *  表缺失 → 200 {ok:true, result.uninitialized:true, template_source}（t260906-01
   *  无表引导态：缺失=未初始化非错误，UI 渲染引导卡片 + 生成默认表动作）。 */
  async function handleRoutes(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const primary = projOf(req, res)
    if (primary === null) return
    try {
      const view = await buildRoutesView(primary)
      if (view.error !== undefined) {
        sendJson(res, 200, { ok: false, error: view.error })
        return
      }
      sendJson(res, 200, { ok: true, result: view })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 模型路由保存（M13，写）：{table} → saveRoutesTable 写 model-routes.yaml。
   *  载荷非法/表缺失/备份失败 → 200 {ok:false, error}（不抛 500）；
   *  成功 → {ok:true, result:{written, routes_file, backup, changed, regenerate}}。 */
  async function handleRoutesSave(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'POST only' })
      return
    }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const primary = projOf(req, res, body)
    if (primary === null) return
    if (body?.table === undefined || typeof body.table !== 'object') {
      sendJson(res, 400, { ok: false, error: '缺少保存载荷 table（{default?, roles?}）' })
      return
    }
    const result = await saveRoutesTable(primary, body.table)
    if (result.error !== undefined) {
      sendJson(res, 200, { ok: false, error: result.error })
      return
    }
    sendJson(res, 200, { ok: true, result })
  }

  /** 模型路由初始化（t260906-01，写）：POST /sandbar-admin/api/routes/init
   *  项目主目录无 model-routes.yaml 时从引擎仓默认表拷贝生成（引导态动作）。
   *  表已存在=200 {ok:false}（零覆盖拒收）；成功 → {ok:true, result:{routes_file}}。
   *  注意（R4）：本端点落在 console 内存服务端——宿主重启 3099 后才生效（KI-052 同族）。 */
  async function handleRoutesInit(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'POST only' })
      return
    }
    let body: any = {}
    try {
      const raw = await readJsonBody(req)
      if (raw && typeof raw === 'object') body = raw
    } catch {
      // init 无必需载荷：空体/非 JSON 容忍（project 可在 query string）。
    }
    const primary = projOf(req, res, body)
    if (primary === null) return
    const result = await initRoutesTable(primary)
    if (!result.ok) {
      sendJson(res, 200, { ok: false, error: result.error })
      return
    }
    sendJson(res, 200, { ok: true, result: { routes_file: result.routes_file } })
  }

  /** 把四条路由挂到 webServer（同一 effect，卸载随插件生命周期）。 */
  const attach = (ws: any): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/tools', handler: handleTools }),
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/call', handler: handleCall }),
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/audit', handler: handleAudit }),
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/routes', handler: handleRoutes }),
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/routes/init', handler: handleRoutesInit }),
        ws.register({ kind: 'exact', path: '/sandbar-admin/api/routes/save', handler: handleRoutesSave }),
      ]
      return () => { for (const dispose of disposers) dispose() }
    }, 'sandbar-admin-ui: admin api routes')
    ctx.logger.info('sandbar-admin-ui: 管理台 API 已挂载 /sandbar-admin/api/*（repo=%s，面板确认名单=%s）',
      repo, [...needsApproval].join(',') || '空')
  }

  // webServer 可能先已提供（直接取），也可能后到（等 internal/service 事件）；
  // headless 永远等不到——待机即正确行为。
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
