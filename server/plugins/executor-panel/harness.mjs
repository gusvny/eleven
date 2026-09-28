/**
 * harness.mjs —— executor-panel 集成场景测试缝（协议锚定 lib_panel_harness.mjs 头注；
 * watchdog harness.mjs 同款先例）：把插件**真实的 API 处理面**（与 node.ts 挂载同一
 * createApi 核 + 同一静态页常量）架在临时端口上。panelDir/watchdogDir 即
 * SANDBAR_PANEL_DIR / SANDBAR_WATCHDOG_DIR 语义注入点；workbenchBase 是 grants
 * 推导的模板事实远端基址（测试可指死端口或本地桩）。端口缺省 0=内核分配，
 * 永不撞 3099/7233。close() 收口服务器，零残留（本插件无常驻定时器）。
 */
import { createServer } from 'node:http'

import { createApi } from './src/host/api.ts'
import { PANEL_PAGE_HTML, PANEL_ROUTE } from './src/host/panel-page.ts'

export { PANEL_PAGE_HTML, PANEL_ROUTE }

function sendJson(res, status, json) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(json))
}

export async function startHarness({ port = 0, panelDir, watchdogDir, workbenchBase = '' } = {}) {
  if (!panelDir || !watchdogDir) throw new Error('startHarness 需要 panelDir 与 watchdogDir（隔离目录注入点）')
  const env = {
    HOME: '/nonexistent-home',
    SANDBAR_PANEL_DIR: panelDir,
    SANDBAR_WATCHDOG_DIR: watchdogDir,
    SANDBAR_WORKBENCH_BASE: workbenchBase,
  }
  const api = createApi(env, { workbenchBase: workbenchBase || undefined })

  const server = createServer(async (req, res) => {
    try {
      const u = new URL(req.url ?? '/', 'http://x')
      const method = req.method ?? 'GET'
      let body = ''
      if (method === 'POST' || method === 'PUT' || method === 'DELETE') {
        for await (const c of req) body += c
      }
      if (u.pathname === PANEL_ROUTE || u.pathname === PANEL_ROUTE + '/') {
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' })
        res.end(PANEL_PAGE_HTML)
        return
      }
      if (u.pathname.startsWith(PANEL_ROUTE + '/api/')) {
        const r = await api.handle(method, u.pathname, u.searchParams, body)
        sendJson(res, r.status, r.json)
        return
      }
      sendJson(res, 404, { ok: false, error: `未知路由：${u.pathname}` })
    } catch (e) {
      sendJson(res, 500, { ok: false, error: String(e instanceof Error ? e.message : e) })
    }
  })

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => resolve())
  })
  const addr = server.address()
  return {
    base: `http://127.0.0.1:${addr.port}`,
    async close() {
      await new Promise((resolve) => server.close(() => resolve()))
    },
  }
}
