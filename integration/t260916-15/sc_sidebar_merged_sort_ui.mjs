#!/usr/bin/env node
// t260916-15 场景：左栏工单合并排序 + 巡检行徽标可辨（巡检票不再沉底）。
// （灰盒 L3 渲染层，browser-free 池；镜 t260915-19/sc_sidebar_inspection_ui.mjs 两层式。）
//
// 用户场景（宿主 260916 当面实报「巡检票在左栏显示在最下面」）：宿主打开工作台看某项目组，
// 巡检行与 dev 工单行按同一口径排序——在等你（blocked/awaiting-human）→ 在跑（running）→
// 已完成（done/closed），同级按 updated_ts 倒序——巡检行不因数据来源不同而沉底；巡检行
// 带可辨认徽标（扫视可辨、可被选择器命中），dev 行渲染零变化（零徽标对照面）；行1 沿用
// 引擎标题原样（排序不得改行内容）。
//
// 两层（镜 0915-19 拆法）：
//   S0 build-contract（纯 node 处处可跑）：shipped 双 bundle 同步 + 合并排序/徽标锚在
//      shipped bundle（wb-card-kind 类字面 + data-kind-badge 属性字面——字符串字面过
//      压缩器存活；函数名不锚=压缩器改名面）。盘上 bundle 新鲜锚=KI-052（改源忘重建
//      的静默穿透面）。
//   S1 真浏览器 DOM 断言：隔离台（lib_fix17 bootConsole，freePort 拒 3099=红线零接触；
//      teardownOnExit 全终态回收）+ playwright-core + chromium，任一缺席=ENV_FAIL exit 2
//      点名。数据只在 API 边界打桩（page.route，自带 /wf/projects 桩——项目组渲染不依赖
//      台面真实注册表，组/行/序全确定）；绝不碰生产 3099/真票。
// 三态（t260904-12）：stdout 末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
// env_fail>0=exit 2。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
// 红的分层（TDD 信号质量）：S0 bundle-anchors/①②③④ 在实现落地前红（新行为面）；
// precheck/rows-landed/⑤行1 标题/⑥行唯一性/⑦卫生子用例不依赖新行为（现状即应绿）——
// 若后者也红，红因在夹具/台面而非本票实现，先查场景自身。
//
// intent 分界：与 t260915-19-sidebar-inspection-ui 不同面——彼守左栏分拣制（项目组归位/
// 兜底组存在性/等你黄调/降级显式性）+反沉底烟测，本条守组内**合并排序口径全矩阵**
// （tier 边界+级内 updated_ts 倒序+兜底组同口径）与**徽标可辨**（命中/可见/文本/dev 行
// 零徽标对照），不复断彼任何一面；与 ticket-session-restore 的 browser 半不同面（彼守点行
// 不切会话；原 t260903-07-click-no-chat-switch 场景 261001 已删并收编于此）。排序纯函数真值表（状态×来源×畸形 ts/缺键/null 元素/未知状态缺省行）归
// developer L1 UT（server/plugins/workbench/tests/t260916-15-*）不同层，此处不重复。
// KI 对齐：KI-052（S0 twin bundle 同步=盘上客户端新鲜锚）、KI-055（真浏览器断言防台面绿
// 真机红）、KI-051（语义锚 data-testid/属性字面，不锚易漂移文案整句）。
//
// 夹具设计（对抗自检）：组内输入序=拼接序（dev 前、巡检后），与期望序刻意错排——若输入序
// 碰巧等于期望序，排序没实现断言也会绿（断言自我失效形态）。时间戳全用引擎单位=秒
// （base.py _now_epoch；消费点归一单点=toMillis），四行 ts 互异拉开 tier 与级内序两面。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
// 取台走 lib_fix17 bootConsole（t260915-19 实测定案）：非 docker 形态——本泳道
// worktree 直起 dsh 台（freePort 拒 3099=红线零接触；teardownOnExit 全终态回收），
// 台加载的 workbench=本 worktree lib bundle（buildProfile 指本仓插件目录）。
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t260916-15-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', '夹具甲', ['/tmp/fx-alpha'])
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

const PROJ_A = 'fixture-alpha'        // 在册项目甲（唯一项目组——本条只守组内序与徽标，多组分拣归 0915-19）
const DEV_A_RUN = 'devfixa1601run'    // 甲组 dev 在跑（tier1，ts 中）
const DEV_A_WAIT = 'devfixa1602wait'  // 甲组 dev 等你（tier0，ts 次新）
const INS_A_WAIT = 'inspfixa1603w'    // 甲组巡检等你（tier0，ts 最新=反沉底主角：必须压过在跑 dev 行）
const INS_A_DONE = 'inspfixa1604d'    // 甲组巡检已收口（tier2，ts 最老=按口径沉组底但仍须在场可见）
const INS_UN_WAIT = 'inspfixun605w'   // 兜底组巡检等你（ts 新）
const INS_UN_RUN = 'inspfixun606r'    // 兜底组巡检在跑（ts 老）

// 引擎单位=秒。T0<T2<T3<T4 拉开：级内倒序（T4>T3 同 tier0）与 tier 边界（T4 巡检压 T2 dev）各有一面。
const T0 = 1789350000
const T2 = 1789353600
const T3 = 1789357200
const T4 = 1789360800

const WORKFLOWS = [{
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'arbitrate', name: '仲裁', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
  ],
}]

function devRow(id, stageState, title, ts) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
  }
}

// 引擎巡检行形状（t260915-08 方案 R4 + t260915-20 行 project 字段=SA 直读）。
function insRow(over) {
  return {
    id: '', kind: 'inspection', engine: 'inspection', project: '', epic: '',
    title: '', template: 'inspection-lite',
    instance_id: '', period: '20260916', stage: 'scan', stage_state: 'running',
    status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
    heartbeat: true, report_path: '', awaiting_gate: false, human_gate: null,
    blocked_reason: '', gate_error: '', created: T2, updated: '09-16 07:30',
    updated_ts: T2, paused: false, paused_phase: '', handoff_count: 0,
    pending_count: 0, worktree: '', workspace: null, role: null, proposal_id: '',
    workflow: '', close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
    ...over,
  }
}

// 组内输入序=拼接序（dev 先、巡检后），与期望序刻意错排——见文件头「夹具设计」。
const DEV_ROWS = [
  devRow(DEV_A_RUN, 'running', '甲组在跑 dev 票', T2),
  devRow(DEV_A_WAIT, 'awaiting-human', '甲组等你 dev 票', T3),
]
const INS_ROWS = [
  insRow({
    id: INS_A_WAIT, project: PROJ_A, instance_id: 'fixture-alpha',
    title: '巡检 fixture-alpha · 期 20260916',
    stage: 'close', stage_state: 'awaiting-human', awaiting_gate: true,
    findings: { high: 1, med: 0, low: 0, total: 1 },
    created: T4, updated_ts: T4,
    report_path: 'out/inspection/inspfixa1603w.json',
  }),
  insRow({
    id: INS_A_DONE, project: PROJ_A, instance_id: 'fixture-alpha',
    title: '巡检 fixture-alpha · 期 20260915',
    stage: 'close', stage_state: 'running', status: 'closed',
    findings: { high: 0, med: 1, low: 0, total: 1 },
    created: T0, updated_ts: T0, close_ts: T0,
    report_path: 'out/inspection/inspfixa1604d.json',
  }),
  insRow({
    id: INS_UN_RUN, project: '', instance_id: 'legacy-run',
    title: '巡检 legacy-run · 期 20260901',
    stage: 'scan', stage_state: 'running',
    findings: { high: 0, med: 0, low: 1, total: 1 },
    created: T0, updated_ts: T0,
    report_path: 'out/inspection/inspfixun606r.json',
  }),
  insRow({
    id: INS_UN_WAIT, project: '', instance_id: 'legacy-wait',
    title: '巡检 legacy-wait · 期 20260902',
    stage: 'report', stage_state: 'awaiting-human', awaiting_gate: true,
    findings: { high: 0, med: 0, low: 0, total: 0 },
    created: T4, updated_ts: T4,
    report_path: 'out/inspection/inspfixun605w.json',
  }),
]
// 期望序（口径：tier 升序→级内 updated_ts 倒序→输入序稳定兜底）：
const EXPECTED_A = [INS_A_WAIT, DEV_A_WAIT, DEV_A_RUN, INS_A_DONE]
const EXPECTED_UN = [INS_UN_WAIT, INS_UN_RUN]
const INSP_IDS = [INS_A_WAIT, INS_A_DONE, INS_UN_WAIT, INS_UN_RUN]
const DEV_IDS = [DEV_A_RUN, DEV_A_WAIT]

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild（KI-052）')
    return
  }
  // 锚=语义契约面（徽标类字面+属性字面，字符串字面过压缩器存活），不锚函数名（改名面）。
  const anchors = ['wb-card-kind', 'data-kind-badge']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 bundle-anchors', 'fail', `shipped bundle missing merged-sort/badge anchors: ${missing.join(', ')}（实现段未落地或未重建=预期红，KI-052）`)
  } else {
    record('S0 bundle-anchors', 'pass', 'twin bundles in sync, merged-sort/badge anchors present')
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

// 组内行序爬取（绑浅：组容器是无类名 div，认「祖先含组头」不绑实现类名——0915-19 ownerOf
// 同法）。fallback=false：proj=项目 key 走组 dot title；fallback=true：走兜底组头 data-testid。
async function groupIdsOf(page, proj, fallback) {
  return page.evaluate(([projKey, fallback]) => {
    let head = null
    if (fallback) head = document.querySelector('.wb-sb [data-testid="sidebar-inspection-head"]')
    else head = document.querySelector(`.wb-sb .wb-group-dot[title="${projKey}"]`)
    if (!head) return null
    let w = head.parentElement
    while (w && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
    if (!w) return null
    return [...w.querySelectorAll('.wb-card[data-ticket-id]')].map(e => e.getAttribute('data-ticket-id'))
  }, [proj, fallback])
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

    // 数据只在 API 边界打桩；inspection 载荷固定（降级子用例归 0915-19，本条不重复）。
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
              ],
              quarantined: [],
            },
          }),
        })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        const proj = url.searchParams.get('project') || ''
        const tickets = proj === PROJ_A ? DEV_ROWS : []
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets, workflows: WORKFLOWS } }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }) })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown ticket or sub-route' }) })
    })

    // precheck：自带 /wf/projects 桩 → 项目组必须真渲染（不依赖台面真实注册表）。
    const groupHeadA = page.locator(`.wb-sb .wb-group-dot[title="${PROJ_A}"]`).first()
    if (!(await waitFor(async () => (await groupHeadA.count()) > 0, 10000))) {
      record('S1 precheck', 'env_fail', `左栏项目组未渲染（stub /wf/projects 未被消费？台面=${BASE}）`)
      return
    }
    record('S1 precheck', 'pass', `左栏项目组渲染（${PROJ_A}）`)

    // 等全量行落组（4+2）：不候齐，①②子用例会跑在渲染前读到残缺序（时序假红）。
    const allLanded = await waitFor(async () => {
      const a = await groupIdsOf(page, PROJ_A, false)
      const u = await groupIdsOf(page, '', true)
      return Array.isArray(a) && a.length === 4 && Array.isArray(u) && u.length === 2
    }, 15000)
    if (!allLanded) {
      const a = await groupIdsOf(page, PROJ_A, false)
      const u = await groupIdsOf(page, '', true)
      record('S1 rows-landed', 'fail', `行未落齐：甲组=${JSON.stringify(a)} 兜底组=${JSON.stringify(u)}`)
      return
    }
    record('S1 rows-landed', 'pass', '甲组 4 行+兜底组 2 行已落组渲染')

    // ① 合并排序全矩阵：DOM 行序==口径期望序。一面同时钉：tier 边界（等你→在跑→已完成）、
    //    级内 updated_ts 倒序（T4 巡检>T3 dev 同 tier0）、反沉底核心（等你巡检行压在跑 dev 行
    //    之上=用户实报「恒沉底」的逆否）、已完成行沉组底但仍可见不丢失。
    const idsA = await groupIdsOf(page, PROJ_A, false)
    const orderOk = JSON.stringify(idsA) === JSON.stringify(EXPECTED_A)
    record('S1 merged-order-group', orderOk ? 'pass' : 'fail',
      orderOk ? `甲组行序==口径期望序：${idsA.join(' → ')}`
        : `甲组行序异常：actual=[${(idsA || []).join(', ')}] expected=[${EXPECTED_A.join(', ')}]`)

    // ② 兜底组同口径：unowned 两行（等你 ts 新+在跑 ts 老）序==[等你,在跑]——合并口径
    //    不分组，兜底组不吃拼接序（输入序刻意与其相反，见夹具）。
    const idsU = await groupIdsOf(page, '', true)
    const fbOk = JSON.stringify(idsU) === JSON.stringify(EXPECTED_UN)
    record('S1 merged-order-fallback', fbOk ? 'pass' : 'fail',
      fbOk ? `兜底组行序==口径期望序：${idsU.join(' → ')}`
        : `兜底组行序异常：actual=[${(idsU || []).join(', ')}] expected=[${EXPECTED_UN.join(', ')}]`)

    // ③ 徽标可辨：巡检行卡内 [data-kind-badge] 恰一、可见（非 display:none）、文本=巡检。
    const badge = await page.evaluate((ids) => ids.map((id) => {
      const card = document.querySelector(`.wb-sb .wb-card[data-ticket-id="${id}"]`)
      if (!card) return { id, present: false, why: 'card-absent' }
      const b = card.querySelector('[data-kind-badge]')
      if (!b) return { id, present: false, why: 'badge-absent' }
      const hidden = getComputedStyle(b).display === 'none'
      // 徽标文案=INSPECTION_ROW_BADGE（server/plugins/workbench/src/host/inspection-face.ts，
      // 宿主令 260925 界面英文化后取值 'Inspection'，迁移前旧值「巡检」）。
      return { id, present: !hidden, text: (b.textContent || '').trim(), why: hidden ? 'display-none' : (b.textContent || '').trim() !== 'Inspection' ? `text=${(b.textContent || '').trim()}` : '' }
    }), INSP_IDS)
    const badgeBad = badge.filter(b => !b.present || b.why)
    record('S1 badge-inspection', badgeBad.length ? 'fail' : 'pass',
      badgeBad.length ? `巡检行徽标面异常：${badgeBad.map(b => `${b.id}(${b.why})`).join('；')}`
        : `巡检行徽标全部在场可见文本=巡检（${INSP_IDS.join(',')}）`)

    // ④ dev 零徽标对照（左栏 dev 行渲染零变化反断言）：dev 行卡内徽标元素数=0；
    //    甲组徽标总数==组内巡检行数（徽标不外溢）。
    const devBadge = await page.evaluate((ids) => ids.map((id) => {
      const card = document.querySelector(`.wb-sb .wb-card[data-ticket-id="${id}"]`)
      return { id, n: card ? card.querySelectorAll('[data-kind-badge]').length : -1 }
    }), DEV_IDS)
    const groupABadges = await page.evaluate((proj) => {
      const dot = document.querySelector(`.wb-sb .wb-group-dot[title="${proj}"]`)
      if (!dot) return -1
      let w = dot.parentElement
      while (w && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
      return w ? w.querySelectorAll('[data-kind-badge]').length : -1
    }, PROJ_A)
    const devOk = devBadge.every(b => b.n === 0) && groupABadges === 2
    record('S1 badge-dev-control', devOk ? 'pass' : 'fail',
      devOk ? 'dev 行零徽标（渲染零变化），甲组徽标总数==巡检行数（2）'
        : `dev 对照面异常：${devBadge.map(b => `${b.id}=${b.n}`).join('；')}；甲组徽标总数=${groupABadges}`)

    // ⑤ 行1 标题原样：排序只动序不动内容——巡检等你行文本含引擎标题原串。
    const insCard = page.locator(`.wb-sb .wb-card[data-ticket-id="${INS_A_WAIT}"]`).first()
    const rowText = await insCard.innerText().catch(() => '')
    const titleOk = rowText.includes('巡检 fixture-alpha · 期 20260916')
    record('S1 row1-title-intact', titleOk ? 'pass' : 'fail',
      titleOk ? '行1 沿用引擎标题「巡检 <实例> · 期 <期号>」' : `行1 标题被波及：text=${rowText.replace(/\s+/g, ' ').slice(0, 120)}`)

    // ⑥ 行唯一性：排序不得丢行/重复键——组内 id 数==去重数==4。
    const uniqOk = Array.isArray(idsA) && idsA.length === 4 && new Set(idsA).size === 4
    record('S1 rows-unique', uniqOk ? 'pass' : 'fail',
      uniqOk ? '甲组 4 行无重复无丢失' : `行唯一性异常：${JSON.stringify(idsA)}`)

    // ⑦ 卫生子用例：全旅程零 pageerror。
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
// 260916 仲裁归因轮，0915-19 同款）。
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
