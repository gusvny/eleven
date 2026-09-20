/**
 * integration/t260915-09/sc_epics_client_project_wire.mjs
 * —— 立项单视图跨项目取数走「客户端真路径」（t260915-09，KI-057 client 穿参收口）。
 *
 * 用户场景（宿主 260915 实报）：dengzhufpv 的界面立项单页显示的是 sandbar 引擎仓的
 * 10 张立项单。API 层实测正确（?project=dengzhufpv→1、?project=sandbar→10、无参→回落
 * 引擎仓），病灶=client bundle 的 epics 数据通道一律裸调（不带 ?project=）→ host 无参
 * 回落引擎仓 → 任何项目视角都显示 sandbar 立项单。t260907-11（KI-057）当年验收全在
 * 「进程内 apply+mock req/res」的 host 面，client bundle 的真实请求路径零场景维度——
 * 本条补上该维度：真浏览器真点击 + 请求面拦截，双断言缺一不可。
 *
 * 断言面（灰盒：只锚公开 UI 契约与 wire，不锚内部结构）：
 *   W1 跨项目对照旅程（工单验收①）：点 dengzhufpv 项目行立项单图标 → 列表=仅
 *      fpv-repo-split 单一；切 sandbar → 引擎仓全集；再切回 → 仍单一（切换重置=
 *      列表/轮询随项目重拉的用户可感知面）。
 *   W2 详情链：点首行进详情（Markdown 面+头部代号）。
 *   W3 状态写链：详情页改状态保存 → 「已保存」在场面 + 写落夹具项目根的字节在案
 *      （写路径真穿参：落点是 fpv 夹具根，不是引擎仓）。
 *   W4 请求面反空转（本票新维度）：旅程收集的全部 /sandbar-workbench/api/epics* 请求
 *      project 参数恒非空（零裸调）；状态写 POST 单点按相位点名断言 project=dengzhufpv；
 *      聚合轮询在详情态至少再打一拍（跨过 8s 轮询窗）。
 *   W5 http 前置子用例（host 契约自检，回落语义保留的负向证明）：无参=引擎仓（与
 *      ?project=sandbar 同根同集，性质断言不钉真实仓清单——仓库每票必变，钉清单必 rot）；
 *      ?project=dengzhufpv=恰一枚 fpv-repo-split。
 *   W6 console 卫生：全旅程零 pageerror。
 *
 * 差异化（intent 级不重复）：
 *   与 t260907-11 三场景（进程内 apply+mock req/res 的 host 解析契约）不同层——彼锁
 *   host 面、本条锁客户端 bundle 真请求路径（当年漏的正是这半）；与
 *   t260903-04-client-bundle-sync（盘上特征词卫生面）不同面；与 t260910-10 docs
 *   project anchor（文档视图组件）intent 不同面。
 *
 * 执行契约（三态，t260904-12：环境缺=ENV_FAIL exit 2 有声红，无干净放行出口）：
 *   playwright-core/浏览器/隔离台依赖缺失=ENV_FAIL exit 2 有声红，绝不静默降级
 *   （KI-036/046 家族）。红线：隔离台端口 freePort 分配，全程不触 3099/7233/3199；
 *   写足迹=场景私有临时夹具根（状态写只落 fpv 夹具文件），退出全终态回收。
 *   写路径安全闸：状态保存仅在详情头部=夹具代号时触发（夹具代号文件只在夹具根存在，
 *   回归态下裸调/错参 POST 恒 404）——测试自身在任何回归态都不产生真仓数据副作用。
 *   实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
 *
 * 直跑：node integration/t260915-09/sc_epics_client_project_wire.mjs
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  REPO_ROOT, tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults, api,
} from '../t260904-17/lib_fix17.mjs'

const { record, summarize } = makeResults()

const FPV_CODE = 'fpv-repo-split'
const FPV_KEY = 'dengzhufpv'
const SB_KEY = 'sandbar'

/** 夹具立项单：字段表格式对齐 host parseEpicMeta（标题行+「状态」「立项日期」行）。 */
const FPV_EPIC_MD = [
  '# 立项单：fpv-repo-split',
  '',
  '| 字段 | 值 |',
  '| --- | --- |',
  `| 代号 | \`${FPV_CODE}\` |`,
  '| 状态 | 已立项（执行中） |',
  '| 立项日期 | 2026-09-15 |',
  '',
  't260915-09 场景夹具立项单（跨项目对照+状态写落点；非真实需求文档）。',
  '',
].join('\n')

/* ---- 夹具：双项目注册表（fpv=自植一枚；sandbar=引擎仓真树，只读） ---- */
const fpvRoot = tmpRoot('t260915-09-fpv-')
await mkdir(join(fpvRoot, 'notes', 'epics'), { recursive: true })
await writeFile(join(fpvRoot, 'notes', 'epics', `${FPV_CODE}.md`), FPV_EPIC_MD)
const projectsRoot = makeRegistryRoot('t260915-09-reg-')
writeProjectEntry(projectsRoot, FPV_KEY, 'FPV 夹具项目', [fpvRoot])
writeProjectEntry(projectsRoot, SB_KEY, 'sandbar 引擎仓', [REPO_ROOT])
record('fixture/dual-project-registry', true, `fpv=${fpvRoot} sandbar=${REPO_ROOT}`)

/* ---- 隔离台自举（失败=环境红点名，不静默） ---- */
const stub = makeTicketStub()
stub.setCtrl({ workflows: [], tickets: [], show: {} })
let bench
try {
  bench = await bootConsole(projectsRoot, stub)
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`)
  summarize()
}
teardownOnExit(bench.teardown)
record('redline/ports', bench.port !== 3099 && bench.port !== 7233 && bench.port !== 3199,
  `port=${bench.port}（freePort 分配，禁区外）`)

/* ---- W5 http 前置子用例：host 契约自检（回落保留+按项目分流；host 本票零改动） ---- */
const EPICS = '/sandbar-workbench/api/epics'
const codesOf = (body) => (Array.isArray(body?.result?.epics) ? body.result.epics.map((e) => e.code) : null)
const fallback = await api(bench.base, 'GET', EPICS)
const fallbackCodes = codesOf(fallback.body)
record('http/fallback-repo-engine',
  fallback.body?.ok === true && Array.isArray(fallbackCodes) && fallbackCodes.length >= 1 && !fallbackCodes.includes(FPV_CODE),
  `无参回落引擎仓：${fallbackCodes?.length} 枚（不含夹具代号=回落根与夹具根互斥）`)
const sb = await api(bench.base, 'GET', `${EPICS}?project=${SB_KEY}`)
const sbCodes = codesOf(sb.body)
record('http/fallback-equals-sandbar-root',
  sb.body?.ok === true && Array.isArray(sbCodes)
    && sbCodes.length === fallbackCodes.length
    && [...sbCodes].sort().join() === [...(fallbackCodes ?? [])].sort().join(),
  `?project=${SB_KEY}=${sbCodes?.length} 枚 ≡ 无参回落同根同集（性质断言，不钉真实仓清单）`)
const fpv = await api(bench.base, 'GET', `${EPICS}?project=${FPV_KEY}`)
const fpvCodes = codesOf(fpv.body)
record('http/project-fpv-single',
  fpv.body?.ok === true && Array.isArray(fpvCodes) && fpvCodes.length === 1 && fpvCodes[0] === FPV_CODE,
  `?project=${FPV_KEY}=${JSON.stringify(fpvCodes)}（对照 API 实测，工单验收①对照面）`)

/* ---- 浏览器子用例 ---- */
const pw = await loadPlaywright()
if (!pw) {
  record('browser/playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器真路径子用例环境红，无干净放行出口')
  summarize()
}
let browser
try {
  browser = await pw.chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => pw.chromium.launch({ headless: true }))
  record('browser/launch', true, 'chrome 通道（不可用回落 playwright chromium）')
} catch (e) {
  record('browser/launch', 'env_fail', `浏览器可执行档缺失（npx playwright install 可解，KI-036 家族）：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`)
  summarize()
}

const pageErrors = []
const wire = [] // { path, project } —— 全旅程 /api/epics* 请求面收集
try {
  const page = await browser.newPage()
  page.on('pageerror', (e) => pageErrors.push(String(e?.message ?? e)))
  page.on('request', (req) => {
    try {
      const u = new URL(req.url())
      if (u.pathname.startsWith('/sandbar-workbench/api/epics')) {
        wire.push({ path: u.pathname, project: u.searchParams.get('project') })
      }
    } catch { /* 非本台 URL 忽略 */ }
  })
  await page.goto(bench.base, { waitUntil: 'domcontentloaded' })
  await page.locator('.wb-group-head').first().waitFor({ state: 'visible', timeout: 20000 })
  await dismissNotice(page)

  const rowCodes = () => page.locator('.wb-ep-table tbody tr .wb-ep-code').allInnerTexts()
  const clickEpicsIcon = async (groupName) => {
    const icon = page.locator('.wb-group-head', { hasText: groupName }).locator('[title="立项单"], [aria-label="立项单"]').first()
    await icon.waitFor({ state: 'visible', timeout: 8000 })
    await icon.click({ timeout: 4000 })
    await page.locator('.wb-ep-root').first().waitFor({ state: 'visible', timeout: 8000 })
  }

  /* W1a dengzhufpv 视角：列表=仅 fpv-repo-split 单一 */
  await clickEpicsIcon('FPV 夹具项目')
  const fpvOnly = await page.waitForFunction(
    () => {
      const codes = [...document.querySelectorAll('.wb-ep-table tbody tr .wb-ep-code')].map((e) => e.textContent)
      return codes.length === 1 && codes[0] === 'fpv-repo-split'
    }, null, { timeout: 10000 }).then(() => true).catch(() => false)
  record('walk/fpv-list-single', fpvOnly,
    `dengzhufpv 立项单列表=${JSON.stringify(await rowCodes().catch(() => null))}（期望恰一枚 ${FPV_CODE}；宿主实报的串台面在此现形）`)

  /* W1b 切 sandbar：引擎仓全集（切换重拉=列表 effect 随项目重取的用户可感知面） */
  await clickEpicsIcon('sandbar 引擎仓')
  const sbRefetched = await page.waitForFunction(
    (n) => {
      const codes = [...document.querySelectorAll('.wb-ep-table tbody tr .wb-ep-code')].map((e) => e.textContent)
      return codes.length === n && !codes.includes('fpv-repo-split')
    }, fallbackCodes.length, { timeout: 10000 }).then(() => true).catch(() => false)
  record('walk/sandbar-list-refetch', sbRefetched,
    `sandbar 列表=${(await rowCodes().catch(() => null))?.length} 枚 ≡ 引擎仓全集 ${fallbackCodes.length}（0=夹具面假空；仍 1=切项目未重拉=deps 缺口现形）`)

  /* W1c 再切回 dengzhufpv：仍单一（切换重置双向） */
  await clickEpicsIcon('FPV 夹具项目')
  const backSingle = await page.waitForFunction(
    () => {
      const codes = [...document.querySelectorAll('.wb-ep-table tbody tr .wb-ep-code')].map((e) => e.textContent)
      return codes.length === 1 && codes[0] === 'fpv-repo-split'
    }, null, { timeout: 10000 }).then(() => true).catch(() => false)
  record('walk/switch-back-reset', backSingle, '切回 dengzhufpv 列表恢复恰一枚（双向切换重置）')

  /* W2 详情链 */
  await page.locator('.wb-ep-table tbody tr').first().click({ timeout: 4000 })
  const headerCode = await page.locator('.wb-ep-head .wb-ep-code').first().innerText().catch(() => '')
  const detailOk = await page.locator('.wb-ep-md').waitFor({ state: 'visible', timeout: 10000 })
    .then(() => true).catch(() => false)
    && headerCode === FPV_CODE
  record('walk/detail-renders', detailOk, `详情面在场+头部代号=${headerCode}（期望 ${FPV_CODE}）`)

  /* W3/W4 写路径子用例（安全闸）：仅当详情头部=夹具代号才触发保存——夹具代号文件只在
   * 场景私有夹具根存在，任何回归态（裸调/错参）下 POST 都落 404，永不触真仓数据；
   * 头部非夹具代号=读路径已串台的回归态，写子用例条件豁免 na（三态契约：N/A 仅给系统
   * 状态条件子用例；场景仍由 W1 读子用例硬红，不产生「豁免出绿」）。 */
  let savedMsg = null
  if (headerCode === FPV_CODE) {
    await page.locator('[data-testid="epic-status-edit"]').selectOption('已完结')
    await page.locator('[data-testid="epic-status-save"]').click({ timeout: 4000 })
    savedMsg = await page.locator('.wb-ep-head .wb-ep-sub', { hasText: '已保存' })
      .waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false)
    // 成功横幅会被保存成功后的详情重拉即时复位（产品现状=瞬态），不锚瞬态——
    // 硬判据=无失败文案（失败路径横幅持久在场可辨）+文件字节+wire 参数三重结果锚。
    await page.waitForTimeout(1500)
    const errText = await page.locator('.wb-ep-head .wb-ep-sub', { hasText: /保存失败|保存请求异常/ })
      .first().innerText().catch(() => '')
    record('write/status-save-ok', errText === '',
      `保存未报错（横幅瞬态捕获=${savedMsg}，仅观察项；${errText ? `失败文案=${errText}` : '失败文案不在场=用户可感知面健康'}）`)
    const written = await readFile(join(fpvRoot, 'notes', 'epics', `${FPV_CODE}.md`), 'utf8')
      .then((t) => t.includes('| 状态 | 已完结')).catch(() => false)
    record('write/status-file-updated', written,
      `状态写落点=${join(fpvRoot, 'notes', 'epics', FPV_CODE)} 已含「已完结」（落夹具根=写真穿参；落引擎仓=串台写）`)
  } else {
    record('write/status-save-ok', 'na', `详情头部=${headerCode}≠${FPV_CODE}（读路径串台回归态）——写子用例条件豁免，防串台写触真仓数据；读子用例已硬红`)
    record('write/status-file-updated', 'na', '写子用例未触发（同上豁免原因）')
  }

  /* W4 轮询拍：详情态跨过 8s 轮询窗，聚合请求至少再打一拍（GET 面无写副作用，不设闸） */
  await page.waitForTimeout(9000)
  const ticketGets = wire.filter((w) => /\/tickets$/.test(w.path))
  record('wire/poll-tickets-refresh', ticketGets.length >= 2,
    `聚合请求收集 ${ticketGets.length} 次（首拉+至少一拍 8s 轮询；参数面归 zero-bare 子用例统一判）`)

  /* W4 状态写 POST 单点相位断言（点击发起、相位无歧义，可点名判 project 值；随安全闸豁免） */
  const statusPost = wire.find((w) => w.path.endsWith('/status'))
  record('wire/status-post-carries-project',
    headerCode !== FPV_CODE ? 'na' : (statusPost !== undefined && statusPost.project === FPV_KEY),
    headerCode !== FPV_CODE
      ? '写子用例未触发（安全闸豁免）'
      : `状态写 POST project=${statusPost?.project ?? '（无请求）'}（期望 ${FPV_KEY}）`)

  /* W4 请求面反空转：全部 /api/epics* 请求零裸调（本票病灶的正向判据） */
  const bare = wire.filter((w) => !w.project)
  record('wire/zero-bare-epics', wire.length >= 4 && bare.length === 0,
    `收集 /api/epics* 请求 ${wire.length} 条、裸调 ${bare.length} 条（0=client 全链穿参；收集面 ${wire.length}<4=断言咬不住，fail-closed）`)

  /* W6 console 卫生 */
  record('hygiene/zero-pageerror', pageErrors.length === 0,
    pageErrors.length ? `pageerror：${pageErrors.slice(0, 2).join(' | ').slice(0, 160)}` : '全旅程零 pageerror')
} finally {
  await browser.close().catch(() => {})
  bench.teardown()
}
summarize()
