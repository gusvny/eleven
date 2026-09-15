// metrics-donut-dom — the DOM-level black-box baseline for the t260903-09
// "three donuts render as blank slates" fix.
//
// Intent (black-box, user perspective): when the metrics panel **has data**,
// the three donuts — 「时间去哪了」 (time, secondary 1), 「有无代码变更票占比」
// (delivery, secondary 2), 「模型份额」 (token, secondary 1) — must really
// render (the canvas has non-transparent pixels = not a blank slate), and the
// human-review sector keeps its own orange; malformed data takes the
// plain-language empty state instead of crashing. Root-cause history:
// renderSpec had no 'donut' branch, so the three donut specs fell through to
// the default no-op and setOption was never called after init (blank slates).
//
// Intent boundary with t03_donut_empty.mjs (integration/t260902-05): that one
// covers the "no data empty state", this scenario covers "with data it really
// renders" — complementary, not duplicate.
//
// Tradeoffs against sc_lane_parallel_dom.mjs's seven fault modes (the
// create_plan gen1 R1 list) — all carried over:
// (1) isolated port 3199 (never touches 3099); (2) a missing environment =
// ENV_FAIL (exit 2); (3) the SUMMARY last-line contract; (4) pageerror /
// console.error hygiene assertions (hardened: malformed donut data must not
// make echarts throw); (5) a stub-consumption precheck (the panel really did
// issue the metrics requests; unconsumed = env_fail, never a fake green);
// (6) a finally-backstop browser close; (7) no real tickets touched (the API
// boundary is fully stubbed). The seven share one rationale: the production
// console is untouchable, machine differences must not fake a red, the whole
// baseline family shares one runner policy, zero-exception hygiene, no fake
// green, terminal-state cleanup, zero real data.
//
// Two layers:
//   S0 build-contract (pure node, runs everywhere): twin bundles in sync +
//      the donut render anchors present in the artifact (donutOption /
//      specToDonutInput / case 'donut' / &mode=fast / the cache-snapshot
//      badge) + a pure-logic smoke (specToDonutInput/donutOption).
//   S1 browser DOM assertions (real rendering level): needs the ISOLATED test
//      console (SANDBAR_TEST_CONSOLE, default 127.0.0.1:3199), playwright-core,
//      and a launchable chromium. Any missing -> ENV_FAIL (exit 2, reason on
//      stdout). Data stubbed at the API boundary with page.route(): the
//      metrics double door (mode=fast snapshot stale → full recompute) is
//      routed by query in the stub, while the DOM/React/echarts render path is
//      all real. Never touches production console (3099) nor real tickets.
//
// Execution contract (t260904-12 three-state): stdout's last line is
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 or every leg na ->
// exit 1; env_fail>0 -> exit 2 (an environmental red: nothing was verified and
// the reason belongs to the environment); all pass -> 0. Node >= 22.18.

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

/** The three donuts in the user's own words: real CLI-measured numbers
 *  ([2786.5,4824.14]/[395267,293065]/[2,46]). */
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

/** Malformed donut (all zeros + mismatched dimensions): must take the
 *  plain-language empty state — no crash, no silently painted blank slate. */
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

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const CHARTS_TS = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'metrics-charts.ts')

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
  // Artifact anchors are written as the post-tsdown-minify literals (the
  // double-quoted case, the &mode=fast concatenation, the badge copy).
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

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

/** Samples non-transparent canvas pixels (a real render = not a blank slate,
 *  at DOM level). Returns each canvas's painted-sample count. */
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

/** Painted-sample count inside the container with the given subtitle (-1 = the container is absent). */
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
  // Factory notice gate (t260829-07 family): on a FRESH stage DSH_HOME the
  // harness shell pops an「Internal Testing Notice」modal (Continue button,
  // full-screen mask, z≈1000) that sits ABOVE the metrics panel (z=95) —
  // every panel click is then intercepted (260915 donut red diagnosed by
  // .sandbar/probe_donut_click.mjs: elementFromPoint hits the notice mask;
  // in-suite greens were stages whose flag an earlier browser had already
  // set). Dismiss before opening the panel — read-only navigation semantics,
  // safe to repeat, same pattern as ui-check/capture.mjs and lib_fix17.
  try {
    const btn = page.locator('button', { hasText: /continue|继续/i }).first()
    await btn.waitFor({ state: 'visible', timeout: 4000 })
    await btn.click({ timeout: 3000 }).catch(() => btn.evaluate((el) => el.click()))
    await btn.waitFor({ state: 'hidden', timeout: 3000 }).catch(() => { /* 已消失即可 */ })
  } catch { /* 未弹出，继续 */ }
  await page.evaluate(() => localStorage.removeItem('sandbar-workbench-metrics-panel-v1')).catch(() => {})
  // Entry = the 「📊 度量」 button at the bottom of the sidebar's middle column
  // or the shell overlay button; the panel listens on the METRICS_TOGGLE_EVENT
  // bus — dispatching that same event directly (it is what the entry button's
  // click cascades into) keeps the DOM render path fully real.
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
    // Routes go in before goto: the shell polls /wf/tickets as soon as it
    // loads, so a late stub would mis-attribute the workbench's 502s to D6.
    // API-boundary stub: the catch-all registers first (later registrations
    // win), so polling endpoints outside the panel that the isolated workbench
    // has not wired to Temporal get 200 empty responses — without that
    // silencing, environmental 502s would be miscounted as panel hygiene
    // failures (D6).
    await page.route('**/sandbar-workbench/api/**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'scenario catch-all stub' }) }))
    await page.route('**/sandbar-workbench/api/wf/metrics**', (route) => {
      const url = new URL(route.request().url())
      metricsRequests += 1
      const view = url.searchParams.get('view') ?? 'time'
      const mode = url.searchParams.get('mode') ?? 'full'
      const body = malformedMode ? MALFORMED_BODY : (mode === 'fast' ? staleBody(view) : VIEW_BODY[view])
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.route('**/sandbar-workbench/api/wf/workflows**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ result: { workflows: [WF] } }) }))
    await page.route('**/sandbar-workbench/api/wf/epics**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ result: [] }) }))
    await page.route('**/sandbar-workbench/api/wf/tickets**', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, result: { tickets: [] }, workflows: [WF] }) }))

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)


    // Stub-consumption precheck (R1 tradeoff 5): the panel must really have
    // issued the metrics requests (both the fast and full doors).
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

    const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 400)}`)
    const run = async (name, fn) => {
      try {
        const err = await fn(page)
        if (err) record(name, 'fail', err)
        else record(name, 'pass')
      } catch (e) { await failWith(name, e) }
    }

    // D1 the fast-snapshot badge shows first (stale) and is removed once the
    // full payload arrives.
    await run('D1 stale badge shown then cleared', async (p) => {
      // By the time the panel opens, the fast door has already answered (the
      // badge may have flashed and been removed) — reopen the panel to
      // reproduce the timing.
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

    // D2 time view: the primary chart and the secondary-1 「时间去哪了」 donut
    // really render (the canvas has non-transparent pixels).
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

    // D3 delivery view: the 「有无代码变更票占比」 donut really renders.
    await run('D3 delivery view donut painted', async (p) => {
      if (!(await clickTab(p, '交付'))) return 'delivery tab missing'
      const subPainted = await waitFor(async () => (await p.evaluate(domSubPainted('有无代码变更票占比'))) > 0, 10000)
      if (!subPainted) return `有无代码变更票占比 donut not painted (painted=${await p.evaluate(domSubPainted('有无代码变更票占比'))})`
      return null
    })

    // D4 token view: the 「模型份额」 donut really renders.
    await run('D4 token view donut painted', async (p) => {
      if (!(await clickTab(p, 'Token'))) return 'token tab missing'
      const subPainted = await waitFor(async () => (await p.evaluate(domSubPainted('模型份额'))) > 0, 10000)
      if (!subPainted) return `模型份额 donut not painted (painted=${await p.evaluate(domSubPainted('模型份额'))})`
      return null
    })

    // D5 malformed donut data: plain-language empty state — no crash and no
    // blank-slate canvas (the R1 tradeoff-4 hardening).
    await run('D5 malformed donut -> blank-state text, no crash', async (p) => {
      malformedMode = true
      if (!(await clickTab(p, '时间'))) return 'time tab missing'
      // 终态空态判定：metrics 缓存特性下 refreshing 分支横幅（「缓存快照已上台，全量
      // 刷新中…」）先于空态文案渲染（空态分支互斥、横幅为在途态），套件负载下瞬时
      // 首文本断言撞横幅=偶发假红（260915 仲裁轮实锤）——改轮询等刷新收敛到终态空态
      // 文案（横幅允许在途，不弱化：终态必须收敛到空态文案），超时点名所见文本。
      const blankRe = /无可绘图数据|无可聚合数据/
      let lastText = ''
      const ok2 = await waitFor(async () => {
        lastText = await p.locator('.wb-m .wb-m-empty').first().textContent().catch(() => '')
        return blankRe.test(lastText)
      }, 30000)
      if (!ok2) {
        return `malformed donut did not reach blank-state text in 30s (last=${JSON.stringify(lastText)})`
      }
      return null
    })

    // D7 terminal mutual exclusion (t260915-09 implement gen2 widening — the
    // baseline enhancement proposed during acceptance walkthrough, routed here
    // by the project-session inspection): the refreshing branch copy
    // 「缓存快照已上台，全量刷新中…」 (metrics.tsx) renders inside the SAME
    // `.wb-m-empty` container family as the terminal blank text — the four
    // body-state branches are mutually exclusive by construction, but nothing
    // asserted that. A regression that strands the panel in the refreshing
    // state (full response never lands / state not cleared) would show a
    // permanently「刷新中」fake-progress face next to a rendered empty state.
    // D5 only requires convergence TO the terminal text; D7 adds the other
    // half of the contract: at terminal state the in-flight copy must be
    // retired. Pure widening — D1-D6 untouched.
    await run('D7 refreshing banner retired at terminal empty state', async (p) => {
      const blankRe = /无可绘图数据|无可聚合数据/
      const empties = await p.locator('.wb-m .wb-m-empty').allTextContents().catch(() => [])
      if (!empties.some((t) => blankRe.test(t))) {
        return `precondition lost: terminal blank text no longer present (empties=${JSON.stringify(empties).slice(0, 120)})`
      }
      const stuck = empties.filter((t) => t.includes('全量刷新中'))
      if (stuck.length > 0) {
        return `refreshing copy stuck alongside terminal empty state (count=${stuck.length}) — 空态分支互斥破`
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
    console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)')
    process.exit(1)
  }

  const healthy = await consoleHealthy()
  if (!healthy) {
    record('S1 precheck', 'env_fail', `test console unreachable at ${BASE} (docker compose -f server/docker-compose.test.yml up -d)`)
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
