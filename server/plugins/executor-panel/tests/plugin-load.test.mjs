/**
 * plugin-load.test.mjs —— 插件面加载 UT：node.ts 可被 Node strip-mode 加载、
 * 导出面形状正确（不调用 apply——宿主服务不可桩于此；路由行为由 api/page UT 覆盖）。
 */
import { assert, done } from './lib.mjs'

let n = 0
const mod = await import('../node.ts')
assert(mod.name === 'sandbar-executor-panel', 'plugin name exported')
assert(Array.isArray(mod.inject) && mod.inject.length === 0, 'no hard inject dependencies (headless standby)')
assert(typeof mod.apply === 'function', 'apply exported')

// apply 的 headless 待机面：无 webServer 且不来 internal/service 时挂不上（不炸）。
{
  let fired = 0
  const fakeCtx = {
    get: () => undefined,
    on: (evt, fn) => { fired++; void evt; void fn },
    effect: () => () => {},
    logger: { info: () => {}, warn: () => {} },
  }
  mod.apply(fakeCtx, {})
  assert(fired === 1, 'headless: registers internal/service waiter only, no throw')
}

// 静态页可由插件页模块拿到（web 路由的真源）。
const page = await import('../src/host/panel-page.ts')
assert(typeof page.PANEL_PAGE_HTML === 'string' && page.PANEL_PAGE_HTML.startsWith('<!doctype html>'), 'PANEL_HTML is the served document')
assert(page.PANEL_ROUTE === '/sandbar-executor-panel', 'route constant matches the mounted path')

n += 5
done(n)
