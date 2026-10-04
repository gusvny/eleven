/**
 * sandbar-executor-panel —— 执行器面板（epic project-executor 第四片，t260929-03）宿主半插件。
 *
 * 是什么：宿主的「脸」——五个 tab（Overview · Requests · Alerts · Ledger · Settings）、
 * 请求主从视图、**页面产声的 beep**（dsh 无发声能力，epic 实证零命中——声音只能由
 * 控制台页面出）、带溯源与写时校验的 Settings。守望者（t260928-28，已合并）算状态面，
 * 本插件只消费 /sandbar-watchdog/api/status，绝不重算、绝不改写守望者本体（out-of-scope）。
 *
 * 挂载与降级（KI-079 族自述纪律）：
 *  - web profile：静态页 + 自有 API 挂 dsh webServer（/sandbar-executor-panel*）；
 *  - headless profile：无 webServer——面板缺席是显式事实（headless 本来没有页面），
 *    本插件待机，不占任何路由；
 *  - 绝不重启/停止/占用控制台（3099 是用户面）；测试走隔离 bench，不触 3099。
 *
 * 全终态：路由注销收在 ctx.effect dispose；本插件无常驻定时器（轮询在浏览器侧）。
 * API 核在 src/host/api.ts（HTTP 解耦，UT 直打 API 层）。
 */

import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Context } from '@deepseek-ai/cordis'

import { createApi, allPanelProjects, PANEL_API_ROUTES } from './src/host/api.ts'
import { PANEL_HTML, PANEL_ROUTE } from './src/host/panel-page.ts'
import { createQuestionBridge, makeRegistryProjectResolver } from './src/host/question-bridge.ts'
import { fsLedgerIo } from './src/host/requests.ts'
import { readFileSync } from 'node:fs'

export const name = 'sandbar-executor-panel'
// webServer 只在 web profile 存在；headless 下待机（无面板面可挂）。
export const inject: string[] = []

export interface ExecutorPanelPluginConfig {
  /** workbench 模板事实端点基址（grants 派生用；缺省同源相对路径）。 */
  workbenchBase?: string
}

function sendHtml(res: ServerResponse, html: string): void {
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' })
  res.end(html)
}

function sendJson(res: ServerResponse, status: number, json: Record<string, unknown>): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(json))
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (c: Buffer) => {
      size += c.length
      if (size > 1_000_000) { reject(new Error('request body too large (>1MB)')); req.destroy(); return }
      chunks.push(c)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

/** 请求来源基址（grants 同源缺省的取材点；t260929-22 GAP B）：`http://<Host 原样>`，无 Host=空。 */
function originOf(req: IncomingMessage): string {
  const host = req.headers.host
  return typeof host === 'string' && host !== '' ? 'http://' + host : ''
}

export function apply(ctx: Context, config: ExecutorPanelPluginConfig = {}): void {
  const api = createApi(process.env, {
    workbenchBase: config.workbenchBase ?? process.env.SANDBAR_WORKBENCH_BASE ?? undefined,
  })

  // 问题桥（t261001-23，KI-181）：把会话级 ask_user_question 镜像进面板请求账——
  // 「看和问」的问在这套部署上原本无处交付（真会话自锁 13+ 分钟，Requests 0 行）。
  // 纯 cordis 监听者，不依赖 webServer：headless/web 都生效；面板缺席时账仍可经
  // API/文件被消费。挂载失败（ctx.on 不可用）显式点名日志，绝不静默。
  const bridge = createQuestionBridge({
    io: fsLedgerIo,
    env: process.env,
    // 键清单与文件根同住 projects 根（allPanelProjects 的根=SANDBAR_PANEL_DIR||~/.sandbar/projects；
    // 反查 project.yaml 也读同一根——SANDBAR_PROJECTS_DIR 的既有分叉是历史欠账，不在此票扩散）。
    resolveProject: makeRegistryProjectResolver(process.env, (env) => allPanelProjects(env), (p) => readFileSync(p, 'utf8')),
    onEvent: (ev) => ctx.logger.info('[question-bridge] %s %s', ev.kind, ev.detail),
  })
  if (typeof ctx.on === 'function') {
    ctx.effect(() => {
      const dispose = ctx.on('user-questions/request', bridge as never)
      return () => { try { dispose() } catch { /* 宿主已卸载=已收口 */ } }
    }, 'sandbar-executor-panel: question bridge（ask_user_question → 请求账）')
    ctx.logger.info('sandbar-executor-panel: question bridge 已挂载（user-questions/request → requests.jsonl）')
  } else {
    ctx.logger.warn('sandbar-executor-panel: ctx.on 不可用——question bridge 未挂载（ask_user_question 将无处交付，KI-181 形态）')
  }

  const attach = (ws: { register: (o: { kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void }): void => {
    ctx.effect(() => {
      // 路由注册=路由表循环（t261003-10）：不再逐条手写（旧写法漏挂 /api/actions、
      // /api/projects——生产 404 的根因）。表=api.ts PANEL_API_ROUTES 单一真源，
      // route-parity UT 机械锁「表内每条都可达、表外每条都 404」。
      const disposers = [
        // 静态页（零构建步骤：页面即本文件产出的 HTML；宿主交接=重启装载后纯浏览器刷新）。
        ws.register({ kind: 'exact', path: PANEL_ROUTE, handler: async (_req, res) => sendHtml(res, PANEL_HTML) }),
        ws.register({ kind: 'exact', path: PANEL_ROUTE + '/', handler: async (_req, res) => sendHtml(res, PANEL_HTML) }),
        ...PANEL_API_ROUTES.map((route) =>
          ws.register({
            kind: 'exact', path: route.path,
            handler: async (req, res) => {
              const method = req.method ?? 'GET'
              const q = new URL(req.url ?? '/', 'http://x').searchParams
              const body = (method === 'POST' || method === 'PUT' || method === 'DELETE') ? await readBody(req) : ''
              // KI-193：凭据原料原样进 API 层（写面凭据门在 api.handle，GET 不设门）。
              const auth = { cookie: req.headers.cookie, host: req.headers.host }
              const r = await api.handle(method, route.path, q, body, originOf(req), auth)
              sendJson(res, r.status, r.json)
            },
          }),
        ),
      ]
      return () => { for (const d of disposers) d() }
    }, 'sandbar-executor-panel: panel routes')
    ctx.logger.info('sandbar-executor-panel: 面板已挂载 %s（五 tab/请求账/页内 beep/Settings 写时校验）', PANEL_ROUTE)
  }

  // 与 watchdog/workbench 同款：webServer 可能已在（直接挂）或后到（等 internal/service）；
  // headless 永远等不到——待机即正确行为（headless 形态本来没有页面）。
  const existing = ctx.get('webServer') as unknown as Parameters<typeof attach>[0] | undefined
  if (existing !== undefined) {
    attach(existing)
  } else {
    ctx.on('internal/service', (serviceName: string, value: unknown) => {
      if (serviceName !== 'webServer') return
      attach(value as Parameters<typeof attach>[0])
    })
  }
}
