// spec-card-dom —— t260904-06「工单详情显示执行规格卡（spec 透出·B 形态）」DOM 级渲染契约。
//
// Intent (black-box, user perspective): 宿主拍板 B 形态——有 spec 的工单在详情抽屉
// 正文卡正下方出「执行规格（spec）」蓝左条卡（默认展开+限高 260px 滚动+字数徽标），
// 无 spec 的老票零扰动。developer 的 L1（workbench tests/spec-card-ui.mjs）已锁
// 三产物字符串契约；本场景只补 L1 锁不住的「payload→像素」真渲染面（若 JSX 运行时
// 抛错/卡落错位/徽标算错/换行丢失/HTML 字符注入，只有真浏览器抓得住）：
//   - T1 有 spec 票：.wb-d2-spec 恰 1 个、data-v=B、紧跟 .wb-d2-body 之后（正文卡
//     正下方）、ttl 文本含「执行规格（spec）」、.cnt 徽标=spec.length+「 字」、
//     .txt 全文逐字保真（HTML 特殊字符以纯文本出现，零标签注入）、蓝左条 4px
//     #0969da、white-space pre-wrap；
//   - T2 无 spec 字段（老票）：卡整体不渲染，正文卡照旧，页面不崩；
//   - T3 超长 spec：限高 260px 可滚动（overflow-y auto，scrollHeight>clientHeight
//     且 clientHeight 收敛），全文仍在 DOM（badge 计全文长度）不撑爆抽屉；
//   - T4 全旅程零 pageerror / console.error。
//
// 分层纪律（防 intent 级重复）：本场景**无 S0 段**——bundle 字符串锁（wb-d2-spec
// 锚点/三产物同步）已是 spec-card-ui.mjs 的 intent，这里只做 S1。bundle 陈旧时
// S1 会以「卡不在 DOM」正确变红（用户看到的就是旧台面），归因由 merge-checks
// bundle_pairs 闸与 t260903-04 client-bundle-sync 负责，不在此重复。
//
// Two layers → 本场景仅 S1（真浏览器渲染级）：needs the ISOLATED test console
// (SUYOU_TEST_CONSOLE, default 127.0.0.1:3199), playwright-core resolvable, and a
// launchable chromium. Any missing -> clean SKIP (exit 0, reason on stdout, 注明
// KI-036——ui-check 依赖未随迁移恢复，恢复后自动生效). Data is stubbed at the API
// boundary with page.route(): the browser, console, shipped bundle and React
// render path are all real; only GET /suyou-workbench/api/wf/tickets[/<id>] is
// intercepted (fixture snapshots). Never touches production console (3099) nor
// real tickets.
//
// Execution contract: stdout last line `SUMMARY pass=<n> skip=<m> fail=<k>`;
// FAIL>0 -> exit 1; SKIP -> exit 0 with reason. Precedent: sc_lane_parallel_dom.mjs.

import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (process.env.SUYOU_TEST_CONSOLE ?? 'http://127.0.0.1:3199').replace(/\/$/, '')

// fixture 票 id（纯字母数字，永不与真票相撞）
const FID_A = 't26090406a' // 有 spec：多行 + HTML 特殊字符（转义/换行/徽标面）
const FID_B = 't26090406b' // 无 spec 字段：老票零扰动面
const FID_C = 't26090406c' // 超长 spec：限高滚动面

// ---------------------------------------------------------------- fixtures

const SPEC_A = [
  '票②=R7 项目色贯通 + R8 顶部行退役，一票交付。<b>加粗</b> & "引号" <script>alert(1)</script>',
  '范围（R8）：sidebar.tsx 移除 SessionTopEntry 挂载；session-entry.tsx 删编辑态。',
  '范围（R7）：projectColor(projectKey) 注入 CSS 变量——+ 钮边框/文字=项目色。',
  '测试面收口：smoke 删 pickSwitchTargets 组；集成退役 sc_session_top_entry.mjs。',
].join('\n')

const SPEC_C = Array.from({ length: 120 }, (_, i) =>
  `第 ${i + 1} 行：执行规格压测行——限高 260px 后必须滚动而非撑爆抽屉，badge 计全文长度。`,
).join('\n')

const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'] },
    { id: 'review_plan', name: '审方案', role: 'integration', parts: ['agent'] },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'] },
    { id: 'design_integration_tests', name: '设计集成测试', role: 'integration', parts: ['agent'] },
    { id: 'run_integration_tests', name: '跑集成测试', role: 'integration', parts: ['script'] },
    { id: 'arbitrate', name: '仲裁', role: 'integration', parts: ['agent', 'script'] },
    { id: 'acceptance_walkthrough', name: '验收走查', role: 'integration', parts: ['agent', 'script'] },
    { id: 'merge_check', name: '合并检查', role: 'integration', parts: ['script'] },
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
    { id: 'suggest_next', name: '建议下一单', role: 'integration', parts: ['script'] },
  ],
}

function row(id, title) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'design_integration_tests', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
  }
}
const ROWS = [row(FID_A, 'spec 卡渲染打桩·有规格'), row(FID_B, 'spec 卡渲染打桩·老票无规格'), row(FID_C, 'spec 卡渲染打桩·超长规格')]

const T = '2026-09-04T00:00:00'
const tle = (stage, state = 'running', reason = '') => ({ at: T, stage, state, reason })

/** Detail fixture 基座（形状对齐 TicketDetail；predecessor=lane-parallel-dom detailBase）。 */
function detailBase(id, title, over) {
  return {
    id, title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'design_integration_tests', stage_state: 'running', stage_name: '设计集成测试',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: 'DOM 级渲染打桩工单正文（原始需求占位，不进 Temporal）',
    write_set: [], timeline: [tle('create_plan'), tle('review_plan'), tle('implement'), tle('design_integration_tests')],
    ...over,
  }
}

const DETAIL_A = detailBase(FID_A, ROWS[0].title, { spec: SPEC_A })
// 老票形态：spec 字段整个缺席（undefined），不是空串——truthy 守卫两条路里更老的一条。
const DETAIL_B = detailBase(FID_B, ROWS[1].title, { timeline: [tle('create_plan'), tle('review_plan')] })
const DETAIL_C = detailBase(FID_C, ROWS[2].title, { spec: SPEC_C })
const DETAIL_BY_ID = { [FID_A]: DETAIL_A, [FID_B]: DETAIL_B, [FID_C]: DETAIL_C }

// ---------------------------------------------------------------- results / helpers

const results = []
function record(name, status, detail = '') {
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const s = results.filter(r => r.status === 'skip').length
  const f = results.filter(r => r.status === 'fail').length
  console.log(`SUMMARY pass=${p} skip=${s} fail=${f}`)
  process.exit(f > 0 ? 1 : 0)
}

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
}

function mainRepoRoot() {
  // node_modules 不随 worktree 走；经 gitfile 解析主检出目录找 playwright-core。
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
  for (const sub of ['server/dsh/ui-check/node_modules/playwright-core/index.mjs',
    'server/dsh/workbench/node_modules/playwright-core/index.mjs']) {
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

// ---------------------------------------------------------------- DOM snapshots（页内求值，一次一个表达式）

/** spec 卡全貌：null=卡不在 DOM。styles/几何/文本一次取齐。 */
const domSpecCard = `(() => {
  const el = document.querySelector('.wb-d2-spec');
  if (!el) return null;
  const cs = getComputedStyle(el);
  return {
    dataV: el.getAttribute('data-v'),
    prevCls: el.previousElementSibling ? el.previousElementSibling.className : '',
    ttl: (el.querySelector('.ttl')?.textContent || ''),
    cnt: (el.querySelector('.cnt')?.textContent || ''),
    txt: (el.querySelector('.txt')?.textContent || ''),
    injected: el.querySelectorAll('b,script,style,img,iframe').length,
    borderLeftWidth: cs.borderLeftWidth,
    borderLeftColor: cs.borderLeftColor,
    maxHeight: cs.maxHeight,
    overflowY: cs.overflowY,
    whiteSpace: cs.whiteSpace,
    clientH: el.clientHeight,
    scrollH: el.scrollHeight,
  };
})()`
const domSpecCount = `document.querySelectorAll('.wb-d2-spec').length`
const domBodyPresent = `document.querySelector('.wb-d2-body') !== null`

/** 失败现场快照（precedent snap()）：此刻页面上有什么。 */
async function snap(p) {
  try {
    const n = await p.evaluate(domSpecCount)
    const body = await p.evaluate(domBodyPresent)
    const card = await p.evaluate(domSpecCard)
    return `specCount=${n} body=${body} card=${JSON.stringify(card)?.slice(0, 220)}`
  } catch { return '(snapshot unavailable)' }
}

/** 关抽屉→点指定 fixture 行→等抽屉渲染（precedent openFixtureDetail 泛化到多票）。 */
async function openDetail(page, fid) {
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  const rowEl = page.locator('tr.wb-row', { hasText: fid }).first()
  if (!(await waitFor(async () => (await rowEl.count()) > 0, 8000))) {
    throw new Error(`fixture row ${fid} not rendered (list stub not consumed?)`)
  }
  await rowEl.click()
  const ok = await waitFor(async () => (await page.locator('.wb-d2-steps').count()) > 0, 8000)
  if (!ok) throw new Error(`stepper not rendered after clicking ${fid}`)
}

// ---------------------------------------------------------------- S1 scenarios

async function scenarioSpecCard(page) {
  await openDetail(page, FID_A)
  const count = await page.evaluate(domSpecCount)
  if (count !== 1) return `expect exactly 1 .wb-d2-spec, got ${count}`
  const c = await page.evaluate(domSpecCard)
  if (!c) return 'spec card vanished between count and snapshot'
  if (c.dataV !== 'B') return `data-v expected "B", got ${JSON.stringify(c.dataV)}`
  // 位置契约：正文卡正下方（钉顶区）——前一个兄弟恰为 wb-d2-body。
  if (!/\bwb-d2-body\b/.test(c.prevCls)) return `card must sit right below wb-d2-body, prev sibling class: ${JSON.stringify(c.prevCls)}`
  if (!c.ttl.includes('执行规格（spec）')) return `ttl missing 执行规格（spec）: ${JSON.stringify(c.ttl)}`
  if (c.cnt !== `${SPEC_A.length} 字`) return `badge expected "${SPEC_A.length} 字", got ${JSON.stringify(c.cnt)}`
  if (c.txt !== SPEC_A) return `.txt text not verbatim (len ${c.txt.length} vs ${SPEC_A.length}; newline/escape loss?)`
  if (c.injected !== 0) return `HTML special chars leaked as elements: ${c.injected} injected tags inside card`
  if (c.borderLeftWidth !== '4px') return `blue bar width expected 4px, got ${JSON.stringify(c.borderLeftWidth)}`
  if (!/rgb\(9,\s*105,\s*218\)/.test(c.borderLeftColor)) return `blue bar color expected #0969da=rgb(9,105,218), got ${JSON.stringify(c.borderLeftColor)}`
  if (c.whiteSpace !== 'pre-wrap') return `white-space expected pre-wrap, got ${JSON.stringify(c.whiteSpace)}`
  return null
}

async function scenarioLegacyTicket(page) {
  await openDetail(page, FID_B)
  const count = await page.evaluate(domSpecCount)
  if (count !== 0) return `legacy ticket (no spec field) must render zero spec cards, got ${count}`
  const body = await page.evaluate(domBodyPresent)
  if (!body) return 'legacy ticket lost its wb-d2-body card (spec change disturbed old tickets)'
  return null
}

async function scenarioOversized(page) {
  await openDetail(page, FID_C)
  const c = await page.evaluate(domSpecCard)
  if (!c) return 'spec card missing on oversized fixture'
  if (c.cnt !== `${SPEC_C.length} 字`) return `badge must count the full text (${SPEC_C.length}), got ${JSON.stringify(c.cnt)}`
  if (c.maxHeight !== '260px') return `max-height expected 260px, got ${JSON.stringify(c.maxHeight)}`
  if (c.overflowY !== 'auto') return `overflow-y expected auto, got ${JSON.stringify(c.overflowY)}`
  if (c.scrollH <= c.clientH) return `expected scrollable (scrollHeight ${c.scrollH} > clientHeight ${c.clientH})`
  // 收敛面：未限高时 clientH 会是数千 px；限高生效则收敛在 260px+padding 量级。
  if (c.clientH > 320) return `card not height-contained (clientHeight ${c.clientH} > 320) — drawer blown open`
  return null
}

// ---------------------------------------------------------------- browser run

async function runBrowser(browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const consoleErrors = []
    const page = await ctx.newPage()
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3000)
    await dismissOverlays(page)

    // API 边界桩：list/detail 带 fixture；子路由与未知 id 答 ok:false——fixture id
    // 永不触达 Temporal/真控制台。glob 尾必须 **：单 * 不跨 /，拦不到 tickets/<id>
    // （sc_lane_parallel_dom P1-P4 实测教训）。
    await page.route('**/suyou-workbench/api/wf/tickets**', (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace(/\/+$/, '')
      const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
      if (path === '/suyou-workbench/api/wf/tickets') {
        return body({ ok: true, result: { tickets: ROWS }, workflows: [WF] })
      }
      const m = /^\/suyou-workbench\/api\/wf\/tickets\/([^/]+)$/.exec(path)
      if (m && DETAIL_BY_ID[decodeURIComponent(m[1])]) {
        return body({ ok: true, result: DETAIL_BY_ID[decodeURIComponent(m[1])] })
      }
      return body({ ok: false, error: 'fixture stub: unknown ticket or sub-route' })
    })

    // 经第一个项目组的 📋 打开工单板（workbench 需先有 projectKey 才渲染列表）。
    const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
    if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
      record('S1 precheck', 'skip', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
      return
    }
    await boardIcon.click()
    const rowOk = await waitFor(async () =>
      (await page.locator('tr.wb-row', { hasText: FID_A }).count()) > 0, 10000)
    if (!rowOk) {
      record('S1 precheck', 'skip', `ticket board did not consume the list stub on ${BASE} (view needs live engine?)`)
      return
    }

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)} @ ${await snap(page)}`)
    const run = async (name, fn) => {
      try {
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    await run('T1 spec card contract (with spec)', scenarioSpecCard)
    await run('T2 legacy ticket without spec: zero disturbance', scenarioLegacyTicket)
    await run('T3 oversized spec: 260px scroll containment', scenarioOversized)

    const hygiene = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') +
      (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) {
      record('T4 zero pageerror/console.error', 'pass')
    } else {
      record('T4 zero pageerror/console.error', 'fail', hygiene)
    }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

async function main() {
  const [maj, min] = process.versions.node.split('.').map(Number)
  if (maj < 22 || (maj === 22 && min < 18)) {
    record('node', 'skip', `node ${process.versions.node} < 22.18`)
    return summarize()
  }

  if (BASE.includes(':3099')) {
    console.error('refusing to run: SUYOU_TEST_CONSOLE points at the production console (3099)')
    process.exit(1)
  }

  const healthy = await consoleHealthy()
  if (!healthy) {
    record('S1 precheck', 'skip', `test console unreachable at ${BASE} (docker compose -f server/dsh/docker-compose.test.yml up -d; KI-036 隔离台/playwright 依赖未恢复则干净 SKIP)`)
    return summarize()
  }
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 precheck', 'skip', 'playwright-core not resolvable (KI-036: ui-check 依赖未恢复；恢复后自动生效)')
    return summarize()
  }
  const browser = await launchBrowser(pw)
  if (!browser) {
    record('S1 precheck', 'skip', 'no browser could be launched')
    return summarize()
  }

  let exiting = false
  const shutdown = async (code) => {
    if (exiting) return
    exiting = true
    await browser.close().catch(() => {})
    process.exit(code)
  }
  process.on('SIGINT', () => { void shutdown(130) })
  process.on('SIGTERM', () => { void shutdown(143) })
  try {
    await runBrowser(browser)
  } finally {
    if (!exiting) await browser.close().catch(() => {})
  }
  summarize()
}

main().catch(e => { console.error(String(e)); summarize() })
