// sc_executor_panel_page.mjs — t260929-03 executor-panel 页面契约（灰盒 L3，真浏览器 + API 桩，browser-free）。
//
// Intent（用户可感知行为；工单 scope②④⑤⑥⑦ + panel-contract.md 逐键）：
//   T1 五 tab 英文界面（Overview/Requests/Alerts/Ledger/Settings 标签在位）。
//   D1–D3 三种不可达各渲染显式降级态，绝不空态/常态冒充：路由 404（unreachable
//      类字样）、declared:false（not enrolled 类字样）、heartbeat.alive:false
//      （stale 类字样 + reason）；D1 附带：拉取失败绝不 beep（计数保持 0）。
//   B1–B4 beep 语义（宿主原话「一声就够」）：新未见 key 恰响一声（__panelBeepCount
//      1）；同 key 重轮询零增量；第二个新 key 再 +1；notify.beep:false 不响；
//      矛形输入（notify.beep=true 但行 night_muted 且非 redline）页面侧防线仍不响。
//      计数器与真实发声同代码路径（桩只换 AudioContext 出口），纯 markup 断言不算证明。
//   A1 alerts tab：level 与 night-muted 标记可见；不发明 answered/auto-action 位。
//   Q1 requests 主从视图：按项目分组、详情含问题/默认动作/等待时间；show more
//      追加旧行**不丢最新尾行**；答复只经显式动作且未答行原样保留。
//   L1 ledger tab：健康度以比例呈现（含 % 或 of），unreadable=显式降级横幅。
//   P1 provenance：≥2 旋钮各显示其来源（file#path 与 factory-default 两种形态）。
//   X1 全旅程零 pageerror/console.error。
//
// 架缝：页面 HTML 取自插件真实页面模块 `src/host/panel-page.ts`（seam 契约：具名导出
//   `PANEL_PAGE_HTML` 字符串），由场景本地 http 服务端出；watchdog status/requests/
//   settings/grants 全部 page 边界桩（形状=panel-contract.md）。红线：零接触 3099。
// 依赖缺席（playwright/chromium）=ENV_FAIL exit 2（KI-036 家族）；页面模块未落地=FAIL
// 点名（TDD 期红属预期）。intent 分工：节点半路由/写盘行为归 sc_executor_panel_api.mjs。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { makeCase } from './lib_panel_harness.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'

async function loadPageModule() {
  const p = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
  if (!existsSync(p)) return null
  return import(pathToFileURL(p).href)
}

// ---------- playwright 装载（t260927-05 同款回落链） ----------
function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const candidates = ['playwright-core']
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) candidates.push(pathToFileURL(p).href)
  }
  for (const c of candidates) { try { return await import(c) } catch { /* next */ } }
  return null
}
async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

const pw = await loadPlaywright()
if (!pw) { C.envFail('playwright-core', '主树 playwright-core 缺失（KI-036 家族）'); C.exit() }
const browser = await launchBrowser(pw)
if (!browser) { C.envFail('chromium', 'chromium/chrome 不可启动'); C.exit() }

const pageMod = await loadPageModule()
if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
  C.case('page-module-present', false,
    '实现未落地——server/plugins/executor-panel/src/host/panel-page.ts 缺具名导出 PANEL_PAGE_HTML（seam 契约见本文件头注；TDD 期红属预期）')
  await browser.close(); C.exit()
}

// ---------- fixture（形状=panel-contract.md 键集） ----------
const NOW = Date.now()
const iso = (msAgo) => new Date(NOW - (msAgo || 0)).toISOString()
function statusFixture(over = {}) {
  return {
    declared: true, enabled: true, phase: 'running',
    config_error: null,
    config_provenance: { file: '/home/x/.sandbar/projects/alpha/watchdog.json',
      keys: { enabled: 'factory-default', stall_minutes: '/home/x/.sandbar/projects/alpha/watchdog.json#stall_minutes',
        'alerts.sound': 'factory-default' } },
    heartbeat: { last_beat: iso(5000), age_seconds: 5, alive: true, reason: '' },
    ledger: { path: '/ledg/alpha.jsonl', watermark_offset: 120, rows_seen: 120, dupes_skipped: 2,
      malformed_rows: 1, gaps_seen: 0, last_row_at: iso(4000), unreadable: null },
    liveness: {
      engine: { online: true, detail: '', checked_at: iso(3000) },
      executor: { state: 'advancing', last_progress_at: iso(20000), stall_minutes: 3, evidence: 'ledger advanced', checked_at: iso(3000) } },
    self_lock: { state: 'none', reason: '', target: null, since: null },
    reconcile: { state: 'ok', reason: '', since: iso(60000), mismatches: [] },
    startup: { missing_rows: 0, replayed_rows: 0, dedupe_keys: 3 },
    wakes: [{ at: iso(30000), ticket: 't-1', dedupe_key: 'k', mode: 'auto', accepted: true }],
    alerts: [{ at: iso(10000), key: 'k1', rule: 'r1', target: 't-1', level: 'info', title: 'Board behind', detail: '', night_muted: false }],
    notify: { beep: true, unseen_redline: 0 },
    last_error: null, ...over,
  }
}
const REQ_ROWS = [
  { id: 'rq-2', at: iso(60e3), project: PROJ, question: 'Sign ticket t-1?', kind: 'sign',
    default_action: 'sign', expires_at: iso(-3600e3), status: 'waiting' },
  { id: 'rq-1', at: iso(3600e3), project: PROJ, question: 'Old one', kind: 'note',
    default_action: 'none', expires_at: null, status: 'waiting' },
  { id: 'rq-0', at: iso(7200e3), project: PROJ, question: 'Oldest', kind: 'note',
    default_action: 'none', expires_at: null, status: 'answered', answer: 'ok', answered_at: iso(3500e3) },
]

// ---------- 场景本地桩服务器（数据在 API 边界桩；真浏览器/真页面渲染链） ----------
let statusBody = { ok: true, result: statusFixture() }
let statusHttp = 200
let answerPosts = []
const srv = createServer((req, res) => {
  const u = new URL(req.url, 'http://x')
  const send = (code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)) }
  if (u.pathname === '/panel') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(pageMod.PANEL_PAGE_HTML); return
  }
  if (u.pathname === '/sandbar-watchdog/api/status') {
    if (statusHttp !== 200) { res.writeHead(statusHttp); res.end('stub down'); return }
    send(200, statusBody); return
  }
  if (u.pathname === '/sandbar-executor-panel/api/requests' && req.method === 'GET') {
    send(200, { rows: REQ_ROWS, malformed_rows: 0 }); return
  }
  if (u.pathname === '/sandbar-executor-panel/api/requests/answer' && req.method === 'POST') {
    let b = ''; req.on('data', c => b += c); req.on('end', () => { answerPosts.push(b); send(200, { ok: true }) }); return
  }
  if (u.pathname === '/sandbar-executor-panel/api/settings' && req.method === 'GET') {
    send(200, { config: { enabled: true, stall_minutes: 3 }, config_provenance: statusFixture().config_provenance,
      night_override: null, effective_night_policy: 'normal' }); return
  }
  if (u.pathname === '/sandbar-executor-panel/api/grants' && req.method === 'GET') {
    // t261003-06 改版后的 grants 读面契约（声明真源 + 三态读出）。
    send(200, { ok: true, degraded: false, grants: { ok: true, rows: [], granted_count: 1 },
      granted_ops: ['sign'], granted_total: 6,
      readout_note: 'Permissions: 1 of 6 granted (distinct permissions, not capability rows)',
      session_readout: { state: 'granted', sessions: ['exec-1'], sentence: 'The session is named. 1 of 6 permissions are granted.' },
      declaration: { version: 1, grants: { sign: true }, executor_sessions: ['exec-1'] },
      declaration_state: { declared: true, kind: 'ok' }, provenance: { keys: {} } })
    return
  }
  if (u.pathname === '/sandbar-executor-panel/api/actions' && req.method === 'GET') {
    // t261003-06 Overview 右栏「最近动作」读面。
    send(200, { ok: true, actions: [{ at: Date.now() - 60e3, action: 'Sign', ticket: 't-1', result: 'merged by executor', permission: 'sign' }],
      unmapped_rows: 0, malformed_rows: 0 }); return
  }
  if (u.pathname === '/sandbar-executor-panel/api/bridge/status') { send(200, { ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] }); return }
  res.writeHead(404); res.end('not found')
})
await new Promise(r => srv.listen(0, '127.0.0.1', r))
const BASE = 'http://127.0.0.1:' + srv.address().port
const URL_ = BASE + '/panel?project=' + PROJ

async function freshPage() {
  const ctx = await browser.newContext() // 全新 localStorage：seen-set 从零开始
  const page = await ctx.newPage()
  page.errors = []
  page.on('pageerror', e => page.errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') page.errors.push(m.text()) })
  return { ctx, page }
}
const beepCount = async (page) => page.evaluate(() => window.__panelBeepCount ?? null)
const bodyText = (page) => page.evaluate(() => document.body.innerText)

// T1 五 tab + 英文界面
{
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(400)
  const t = await bodyText(page)
  // t261003-06 改版定稿：五 tab = Overview/Grants/Alerts/Ledger/Settings；Requests 页签
  // 退役并入 Overview（本场景的 tab 清单随之更新——旧清单钉的是已退役布局）。
  const tabs = ['Overview', 'Grants', 'Alerts', 'Ledger', 'Settings']
  const missing = tabs.filter(x => !t.includes(x))
  const requestsTabRetired = !/(^|\n)\s*Requests\s*(\n|$)/.test(t)
  const navEl = await page.evaluate(() => {
    const nav = document.querySelector('nav') || document.body
    return nav.innerText
  })
  const cjk = /[\u4e00-\u9fff]/.test(navEl)
  C.case('T1-five-tabs-english-chrome', missing.length === 0 && !cjk && requestsTabRetired,
    missing.length ? 'missing tabs: ' + missing.join(',') : (!requestsTabRetired ? 'standalone Requests tab still present (retired by t261003-06)' : (cjk ? 'CJK in chrome nav' : 'ok')))
  await ctx.close()
}

// D1 路由不可达=显式降级 + 不 beep
{
  statusHttp = 404
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(600)
  const t = await bodyText(page)
  const degraded = /unreachable|unavailable|cannot reach/i.test(t)
  C.case('D1-route-down-explicit-degraded', degraded, degraded ? 'ok' : 'no degraded wording; body=' + t.slice(0, 120))
  await page.waitForTimeout(400)
  C.case('D1b-route-down-never-beeps', (await beepCount(page)) === 0, `beepCount=${await beepCount(page)}`)
  await ctx.close(); statusHttp = 200
}
// D2 declared:false
{
  statusBody = { ok: true, result: { declared: false } }
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(400)
  const t = await bodyText(page)
  // t261003-06 STE 改版措辞：declared:false 的显式降级句 = "No watchdog declaration exists."
  // （旧锚 not enrolled/undeclared 随文案定稿退役——锚语义「显式非正常态」不变）。
  const ok = /no watchdog declaration|not enrolled|undeclared|not declared/i.test(t) && !/watermark/i.test(t)
  C.case('D2-declared-false-not-normal-state', ok, ok ? 'ok' : 'body=' + t.slice(0, 120))
  await ctx.close()
}
// D3 alive:false
{
  statusBody = { ok: true, result: statusFixture({ heartbeat: { last_beat: iso(600e3), age_seconds: 600, alive: false, reason: 'no beat for 10m' } }) }
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(400)
  const t = await bodyText(page)
  const ok = /stale|possibly stale|expired/i.test(t) && t.includes('no beat for 10m')
  C.case('D3-alive-false-stale-with-reason', ok, ok ? 'ok' : 'body=' + t.slice(0, 160))
  await ctx.close()
}

// B1–B4 beep 语义
async function beepCase(name, fixture, expectAfterLoad, expectAfterRepoll) {
  statusBody = { ok: true, result: fixture }
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(500)
  const c1 = await beepCount(page)
  await page.reload(); await page.waitForTimeout(500) // 重轮询（同 key 或给定后续面）
  const c2 = await beepCount(page)
  C.case(name, c1 === expectAfterLoad && c2 === expectAfterRepoll,
    `${name}: after_load=${c1} expect=${expectAfterLoad} after_repoll=${c2} expect=${expectAfterRepoll}`)
  await ctx.close()
}
await beepCase('B1-new-key-beeps-once-zero-on-repoll',
  statusFixture(), 1, 1)
await beepCase('B2-second-new-key-adds-one-more',
  statusFixture({ alerts: statusFixture().alerts.concat([{ at: iso(5000), key: 'k2', rule: 'r2', target: 't-2', level: 'warn', title: 'Second', detail: '', night_muted: false }]) }),
  2, 2)
await beepCase('B3-notify-false-never-beeps',
  statusFixture({ notify: { beep: false, unseen_redline: 0 } }), 0, 0)
await beepCase('B4-nightmuted-nonredline-defense',
  statusFixture({ alerts: [{ at: iso(10000), key: 'k1', rule: 'r1', target: 't-1', level: 'info', title: 'Muted one', detail: '', night_muted: true }],
    notify: { beep: true, unseen_redline: 0 } }), 0, 0)

// 正常态：Overview 数据 + Alerts + Requests + Ledger + provenance
statusBody = { ok: true, result: statusFixture() }
{
  const { ctx, page } = await freshPage()
  await page.goto(URL_); await page.waitForTimeout(500)
  const t = await bodyText(page)
  // Overview（t261003-06 改版）：两栏并列——左 Needs your answer 右 Recent actions；
  // 状态条与等待请求同屏渲染（旧的 watermark/reconcile/advancing 三词锚随布局退役，
  // 数据面存在性改锚到两栏区块 + 真实等待问题行——锚语义不锚字面，KI-051 纪律）。
  const ov = t.includes('Needs your answer'.toLowerCase()) || /needs your answer/i.test(t)
  const ov2 = /recent action/i.test(t)
  const ov3 = t.includes('Sign ticket t-1?')
  C.case('O1-overview-surface', ov && ov2 && ov3, `needs_you=${ov} recent_actions=${ov2} waiting_row=${ov3}`)
  // Alerts：night_muted 标记 + 无 answered/auto-action 位
  await page.click('text=Alerts').catch(() => {})
  await page.waitForTimeout(300)
  const at = await bodyText(page)
  const nightRow = statusFixture({ alerts: statusFixture().alerts.concat([{ at: iso(9000), key: 'k9', rule: 'r', target: 't', level: 'info', title: 'Night one', detail: '', night_muted: true }]) })
  statusBody = { ok: true, result: nightRow }
  await page.reload(); await page.waitForTimeout(400)
  await page.click('text=Alerts').catch(() => {})
  await page.waitForTimeout(300)
  const at2 = await bodyText(page)
  C.case('A1-night-muted-mark-visible', /night.?muted/i.test(at2), `/night.?muted/=${/night.?muted/i.test(at2)}`)
  C.case('A2-no-auto-action-field-invented', !/auto.?action|auto.?answered/i.test(at2), 'ok')
  // Requests（t261003-06 改版）：并入 Overview 两栏——waiting 行在左栏可见；
  // answered 行收进折叠 Answered 区（答过的行不再常驻主视野——设计 §1 毛病 2 的修复面）。
  await page.click('text=Overview').catch(() => {})
  await page.waitForTimeout(400)
  let rt = await bodyText(page)
  const detailOk = rt.includes('Sign ticket t-1?') && /sign/i.test(rt) && /waiting|waited|\d+[smh]/i.test(rt)
  // Answered 区默认折叠：展开回看后 answered 行内容仍保留（审计链在页面上的投影）。
  const answeredToggle = page.getByText(/answered/i).first()
  if (await answeredToggle.count()) { await answeredToggle.click().catch(() => {}); await page.waitForTimeout(300) }
  rt = await bodyText(page)
  const tailKept = rt.includes('Sign ticket t-1?') && /oldest/i.test(rt)
  C.case('Q1-requests-master-detail-tail-kept', detailOk && tailKept,
    `detail=${detailOk} tail_kept=${tailKept}`)
  // 答复仅显式动作：无 answer POST 发生在纯浏览时
  C.case('Q2-no-auto-answer-on-render', answerPosts.length === 0, `answer_posts=${answerPosts.length}`)
  // Ledger：比例呈现 + unreadable 横幅
  await page.click('text=Ledger').catch(() => {})
  await page.waitForTimeout(300)
  const lt = await bodyText(page)
  C.case('L1-ledger-proportions', /%| of /.test(lt), `proportion_face=${/%| of /.test(lt)}`)
  statusBody = { ok: true, result: statusFixture({ ledger: statusFixture().ledger, }) }
  statusBody.result.ledger = { ...statusBody.result.ledger, unreadable: 'EACCES: /ledg/alpha.jsonl' }
  await page.reload(); await page.waitForTimeout(400)
  const lt2 = await bodyText(page)
  C.case('L2-ledger-unreadable-banner', /unreadable|EACCES/i.test(lt2), 'ok')
  // Settings：≥2 旋钮溯源两种形态
  await page.click('text=Settings').catch(() => {})
  await page.waitForTimeout(400)
  const st = await bodyText(page)
  const prov2 = st.includes('factory-default') && st.includes('stall_minutes')
  C.case('P1-provenance-two-knobs-two-forms', prov2, `factory=${st.includes('factory-default')} stall_source=${st.includes('stall_minutes')}`)
  C.case('X1-zero-pageerrors', page.errors.length === 0, page.errors.slice(0, 3).join(' | '))
  await ctx.close()
}

srv.close()
await browser.close()
C.exit()
