// metrics-donut-dom —— t260903-09「三 donut 白板」修复的 DOM 级黑盒基线。
//
// Intent (black-box, user perspective): 度量面板在**有数据**时，三张环形图——
// 「时间去哪了」（time 副1）、「有无代码变更票占比」（delivery 副2）、「模型份额」
// （token 副1）——必须真渲染（canvas 有非透明像素=非白板），且人审扇区独立橙色；
// 畸形数据走人话空态不崩。根因历史：renderSpec 缺 'donut' 分支，三张 donut spec
// 落 default no-op，init 后从不 setOption（白板）。
//
// 与 t03_donut_empty.mjs（integration/t260902-05）的 intent 边界：那边管「无数据
// 空态」，本场景管「有数据真渲染」——互补不重复。
//
// 对 sc_lane_parallel_dom.mjs 七项故障模式的取舍（create_plan gen1 R1 清单）：
// 全带——①3199 端口隔离（绝不碰 3099）②环境缺失=ENV_FAIL（exit 2） ③SUMMARY 末行契约
// ④pageerror/console.error 卫生断言（加码：畸形 donut 数据不得触发 echarts 抛错）
// ⑤stub 消费预检（面板确实发出了 metrics 请求，未消费即 env_fail 不假绿）⑥finally
// 兜底关浏览器 ⑦不碰真票（API 边界全 stub）。七项理由同源：生产台不可占用、
// 机器差异不假红、全族运行器口径一致、零异常卫生、不假绿、终态回收、零真数据。
//
// Two layers:
//   S0 build-contract (pure node, runs everywhere): twin bundles in sync +
//      donut 渲染锚点在产物中（donutOption/specToDonutInput/case 'donut'/
//      &mode=fast/缓存快照角标）+ 纯逻辑 smoke（specToDonutInput/donutOption）。
//   S1 browser DOM assertions (real rendering level): needs the ISOLATED test
//      console (SUYOU_TEST_CONSOLE, default 127.0.0.1:3199), playwright-core,
//      and a launchable chromium. Any missing -> ENV_FAIL (exit 2, reason on
//      stdout). Data stubbed at the API boundary with page.route(): metrics
//      双门（mode=fast 快照 stale → full 全量）由桩按 query 分流，DOM/React/
//      echarts 渲染路径全真。Never touches production console (3099) nor real
//      tickets.
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 或全腿 na -> exit 1;
// env_fail>0 -> exit 2（环境红：没验成，原因归环境）; all pass -> 0. Node >= 22.18.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;

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

// ---------------------------------------------------------------- fixtures

const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', exit: 'agent' },
    { id: 'review_plan', name: '审方案', role: 'integration', exit: 'human' },
    { id: 'implement', name: '实现', role: 'developer', exit: 'agent' },
  ],
}

const donutSpec = (title, cats, data) => ({ kind: 'donut', title, categories: cats, series: [{ name: '值', data }], drill: true })

/** 用户原话的三张 donut：CLI 实测数据俱在（[2786.5,4824.14]/[395267,293065]/[2,46]）。 */
const VIEW_BODY = {
  time: {
    kpis: { tickets: 48, closed: 10, avg_delivery_min: 126.1, tokens_total: 688332 },
    charts: {
      primary: { kind: 'bar', title: 'stage 时长合计（分钟）', categories: ['create_plan', 'review_plan', 'implement'], series: [{ name: '时长(min)', data: [100, 30, 200] }], drill: true },
      secondaries: [
        donutSpec('时间去哪了：人审等待 vs 机器', ['人审等待', '机器'], [2786.5, 4824.14]),
        { kind: 'stackBar', title: 'Top 票 stage 构成（分钟）', categories: ['t-a', 't-b'], series: [{ name: '机器', data: [10, 20] }, { name: '人审等待', data: [5, 6] }], drill: true },
      ],
    },
    generated_at: '2026-09-03T00:00:00Z',
    cache: { status: 'hit', computed_at: '2026-09-03T00:00:00Z', source_version: 'v1' },
  },
  delivery: {
    kpis: { tickets: 48, closed: 10, avg_delivery_min: 126.1, tokens_total: 688332 },
    charts: {
      primary: { kind: 'hBar', title: 'Top 票变更量（行）', categories: ['t-a'], series: [{ name: '行数', data: [1200] }], drill: true },
      secondaries: [
        { kind: 'bar', title: '全窗口变更总量', categories: ['additions', 'deletions', 'commits'], series: [{ name: '量', data: [100, 40, 6] }], drill: true },
        donutSpec('有无代码变更票占比', ['有变更', '无变更/无数据'], [2, 46]),
      ],
    },
    generated_at: '2026-09-03T00:00:00Z',
    cache: { status: 'hit', computed_at: '2026-09-03T00:00:00Z', source_version: 'v1' },
  },
  token: {
    kpis: { tickets: 48, closed: 10, avg_delivery_min: 126.1, tokens_total: 688332 },
    charts: {
      primary: { kind: 'bar', title: 'stage token 消耗', categories: ['create_plan', 'review_plan', 'implement'], series: [{ name: 'tokens', data: [1000, 2000, 3000] }], drill: true },
      secondaries: [
        donutSpec('模型份额', ['deepseek/v3', 'gpt-5'], [395267, 293065]),
        { kind: 'hBar', title: 'Top 票 token 消耗', categories: ['t-a'], series: [{ name: 'tokens', data: [9000] }], drill: true },
      ],
    },
    generated_at: '2026-09-03T00:00:00Z',
    cache: { status: 'hit', computed_at: '2026-09-03T00:00:00Z', source_version: 'v1' },
  },
}

const staleBody = (view) => ({
  ...VIEW_BODY[view],
  cache: { status: 'stale', computed_at: '2026-09-03T00:00:00Z', source_version: 'v1' },
  reason: 'fast 无可用缓存（未算过或引擎版本失配），跳过现算',
})

/** 畸形 donut（全零+维度不齐）：必须走人话空态，不崩不静默画白板。 */
const MALFORMED_BODY = {
  kpis: { tickets: 1, closed: 0, avg_delivery_min: 0.0, tokens_total: 0 },
  charts: {
    primary: { kind: 'bar', title: 'stage 时长合计', categories: ['a'], series: [{ name: '时长(min)', data: [0] }], drill: true },
    secondaries: [donutSpec('时间去哪了：人审等待 vs 机器', ['人审等待', '机器', '幽灵扇区'], [0, 0])],
  },
  generated_at: '2026-09-03T00:00:00Z',
  cache: { status: 'hit', computed_at: '2026-09-03T00:00:00Z', source_version: 'v1' },
  reason: 't-ghost: delivery 维不可算（测试畸形样本）',
}

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'dsh', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'dsh', 'workbench', 'lib', 'client.cjs')
const CHARTS_TS = join(REPO, 'server', 'dsh', 'workbench', 'src', 'client', 'metrics-charts.ts')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return false
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return false
  }
  // 产物锚点按 tsdown 压缩后的字面（双引号 case、&mode=fast 拼接、角标文案）
  const anchors = ['donutOption', 'specToDonutInput', 'case "donut": return donut(', '&mode=fast', '缓存快照 · 刷新中']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing donut-render anchors: ${missing.join(', ')}`)
    return false
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, donut-render + cache-first anchors present')
  return true
}

async function dataSourceSmoke() {
  if (!existsSync(CHARTS_TS)) {
    record('S0 data-source', 'fail', 'metrics-charts.ts missing')
    return false
  }
  try {
    const mod = await import(pathToFileURL(CHARTS_TS).href + '?t=' + Date.now())
    if (typeof mod.specToDonutInput !== 'function' || typeof mod.donutOption !== 'function') {
      record('S0 data-source', 'fail', 'metrics-charts.ts does not export specToDonutInput/donutOption')
      return false
    }
    const spec = { kind: 'donut', title: '时间去哪了', categories: ['人审等待', '机器'], series: [{ name: '占比', data: [2786.5, 4824.14] }], drill: true }
    const d = mod.specToDonutInput(spec)
    const opt = mod.donutOption(d)
    const humanOk = d.slices[0].human === true && d.slices[1].human === false
    const optOk = opt.series?.[0]?.type === 'pie' && opt.series[0].data[0].itemStyle?.color === '#ff9b1f'
    if (!humanOk || !optOk) {
      record('S0 data-source', 'fail', `human slice/option shape broken: human=${JSON.stringify(d.slices)} opt=${JSON.stringify(opt.series?.[0]?.data)}`)
      return false
    }
    record('S0 data-source', 'pass', 'specToDonutInput human 判定 + donutOption pie 着色正确')
    return true
  } catch (e) {
    record('S0 data-source', 'fail', `metrics-charts.ts not importable: ${String(e).slice(0, 120)}`)
    return false
  }
}

// ---------------------------------------------------------------- S1 infra (precedent: sc_lane_parallel_dom.mjs)

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
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

/** canvas 非透明像素采样（真渲染=非白板的 DOM 级证据）。返回每个 canvas 的 painted 采样数。 */
const domCanvasPainted = `(() => {
  const out = [];
  document.querySelectorAll('.wb-m canvas').forEach(cv => {
    const w = cv.width, h = cv.height;
    if (!w || !h) { out.push(0); return; }
    const ctx = cv.getContext('2d');
    if (!ctx) { out.push(-1); return; }
    const img = ctx.getImageData(0, 0, w, h).data;
    let painted = 0;
    const stride = Math.max(16, Math.floor(img.length / 4096 / 4) * 4);
    for (let i = 3; i < img.length; i += stride) if (img[i] !== 0) painted++;
    out.push(painted);
  });
  return out;
})()`

/** 指定小标题容器内的 painted 采样数（-1=容器不在场）。 */
const domSubPainted = (title) => `(() => {
  const subs = [...document.querySelectorAll('.wb-m-sub')];
  const sub = subs.find(s => (s.querySelector('.t')?.textContent || '').includes(${JSON.stringify(title)}));
  if (!sub) return -1;
  const cvs = [...sub.querySelectorAll('canvas')];
  const res = [];
  cvs.forEach(cv => {
    const w = cv.width, h = cv.height;
    if (!w || !h) { res.push(0); return; }
    const ctx = cv.getContext('2d');
    if (!ctx) { res.push(-1); return; }
    const img = ctx.getImageData(0, 0, w, h).data;
    let painted = 0;
    const stride = Math.max(16, Math.floor(img.length / 4096 / 4) * 4);
    for (let i = 3; i < img.length; i += stride) if (img[i] !== 0) painted++;
    res.push(painted);
  });
  return Math.max(-1, ...res, -1);
})()`

async function openMetricsPanel(page) {
  await page.evaluate(() => localStorage.removeItem('suyou-workbench-metrics-panel-v1')).catch(() => {})
  // 入口=侧栏中列底「📊 度量」钮或 shell 覆盖层钮；面板挂 METRICS_TOGGLE_EVENT 总线——
  // 直接派发同一事件（入口钮 click 的下游就是它），DOM 渲染路径全真。
  const toggled = await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('wb-metrics-toggle'))
    return true
  })
  const open = await waitFor(async () => (await page.locator('.wb-m').count()) > 0, 8000)
  return { toggled, open }
}

async function clickTab(page, label) {
  const tab = page.locator('.wb-m-tab', { hasText: label }).first()
  if (!(await tab.count())) return false
  await tab.click()
  return true
}

async function runBrowser(pw, browser) {
  const ctx = await browser.newContext()
  try {
    const pageErrors = []
    const consoleErrors = []
    const badResponses = []
    let metricsRequests = 0
    let malformedMode = false
    const page = await ctx.newPage()
    page.on('response', (res) => { if (res.status() >= 400) badResponses.push(`${res.status()} ${res.url().slice(-90)}`) })
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    // 路由先于 goto：shell 装载即轮询 /wf/tickets，晚装桩会把台面 502 误记进 D6
    // API-boundary stub: catch-all 先注册（后注册者优先），隔离台未接 Temporal 的
    // 面板外轮询端点回 200 空响应——不消音会把环境 502 误记成面板卫生故障（D6）。
    await page.route('**/suyou-workbench/api/**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'scenario catch-all stub' }) }))
    await page.route('**/suyou-workbench/api/wf/metrics**', (route) => {
      const url = new URL(route.request().url())
      metricsRequests += 1
      const view = url.searchParams.get('view') ?? 'time'
      const mode = url.searchParams.get('mode') ?? 'full'
      const body = malformedMode ? MALFORMED_BODY : (mode === 'fast' ? staleBody(view) : VIEW_BODY[view])
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.route('**/suyou-workbench/api/wf/workflows**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ result: { workflows: [WF] } }) }))
    await page.route('**/suyou-workbench/api/wf/epics**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ result: [] }) }))
    await page.route('**/suyou-workbench/api/wf/tickets**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [] }, workflows: [WF] }) }))

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)


    // stub 消费预检（R1 取舍⑤）：面板必须真的发出了 metrics 请求（fast+full 两门）。
    const { open } = await openMetricsPanel(page)
    if (!open) {
      record('S1 precheck', 'env_fail', `metrics panel did not open on ${BASE} (app shell not provisioned for workbench plugin?)`)
      return
    }
    const consumed = await waitFor(async () => metricsRequests >= 2, 10000)
    if (!consumed) {
      record('S1 precheck', 'env_fail', `metrics stub not consumed (requests=${metricsRequests}) — panel fetch path changed?`)
      return
    }
    record('S1 precheck', 'pass', `metrics stub consumed (${metricsRequests} requests: fast+full double-door)`)

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 140)}`)
    const run = async (name, fn) => {
      try {
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    // D1 fast 快照角标先在（stale），全量到达后摘除。
    await run('D1 stale badge shown then cleared', async (p) => {
      // 面板打开时 fast 门已先回（角标可能已闪现后被摘）——重开面板复现时序。
      await p.locator('.wb-m-x').click()
      await p.waitForTimeout(300)
      await p.evaluate(() => document.dispatchEvent(new CustomEvent('wb-metrics-toggle')))
      const badge = await waitFor(async () =>
        (await p.locator('.wb-m .wb-m-degrade', { hasText: '缓存快照' }).count()) > 0, 6000)
      const badgeGone = await waitFor(async () =>
        (await p.locator('.wb-m .wb-m-degrade', { hasText: '缓存快照' }).count()) === 0, 15000)
      if (!badge && !badgeGone) return 'badge never appeared and never cleared (fast door broken?)'
      if (!badgeGone) return 'stale badge stuck (full replacement did not clear it)'
      return null
    })

    // D2 time 视图：主图与副1「时间去哪了」donut 真渲染（canvas 有非透明像素）。
    await run('D2 time view donut painted', async (p) => {
      const painted = await waitFor(async () => {
        const arr = await p.evaluate(domCanvasPainted)
        return arr.filter(v => v > 0).length >= 2
      }, 10000)
      if (!painted) return `time view canvases not painted: ${JSON.stringify(await p.evaluate(domCanvasPainted))}`
      const subPainted = await p.evaluate(domSubPainted('时间去哪了'))
      if (subPainted <= 0) return `时间去哪了 donut not painted (painted=${subPainted})`
      return null
    })

    // D3 delivery 视图：「有无代码变更票占比」donut 真渲染。
    await run('D3 delivery view donut painted', async (p) => {
      if (!(await clickTab(p, '交付'))) return 'delivery tab missing'
      const subPainted = await waitFor(async () => (await p.evaluate(domSubPainted('有无代码变更票占比'))) > 0, 10000)
      if (!subPainted) return `有无代码变更票占比 donut not painted (painted=${await p.evaluate(domSubPainted('有无代码变更票占比'))})`
      return null
    })

    // D4 token 视图：「模型份额」donut 真渲染。
    await run('D4 token view donut painted', async (p) => {
      if (!(await clickTab(p, 'Token'))) return 'token tab missing'
      const subPainted = await waitFor(async () => (await p.evaluate(domSubPainted('模型份额'))) > 0, 10000)
      if (!subPainted) return `模型份额 donut not painted (painted=${await p.evaluate(domSubPainted('模型份额'))})`
      return null
    })

    // D5 畸形 donut 数据：人话空态，不崩、不出白板画布（R1 取舍④加码项）。
    await run('D5 malformed donut -> blank-state text, no crash', async (p) => {
      malformedMode = true
      if (!(await clickTab(p, '时间'))) return 'time tab missing'
      const ok2 = await waitFor(async () =>
        (await p.locator('.wb-m .wb-m-empty').count()) > 0, 10000)
      const emptyText = ok2 ? await p.locator('.wb-m .wb-m-empty').first().textContent() : ''
      if (!ok2) return 'malformed donut did not surface blank-state text'
      if (!String(emptyText).includes('无可绘图数据') && !String(emptyText).includes('无可聚合数据')) {
        return `blank-state text unexpected: ${JSON.stringify(emptyText)}`
      }
      return null
    })
    malformedMode = false

    const hygieneDetail = `pageerrors=${pageErrors.length} consoleErrors=${consoleErrors.length}` +
      (pageErrors.length ? ` first=${pageErrors[0]}` : '') + (consoleErrors.length ? ` firstConsole=${consoleErrors[0]}` : '') +
      (badResponses.length ? ` bad=[${[...new Set(badResponses)].slice(0, 6).join(' | ')}]` : '')
    if (pageErrors.length === 0 && consoleErrors.length === 0) {
      record('D6 zero pageerror/console.error', 'pass')
    } else {
      record('D6 zero pageerror/console.error', 'fail', hygieneDetail)
    }
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

async function main() {
  const [maj, min] = process.versions.node.split('.').map(Number)
  if (maj < 22 || (maj === 22 && min < 18)) {
    record('node', 'env_fail', `node ${process.versions.node} < 22.18`)
    return summarize()
  }

  const s0ok = buildContract()
  if (s0ok) await dataSourceSmoke()

  if (BASE.includes(':3099')) {
    console.error('refusing to run: SUYOU_TEST_CONSOLE points at the production console (3099)')
    process.exit(1)
  }

  const healthy = await consoleHealthy()
  if (!healthy) {
    record('S1 precheck', 'env_fail', `test console unreachable at ${BASE} (docker compose -f server/dsh/docker-compose.test.yml up -d)`)
    return summarize()
  }
  const pw = await loadPlaywright()
  if (!pw) {
    record('S1 precheck', 'env_fail', 'playwright-core not resolvable (browser scenarios not run: env)')
    return summarize()
  }
  const browser = await launchBrowser(pw)
  if (!browser) {
    record('S1 precheck', 'env_fail', 'no browser could be launched')
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
    await runBrowser(pw, browser)
  } finally {
    if (!exiting) await browser.close().catch(() => {})
  }
  summarize()
}

main().catch(e => { console.error(String(e)); summarize() })
