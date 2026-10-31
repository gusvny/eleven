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
//
// S1 readiness condition (t261031-12, KI-437). The S1 precheck used a FIXED
// budget: waitFor(..., 10000) wrapped around two fixed sleeps (2000 ms after
// load, 1200 ms after the row click). A loaded machine reads "not yet" as
// "never": the 22:15Z whole-line round booked 112.5 s ENV_FAIL - "timeline
// panel never rendered" - while the same tree passes standalone in 20.9 s. The
// budget is now a CONDITION: the case polls the ticket row and the detail
// timeline panel, clicks the row while the panel is still absent (a swallowed
// click is re-armed, never judged), and returns the instant the panel is
// present. A healthy machine pays the render, not the ceiling.
//
// The ceiling is INJECTABLE through the project's SANDBAR_*_SECS convention
// (same shape as SANDBAR_T26101115_REFUSAL_NOTICE_SECS in t261011-15):
// `SANDBAR_T26100823_RENDER_SECS`, default 120. A malformed or non-positive
// value is NAMED and falls back to the default - an unreadable knob must never
// shorten the wait into a false red. The ceiling only bounds how long a
// genuinely missing face is awaited; its expiry is an ENV_FAIL that NAMES what
// never happened and keeps the observed state in the receipt (row present?,
// detail panel present?, page errors, elapsed). The same ceiling bounds the two
// other fixed clocks this case owned - the S2 rows wait and the in-page React
// flush of T3b/T3c - because both are the same kind of judgement. The T1-T4
// claims themselves are untouched.
//
// Status note: a slow-but-arriving face was never a content red here. The S1
// precheck is a precheck (its expiry was already ENV_FAIL before this ticket),
// so that named env_fail face is kept - not weakened into a pass, and not
// rewritten into a product red.

import { join } from 'node:path'
import {
  TID, fixtureTimeline, fixtureTicketDetail, routeDetail,
  loadPlaywright, launchBrowser, bootFixture, recorder, dismissIntroModal,
} from './lib_fix23.mjs'

const REPO = process.cwd()

/* ---------------------------------------------------------------- render ceiling (t261031-12)
 * The ONE clock this case owns. Every wait below is a CONDITION poll bounded by
 * this ceiling, so a loaded machine costs the render, never a false "never".
 * Provenance rides in every receipt: an unreadable knob is named, and it falls
 * BACK to the default - a typo must never shorten the wait into a false red. */
const RENDER_SECS_ENV = 'SANDBAR_T26100823_RENDER_SECS'
const DEFAULT_RENDER_CEILING_S = 120
const RENDER_POLL_MS = 250

function renderCeiling() {
  const fallback = { ms: DEFAULT_RENDER_CEILING_S * 1000, provenance: 'default' }
  const raw = String(process.env[RENDER_SECS_ENV] ?? '').trim()
  if (raw === '') return fallback
  const secs = Number(raw)
  if (!Number.isFinite(secs)) {
    return { ms: fallback.ms, provenance: `malformed ${JSON.stringify(raw)} -> default` }
  }
  if (!(secs > 0)) {
    return { ms: fallback.ms, provenance: `non-positive ${JSON.stringify(raw)} -> default` }
  }
  return { ms: Math.round(secs * 1000), provenance: `env ${JSON.stringify(raw)}` }
}

const RENDER = renderCeiling()
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

/* ---------------------------------------------------------------- condition waits (t261031-12)
 * One probe is one query round. Errors are DATA here (the poll keeps trying);
 * they are reported with the state so a stuck page is readable from the
 * receipt. Nothing below judges a duration - the ceiling only ends a wait that
 * would otherwise run forever. */
const TIMELINE_PANEL = '[data-testid="detail-timeline"]'

function errText(e) {
  return String(e && e.message ? e.message : e).slice(0, 140)
}

async function probeTimelineFace() {
  try {
    const row = await page.$(`[data-ticket-id="${TID}"]`)
    const panel = await page.$(TIMELINE_PANEL)
    return { rowPresent: !!row, panelPresent: !!panel, error: '' }
  } catch (e) {
    return { rowPresent: null, panelPresent: null, error: errText(e) }
  }
}

// The first-run notice overlay intercepts clicks. A late overlay would swallow
// every row click and turn "not ready yet" into a false expiry, so the poll
// re-arms the dismissal instead of assuming the first attempt won.
async function reArmIntroModal() {
  try {
    const btn = page.getByRole('button', { name: 'Continue' }).first()
    if (await btn.isVisible()) await btn.click({ timeout: 3000 })
  } catch { /* no overlay up - nothing to dismiss */ }
}

// Poll the S1 condition: the ticket row is on the board AND the detail timeline
// panel is mounted. Returns { ready, waitedMs, rounds, clicks, last, ... } - the
// verdict and the whole receipt come from here, so "never rendered" is always
// named with the state that was observed.
async function waitTimelineFace() {
  const started = Date.now()
  let rounds = 0
  let clicks = 0
  let last = { rowPresent: false, panelPresent: false, error: '' }
  for (;;) {
    rounds += 1
    last = await probeTimelineFace()
    if (last.panelPresent === true) {
      return { ready: true, rounds, clicks, waitedMs: Date.now() - started, last }
    }
    if (last.rowPresent !== true) {
      // the board itself is not up yet: re-arm the overlay, click nothing
      await reArmIntroModal()
    } else {
      // the row is up and the panel is not: this is the click the case makes
      try {
        const row = await page.$(`[data-ticket-id="${TID}"]`)
        if (row) { await row.click(); clicks += 1 }
      } catch (e) { last = { ...last, error: errText(e) } }
    }
    const elapsed = Date.now() - started
    if (elapsed >= RENDER.ms) {
      return { ready: false, rounds, clicks, waitedMs: elapsed, last, ceilingMs: RENDER.ms }
    }
    await new Promise(r => setTimeout(r, Math.min(RENDER_POLL_MS, Math.max(0, RENDER.ms - elapsed))))
  }
}

// Generic condition wait on the same named ceiling: returns the last probe
// value beside the verdict, so an expiry names what never happened.
async function waitCond(cond) {
  const started = Date.now()
  let rounds = 0
  let last = null
  for (;;) {
    rounds += 1
    try { last = await cond() } catch (e) { last = { error: errText(e) } }
    if (last && last.held === true) {
      return { held: true, rounds, waitedMs: Date.now() - started, last }
    }
    const elapsed = Date.now() - started
    if (elapsed >= RENDER.ms) {
      return { held: false, rounds, waitedMs: elapsed, last, ceilingMs: RENDER.ms }
    }
    await new Promise(r => setTimeout(r, Math.min(RENDER_POLL_MS, Math.max(0, RENDER.ms - elapsed))))
  }
}

const opened = await waitTimelineFace()
if (!opened.ready) {
  record('S1 precheck', 'env_fail',
    `detail timeline never rendered for ${TID} within the ${RENDER.ms}ms ceiling (${RENDER.provenance}): `
    + `rowPresent=${opened.last.rowPresent} panelPresent=${opened.last.panelPresent} `
    + `pageErrors=${pageErrors.length} elapsed=${opened.waitedMs}ms probes=${opened.rounds} `
    + `rowClicks=${opened.clicks} probeError=${JSON.stringify(opened.last.error || '')}`)
  await browser.close(); await bench.teardown()
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2)
}
record('S1 precheck', 'pass',
  `timeline panel rendered: elapsed=${opened.waitedMs}ms of ${RENDER.ms}ms ceiling `
  + `(${RENDER.provenance}), probes=${opened.rounds}, rowClicks=${opened.clicks}`)

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
const rowsWait = await waitCond(async () => {
  // The probe result rides out through the poll's own `last` value (the shared
  // lib waitFor returned only true, so the state died with it - fixture gap).
  const v = await page.evaluate(TL)
  return { held: !!(v && v.rowCount > 0), value: v }
})
if (rowsWait.last && rowsWait.last.value) tl = rowsWait.last.value
if (!rowsWait.held || !tl) {
  record('S2 timeline rows', 'fail',
    `timeline rows never rendered within the ${RENDER.ms}ms ceiling (${RENDER.provenance}): `
    + `lastProbe=${JSON.stringify(rowsWait.last || null)} elapsed=${rowsWait.waitedMs}ms `
    + `probes=${rowsWait.rounds} pageErrors=${pageErrors.length}`)
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
// The React flush after the click is a CONDITION too (t261031-12): the old read
// waited a fixed 150 ms tick and would judge a slow flush as "the text did not
// grow". The in-page loop polls until the flush lands or the named ceiling ends
// it - the claim is unchanged, only the clock became a condition.
const REVEAL_BUDGET_MS = RENDER.ms
if (tl.isButton) {
  const reveal = await page.evaluate(`(async () => {
    const budgetMs = ${REVEAL_BUDGET_MS}
    const panel = document.querySelector('[data-testid="detail-timeline"]')
    const rows = [...panel.querySelectorAll('li')]
    const long = rows.find(li => li.querySelector('[data-testid="timeline-row"][data-collapsed="true"]'))
    const btn = long.querySelector('button')
    const before = long.textContent.length
    btn.focus(); btn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    btn.click()
    const started = Date.now()
    let seen = { after: before, expanded: btn.getAttribute('aria-expanded'),
      full: long.textContent.includes(${JSON.stringify(LONG.slice(-80))}) }
    while (Date.now() - started < budgetMs) {
      seen = { after: long.textContent.length, expanded: btn.getAttribute('aria-expanded'),
        full: long.textContent.includes(${JSON.stringify(LONG.slice(-80))}) }
      if (seen.expanded === 'true' && seen.after > before) break
      await new Promise(r => setTimeout(r, 50))
    }
    return { before, after: long.textContent.length, expanded: btn.getAttribute('aria-expanded'),
      full: long.textContent.includes(${JSON.stringify(LONG.slice(-80))}), waitedMs: Date.now() - started }
  })()`)
  rec('T3b activating the control expands to the full reason text',
    reveal.after > reveal.before && reveal.expanded === 'true' && reveal.full,
    JSON.stringify(reveal))
  // 全文不丢的负面面：再收起回到短式，条目仍在、控件仍在（文本可随时再展开=未丢）。
  const collapseBack = await page.evaluate(`(async () => {
    const budgetMs = ${REVEAL_BUDGET_MS}
    const panel = document.querySelector('[data-testid="detail-timeline"]')
    const rows = [...panel.querySelectorAll('li')]
    const long = rows.find(li => li.querySelector('[data-testid="timeline-row"]') &&
      li.querySelector('[data-testid="timeline-row"]').textContent.length > 80 &&
      li.querySelector('button'))
    const btn = long.querySelector('button')
    const rowEl = long.querySelector('[data-testid="timeline-row"]')
    btn.click()
    const started = Date.now()
    // the same condition wait: poll the collapse back into the short form
    while (Date.now() - started < budgetMs) {
      if (btn.getAttribute('aria-expanded') === 'false' && rowEl.getAttribute('data-collapsed') === 'true') break
      await new Promise(r => setTimeout(r, 50))
    }
    return { expanded: btn.getAttribute('aria-expanded'),
      collapsedAgain: rowEl.getAttribute('data-collapsed') === 'true',
      rowStillPresent: rows.length, waitedMs: Date.now() - started }
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
