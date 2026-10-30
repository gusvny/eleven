#!/usr/bin/env node
// t261011-15 场景：摘除理由框在长列表下的可见性面（灰盒 L3，browser-free 池，
// 镜 t261008-08/sc_t26100808_left_column_row_composition.mjs 的 bootConsole +
// API 打桩 + 真浏览器形态）。
//
// 用户场景（工单正文）：在左栏 failed 行点 Dismiss，理由框是滚动容器的最后一个
// 孩子——板面一长（宿主实况：4 项目 / 310 票）框就开在折叠线以下，点击看起来
// 没反应，理由没处填、请求从不发出。修复后：理由框锚到被点行、open effect
// scrollIntoView + focus，列表多长都可见；restore 同一规则。
//
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。playwright 缺席
// =ENV_FAIL（KI-036，经 lib_pw_deps 单点解析）。
//
// Bench-broken classification (t261030-46). The incident: the same situation -
// the isolated bench never rendered the long failed list - was booked as a
// content red inside a line round (which reds the round and freezes the line)
// and as ENV_FAIL standalone. Rule now enforced here: a bench that cannot
// boot, or whose face is broken, is a NAMED ENV_FAIL (exit 2 -> env_fail in
// the round) on EVERY path. The bench-dependent steps are named - bench-boot,
// playwright, browser-launch, browser-context, page-load, fixture-list,
// dismissal - and every failure of one of them reports the step, the error and
// what the page did (URL, pageerrors, sidebar size, rendered Dismiss controls,
// visible sidebar text). An unexpected throw or unhandled rejection while the
// bench is driven can therefore never escape as exit 1. What stays a content
// red is what was actually observed about the product: the prompt not being
// visible, the reason box not focused, the wire contract, the refusal not
// surfacing, and the twin bundles DRIFTING (KI-052). No known-red booking, no
// skip, no weakened assertion.
//
// S3d fixture determinism + the POST's answer (t261031-01). The 261031 round
// recorded the refusal notice missing for the whole 180 s ceiling (893 poll
// rounds) AND the prompt closed at the end - the shape of a dismissal the route
// ANSWERED, not of a refusal that was waited for too briefly. The receipt could
// not say more, because the leg recorded the REQUEST side only. Two changes:
//   1. the leg now records what the route ANSWERED (status + body) and what the
//      stub's refusal predicate saw for the clicked row, inside the same state
//      JSON as the existing fields - a next occurrence is decidable without a
//      rerun;
//   2. the refusal is established BY CONSTRUCTION before the click and asserted
//      to hold (S3p1-S3p3): the fixture still serves the clicked failed row, the
//      engine channel the route spawns answers that exact dismissal with the
//      named refusal, the probe went through the stub and changed nothing. The
//      assertion itself is untouched: a refusal must surface verbatim on the
//      face and must never be swallowed.
//
// S3d condition wait (t261030-50, KI-431 family). The refusal-notice leg used
// to wait a FIXED settle budget for a DOM condition, so a loaded machine read
// "not yet" as "never" and reddened a full round twice. It now polls the
// condition - the engine's named refusal attached to the clicked row's face -
// and returns the instant it holds, so a healthy machine pays the render, not
// the ceiling. The ceiling only bounds how long a genuinely missing notice is
// awaited; it is injectable through SANDBAR_T26101115_REFUSAL_NOTICE_SECS
// (malformed/non-positive value named and defaulted), and its expiry fails BY
// NAME with the t261030-46 state fields intact. The assertion is not
// weakened: a non-empty notice that does not carry the engine's own refusal
// still reds, because that is the refusal being swallowed or replaced.
//
// The two directions of the disposition (t261031-05). The 261031 round recorded a
// refused POST (200 + ok:false) with the prompt gone and no notice. The refusal
// branch itself never closes the prompt (sidebar.tsx closes it only when the
// answer carries ok:true), so what the round measured is a STATE LOSS of the
// sidebar subtree, and the case could not tell it apart because it owned ONE
// direction only. What it owes and now proves:
//   1. S3d asserts the prompt face explicitly - the notice renders INSIDE the
//      prompt, so "the engine refusal surfaced" and "the prompt stayed open" are
//      ONE claim, and the receipt carries promptOpen: a closed prompt can no
//      longer pass as a surfaced refusal;
//   2. S5 drives the ACCEPTED direction on the same bench and the same row: the
//      stub's channel property is flipped to the engine's acceptance face
//      (ctrl.accept.dismiss - opt-in, see t260904-17/lib_fix17.mjs), the person's
//      retry is answered ok:true, and the face must close the prompt AND take the
//      row off the board, with the project's dismissed count naming where it
//      went. The legitimate close path is pinned, not assumed.
//
// intent 分界（防 intent 级重复）：
//   - 行两行组成/悬停/项目块边框/排序控件 → t261008-08 与 t261006-18（本条零重叠）。
//   - dismiss 的 **答案面**（路由→真 ticket.py→journal 落盘→行离板）与 who/reason
//     契约 → t261009-54 的 sc_t26100954_dismiss_seam_engine_answer（真缝端到端，
//     journal 行读取自盘面）。本条只借「请求到达引擎缝」一根针（stub trace 出现
//     ticket:dismiss + 拒收原文上脸），不重复 journal 断言。
//   - 空项目键（unowned 组）不带 ?project= 的 URL 契约 → L1（t261011-15-dismiss-
//     request）钉死；本条只钉「带键的浏览器请求线上确实带 ?project=」。
// KI 对齐：KI-055（真浏览器断言）；KI-052（双 bundle 同步，S0）；KI-036（playwright
// 缺席=ENV_FAIL）；输入三态（拒收原文逐字上脸，绝不被吞）。
// 新故障面登记建议（integration 岗位）：「行内弹层开在滚动容器尾部 ⇒ 折叠线以下
// 不可见」——老测试用短夹具列表看不见此面；长列表可见性断言必须锚 viewport。

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, dismissNotice } from '../t260904-17/lib_fix17.mjs';
import { loadPlaywright } from '../lib_pw_deps.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// Resolved from THIS file, never from cwd (t261030-46): the runner starts a
// case with cwd = the repo root, but a case started anywhere else must still
// judge the tree it lives in. A cwd-derived path makes the S0 build-contract
// leg report "workbench not built" - a broken context booked as a content red,
// exactly the misclassification this ticket removes.
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')

// ---------------------------------------------------------------- three-state bookkeeping
// Contract (integration/README.md): the last stdout line is
// `SUMMARY pass=N fail=N env_fail=N na=N`, exit 1 when any assertion failed
// (or everything was na), exit 2 when the context was missing or broken.
// The runner books exit 2 as env_fail and any other non-zero exit as the case
// red that reds the line round, so this split IS the round's verdict.

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function rec(name, cond, detail = '') {
  record(name, cond ? 'pass' : 'fail', detail)
}
function counts() {
  const out = { pass: 0, fail: 0, env_fail: 0, na: 0 }
  for (const r of results) out[r.status] += 1
  return out
}
function summarize() {
  const c = counts()
  const allNa = results.length > 0 && c.na === results.length
  console.log(`SUMMARY pass=${c.pass} fail=${c.fail} env_fail=${c.env_fail} na=${c.na}`)
  process.exit(c.fail > 0 || allNa ? 1 : c.env_fail > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- bench-failure classification
// Project rule (ticket t261030-46): a bench that cannot boot, or whose face is
// broken, is a NAMED ENV_FAIL on EVERY path - standalone and inside a line
// round alike. It is never a content red.
// The mechanism, so no future edit can silently reopen the hole:
//   1. every bench-dependent step names itself in STEP before it runs;
//   2. any throw / unhandled rejection while driving the bench is caught by
//      the two handlers below and reported with that step, the error, and what
//      the page did (URL, pageerrors, sidebar size, the Dismiss controls it
//      rendered, the visible sidebar text);
//   3. the verdict is exit 2, which the round books as env_fail.
// Only observed product behaviour stays a content red: rec() with a false
// condition, and the twin-bundle DRIFT face of the build contract (KI-052).
let STEP = 'bench-boot'
let page = null
let browser = null
let exiting = false
let judged = false
const pageErrors = []

function pageFacts() {
  let url = '(no page opened)'
  try { if (page && !page.isClosed()) url = page.url() } catch { /* page gone */ }
  return `url=${url}; pageerrors=${pageErrors.length ? pageErrors.slice(-3).join(' | ') : 'none'}`
}

// What the page did/shows, probed with a bound: this runs on the failing path,
// where the page may be wedged, and the exit must never hang on it.
async function pageDomFacts(waitMs = 2500) {
  if (!page) return 'dom=(no page opened)'
  try { if (page.isClosed()) return 'dom=(page closed)' } catch { /* treat as closed */ }
  try {
    const probe = page.evaluate(() => {
      const sb = document.querySelector('.wb-sb')
      const btn = document.querySelector('button[title^="Dismiss:"]')
      const text = String((sb || document.body)?.innerText || '').replace(/\s+/g, ' ').slice(0, 240)
      return {
        sidebarNodes: sb ? sb.querySelectorAll('*').length : 0,
        dismissButtons: document.querySelectorAll('button[title^="Dismiss:"]').length,
        firstDismissTitle: btn ? String(btn.title).slice(0, 80) : '',
        text,
      }
    }).catch((e) => ({ probeError: String(e).slice(0, 120) }))
    const dom = await Promise.race([probe,
      new Promise((r) => setTimeout(() => r({ probeError: `probe timeout >${waitMs}ms` }), waitMs))])
    if (dom.probeError) return `dom unreadable: ${dom.probeError}`
    return `sidebarNodes=${dom.sidebarNodes}; dismissButtons=${dom.dismissButtons}`
      + `; firstDismissTitle=${JSON.stringify(dom.firstDismissTitle)}; sidebarText=${JSON.stringify(dom.text)}`
  } catch (e) {
    return `dom unreadable: ${String(e).slice(0, 120)}`
  }
}

async function benchEnvFail(step, cause) {
  if (judged) {
    // Every assertion has already been judged: a late bench/teardown fault
    // says nothing about the product, so it is named and the verdict stands
    // (the alternative - flipping a judged run to env_fail - would be a false
    // environment red).
    console.log(`[note] bench fault after the assertions were judged (verdict unchanged): ${String(cause instanceof Error ? cause.message : cause).replace(/\s+/g, ' ').slice(0, 300)}`)
    return
  }
  if (exiting) process.exit(2)
  exiting = true
  const raw = cause instanceof Error ? cause.message : String(cause)
  const msg = raw.replace(/\s+/g, ' ').slice(0, 400)
  const dom = await pageDomFacts()
  record(`bench ${step}`, 'env_fail',
    `bench step '${step}' broke, so the assertion was NOT judged: ${msg}`)
  console.log(`[ENV_FAIL] bench step '${step}': page ${pageFacts()}; ${dom}`)
  if (browser) { try { await browser.close() } catch { /* reaping below */ } }
  summarize()
}

process.on('uncaughtException', (e) => { void benchEnvFail(STEP, e) })
process.on('unhandledRejection', (e) => { void benchEnvFail(STEP, e) })

// Facts from the fixture/engine-channel face: which ops the stub actually saw.
function stubTraceFacts(stubRef) {
  try {
    const trace = stubRef.readTrace()
    const listOps = trace.filter((t) => t.op === 'ticket:list').length
    const last = trace.slice(-5).map((t) => `${t.op}:${t.id || ''}`).join(', ')
    return `engineChannel ticket:list ops=${listOps}; lastTrace=${last || 'empty'}`
  } catch (e) {
    return `engineChannel unreadable: ${String(e).slice(0, 120)}`
  }
}

// ---------------------------------------------------------------- boot（离线隔离台）

let BASE = ''
let bench = null
const PROJ = 'fixture-dv'   // 长列表主项目（dismiss 脸载体）
const PROJ2 = 'fixture-rs'  // restore 脸载体（折叠行）
// Dwell window is a pinned 24 h (failed rows settle like closed ones) — fixture
// rows must be fresh against the real wall clock or the sidebar retires them.
const T0 = Math.floor(Date.now() / 1000) - 600
const TARGET = 'fd-last'    // 被点的最后一个 failed 行
const RESTORE_TARGET = 'rs-d1'

function devRow(id, title, ts, extra = {}) {
  return {
    id, role: 'developer', status: 'failed', title,
    workflow: 'dev-lane', stage: 'implement', stage_state: 'failed',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—', updated_ts: ts,
    created: ts, engine: 'template-as-code-v2', exec_status: 'RUNNING',
    epic: 'dismiss-visibility', ...extra,
  }
}

// 长 failed 列表：70 行 ≈ 远超 800px 视口（折叠线以下才有内容）。
const rows = []
for (let i = 0; i < 69; i++) rows.push(devRow(`fd${String(i).padStart(2, '0')}`, `bulk failed row ${i}`, T0 + i))
rows.push(devRow(TARGET, 'the failed row the person clicks', T0 + 500))
const rows2 = [
  devRow('rs-ok', 'normal failed row', T0),
  devRow(RESTORE_TARGET, 'dismissed row awaiting restore', T0 + 1,
    { dismissed: { at: '2026-10-11T09:00:00Z', who: 'host', reason: 'duplicate of rs-ok' } }),
]

const stub = makeTicketStub()
stub.setCtrl({
  workflows: [],
  tickets: [
    ...rows.map(t => ({ ...t, project: PROJ })),
    ...rows2.map(t => ({ ...t, project: PROJ2 })),
  ],
  show: {},
})

STEP = 'bench-boot'
try {
  const projectsRoot = makeRegistryRoot('t26101115-registry-')
  writeProjectEntry(projectsRoot, PROJ, PROJ, ['/tmp/fx-dv'])
  writeProjectEntry(projectsRoot, PROJ2, PROJ2, ['/tmp/fx-rs'])
  bench = await bootConsole(projectsRoot, stub)
  BASE = bench.base
  await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  // The isolated bench (profile build, spawn, 45 s readiness, token exchange)
  // is the one thing every assertion below depends on: a broken boot is a
  // NAMED ENV_FAIL, never a case red.
  await benchEnvFail('bench-boot', e)
}

// ---------------------------------------------------------------- S0 build contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    // "Not built at all" is missing context (the face cannot be judged at
    // all), so it is an ENV_FAIL. The PRODUCT claim stays where it was and
    // still reds: the twin bundles must not drift apart (KI-052).
    record('S0 build-contract', 'env_fail',
      `lib/client.js or lib/client.cjs missing — workbench not built, so the face cannot be judged (looked in ${REPO})`)
    return false
  }
  if (readFileSync(LIB_JS, 'utf8') !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return false
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync')
  return true
}

// ---------------------------------------------------------------- 浏览器

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* poll */ }
    await new Promise(r => setTimeout(r, 200))
  }
  try { return await cond() } catch { return false }
}

// ---------------------------------------------------------------- S3d condition wait (KI-431 family)
// The refusal notice on the row's face is a CONDITION, not a duration. S3c has
// already proved the POST reached the engine channel, so the only thing left to
// observe is the panel rendering the engine's refusal. A FIXED settle budget
// read "not yet" as "never": on a loaded machine the same path takes ~4x longer
// (two full rounds measured 116.8s / 117.3s against ~30s standalone) and the leg
// went red although nothing was swallowed. The wait below therefore polls the
// condition and returns the instant it holds - its cost on a healthy machine is
// the render, not a window - and the ceiling only bounds how long a genuinely
// missing notice is awaited.
//
// The ceiling is INJECTABLE through the project's `SANDBAR_*_SECS` convention
// (same shape as SANDBAR_D2B_PYTEST_BUDGET_SECS / SANDBAR_T26100503_CHILD_READY_SECS):
// `SANDBAR_T26101115_REFUSAL_NOTICE_SECS`. A malformed or non-positive value is
// NAMED and falls back to the default - an unreadable knob must never shorten
// the wait into a false red.
const NOTICE_SECS_ENV = 'SANDBAR_T26101115_REFUSAL_NOTICE_SECS'
const DEFAULT_NOTICE_CEILING_S = 180
const NOTICE_POLL_MS = 200
const NOTICE_SELECTOR = '[data-wb-dismiss-notice]'

function noticeCeiling() {
  // (effective ceiling in ms, provenance string) - never silent: the provenance
  // rides in the pass receipt and in the failing leg's text.
  const raw = String(process.env[NOTICE_SECS_ENV] ?? '').trim()
  const fallback = { ms: DEFAULT_NOTICE_CEILING_S * 1000, provenance: 'default' }
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

// One probe is one evaluate round with NO Playwright auto-wait: locator
// text-content waits for attachment up to the action timeout, which would hide
// the budget from the poll. Errors are data here (the poll keeps trying).
// t261031-01: the probe also reports whether the prompt is still on the page -
// the notice is rendered INSIDE the prompt, so a closed prompt means the notice
// can never attach. That moment is recorded, not judged here.
async function probeNotice() {
  try {
    const got = await page.evaluate((sel) => {
      const el = document.querySelector(sel)
      return {
        attached: el !== null,
        text: el ? String(el.textContent || '').trim() : '',
        promptOpen: document.querySelector('[data-wb-dismiss-prompt]') !== null,
      }
    }, NOTICE_SELECTOR)
    return {
      attached: got?.attached === true, text: String(got?.text || ''),
      promptOpen: got?.promptOpen === true, error: '',
    }
  } catch (e) {
    return {
      attached: false, text: '', promptOpen: null,
      error: String(e && e.message ? e.message : e).slice(0, 140),
    }
  }
}

// One probe bounded by what is LEFT of the ceiling (t261031-01). A probe is an
// evaluate round, and on a stalled page that round can outlast the declared
// ceiling: on a loaded machine this leg has run 835 poll rounds over 1091 s
// against a 180 s ceiling (the stall also starved the timer that was supposed to
// end it), and a leg that runs past its own ceiling is no longer the wait it
// declares. A probe that cannot answer inside the remaining budget is reported as
// such, never as an empty notice.
async function boundedProbe(remainMs) {
  const probe = probeNotice()
  return Promise.race([
    probe,
    new Promise((resolveP) => {
      const timer = setTimeout(() => resolveP({
        attached: false, text: '', promptOpen: null,
        error: `probe did not answer within the remaining ceiling (${remainMs}ms)`,
      }), Math.max(0, remainMs))
      if (typeof timer.unref === 'function') timer.unref()
    }),
  ])
}

// Poll for the refusal notice to attach with non-empty text. Returns
// { shown, rounds, waitedMs, last, provenance, ceilingMs?, promptClosedAfterMs,
// firstProbe } - the verdict and the whole receipt come from here, so "never
// appeared" is always named, and a prompt that closed DURING the wait is named
// with the moment it was first seen gone (the answer side is added by the
// caller).
async function waitForNotice(ceiling) {
  const started = Date.now()
  let rounds = 0
  let last = { attached: false, text: '', promptOpen: null, error: '' }
  let promptClosedAfterMs = null
  let firstProbe = null
  for (;;) {
    rounds += 1
    last = await boundedProbe(Math.max(0, ceiling.ms - (Date.now() - started)))
    if (firstProbe === null) firstProbe = { ...last }
    if (last.attached && last.text !== '') {
      return {
        shown: true, rounds, waitedMs: Date.now() - started, last,
        provenance: ceiling.provenance, promptClosedAfterMs, firstProbe,
      }
    }
    if (last.promptOpen === false && promptClosedAfterMs === null) promptClosedAfterMs = Date.now() - started
    const elapsed = Date.now() - started
    if (elapsed >= ceiling.ms) {
      return {
        shown: false, rounds, waitedMs: elapsed, last,
        provenance: ceiling.provenance, ceilingMs: ceiling.ms, promptClosedAfterMs, firstProbe,
      }
    }
    await new Promise(r => setTimeout(r, Math.min(NOTICE_POLL_MS, Math.max(0, ceiling.ms - elapsed))))
  }
}

// ---------------------------------------------------------------- fixture determinism (t261031-01)
// The engine channel of this bench refuses EVERY ticket op it does not serve
// (only list and show are served), so the refusal this leg needs is a property
// of the CHANNEL, not of the ticket's state. It is still established before the
// click and asserted to hold: the probe below runs the same channel shape the
// dismiss route uses (admin.py call ticket {...} with the bench env, where
// python3 resolves to the stub's shim through PATH), so the receipt proves what
// the engine channel answered at that moment instead of assuming it.
const ENGINE_REFUSAL_MARK = 'fix17'   // the isolated bench's named dismissal refusal
const PROBE_CEILING_MS = 120000       // child-process hard ceiling for the probe channel

// The fixture face the stub serves for the clicked row: what a refusal predicate
// keyed on ticket state would read, and what the row face is derived from.
function fixtureRowFacts(stubRef) {
  try {
    const ctrl = JSON.parse(readFileSync(stubRef.ctrlPath, 'utf8'))
    const rows = Array.isArray(ctrl.tickets) ? ctrl.tickets : []
    const row = rows.find((t) => t && t.id === TARGET) ?? null
    return {
      rows: rows.length,
      row: row === null ? null : {
        id: row.id, project: row.project, status: row.status,
        stage_state: row.stage_state, dismissed: Object.hasOwn(row, 'dismissed'),
      },
      digest: JSON.stringify(row),
    }
  } catch (e) {
    return { rows: -1, row: null, digest: `unreadable: ${String(e).slice(0, 120)}` }
  }
}

// t261031-05: flip the stub's disposition answer face (S5, the accepted
// direction). Read-modify-write the ctrl file - the stub itself rewrites it when
// it accepts, so the served rows are exactly the ones this journey has produced
// so far. The knob is opt-in: without it the channel keeps refusing by name,
// which is the property S3p1-S3p3 establish.
function setAcceptKnob(on) {
  const cur = JSON.parse(readFileSync(stub.ctrlPath, 'utf8'))
  cur.accept = on ? { dismiss: true, restore: true } : {}
  stub.setCtrl(cur)
}

// One probe of the engine channel the dismiss route spawns. Returns the answer
// verbatim plus the stub trace rows it produced, so "the channel refused" is
// observed rather than assumed.
function dismissalProbe(stubRef) {
  const traceSize = stubRef.traceSizeAt()
  const env = {
    ...process.env,
    PATH: `${stubRef.dir}:${process.env.PATH || ''}`,
    FIX17_CTRL: stubRef.ctrlPath,
    FIX17_TRACE: stubRef.tracePath,
  }
  const res = spawnSync(join(stubRef.dir, 'python3'),
    [join(REPO, 'server', 'admin.py'), 'call', 'ticket',
      JSON.stringify({ op: 'dismiss', id: TARGET, by: 'fixture-probe', reason: 'fixture determinism probe' })],
    { env, encoding: 'utf8', timeout: PROBE_CEILING_MS })
  let answer = null
  let parseError = ''
  try { answer = JSON.parse(String(res.stdout || '').trim()) } catch (e) {
    parseError = String(e && e.message ? e.message : e).slice(0, 140)
  }
  return {
    status: res.status,
    answer,
    parseError,
    signal: res.signal ?? '',
    stderr: String(res.stderr || '').slice(0, 200),
    traced: stubRef.traceSince(traceSize).map((t) => `${t.op}:${t.id}`),
  }
}

// What the stub's refusal predicate saw for the clicked row at the moment the
// leg looks: the served fixture row and the ops the shim actually received.
function stubPredicateView(stubRef, sinceSize) {
  const fixture = fixtureRowFacts(stubRef)
  let ops = []
  try { ops = stubRef.traceSince(sinceSize ?? 0).map((t) => `${t.op}:${t.id}`).slice(-8) } catch { /* reported below */ }
  return {
    refuseRule: 'every ticket op other than list/show is refused by name (the channel, not the ticket state)',
    servedRow: fixture.row,
    fixtureRows: fixture.rows,
    opsSinceClick: ops,
  }
}

// 断言绑公开行为（viewport 相交 + DOM 锚 data-*），不绑内部布局/类名主体。
STEP = 'playwright'
const pw = await loadPlaywright()
if (!pw) {
  await benchEnvFail('playwright', 'lib_pw_deps probe came back empty — no playwright-core on any candidate face')
}
STEP = 'browser-launch'
for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
  try { browser = await pw.chromium.launch(opts); break } catch { /* next */ }
}
if (!browser) {
  await benchEnvFail('browser-launch', 'no chromium/chrome browser launchable from the resolved playwright-core')
}

if (!buildContract()) { if (browser) await browser.close().catch(() => {}); summarize() }

STEP = 'browser-context'
try {
  page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage()
} catch (e) {
  await benchEnvFail('browser-context', e)
}
page.on('pageerror', (e) => { pageErrors.push(String(e && e.message ? e.message : e).slice(0, 200)) })
// t261031-01: a renderer crash also wipes the prompt state (and with it a notice
// that WAS rendered), so it is recorded on the same face as a page error instead
// of surfacing as an unexplained missing notice.
page.on('crash', () => { pageErrors.push('page crashed (renderer gone - state would be lost)') })
const dismissPosts = []
page.on('request', (req) => {
  const u = req.url()
  if (u.includes('/dismiss') || u.includes('/restore')) {
    dismissPosts.push({ url: u, body: req.postData() ?? '' })
  }
})
// t261031-01: the ANSWER side of the same request. The 261031 red recorded only
// what was sent, so the answer had to be guessed from a rerun. Status and body
// text are stored per POST answer; the leg prints them beside its own state
// fields. A body that cannot be read is NAMED (an unread answer is not "empty").
const wireAnswers = []
page.on('response', (res) => {
  const u = res.url()
  if (!u.includes('/dismiss') && !u.includes('/restore')) return
  const answer = { url: u, status: res.status(), body: '', readError: '', settled: false }
  wireAnswers.push(answer)
  void res.text()
    .then((t) => { answer.body = String(t).slice(0, 400) })
    .catch((e) => { answer.readError = String(e && e.message ? e.message : e).slice(0, 140) })
    .finally(() => { answer.settled = true })
})
// t261031-01: a page reload or a sidebar remount would wipe the prompt state -
// and the notice lives INSIDE the prompt, so that looks exactly like a swallowed
// refusal. Counted, so the receipt can tell the two apart.
const mainFrameNavs = []
page.on('framenavigated', (f) => { try { if (f === page.mainFrame()) mainFrameNavs.push(page.url().slice(0, 120)) } catch { /* page gone */ } })

// Bounded settle for the answer bodies (called on every verdict path, so it may
// not hang the exit). Returns the count and the last answer verbatim.
async function wireAnswerFacts(boundMs = 5000) {
  const started = Date.now()
  while (wireAnswers.some((a) => !a.settled) && Date.now() - started < boundMs) {
    await new Promise(r => setTimeout(r, 50))
  }
  const last = wireAnswers[wireAnswers.length - 1] ?? null
  return {
    count: wireAnswers.length,
    unread: wireAnswers.filter((a) => !a.settled).length,
    last: last === null ? null : {
      status: last.status, body: last.body, readError: last.readError, settled: last.settled,
    },
  }
}
STEP = 'page-load'
try {
  await bench.goto(page, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await dismissNotice(page)   // 出厂 notice 遮罩会截走点击与焦点——先关（t260904-15 面）
} catch (e) {
  await benchEnvFail('page-load', e)
}

// 等左栏长列表渲染出来（目标行存在 = 列表已就位）。行卡入口的真源是
// ticket-row-card.tsx 的 title 锚（failed 行 "Dismiss:…" / 折叠行 "Restore:…"），
// 不绑类名主体（t261008-08 同纪律）。
const FIND_BTN = `
(id, prefix) => {
  const sb = document.querySelector('.wb-sb') || document.body
  const leaves = [...sb.querySelectorAll('*')].filter(el => el.children.length === 0
    && (el.textContent || '').trim() === id)
  for (const leaf of leaves) {
    let w = leaf
    while (w && w !== document.body) {
      const btn = [...w.querySelectorAll('button')].find(b => (b.title || '').startsWith(prefix))
      if (btn) return btn
      w = w.parentElement
    }
  }
  return null
}
`
STEP = 'fixture-list'
const listReady = await waitFor(async () =>
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:') !== null`), 20000)
if (!listReady) {
  // The measured incident (t261030-46): the bench served a page but never the
  // long failed list, and the verdict came back two different ways depending
  // on the path. It is ONE thing - a context that is missing or broken - so it
  // is ONE verdict: a NAMED ENV_FAIL naming the step, what the page shows and
  // what the engine channel saw.
  await benchEnvFail('fixture-list',
    `long failed list never rendered on the isolated bench (boot or fixture face broken):`
    + ` target row ${TARGET} carries no Dismiss control after 20s of polling`
    + ` — ${stubTraceFacts(stub)}`)
}

// S1: 点最后一个 failed 行的 Dismiss —— 理由框必须在视口内（不用人手滚）。
// 修复前该框开在滚动容器尾部 = 折叠线以下，本子用例在旧 bundle 上必红（TDD 信号）。
STEP = 'dismissal'
// S3-pre (t261031-01): establish the refusal BY CONSTRUCTION before the click and
// assert it held. This is the half the 261031 round was missing - it assumed the
// fixture refused, so an ACCEPTED answer and a swallowed refusal produced the
// same receipt. Three legs, each on a public face:
//   S3p1 the fixture still serves the row the person clicks (status/stage, and
//        no dismissal voucher - a voucher would make the row a restore row);
//   S3p2 the engine channel the dismiss route spawns answers that exact
//        dismissal with the named refusal (a real probe, not an assumption);
//   S3p3 the probe really went through the stub and changed nothing (trace row,
//        fixture row byte-identical), so "the channel refuses" is about THIS
//        bench and not about a stale or foreign channel.
const fixtureBefore = fixtureRowFacts(stub)
const servedOk = fixtureBefore.row !== null
  && fixtureBefore.row.project === PROJ && fixtureBefore.row.status === 'failed'
  && fixtureBefore.row.stage_state === 'failed' && fixtureBefore.row.dismissed === false
rec('S3p1 fixture serves the fd-last failed row the person clicks', servedOk,
  `row=${JSON.stringify(fixtureBefore.row)} of ${fixtureBefore.rows} fixture rows`)
const probe = dismissalProbe(stub)
const probeRefused = probe.status === 0 && probe.answer?.ok === false
  && String(probe.answer?.error ?? '').includes(ENGINE_REFUSAL_MARK)
rec('S3p2 engine channel refuses that dismissal by name before the click', probeRefused,
  `probe answer=${JSON.stringify(probe.answer)} exit=${probe.status}`
  + `${probe.parseError ? ` parse=${probe.parseError}` : ''}`
  + `${probe.signal ? ` signal=${probe.signal}` : ''}`
  + `${probe.stderr ? ` stderr=${JSON.stringify(probe.stderr)}` : ''}`)
const fixtureAfterProbe = fixtureRowFacts(stub)
const probeWentThrough = probe.traced.includes(`ticket:dismiss:${TARGET}`)
  && fixtureAfterProbe.digest === fixtureBefore.digest
rec('S3p3 the refusal probe went through the stub and changed nothing', probeWentThrough,
  `probe trace=${JSON.stringify(probe.traced)};`
  + ` fixture row unchanged=${fixtureAfterProbe.digest === fixtureBefore.digest}`)

const prompt = page.locator('[data-wb-dismiss-prompt]')
await page.evaluate(`(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:').click()`)
await prompt.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
const inViewport = await prompt.evaluate((el) => {
  const r = el.getBoundingClientRect()
  return r.height > 0 && r.top >= -2 && r.bottom <= window.innerHeight + 2
    && r.left >= -2 && r.right <= window.innerWidth + 2
}).catch(() => false)
rec('S1 dismiss prompt visible in viewport on a long list', inViewport === true,
  inViewport ? 'prompt rect inside the 1280x800 viewport after the click' : 'prompt opened off-screen (or never appeared)')

// S2: 理由框拿到焦点（人可以直接打字——可见性的一部分）。
const focused = await page.evaluate(() => {
  const el = document.querySelector('[data-wb-dismiss-reason]')
  return el !== null && document.activeElement === el
})
rec('S2 reason box holds focus after opening', focused)

// S3: 线上面 —— 请求带 ?project=，body 只有 who/reason（引擎契约不变），且请求
// 真到达引擎缝（stub trace 出现 ticket:dismiss）。journal 落盘面归 t261009-54。
const traceSizeBefore = stub.traceSizeAt()
await page.locator('[data-wb-dismiss-reason]').click()
await page.keyboard.type('failed ticket, duplicating another lane')
await page.locator('[data-dismiss-confirm]').click()
await waitFor(async () => stub.readTrace().length > traceSizeBefore, 10000)
const post = dismissPosts.find(p => p.url.includes('/dismiss'))
rec('S3a dismiss POST carries ?project= on the wire',
  post !== undefined && post.url.includes(`project=${PROJ}`),
  post ? post.url : 'no dismiss POST observed')
let bodyOk = false
try {
  const b = JSON.parse(post?.body ?? '{}')
  bodyOk = typeof b.who === 'string' && b.who.trim() !== ''
    && typeof b.reason === 'string' && b.reason.trim() !== ''
    && !('project' in b)
} catch { bodyOk = false }
rec('S3b body carries who+reason only (engine contract unchanged)', bodyOk,
  post?.body ?? 'no body')
// Scoped to what arrived AFTER the click (t261031-01): S3p2 already put a
// ticket:dismiss row in the trace from the probe, so a whole-file scan would
// pass even if this click never reached the channel.
const traced = stub.traceSince(traceSizeBefore).some(t => t.op === 'ticket:dismiss' && t.id === TARGET)
rec('S3c request reached the engine channel', traced)
// The answer, printed as soon as it settles (t261031-01): the request side alone
// left the 261031 occurrence undecidable. Bounded settle, never a blind sleep.
const answerAfterClick = await wireAnswerFacts()
console.log(`[note] S3 dismiss answer (status/body): ${JSON.stringify(answerAfterClick)}`)

// S3d: the engine's named refusal must surface VERBATIM on the row's face and
// must never be swallowed. The engine channel refuses this op with a NAMED
// text, so the panel has exactly one lawful rendering: that text, on the
// notice of the ticket whose prompt is open. The wait polls that condition
// (see waitForNotice above); the assertion keeps its old strength (a non-empty
// notice could never pass as "swallowed") and reads the engine's own word, so
// a locally invented message or an emptied refusal cannot pass as the
// engine's refusal either.
const NOTICE_CEILING = noticeCeiling()
console.log(`[note] S3d condition wait: polling ${NOTICE_SELECTOR} on the ${TARGET} row's`
  + ` face every ${NOTICE_POLL_MS}ms, ceiling ${NOTICE_CEILING.ms}ms (wait=${NOTICE_CEILING.provenance})`)
const noticeWait = await waitForNotice(NOTICE_CEILING)
// What the route answered, and what the stub's predicate saw (t261031-01). Always
// read on both verdict paths: the answer is the fact the 261031 receipt lacked.
const answerFacts = await wireAnswerFacts()
const predicateView = stubPredicateView(stub, traceSizeBefore)
// t261031-05: the notice renders INSIDE the prompt, so "the refusal surfaced" and
// "the prompt is still on the face" are ONE claim, and the leg asserts both. A
// refused dismissal that leaves the user with a closed prompt is exactly the
// 261031 incident; it must never pass as "the refusal surfaced" because some
// future edit moved the notice out of the prompt, or lost the prompt while the
// notice survived. The receipt carries promptOpen, so the state is readable
// without a rerun.
const noticeCarriesEngineRefusal = noticeWait.shown && noticeWait.last.text.includes(ENGINE_REFUSAL_MARK)
const promptKeptOpen = noticeWait.last.promptOpen === true
if (noticeCarriesEngineRefusal && promptKeptOpen) {
  rec('S3d refusal surfaces verbatim on the face (never swallowed)', true,
    `the engine refusal attached to the ${TARGET} row's face after ${noticeWait.waitedMs}ms`
    + ` (${noticeWait.rounds} poll rounds; ceiling ${NOTICE_CEILING.ms}ms,`
    + ` wait=${noticeWait.provenance}); notice=${JSON.stringify(noticeWait.last.text.slice(0, 120))}`
    + `; promptOpen=${noticeWait.last.promptOpen}`
    + `; postAnswer=${JSON.stringify(answerFacts)}`
    + `; firstNoticeProbe=${JSON.stringify(noticeWait.firstProbe)}`
    + `; stubPredicate=${JSON.stringify(predicateView)}`)
} else {
  // A working bench that swallowed the refusal IS the product claim this leg
  // guards, so the verdict stays a content red - but the receipt must name
  // what was observed and WHICH condition never held (t261030-46: the
  // historical round booked this leg red and the record carried nothing but
  // the word 'fail'; t261030-50: it must also name the ceiling it waited).
  const diag = await page.evaluate(({ mark, target }) => {
    const notice = document.querySelector('[data-wb-dismiss-notice]')
    const sb = document.querySelector('.wb-sb') || document.body
    const text = String((sb)?.innerText || '').replace(/\s+/g, ' ')
    return {
      promptOpen: document.querySelector('[data-wb-dismiss-prompt]') !== null,
      noticeAttached: notice !== null,
      noticeText: notice ? String(notice.textContent || '').slice(0, 120) : '',
      stubRefusalOnFace: text.includes(mark),
      // t261031-01: the surrounding faces, so "the prompt is gone" is separable
      // from "the row/group is gone" (a vanished group unmounts the prompt slot
      // and with it the notice, which is not the refusal being swallowed).
      promptSlots: document.querySelectorAll('[data-wb-dismiss-prompt]').length,
      projectBlocks: document.querySelectorAll('[data-wb-project-block]').length,
      targetRowOnFace: text.includes(target),
      confirmButtons: document.querySelectorAll('[data-dismiss-confirm]').length,
      sidebarText: text.slice(0, 200),
    }
  }, { mark: ENGINE_REFUSAL_MARK, target: TARGET }).catch((e) => ({ probeError: String(e).slice(0, 140) }))
  const what = noticeWait.shown && noticeWait.last.text.includes(ENGINE_REFUSAL_MARK)
    ? `the notice carried the engine's named refusal but the prompt was GONE`
      + ` (promptOpen=${JSON.stringify(noticeWait.last.promptOpen)};`
      + ` closed after ${JSON.stringify(noticeWait.promptClosedAfterMs)}ms of the wait),`
      + ` so the refusal had no prompt face to be read on - the 261031 shape`
    : noticeWait.shown
    ? `the notice attached but never carried the engine's named refusal`
      + ` (${JSON.stringify(ENGINE_REFUSAL_MARK)}); it read`
      + ` ${JSON.stringify(noticeWait.last.text.slice(0, 120))}`
    : `the engine refusal notice (${NOTICE_SELECTOR} with non-empty text on the`
      + ` ${TARGET} row's face) never attached within the ${noticeWait.ceilingMs}ms`
      + ` ceiling (wait=${noticeWait.provenance}; ${noticeWait.rounds} poll rounds;`
      + ` last probe: attached=${noticeWait.last.attached}`
      + ` text=${JSON.stringify(noticeWait.last.text.slice(0, 60))}`
      + ` error=${JSON.stringify(noticeWait.last.error)})`
  // One state JSON, the same keys on every failing path (t261031-01): the DOM
  // faces, then the ANSWER the route gave, then what the stub's refusal
  // predicate saw, then the wait's own facts. An accepted answer can therefore
  // never read like a refused one, and neither can read like a lost state.
  const state = {
    ...diag,
    promptKeptOpen,
    postAnswer: answerFacts.last,
    postAnswers: answerFacts.count,
    postAnswersUnread: answerFacts.unread,
    promptClosedAfterMs: noticeWait.promptClosedAfterMs,
    firstNoticeProbe: noticeWait.firstProbe,
    noticeRounds: noticeWait.rounds,
    noticeWaitedMs: noticeWait.waitedMs,
    ceilingMs: noticeWait.ceilingMs,
    waitProvenance: noticeWait.provenance,
    mainFrameNavs: mainFrameNavs.slice(-3),
    mainFrameNavCount: mainFrameNavs.length,
    stubPredicate: predicateView,
    pageErrors: pageErrors.slice(-4),
  }
  record('S3d refusal surfaces verbatim on the face (never swallowed)', 'fail',
    `${what}: ${JSON.stringify(state)}`)
}

// ---------------------------------------------------------------- S5 the ACCEPTED direction (t261031-05)
// The legitimate close path must stay exactly what it was: an ACCEPTED dismiss
// closes the prompt and takes the row off the board. Without this leg the case
// owned one direction only, so "the prompt closed" could never be told apart from
// "the prompt was lost" - the hole the 261031 round fell into.
//
// The fixture flips its channel property to the engine's acceptance face
// (ctrl.accept.dismiss: the stub writes the engine's dismissed:{at,who,reason}
// voucher onto the served row and answers ok:true). The person's retry reuses the
// prompt the refusal left open - if it is not open (the refusal leg found it
// lost), the row's own Dismiss control opens it again, so this leg judges the
// ACCEPTED answer and never the previous leg's outcome.
STEP = 'dismissal-accept'
setAcceptKnob(true)
const acceptTraceSize = stub.traceSizeAt()
const answersBeforeAccept = wireAnswers.length
const promptOpenBeforeAccept = await page.evaluate(
  () => document.querySelectorAll('[data-wb-dismiss-prompt]').length > 0).catch(() => false)
if (!promptOpenBeforeAccept) {
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:').click()`)
  await prompt.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
}
await page.locator('[data-wb-dismiss-reason]').click()
await page.keyboard.type('retry: the engine accepts this disposition')
await page.locator('[data-dismiss-confirm]').click()
await waitFor(async () => wireAnswers.length > answersBeforeAccept
  && wireAnswers.slice(answersBeforeAccept).every((a) => a.settled), 20000)
const acceptAnswers = await wireAnswerFacts()
const acceptAnswer = acceptAnswers.last
let acceptOkBody = null
let acceptParseError = ''
try { acceptOkBody = JSON.parse(String(acceptAnswer?.body ?? '')) } catch (e) {
  acceptParseError = String(e && e.message ? e.message : e).slice(0, 140)
}
const acceptFixtureRow = fixtureRowFacts(stub).row
const acceptTraced = stub.traceSince(acceptTraceSize).some((t) => t.op === 'ticket:dismiss' && t.id === TARGET)
rec('S5a the route answered the accepted dismiss with ok:true', acceptAnswer !== null
  && acceptAnswer.status === 200 && acceptOkBody?.ok === true,
  `postAnswer=${JSON.stringify(acceptAnswer)}${acceptParseError ? ` parse=${acceptParseError}` : ''}`
  + `; reachedEngineChannel=${acceptTraced}`
  + `; fixtureRowAfterAccept=${JSON.stringify(acceptFixtureRow)}`)

// The face: the prompt is closed (and its notice with it - a stale refusal left
// on a successful dismissal would be its own lie), and the row left the board
// with the engine's payload as the only reason (the client never flips locally,
// so the row leaving IS the re-read of ticket-list landing). Both are CONDITIONS:
// the prompt closes on the answer, the row leaves one fresh list read later, so
// each is polled with a ceiling instead of read once - a read at the wrong
// instant must never be booked as "the row stayed".
const acceptWaitClosed = await waitFor(async () => await page.evaluate(
  () => document.querySelectorAll('[data-wb-dismiss-prompt]').length === 0), 30000)
const acceptWaitRowGone = await waitFor(async () => {
  const controlGone = await page.evaluate(
    `(${FIND_BTN})(${JSON.stringify(TARGET)}, 'Dismiss:') === null`).catch(() => false)
  const textGone = await page.evaluate(({ target }) => {
    const sb = document.querySelector('.wb-sb') || document.body
    return !String(sb?.innerText || '').includes(target)
  }, { target: TARGET }).catch(() => false)
  return controlGone === true && textGone === true
}, 60000)
const closedState = await page.evaluate(({ target }) => {
  const sb = document.querySelector('.wb-sb') || document.body
  const text = String((sb)?.innerText || '').replace(/\s+/g, ' ')
  return {
    promptSlots: document.querySelectorAll('[data-wb-dismiss-prompt]').length,
    confirmButtons: document.querySelectorAll('[data-dismiss-confirm]').length,
    noticeAttached: document.querySelector('[data-wb-dismiss-notice]') !== null,
    targetRowOnFace: text.includes(target),
    dismissedCounts: [...document.querySelectorAll('[data-wb-dismissed-fold]')]
      .map((f) => [f.getAttribute('data-wb-dismissed-fold'), f.getAttribute('data-dismissed-count')]),
    sidebarText: text.slice(0, 200),
  }
}, { target: TARGET }).catch((e) => ({ probeError: String(e).slice(0, 140) }))
rec('S5b accepted dismiss closes the prompt (no stale refusal notice)', acceptWaitClosed
  && closedState.promptSlots === 0 && closedState.confirmButtons === 0
  && closedState.noticeAttached === false,
  `promptClosedWithinCeiling=${acceptWaitClosed}; state=${JSON.stringify(closedState)}`)
rec('S5c the accepted row leaves the board face (and the project names it dismissed)',
  acceptWaitRowGone === true && closedState.targetRowOnFace !== true
  && (closedState.dismissedCounts || []).some(([k, n]) => k === PROJ && n === '1'),
  `rowLeftWithinCeiling=${acceptWaitRowGone}`
  + `; rowTextGone=${closedState.targetRowOnFace !== true}`
  + `; dismissedFolds=${JSON.stringify(closedState.dismissedCounts)}`
  + `; sidebarText=${JSON.stringify(closedState.sidebarText)}`)

// Leave the face as the next sub-case expects it: the refusal prompt is already
// closed by the accepted dismissal; this only runs when it is still open (the
// refusal leg's prompt), bounded so a missing control never costs a blind 30 s.
const cancelPresent = await page.evaluate(
  () => document.querySelectorAll('[data-dismiss-cancel]').length > 0).catch(() => false)
if (cancelPresent) await page.locator('[data-dismiss-cancel]').click({ timeout: 5000 }).catch(() => {})

// S4: restore 同一可见性规则 —— 打开 dismissed 折叠，点 Restore，理由框仍在视口内。
await page.locator(`[data-wb-dismissed-fold="${PROJ2}"] [data-wb-dismissed-toggle]`).click().catch(() => {})
const restoreReady = await waitFor(async () =>
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(RESTORE_TARGET)}, 'Restore:') !== null`), 8000)
if (!restoreReady) {
  record('S4 restore prompt same visibility rule', 'na',
    `dismissed fold/restore control never rendered on the fixture face — ${await pageDomFacts()}`)
} else {
  await page.evaluate(`(${FIND_BTN})(${JSON.stringify(RESTORE_TARGET)}, 'Restore:').click()`)
  await prompt.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
  const rIn = await prompt.evaluate((el) => {
    const r = el.getBoundingClientRect()
    return r.height > 0 && r.top >= -2 && r.bottom <= window.innerHeight + 2
      && r.left >= -2 && r.right <= window.innerWidth + 2
  }).catch(() => false)
  rec('S4 restore prompt same visibility rule', rIn,
    rIn ? 'restore prompt rect inside the viewport' : 'restore prompt opened off-screen')
}

judged = true
await browser.close()
summarize()
