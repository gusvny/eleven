// sc_ki048_status_card_dom.mjs —— KI-048 详情人话状态卡 payload→pixel 契约（t260911-05，灰盒 L3）。
//
// Intent (black-box, user perspective): 合并被 main 脏工作区挡住而 blocked 的工单，
// 详情抽屉落一张「人话状态卡」（mock 260904 A 块四件：人话主文案＋挡事文件点名＋
// 下一步安排＋原始日志折叠）——用户在票面就能看到哪个文件、什么原因、接下来做什么，
// 不必去翻 worker log（验收 d/e）。数据契约 = detail.blocked_reason（既有横幅）+
// detail.blocked_detail{reason_code, files, next_action}（本票新增结构）。
//   - T1 blocked 脏工作区票：.wb-status-card 恰 1 个（红态），卡文本含人话主文案
//     核心（「非冲突」）、点名文件 chip（server/model-routes.yaml）、下一步
//     （retry_qc）、<details> 原始日志折叠在位且折叠摘要为英文固定元素（界面固定
//     元素英文口径——锚「无 CJK」不锚具体措辞）；blocked_reason 横幅同页可达（验收d）；
//   - T2 无 blocked 字段老票：整卡不渲染（老票零侵入），正文卡照旧，页面不崩；
//   - T3 畸形 blocked_detail（空对象、blocked_reason 无路径）：卡退化渲染不崩，
//     不凭空捏造文件点名（UI 不翻译它没拿到的信息）；
//   - T4 全旅程零 pageerror / console.error。
//
// 分层纪律（防 intent 级重复）：developer L1（workbench tests status-card 视图模型
// 用例，锁翻译纯函数/畸形输入降级）之下、t260904-06 spec-card-dom（spec 卡落位面）
// 与 t260904-17 行卡面（列表四态/看原因导航）intent 不同面——本场景只锁「blocked
// 明细 payload→像素」真渲染面。bundle 陈旧时以「卡不在 DOM」正确变红（用户看到的
// 就是旧台面），归因归 merge-checks bundle_pairs 闸与 t260903-04 bundle-sync。
//
// Two layers → 仅 S1：needs the ISOLATED test console (lib_stage_console),
// playwright-core resolvable, and a launchable chromium. Any missing -> ENV_FAIL
// (exit 2, reason on stdout, 注明 KI-036). Data is stubbed at the API boundary with
// page.route(): browser/console/shipped bundle/React render path all real; only
// GET /sandbar-workbench/api/wf/tickets[/<id>] intercepted. Never touches 3099.
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 或全部子用例 na -> exit 1;
// env_fail>0 -> exit 2. Precedent: t260904-06/sc_spec_card_dom.mjs.

import { ensureStageConsole } from '../lib_stage_console.mjs'
import { loadPlaywright as pwLoad, pwMissingDetail } from '../lib_pw_deps.mjs' // t261012-05: single-source probe;
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;

// fixture 票 id（纯字母数字，永不与真票相撞）
const FID_K = 't26091105k' // blocked：脏 main 挡收口（blocked_reason + blocked_detail 全量）
const FID_O = 't26091105o' // 老票：无 blocked 字段（零侵入面）
const FID_M = 't26091105m' // 畸形：blocked_detail 空对象 + blocked_reason 无路径（降级面）

const FILE = 'server/model-routes.yaml'
const REASON_K = 'merge 未收口（dirty/main_dirty）：合并收口被 main 工作区未提交改动挡住（git 本地改动保护，非冲突；主树现场未动）：将相撞：' + FILE
const NEXT_K = '在 main 提交或暂存（git stash）这些改动，或票面说明后发 retry_qc 重验；引擎不自动 stash/提交'
const RAW_ANCHOR = 'merge 未收口（dirty/main_dirty）'

function row(id, title) {
  return {
    id, role: 'developer', status: 'dispatched', title,
    workflow: 'dev-lane', stage: 'merge', stage_state: 'blocked',
    handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
  }
}
const ROWS = [row(FID_K, '状态卡打桩·脏main受阻'), row(FID_O, '状态卡打桩·老票'), row(FID_M, '状态卡打桩·明细畸形')]

const T = '2026-09-11T00:00:00'
const tle = (stage, state = 'running', reason = '') => ({ at: T, stage, state, reason })

/** Detail fixture 基座（形状对齐 TicketDetail；precedent=spec-card-dom detailBase）。 */
function detailBase(id, title, over) {
  return {
    id, title, workflow_id: 'dev-lane', epic: '',
    status: 'dispatched', role: 'developer', lane: 'worktree',
    stage: 'design_integration_tests', stage_state: 'running', stage_name: '设计集成测试',
    acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
    pending: [], log: [], body: 'DOM 级渲染打桩工单正文（原始需求占位，不进 Temporal）',
    write_set: [], timeline: [tle('create_plan'), tle('review_plan'), tle('implement')],
    ...over,
  }
}

const DETAIL_K = detailBase(FID_K, ROWS[0].title, {
  stage: 'merge', stage_name: '合并', stage_state: 'blocked',
  blocked_reason: REASON_K,
  // 真实链形状：结构化受阻面挂 meta（引擎 dev_lane 落 meta.blocked_detail，KI-024
  // meta 全文透传；blocked_reason 由 host 面单独透出供横幅）。
  meta: { blocked_detail: { reason_code: 'main_dirty', files: [FILE], next_action: NEXT_K } },
  timeline: [
    tle('implement'), tle('merge_check', 'running'),
    tle('merge_check', 'green', '4+1 项检查：分支有 commit=绿；工作区干净=绿；写集白名单=绿；verify_lane=绿；合并前脏检查=绿'),
    tle('merge', 'blocked', RAW_ANCHOR + '……'),
  ],
})
// 老票形态：blocked_reason / meta.blocked_detail 字段整个缺席（undefined）——零侵入对照。
const DETAIL_O = detailBase(FID_O, ROWS[1].title, { timeline: [tle('create_plan'), tle('review_plan')] })
// 畸形形态：结构化明细空对象（断链/缺字段），blocked_reason 本身不含任何路径 token
// ——卡可退化渲染（主文案+下一步），但绝不凭空捏造文件点名。
const DETAIL_M = detailBase(FID_M, ROWS[2].title, {
  stage: 'merge', stage_name: '合并', stage_state: 'blocked',
  blocked_reason: 'merge 未收口（failed/merge_fault）：合并执行故障（非冲突），人工处置后发 retry_qc 重验',
  meta: { blocked_detail: {} },
})
const DETAIL_BY_ID = { [FID_K]: DETAIL_K, [FID_O]: DETAIL_O, [FID_M]: DETAIL_M }

// ---------------------------------------------------------------- results / helpers

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`);
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length;
  const e = results.filter(r => r.status === 'env_fail').length;
  const n = results.filter(r => r.status === 'na').length;
  const f = results.filter(r => r.status === 'fail').length;
  const allNa = results.length > 0 && n === results.length;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
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

/** 状态卡全貌：null=卡不在 DOM。四件一次取齐。 */
const domCard = `(() => {
  const el = document.querySelector('.wb-status-card');
  if (!el) return null;
  const sum = el.querySelector('details summary');
  return {
    cls: el.className || '',
    text: el.textContent || '',
    fileChips: el.querySelectorAll('code').length,
    hasDetails: !!el.querySelector('details'),
    summaryText: (sum?.textContent || '').trim(),
    summaryCJK: /[\\u4e00-\\u9fff]/.test(sum?.textContent || ''),
  }
})()`
const domCardCount = `document.querySelectorAll('.wb-status-card').length`
const domBanner = `(() => { const b = document.querySelector('.wb-d2-blocked'); return b ? b.textContent : '' })()`
const domBodyPresent = `document.querySelector('.wb-d2-body') !== null`

async function snap(p) {
  try {
    const n = await p.evaluate(domCardCount)
    const card = await p.evaluate(domCard)
    return `cardCount=${n} card=${JSON.stringify(card)?.slice(0, 260)}`
  } catch { return '(snapshot unavailable)' }
}

/** 关抽屉→点指定 fixture 行→等抽屉渲染（precedent openDetail）。 */
async function openDetail(page, fid) {
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 3000 }).catch(() => {})
  const rowEl = page.locator('.wb-card[data-ticket-id]', { hasText: fid }).first()
  if (!(await waitFor(async () => (await rowEl.count()) > 0, 8000))) {
    throw new Error(`fixture row ${fid} not rendered (list stub not consumed?)`)
  }
  await rowEl.click()
  const ok = await waitFor(async () => (await page.locator('.wb-d2-steps').count()) > 0, 8000)
  if (!ok) throw new Error(`stepper not rendered after clicking ${fid}`)
}

// ---------------------------------------------------------------- S1 scenarios

async function scenarioBlockedCard(page) {
  await openDetail(page, FID_K)
  const count = await page.evaluate(domCardCount)
  if (count !== 1) return `expect exactly 1 .wb-status-card, got ${count}`
  const c = await page.evaluate(domCard)
  if (!c) return 'status card vanished between count and snapshot'
  // 红/黄两态属 mock 样式细节不锁类名（灰盒：绑定浅）；四件构成才是验收 e 契约。
  // 主文案必答「是不是冲突」（不冒充冲突=本票核心承诺）。t260915-05 翻译层词条表
  // 迁移：主文案从英文词条改中文人话词条（「不是冲突」）——锚语义（否认冲突）
  // 不锚语言，措辞族并存防回退。
  if (!/not a conflict|非冲突|不是冲突/i.test(c.text)) return `headline must deny conflict semantics (ticket ① core), text: ${JSON.stringify(c.text.slice(0, 200))}`
  if (!c.text.includes(FILE)) return `card must point-name the blocking file ${FILE}`
  if (!/retry[-_]qc/i.test(c.text)) return `card must carry the next-step (retry qc), text: ${JSON.stringify(c.text.slice(0, 220))}`
  if (!c.hasDetails) return 'raw log folding (<details>) missing — card not four-piece'
  // t260915-05：折叠 summary 固定文案随词条表迁移改中文（「原始引擎日志」）——
  // 原断言语义=「summary 是固定文案、不随引擎数据漂移」，改锚固定中文串＋
  // 不得泄漏引擎原文（RAW_ANCHOR 是 timeline 数据，出现在 summary=数据串进文案）。
  if (!c.summaryText.includes('Raw engine log')) return `folding summary must be the fixed copy (Raw engine log), got ${JSON.stringify(c.summaryText)}`
  if (c.summaryText.includes(RAW_ANCHOR)) return `folding summary leaked engine data (${RAW_ANCHOR})`
  const banner = await page.evaluate(domBanner)
  if (!banner.includes('非冲突')) return `blocked_reason banner must surface the reason on the ticket face (验收d), got ${JSON.stringify(banner.slice(0, 160))}`
  return null
}

async function scenarioLegacyTicket(page) {
  await openDetail(page, FID_O)
  const count = await page.evaluate(domCardCount)
  if (count !== 0) return `legacy ticket (no blocked fields) must render zero status cards, got ${count}`
  const body = await page.evaluate(domBodyPresent)
  if (!body) return 'legacy ticket lost its wb-d2-body card (status card disturbed old tickets)'
  return null
}

async function scenarioMalformedDetail(page) {
  await openDetail(page, FID_M)
  const count = await page.evaluate(domCardCount)
  if (count !== 1) return `degraded card must still render from blocked_reason alone (卡退化为无文件行), got ${count}`
  const c = await page.evaluate(domCard)
  if (!c) return 'status card vanished between count and snapshot'
  if (c.text.includes(FILE)) return `card invented a file point-name not present in payload (UI 不得翻译它没拿到的信息): ${JSON.stringify(c.text.slice(0, 200))}`
  if (!/retry[-_]qc/i.test(c.text)) return `degraded card lost the next-step, text: ${JSON.stringify(c.text.slice(0, 220))}`
  return null
}

// ---------------------------------------------------------------- browser run


// t261012-05: playwright-core resolution converges on integration/lib_pw_deps.mjs
// (single source: SANDBAR_PLAYWRIGHT_PATH -> legacy SANDBAR_PLAYWRIGHT_MODULE ->
// bare import -> this-tree ui-check -> main tree via git common-dir). The old
// inline copy dropped both env overrides, so the documented asset-injection
// path (KI-036 remedy) was dead here; the fact-naming miss detail now comes
// from pwMissingDetail() (names every probed candidate, no blame wording).
async function loadPlaywright() { return pwLoad() }

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

async function run() {
  const ctx = { browser: null, pw: null }
  try {
    ctx.pw = await loadPlaywright()
  } catch { /* treated as missing below */ }
  if (!ctx.pw) {
    record('S0 playwright', 'env_fail', pwMissingDetail())
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
  const page = await bctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(3000)
  await dismissOverlays(page)

  // API 边界桩：list/detail 带 fixture；子路由与未知 id 答 ok:false——fixture id
  // 永不触达 Temporal/真控制台。glob 尾必须 **：单 * 不跨 /，拦不到 tickets/<id>。
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

  // 经第一个项目组的 📋 打开工单板（workbench 需先有 projectKey 才渲染列表）。
  const boardIcon = page.locator('span.wb-view-icon[title="Tickets"]').first()
  if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) {
    record('S1 precheck', 'env_fail', `no project group 📋 found on ${BASE} (console not provisioned for board view)`)
    summarize()
  }
  await boardIcon.click()
  const rowOk = await waitFor(async () =>
    (await page.locator('.wb-card[data-ticket-id]', { hasText: FID_K }).count()) > 0, 10000)
  if (!rowOk) {
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

  await run1('T1 blocked ticket: four-piece status card + banner (验收d/e)', scenarioBlockedCard)
  await run1('T2 legacy ticket without blocked fields: zero disturbance', scenarioLegacyTicket)
  await run1('T3 malformed blocked_detail: degrade, never invent files', scenarioMalformedDetail)

  // UI 证据钩子（t260911-05 implement 段交付面，加法式、零断言影响）：
  // SANDBAR_KI048_SHOT=<dir> 时，重开 blocked fixture 抽屉存整页 PNG（工单台
  // 「UI 票交付证据须含改动前后截图」的机械产出面；缺省环境不落盘不报错）。
  if (process.env.SANDBAR_KI048_SHOT) {
    try {
      const { mkdirSync } = await import('node:fs')
      mkdirSync(process.env.SANDBAR_KI048_SHOT, { recursive: true })
      await openDetail(page, FID_K)
      await page.waitForTimeout(400)
      await page.screenshot({ path: `${process.env.SANDBAR_KI048_SHOT}/ki048-status-card-after.png`, fullPage: true })
      await openDetail(page, FID_O)
      await page.waitForTimeout(400)
      await page.screenshot({ path: `${process.env.SANDBAR_KI048_SHOT}/ki048-status-card-legacy-no-card.png`, fullPage: true })
      console.log(`[SHOT] saved to ${process.env.SANDBAR_KI048_SHOT}`)
    } catch (e) { console.log(`[SHOT] failed (non-fatal): ${String(e).slice(0, 140)}`) }
  }

  const hygiene = pageErrors.length === 0 && consoleErrors.length === 0
  record('T4 zero pageerror/console.error across journey', hygiene ? 'pass' : 'fail',
    hygiene ? '' : `pageErrors=${JSON.stringify(pageErrors)} consoleErrors=${JSON.stringify(consoleErrors)}`)

  await bctx.close()
  await browser.close()
  summarize()
}

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

run().catch(e => { console.error('FATAL', e); record('S1 run', 'fail', String(e).slice(0, 200)); summarize() })
