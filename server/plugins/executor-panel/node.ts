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

import { createApi } from './src/host/api.ts'
import { PANEL_HTML, PANEL_ROUTE } from './src/host/panel-page.ts'

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

export function apply(ctx: Context, config: ExecutorPanelPluginConfig = {}): void {
  const api = createApi(process.env, {
    workbenchBase: config.workbenchBase ?? process.env.SANDBAR_WORKBENCH_BASE ?? undefined,
  })

  const attach = (ws: { register: (o: { kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void }): void => {
    ctx.effect(() => {
      const disposers = [
        // 静态页（零构建步骤：页面即本文件产出的 HTML；宿主交接=重启装载后纯浏览器刷新）。
        ws.register({ kind: 'exact', path: PANEL_ROUTE, handler: async (_req, res) => sendHtml(res, PANEL_HTML) }),
        ws.register({ kind: 'exact', path: PANEL_ROUTE + '/', handler: async (_req, res) => sendHtml(res, PANEL_HTML) }),
        // 自有 API（requests 账 / settings 写面 / grants 派生面；核在 api.ts，UT 直打）。
        ws.register({
          kind: 'exact', path: PANEL_ROUTE + '/api/requests',
          handler: async (req, res) => {
            const q = new URL(req.url ?? '/', 'http://x').searchParams
            const body = req.method === 'POST' ? await readBody(req) : ''
            const r = await api.handle(req.method ?? 'GET', PANEL_ROUTE + '/api/requests', q, body)
            sendJson(res, r.status, r.json)
          },
        }),
        ws.register({
          kind: 'exact', path: PANEL_ROUTE + '/api/requests/answer',
          handler: async (req, res) => {
            if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: '应答面仅 POST' }); return }
            const q = new URL(req.url ?? '/', 'http://x').searchParams
            const r = await api.handle('POST', PANEL_ROUTE + '/api/requests/answer', q, await readBody(req))
            sendJson(res, r.status, r.json)
          },
        }),
        ws.register({
          kind: 'exact', path: PANEL_ROUTE + '/api/settings',
          handler: async (req, res) => {
            const q = new URL(req.url ?? '/', 'http://x').searchParams
            const body = req.method === 'POST' ? await readBody(req) : ''
            const r = await api.handle(req.method ?? 'GET', PANEL_ROUTE + '/api/settings', q, body)
            sendJson(res, r.status, r.json)
          },
        }),
        ws.register({
          kind: 'exact', path: PANEL_ROUTE + '/api/grants',
          handler: async (req, res) => {
            const q = new URL(req.url ?? '/', 'http://x').searchParams
            const r = await api.handle(req.method ?? 'GET', PANEL_ROUTE + '/api/grants', q, '')
            sendJson(res, r.status, r.json)
          },
        }),
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
