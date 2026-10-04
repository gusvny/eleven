/**
 * route-parity.test.mjs —— 路由表奇偶锁（t261003-10 票面要求②）：
 *   ① 表内每条路径 api.handle 都真的处理（不是「未知面板路由」404）；
 *   ② node.ts 生产注册面注册的 API 路径集合 === PANEL_API_ROUTES（经 stub webServer
 *      捕获，apply 真身驱动——下一个漏注册的路径在这里红，而不是在生产 404）；
 *   ③ 表外路径 handle 一律 404（表⊇可处理，防「路径在 dispatch 里但不在表里」漂移）。
 * 单一真源=PANEL_API_ROUTES；两侧都不另维护清单。
 */
import { assert, done } from './lib.mjs'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'
import * as pluginNs from '../node.ts'
const plugin = pluginNs

const api = createApi(
  { HOME: '/nonexistent-home', SANDBAR_PANEL_DIR: '/nonexistent-projects', SANDBAR_WATCHDOG_DIR: '/nonexistent-watchdog' },
  { now: () => 1, fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }) },
)
const Q = (s = '') => new URLSearchParams(s)
let n = 0

// ① 表内每条路径都可处理（GET 为主；POST-only 的 answer 断言 405=已进路由而非 404）。
for (const route of PANEL_API_ROUTES) {
  const r = await api.handle('GET', route.path, Q(), '')
  assert(!(r.status === 404 && String(r.json.error || '').includes('未知面板路由')),
    'handled: ' + route.path + ' (GET → ' + r.status + ', not unknown-route 404)')
  n++
}

// ② 生产注册面（node.ts apply 真身 + stub webServer）注册集合 === 表。
{
  const registered = []
  const ws = { register: (o) => { registered.push(o.path); return () => {} } }
  const fakeCtx = {
    get: () => ws,
    on: () => () => {},
    effect: (fn) => { fn(); return () => {} },
    logger: { info: () => {}, warn: () => {} },
  }
  plugin.apply(fakeCtx, {})
  const apiRegistered = registered.filter((p) => p.includes('/api/')).sort()
  const expected = PANEL_API_ROUTES.map((r) => r.path).sort()
  assert(JSON.stringify(apiRegistered) === JSON.stringify(expected),
    'node.ts registers exactly PANEL_API_ROUTES (got ' + JSON.stringify(apiRegistered) + ')')
  assert(registered.includes('/sandbar-executor-panel') && registered.includes('/sandbar-executor-panel/'),
    'static page routes still registered')
  n += 2
}

// ③ 表外路径 404（守卫唯一出口），表内 POST-only 面 GET 得 405（不是 404）。
{
  const r1 = await api.handle('GET', '/sandbar-executor-panel/api/not-in-table', Q(), '')
  assert(r1.status === 404, 'off-table path → 404')
  const r2 = await api.handle('GET', '/sandbar-executor-panel/api/requests/answer', Q(), '')
  assert(r2.status === 405, 'on-table POST-only path GET → 405 (routed)')
  n += 2
}

done(n)
