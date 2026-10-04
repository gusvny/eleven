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

/**
 * startPluginHarness（t261003-10：生产路由壳缝）——把 **node.ts 的真 apply()** 架在
 * 临时端口上：stub cordis ctx + stub webServer.register，请求流经生产的注册面。
 * 与 startHarness（直转 api.handle）的本质差别：漏注册的路径在这里 404，与生产同形。
 * 环境注入走 process.env（node.ts 直接读 process.env）——start 时设置、close 时还原，
 * 绝不残留。端口缺省 0=内核分配，永不撞 3099/7233；close() 收口服务器并还原 env。
 */
export async function startPluginHarness({ port = 0, panelDir, watchdogDir, adminLogPath } = {}) {
  if (!panelDir) throw new Error('startPluginHarness 需要 panelDir（隔离目录注入点；watchdogDir 可选）')
  const saved = {}
  const setEnv = (k, v) => { saved[k] = process.env[k]; if (v === undefined) delete process.env[k]; else process.env[k] = v }
  setEnv('HOME', '/nonexistent-home')
  setEnv('SANDBAR_PANEL_DIR', panelDir)
  setEnv('SANDBAR_WATCHDOG_DIR', watchdogDir)
  if (adminLogPath !== undefined) setEnv('SANDBAR_ADMIN_LOG', adminLogPath)

  const mod = await import('./node.ts')
  const routes = new Map()
  const ws = { register: (o) => { routes.set(o.path, o.handler); return () => routes.delete(o.path) } }
  const fakeCtx = {
    get: () => ws,
    on: () => () => {},
    effect: (fn) => { fn(); return () => {} },
    logger: { info: () => {}, warn: () => {} },
  }
  mod.apply(fakeCtx, {})

  const server = createServer(async (req, res) => {
    try {
      const u = new URL(req.url ?? '/', 'http://x')
      const handler = routes.get(u.pathname)
      if (!handler) { sendJson(res, 404, { ok: false, error: `未注册路由（生产同形 404）：${u.pathname}` }); return }
      await handler(req, res)
    } catch (e) {
      sendJson(res, 500, { ok: false, error: String(e instanceof Error ? e.message : e) })
    }
  })
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', () => resolve()) })
  const addr = server.address()
  return {
    base: `http://127.0.0.1:${addr.port}`,
    registeredRoutes: [...routes.keys()],
    async close() {
      await new Promise((resolve) => server.close(() => resolve()))
      for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete process.env[k]; else process.env[k] = v }
    },
  }
}

// workbenchStub（t260929-22 GAP B 场景缝）：模拟「普通生产形态控制台」——
// 同一台服务器上 workbench 只读端点在场、且**没有任何基址配置**（无 env 无 config），
// grants 只能靠请求来源推同源基址解析。workflows 桩 payload 可注入（默认两条模板）。
export async function startHarness({ port = 0, panelDir, watchdogDir, workbenchBase = '', workbenchStub = false, sameOriginWorkbench = false, workflows = null } = {}) {
  if (!panelDir || !watchdogDir) throw new Error('startHarness 需要 panelDir 与 watchdogDir（隔离目录注入点）')
  const env = {
    HOME: '/nonexistent-home',
    SANDBAR_PANEL_DIR: panelDir,
    SANDBAR_WATCHDOG_DIR: watchdogDir,
    SANDBAR_WORKBENCH_BASE: (workbenchStub || sameOriginWorkbench) ? '' : workbenchBase,
  }
  const api = createApi(env, { workbenchBase: (workbenchStub || sameOriginWorkbench) ? undefined : (workbenchBase || undefined) })

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
      if ((workbenchStub || sameOriginWorkbench) && method === 'GET' && u.pathname === '/sandbar-workbench/api/wf/workflows') {
        // 260930 直修（宿主令）：桩默认改成**真端点的形状** `{ok:true, result:[…]}`——
        // 旧默认喂 `{workflows:[…]}`，恰是提取器认的那种 ⇒ 桩与真端点分歧不了，
        // Grants 页签在生产恒降级而测试全绿（与 t260929-07 看板读取器同族）。
        sendJson(res, 200, workflows ?? { ok: true, result: [
          { id: 'dev-lane', name: 'dev-lane', kind: 'dev', has_human_gate: true },
          { id: 'inspection', name: 'inspection', kind: 'inspection', has_human_gate: false },
        ] })
        return
      }
      if (u.pathname.startsWith(PANEL_ROUTE + '/api/')) {
        const r = await api.handle(method, u.pathname, u.searchParams, body, 'http://' + (req.headers.host ?? ''))
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
