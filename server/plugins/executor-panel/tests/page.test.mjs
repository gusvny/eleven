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

// ---- t261001-10 回归锁（源级；浏览器行为面由 browser-save.test.mjs 真杆覆盖）----

// 旋钮 id：唯一真源 idFor（split/join，不吃反斜杠），inputFor/readInput 共用不许漂移。
assert(!PANEL_PAGE_HTML.includes("replace(/\\./g"), 'no regex-based knob id (the template literal eats the backslash)')
assert(!PANEL_PAGE_HTML.includes("replace(/./g"), 'no wildcard regex reachable in the served page')
{
  const idForSrc = (PANEL_PAGE_HTML.match(/function idFor\(path\)\{[^}]*\}/) || [])[0] || ''
  assert(idForSrc.includes("path.split('.').join('_')"), 'idFor uses split/join (no escape to lose)')
  const uses = (PANEL_PAGE_HTML.match(/idFor\(path\)/g) || []).length
  assert(uses >= 3, 'idFor is the single id source (definition + inputFor + readInput), found ' + uses)
}

// 保存结果不被刷新抹掉：结果存 saveMsg 变量且 renderSettings 每次重渲染后回写。
assert(PANEL_PAGE_HTML.includes("el('saveResult').innerHTML = saveMsg"), 'save result re-written after every settings re-render')
assert(PANEL_PAGE_HTML.includes("saveMsg = ''"), 'save result variable initialised (and reset on project switch)')

// 每个 POST 路径都有传输层失败显示路径（saveFailHtml / 显式 .catch）。
assert(PANEL_PAGE_HTML.includes('function saveFailHtml('), 'transport-failure renderer present')
{
  const posts = (PANEL_PAGE_HTML.match(/postJson\('/g) || []).length
  const catches = (PANEL_PAGE_HTML.match(/\.catch\(function/g) || []).length
  assert(posts === 5, 'all five POST paths accounted for, found ' + posts)
  assert(catches >= 6, 'every POST path has a .catch (5 POST + read-path catches), found ' + catches)
  assert((PANEL_PAGE_HTML.match(/\.catch\(function\(e\)\{ saveMsg = saveFailHtml\(e\)/g) || []).length === 4,
    'all four settings POST paths display transport failures in #saveResult')
  assert(PANEL_PAGE_HTML.includes("alert('Answer failed to send: ')") || PANEL_PAGE_HTML.includes("Answer failed to send"), 'answer POST has a visible transport-failure path')
}

n += 35
done(n)
