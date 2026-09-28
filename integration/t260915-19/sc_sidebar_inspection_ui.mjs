#!/usr/bin/env node
// t260915-19 场景：左栏收录巡检票——「分拣制」UI 面（t260915-20 落仓后新口径，方案 v2 定稿）。
// （灰盒 L3 渲染层，browser-free 池；镜 t260915-08/sc_inspection_board_ui.mjs 两层式。）
//
// 用户场景（宿主实报「左边栏也看不见巡检票」）：宿主打开工作台，左栏必须能看见巡检票——
// 有项目身份的巡检行并进对应项目组（t260916-15 起组内与 dev 行合并统一口径排序，本场景
// 只守反沉底全序烟测（等你→在跑三行全序），排序全口径矩阵归 t260916-15 场景）；老票/无身份行进显式「巡检」
// 兜底组（不静默丢失）；到人审门的巡检行按既有「等你」口径黄调一眼可见（项目 dev 行不上漆=
// 左栏项目组渲染零变化的对照面）；点行下钻=中列同款巡检详情抽屉；端点失败=左栏显式降级横幅
// （含错误原文）且快照行保留（不吞成空列表）。
//
// 两层（镜 08 拆法）：
//   S0 build-contract（纯 node 处处可跑）：shipped 双 bundle 同步 + 左栏巡检锚点在位
//      （端点串/两个 data-testid/data-engine 黄调选择器）+ node.ts 巡检 502 原文透传源锚。
//   S1 真浏览器 DOM 断言：隔离台（SANDBAR_TEST_CONSOLE，经 lib_stage_console 按测试树起台）
//      + playwright-core + chromium，任一缺席=ENV_FAIL exit 2 点名。数据只在 API 边界打桩
//      （page.route），且自带 /wf/projects 桩——项目组渲染不依赖台面真实注册表（确定性
//      夹具，组/行/序全可控）；绝不碰生产 3099/真票。
// 三态（t260904-12）：stdout 末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
// env_fail>0=exit 2。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// intent 分界：与 t260915-08-board-ui 不同面——彼守中列板面巡检行/详情/签字通道，本条守
// 左栏分拣制（项目组归位/兜底组/反沉底烟测）/左栏等你黄调/左栏降级显式性；与
// t260903-07-click-no-chat-switch 不同面（彼守点行不切会话，本守左栏巡检行的存在与行为）。
// KI 对齐：KI-018①（错误文案进横幅不进数据字段=降级子用例断言）、KI-051（原文断子串不锚整句、
// 语义 testid 锚）、KI-055（真机计算样式断言+bundle 锚，防台面绿真机红）、t260910-04 R3/
// KI-008（失败保快照不吞空列表）。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
// 取台走 lib_fix17 bootConsole（t260915-19 实测定案）：非 docker 形态——本泳道
// worktree 直起 dsh 台（freePort 拒 3099=红线零接触；teardownOnExit 全终态回收），
// 台加载的 workbench=本 worktree lib bundle（buildProfile 指本仓插件目录）。docker
// 形态供给台（ensureStageConsole）在本环境不可得（孤儿台租约死+docker daemon 不可
// 达，260916 实录），同族 t260915-09/t260915-10 已用此通道跑绿=先例。
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t260915-19-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', '夹具甲', ['/tmp/fx-alpha'])
  writeProjectEntry(projectsRoot, 'fixture-beta', '夹具乙', ['/tmp/fx-beta'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  BASE = bench.base
  await benchAuthUrl(bench) // dsh 会话门：先拿带 token 首页地址（拿不到=ENV_FAIL exit 2），否则首页 401 无 DOM
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console 不可得：${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

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

// ---------------------------------------------------------------- 夹具（API 桩数据面）

const PROJ_A = 'fixture-alpha'   // 在册项目甲（纯小写字母数字中划线，引擎 key 白名单内）
const PROJ_B = 'fixture-beta'    // 在册项目乙
const DEV_A_RUN = 'devfixa1901run'    // 甲组 dev 工单（进行中；序位对照）
const DEV_A_WAIT = 'devfixa1902wait'  // 甲组 dev 工单（到人审门=等你行，不上漆对照面）
const INS_A = 'inspfixa1903a'    // 巡检行·归属甲（到人审门=黄行主角）
const INS_B = 'inspfixb1904b'    // 巡检行·归属乙（乙组零 dev 票——巡检行顶替「无进行中工单」面）
const INS_UN = 'inspfixun1905u'  // 巡检老票·无项目身份（兜底组面）

const WORKFLOWS = [{
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'arbitrate', name: '仲裁', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
  ],
}]

function devRow(id, stageState, title, updatedTs = 1789354800) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: updatedTs,
    created: 1789354800, engine: 'template-as-code-v2', exec_status: 'RUNNING',
  }
}

// 引擎巡检行形状（t260915-08 方案 R4 + t260915-20 行 project 字段=SA 直读）。
function insRow(over) {
  return {
    id: '', kind: 'inspection', engine: 'inspection', project: '', epic: '',
    title: '', template: 'inspection-lite',
    instance_id: '', period: '20260915', stage: 'inspect', stage_state: 'running',
    status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
    heartbeat: true, report_path: '', awaiting_gate: false, human_gate: null,
    blocked_reason: '', gate_error: '', created: 1789354800, updated: '09-15 07:30',
    updated_ts: 1789354800, paused: false, paused_phase: '', handoff_count: 0,
    pending_count: 0, worktree: '', workspace: null, role: null, proposal_id: '',
    workflow: '', close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
    ...over,
  }
}

const INS_ROWS = [
  insRow({
    id: INS_A, project: PROJ_A, instance_id: 'fixture-alpha', title: '巡检 fixture-alpha · 期 20260915',
    stage: 'close', stage_state: 'awaiting-human', awaiting_gate: true,
    findings: { high: 1, med: 2, low: 0, total: 3 },
    // t260916-15 反沉底烟测配套：INS_A updated_ts 拉到最新（引擎单位=秒）——合并口径下
    // 等你巡检行（tier0+最新 ts）必须排在在跑 dev 行（tier1）之前，恒尾旧序必红。
    created: 1789362000, updated_ts: 1789362000,
    report_path: 'out/inspection/inspfixa1903a.json',
  }),
  insRow({
    id: INS_B, project: PROJ_B, instance_id: 'fixture-beta', title: '巡检 fixture-beta · 期 20260915',
    stage: 'inspect', stage_state: 'running',
    findings: { high: 0, med: 0, low: 1, total: 1 },
    report_path: 'out/inspection/inspfixb1904b.json',
  }),
  insRow({
    id: INS_UN, project: '', instance_id: 'legacy', title: '巡检 legacy · 期 20260901',
    stage: 'report', stage_state: 'running',
    findings: { high: 0, med: 1, low: 0, total: 1 },
    report_path: 'out/inspection/inspfixun1905u.json',
  }),
]

const tle = (stage, state, reason = '') => ({ at: '2026-09-15T07:30:00', stage, state, reason })
const INS_A_DETAIL = {
  id: INS_A, kind: 'inspection', engine: 'inspection', template: 'inspection-lite',
  title: '巡检 fixture-alpha · 期 20260915', stage: 'close', stage_state: 'awaiting-human',
  status: 'running', decision: '', gate_id: 'inspection-close',
  instance_id: 'fixture-alpha', period: '20260915',
  report_path: 'out/inspection/inspfixa1903a.json',
  red_line: '巡检只出报告与开票建议，绝不直接改码。',
  heartbeat: true, summary: { high: 1, med: 2, low: 0 },
  findings: [
    { id: 'f1', scan: 'test', severity: 'high', subject: '高危样例', evidence: 'evidence-high', suggestion: '开票修' },
  ],
  suggested_fix_tickets: [], blocked_reason: '', human_gate: null, gate_error: '',
  worktree: '', workspace: null,
  timeline: [tle('inspect', 'done'), tle('report', 'done'), tle('close', 'running', '人审发现清单')],
}

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const NODE_TS = join(REPO, 'server', 'plugins', 'workbench', 'node.ts')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return
  }
  // 锚=语义契约面（端点串/两个 data-testid/黄调等值选择器），不锚易漂移文案字面（KI-051）。
  const anchors = ['wf/inspection/tickets', 'sidebar-inspection-head', 'sidebar-inspection-degraded', 'data-engine=inspection']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 bundle-anchors', 'fail', `shipped bundle missing sidebar inspection anchors: ${missing.join(', ')}（实现段未落地或未重建=预期红）`)
  } else {
    record('S0 bundle-anchors', 'pass', 'twin bundles in sync, sidebar inspection anchors present')
  }
  if (!existsSync(NODE_TS)) {
    record('S0 host-502-passthrough', 'fail', 'node.ts missing')
    return
  }
  // 巡检端点 ok:false→502 原文透传纪律（t260910-04 R3）：左栏降级横幅的原文真源在 host。
  const host = readFileSync(NODE_TS, 'utf8')
  if (/ticket-list\(inspection\) 失败/.test(host)) {
    record('S0 host-502-passthrough', 'pass', 'node.ts 巡检端点 502 原文透传在位（不吞成空列表）')
  } else {
    record('S0 host-502-passthrough', 'fail', 'node.ts handleInspectionTickets 未见 ticket-list(inspection) 失败透传（降级横幅将无原文可显）')
  }
}

// ---------------------------------------------------------------- S1 真浏览器

function consoleHealthy() {
  // 首页受 dsh 浏览器会话门保护（匿名 GET / 恒 401）：探带 token 首页地址——
  // 200（cookie 已兑换）与 303（token 可兑换）都算台面在位。
  const url = bench.authUrl ?? `${BASE}/`
  return fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(5000) })
    .then(r => r.status === 303 || r.ok).catch(() => false)
}

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
  for (const c of candidates) {
    try { return await import(c) } catch { /* next */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
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

// 行→组归属走爬（组容器是无类名 div，绑「祖先含组头」不绑实现类名——灰盒绑定要浅）：
// 返回 组 dot 的 title（=项目 key）/ '__fallback__'（兜底组）/ 'absent' / 'no-group'。
async function ownerOf(page, id) {
  return page.evaluate((tid) => {
    const el = document.querySelector(`.wb-sb .wb-card[data-ticket-id="${tid}"]`)
    if (!el) return 'absent'
    const hasHead = (n) => n && (n.querySelector('.wb-group-head') || n.querySelector('[data-testid="sidebar-inspection-head"]'))
    let d = el.parentElement
    while (d && !hasHead(d)) d = d.parentElement
    if (!d) return 'no-group'
    if (d.querySelector('[data-testid="sidebar-inspection-head"]')) return '__fallback__'
    const dot = d.querySelector('.wb-group-dot')
    return dot ? (dot.getAttribute('title') || '') : 'unknown'
  }, id)
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    await bench.goto(page, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    // 数据只在 API 边界打桩；inspection 载荷可变（降级子用例换 ok:false）。
    let insPayload = { ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }
    const DEGRADE = { ok: false, error: 'ticket-list(inspection) 失败: fixture 降级注入 0x519' }
    await page.route('**/sandbar-workbench/api/wf/**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      if (path === '/sandbar-workbench/api/wf/projects') {
        return route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            result: {
              projects: [
                { key: PROJ_A, name: '夹具甲', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
                { key: PROJ_B, name: '夹具乙', primary: '/tmp/fx-beta', dirs: ['/tmp/fx-beta'] },
              ],
              quarantined: [],
            },
          }),
        })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        const proj = url.searchParams.get('project') || ''
        const tickets = proj === PROJ_A
          ? [devRow(DEV_A_RUN, 'running', '甲组进行中 dev 票'), devRow(DEV_A_WAIT, 'awaiting-human', '甲组等你 dev 票')]
          : []
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets, workflows: WORKFLOWS } }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(insPayload) })
      }
      const m = /^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && decodeURIComponent(m[1]) === INS_A) {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: INS_A_DETAIL }) })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown ticket or sub-route' }) })
    })

    // precheck：自带 /wf/projects 桩 → 项目组必须真渲染（不依赖台面真实注册表）。
    const groupHeadA = page.locator(`.wb-sb .wb-group-dot[title="${PROJ_A}"]`).first()
    if (!(await waitFor(async () => (await groupHeadA.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `左栏项目组未渲染（stub /wf/projects 未被消费？台面=${BASE}）`)
      return
    }
    record('S1 precheck', 'pass', `左栏项目组渲染（${PROJ_A}/${PROJ_B}）`)

    // 等第一拍 load 完成：侧栏 setProjects 先落账（组头先出）、逐组拉取与巡检行
    // 分拣后到——不候行落组，①②子用例会跑在渲染前（ownerOf 读到 absent 的时序假红）。
    const insCardProbe = page.locator(`.wb-sb .wb-card[data-ticket-id="${INS_A}"]`).first()
    if (!(await waitFor(async () => (await insCardProbe.count()) > 0, 15000))) {
      record('S1 rows-landed', 'fail', `巡检行未落组（${INS_A} 缺席）——分拣面未落地或轮询未完成`)
      return
    }
    record('S1 rows-landed', 'pass', '巡检行已落组渲染（第一拍 load 完成）')

    // ① 分拣归位：有身份巡检行进对应项目组（不是兜底组、不是引擎级散组）。
    const ownerA = await ownerOf(page, INS_A)
    const ownerB = await ownerOf(page, INS_B)
    const okSplit = ownerA === PROJ_A && ownerB === PROJ_B
    record('S1 split-by-project', okSplit ? 'pass' : 'fail',
      okSplit ? `巡检行归位：${INS_A}→${PROJ_A}，${INS_B}→${PROJ_B}`
        : `分拣面未落地或归位错：${INS_A}→${ownerA}，${INS_B}→${ownerB}`)

    // ② 反沉底全序烟测（t260916-15 契约变更配套改写，非凑绿；review 意见④：
    //    断言完整期望序列而非两行相对序——相对序分不出「级内 updated_ts 倒序」
    //    是否真生效）。夹具 ts 拉开：INS_A(等你, ts+2h) > DEV_A_WAIT(等你, ts+0)
    //    同 tier0 级内倒序 → 二者先于在跑的 DEV_A_RUN(tier1)，全序三行一次钉死
    //    tier 边界+级内倒序两面。含收口行/兜底组序的全矩阵归
    //    t260916-15-sidebar-merged-sort-ui 场景，此处不重复。
    const orderOk = await page.evaluate(([proj, want]) => {
      const dot = document.querySelector(`.wb-sb .wb-group-dot[title="${proj}"]`)
      if (!dot) return 'no-group'
      let w = dot.parentElement
      while (w && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
      if (!w) return 'no-wrapper'
      const ids = [...w.querySelectorAll('.wb-card[data-ticket-id]')].map(e => e.getAttribute('data-ticket-id'))
      return ids.join(',') === want ? 'anti-sink' : 'order=' + ids.join(',')
    }, [PROJ_A, [INS_A, DEV_A_WAIT, DEV_A_RUN].join(',')])
    record('S1 anti-sink-smoke', orderOk === 'anti-sink' ? 'pass' : 'fail',
      orderOk === 'anti-sink' ? '组内全序=等你层(级内倒序)→在跑层（反沉底）' : `组内行序面异常：${orderOk}`)

    // ③ 行1/行2 字样与端点一致：标题=引擎 title；行2=等你签字 · 发现 高x/中y/低z（face 层既有词表）。
    const insCardA = page.locator(`.wb-sb .wb-card[data-ticket-id="${INS_A}"]`).first()
    const rowText = await insCardA.innerText().catch(() => '')
    const missFields = [
      ['行1 标题「巡检 fixture-alpha · 期 20260915」', rowText.includes('巡检 fixture-alpha · 期 20260915')],
      // 行2 的**界面标签**随宿主令 260925 英文化（现取值「Awaiting your signature ·
      // findings H1/M2/L0」；旧中文「等你签字 · 发现 高1/中2/低0」已退役）；行1 标题仍是
      // 引擎数据（不译）——本子用例=界面字段与端点数据一致，两个面分别锚。
      ['行2 等你签字', /Awaiting your signature|等你签字/.test(rowText)],
      ['行2 发现数 H1/M2/L0', /findings\s*H1\/M2\/L0|发现\s*高1\/中2\/低0/.test(rowText)],
    ].filter(([, good]) => !good).map(([label]) => label)
    record('S1 row-fields', missFields.length ? 'fail' : 'pass',
      missFields.length ? `行文本缺字段：${missFields.join('；')}；text=${rowText.replace(/\s+/g, ' ').slice(0, 160)}` : '行1 标题+行2 等你/发现数与端点一致')

    // ④ 兜底组：无身份老票显式在「巡检」组（不静默丢失、不落错组）。
    const fbHead = page.locator('.wb-sb [data-testid="sidebar-inspection-head"]').first()
    const fbHeadOk = await waitFor(async () => (await fbHead.count()) > 0, 8000)
    const ownerUn = fbHeadOk ? await ownerOf(page, INS_UN) : 'absent'
    const fbText = fbHeadOk ? await fbHead.innerText().catch(() => '') : ''
    // 绑浅：老票「不在任何项目组」+ 兜底组头在场即可（wrapper 形态不锚——走爬认不出
    // 无头 wrapper 的实现变体时不误伤，落错组才是用户可感知缺陷）。
    // 兜底组名=INSPECTION_ROW_BADGE（host/inspection-face.ts，260925 后取值 'Inspection'，
    // 旧中文「巡检」已退役）；中英双accept，判据仍是「兜底组头在场且点名该类」。
    const fbOk = fbHeadOk && /巡检|Inspection/.test(fbText)
      && ownerUn !== 'absent' && ownerUn !== PROJ_A && ownerUn !== PROJ_B
    record('S1 fallback-group', fbOk ? 'pass' : 'fail',
      fbOk ? `兜底组在场（head 含「巡检」），老票 ${INS_UN} 不在任何项目组（owner=${ownerUn}）`
        : `兜底组面异常：head=${fbHeadOk}（text=${fbText.slice(0, 60)}），${INS_UN}→${ownerUn}`)

    // ⑤ 乙组零 dev 票：巡检行顶替「无进行中工单」占位（空态语义=有内容不占位）。
    const bGroupText = await page.evaluate((proj) => {
      const dot = document.querySelector(`.wb-sb .wb-group-dot[title="${proj}"]`)
      if (!dot) return ''
      let w = dot.parentElement
      while (w && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
      return w ? w.innerText : ''
    }, PROJ_B)
    const bOk = bGroupText.includes(INS_B) && !bGroupText.includes('无进行中工单')
    record('S1 group-b-no-empty-placeholder', bOk ? 'pass' : 'fail',
      bOk ? '乙组由巡检行呈现、无「无进行中工单」占位' : `乙组空态语义异常：text=${bGroupText.replace(/\s+/g, ' ').slice(0, 100)}`)

    // ⑥ 等你黄调（KI-055 真机计算样式）：巡检 waiting 行上漆；dev 等你对照行不上漆（左栏项目行零变化反断言）。
    const stateIns = await insCardA.getAttribute('data-state')
    const bgIns = await insCardA.evaluate(el => getComputedStyle(el).backgroundColor).catch(() => '')
    const devCardWait = page.locator(`.wb-sb .wb-card[data-ticket-id="${DEV_A_WAIT}"]`).first()
    const stateDev = await devCardWait.getAttribute('data-state').catch(() => '')
    const bgDev = await devCardWait.evaluate(el => getComputedStyle(el).backgroundColor).catch(() => '')
    const painted = (bg) => {
      const mRgba = /^rgba?\(([^)]+)\)$/.exec(bg || '')
      const mColor = /^color\(srgb\s+([^)]+)\)$/.exec(bg || '')
      const parts = mRgba ? mRgba[1].split(/[,/]/).map(s => parseFloat(s))
        : mColor ? mColor[1].split(/[\s,/]+/).filter(Boolean).map(s => parseFloat(s) * 255)
        : []
      const alpha = mColor ? 1 : (parts.length >= 4 ? parts[3] : (parts.length === 3 ? 1 : 0))
      const whiteish = parts.length >= 3 && parts[0] > 250 && parts[1] > 250 && parts[2] > 250
      return alpha > 0 && !whiteish
    }
    const yellowOk = stateIns === 'waiting' && painted(bgIns)
    const controlOk = stateDev === 'waiting' && !painted(bgDev)
    record('S1 waiting-yellow-inspection', yellowOk ? 'pass' : 'fail',
      yellowOk ? `巡检等你行上漆 data-state=waiting bg=${bgIns}` : `巡检等你行未上漆：state=${stateIns} bg=${bgIns}`)
    record('S1 waiting-yellow-control', controlOk ? 'pass' : 'fail',
      controlOk ? `dev 等你对照行保持不上漆（state=${stateDev} bg=${bgDev}）=左栏项目行零变化`
        : `dev 等你对照行被波及：state=${stateDev} bg=${bgDev}（左栏项目行外观变化=零回归破面）`)

    // ⑦ 点行下钻=中列同款巡检详情（同 data-testid=inspection-face 组件锚）。
    await insCardA.click()
    const faceOk = await waitFor(async () => (await page.locator('[data-testid="inspection-face"]').count()) > 0, 10000)
    record('S1 click-drilldown', faceOk ? 'pass' : 'fail',
      faceOk ? '左栏点巡检行→inspection-face 详情抽屉（与中列同组件）'
        : '左栏点巡检行未开巡检详情（inspection-face 缺席）')
    await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
    await page.keyboard.press('Escape').catch(() => {})
    await waitFor(async () => (await page.locator('.wb-drawer, [role="dialog"]').count()) === 0, 5000)

    // ⑧ 降级子用例（KI-018①/051/t260910-04 R3）：端点 ok:false → 横幅显原文子串；快照行保留；
    //    错误文案不写进行数据（行文本不含「拉取失败」）。
    insPayload = DEGRADE
    const banner = page.locator('.wb-sb [data-testid="sidebar-inspection-degraded"]').first()
    const bannerOk = await waitFor(async () => (await banner.count()) > 0, 15000) // 侧栏 10s 轮询+余量
    const bannerText = bannerOk ? await banner.innerText().catch(() => '') : ''
    const bannerHit = bannerOk && bannerText.includes('fixture 降级注入 0x519')
    const snapA = await ownerOf(page, INS_A)
    const snapUn = await ownerOf(page, INS_UN)
    const rowsKept = snapA === PROJ_A && snapUn !== 'absent' && snapUn !== PROJ_A && snapUn !== PROJ_B
    const rowTextAfter = await page.evaluate(() =>
      [...document.querySelectorAll('.wb-sb .wb-card[data-ticket-id]')].map(e => e.textContent || '').join('|'))
    const noLeak = !rowTextAfter.includes('拉取失败') && !rowTextAfter.includes('fixture 降级注入')
    const degradeOk = bannerHit && rowsKept && noLeak
    record('S1 degrade-banner', degradeOk ? 'pass' : 'fail',
      degradeOk ? `降级横幅显原文子串（…${bannerText.slice(-40).trim()}），快照行保留，错误文案未进行数据`
        : `降级面异常：banner=${bannerOk}（text=${bannerText.slice(0, 80)}）snapA=${snapA} snapUn=${snapUn} noLeak=${noLeak}`)

    // ⑨ 卫生子用例：全旅程零 pageerror。
    record('S1 page-health', pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror 计 ${pageErrors.length}：${pageErrors.slice(0, 3).join(' | ')}` : '全程零 pageerror')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- 主流程

buildContract()
// consoleHealthy 是 async——不 await 则恒真值（promise 对象），ensure 成功后台面中途
// 死掉的场景会漏进浏览器子用例拿「未捕获异常=FAIL」而非诚实 env_fail（三态误报修正，
// 260916 仲裁归因轮；08 同形不在本票写集，随岗位置另议）。
if (!(await consoleHealthy())) {
  record('S1 console', 'env_fail', `测试控制台不可达：${BASE}（supply 台未起？宿主 3099 红线不碰）`)
} else {
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 playwright', 'env_fail', 'playwright-core 不可解析（候选路径全落空）')
  } else {
    const browser = await launchBrowser(pw)
    if (!browser) {
      record('S1 chromium', 'env_fail', 'chromium/chrome 无法启动（headless 环境缺浏览器）')
    } else {
      try {
        await runBrowser(pw, browser)
      } catch (e) {
        // 三态纪律：意外异常=FAIL 落账+SUMMARY 收口，绝不裸异常逃逸（逃逸=闸侧计数失真）。
        record('S1 run-browser', 'fail', `未捕获异常：${String(e).slice(0, 300)}`)
      } finally {
        await browser.close().catch(() => {})
      }
    }
  }
}
summarize()
