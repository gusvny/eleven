#!/usr/bin/env node
// sc_t26100953_lane_map_pipe.mjs —— 泳道图=mock 的细管道而非积木块（t261009-53）。
//
// intent（灰盒 L3，browser-free 池，真浏览器 + page-boundary API 打桩，零 docker，
// 红线零接触 3099）：t261009-22 补齐了 mock 的 chrome 面但段渲染仍留 v1/v5 块结构
// ——整段一个大盒子（.wb-lm-track min-height:96px + 整底填色的 .wb-lm-item）、
// 标签塞在盒子里的 flex 列。本条独占 t261009-53 的段几何面（mock laneMap()
// notes/discussions/261004-concurrency-limit-mock.html，设计稿 §7.6 判据 1/4/5）：
// P1 主道=一条基线上的细条（12px 级、同高、同一 y）而非满轨道高的盒子；
// P2 标签浮在条上方两级交错、middle 锚、夹在画布内、不压条；
// P3 同级相邻标签互不压字（两级交错是唯一的防重叠面——审查意见①）；
// P4 人门菱形在段的左端（条头）不在盒子中心；
// P5 并行伙伴=主道下方第二道、虚线窗包住两道、∥ 标记、伙伴名在那道之下；
// P6 now 游标竖线纵贯两道；
// P7 状态=填充（done 22% 同色浅填充、running 实色）；段宽∝时长不回退（v5 存活）；
// P8 chrome 存活绊线（头部 elapsed/now-at + 时间轴两时刻；深断言归
// t261009-22-lane-map-mock-chrome，不重复）。
// intent 分界：比例宽/名义宽/主题捕获=t261008-23；chrome 字面（图例/轴刻度文案/
// waiting-for-you/hover/skipped 虚线空框）=t261009-22；拓扑解析/降级/受阻史=
// t260915-05、t260927-05。本条锚 SVG 图元几何（rect/text/path 属性+容差）——
// mock 的图面几何本身就是规格，不锚类名（KI-051）。
// KI 对齐：KI-055（真浏览器断言）；KI-051（语义锚 data-stage/data-kind，不锚类名）。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。

import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  PROJ, TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from '../t261008-23/lib_fix23.mjs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null
try {
  const b = await bootFixture(REPO, 't26100953-lanemap')
  bench = b.bench
  bench.teardownOnExit = b.teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// S0 build-contract：双 bundle 同步（KI-052）+ 本票新鲜度——stale lib 会把新几何
// 变成神秘红，点名重建入口，不静默。
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
  record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
} else {
  const js = readFileSync(LIB_JS, 'utf8')
  const sync = js === readFileSync(LIB_CJS, 'utf8')
  record('S0 build-contract', sync ? 'pass' : 'fail', sync ? 'twin bundles in sync' : 'twin bundles out of sync — rebuild (KI-052)')
}

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
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))

const detail = fixtureTicketDetail(fixtureTimeline())
await routeDetail(page, detail)
await bench.goto(page, { waitUntil: 'networkidle' })
await dismissIntroModal(page)
await page.waitForTimeout(2000)

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

// 泳道图 SVG 几何探针：锚 data-testid="detail-lane-map" 语义锚 + SVG 图元属性
// （rect/text/path/line 的 x/y/w/h/fill/fill-opacity/stroke-dasharray），
// 不锚类名、不锚字面坐标（KI-051；mock 几何即规格，容差放宽到实现可满足的档）。
const PROBE = `(() => {
  const lm = document.querySelector('[data-testid="detail-lane-map"]')
  if (!lm) return { found: false }
  const svg = lm.querySelector('svg')
  if (!svg) return { found: true, svg: false, text: (lm.textContent || '') }
  const vb = svg.viewBox && svg.viewBox.baseVal
  const num = (el, a) => { const v = el.getAttribute(a); return v == null || v === '' ? null : Number(v) }
  const rects = [...svg.querySelectorAll('rect')].map((r) => ({
    x: num(r, 'x'), y: num(r, 'y'), w: num(r, 'width'), h: num(r, 'height'),
    rx: num(r, 'rx'), fill: r.getAttribute('fill') || '',
    fo: r.getAttribute('fill-opacity') == null ? 1 : Number(r.getAttribute('fill-opacity')),
    dash: r.getAttribute('stroke-dasharray') || '',
    title: (r.querySelector('title') || {}).textContent || '',
  }))
  const texts = [...svg.querySelectorAll('text')].map((t) => ({
    x: num(t, 'x'), y: num(t, 'y'),
    anchor: t.getAttribute('text-anchor') || '',
    s: (t.textContent || '').trim(),
  }))
  const lines = [...svg.querySelectorAll('line')].map((l) => ({
    x1: num(l, 'x1'), y1: num(l, 'y1'), x2: num(l, 'x2'), y2: num(l, 'y2'),
    dash: l.getAttribute('stroke-dasharray') || '',
  }))
  const paths = [...svg.querySelectorAll('path')].map((p) => p.getAttribute('d') || '')
  const gs = [...svg.querySelectorAll('g[data-stage]')].map((g) => ({
    stage: g.getAttribute('data-stage') || '',
    kind: g.getAttribute('data-kind') || '',
    vis: g.getAttribute('data-vis') || '',
  }))
  return { found: true, svg: true, text: (lm.textContent || ''),
    vbw: vb ? vb.width : null, vbh: vb ? vb.height : null,
    rects, texts, lines, paths, gs,
    header: (lm.querySelector('header, [class*="head"], [class*="lsum"]') || lm).textContent.slice(0, 200) }
})()`

let lm = null
await waitFor(async () => {
  const v = await page.evaluate(PROBE)
  if (v.found && v.svg && v.rects.length >= 5) { lm = v; return true }
  return false
}, 10000)
if (!lm) {
  record('S2 lane-map svg present', 'fail', 'slim-pipe svg never rendered (block structure or absent); probe=' +
    JSON.stringify(await page.evaluate(PROBE)).slice(0, 300))
  await browser.close(); await bench.teardown(); summarize()
}
record('S2 lane-map svg present', 'pass', `rects=${lm.rects.length} texts=${lm.texts.length}`)
const approx = (a, b, tol) => Math.abs(a - b) <= tol

// 主道细条=同高（10-14 单位）的 rx 圆角矩形；伙伴条=第二个轨道 y 上的同高条；
// 虚线窗=带 dasharray 且高跨两道的大框。
const slim = lm.rects.filter((r) => r.h >= 10 && r.h <= 14 && r.rx != null && r.rx <= 4 && r.w > 0)
const baseYs = {}
for (const r of slim) baseYs[r.y] = (baseYs[r.y] || 0) + 1
const trackYs = Object.keys(baseYs).map(Number).sort((a, b) => a - b)
const mainY = trackYs[0]
const main = slim.filter((r) => r.y === mainY).sort((a, b) => a.x - b.x)
const partners = slim.filter((r) => r.y !== mainY)
const windows = lm.rects.filter((r) => r.dash && r.h > 20 && r.fill === 'none')

// P1 主道=一条基线上的细条（12px 级、同高、同一 y、圆角）。
rec('P1 main track is one baseline of slim equal-height rounded bars',
  main.length >= 6 && trackYs.length >= 1 && main.every((r) => r.h === main[0].h) && main[0].h <= 14,
  `main=${main.length} trackYs=${trackYs.join(',')} h=${main[0] && main[0].h} vbh=${lm.vbh}`)

// P2 不是整段大盒子：条的高的量级远小于画面高（块结构 min-height:96px 整底填色
// 的对面——条高 ≈ 12/96 画面占比；用比例断言不锚绝对像素）。
rec('P2 segments are slim bars, not full-track blocks',
  lm.vbh > 0 && main[0] && main[0].h / lm.vbh <= 0.3,
  `barH/vbH=${main[0] ? (main[0].h / lm.vbh).toFixed(2) : 'n/a'}`)

// P3 标签浮在条上方、两级交错、middle 锚、不压条。
const labels = lm.texts.filter((t) => t.y != null && t.y < mainY).sort((a, b) => a.x - b.x)
const levels = [...new Set(labels.map((t) => t.y))]
// 交错面：相邻（按 x 排序）标签不得长期同一级（mock 的两级交错）。
let adjacentSameLevel = 0
for (let i = 1; i < labels.length; i++) if (labels[i].y === labels[i - 1].y) adjacentSameLevel++
rec('P3a labels float above the bars in two alternating levels',
  labels.length >= 6 && levels.length === 2 && adjacentSameLevel <= Math.floor(labels.length / 3),
  `labels=${labels.length} levels=${levels.join(',')} adjacentSame=${adjacentSameLevel}`)
rec('P3b labels are middle-anchored and never painted onto a bar',
  labels.every((t) => t.anchor === 'middle') && labels.every((t) => t.y < mainY - 1),
  `anchors=${[...new Set(labels.map((t) => t.anchor))].join('/')} maxY=${Math.max(...labels.map((t) => t.y))} baseline=${mainY}`)

// P3c 夹边：每个标签 x 都在画布内（mock：Math.max(20, Math.min(cx, W+RPAD-20))）。
rec('P3c edge labels are clamped inside the canvas',
  labels.every((t) => t.x >= 5 && t.x <= lm.vbw - 5),
  `xs=[${Math.min(...labels.map((t) => t.x))}..${Math.max(...labels.map((t) => t.x))}] vbw=${lm.vbw}`)

// P3d 同级相邻标签互不压字（审查意见①：两级交错是唯一防重叠面——按字数估宽，
// 4.5 单位/字符 @8px 字号；同级相邻两标签的间距必须容下两份半宽）。
let overlapFree = true
let overlapDetail = ''
for (const lv of levels) {
  const row = labels.filter((t) => t.y === lv)
  for (let i = 1; i < row.length; i++) {
    const half = (t) => t.s.length * 4.5 / 2
    if (row[i].x - row[i - 1].x < half(row[i]) + half(row[i - 1])) {
      overlapFree = false
      overlapDetail = `${row[i - 1].s} <-> ${row[i].s} gap=${(row[i].x - row[i - 1].x).toFixed(0)}`
    }
  }
}
rec('P3d same-level neighbour labels do not overlap', overlapFree, overlapDetail || 'no same-level collision')

// P4 人门菱形在段的左端（条头）：找 data-kind=human 的段包装（语义锚），其
// path 的 x 范围必须落在该段条的左端 12 单位内，不在段中央。
const hum = lm.gs.find((g) => g.kind === 'human')
let diamondAtHead = false, diamondNote = 'no human segment found'
if (hum) {
  const hg = [...(await page.$$('svg g[data-kind="human"]'))]
  for (const g of hg) {
    const info = await g.evaluate((el) => {
      const num = (a) => { const v = el.getAttribute(a); return v == null ? null : Number(v) }
      const r = el.querySelector('rect')
      const p = el.querySelector('path')
      if (!r || !p) return null
      const nums = (p.getAttribute('d') || '').match(/-?[\d.]+/g)?.map(Number) || []
      const xs = nums.filter((_, i) => i % 2 === 0)
      return { rx: Number(r.getAttribute('x')), rw: Number(r.getAttribute('width')),
        pxmin: Math.min(...xs), pxmax: Math.max(...xs) }
    })
    if (info) {
      const atHead = info.pxmin >= info.rx - 2 && info.pxmax <= info.rx + 12
      diamondAtHead = diamondAtHead || atHead
      diamondNote = JSON.stringify(info)
    }
  }
}
rec('P4 human gate diamond sits at the LEFT head of its bar', diamondAtHead, diamondNote)

// P5 并行伙伴=第二道 + 虚线窗包两道 + ∥ 标记 + 伙伴名在那道之下。
const parOk = windows.length >= 2 && partners.length >= 2 &&
  windows.every((w) => partners.some((p) => p.y > w.y && p.y + p.h < w.y + w.h && p.x >= w.x - 1))
rec('P5a partner bars on a second track inside dashed windows spanning both tracks',
  parOk, `windows=${windows.length} partners=${partners.length}`)
const parMark = lm.texts.some((t) => t.s.includes('∥') || t.s.includes('||'))
rec('P5b the parallel mark is drawn', parMark, `texts=${lm.texts.map((t) => t.s).slice(0, 8).join('|')}`)
let parLabelBelow = false
if (partners.length) {
  // 伙伴名：伙伴条 x 范围内、y 在伙伴道之下（窗内或窗沿附近）的文本。
  parLabelBelow = partners.some((p) => lm.texts.some((t) =>
    t.y > p.y + p.h - 1 && t.y < p.y + p.h + 16 && t.x >= p.x - 2 && t.x <= p.x + p.w + 30))
}
rec('P5c the partner name sits below the partner track', parLabelBelow,
  partners.length ? `partnerY=${partners[0].y}` : 'no partner')

// P6 now 游标：虚线竖线，起于主道上方、纵贯到伙伴道之下（有窗时任一窗）。
const cursor = lm.lines.find((l) => l.dash && l.y1 < mainY && (partners.length ? l.y2 > Math.max(...partners.map((p) => p.y + p.h)) : l.y2 > mainY + main[0].h))
rec('P6 the now cursor spans both tracks', Boolean(cursor), JSON.stringify(cursor || {}))

// P7 状态=填充：done=22% 同色浅填充（fill-opacity≈0.22）、当前段实色（≈1）；
// 灰盒锚=夹具全链 done + merge 在跑（lib_fix23 时间线）。
const tinted = slim.filter((r) => approx(r.fo, 0.22, 0.03)).length
const solid = slim.filter((r) => approx(r.fo, 1, 0.02)).length
rec('P7 state by fill: done 22% tint and current solid', tinted >= 4 && solid >= 1,
  `tinted=${tinted} solid=${solid}`)

// P8 v5 比例宽存活：主道条宽不全等且最宽/最窄 ≥ 2（夹具 implement 窗 24m 对
// review 4m；深比例断言归 t261008-23，此处只锁不回退到等宽块）。
const ws = main.map((r) => r.w)
rec('P8 proportional widths survive (not equal-width blocks)',
  ws.length >= 6 && Math.min(...ws) > 0 && Math.max(...ws) / Math.min(...ws) >= 2,
  `w range ${Math.min(...ws)}..${Math.max(...ws)}`)

// P9 chrome 存活绊线：头部 elapsed/now-at + 时间轴两时刻（深断言归 t261009-22）。
// 时间轴起止时刻是 t261009-22 交付的 HTML 行（.wb-lm-axis），不在 SVG 里，
// 故按整图 textContent 认时刻（t261009-53 实现对拍修正）。
rec('P9 chrome tripwire: header summary and axis clocks still render',
  /elapsed/i.test(lm.header) && /now at/i.test(lm.header) &&
  (lm.text.match(/\b\d{2}:\d{2}\b/g) || []).length >= 2,
  lm.header.slice(0, 120))

// P10 全程零页错、零 undefined 字面（畸形时间线条目已在夹具外由 t261009-22
// 覆盖；此处锁本票重写后不引入新的崩溃面）。
rec('P10 zero pageerror and no undefined literal after the rewrite',
  pageErrors.length === 0 && !/undefined/i.test(lm.text),
  pageErrors.join(' | ').slice(0, 200))

// 明暗双主题捕获（KI-055 证据面；尽力而为，不判红）。
const outDir = join(REPO, 'integration', 't261009-53', 'out')
try { mkdirSync(outDir, { recursive: true }) } catch { /* exists */ }
for (const scheme of ['light', 'dark']) {
  try {
    await page.emulateMedia({ colorScheme: scheme })
    await page.waitForTimeout(300)
    const lmEl = await page.$('[data-testid="detail-lane-map"]')
    if (lmEl) { await lmEl.scrollIntoViewIfNeeded(); await page.waitForTimeout(200) }
    const shot = lmEl || page
    await shot.screenshot({ path: join(outDir, `lane-map-pipe-${scheme}.png`) })
    record(`C capture-${scheme}`, 'pass', `out/lane-map-pipe-${scheme}.png`)
  } catch (e) {
    record(`C capture-${scheme}`, 'na', String(e).slice(0, 120))
  }
}

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()
