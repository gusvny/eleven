#!/usr/bin/env node
// t261005-09 场景 2：左栏重构用户旅程（品牌行 / 项目身份 / 工单行 / 会话区句柄）。
// （灰盒 L3 渲染层，browser-free 池；两层式，镜 t260916-15/sc_sidebar_merged_sort_ui.mjs。）
//
// 用户场景（epic console-ui UI-1，宿主令 261005）：人打开控制台，左栏是一处管理项目的
// 地方——顶行是品牌（不额外加高）；项目带自己的身份徽标与项目色；展开项目看到工单列表
// （含阶段英文标签、无排队号/无拖拽箭头=CL-2/CL-3 边界面：引擎面未下发排队字段就不造）；
// 项目内会话区每行带会话句柄短码，可发现「+ 新建会话」入口；executor 句柄只在有面标记时
// 出现（今日无该面，不得凭空渲染）。
//
// 两层：
//   S0 build-contract（纯 node）：shipped 双 bundle 同步（KI-052）+ 品牌/会话入口文案字面
//      在 shipped bundle（'Sandbar'、'projects'、'New session'——字符串字面过压缩器存活）。
//   S1 真浏览器 DOM：隔离台（lib_fix17 bootConsole，freePort 拒 3099；teardownOnExit
//      全终态回收）+ playwright-core + chromium，任一缺席=ENV_FAIL exit 2。数据只在 API
//      边界打桩（/wf/projects、/wf/tickets、/wf/inspection/tickets），账册经 localStorage
//      种子（LEDGER_KEY 公开字面量）——浏览器/bundle/React 全真，宿主 3099 零接触。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。实现段落地前红属预期
// （TDD 信号：S0 品牌锚/会话短码/品牌行子用例），arbitrate/merge 期必须绿；precheck/
// rows-landed 等现状面若也红=红因在夹具/台面，先查场景自身。
//
// intent 分界：会话短码模块契约/畸形输入归 t261005-09-session-handle-contract 与 developer
// L1（tests/session-handle.mjs）；巡检分拣制归 t260915-19、合并排序口径归 t260916-15（本条
// 巡检行只在场性回归守卫，不复断其任何一面）；排队语义归 CL-2/CL-3（本条只断「不造」）。
// KI 对齐：KI-052（双 bundle 同步）、KI-055（真浏览器断言防台面绿真机红）、KI-051（锚字面/
// 属性，不锚易漂移整句）、KI-036（playwright 缺席=ENV_FAIL）。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = process.cwd()
let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t261005-09-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', 'fixture-alpha', ['/tmp/fx-alpha'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  BASE = bench.base
  await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
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

// ---------------------------------------------------------------- 夹具（模块/数据面）

const PROJ_A = 'fixture-alpha'
const RUN_ID = 'devfixa0901run'    // 在跑（updated_ts 较老）
const WAIT_ID = 'devfixa0902wait'  // 等你（updated_ts 较新）
const INS_ID = 'inspfixa0903w'     // 巡检行（在场性回归守卫，归 0915-19 的面不复断）
const T2 = 1789353600
const T3 = 1789357200

// 会话区种子（LEDGER_KEY 公开字面量，session-ledger-store.ts）：两条项目内会话，
// 短码期望由 session-handle 模块现算（单源：渲染=模块，断言=同模块）。
const LEDGER_KEY = 'sandbar-workbench-opened-sessions-v1'
const SESS_A = { id: 'sess-3f9c2a7e-1111-4000-8000-000000000001', seq: 1, title: 'Plan session', project: PROJ_A, cwd: '', lastOpenedAt: T2 }
const SESS_B = { id: 'sess-77aa4b2e-2222-4000-8000-000000000002', seq: 2, title: 'Review session', project: PROJ_A, cwd: '', lastOpenedAt: T3 }
const LEDGER_SEED = JSON.stringify([SESS_A, SESS_B])

// ui-labels + ticket-list-model 现算期望标签（界面英文=前端映射表统一映射引擎既有英文标识，
// CLAUDE.md 规则 6；不锚具体哪个映射函数/词表=合法实现选择面，锚「有映射词、非自造词」）。
let stageLabelOf = null
try {
  const ul = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/client/ui-labels.ts')).href)
  const tlm = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/client/ticket-list-model.ts')).href)
  stageLabelOf = (row) => {
    const cands = []
    for (const fn of ['stateLabel', 'stageLabel', 'stageDisplayLabel', 'statusLabel']) {
      try {
        const v = ul[fn](row.stage_state ?? row.stage ?? row.status)
        if (typeof v === 'string' && v) cands.push(v)
      } catch { /* candidate unavailable */ }
    }
    // t261008-08：状态英文词已从左栏行退役（状态语义由彩点承载），STATE4_LABEL 不再
    // 作为阶段标签候选——只认 ui-labels 阶段映射词；无映射阶段的行不造标签（缺席合法，
    // 标题仍在即数据面未丢）。
    return cands
    return cands
  }
} catch { stageLabelOf = () => [] }

// session-handle 模块（pre-implement 缺席=相关子用例 FAIL 点名，不 env_fail——红因=实现未落地）。
let sessionHandle = null
try {
  const sh = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/shared/session-handle.ts')).href)
  sessionHandle = sh.sessionHandle
} catch { sessionHandle = null }

// project-color 现算项目色（UI-4/票② R7 色板真源）。
let projectColorOf = () => null
try {
  const pc = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/shared/project-color.ts')).href)
  projectColorOf = (k) => (pc.projectColor ?? pc.default?.projectColor)?.(k) ?? null
} catch { /* colour face optional in assertions */ }

const WORKFLOWS = [{
  id: 'dev-lane', name: 'dev lane', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: 'plan', role: 'developer', parts: ['agent'] },
    { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
    { id: 'arbitrate', name: 'arbitrate', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge', name: 'merge', role: 'integration', parts: ['human'] },
  ],
}]

function devRow(id, stageState, title, ts, over = {}) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: stageState,
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    ...over,
  }
}

// 输入序=刻意错排（等你行 updated_ts 更新却排后），配合 B4 不造序边界。
const DEV_ROWS = [
  devRow(RUN_ID, 'running', 'alpha running ticket', T2),
  devRow(WAIT_ID, 'awaiting-human', 'alpha waiting ticket', T3, { epic: 'sandbar' }),
]
const INS_ROWS = [{
  id: INS_ID, kind: 'inspection', engine: 'inspection', project: PROJ_A, epic: '',
  title: 'Inspection fixture-alpha · period 20261005', template: 'inspection-lite',
  instance_id: 'fixture-alpha', period: '20261005', stage: 'scan', stage_state: 'running',
  status: 'running', decision: '', findings: { high: 0, med: 0, low: 0, total: 0 },
  heartbeat: true, report_path: 'out/inspection/x.json', awaiting_gate: false, human_gate: null,
  blocked_reason: '', gate_error: '', created: T2, updated: '10-05 07:30',
  updated_ts: T2, paused: false, paused_phase: '', handoff_count: 0,
  pending_count: 0, worktree: '', workspace: null, role: null, proposal_id: '',
  workflow: '', close_ts: 0, authz_active: 0, exec_status: 'RUNNING',
}]

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
    record('S0 build-contract', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return
  }
  const missing = ['Sandbar', 'New session'].filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 bundle-anchors', 'fail', `shipped bundle missing left-column anchors: ${missing.join(', ')}（pre-implement red expected / KI-052）`)
  } else {
    record('S0 bundle-anchors', 'pass', 'twin bundles in sync, brand + new-session anchors present')
  }
}

// ---------------------------------------------------------------- S1 真浏览器

function consoleHealthy() {
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

// 项目组容器（绑浅：从项目名文本向上爬到含工单卡的祖先，不绑实现类名）。
async function groupContainer(page) {
  return page.evaluateHandle(() => {
    const sb = document.querySelector('.wb-sb') || document.body
    const head = [...sb.querySelectorAll('*')].find(el => el.children.length === 0
      && (el.textContent || '').trim() === 'fixture-alpha')
    let w = head
    while (w && w !== document.body && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
    return w && w !== document.body ? w : null
  })
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    // 账册种子在任何页面脚本之前落进 localStorage（侧栏挂载即读到）。
    await ctx.addInitScript(([key, val]) => { try { localStorage.setItem(key, val) } catch { /* fresh */ } },
      [LEDGER_KEY, LEDGER_SEED])
    const pageErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    await bench.goto(page, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    // 数据只在 API 边界打桩（不碰台面真实注册表/真票）。
    await page.route('**/sandbar-workbench/api/wf/**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      if (path === '/sandbar-workbench/api/wf/projects') {
        return route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { projects: [
            { key: PROJ_A, name: 'fixture-alpha', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
          ], quarantined: [] } }),
        })
      }
      if (path === '/sandbar-workbench/api/wf/tickets') {
        const proj = url.searchParams.get('project') || ''
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: proj === PROJ_A ? DEV_ROWS : [], workflows: WORKFLOWS } }) })
      }
      if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
        return route.fulfill({ contentType: 'application/json',
          body: JSON.stringify({ ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }) })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
    })

    // precheck：项目组真渲染（自带 /wf/projects 桩）。
    const group = await groupContainer(page)
    const groupLanded = await waitFor(async () => {
      const h = await groupContainer(page)
      return !!(await h.evaluate(e => !!e).catch(() => false))
    }, 12000)
    if (!groupLanded) {
      record('S1 precheck', 'env_fail', `项目组未渲染（stub /wf/projects 未被消费？台面=${BASE}）`)
      return
    }
    record('S1 precheck', 'pass', `左栏项目组渲染（${PROJ_A}）`)
    const g = await groupContainer(page)

    // B0 品牌第一行：'Sandbar' 字样 + 'N projects' 计数文案在场；行高 ≈26px（≤34，零额外加高
    // 的用户可感知面）；行内零按钮（fold/theme 两钮随票退役）。
    const brand = await page.evaluate(() => {
      const sb = document.querySelector('.wb-sb') || document.body
      // 品牌行=最内层匹配元素：不含工单卡（排除整列/组头误匹配）、文本含品牌与项目计数。
      const cands = [...sb.querySelectorAll('*')].filter(el =>
        !el.querySelector('.wb-card') && /sandbar/i.test(el.textContent || '') && /projects?/i.test(el.textContent || ''))
      const el = cands[cands.length - 1]
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { h: r.height, buttons: el.querySelectorAll('button').length, top: r.top }
    })
    const brandOk = !!brand && brand.h > 16 && brand.h <= 34 && brand.buttons === 0
    record('B0 brand-first-row', brandOk ? 'pass' : 'fail',
      brandOk ? `brand row h=${Math.round(brand.h)}px, buttons=0, 'Sandbar' + 'N projects' present`
        : `brand row contract violated: ${JSON.stringify(brand)}（pre-implement red expected）`)

    // B1 项目身份：组头带身份徽标（svg）；项目身份承载=徽标+名字（票 t261008-08，
    // mock v11 对齐）：项目块 3px 左色条已退役——左条改反断言（任何元素都不得再带
    // 项目色左边条），选中块的 6% color-mix 上漆仍算合法色面（只记录不判）。
    const expectedColor = projectColorOf(PROJ_A)
    const ident = await page.evaluate(([proj, hex]) => {
      const sb = document.querySelector('.wb-sb') || document.body
      const head = [...sb.querySelectorAll('*')].find(el => el.children.length === 0
        && (el.textContent || '').trim() === proj)
      if (!head) return { badge: -1, bar: false, dbg: 'head-absent' }
      let w = head
      while (w && w !== document.body && !w.querySelector('.wb-card[data-ticket-id]')) w = w.parentElement
      if (!w || w === document.body) return { badge: -1, bar: false, dbg: 'container-absent' }
      const badge = w.querySelectorAll('svg').length
      const rgbOf = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number)
      let bar = false
      let dbg = 'no-colour-face'
      if (hex) {
        const rgb = hex.replace('#', '').match(/../g).map(x => parseInt(x, 16))
        for (const el of [w, ...w.querySelectorAll('*')]) {
          const cs = getComputedStyle(el)
          const bl = rgbOf(cs.borderLeftColor)
          const bw = parseFloat(cs.borderLeftWidth) || 0
          if (bw >= 2 && bl[0] === rgb[0] && bl[1] === rgb[1] && bl[2] === rgb[2]) { bar = true; dbg = 'border-left'; break }
          const bg = rgbOf(cs.backgroundColor)
          const washish = cs.backgroundColor.includes('color-mix') || (bg[0] > 0 && Math.abs(bg[0] - rgb[0]) < 40 && Math.abs(bg[1] - rgb[1]) < 40 && Math.abs(bg[2] - rgb[2]) < 40 && bg[3] !== undefined)
          if (bg[3] > 0 && washish) { dbg = `wash(${cs.backgroundColor.slice(0, 60)})`; break }
        }
      } else { dbg = 'colour-module-unavailable' }
      return { badge, bar, dbg, block: getComputedStyle(w).borderLeftWidth + '/' + getComputedStyle(w).borderLeftColor + '/' + getComputedStyle(w).backgroundColor.slice(0, 40) }
    }, [PROJ_A, expectedColor])
    const identOk = ident.badge >= 1 && ident.bar !== true
    record('B1 project-identity', identOk ? 'pass' : 'fail',
      identOk ? `group head carries badge (svg×${ident.badge}), no project-colour left bar (${ident.dbg})`
        : `identity face violated: ${JSON.stringify(ident)} (expected colour ${expectedColor})`)

    // rows-landed：两 dev 行+巡检行都落组（不候齐则内容断言读残缺 DOM=时序假红）。
    const allLanded = await waitFor(async () => {
      const h = await groupContainer(page)
      if (!(await h.evaluate(e => !!e).catch(() => false))) return false
      return await h.evaluate((e, ids) => ids.every(id => e.querySelector(`.wb-card[data-ticket-id="${id}"]`)), [RUN_ID, WAIT_ID, INS_ID])
    }, 15000)
    if (!allLanded) {
      record('S1 rows-landed', 'fail', `行未落齐（含组头点击展开重试）：ids=${JSON.stringify([RUN_ID, WAIT_ID, INS_ID])}`)
      return
    }
    record('S1 rows-landed', 'pass', '2 dev 行+1 巡检行落组渲染')

    // B2 工单行两行式：行文本含标题（数据不译）+ 阶段英文标签（ui-labels 现算候选之一；
    // 不锚具体取哪个映射函数=合法实现选择面）。t261008-08：状态英文词已从左栏行退役
    // （状态语义由彩点承载），STATE4_LABEL 不再是候选；无映射阶段的行不造标签（缺席
    // 合法），标题仍须在（数据面未丢）。
    const labelRows = await page.evaluate((ids) => ids.map((id) => {
      const card = document.querySelector(`.wb-sb .wb-card[data-ticket-id="${id}"]`)
      return { id, text: card ? (card.innerText || '').replace(/\s+/g, ' ') : null }
    }), [RUN_ID, WAIT_ID])
    const b2bad = []
    for (const r of labelRows) {
      if (!r.text) { b2bad.push(`${r.id}(card-absent)`); continue }
      const devRow = DEV_ROWS.find(d => d.id === r.id)
      // 候选只钉行面显示的那个字段=stage（二行阶段小字）；stage_state 是另一维度
      // （旧实现靠状态词碰巧命中，t261008-08 拔词后必须钉真源）。
      const cands = stageLabelOf({ ...devRow, stage_state: undefined })
      const titleOk = !!devRow && r.text.includes(devRow.title)
      if (cands.length === 0) {
        if (!titleOk) b2bad.push(`${r.id}(unmapped stage but title missing)`)
        continue
      }
      const hit = cands.some(c => r.text.includes(c))
      if (!hit) b2bad.push(`${r.id}(no mapped label; candidates=${JSON.stringify(cands)}; text=${r.text.slice(0, 120)})`)
    }
    record('B2 ticket-stage-label', b2bad.length ? 'fail' : 'pass',
      b2bad.length ? b2bad.join('；') : 'both rows carry title + mapped English stage label')

    // B3 epic 名在场（sandbar 行带 epic:'sandbar'；落点/形态=实现面，本条只断数据到达用户）。
    const groupText = await (await groupContainer(page)).evaluate(e => (e.innerText || '').replace(/\s+/g, ' '))
    record('B3 epic-name-reachable', groupText.includes('sandbar') ? 'pass' : 'fail',
      groupText.includes('sandbar') ? "epic code 'sandbar' visible in the project group"
        : `epic name missing from group text: ${groupText.slice(0, 160)}`)

    // B4 CL 边界——不造排队：工单卡无 draggable、行文本无「数字+.」排队号前缀、无拖拽把手
    // 字符（⠿/≡/☰）；（DOM 排序口径归 t260916-15，本条不重复）。
    const queue = await page.evaluate((ids) => ids.map((id) => {
      const card = document.querySelector(`.wb-sb .wb-card[data-ticket-id="${id}"]`)
      if (!card) return { id, bad: 'absent' }
      if (card.getAttribute('draggable') === 'true' || card.closest('[draggable="true"]')) return { id, bad: 'draggable' }
      const t = (card.innerText || '')
      if (/^\s*\d+[.)]\s/m.test(t)) return { id, bad: 'queue-number' }
      if (/[⠿≡☰]/.test(t)) return { id, bad: 'drag-glyph' }
      return { id, bad: null }
    }), [RUN_ID, WAIT_ID])
    const qbad = queue.filter(q => q.bad)
    record('B4 no-queue-invention', qbad.length ? 'fail' : 'pass',
      qbad.length ? `queue/drag ordering invented locally: ${qbad.map(q => `${q.id}(${q.bad})`).join('；')}`
        : 'rows carry no queue numbers / drag handles (CL-2/CL-3 face not invented)')

    // B5 会话区句柄：种子账册两行渲染在组内，各以模块现算短码可辨（可见词面或可及名/tooltip），
    // 标题可经 tooltip/可及名到达；executor 字面零出现（今日无标记面，渲染 executor=凭空造数据）。
    const sess = await page.evaluate((titles) => {
      const sb = document.querySelector('.wb-sb') || document.body
      const text = (sb.innerText || '').replace(/\s+/g, ' ')
      const named = [...sb.querySelectorAll('[title], [aria-label]')]
        .map(el => `${el.getAttribute('title') || ''} ${el.getAttribute('aria-label') || ''}`).join(' ')
      return {
        text,
        exec: /\bexecutor\b/.test(text),
        titleReachable: titles.every(t => named.includes(t)),
        handlesInNamed: named,
      }
    }, [SESS_A.title, SESS_B.title])
    const codeA = sessionHandle ? sessionHandle(SESS_A.id, []) : null
    const codeB = sessionHandle ? sessionHandle(SESS_B.id, []) : null
    const codeOk = !!sessionHandle && !!codeA && !!codeB
      && sess.text.includes(codeA) && sess.text.includes(codeB)
    const sessBad = !codeOk ? `handle short codes not rendered as defined (module=${!!sessionHandle}, A=${codeA}, B=${codeB})`
      : !sess.titleReachable ? `session titles not reachable via tooltip/accessible name (text=${sess.text.slice(0, 120)})`
      : sess.exec ? 'executor literal rendered without a marking face (must not invent data)'
      : null
    record('B5 session-handles', sessBad ? 'fail' : 'pass',
      sessBad ?? `tabs distinguishable by derived short codes (${codeA}, ${codeB}); titles reachable via tooltip; no executor literal`)

    // B6 入口 1：组内「+ New session」控件在场可发现（可见文案或可及名/tooltip 含 new session），
    // 是可点 button 面；空组态=带字按钮形态（现实现两形态同锚 data-wb-psess-new）。
    const entrance = await page.evaluate(() => {
      const sb = document.querySelector('.wb-sb') || document.body
      const els = [...sb.querySelectorAll('button, [role="button"], a')]
        .filter(el => /new\b[\s\S]*session/i.test(`${el.textContent || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''}`))
      return els.length
    })
    record('B6 new-session-entrance', entrance >= 1 ? 'pass' : 'fail',
      entrance >= 1 ? `new-session entrance discoverable ×${entrance} (visible copy or accessible name)` : 'no new-session entrance in the left column')

    // B7 巡检行在场性回归守卫（分拣/排序口径归 t260915-19/-16，本条只防重构丢行）。
    const insPresent = await page.evaluate((id) => !!document.querySelector(`.wb-sb .wb-card[data-ticket-id="${id}"]`), INS_ID)
    record('B7 inspection-row-intact', insPresent ? 'pass' : 'fail',
      insPresent ? 'inspection row still rendered after restructure' : `inspection row lost: ${INS_ID}`)

    // B8 卫生：全旅程零 pageerror。
    record('S1 page-health', pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror ×${pageErrors.length}: ${pageErrors.slice(0, 3).join(' | ')}` : 'zero pageerror across the journey')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- 主流程

buildContract()
if (!(await consoleHealthy())) {
  record('S1 console', 'env_fail', `test console unreachable: ${BASE}`)
} else {
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 playwright', 'env_fail', 'playwright-core not resolvable (KI-036 family)')
  } else {
    const browser = await launchBrowser(pw)
    if (!browser) {
      record('S1 chromium', 'env_fail', 'chromium/chrome cannot start (headless environment)')
    } else {
      try {
        await runBrowser(pw, browser)
      } catch (e) {
        record('S1 run-browser', 'fail', `uncaught: ${String(e).slice(0, 300)}`)
      } finally {
        await browser.close().catch(() => {})
      }
    }
  }
}
summarize()
