// lib_panel_stub.mjs — t261003-09 场景族共享缝（复用 t261003-06 lib_panel_seam 的
// harness/PANEL_PAGE 缝协议，不另立契约）。只做装载/夹具/三态出口，零行为断言。
//
// servePanelHtml({ html, query })：本地 http 起一面板页（PANEL_PAGE_HTML 原文），
// API 走 page.route 拦截到独立桩端（同 t261003-06 page-redesign 架缝）。
// 三态纪律（t260904-12）：缝缺席=FAIL 点名（TDD 期红属预期）；浏览器族缺
// playwright/chromium=ENV_FAIL exit 2（KI-036 家族）。
import { createServer } from 'node:http'
export { REPO, PANEL_PAGE_PATH, makeCase, makeIsoDir } from '../t261003-06/lib_panel_seam.mjs'

/** 主树 playwright-core 装载（worktree 沙箱回落主树，t261003-06 同款）。 */
export async function loadPw(REPO) {
  const { existsSync } = await import('node:fs')
  const { execFileSync } = await import('node:child_process')
  const { join, resolve } = await import('node:path')
  const { pathToFileURL } = await import('node:url')
  let main = REPO
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) main = resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

/** 面板 HTML 本地面板服务（同源取数走相对路径；API 由 page.route 打到桩端）。 */
export async function servePanel(html) {
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  return { port: local.address().port, close: () => local.close() }
}

/** 独立 API 桩端（t261003-06 桩形状 + 本票面：grants 可注入 executor_sessions）。 */
export async function serveApiStub(fix = {}) {
  const stub = createServer((req, res) => {
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    const u = new URL(req.url, 'http://x')
    if (u.pathname.endsWith('/api/requests')) return json({ rows: fix.requests ?? [] })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json(fix.grants ?? { granted_count: 0, total: 6, executor_sessions: [], session_state: 'none', note: '' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: fix.recent ?? [] })
    if (u.pathname.endsWith('/api/watchdog/status') || u.pathname === '/status') return json({ declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x', unreadable: false, counts: { lines: 1, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } })
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  return { port: stub.address().port, close: () => stub.close() }
}

/** 浏览器页开面板页（拦截 API→桩；query 透传 ?project= / ?theme=）。 */
export async function openPanel(pw, { html, apiPort, query, viewport }) {
  const { port, close } = await servePanel(html)
  const browser = await pw.chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: viewport ?? { width: 1280, height: 900 } })
  const page = await ctx.newPage()
  await page.route('**/api/**', (route) =>
    route.continue({ url: `http://127.0.0.1:${apiPort}` + new URL(route.request().url()).pathname }))
  await page.goto(`http://127.0.0.1:${port}/${query}`)
  await page.waitForTimeout(600)
  return { browser, ctx, page, closeAll: async () => { await browser.close().catch(() => {}); close() } }
}

/** sRGB → 相对亮度（WCAG 定义；主题明暗判定的用户可感知口径）。 */
export function luminance(rgbStr) {
  const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(rgbStr || '')
  if (!m) return null
  const lin = (v) => { const s = Number(v) / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(m[1]) + 0.7152 * lin(m[2]) + 0.0722 * lin(m[3])
}
