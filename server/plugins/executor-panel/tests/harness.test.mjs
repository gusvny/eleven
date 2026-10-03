/**
 * harness.test.mjs —— 插件测试缝 UT：startHarness 起**真 HTTP**（内核分配端口，
 * 零 3099/7233），验证 harness.mjs 与 node.ts 走同一 API 核与同一静态页常量，
 * 全终态 close 后端口收口。这是插件目录内的 UT（run_tests 执行），不是集成入口。
 */
import { assert, done, freshDir, cleanup, isolatedEnv } from './lib.mjs'
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'

let n = 0
const mod = await import('../harness.mjs')
assert(typeof mod.startHarness === 'function' && typeof mod.PANEL_PAGE_HTML === 'string', 'harness exports startHarness + PANEL_PAGE_HTML')

const wd = freshDir(), pan = freshDir()
const H = await mod.startHarness({ port: 0, panelDir: pan, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
try {
  // 页面路由 = 静态页常量（与 node.ts 挂载同一真源）。
  const page = await fetch(H.base + '/sandbar-executor-panel')
  const html = await page.text()
  assert(page.status === 200 && html.startsWith('<!doctype html>') && html.includes('<title>Executor</title>'), 'GET panel route serves the real page')
  // API 面：append → read（top-level rows）→ answer。
  const app = await fetch(H.base + '/sandbar-executor-panel/api/requests', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ project: 'alpha', kind: 'sign', question: 'Sign t-1?' }) })
  assert(app.status === 200, 'harness append works over real HTTP')
  const list = await (await fetch(H.base + '/sandbar-executor-panel/api/requests?project=alpha')).json()
  assert(list.ok === true && Array.isArray(list.rows) && list.rows.length === 1 && list.rows[0].status === 'waiting', 'harness read exposes waiting row')
  const ans = await fetch(H.base + '/sandbar-executor-panel/api/requests/answer', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ project: 'alpha', id: list.rows[0].id, answer: 'ok' }) })
  assert(ans.status === 200, 'harness answer works over real HTTP')
  // grants 走死端口 → 显式降级位（不 500）。
  const g = await (await fetch(H.base + '/sandbar-executor-panel/api/grants?project=alpha')).json()
  assert(g.degraded === true && g.grants.ok === false, 'harness grants unreachable = explicit degraded, not 500')
  // settings 保存往返（盘上真落盘进注入目录）。
  const { readFileSync, existsSync } = await import('node:fs')
  const saved = await (await fetch(H.base + '/sandbar-executor-panel/api/settings?project=alpha', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ declaration: { stall_minutes: 9 } }) })).json()
  assert(saved.saved === true && existsSync(join(wd, 'alpha', 'watchdog.json')) && readFileSync(join(wd, 'alpha', 'watchdog.json'), 'utf8').includes('9'), 'harness save lands in the injected watchdog dir')
} finally {
  await H.close()
}
// 缺参数=显式抛错（协议刚性）。
let threw = false
try { await mod.startHarness({}) } catch { threw = true }
assert(threw, 'startHarness without dirs throws explicitly')

cleanup([wd, pan])
n += 8
done(n)
