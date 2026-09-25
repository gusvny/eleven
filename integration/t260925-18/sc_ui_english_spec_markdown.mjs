// sc_ui_english_spec_markdown.mjs — t260925-18 console 工单详情英文化 + spec markdown + 底部六区块移除的 DOM 级验收场景。
//
// Intent (black-box, user perspective)：宿主刷新现有 console 页面后可感知三件事——
//   E1 英文界面×中文数据：详情抽屉与左栏工单列表的全部**界面文案**（状态/阶段/枚举
//      标签、卡标题、计数徽标）无 CJK；而**数据**（票标题、正文、spec、blocked_reason
//      等引擎产出物）保持原语言不被翻译——「英文界面 + 中文内容」是票面拍板的预期形态。
//      标签真源=引擎既有标识（stage id / stage_state / status）经前端映射表；
//      **未知值回落原始标识**：未知 stage_state/stage 在页面原样可见（永不空白、
//      永不中文）——这是映射表契约的可判定锚，不锚任何具体英文措辞。
//   E2 spec 卡 markdown 渲染 + 消毒：spec 内容按基本 markdown 出结构化元素
//      （标题/列表/粗体/行内码/代码栅栏），不再是裸文本块；agent/用户可写的 spec
//      是外部输入——内联 <script>/<img onerror>/javascript: 链接全部失活（转义显示，
//      零可执行注入路径），畸形/非字符串输入不炸。
//   E3 底部六区块移除：入参/验收清单/流水 log/接力时间线/快照要点/基本信息不再出现在
//      详情抽屉（数据面仍可经 ticket CLI/Temporal 查询——本场景只锁 UI 不在，不锁数据删除，
//      数据仍在=另由 CLI 面既有场景覆盖）。
//   E4 泳道图阶段标签来自 stage id 映射：已知 id 不再显示引擎模板中文 label（做方案/
//      审方案族）；拓扑含未知 id 节点时回落显示原始 id。
//   E5 全旅程零 pageerror / console.error（渲染链卫生）。
//
// 分层纪律（防 intent 级重复）：
//   - t260904-06 sc_spec_card_dom 锁的是旧形态（纯文本保真/字数徽标/「执行规格（spec）」
//     中文标题）——本票改动兑现后其 T1 断言面被本票有意推翻（中文标题→英文、纯文本→
//     markdown），归 implement 段随票同步改写；本场景锁新契约（markdown 结构化+消毒+
//     英文界面），两者不并存双锁。
//   - t260915-05 sc_ticket_detail_lane_map_dom 锁泳道图拓扑渲染/降级/红灯翻译层，
//     锚「标签来自拓扑」；本场景只锁「标签语言层=stage id 映射+未知回落」，不碰其拓扑形状断言。
//   - t260911-05 sc_ki048_status_card_dom 锁 blocked 明细 payload→pixel；本场景只用
//     blocked_reason 当「中文数据不被翻译」的对照组，不复断其四件形状。
//   - developer L1（ui-labels 纯函数矩阵/spec-card-ui.mjs）不同层：本场景锁 payload→像素
//     真渲染面与构建产物（bundle 陈旧时以「页面仍是旧 UI」正确变红，归因 merge-checks
//     bundle_pairs / t260903-04 client-bundle-sync）。
//
// Two layers → 仅 S1（真浏览器渲染级，precedent=t260911-05 ki048）：needs the
// ISOLATED test console (lib_stage_console)，playwright-core 可解析，chromium 可启动，
// 任一缺席=ENV_FAIL exit 2（注明 KI-036 家族）。数据在 API 边界用 page.route() 桩：
// 真浏览器/真 console/真 bundle/真 React 渲染链，只拦 /sandbar-workbench/api/wf/tickets**
// 与 /api/wf/workflows**（夹具快照）。红线：永不接触生产 console(3099)、不起替换服务。
// 定位板入口的图标锚用 class（wb-view-icon）逐个试探，不锚其 title 文案——title 本身
// 是本票英文化对象，锚它会自缚（ki048 的 title="工单列表" 锚即前车之鉴）。
//
// 执行契约（t260904-12 三态）：stdout 末行
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；FAIL>0 或全部子用例 na → exit 1；
// env_fail>0 → exit 2。实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base

// fixture 票 id（纯字母数字，永不与真票相撞）
const FID_A = 't26092518a' // 主形态：markdown spec + 注入样本 + 已知 stage/status
const FID_B = 't26092518b' // 未知枚举形态：stage/stage_state 均为未知标识（回落契约）
const FID_C = 't26092518c' // 无 spec 老票（零扰动对照）+ 中文标题（数据不译对照）

const CJK = /[\u4e00-\u9fff]/

// ---------------------------------------------------------------- fixtures

function row(id, title, over = {}) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
    ...over,
  }
}
const ROWS = [
  row(FID_A, 'Fixture ticket A — english ui & markdown spec'),
  row(FID_B, 'Fixture ticket B — unknown enum fallback', { stage: 'weird_stage_x', stage_state: 'weird_state_y', status: 'weird_status_z' }),
  row(FID_C, '夹具票C·中文标题数据不译对照'),
]

const T = '2026-09-25T00:00:00'
const tle = (stage, state = 'running', reason = '') => ({ at: T, stage, state, reason })

function detailBase(id, title, over = {}) {
  return {
    id, title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'implement', stage_state: 'running', stage_name: '实现',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [],
    body: '夹具工单正文（原始需求占位，中文数据不译对照锚）',
    write_set: [], timeline: [tle('create_plan'), tle('review_plan'), tle('implement')],
    ...over,
  }
}

// spec 样本：基本 markdown 全族 + 三类注入样本（先转义口径下都以纯文本出现）+ 中文数据段。
const SPEC_MD = [
  '# Specs Must Render',
  '',
  'This **bold** and `inline_code` matter.',
  '',
  '- first item',
  '- second item',
  '',
  '```js',
  'const x = 1',
  '```',
  '',
  '<script>window.__pwned = true</script>',
  '<img src=x onerror="window.__pwned = true">',
  '[clickme](javascript:alert(1))',
  '',
  '中文数据段：spec 内容保持原语言（不译）。',
].join('\n')

const DETAIL_A = detailBase(FID_A, ROWS[0].title, {
  spec: SPEC_MD,
  spec_len: SPEC_MD.length,
  blocked_reason: '复核打回（中文引擎文案=数据不译对照）：验收口径缺畸形输入用例',
})

const DETAIL_B = detailBase(FID_B, ROWS[1].title, {
  stage: 'weird_stage_x', stage_state: 'weird_state_y', stage_name: 'weird_stage_x',
  status: 'weird_status_z',
  timeline: [tle('weird_stage_x', 'weird_state_y')],
})

const DETAIL_C = detailBase(FID_C, ROWS[2].title) // 无 spec 字段：老票零扰动对照
const DETAIL_BY_ID = { [FID_A]: DETAIL_A, [FID_B]: DETAIL_B, [FID_C]: DETAIL_C }

const TOPO_DEVLANE = {
  template: 'dev-lane', name: '开发泳道',
  nodes: [
    { id: 'create_plan', label: '做方案', role: 'developer', kind: 'agent' },
    { id: 'review_plan', label: '审方案', role: 'integration', kind: 'agent' },
    { id: 'implement', label: '实现', role: 'developer', kind: 'agent' },
    { id: 'weird_stage_x', label: '未知夹具段', role: 'developer', kind: 'agent' },
  ],
  edges: [['create_plan', 'review_plan'], ['review_plan', 'implement'], ['implement', 'weird_stage_x']],
  groups: [],
}
const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: TOPO_DEVLANE.nodes.map(n => ({ id: n.id, name: n.label, role: n.role, parts: ['agent'] })),
  topology: TOPO_DEVLANE,
}

// ---------------------------------------------------------------- results / helpers

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await p.keyboard.press('Escape').catch(() => {})
    await p.waitForTimeout(600)
  }
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

async function snap(p) {
  try {
    const txt = await p.evaluate(() => (document.querySelector('.wb-d2, .wb-drawer')?.textContent || '').slice(0, 200))
    return JSON.stringify(txt)
  } catch { return '(snapshot unavailable)' }
}

/** 关旧抽屉→点指定 fixture 行→等抽屉渲染。 */
async function openDetail(page, fid) {
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  const rowEl = page.locator('.wb-card[data-ticket-id]', { hasText: fid }).first()
  if (!(await waitFor(async () => (await rowEl.count()) > 0, 8000))) {
    throw new Error(`fixture row ${fid} not rendered (list stub not consumed?)`)
  }
  await rowEl.click()
  // 就绪信号锚详情渲染产物（正文卡标题进 DOM），不锚 .wb-drawer 容器——容器常驻
  // DOM（同 ki048 用 .wb-d2-steps 的道理：锚渲染产物，不锚挂载点）。哪个 fid 由
  // 上一步点击保证；列表行也含 fid，故不能拿 fid 当就绪信号。
  const ok = await waitFor(async () => await page.evaluate(() =>
    (document.body.textContent || '').includes('工单正文（原始需求）') ||
    !!document.querySelector('.wb-d2-spec, .wb-d2-steps, .wb-d2-body')), 8000)
  if (!ok) throw new Error(`detail drawer did not render ${fid}`)
}

// ---- E1 界面英文化（锚「无 CJK + 未知回落」，不锚英文措辞——映射表措辞是 developer 面）

async function scenarioEnglishChrome(page) {
  await openDetail(page, FID_A)
  // 详情抽屉界面骨架：卡标题/计数徽标/步骤条不含 CJK；数据卡（正文/spec 源文本）含 CJK。
  const m = await page.evaluate(() => {
    const d = document.querySelector('.wb-drawer') || document.body
    const ttls = [...d.querySelectorAll('.ttl')].map(e => e.textContent || '')
    const cnts = [...d.querySelectorAll('.cnt')].map(e => e.textContent || '')
    // 正文卡数据直接渲染在 .wb-d2-body 里（卡头 .ttl 是界面骨架，正文无 .txt 包裹层——
    // t260904-06 起即如此；textContent 含卡头拉丁标题不影响 CJK 检测）。
    const bodyTxt = d.querySelector('.wb-d2-body')?.textContent || ''
    const all = d.textContent || ''
    return { ttls, cnts, bodyTxt, all }
  })
  if (!m.ttls.length) return 'no .ttl headings found in detail drawer (drawer shape changed?)'
  const cjkTtl = m.ttls.filter(t => CJK.test(t))
  if (cjkTtl.length) return `interface headings still contain CJK: ${JSON.stringify(cjkTtl.slice(0, 5))}`
  // 详情头工作流模板名（状态徽标同排的 .wb-sub，index.tsx 头部 meta 行）：用户原话点名
  // 「开发泳道」必须英文——WORKFLOW_TABLE 已备，渲染点须走 workflowLabel(id)（未知模板
  // id 回落原始 id，不空白不中文）。t260925-18 gen2 F2。
  const wfName = await page.evaluate(() => {
    const el = document.querySelector('.wb-badge[data-kind="status"] ~ .wb-sub')
    return el ? (el.textContent || '').trim() : null
  })
  if (wfName === null) return 'detail header workflow template line (.wb-sub after status badge) not found (header shape changed?)'
  if (!wfName) return 'detail header workflow template line is blank (fallback contract violated: never blank)'
  if (CJK.test(wfName)) return `detail header workflow template name still CJK (expected workflowLabel mapping or raw id): ${JSON.stringify(wfName)}`
  const cjkCnt = m.cnts.filter(t => CJK.test(t))
  if (cjkCnt.length) return `counter badges (「N 字」family) still contain CJK: ${JSON.stringify(cjkCnt.slice(0, 5))}`
  if (!CJK.test(m.bodyTxt)) return 'body card lost its Chinese data — data must NOT be translated (english-ui + chinese-content is the contract)'
  // 已知 stage 的当前步骤显示拉丁标签或原始 id（两者都是映射契约的合法产出），不得空白。
  // 步骤条是「无拓扑回落」形态（有拓扑时渲染泳道图，.wb-d2-steps 不存在——t260915-05 口径）；
  // 有泳道图时段标签契约由 E4 断言，此处只在步骤条在场时才检查，不做结构性必现断言。
  const stepper = await page.evaluate(() => {
    const s = document.querySelector('.wb-d2-steps, .wb-lanemap')
    return s ? (s.textContent || '').trim() : ''
  })
  if (stepper && !/[A-Za-z]{3,}/.test(stepper)) return `stepper has no latin (english/id) label for known stage: ${JSON.stringify(stepper.slice(0, 120))}`
  return null
}

async function scenarioUnknownEnumFallback(page) {
  await openDetail(page, FID_B)
  // 未知枚举：原始标识必须原样出现在抽屉（回落契约=永不空白、永不中文、不吞值）。
  const txt = await page.evaluate(() => document.body.textContent || '')
  for (const raw of ['weird_stage_x', 'weird_state_y', 'weird_status_z']) {
    if (!txt.includes(raw)) return `unknown enum value ${raw} fell back to nothing — contract: raw identifier must stay visible`
  }
  return null
}

async function scenarioSidebarEnglish(page) {
  // 左栏行：状态/阶段字段无 CJK；中文票标题（数据）原样保留。
  const rows = await page.evaluate(() => {
    return [...document.querySelectorAll('.wb-card[data-ticket-id]')].map(el => ({
      id: el.getAttribute('data-ticket-id'),
      text: el.textContent || '',
    }))
  })
  const c = rows.find(r => r.id === FID_C)
  if (!c) return `fixture row ${FID_C} missing from list`
  if (!c.text.includes('夹具票C')) return `Chinese ticket title (data) must stay untranslated, row text: ${JSON.stringify(c.text.slice(0, 120))}`
  const withoutTitle = c.text.replace(/夹具票C·中文标题数据不译对照/g, '')
  if (CJK.test(withoutTitle)) return `sidebar row interface fields still contain CJK beyond the data title: ${JSON.stringify(withoutTitle.slice(0, 160))}`
  return null
}

// ---- E2 spec markdown + 消毒

async function scenarioSpecMarkdown(page) {
  await openDetail(page, FID_A)
  const card = await page.evaluate(() => {
    const el = document.querySelector('.wb-d2-spec')
    if (!el) return null
    const txt = el.querySelector('.txt')
    return {
      hasTxt: !!txt,
      h1: !!txt?.querySelector('h1,h2,h3'),
      li: txt?.querySelectorAll('li').length ?? -1,
      strong: !!txt?.querySelector('strong,b'),
      code: !!txt?.querySelector('code'),
      pre: !!txt?.querySelector('pre'),
      script: txt?.querySelectorAll('script').length ?? -1,
      imgOnerror: [...(txt?.querySelectorAll('img') || [])].some(i => i.getAttribute('onerror')),
      jsHref: [...(txt?.querySelectorAll('a') || [])].some(a => /^javascript:/i.test(a.getAttribute('href') || '')),
      literalEscaped: (txt?.textContent || '').includes('<script>'),
      chineseKept: (txt?.textContent || '').includes('中文数据段'),
      pwned: window.__pwned === true,
    }
  })
  if (!card) return '.wb-d2-spec card not rendered for ticket with spec'
  if (!card.hasTxt) return 'spec card lost its .txt content region'
  for (const [k, v] of [['heading', card.h1], ['list items', card.li > 0], ['bold', card.strong], ['inline code', card.code], ['code fence', card.pre]]) {
    if (!v) return `basic markdown not rendered: missing ${k} element (raw blob regression?)`
  }
  if (card.script !== 0) return `active <script> element(s) in spec card: ${card.script}`
  if (card.imgOnerror) return '<img onerror> attribute survived sanitization'
  if (card.jsHref) return 'javascript: href survived sanitization'
  if (!card.literalEscaped) return 'injected HTML not shown escaped as literal text (dropped silently?)'
  if (!card.chineseKept) return 'spec Chinese content lost — data must not be translated'
  if (card.pwned) return 'window.__pwned set — injection EXECUTED (critical)'
  return null
}

async function scenarioSpecLegacyTicket(page) {
  // 无 spec 老票：spec 卡不渲染、正文卡照旧、页面不崩。
  const has = await page.evaluate(() => !!document.querySelector('.wb-d2-spec'))
  if (has) return `spec card rendered for ticket without spec (${FID_C})`
  const body = await page.evaluate(() => !!document.querySelector('.wb-d2-body'))
  if (!body) return 'legacy ticket lost its body card'
  return null
}

// ---- E3 底部六区块移除（锚被移除区块的中文界面标题不在抽屉）

const REMOVED_HEADINGS = ['基本信息', '入参', '验收清单', '流水', '接力时间线', '快照要点']
async function scenarioBottomSectionsRemoved(page) {
  await openDetail(page, FID_A)
  const txt = await page.evaluate(() => {
    const d = document.querySelector('.wb-drawer') || document.body
    return d.textContent || ''
  })
  // 「入参」「验收清单」「流水」按界面标题语义匹配可能撞数据词，故对数据面白名单：
  // 夹具数据不含这些词，抽屉出现即视为区块未删净。
  for (const h of REMOVED_HEADINGS) {
    if (txt.includes(h)) return `removed bottom section heading still present in drawer: ${h}`
  }
  return null
}

// ---- E4 泳道图 stage id 映射

async function scenarioLaneMapLabels(page) {
  await openDetail(page, FID_A)
  const map = await page.evaluate(() => {
    const el = document.querySelector('.wb-lanemap, [data-template]')
    return el ? (el.textContent || '') : null
  })
  if (map === null) return 'lane map not rendered (topology stub consumed?)'
  for (const zh of ['做方案', '审方案']) {
    if (map.includes(zh)) return `engine Chinese template label leaked to lane map UI: ${zh} (stage-id mapping contract)`
  }
  if (!map.includes('weird_stage_x')) return `unknown topology node id weird_stage_x not shown raw (fallback contract)`
  if (!/[A-Za-z]{3,}/.test(map)) return 'lane map has no latin labels at all — mapping table not applied?'
  return null
}

// ---------------------------------------------------------------- browser run

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree — cwd is the main checkout */ }
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
  for (const c of candidates) {
    try { return await import(c) } catch { /* next candidate */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function run() {
  const ctx = { browser: null, pw: null }
  try { ctx.pw = await loadPlaywright() } catch { /* treated as missing below */ }
  if (!ctx.pw) {
    record('S0 playwright', 'env_fail', 'playwright-core 不可解析（KI-036 家族：ui-check 依赖缺席，恢复后自动生效）')
    summarize()
  }
  ctx.browser = await launchBrowser(ctx.pw)
  if (!ctx.browser) {
    record('S0 chromium', 'env_fail', '无可启动的 chromium/chrome（headless）')
    summarize()
  }

  const browser = ctx.browser
  const bctx = await browser.newContext()
  const pageErrors = []
  const consoleErrors = []
  const dialogsFired = []
  const page = await bctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
  page.on('dialog', async d => { dialogsFired.push(d.message().slice(0, 80)); await d.dismiss().catch(() => {}) })
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(3000)
  await dismissOverlays(page)

  // API 边界桩：list/detail/workflows 全夹具；未知 id/子路由 ok:false（绝不漏到真台）。
  await page.route('**/sandbar-workbench/api/wf/tickets**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/\/+$/, '')
    const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
    if (path === '/sandbar-workbench/api/wf/tickets') {
      return body({ ok: true, result: { tickets: ROWS }, workflows: [WF] })
    }
    const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
    if (m && DETAIL_BY_ID[decodeURIComponent(m[1])]) {
      return body({ ok: true, result: DETAIL_BY_ID[decodeURIComponent(m[1])] })
    }
    return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
  })
  await page.route('**/sandbar-workbench/api/wf/workflows**', (route) => {
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: [WF] }) })
  })

  // 板入口图标锚用 class 逐个试探（不锚 title 文案——title 本身是本票英文化对象）。
  const icons = page.locator('span.wb-view-icon')
  const nIcons = await waitFor(async () => await icons.count() > 0, 10000) ? await icons.count() : 0
  if (!nIcons) {
    record('S1 precheck', 'env_fail', `no .wb-view-icon found on ${BASE} (console not provisioned for board view)`)
    summarize()
  }
  let opened = false
  for (let i = 0; i < nIcons && !opened; i++) {
    await icons.nth(i).click().catch(() => {})
    opened = await waitFor(async () =>
      (await page.locator('.wb-card[data-ticket-id]', { hasText: FID_A }).count()) > 0, 5000)
  }
  if (!opened) {
    record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
    summarize()
  }

  const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
  const run1 = async (name, fn) => {
    try {
      const err = await fn(page)
      if (err) record(name, 'fail', err)
      else record(name, 'pass')
    } catch (e) { await failWith(name, e) }
  }

  await run1('E1 detail chrome english + chinese data kept', scenarioEnglishChrome)
  await run1('E1b unknown enum falls back to raw identifier', scenarioUnknownEnumFallback)
  await run1('E1c sidebar row fields english + title data kept', scenarioSidebarEnglish)
  await run1('E2 spec card renders basic markdown', scenarioSpecMarkdown)
  await run1('E2b spec injection inert (script/img-onerror/js-href)', async () => {
    // 注入断言已在 E2 逐项锁；此条单独锁「注入样本未执行」全局面（dialog/pwned）。
    if (dialogsFired.length) return `dialog fired from injected payload: ${JSON.stringify(dialogsFired)}`
    const pwned = await page.evaluate(() => window.__pwned === true)
    if (pwned) return 'window.__pwned set anywhere — injection executed'
    return null
  })
  await run1('E2c legacy ticket without spec: zero disturbance', async (p) => {
    await openDetail(p, FID_C)
    return scenarioSpecLegacyTicket(p)
  })
  await run1('E3 bottom six sections removed from drawer', scenarioBottomSectionsRemoved)
  await run1('E4 lane map labels from stage-id mapping + raw fallback', scenarioLaneMapLabels)
  await run1('E5 zero pageerror/console.error hygiene', async () => {
    if (pageErrors.length) return `pageerror: ${JSON.stringify(pageErrors.slice(0, 3))}`
    if (consoleErrors.length) return `console.error: ${JSON.stringify(consoleErrors.slice(0, 3))}`
    return null
  })

  await bctx.close()
  await browser.close()
  summarize()
}

run().catch(e => { console.error('FATAL', e); record('S1 run', 'fail', String(e).slice(0, 200)); summarize() })
