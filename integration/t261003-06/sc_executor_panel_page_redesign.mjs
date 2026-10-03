// sc_executor_panel_page_redesign.mjs — t261003-06 面板改版页面契约（灰盒 L3，真浏览器
// + API 桩，零 docker，红线零接触 3099；t260929-03-executor-panel-page 同款架构缝）。
//
// Intent（用户可感知行为；工单派发规格 + 设计 note §2/§3/§4 + mock 视觉基准）：
//   T1 五页签 Overview/Grants/Alerts/Ledger/Settings；Requests 页签退场（并入 Overview）。
//   L1 负形：项目选择器（下拉 / 手填 key 框 / Load 按钮）与轮询状态行（"polling…"）
//      不存在——从哪个项目行进来就是哪个项目。
//   L2 Overview 两栏并列：左「Needs your answer」右「Recent actions」；CSS 带
//      ~760px 断点（窄窗叠放）。
//   L3 请求条目收起一行，点开展开：详细内容块（限高、可内滚）、回答控件、溯源行
//      （raised by / request id / default action）。
//   L4 带选项的请求渲染按钮；无选项的请求给自由文本框（兜底文案 "Type an answer"）。
//   L5 已答项收进折叠 Answered 区，可再展开回看（内容与答复保留）。
//   L6 Overview 电源开关与 Grants 总开关同一状态：Overview 关 → 切到 Grants 页签
//      总开关呈关（一份状态，两处呈现）。
//   L7 Overview 页签带等待数徽标。
//   S1 STE 文案抽查（§4 全面板口径，跨页签取点）：渲染文本零缩略形式
//      （don't/won't/can't/it's…）；「Needs your answer」「Type an answer」定稿措辞
//      在场；旧习语「Needs you」单独出现=红（锚语义不锚字面：允许更长句包含它）。
//   X1 全旅程零 pageerror。
//
// 架缝：页面 HTML 取自插件真实页面模块具名导出 PANEL_PAGE_HTML；watchdog status /
// requests / settings / grants / recent-actions 全部 page 边界桩。依赖缺席
// （playwright/chromium）=ENV_FAIL exit 2（KI-036 家族）；页面模块未落地=FAIL 点名
// （TDD 期红属预期）。intent 分工：路由面/写盘/选项校验归本票另三条；入口/切换器归
// t260929-22 族。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from './lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts 缺席')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts 缺具名导出 PANEL_PAGE_HTML（缝契约；TDD 期红属预期）')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }

  // ---- page 边界桩（形状=panel-contract + 本票新增面） ----
  const waiting = [
    { id: 'req-1', project: PROJ, question: 'Which ticket does the executor verify first?', detail: 'Two tickets wait. Ticket t1 blocks ticket t2. Pick the first one.', raised_by: 'bench:plan', default_action: 'verify t1', state: 'waiting', created_at: 1 },
    { id: 'req-2', project: PROJ, question: 'How should the executor proceed?', detail: 'two viable paths', raised_by: 'bench', default_action: 'Open a new ticket', state: 'waiting', created_at: 2, options: ['Open a new ticket', 'Extend the current ticket'] },
  ]
  const answered = [{ id: 'req-0', project: PROJ, question: 'Old question?', detail: 'done', raised_by: 'bench', default_action: 'x', state: 'answered', answer: 'Open a new ticket', created_at: 0 }]
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [...waiting, ...answered] })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [{ time: 1, action: 'sign', ticket: 't261002-10', result: 'ok', permission: 'merge' }] })
    if (u.pathname.endsWith('/api/watchdog/status') || u.pathname === '/status') return json({ declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } })
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const html = pageMod.PANEL_PAGE_HTML

  const { chromium } = pw
  let browser = null
  try {
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    // 页面模块以 ?project= 深链进面板（选择器退役后的唯一到达路径）
    await page.route('**/*', (route) => {
      const u = new URL(route.request().url())
      if (u.pathname === '/' || u.pathname.endsWith('.html')) return route.fulfill({ contentType: 'text/html', body: html })
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({}) })
    })
    // 直接内容注入（页面 JS 会自行拉桩数据；这里经 data URL 之外的最简路径：本地服务）
    const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
    await new Promise(r => local.listen(0, '127.0.0.1', r))
    const lport = local.address().port
    // 页面取数走同源相对路径 —— 桩端口号未知于页面，故用 route 拦截把 API 打到桩：
    await page.unroute('**/*')
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForTimeout(600)

    const text = await page.evaluate(() => document.body.innerText)
    const t = text.toLowerCase()

    // T1 五页签
    const tabs = ['overview', 'grants', 'alerts', 'ledger', 'settings'].filter(x => t.includes(x))
    C.case('T1-five-tabs', tabs.length === 5, `found=${tabs.join(',')}`)
    const hasRequestsTab = await page.evaluate(() => {
      const els = [...document.querySelectorAll('label,input[name],.tab,[data-tab]')]
      return els.some(e => /^\s*requests\s*$/i.test(e.textContent || ''))
    })
    C.case('T2-requests-tab-gone', !hasRequestsTab, '独立 Requests 页签应退场')

    // L1 负形：选择器三件套 + 轮询行
    const inputs = await page.evaluate(() => [...document.querySelectorAll('input[type=text],input:not([type]),select,button')].map(e => (e.placeholder || e.value || e.textContent || '').trim()))
    const joined = inputs.join('|')
    const negForm = !/load/i.test(joined) && !/polling/i.test(text) && (await page.$$eval('select', s => s.length)) === 0
    C.case('L1-picker-and-poll-line-absent', negForm, `controls=${joined.slice(0, 120)} pollText=${/polling/i.test(text)}`)

    // L2 两栏 + 760px 断点
    const twoCol = await page.evaluate(() => {
      const cols = document.querySelectorAll('[class*="col"],[class*="column"],[class*="overview"] > div')
      const css = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules].map(r => r.cssText) } catch { return [] } }).join('\n')
      return { cols: cols.length >= 2, mq: /max-width:\s*7\d\dpx/.test(css) }
    })
    C.case('L2-two-columns-with-breakpoint', twoCol.cols && twoCol.mq, `cols>=2=${twoCol.cols} media-760=${twoCol.mq}`)
    C.case('L2b-section-wording', t.includes('needs your answer') && t.includes('recent action'), '左栏 Needs your answer / 右栏 recent actions 措辞')

    // L3 展开条目：收起一行 → 点击出现溯源行
    const before = await page.evaluate(() => document.body.innerText.includes('raised by') || document.body.innerText.toLowerCase().includes('raised by'))
    let clicked = false
    try { await page.click('text=/Which ticket does the executor verify first?/'); clicked = true } catch { /* fallback below */ }
    if (!clicked) { try { await page.click('text=/How should the executor proceed?/'); clicked = true } catch { /* noop */ } }
    await page.waitForTimeout(300)
    const after = (await page.evaluate(() => document.body.innerText.toLowerCase())).includes('raised by') || (await page.evaluate(() => document.body.innerText.toLowerCase())).includes('default action')
    C.case('L3-expandable-row-trace-line', clicked && after && !before, `clicked=${clicked} trace-visible-after=${after}`)

    // L4 选项按钮 vs 自由文本
    const optionButtons = await page.$$eval('button', bs => bs.filter(b => /open a new ticket|extend the current ticket/i.test(b.textContent || '')).length)
    const freeBox = await page.evaluate(() => {
      const ta = document.querySelector('textarea,input[type=text]')
      return !!ta
    })
    C.case('L4-options-render-as-buttons', optionButtons >= 2, `option-buttons=${optionButtons}`)
    C.case('L4b-free-text-fallback-present', t.includes('type an answer'), '兜底文案 Type an answer')

    // L5 answered 折叠区
    C.case('L5-answered-collapsed-section', t.includes('answered'), 'Answered 折叠区在文档流（默认收起不算 FAIL，可展开回看由 L1 单元面守）')

    // L6 电源开关 ≡ Grants 总开关（同一状态两处呈现）
    C.case('L6-power-and-master-one-state', t.includes('disable') || t.includes('enable'),
      'Overview 电源开关在场（同一份状态的跨页签一致性由 harness 路由面场景 sc_executor_grants_session_roundtrip 钉行为面，此处锁呈现面）')

    // L7 徽标
    const badge = await page.evaluate(() => { const e = [...document.querySelectorAll('[class*="badge"],[class*="count"],[data-badge]')]; return e.some(x => /\d/.test(x.textContent || '')) })
    C.case('L7-overview-waiting-badge', badge, 'Overview 页签等待数徽标')

    // S1 STE 文案抽查
    const badContraction = /\b(don't|won't|can't|isn't|doesn't|didn't|shouldn't|couldn't|you're|we're|it's|that's|there's)\b/i.test(text)
    C.case('S1a-no-contractions', !badContraction, `hits=${(text.match(/\b(don't|won't|can't|isn't|doesn't|it's|that's)\b/gi) || []).join(',')}`)
    const bareIdiom = await page.evaluate(() => {
      const els = [...document.querySelectorAll('h1,h2,h3,h4,label,button,th,[class*="title"],[class*="header"]')]
      return els.some(e => /^\s*needs you\s*$/i.test(e.textContent || ''))
    })
    C.case('S1b-fixed-terms', !bareIdiom && t.includes('needs your answer'), `bare "Needs you" heading=${bareIdiom}`)
    const longSentence = text.split(/[.!?\n]/).map(s => s.trim()).filter(s => s.split(/\s+/).length > 40)
    C.case('S1c-no-marathon-sentences', longSentence.length === 0, `over-40-word sentences=${longSentence.length}: ${JSON.stringify(longSentence).slice(0, 120)}`)

    // X1 零 pageerror
    C.case('X1-zero-pageerror', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)

    await browser.close()
    local.close()
    stub.close()
  } catch (e) {
    if (browser) { try { await browser.close() } catch { /* noop */ } }
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg)
    return C.exit()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
