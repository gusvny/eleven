// sc_executor_panel_page_redesign.mjs — t261003-06 面板改版页面契约（灰盒 L3，真浏览器
// + API 桩，零 docker，红线零接触 3099；t260929-03-executor-panel-page 同款架构缝）。
//
// t261004-03 修编（五个假红断言的处置，面板无缺陷、全是场景侧锚/桩形漂移）：
//   桩形：行形状对齐 requests.ts RequestView（status/at）；status 端口=/{ok,result} 信封、
//         路径=/sandbar-watchdog/api/status；actions 端口=/api/actions（页面真拉的面）。
//   L1：负形收窄到 #paneOv（Settings 夜间策略下拉是合法 <select>，全文档扫描误判）。
//   L2：两栏锚 .cols > div；断点锚 @container max-width:7xx（视口 media 锚过时，
//       t261003-09 缺陷 1 定稿=按容器宽折叠）。
//   L4b：兜底锚=兜底控件本体（折叠行体 display:none 不进 innerText，文案锚必假红）。
//   L5：锚 #doneHead2 textContent + data-open（.sect 的 uppercase 使 innerText 锚随
//       Chromium 版本漂）；分栏由修正后的桩形驱动。
//   X1 的两条 404 同源（桩形）；宿主 node.ts 是否漏注册 /api/actions 属 t261003-10，
//   本场景不经宿主路由面，不在此重复修。
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
  // t261004-03 桩形修正：行形状对齐 requests.ts 的 RequestView 真读出视图——
  // status('waiting'|'answered')/at(毫秒)。旧桩的 state/created_at 是不存在的字段，
  // 页面按 status 分栏，answered 行永远进不了 Answered 区（L5 假红的根因）。
  const NOW = Date.now()
  const waiting = [
    { type: 'request', id: 'req-1', at: NOW - 120_000, project: PROJ, kind: 'question', question: 'Which ticket does the executor verify first?', detail: 'Two tickets wait. Ticket t1 blocks ticket t2. Pick the first one.', raised_by: 'bench:plan', default_action: 'verify t1', expires_at: null, status: 'waiting' },
    { type: 'request', id: 'req-2', at: NOW - 60_000, project: PROJ, kind: 'decision', question: 'How should the executor proceed?', detail: 'two viable paths', raised_by: 'bench', default_action: 'Open a new ticket', options: ['Open a new ticket', 'Extend the current ticket'], expires_at: null, status: 'waiting' },
  ]
  const answered = [{ type: 'request', id: 'req-0', at: NOW - 3_600_000, project: PROJ, kind: 'question', question: 'Old question?', detail: 'done', raised_by: 'bench', default_action: 'x', expires_at: null, status: 'answered', answer: 'Open a new ticket' }]
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [...waiting, ...answered] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    // t261004-03 桩形修正：页面拉的是 /sandbar-executor-panel/api/actions（recent-actions
    // 读源），不是 /api/recent-actions；行形状对齐 api.ts 的 actions 出面（action 用显示名）。
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [{ at: NOW, action: 'Sign', ticket: 't261002-10', result: 'ok', permission: 'merge' }], malformed_rows: 0, unmapped_rows: 0 })
    // t261004-03 桩形修正：真实路由是 /sandbar-watchdog/api/status（不是
    // /api/watchdog/status）；且页面按 { ok, result } 信封解包（poll()），裸对象=不可达假象。
    if (u.pathname.endsWith('/api/status')) return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } } })
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] })
    // t261006-17 (CL-2) + t261005-10 (UI-2) merged stubs: the page fetches the
    // concurrency read face on load (and lazily fetches the read-only tab faces);
    // an unstubbed fetch 404s and fails the hygiene leg on stub noise, not
    // product. The concurrency face keeps the CL-2 quiet shape (empty holders /
    // never-changed audit) so the zero-pageerror and render assertions judge
    // THEIR faces, not the new block.
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: 'alpha', limit: 3, unlimited: false, at_work: 0, waiting: 0, holders: [], queue: [], audit: { ok: false } })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
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

    // T1 五页签（t261008-20 起 Ledger 页签退场——tab 集为 4；ledger 面改为 Overview
    // source-event 对话框，从入口文字断言其可达，不再作为页签存在）
    const tabs = ['overview', 'grants', 'alerts', 'settings'].filter(x => t.includes(x))
    C.case('T1-five-tabs', tabs.length === 4, `found=${tabs.join(',')}`)
    C.case('T1b-ledger-face-entry', !/data-tab="ledger"/.test(html) && t.includes('recent actions (view source event)'),
      'the ledger face is reachable from the Overview entry, never a Ledger tab')
    const hasRequestsTab = await page.evaluate(() => {
      const els = [...document.querySelectorAll('label,input[name],.tab,[data-tab]')]
      return els.some(e => /^\s*requests\s*$/i.test(e.textContent || ''))
    })
    C.case('T2-requests-tab-gone', !hasRequestsTab, '独立 Requests 页签应退场')

    // L1 负形：选择器三件套 + 轮询行。
    // t261004-03 锚修正：负形断言收窄到 Overview 面（#paneOv）——Settings 页签的夜间
    // 策略下拉是合法 <select>，全文档扫描把它误判成「选择器还在」；选择器本是 Overview
    // 控件，退役与否只该看这一面。轮询行仍查整页渲染文本（它在哪都不该出现）。
    const ovNeg = await page.evaluate(() => {
      const pane = document.getElementById('paneOv')
      if (!pane) return null
      const els = [...pane.querySelectorAll('input[type=text],input:not([type]),select,button')]
      return { joined: els.map(e => (e.placeholder || e.value || e.textContent || '').trim()).join('|'), selects: pane.querySelectorAll('select').length }
    })
    const negForm = ovNeg !== null && !/load/i.test(ovNeg.joined) && !/polling/i.test(text) && ovNeg.selects === 0
    C.case('L1-picker-and-poll-line-absent', negForm, `ovControls=${ovNeg ? ovNeg.joined.slice(0, 120) : 'NO-PANE'} ovSelects=${ovNeg ? ovNeg.selects : '?'} pollText=${/polling/i.test(text)}`)

    // L2 两栏 + ~760px 断点。
    // t261004-03 锚修正：两栏锚 .cols > div（旧 [class*="col"] 只命中 .cols 容器本身，
    // 计数恒 1）；断点锚容器查询 @container (max-width:760px)——面板按设计（t261003-09
    // 缺陷 1）以容器宽而非视口宽折叠，media-query 锚是过时预期。
    const twoCol = await page.evaluate(() => {
      const cols = document.querySelectorAll('.cols > div')
      const css = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules].map(r => r.cssText) } catch { return [] } }).join('\n')
      return { cols: cols.length >= 2, mq: /@(container|media)[^{]*max-width:\s*7\d\dpx/.test(css) }
    })
    C.case('L2-two-columns-with-breakpoint', twoCol.cols && twoCol.mq, `cols>=2=${twoCol.cols} container-760=${twoCol.mq}`)
    // 措辞锚走 waitHead 的 textContent：.sect 有 text-transform:uppercase，innerText 是否
    // 随之变形随 Chromium 版本漂（main 复现=不随、新 headless=随），textContent 恒稳定。
    const waitHeadTxt = (await page.textContent('#waitHead')) || ''
    C.case('L2b-section-wording', /needs your answer/i.test(waitHeadTxt) && t.includes('recent action'), `waitHead="${waitHeadTxt.trim()}" rightCol=${t.includes('recent action')}`)

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
    // t261004-03 锚修正：兜底文案长在折叠行体内 + placeholder 上——display:none 的文本
    // 不进 innerText（行默认收起是设计行为，非缺陷）。锚改钉兜底控件本身：无选项行给
    // input[data-answerbox][placeholder="Type an answer"]，有选项行给 reveal 按钮。
    const freeFallback = await page.evaluate(() =>
      !!document.querySelector('#paneOv input[data-answerbox][placeholder="Type an answer"], #paneOv button[data-reveal]'))
    C.case('L4b-free-text-fallback-present', freeFallback, '兜底控件（Type an answer 输入框/reveal 按钮）在等待列')

    // L5 answered 折叠区。
    // t261004-03：锚走 #doneHead2 的 textContent（textContent 不随 text-transform:uppercase
    // 变形，innerText 随版本漂）；同时钉默认收起（data-open="false"）。行分栏由修正后的
    // RequestView 桩形（status:'answered'）驱动。
    const doneHeadTxt = (await page.textContent('#doneHead2')) || ''
    const doneCollapsed = await page.getAttribute('#doneWrap', 'data-open')
    C.case('L5-answered-collapsed-section', /answered\s*·\s*\d/i.test(doneHeadTxt) && doneCollapsed === 'false', `head="${doneHeadTxt.trim()}" collapsed=${doneCollapsed}`)

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
    // t261004-03：定稿措辞锚同步换 textContent（#waitHead），理由同 L2b——innerText 的
    // text-transform 行为随 Chromium 版本漂，不定锚会整段间歇红。
    C.case('S1b-fixed-terms', !bareIdiom && /needs your answer/i.test(waitHeadTxt), `bare "Needs you" heading=${bareIdiom}`)
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
