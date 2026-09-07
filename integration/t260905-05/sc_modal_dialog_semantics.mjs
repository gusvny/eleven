// modal-dialog-semantics —— t260905-05 L2 组件契约：wb-modal 弹层族 dialog 语义.
//
// Intent (grey-box L2, user-perceivable): 本票 client 侧唯一行为变化 = 四类 wb-modal
// （审批推进 / 打回 / 派活指令 / 内容预览）补 role="dialog" + aria-modal="true" +
// aria-label。用户可感知承诺（对外契约，锚承诺不锚实现）：
//   (1) 可发现：弹层在场时，标准 dialog 语义通路 [role="dialog"] 能找到它——
//       全仓 6 个集成文件里的 dismissOverlays 类 helper 靠这条路工作，本票改动
//       就是把这条通路从「恒空 no-op」变成真实可用；
//   (2) 模态语义在册：aria-modal="true"；
//   (3) 可经语义通路关闭：点弹层内按钮，弹层消失。
// 与既有场景 intent 不同面（防 intent 级重复）：
//   - t260901-22 approve-modal-ui 钉「弹层出现 + 内容在册」（UI 在场面），
//     本场景钉「弹层以 dialog 语义暴露且可经语义通路关闭」（a11y 契约面）；
//   - t260903-04 bundle-sync 钉 src≡lib 构建卫生（特征词面），本场景产物腿钉
//     「服务产物内每处 wb-modal 皆带 role」（产物完备面），互不替代；
//   - multi-tab-coexistence 钉跨页签行为（族行为面）。
// 三态分级（gen0 实锤后定稿；本票仲裁补「假一致」一课）：页面发现不了 role 时先分清
// 「谁的锅」——
//   仓内 lib/client.js 无 role                          = 产品红 fail（TDD 验收门）；
//   仓内 lib 有 role 但台面服务产物无 role              = 环境红 env_fail（共享台客户端
//     资产供给滞后：常驻台挂载树/启动缓存落后于被测 worktree，KI-052 同族错窗在
//     测试台的形态；刷新台面后自动转绿，不假红）；
//   台面服务产物 wb-modal/role 覆盖与仓内一致而页面仍发现不了 = 产品红 fail（真契约破）；
//   【假一致实锤】「台面产物含 role:"dialog" 子串」≠「供给新鲜」：别的树重建过的
//     lib 天然带别的 role:"dialog"（灯箱等），子串探测曾把错树供给（共享台 /repo 挂着
//     别票的树）判成「一致」→ 页面腿被错归类成产品红。故供给判定必须【覆盖计数
//     对齐】（wb-modal 总数与带 role 数双双对齐仓内产物），不认子串。
// 实现段落地前「产品红」形态属预期（S0 build-contract 先例）；arbitrate/merge 期必须绿。
//
// 台面：共享隔离台（lib_stage_console 供给，绝不触 3099 生产台）+ 每页 API 桩
// （/sandbar-workbench/api/wf/tickets* 供夹具、写操作只落桩内计数，零真写；其余
// 路由透传真台）。执行契约（t260904-12 三态）：SUMMARY 末行 + 退出码 0/1/2，
// （三态=闸内无跳过态的现行定稿，旧跳过语义退役）；本场景无 N/A 腿（夹具恒提供 awaiting-human 票，弹层必可达）。

import {
  BASE,
  refuseProductionConsole,
  consoleHealthy,
  loadPlaywright,
  openTestPage,
  makeResults,
} from '../t260904-05/lib_browser.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const FID = 'it05c' // 夹具票 id（alnum；绝不真票）
const LIB_JS = join(REPO, 'server', 'dsh', 'workbench', 'lib', 'client.js')
// L4 探测资产=页面实际执行的 workbench 插件客户端（t260905-05 implement 实锤：
// dsh 壳层聚合包 dsh-client-modules/client.js 不含 workbench 弹层代码（wb-modal=0），
// 弹层真源是按 rev 懒加载的 /plugins/sandbar-workbench/client.js——探错资产会把
// 全新台面也误判成供给滞后）。
const SERVED_CLIENT = '/plugins/sandbar-workbench/client.js'

const results = makeResults()

/** 泳道/worktree 兜底（同 sc_multi_tab_coexistence mainRepoRoot 先例）：worktree 不带
 *  node_modules，lib_browser 三路探测（泳道 ui-check 软链，KI-036 supply 面）可能全空；
 *  经 worktree gitfile 解析主检出，直取主树 playwright-core。解析不到=null=ENV_FAIL。 */
async function loadPlaywrightRobust() {
  const pw = await loadPlaywright()
  if (pw) return pw
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (!common) return null
    const main = resolve(REPO, common, '..')
    for (const sub of ['server/dsh/ui-check/node_modules/playwright-core/index.mjs',
      'server/dsh/workbench/node_modules/playwright-core/index.mjs']) {
      const p = join(main, sub)
      if (existsSync(p)) {
        try { return await import(pathToFileURL(p).href) } catch { /* next */ }
      }
    }
  } catch { /* not a worktree */ }
  return null
}

// ------------------------------------------------------------- 产物面探测

/** 仓内产物（被测真源）的 wb-modal/role 覆盖计数。压缩容忍：JSX 在产物里是对象
 *  字面量（实测 className: "wb-modal"，空格/引号风格随压缩器漂移一律放宽容忍）；
 *  covered 在匹配点向后 160 字符窗内找 role:"dialog"（属性序邻接不假设）。
 *  gen0 实锤：按源码 JSX 形态数=minified 全漏。 */
function repoBundleCoverage() {
  let js = null
  try { js = readFileSync(LIB_JS, 'utf8') } catch { return null }
  const siteRe = /className\s*[:=]\s*["']wb-modal["']/g
  const roleRe = /role\s*[:=]\s*["']dialog["']/
  let total = 0, covered = 0
  for (const m of js.matchAll(siteRe)) {
    total++
    if (roleRe.test(js.slice(m.index, m.index + 160))) covered++
  }
  return { total, covered }
}

/** 台面实际在服务的 client 产物的 wb-modal/role 覆盖计数（HTTP 直取，不经浏览器）。
 *  与仓内产物做【覆盖计数对齐】而非「含 role:dialog 子串」——错树供给的 lib 天然
 *  带别的 role:"dialog"（灯箱等），子串探测产生假一致（实锤见头注）。
 *  null=探测失败（台可达性已由 L0 保证，此态 practically 不可达；保守当未知处理）。 */
async function servedBundleCoverage() {
  try {
    const r = await fetch(`${BASE}${SERVED_CLIENT}`, { signal: AbortSignal.timeout(8000) })
    if (!r.ok) return null
    const js = await r.text()
    const siteRe = /className\s*[:=]\s*["']wb-modal["']/g
    const roleRe = /role\s*[:=]\s*["']dialog["']/
    let total = 0, covered = 0
    for (const m of js.matchAll(siteRe)) {
      total++
      if (roleRe.test(js.slice(m.index, m.index + 160))) covered++
    }
    return { total, covered }
  } catch { return null }
}

const SUPPLY_STALE_SHORT = '——台面客户端资产供给滞后/错树（常驻共享台 /repo 挂载的不是被测树或缓存落后，KI-052 同族错窗测试台形态）；lib_stage_console 复用前已核对挂载源并自愈重建，重跑本场景应转绿'

// ------------------------------------------------------------- 夹具与 API 桩

// settled + awaiting-human => 行卡出「推进/打回」两写键（同 multi-tab 基线夹具口径）。
const row = {
  id: FID, role: 'developer', status: 'settled', title: 'modal 语义打桩票',
  workflow: 'dev-lane', stage: 'merge', stage_state: 'awaiting-human',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
}
const detail = {
  id: FID, title: row.title, workflow_id: 'dev-lane', epic: '',
  status: 'settled', role: 'developer', lane: 'worktree',
  stage: 'merge', stage_state: 'awaiting-human', stage_name: '合并',
  acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
  pending: [], log: [], body: 'modal fixture body', write_set: [],
  timeline: [], updated: '—', updated_ts: 0,
}

/** 页级 API 桩（夹具形态同 sc_multi_tab_coexistence 基线，共享前置步骤）：列表/详情
 *  供夹具；POST /tickets/:id/:op 记写数并回 ok（写只落桩内，零真写）；其余透传真台。 */
async function attachStub(page, counts) {
  await page.route('**/sandbar-workbench/api/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const m = /^\/sandbar-workbench\/api\/wf\/tickets(?:\/([^/]+)(?:\/([^/]+)))?$/.exec(url.pathname)
    const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })
    if (!m) {
      try {
        const resp = await route.fetch()
        await route.fulfill({ response: resp })
      } catch {
        await route.fulfill({ status: 502, contentType: 'application/json', body: '{"ok":false,"error":"fixture passthrough failed"}' })
      }
      return
    }
    const [, id, sub] = m
    if (!id && req.method() === 'GET') return body({ ok: true, result: { tickets: [row], workflows: [{ id: 'dev-lane', name: '开发泳道', lane: 'worktree', stages: [{ id: 'merge', name: '合并', role: 'integration', parts: ['human'] }] }] } })
    if (id && !sub && req.method() === 'GET') return body({ ok: true, result: detail })
    if (id && sub && req.method() === 'POST') { counts.write++; return body({ ok: true, result: { ...detail, body: detail.body + ' written', updated: '刚刚', updated_ts: Date.now() } }) }
    return body({ ok: false, error: 'fixture stub: unsupported' })
  })
}

// ------------------------------------------------------------- 共享驱动

function mainCard(page) {
  // 行卡契约锚（t260904-17 已落 boardCard 契约）：[data-ticket-id][data-compact="false"]
  // ——显式排除侧栏迷你卡（同票两侧并存共用 id，17 号场景书面钉明的陷阱）。
  return page.locator(`[data-ticket-id="${FID}"][data-compact="false"]`)
}

async function openBoard(page) {
  const icon = page.locator('span.wb-view-icon[title="工单列表"]').first()
  let there = false
  for (let i = 0; i < 40; i++) {
    if (await icon.count()) { there = true; break }
    await page.waitForTimeout(250)
  }
  if (!there) return false
  await icon.click()
  // 行卡在场（桩列表被真台面消费），15s 上限。
  for (let i = 0; i < 60; i++) {
    if (await mainCard(page).count()) return true
    await page.waitForTimeout(250)
  }
  return false
}

/** dialog 语义三断言（发现 / aria-modal / 可关闭），报错精确到「哪个检查失败」。
 *  返回 null=全过；否则返回人话错误（分类归调用方）。 */
async function assertDialogSemantics(page, { bindText, closeByText }) {
  // (1) 可发现：等待可见 [role="dialog"]（bindText 用于在多弹层可能并存时钉住目标）。
  const probe = bindText
    ? page.locator('[role="dialog"]', { hasText: bindText }).first()
    : page.locator('[role="dialog"]').first()
  let showed = false
  for (let i = 0; i < 32; i++) {
    if (await probe.count()) { showed = true; break }
    await page.waitForTimeout(250)
  }
  if (!showed) {
    const anyModal = await page.locator('.wb-modal').count()
    return anyModal
      ? `弹层已出现但 [role="dialog"] 发现不了（role="dialog" 缺失）`
      : `点击驱动后弹层未出现（驱动路径或夹具态变化，先查可达性）`
  }
  // (2) aria-modal 语义在册。
  const ariaModal = await probe.getAttribute('aria-modal')
  if (ariaModal !== 'true') return `弹层可发现但 aria-modal=${JSON.stringify(ariaModal)}（期望 "true"）`
  // (3) 可经语义通路关闭：点弹层内按钮 → 弹层消失。native confirm 全程自动 accept。
  const btn = closeByText
    ? probe.locator('button:enabled', { hasText: closeByText }).first()
    : probe.locator('button:enabled').first()
  if (!(await btn.count())) {
    const anyBtn = await probe.locator('button:enabled').count()
    if (!anyBtn) return `弹层内无可用按钮，语义通路无法关闭`
    await probe.locator('button:enabled').first().click()
  } else {
    await btn.click()
  }
  let closed = false
  for (let i = 0; i < 32; i++) {
    if (!(await page.locator('[role="dialog"]').count())) { closed = true; break }
    await page.waitForTimeout(250)
  }
  if (!closed) return `点击后弹层 8s 未消失（[role="dialog"] 仍在）——关闭通路断`
  return null
}

// ------------------------------------------------------------- main

async function main() {
  refuseProductionConsole()

  if (!(await consoleHealthy())) {
    results.record('L0 precheck', 'env_fail', `test console unreachable at ${BASE}`)
    return results.summarize()
  }
  const pw = await loadPlaywrightRobust()
  if (!pw) {
    results.record('L0 precheck', 'env_fail', 'playwright-core not resolvable')
    return results.summarize()
  }

  // 产物面先判（决定页面腿红的三态归类）：
  //   repoBundle=仓内被测真源；served=台面实际服务产物的 wb-modal/role 覆盖计数。
  //   供给新鲜 = served 覆盖计数与仓内产物双双对齐（不认子串，见头注「假一致实锤」）。
  const bundle = repoBundleCoverage()
  const repoHasRole = !!bundle && bundle.total > 0 && bundle.covered === bundle.total
  const served = await servedBundleCoverage()
  const servedFresh = !!bundle && !!served &&
    served.total === bundle.total && served.covered === bundle.covered
  // 页面腿归因：仓内真源齐而台面供给不对齐/探测不到 = 环境红（供给面）；
  //   供给对齐而页面仍发现不了 = 产品红（真契约破）。报错精确到「哪个检查失败」。
  const classifyPageLeg = () =>
    (repoHasRole && !servedFresh) ? 'env_fail' : 'fail'
  const supplyHint = () => served === null
    ? `——台面服务产物探测失败（${BASE}${SERVED_CLIENT} 不可达/非 2xx）：台面挂载空壳或资产缺失${SUPPLY_STALE_SHORT}`
    : `——served wb-modal ${served.total} 处/${served.covered} 处带 role vs 仓内 ${bundle ? `${bundle.total} 处/${bundle.covered} 处` : '不可读'}${SUPPLY_STALE_SHORT}`

  const consoleErrors = []
  const counts = { write: 0 }
  const opened = await openTestPage(pw, { results, tag: 'L0', consoleErrors })
  if (!opened) return results.summarize()
  const { browser, page } = opened
  // native confirm/dialog 全程自动 accept（守门 confirm 可能跟在审批确认之后）。
  page.on('dialog', (dlg) => { void dlg.accept() })

  try {
    await attachStub(page, counts)

    // L0 precheck：台面行卡消费桩列表（环境不备=env_fail，不假红）。
    if (!(await openBoard(page))) {
      results.record('L0 precheck', 'env_fail', `board did not render fixture rowcard on ${BASE}`)
      return results.summarize()
    }
    results.record('L0 precheck', 'pass', '行卡消费桩列表（t260904-17 契约锚）')

    // L1 审批弹层：行卡「推进」→ 审批通过并推进弹层 → dialog 语义三断言。
    // 关闭钮按「确认/通过」语义找（按钮文案演化不破驱动；断言只落关闭行为本身）。
    await mainCard(page).locator('button', { hasText: '推进' }).first().click({ timeout: 5000 })
    const e1 = await assertDialogSemantics(page, { bindText: FID, closeByText: /确认|通过/ })
    if (!e1) {
      results.record('L1 approve-modal dialog semantics', 'pass', '发现 + aria-modal + 语义通路关闭 三断言全过')
    } else {
      const cls = classifyPageLeg()
      results.record('L1 approve-modal dialog semantics', cls, e1 + (cls === 'env_fail' ? supplyHint() : ''))
    }

    // L2 打回弹层：重载换干净态 → 行卡「打回」→ 打回弹层 → 同一套三断言。
    await page.reload({ waitUntil: 'domcontentloaded' })
    await attachStub(page, counts)
    page.on('dialog', (dlg) => { void dlg.accept() })
    if (!(await openBoard(page))) {
      results.record('L2 reject-modal dialog semantics', 'env_fail', 'reload 后行卡未再现')
    } else {
      await mainCard(page).locator('button', { hasText: '打回' }).first().click({ timeout: 5000 })
      // 关闭钮按「取消/关闭」找（取消路径不落写，断言最纯）；找不到则退首个可用钮。
      const e2 = await assertDialogSemantics(page, { closeByText: /取消|关闭/ })
      if (!e2) {
        results.record('L2 reject-modal dialog semantics', 'pass', '发现 + aria-modal + 语义通路关闭 三断言全过')
      } else {
        const cls = classifyPageLeg()
        results.record('L2 reject-modal dialog semantics', cls, e2 + (cls === 'env_fail' ? supplyHint() : ''))
      }
    }

    // L3 仓内产物完备：盘上 lib/client.js（被测真源）内每处 wb-modal 容器都带
    // role="dialog"——审批/打回/派活/内容预览四面一个不漏。真源缺=产品红（TDD 门）。
    if (bundle === null) {
      results.record('L3 repo-bundle modal coverage', 'fail', `lib/client.js unreadable at ${LIB_JS}`)
    } else if (bundle.total === 0) {
      results.record('L3 repo-bundle modal coverage', 'fail', '仓内产物 wb-modal 容器数为 0（产物/源码形态漂移，先查真源）')
    } else if (bundle.covered !== bundle.total) {
      results.record('L3 repo-bundle modal coverage', 'fail', `仓内产物 ${bundle.total} 处 wb-modal 仅 ${bundle.covered} 处带 role="dialog"（漏补或 tsdown 未重建——重建遗漏即 KI-052 同族静默穿透）`)
    } else {
      results.record('L3 repo-bundle modal coverage', 'pass', `${bundle.total}/${bundle.total} 处 wb-modal 带 role="dialog"`)
    }

    // L4 台面供给一致性：served 覆盖计数与仓内产物对齐才算新鲜（不认子串——
    // 错树供给的 lib 天然带别的 role:"dialog"，假一致曾把页面腿错归产品红）。
    if (served === null) {
      results.record('L4 served-asset freshness', 'env_fail', `台面服务产物不可达/探测失败：${BASE}${SERVED_CLIENT}`)
    } else if (!servedFresh) {
      results.record('L4 served-asset freshness', 'env_fail',
        `${SERVED_CLIENT} wb-modal/role 覆盖与仓内产物不对齐（served ${served.total} 处仅 ${served.covered} 处带 role vs 仓内 ${bundle ? `${bundle.total}/${bundle.covered}` : '不可读'}）${supplyHint()}`)
    } else {
      results.record('L4 served-asset freshness', 'pass', `台面服务产物 wb-modal/role 覆盖与仓内产物一致（${served.total}/${served.covered}）`)
    }

    // L5 卫生：全程零 console.error / pageerror。
    if (consoleErrors.length === 0) {
      results.record('L5 zero console.error/pageerror', 'pass')
    } else {
      results.record('L5 zero console.error/pageerror', 'fail',
        `${consoleErrors.length} 条，首条=${String(consoleErrors[0]).slice(0, 160)}`)
    }
  } finally {
    await browser.close().catch(() => {})
  }
  results.summarize()
}

main().catch(e => { console.error(String(e)); results.record('main', 'fail', String(e).slice(0, 180)); results.summarize() })
