#!/usr/bin/env node
// sc_console_boot_no_plugin_banner.mjs —— t260916-26 场景③：真宿主装载本票两插件的
// 活体回归腿（灰盒 L3，browser-free 池，隔离台=本泳道 worktree 直起 dsh 台）。
//
// 用户故事（工单验收①④的生产版本半边）：升级期混版窗口里，同一份 knowledge/providers
// 装机包在生产版本（0.1.1-rc.2，本机 dsh 即该版本）上必须照常激活——用户打开控制台
// 不看到「Failed to load plugins / … did not activate」顶部报错，工单台壳与「模型」
// 视图照常可用。本台宿主=0.1.1-rc.2（conversationViews 服务在场），故本腿**实现前后
// 都应绿**（纯零回归守卫）；对修复的判别力由场景①（装机包注入契约）承担，两面合起来
// 才是验收①的全谱。0.1.5 stage 活体腿不可本地机械复现（本机无 0.1.5 宿主），归宿主
// stage 3199 走查（方案 S5）。
//
// 台面通道（t260915-19 实测定案的先例）：lib_fix17 bootConsole 骨架的泳道三插件覆盖
// 变体（lib_t260916_26_bench）——docker 供给台在本环境不可得（260916 实录），且
// lib_fix17 原样只把 workbench 覆盖到泳道树、knowledge/providers 会 realpath 回主树
// 旧产物（KI-052「盘上×别树」同族假绿）。本台随机高端口（拒 3099=红线零接触）、
// Temporal 钉死端口、票源走 FIX17 桩，四路径回收。
//
// 腿：
//   T0 防错树夹具自检（t260906-01 根除面）：台面 profile 三条覆盖链 realpath 全部落在
//      本泳道仓内——台加载的不是本票产物=本场景所有绿都作废；
//   T1 隔离台起台就绪（workbench API 200）；
//   T2 壳层渲染正向控制（夹具甲项目行在 DOM——先证台面真渲染了，再看 absence，防
//      KI-052「绿≠真查」的空转绿）；
//   T3 事故文案零残留：页面全程无 /Failed to load plugins/i 且无 /did not activate/i
//      （锚事故原文词，不锚横幅 DOM 类名=实现细节）；
//   T4 「模型路由」视图走查烟测（验收①「两页签可用」校准语义的 providers 半边；docs 半边
//      归 t260905-06/t260915-10 深锁不重复）：点夹具甲组「模型路由」图标（作用域锚
//      aria-label，复制 t260915-10 docsIconOf 同款）→ ProvidersSection 渲染出显式状态
//      （正常头「模 型」或 API 未挂载的显式错误框二取一——空白菜单/白屏才算红）。
//
// 三态（t260904-12）：末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
// env_fail>0=exit 2。dsh 缺席/起台失败/playwright 缺失=ENV_FAIL 点名（KI-036 家族）。
import { makeTicketStub, teardownOnExit, loadPlaywright, dismissNotice, makeResults, makeRegistryRoot, writeProjectEntry } from '../t260904-17/lib_fix17.mjs';
import { bootLaneConsole } from './lib_t260916_26_bench.mjs';
import path from 'node:path';

const { record, summarize } = makeResults();

const REDLINE_PORTS = new Set([3099, 7233, 8233]);
const BANNER_PATTERNS = [/Failed to load plugins/i, /did not activate/i];

// ---- T0/T1 隔离台（三插件覆盖泳道树）----
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t260916-26-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', '夹具甲', ['/tmp/fx-alpha'])
  bench = await bootLaneConsole(projectsRoot, makeTicketStub())
  teardownOnExit(bench.teardown)
} catch (e) {
  record('隔离台起台（本泳道三插件覆盖台）', 'env_fail',
    `bootConsole 失败：${String(e).slice(0, 220)}`)
  summarize()
}

// T0 防错树：台面覆盖链 realpath 必须落在本泳道仓内
const REPO = process.cwd()
for (const [pkg, real] of Object.entries(bench.laneAnchors)) {
  record(`T0 防错树：${pkg} 装载链指向本泳道仓`,
    real.startsWith(REPO), `realpath=${real}`)
}

// T1 就绪（waitReady 已在 boot 内通过=workbench API 200）
record('T1 隔离台就绪且不触红线端口',
  !REDLINE_PORTS.has(bench.port), `port=${bench.port}（3099/7233/8233 零接触）`)

// ---- 浏览器走查 ----
const pw = await loadPlaywright()
if (!pw) {
  record('T2-T4 浏览器走查', 'env_fail', 'playwright-core 不可用（KI-036 家族）')
  summarize()
}
const { chromium } = pw
// 启动形态（复制自 t260904-05/lib_browser.mjs launchBrowser 先例，漂移责任两侧头注）：
// 系统级 Chrome（channel:'chrome'，同 ui-check/capture.mjs）优先，缺再退bundled chromium。
const launchBrowser = async () => {
  try { return await chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await chromium.launch({ headless: true }) }
}
let browser
try {
  browser = await launchBrowser()
  const page = await browser.newPage()
  await page.goto(bench.base, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(5000) // 壳层首屏
  await dismissNotice(page)
  // dsh 首跑 API key 向导（本台无凭据时出现）——「Configure later」关掉，不挡走查。
  // 挂载时机随 bundle 加载速度漂移（t260916-26 merge 轮实锤：合并后 bundle 让向导
  // 晚于旧的一次性 count 检查窗挂载，遮罩 _mask_* 罩住整屏，T4 点击 actionability
  // 永久等待=超时假红）。改轮询等挂载→点击→确认遮罩退场再放行走查。
  const laterBtn = page.getByText('Configure later', { exact: true })
  try {
    await laterBtn.first().waitFor({ state: 'visible', timeout: 10000 })
    await laterBtn.first().click({ timeout: 5000 })
  } catch { /* 本台有凭据无向导=合法形态 */ }
  await page.waitForFunction(() => !document.querySelector('[class*="_mask_"]'),
    { timeout: 10000 }).catch(() => { /* 遮罩未退=让 T4 的 actionability 超时如实点名 */ })
  await page.waitForTimeout(1500)

  // T2 正向控制：壳层真渲染（夹具甲项目行可见——台面注册表种子=确定性锚）
  let shellVisible = false
  try {
    await page.getByText('夹具甲', { exact: true }).first().waitFor({ state: 'visible', timeout: 15000 })
    shellVisible = true
  } catch { /* 落到判定 */ }
  record('T2 壳层渲染正向控制（夹具甲项目行可见）', shellVisible,
    shellVisible ? '台面已渲染' : '等 15s 未见「夹具甲」——台面未渲染，absence 腿作废')

  if (shellVisible) {
    // T3 事故文案零残留
    const bodyText = await page.locator('body').innerText()
    const hits = BANNER_PATTERNS.filter((re) => re.test(bodyText)).map((re) => re.source)
    record('T3 事故文案零残留（无 Failed to load plugins / did not activate）',
      hits.length === 0, hits.length ? `命中：${hits.join(' , ')}` : '零命中')
  } else {
    record('T3 事故文案零残留（无 Failed to load plugins / did not activate）', 'fail',
      '壳层未渲染（T2 红），absence 判定不可信')
  }

  // T4 「模型路由」视图烟测（点夹具甲组「模型路由」图标，作用域锚复制自 t260915-10
  // docsIconOf 同款——全局 aria-label 序数会被组内 svg 错位，必须按组头收窄）：
  // 渲染出显式状态（正常头「模 型」或 API 未挂载显式错误框）即算可用，空白才算红
  try {
    const routesIcon = page.locator('.wb-group-head', { hasText: '夹具甲' })
      .locator('span[aria-label="模型路由"]')
    // 点击预算 20s（t260916-26 implement gen3 加固）：图标在 workbench 板面数据
    // 加载后才渲染，闸内并发 herd（concurrency=4）下 8s 预算两度超时（单跑同树
    // 两跑全绿=负载抖动非语义红，registry load-flake 家族同型）。预算不是断言
    // 语义：本腿锚的仍是「点击后 ProvidersSection 显式状态在 DOM」，正向控制
    // T2 的等待预算（15s）本就按负载口径给，此处对齐。
    await routesIcon.click({ timeout: 20000 })
    await page.waitForTimeout(1500)
    const txt = await page.locator('body').innerText()
    const okShape = txt.includes('模 型') || txt.includes('模型管理 API 未挂载')
    record('T4 「模型路由」视图渲染出显式状态（正常头或显式错误框，非空白）', okShape,
      okShape ? 'ProvidersSection 显式状态在 DOM' : '点击后未见「模 型」头亦未见显式错误框')
  } catch (e) {
    record('T4 「模型路由」视图渲染出显式状态（正常头或显式错误框，非空白）', 'fail',
      `导航/点击失败：${String(e).slice(0, 160)}`)
  }
} catch (e) {
  record('T2-T4 浏览器走查', 'env_fail', `浏览器通道失败：${String(e).slice(0, 200)}`)
} finally {
  if (browser) { try { await browser.close() } catch { /* 已闭 */ } }
}

summarize()
