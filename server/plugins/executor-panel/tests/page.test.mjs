/**
 * page.test.mjs —— 静态页形状 UT：五 tab、显式降级文案、beep 缝、纯函数真嵌入
 * （页面与单测同一份实现）、契约偏差声明在案（review #1：seen-set 本地清除）。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML, PANEL_ROUTE } from '../src/host/panel-page.ts'

let n = 0

// 五 tab（英文 chrome，宿主令 260925）。
for (const tab of ['Overview', 'Requests', 'Alerts', 'Ledger', 'Settings']) {
  assert(PANEL_PAGE_HTML.includes('>' + tab + '<'), 'tab label present: ' + tab)
}

// 三种不可达的显式降级文案（绝不空态/正常态）+ 其他契约键显式渲染。
for (const frag of [
  'Watchdog unreachable', 'Not enrolled', 'data possibly stale',
  'Declaration REJECTED', 'last_error', 'UNREADABLE', 'liveness UNKNOWN', 'Self-lock UNKNOWN',
]) {
  assert(PANEL_PAGE_HTML.includes(frag), 'explicit degraded/error surface present: ' + frag)
}

// beep：页内发声 + 计数缝（场景断言 __panelBeepCount，不是 markup-only 证明）。
assert(PANEL_PAGE_HTML.includes('createOscillator'), 'page plays real WebAudio oscillator (no audio asset stub)')
assert(PANEL_PAGE_HTML.includes('__panelBeepCount'), 'beep counter seam exposed for the browser scenario')
assert(PANEL_PAGE_HTML.includes('beepDecision('), 'page calls the SAME beepDecision implementation the unit tests table-drive')
assert(PANEL_PAGE_HTML.includes('function beepDecision'), 'beepDecision source embedded (single implementation, no drift copy)')

// 请求边界文案（Alerts=告诉你 / Requests=等你答）+ 永不自动应答声明。
assert(PANEL_PAGE_HTML.includes('never deleted by the machine, never answered by the machine'), 'requests boundary statement rendered in place')
assert(PANEL_PAGE_HTML.includes('never turns into a decision on its own'), 'alerts/requests boundary rendered (no answered/auto-action wording invented)')
assert(PANEL_PAGE_HTML.includes('show more'), 'show-more control present (tail kept)')

// 溯源（KI-148/149）+ 写时校验文案 + 派生授权文案。
assert(PANEL_PAGE_HTML.includes('decided by:'), 'per-knob provenance line rendered')
assert(PANEL_PAGE_HTML.includes('factory-default'), 'factory-default provenance rendered')
assert(PANEL_PAGE_HTML.includes('validate-on-write'), 'validate-on-write stated on the save control')
assert(PANEL_PAGE_HTML.includes('derived from the template'), 'grants derivation stated (decision 10)')

// 夜间过期显式（不静默回切）。
assert(PANEL_PAGE_HTML.includes('EXPIRED'), 'expired night override rendered explicitly')

// 嵌入函数无 TS 类型残留（strip 后应无「: boolean」这类注解混进 <script>）。
const m = PANEL_PAGE_HTML.match(/function beepDecision\([^)]*\)/)
assert(m && !/:/.test(m[0].replace(/https?:/, '')), 'embedded beepDecision is stripped JS (no TS annotations)')

// rework gen1 回归锁：renderAlertsLedger 必须有调用点（此前只有定义=Alerts/Ledger 永空，
// 仲裁 code-fault 打回项）——源级钉死「定义+≥2 调用（成功轮询/失败路径）」。
{
  const calls = (PANEL_PAGE_HTML.match(/renderAlertsLedger\(\)/g) || []).length
  assert(calls >= 3, 'renderAlertsLedger has call sites (definition + poll success + failure path), found ' + calls)
}

// 路由常量（node.ts 挂载与页面 fetch 同源防漂移）。
assert(PANEL_ROUTE === '/sandbar-executor-panel', 'panel route constant')

// 轮询面：固定间隔 + watchdog 状态端点为唯一状态源（不重算）。
assert(PANEL_PAGE_HTML.includes('/sandbar-watchdog/api/status'), 'page consumes the watchdog contract endpoint directly')

n += 24
done(n)
