#!/usr/bin/env node
// sc_t26100823_lane_map_v5.mjs —— 泳道图 mock v5 形态（t261008-23 缺陷 ①）。
//
// intent（灰盒 L3，browser-free 池，真浏览器 + page-boundary API 打桩，零 docker，
// 红线零接触 3099）：详情面泳道图按 mock v5 画——段宽 ∝ 段耗时（比例断言按模型携带
// 的时长真源 data-weight-ms 对照渲染宽度，容差取固定宽实现不可能满足的档）、未开始
// 段占名义宽（不被首段吃光）、两处真并行叉（implement∥design_integration_tests、
// arbitrate∥acceptance_walkthrough）=同一时间窗内两道带 + 虚线框 + ‖/∥ 标记；
// 明暗两主题捕获（KI-055）；渲染器通用性=组件词面零 dev-lane 业务词（锚=DOM 词面）。
// intent 分界：泳道拓扑解析/降级/受阻史归 t260915-05 与 t260927-05（外置模板）；
// 本条独占 v5 的时长比例面、并行双带窗面、名义宽面与主题捕获。
// KI 对齐：KI-055（真浏览器断言+明暗双主题）；KI-051（锚语义不锚字面：宽度断言用
// data-weight-ms 与几何比，不锚类名）；实现未落地段红属预期（TDD 信号）。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。

import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  PROJ, TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from './lib_fix23.mjs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null
try {
  const b = await bootFixture(REPO, 't26100823-lanemap')
  bench = b.bench
  bench.teardownOnExit = b.teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// S0 build-contract：双 bundle 同步（KI-052）。
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return false
  }
  const sync = readFileSync(LIB_JS, 'utf8') === readFileSync(LIB_CJS, 'utf8')
  record('S0 build-contract', sync ? 'pass' : 'fail', sync ? 'twin bundles in sync' : 'twin bundles out of sync — rebuild (KI-052)')
  return sync
}

const detail = fixtureTicketDetail(fixtureTimeline())
let pw = null, browser = null
try { pw = await loadPlaywright(REPO) } catch { /* handled below */ }
browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  try { await bench.teardown() } catch { /* already down */ }
  process.exit(2)
}

const ctx = await browser.newContext()
const pageErrors = []
const page = await ctx.newPage()
page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))

await routeDetail(page, detail)
await bench.goto(page, { waitUntil: 'networkidle' })
await dismissIntroModal(page)
await page.waitForTimeout(2000)

// 打开详情抽屉（锚=行 data-ticket-id，不绑类名主体）。
const opened = await waitFor(async () => {
  const row = await page.$(`[data-ticket-id="${TID}"]`)
  if (!row) return false
  await row.click()
  await page.waitForTimeout(1200)
  return !!(await page.$('[data-testid="detail-columns"]'))
}, 10000)
if (!opened) {
  record('S1 precheck', 'env_fail', `detail drawer never opened for ${TID}`)
  await browser.close(); await bench.teardown()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2)
}
record('S1 precheck', 'pass', 'detail drawer open')

// 泳道图探针：锚 data-band / data-weight-ms（方案声明的语义锚）；几何取 getBoundingClientRect。
const PROBE = `(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"], .wb-lanemap') ||
    [...document.querySelectorAll('*')].find(el => el.children.length && /lane map/i.test(el.textContent || '') && el.querySelector('[data-weight-ms]'))
  if (!lm) return { found: false }
  // partner bands carry data-band but not data-weight-ms (the group item
  // carries the window weight) — enumerate both anchors (fixture gap).
  const segs = [...lm.querySelectorAll('[data-weight-ms], [data-band]')].map(el => {
    const r = el.getBoundingClientRect()
    return {
      w: Math.round(r.width), ms: Number(el.getAttribute('data-weight-ms')),
      band: el.getAttribute('data-band') || null,
      label: (el.getAttribute('data-stage') || el.getAttribute('data-label') || el.textContent || '').trim().slice(0, 40),
    }
  })
  const dashed = [...lm.querySelectorAll('*')].filter(el => {
    const cs = getComputedStyle(el)
    return (cs.borderTopStyle === 'dashed' || cs.borderStyle === 'dashed') &&
      Math.round(el.getBoundingClientRect().width) > 40
  }).length
  const text = lm.textContent || ''
  return {
    found: true, segs, dashed,
    mark: /\\u2225|\\|\\|/.test(text),
    words: /implement|arbitrate|walkthrough|design_integration_tests/.test(text),
    body: text.slice(0, 300),
  }
})()`

let lm = null
await waitFor(async () => {
  // lib waitFor returns only true, never the cond value — capture the probe
  // result through the outer variable (fixture gap: lm was always true).
  const v = await page.evaluate(PROBE)
  if (v.found && v.segs.length >= 6) { lm = v; return true }
  return false
}, 10000)
if (!lm) {
  record('S2 lane-map present', 'fail', 'lane map with weighted segments never rendered; body=' +
    JSON.stringify(await page.evaluate(PROBE)).slice(0, 300))
  await browser.close(); await bench.teardown(); summarize()
}

const segs = lm.segs
const singles = segs.filter(s => s.band !== 'partner')
const partners = segs.filter(s => s.band === 'partner')

// T1 段宽 ∝ 时长：非全等 + 与 data-weight-ms 成仿射关系（mock v5 公式本身带名义
// 地板：width = MIN_PCT + flex × weight/total，纯比例断言会误伤地板语义）。
// 断言：width 对 ms 线性回归后残差 ≤ 满量程 25%，且斜率显著 > 0（固定宽实现
// 斜率=0、残差满量程，必红）。未开始段名义宽：最窄段不得小于最宽段的 1/12。
const withMs = singles.filter(s => s.ms > 0 && s.w > 0)
const widths = new Set(withMs.map(s => s.w))
rec('T1a segment widths are NOT all equal', widths.size > 1, `distinct widths=${[...widths].join(',')}`)
let fit = { b: 0, worst: 1 }
if (withMs.length >= 2) {
  const n = withMs.length
  const mx = withMs.reduce((a, s) => a + s.ms, 0) / n
  const my = withMs.reduce((a, s) => a + s.w, 0) / n
  let num = 0, den = 0
  for (const s of withMs) { num += (s.ms - mx) * (s.w - my); den += (s.ms - mx) ** 2 }
  const b = den > 0 ? num / den : 0
  const a = my - b * mx
  const range = Math.max(...withMs.map(s => s.w)) - Math.min(...withMs.map(s => s.w))
  const worst = range > 0
    ? Math.max(...withMs.map(s => Math.abs(s.w - (a + b * s.ms)))) / range
    : 1
  fit = { b, worst }
}
rec('T1b widths affine in durations (mock v5 formula: floor + flex × share; fixed-width cannot satisfy)',
  fit.b > 0 && fit.worst <= 0.25, `slope=${fit.b.toExponential(2)} worst rel residual=${fit.worst.toFixed(3)}`)
const minW = Math.min(...singles.map(s => s.w)), maxW = Math.max(...singles.map(s => s.w))
rec('T1c unstarted stages keep a nominal width (not swallowed by the longest stage)',
  minW > 0 && minW >= maxW / 12, `min=${minW}px max=${maxW}px`)

// T2 并行叉=同一时间窗两道带 + 虚线框 + ‖ 标记。
const bandsByWindow = partners.length
rec('T2a each parallel fork draws a partner band', bandsByWindow >= 2, `partner bands=${bandsByWindow}`)
rec('T2b dashed window boxes drawn around the parallel windows', lm.dashed >= 1, `dashed boxes=${lm.dashed}`)
rec('T2c parallel mark (|| glyph family) present', lm.mark, `mark=${lm.mark}`)

// T3 渲染器通用性：泳道图 DOM 词面允许出现 stage 名（数据），但组件不得把
// dev-lane 业务判定词写死进渲染面（锚=图内不出现渲染器自带的业务句）。
rec('T3 renderer stays generic (no invented business sentences in the map)',
  !/handoff from|you are here|blocked once: a check measured/i.test(lm.body),
  lm.body.slice(0, 120))

rec('T4 no pageerror on the detail face', pageErrors.length === 0, pageErrors.join(' | ').slice(0, 200))

// T5 明暗两主题捕获（KI-055 验收证据面；尽力而为，不判红）。
const outDir = join(REPO, 'integration', 't261008-23', 'out')
try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
for (const scheme of ['light', 'dark']) {
  try {
    await page.emulateMedia({ colorScheme: scheme })
    await page.waitForTimeout(300)
    await page.screenshot({ path: join(outDir, `lane-map-v5-${scheme}.png`), fullPage: false })
    record(`T5 capture-${scheme}`, 'pass', `out/lane-map-v5-${scheme}.png`)
  } catch (e) {
    record(`T5 capture-${scheme}`, 'na', String(e).slice(0, 120))
  }
}

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()
