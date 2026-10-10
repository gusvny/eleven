#!/usr/bin/env node
// sc_t26100823_timeline_reason_collapse.mjs —— 时间线降噪 option b（t261008-23 缺陷 ②）。
//
// intent（灰盒 L3，browser-free 池，真浏览器 + page-boundary API 打桩，零 docker，
// 红线零接触 3099）：工单时间线**每一条目都保留**（行数=时间线长度，不许丢行换整洁）；
// 长理由行呈现短式 + 展开控件（键盘可达：button + aria-expanded），展开露出全文且
// 文本不丢；短理由行照旧直排；畸形条目（缺 reason/缺 state）不炸不产 undefined 字面量。
// intent 分界：时间线行的时间/阶段/状态词构成归既有详情列条目（t260915-05 族）；
// 本条独占 reason 折叠面、行数保全面与畸形条目三态。
// KI 对齐：KI-051（锚语义：aria-expanded + 行内全文在 DOM，不锚类名）；输入三态
// （畸形时间线条目：不丢、不 undefined、不 pageerror）。实现未落地段红属预期（TDD）。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。

import { join } from 'node:path'
import {
  TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, waitFor, dismissIntroModal,
} from './lib_fix23.mjs'

const REPO = process.cwd()
const { record, rec, summarize } = recorder()
let bench = null
try {
  const b = await bootFixture(REPO, 't26100823-timeline')
  bench = b.bench
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

// t261009-79: the fixture interleaves done marks, so rows must be selected by
// stage, never by position.
const LONG = fixtureTimeline().find((r) => r.stage === 'implement').reason
const detail = fixtureTicketDetail(fixtureTimeline())
// 畸形条目三态：缺 reason、缺 state、at 缺失——都不得炸、不得丢行。
detail.timeline.push(
  { at: Date.now() + 5000, stage: 'merge_check', reason: '' },
  { at: Date.now() + 6000, stage: 'merge', state: '', reason: undefined },
  { stage: 'merge', reason: 'no timestamp row' },
)

const pw = await loadPlaywright(REPO)
const browser = pw ? await launchBrowser(pw) : null
if (!browser) {
  console.log('[ENV_FAIL] playwright-core/chromium unavailable (KI-036 family)')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  try { await bench.teardown() } catch { /* down */ }
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

const opened = await waitFor(async () => {
  const row = await page.$(`[data-ticket-id="${TID}"]`)
  if (!row) return false
  await row.click()
  await page.waitForTimeout(1200)
  return !!(await page.$('[data-testid="detail-timeline"]'))
}, 10000)
if (!opened) {
  record('S1 precheck', 'env_fail', `timeline panel never rendered for ${TID}`)
  await browser.close(); await bench.teardown()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2)
}
record('S1 precheck', 'pass', 'timeline panel rendered')

const TL = `(() => {
  const panel = document.querySelector('[data-testid="detail-timeline"]')
  if (!panel) return null
  const rows = [...panel.querySelectorAll('li')]
  // KI-051 semantic anchor: a collapsed long-reason row marks itself with
  // data-testid="timeline-row" + data-collapsed="true" and carries a native
  // expand button. Do NOT anchor on textContent length — the shipped contract
  // is "short form (TIMELINE_REASON_MAX) + expand reveals the full text", so a
  // collapsed row is SHORT in the DOM by design.
  const long = rows.find(li => li.querySelector('[data-testid="timeline-row"][data-collapsed="true"]'))
  let btn = long ? long.querySelector('button,[role="button"]') : null
  if (!btn && long) btn = [...long.querySelectorAll('*')].find(el =>
    el.getAttribute('aria-expanded') !== null || /more|less|expand|collapse/i.test(el.textContent || ''))
  return {
    rowCount: rows.length,
    undefinedLit: /\\bundefined\\b/.test(panel.textContent || ''),
    long: !!long,
    expanded: btn ? btn.getAttribute('aria-expanded') : null,
    isButton: btn ? btn.tagName === 'BUTTON' : false,
  }
})()`

let tl = false
await waitFor(async () => {
  // lib waitFor returns only true, never the cond value — capture the probe
  // result through the outer variable (fixture gap: tl was always true).
  const v = await page.evaluate(TL)
  if (v && v.rowCount > 0) { tl = v; return true }
  return false
}, 10000)
if (!tl) {
  record('S2 timeline rows', 'fail', 'timeline rows never rendered')
  await browser.close(); await bench.teardown(); summarize()
}

// T1 行数保全：时间线行数=夹具条数（option b 铁律：一条不少）。
rec('T1 every timeline entry is kept (row count equals fixture length)',
  tl.rowCount === detail.timeline.length,
  `rows=${tl.rowCount} fixture=${detail.timeline.length}`)

// T2 长理由收短式 + 展开控件（data-collapsed 锚，短式在 DOM 是设计态）。
rec('T2 a long reason row renders a collapsed form with an expand control',
  tl.long && tl.expanded !== null, `expanded=${tl.expanded} hasControl=${tl.expanded !== null}`)

// T3 键盘可达 + 展开露全文不丢。
rec('T3 expand control is keyboard reachable and reveals the full text without loss',
  tl.isButton && tl.expanded === 'false',
  `isButton=${tl.isButton} aria-expanded=${tl.expanded}`)
if (tl.isButton) {
  const reveal = await page.evaluate(`(async () => {
    const panel = document.querySelector('[data-testid="detail-timeline"]')
    const rows = [...panel.querySelectorAll('li')]
    const long = rows.find(li => li.querySelector('[data-testid="timeline-row"][data-collapsed="true"]'))
    const btn = long.querySelector('button')
    const before = long.textContent.length
    btn.focus(); btn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    btn.click()
    await new Promise(r => setTimeout(r, 150)) // React state flush: reads must wait a tick
    return { before, after: long.textContent.length,
      expanded: btn.getAttribute('aria-expanded'),
      full: long.textContent.includes(${JSON.stringify(LONG.slice(-80))}) }
  })()`)
  rec('T3b activating the control expands to the full reason text',
    reveal.after > reveal.before && reveal.expanded === 'true' && reveal.full,
    JSON.stringify(reveal))
  // 全文不丢的负面面：再收起回到短式，条目仍在、控件仍在（文本可随时再展开=未丢）。
  const collapseBack = await page.evaluate(`(async () => {
    const panel = document.querySelector('[data-testid="detail-timeline"]')
    const rows = [...panel.querySelectorAll('li')]
    const long = rows.find(li => li.querySelector('[data-testid="timeline-row"]') &&
      li.querySelector('[data-testid="timeline-row"]').textContent.length > 80 &&
      li.querySelector('button'))
    const btn = long.querySelector('button')
    btn.click()
    await new Promise(r => setTimeout(r, 150)) // React state flush: reads must wait a tick
    const rowEl = long.querySelector('[data-testid="timeline-row"]')
    return { expanded: btn.getAttribute('aria-expanded'),
      collapsedAgain: rowEl.getAttribute('data-collapsed') === 'true',
      rowStillPresent: rows.length }
  })()`)
  rec('T3c collapsing again returns to the short form with the entry and control intact',
    collapseBack.expanded === 'false' && collapseBack.collapsedAgain && collapseBack.rowStillPresent === detail.timeline.length,
    JSON.stringify(collapseBack))
}

// T4 畸形条目三态：不炸、不 undefined、行不丢（T1 已数行）。
rec('T4 malformed entries: no undefined literal, no pageerror',
  !tl.undefinedLit && pageErrors.length === 0,
  `undefinedLit=${tl.undefinedLit} pageErrors=${pageErrors.length}`)

await browser.close()
try { await bench.teardown() } catch { /* down */ }
summarize()
