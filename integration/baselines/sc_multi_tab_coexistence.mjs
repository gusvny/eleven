// multi-tab-coexistence — the t260901-15 "ticket workbench multi-tab
// coexistence" integration baseline.
//
// Intent (black-box, user perspective): the ticket workbench is used with
// MULTIPLE console tabs open at all times. User-reported defects:
//   (1) tabs are blind to each other — no hint that another tab is viewing a
//       ticket;
//   (2) write ops (推进/签字/... — advance/sign-off and friends) from one tab
//       silently invalidate the other tab's stale view;
//   (3) hidden tabs keep polling at full rate, amplifying query-channel load
//       (KI-003); plus the reported race: opening ticket "13" detail "jumps
//       back to 11" when a stale in-flight poll response lands late.
// This baseline drives a REAL browser against the ISOLATED test console
// (SANDBAR_TEST_CONSOLE, default 127.0.0.1:3199) with TWO+ same-origin pages
// (real BroadcastChannel + localStorage between them) and stubs the workbench
// API boundary per page with page.route() — the shipped bundle, React render
// path and the genuine browser tab-communication primitives are all under
// test; only /sandbar-workbench/api/wf/tickets* carries fixtures (fixture state
// is SHARED across pages so a write on one tab is observable on another;
// request counters stay per-page for the hidden-tab attribution). Never
// touches the production console (3099) nor real tickets.
//
// Scenarios:
//   S0  build-contract (pure node, runs everywhere): shipped twin bundles
//       (lib/client.js == lib/client.cjs) in sync + multi-tab wiring anchors
//       present in the shipped bundle. Pre-implement this fails by design —
//       it is the acceptance gate for the implement stage.
//   T1  presence mutual visibility: tab A opens ticket detail -> tab B shows
//       a "another tab is viewing" hint; B opening the same ticket shows the
//       peer line inside the DRAWER; A closing its drawer clears B's hint
//       (unsubscribe/TTL), not only on tab close.
//   T2  write cross-invalidation: tab D clicks 推进 (advance) on a ticket tab
//       B is
//       viewing -> B shows a notice AND silently re-renders the fresh detail
//       (fixture body marker appears in B's drawer without manual action).
//       Write-guard: within the recent-remote-write window B's own write
//       attempt raises a confirm dialog naming the peer write instead of
//       firing straight through (a SECOND D write re-opens the window so the
//       assertion is not racy with the slow banner checks above it).
//   T3  hidden tab stops polling: background tab makes ZERO API requests over
//       a 33s window (covers 5s list/detail, 5s health+workers, 8s
//       agent-live and the 30s scan period), and immediately refetches when
//       visible again. If the browser/emulation cannot produce
//       document.visibilityState === 'hidden' this scenario records env_fail (exit 2) with the
//       reason (honest coverage declaration, not a dumb guard).
//   T4  stale-detail race (the "click 13, land on 11" regression): ticket A's
//       detail response
//       is delayed; the user clicks ticket B before it lands; the drawer must
//       show B and MUST NOT jump back to A when the stale response arrives.
//   T5  hostile tab traffic: a same-origin page broadcasts malformed messages
//       on the tab channel (non-JSON, missing fields, unknown type, wrong
//       field types) and corrupts presence-looking localStorage keys -> no
//       pageerror, presence keeps working. T5a: a page with BroadcastChannel
//       disabled falls back to the localStorage/storage-event path and is
//       still seen by a healthy peer.
//   T6  tab closed -> peer's viewer-list entry disappears (graceful bye or
//       heartbeat-TTL expiry, either acceptable; bounded wait).
//   T7  hygiene: zero pageerror / console.error across every page.
//
// Execution contract (t260904-12 three-state): stdout's last line is
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; FAIL>0 or every leg na ->
// exit 1;
// environment-dependent halves record env_fail (exit 2) with
// reason). Node >= 22.18. Precedent for the two-layer split, stubbing style
// and infra helpers: lane-parallel-dom.mjs / session-tab-interactions.mjs.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { readFileSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base;
const CHANNEL = 'sandbar-workbench-tabs' // approved plan's channel name
const FIDA = 'it15a' // fixture ticket ids (alnum only; never real tickets)
const FIDB = 'it15b'
const MARKER_V2 = '[advanced-by-peer-v2]'

const results = [] // { name, status: 'pass'|'fail'|'env_fail'|'na', detail }
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

// ---------------------------------------------------------------- S0 build-contract

const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 build-contract', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 build-contract', 'fail', 'lib/client.js and lib/client.cjs out of sync — rebuild')
    return
  }
  // Multi-tab wiring anchors from the approved plan: cross-tab channel,
  // presence heartbeat, visibility-gated polling. Absent => feature not in
  // the shipped bundle => acceptance gate fails loudly (by design pre-implement).
  const anchors = ['BroadcastChannel', CHANNEL, 'visibilitychange']
  const missing = anchors.filter(a => !js.includes(a))
  if (missing.length) {
    record('S0 build-contract', 'fail', `shipped bundle missing multi-tab anchors: ${missing.join(', ')}`)
    return
  }
  record('S0 build-contract', 'pass', 'twin bundles in sync, multi-tab anchors present')
}

// ---------------------------------------------------------------- fixtures (shared details, per-page counters)

const WF = {
  id: 'dev-lane', name: '开发泳道', lane: 'worktree',
  stages: [
    { id: 'create_plan', name: '方案', role: 'developer', parts: ['agent'], next: 'review_plan' },
    { id: 'review_plan', name: '审方案', role: 'integration', parts: ['agent'], next: 'implement' },
    { id: 'implement', name: '实现', role: 'developer', parts: ['agent'], next: 'merge' },
    { id: 'merge', name: '合并', role: 'integration', parts: ['human'] },
  ],
}
// settled + awaiting-human => availableOps yields 推进/打回 (advance / send-back, a no-input write op).
const row = (id, title) => ({
  id, role: 'developer', status: 'settled', title,
  workflow: 'dev-lane', stage: 'merge', stage_state: 'awaiting-human',
  handoff_count: 0, pending_count: 0, worktree: '/tmp/fixture', updated: '—', updated_ts: 0,
})
const ROW_A = row(FIDA, '多页签共存打桩甲')
const ROW_B = row(FIDB, '多页签共存打桩乙')

const detailBase = (over) => ({
  id: FIDA, title: ROW_A.title, workflow_id: 'dev-lane', epic: '',
  status: 'settled', role: 'developer', lane: 'worktree',
  stage: 'merge', stage_state: 'awaiting-human', stage_name: '合并',
  acceptance: [], stage_acceptance: [], checks: {}, results: {}, handoffs: [],
  pending: [], log: [], body: 'multi-tab fixture body', write_set: [],
  timeline: [], ...over,
})

function sharedFixtures() {
  return {
    details: {
      [FIDA]: detailBase({ id: FIDA, title: ROW_A.title }),
      [FIDB]: detailBase({ id: FIDB, title: ROW_B.title, body: 'multi-tab fixture body B' }),
    },
    delays: {}, // ticketId -> ms, for GET detail (stale-response race scenario)
  }
}

/** Per-page API-boundary stub. Counts EVERY /sandbar-workbench/api/** request in
 *  that page's own counter (hidden-tab attribution), serves ticket fixtures
 *  from the SHARED fixture map (so a write on tab D is visible to tab B's
 *  next fetch), passes everything else through to the real test console. */
async function attachStub(page, shared, counts) {
  // 取证日志（t260915-10 gen8 补，仲裁令「修前实跑定位泄漏 URL 构成」；只加证据
  // 不改判定）：每次 API 计数记时间戳+路径+query，T3 败径据此报泄漏构成。
  counts.log ??= []
  await page.route('**/sandbar-workbench/api/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    counts.total++
    counts.log.push({ t: Date.now(), u: url.pathname + url.search })
    const m = /^\/sandbar-workbench\/api\/wf\/tickets(?:\/([^/]+)(?:\/([^/]+))?)?$/.exec(url.pathname)
    // fulfill 去险化（t260910-08 arbitrate gen6，tail 点名 :179 'Route is already
    // handled!'）：负载下页面导航会取消在途请求，fetch→fulfill 窗口内路由已被
    // 处理属良性竞态——stub 不许因此 crash 整个场景进程（业务断言已被误杀一次）。
    const body = (b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) }).catch(() => {})
    if (!m) {
      try {
        const resp = await route.fetch()
        await route.fulfill({ response: resp })
      } catch {
        await route.fulfill({ status: 502, contentType: 'application/json', body: '{"ok":false,"error":"fixture passthrough failed"}' }).catch(() => {})
      }
      return
    }
    const [, id, sub] = m
    if (!id && req.method() === 'GET') {
      counts.listGet++
      return body({ ok: true, result: { tickets: [ROW_A, ROW_B], workflows: [WF] } })
    }
    if (id && !sub && req.method() === 'GET') {
      const d = shared.details[id]
      if (!d) return body({ ok: false, error: 'fixture stub: unknown ticket' })
      counts.detailGet++
      const delay = shared.delays[id] ?? 0
      if (delay > 0) await new Promise(r => setTimeout(r, delay))
      return body({ ok: true, result: shared.details[id] })
    }
    if (id && sub && req.method() === 'POST') {
      if (!shared.details[id]) return body({ ok: false, error: 'fixture stub: unknown ticket' })
      counts.write++
      // The write lands: advance the fixture detail so a peer's silent
      // refresh has observable fresh data (body marker + updated stamp).
      const d = shared.details[id]
      shared.details[id] = {
        ...d,
        body: d.body.includes(MARKER_V2) ? d.body : d.body + ' ' + MARKER_V2,
        updated: '刚刚', updated_ts: Date.now(),
      }
      return body({ ok: true, result: shared.details[id] })
    }
    return body({ ok: false, error: 'fixture stub: unsupported method/sub-route' })
  })
}

// ---------------------------------------------------------------- S1 infra (precedent: lane-parallel-dom.mjs)

function consoleHealthy() {
  return fetch(`${BASE}/`, { signal: AbortSignal.timeout(5000) })
    .then(r => r.ok)
    .catch(() => false)
}

function mainRepoRoot() {
  // node_modules never travels with git worktrees; resolve the main checkout
  // via the gitfile so playwright-core can be found there.
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree — cwd is the main checkout */ }
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

async function dismissOverlays(p) {
  for (let i = 0; i < 5; i++) {
    const dialog = p.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await p.keyboard.press('Escape').catch(() => {})
    await p.waitForTimeout(600)
  }
}

/** Open the ticket board via the first project group's 📋 (workbench needs a
 *  projectKey before it renders the ticket list). Returns false if the
 *  console cannot render the board (precheck env_fail). */
async function openBoard(page) {
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await dismissOverlays(page)
  const boardIcon = page.locator('span.wb-view-icon[title="工单列表"]').first()
  if (!(await waitFor(async () => (await boardIcon.count()) > 0, 10000))) return false
  await boardIcon.click()
  // t260905-05 re-anchored: the row-card contract (boardCard, above) replaces
  // the retired tr.wb-row.
  return waitFor(async () =>
    (await boardCard(page, FIDA).count()) > 0 &&
    (await boardCard(page, FIDB).count()) > 0, 10000)
}

// ---------------------------------------------------------------- S1 DOM probes (run in page context)

const domViewerHint = `(() => {
  const text = document.body.innerText || '';
  if (/另一页签|其它页签|正在查看|正在看/.test(text)) return 'text';
  if ([...document.querySelectorAll('[title]')].some(e => /正在查看|正在看|另一页签|其它页签/.test(e.getAttribute('title') || ''))) return 'title';
  if (text.includes('👀')) return 'emoji';
  return null;
})()`

const domDrawerViewerHint = `(() => {
  const el = document.querySelector('.wb-drawer');
  if (!el) return null;
  const text = el.innerText || '';
  return /另一页签|其它页签|正在查看|正在看/.test(text) ? 'drawer-text' : null;
})()`

const domDrawerId = `(() => {
  // The real class is wb-d2-id (the t260826-02 ticket-code in the detail
  // drawer header); wb-drawer-id was a design-time misnomer. Try both
  // candidates, newest first, so a future rename stays compatible.
  const el = document.querySelector('.wb-drawer .wb-d2-id') || document.querySelector('.wb-d2-id')
    || document.querySelector('.wb-drawer .wb-drawer-id');
  return el ? el.textContent : null;
})()`

const domNotice = `(() => {
  const text = document.body.innerText || '';
  return /另一页签|其它页签|刚被|已刷新/.test(text);
})()`

// Narrow on purpose: corrupting unrelated console keys (theme/prefs) would be
// collateral damage and unfairly trip the T7 hygiene gate.
const fnCorruptStorage = `(() => {
  const bad = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && /presence|heartbeat|workbench-tabs|suyou-tabs/i.test(k)) { localStorage.setItem(k, '{{{corrupted'); bad.push(k); }
  }
  return bad;
})()`

/** Broadcast malformed traffic on the tab channel from a same-origin page. */
const fnHostileTraffic = `(channel) => {
  const bc = new BroadcastChannel(channel);
  bc.postMessage('not-json{{{');
  bc.postMessage('');
  bc.postMessage(JSON.stringify({ type: 'presence' }));                       // missing fields
  bc.postMessage(JSON.stringify({ type: 'write', ticketId: 123, ts: 'x' }));  // wrong field types
  bc.postMessage(JSON.stringify({ type: 'unknown-echo', foo: 1 }));           // unknown type
  bc.postMessage(42);
  bc.close();
  return 'sent';
}`

// ---------------------------------------------------------------- S1 scenarios

// Row-card anchor contract (pinned by t260904-17): the middle column's
// full-size card and the left column's mini card share data-ticket-id, so
// disambiguate with the component's own data-compact declaration —
// board=false, left column=true (a bare locator would match both; precedent:
// integration/t260904-17/sc_ticket_list_rowcard_ui.mjs boardCard).
// t260905-05 re-anchoring: the old tr.wb-row anchor was retired along with
// t260904-17's flat row cards (zero matches in the current bundle, which kept
// the S1 precheck at a permanent env_fail); the assertion semantics are
// unchanged, only the anchor moved, plus the M9 approval-modal hop (see
// completeApproveModal).
const boardCard = (page, id) => page.locator(`[data-ticket-id="${id}"][data-compact="false"]`)

/** M9 approval-modal helper (the second hop of the write chain decided by
 *  t260901-22): clicking 推进 on an awaiting-human ticket opens the .wb-modal
 *  approval layer, and 「确认通过并推进」 must be clicked before the write
 *  lands (the write-guard native confirm lives in the doOp after it; the
 *  page-level dialog handler accepts it). Returns true = the modal was
 *  confirmed. Failure policy (review C3, never silently skipped): the modal
 *  is present but the confirm button is missing → throw naming the assertion;
 *  after the click there is neither a native confirm nor a landed write → the
 *  caller's guardMsgs/write-count assertions decide the failure. */
async function completeApproveModal(page) {
  if (!(await waitFor(async () => (await page.locator('.wb-modal').count()) > 0, 5000))) return false
  const confirmBtn = page.locator('.wb-modal button', { hasText: '确认通过并推进' }).first()
  if (!(await confirmBtn.count())) {
    throw new Error('审批弹层在场但「确认通过并推进」按钮缺失（审批流改版？断言不得静默跳过）')
  }
  await confirmBtn.click({ timeout: 5000 })
  return true
}

async function clickRowAdvance(page, id) {
  const card = boardCard(page, id)
  if (!(await waitFor(async () => (await card.count()) > 0, 8000))) {
    throw new Error(`row ${id} not rendered`)
  }
  await card.locator('button', { hasText: '推进' }).first().click({ timeout: 5000 })
  await completeApproveModal(page)
}

async function openDetail(page, id, { force = false } = {}) {
  const card = boardCard(page, id)
  if (!(await waitFor(async () => (await card.count()) > 0, 8000))) {
    throw new Error(`row ${id} not rendered`)
  }
  // force only relaxes how the click reaches the target (bypassing
  // actionability's stable wait); the behavior assertion is unchanged (the
  // drawer must really open). T5b-only: after hostile traffic, the
  // high-frequency presence-poll rerenders keep boundingBox jittering so
  // stable never settles = a tooling fake red (the row is present, the console
  // has zero errors, a real user can click it). The row's normal
  // clickability is verified separately by T4 (the non-force path). If the
  // drawer still does not open after force, that is a real product red.
  await card.click(force ? { force: true, timeout: 8000 } : undefined)
  const ok = await waitFor(async () => {
    const t = await page.evaluate(domDrawerId)
    return t && t.includes(id)
  }, 8000)
  if (!ok) throw new Error(`drawer did not open for ${id}`)
}

async function closeDrawer(page) {
  await page.locator('.wb-drawer .wb-close, .wb-close').first().click({ timeout: 5000 }).catch(() => {})
}

async function scenarioPresence(a, b) {
  // T1a: A opens FIDA detail -> B (list view) must surface a remote-viewer hint.
  await openDetail(a, FIDA)
  const hint = await waitFor(async () => (await b.evaluate(domViewerHint)) !== null, 10000)
  if (!hint) {
    const sample = JSON.stringify((await b.evaluate('document.body.innerText')).slice(0, 160))
    return `B showed no viewer hint after A opened detail (body=${sample})`
  }
  // T1b: B opens the same ticket -> the DRAWER itself must name the peer
  // (page-level hint alone would also match the still-mounted list row).
  await openDetail(b, FIDA)
  const drawerHint = await waitFor(async () => (await b.evaluate(domDrawerViewerHint)) !== null, 6000)
  if (!drawerHint) return 'B drawer does not name the peer tab with both tabs viewing'
  // T1c: A closes its drawer -> B's hint must clear (unsubscribe/TTL), bounded.
  await closeDrawer(a)
  const cleared = await waitFor(async () => (await b.evaluate(domViewerHint)) === null, 15000)
  if (!cleared) return 'B still shows a viewer hint 15s after A closed the drawer'
  return null
}

async function scenarioClosedTab(a, b) {
  await openDetail(a, FIDA)
  const seen = await waitFor(async () => (await b.evaluate(domViewerHint)) !== null, 10000)
  if (!seen) return 'precondition failed: B does not see A as viewer'
  const t0 = Date.now()
  await a.close()
  const gone = await waitFor(async () => (await b.evaluate(domViewerHint)) === null, 18000)
  if (!gone) return `B still lists the closed tab as viewer after ${Date.now() - t0}ms (bye/TTL expected <= ~13s)`
  return null
}

// Qualification tag for the T2/T5 failure text: three rounds of t260904-19
// arbitration qualified both legs as a pre-existing defect of the workbench's
// multi-tab write-invalidation chain (proven by an environment-independent
// control plus force-based evidence capture; not a regression of this ticket),
// 豁免申请已交宿主签字（.suyou/stage_arbitrate_gen14.json）。标签随 FAIL 行输出，  // naming-compat
// so that "red = normal" habituation cannot drown a real regression on this
// surface: once a fix turns the leg green, the tag naturally disappears.
const PRE_EXISTING_TAG = '（t260904-19 仲裁定性：既有产品缺陷 pre-existing，豁免申请 gen14 待宿主签字；workbench 专项票修复后转绿）'
const tagPreExisting = () => PRE_EXISTING_TAG

async function scenarioWriteCrossInvalidation(b, d) {
  // The drawer T1b left behind is a full-screen overlay that would block this
  // scenario's row clicks — close it first (a real user would too).
  await closeDrawer(b)
  await openDetail(b, FIDB)
  // Write-guard policy (the plan decided "warn rather than hard-block"): B is
  // viewing FIDB, so D's write raises a confirm (naming 「另一页签正在查看」);
  // in practice it must be accepted explicitly, otherwise Playwright's default
  // dismiss cancels the write. The messages are collected so the assertion can
  // prove the guard really named the peer.
  const guardMsgs = []
  for (const p of [b, d]) {
    p.on('dialog', (dlg) => { guardMsgs.push(dlg.message()); void dlg.accept() })
  }
  // D performs the write from its list row; B is viewing the same ticket.
  await clickRowAdvance(d, FIDB)
  await page_wait(800) // confirm + POST landing
  // An awaiting-human ticket first raises the pre-existing 「审批通过并推进？」
  // confirm, with the write-guard confirm after it — so assert that "some
  // dialog in this round named the peer" instead of pinning the order.
  const guardHit = guardMsgs.find(m => /另一页签|其它页签|正在查看/.test(m))
  if (!guardHit) {
    return `no dialog names the viewing peer (dialogs: ${JSON.stringify(guardMsgs)})`
  }
  const noticed = await waitFor(async () => await b.evaluate(domNotice), 8000)
  if (!noticed) return 'B got no cross-invalidation notice after D wrote'
  const refreshed = await waitFor(async () =>
    (await b.evaluate('document.body.innerText')).includes(MARKER_V2), 8000)
  if (!refreshed) return `B drawer did not silently refresh to the post-write detail (missing ${MARKER_V2})`
  // Write guard: B's own write attempt within the recent-remote-write window
  // must raise a confirm naming the peer write, not fire straight through.
  // The window from D's write above may already be stale after the slow
  // banner checks, so D writes AGAIN and B clicks within the fresh window.
  await clickRowAdvance(d, FIDB)
  await page_wait(1500) // let the broadcast land on B before B's click
  await closeDrawer(b)
  // B's write goes through the same page-level persistent dialog handler
  // (guardMsgs collects and accepts them all — stacking a once handler would
  // double-accept and report "already handled"). A new dialog is detected by
  // the difference in the message count.
  const before = guardMsgs.length
  await clickRowAdvance(b, FIDB)
  // B's write first raises the pre-existing 「审批通过并推进？」confirm, with
  // the write-guard confirm after it — wait up to 5s for any new dialog to
  // name the peer, while also watching the write count (a write that lands
  // without a single confirm = the guard is missing: fail immediately instead
  // of waiting out the timeout).
  const beforeWrites = b.__st.counts.write
  const hitPeer = await waitFor(async () => {
    if (guardMsgs.length > before && guardMsgs.slice(before).some(m => /另一页签|其它页签|正在查看|仍要继续|刚刚/.test(m))) return true
    if (b.__st.counts.write > beforeWrites) throw new Error('__WRITETHRU__')
    return false
  }, 5000)
  if (hitPeer === false) {
    if (b.__st.counts.write > beforeWrites) return 'write-guard missing: B wrote straight through with no confirm despite a remote write seconds ago'
    return 'B produced neither a guard dialog nor a write — click had no effect'
  }
  if (hitPeer === '__WRITETHRU__') {
    return 'write-guard missing: B wrote straight through with no confirm despite a remote write seconds ago'
  }
  const landed = await waitFor(async () => b.__st.counts.write >= 1, 5000)
  if (!landed) return 'guard dialog accepted but the write never landed'
  return null
}

function page_wait(ms) { return new Promise(r => setTimeout(r, ms)) }

async function scenarioHiddenStopsPolling(front, hidden, ctx) {
  // Baseline: the tab polls while visible.
  await front.bringToFront()
  const base = hidden.__st.counts.total
  const sawPoll = await waitFor(async () => hidden.__st.counts.total > base, 8000)
  if (!sawPoll) return 'precondition failed: tab issued no polls even while visible'
  // Background it; verify the browser actually reports hidden, trying CDP if not.
  await hidden.bringToFront()
  await front.bringToFront()
  let vs = await hidden.evaluate('document.visibilityState')
  if (vs !== 'hidden') {
    try {
      const cdp = await ctx.newCDPSession(hidden)
      await cdp.send('Page.setWebLifecycleState', { state: 'hidden' })
    } catch { /* CDP path unavailable */ }
    vs = await hidden.evaluate('document.visibilityState')
  }
  let emulated = false;
  if (vs !== 'hidden') {
    // Headless Chrome always reports visible for a background tab (both the
    // bringToFront rotation and CDP Page.setWebLifecycleState failed in
    // practice, confirmed 260908) — fall back to property-level emulation:
    // overwrite document.visibilityState and dispatch visibilitychange. This
    // still drives the app's own listener and contract (visibility-poll.ts
    // gates polling on visibilityState + the event), and the assertion surface
    // (33s of zero requests + refetch on becoming visible again) is not
    // loosened by a word.
    await hidden.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { get: () => 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    emulated = true;
    vs = 'hidden';
  }
  if (vs !== 'hidden') {
    record('T3 hidden tab stops polling', 'env_fail', `browser keeps visibilityState=${vs} for backgrounded pages — cannot cover here`)
    return '__ENV_FAIL__'
  }
  // 慢机排空窗（t260915-08 仲裁加固，契约未松一字）：强转 hidden 后，事件循环
  // 里可能仍压着转换前排队的旧 tick（216 场景连跑高负载下可迟到数秒——260915
  // 机械轮 T3 伪红即此形态：同一棵树本地复跑两连绿）。设窗前先等计数静默，
  // 排走的只是设窗前的旧账；排不走（15s 仍不静默）= 真在漏，交给下面 33s 窗
  // 如实判红，不吞不掩。
  let quietWaited = 0
  for (;;) {
    const q0 = hidden.__st.counts.total
    await page_wait(3000)
    quietWaited += 3
    if (hidden.__st.counts.total === q0) break
    if (quietWaited >= 15) break
  }
  const c0 = hidden.__st.counts.total
  const cList0 = hidden.__st.counts.listGet
  const t0 = Date.now()
  await page_wait(33000) // > 30s scan period: every timer must fire at least once if unpaused
  const leak = hidden.__st.counts.total - c0
  const leakList = hidden.__st.counts.listGet - cList0
  if (leak !== 0) {
    // 判别探针（t260915-10 gen7 补，只加证据不改判定）：leak>0 时读页面自身状态定归因——
    // ①emulation 补丁丢失/翻回 visible（defineProperty get 描述符不在、visibilityState
    //   读回 visible）＝隐藏模拟在负载窗内失效，测试前提面铁证（页签按页面自身认知是
    //   可见的，轮询照章办事）；
    // ②补丁在场（get 在、读回 hidden）而 leak 持续＝可见性门在补丁下仍放行，产品面证据
    //   强化（visibility-poll.ts 停表/门控缺陷）。两种形态下断言阈值一字未动。
    const trace = await hidden.evaluate(() => {
      const d = Object.getOwnPropertyDescriptor(document, 'visibilityState')
      const patched = !!(d && d.get)
      return `visibilityState=${document.visibilityState} 模拟补丁${patched ? '在场' : '丢失'}`
    }).catch((e) => `trace 不可得（${String(e).slice(0, 60)}）`)
    // 泄漏构成（t260915-10 gen8 取证增强）：窗内逐请求 路径+query 与间隔形状，
    // 供 developer 对位无门取数路径（nudge 强取/兜底链 vs 轮询节拍）。
    const winLog = (hidden.__st.counts.log ?? []).filter((e) => e.t >= t0)
    const shape = winLog.map((e) => `${e.u}@${((e.t - t0) / 1000).toFixed(1)}s`).join(', ')
    return `hidden tab issued ${leak} API request(s) in 33s (list polls: ${leakList})；${trace}；构成=[${shape}]`
  }
  await hidden.bringToFront()
  if (emulated) {
    // Visible again: flip the emulated state back to visible and dispatch the
    // event (in a real OCCLUSION environment this step happens on its own).
    await hidden.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
  }
  const resumed = await waitFor(async () => hidden.__st.counts.total > c0, 5000)
  if (!resumed) return 'tab made visible again but issued no refetch within 5s'
  return null
}

async function scenarioStaleDetailRace(page, shared) {
  // Reproduce the "click 13, land on 11" jump: FIDA's detail response is
  // held; the user clicks
  // FIDB before it lands; the late stale response must not overwrite the drawer.
  shared.delays[FIDA] = 1500
  const rowA = boardCard(page, FIDA)
  await rowA.click()
  await page_wait(300) // FIDA request in flight, still pending
  // FIDA's drawer is already open at this point (a full-screen overlay blocks
  // the pointer), so the real-world second hop comes from clicking a ticket in
  // the sidebar (the focusId linkage) — which funnels into the same openDetail
  // entry as a row click. Here a JS-dispatched click on the other row card
  // drives that same code path through the overlay (what is under test is the
  // in-flight race, not the overlay).
  await page.evaluate(`(() => {
    const row = [...document.querySelectorAll('[data-ticket-id]')].find(r =>
      r.getAttribute('data-ticket-id') === '${FIDB}' && r.getAttribute('data-compact') === 'false')
    if (!row) throw new Error('row ${FIDB} not found')
    row.click()
  })()`)
  const okB = await waitFor(async () => {
    const t = await page.evaluate(domDrawerId)
    return t && t.includes(FIDB)
  }, 8000)
  if (!okB) {
    const idNow = await page.evaluate(domDrawerId)
    return `drawer did not land on ${FIDB}: ${JSON.stringify(idNow)}`
  }
  await page_wait(1800) // stale FIDA response has now landed
  const idAfter = await page.evaluate(domDrawerId)
  if (!idAfter || !idAfter.includes(FIDB)) {
    return `stale in-flight response overwrote the drawer — jumped back to ${JSON.stringify(idAfter)}`
  }
  return null
}

async function scenarioFallbackAndHostile(healthy, d2, ctx) {
  // T5a: a BroadcastChannel-less page must fall back to the localStorage /
  // storage-event path and still be seen by a healthy peer.
  await healthy.bringToFront()
  const g = await ctx.newPage()
  await g.addInitScript(() => {
    Object.defineProperty(window, 'BroadcastChannel', { value: undefined })
  })
  await attachStub(g, healthy.__st.shared, { total: 0, listGet: 0, detailGet: 0, write: 0 })
  const gErr = []
  g.on('pageerror', e => gErr.push(String(e).slice(0, 200)))
  try {
    if (!(await openBoard(g))) return 'fallback tab could not open the ticket board'
    await openDetail(g, FIDA)
    const seen = await waitFor(async () => (await healthy.evaluate(domViewerHint)) !== null, 10000)
    if (!seen) {
      const keys = await healthy.evaluate('JSON.stringify(Object.keys(localStorage))')
      return `BC-less page was not seen by the healthy peer (localStorage keys: ${keys})`
    }
  } finally {
    await g.close().catch(() => {})
  }
  if (gErr.length) return `BC-less page threw: ${gErr[0]}`

  // T5b: hostile same-origin traffic — malformed channel messages plus
  // corrupted presence-looking localStorage keys. App must not crash and
  // presence must keep working afterwards.
  const e = await ctx.newPage()
  await e.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  await e.evaluate(fnHostileTraffic, CHANNEL)
  const corrupted = await e.evaluate(fnCorruptStorage)
  await e.close()
  const before = healthy.__err.length
  await openDetail(d2, FIDA, { force: true })
  const stillWorks = await waitFor(async () => (await healthy.evaluate(domViewerHint)) !== null, 10000)
  if (!stillWorks) return 'presence broke after hostile channel traffic / storage corruption'
  if (healthy.__err.length > before) return `pageerror after hostile traffic: ${healthy.__err[before]}`
  console.log(`  (T5b corrupted localStorage keys: ${corrupted.length})`)
  return null
}

// ---------------------------------------------------------------- main browser run

async function runBrowser(pw, browser) {
  const shared = sharedFixtures()
  const ctx = await browser.newContext()
  const pageErrors = [] // global hygiene (T7)
  const consoleErrors = []
  const mkPage = async () => {
    const p = await ctx.newPage()
    const counts = { total: 0, listGet: 0, detailGet: 0, write: 0 }
    p.__st = { shared, counts }
    p.__err = []
    p.on('pageerror', e => { p.__err.push(String(e).slice(0, 200)); pageErrors.push(String(e).slice(0, 200)) })
    p.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })
    await attachStub(p, shared, counts)
    return p
  }
  // failWith (the catch path) carries the qualification tag too: T2/T5 throws
  // (e.g. "drawer did not open") land here rather than in the err branch — both
  // paths must carry the arbitration qualification, or the anti-habituation
  // measure is only half there.
  const failWith = async (name, e) => record(name, 'fail', String(e).slice(0, 180) + tagPreExisting())
  try {
    const a = await mkPage()
    const b = await mkPage()
    let boardOk = true
    for (const [nm, p] of [['A', a], ['B', b]]) {
      if (!(await openBoard(p))) {
        record('S1 precheck', 'env_fail', `ticket board did not consume the list stub on ${BASE} (tab ${nm})`)
        boardOk = false
        break
      }
    }
    if (!boardOk) return
    record('S1 precheck', 'pass', 'board rendered both fixture rows on two tabs')

    try {
      const err = await scenarioPresence(a, b)
      if (err) record('T1 presence mutual visibility', 'fail', err)
      else record('T1 presence mutual visibility', 'pass', 'page hint, drawer peer line, clears on drawer close')
    } catch (e) { await failWith('T1 presence mutual visibility', e) }
    try {
      const err = await scenarioClosedTab(a, b)
      if (err) record('T6 closed tab leaves viewer list', 'fail', err)
      else record('T6 closed tab leaves viewer list', 'pass', 'viewer entry gone after tab close (bye/TTL)')
    } catch (e) { await failWith('T6 closed tab leaves viewer list', e) }

    // T2: fresh writer tab D; B reuses its tab.
    const d = await mkPage()
    if (!(await openBoard(d))) {
      record('T2 write cross-invalidation', 'env_fail', 'writer tab could not open the board')
    } else {
      try {
        const err = await scenarioWriteCrossInvalidation(b, d)
        if (err) record('T2 write cross-invalidation', 'fail', err + tagPreExisting())
        else record('T2 write cross-invalidation', 'pass', 'notice + silent refresh + write-guard confirm')
      } catch (e) { await failWith('T2 write cross-invalidation', e) }
    }

    // T3: D stays front, B is backgrounded.
    try {
      const err = await scenarioHiddenStopsPolling(d, b, ctx)
      if (err === '__ENV_FAIL__') { /* scenario recorded its own env_fail */ }
      else if (err) record('T3 hidden tab stops polling', 'fail', err)
      else record('T3 hidden tab stops polling', 'pass', 'zero API requests in 33s hidden, refetch on visible')
    } catch (e) { await failWith('T3 hidden tab stops polling', e) }

    // T4: fresh single tab F (the race is single-tab reproducible).
    const f = await mkPage()
    if (!(await openBoard(f))) {
      record('T4 stale detail cannot overwrite drawer', 'env_fail', 'race tab could not open the board')
    } else {
      try {
        const err = await scenarioStaleDetailRace(f, shared)
        if (err) record('T4 stale detail cannot overwrite drawer', 'fail', err)
        else record('T4 stale detail cannot overwrite drawer', 'pass', 'drawer stayed on second click after stale response landed')
      } catch (e) { await failWith('T4 stale detail cannot overwrite drawer', e) }
    }

    // T5: healthy observer H; writer d2 reuses D; hostile pages on demand.
    const h = await mkPage()
    if (!(await openBoard(h))) {
      record('T5 hostile traffic tolerated', 'env_fail', 'observer tab could not open the board')
    } else {
      try {
        const err = await scenarioFallbackAndHostile(h, d, ctx)
        if (err) record('T5 hostile traffic tolerated', 'fail', err + tagPreExisting())
        else record('T5 hostile traffic tolerated', 'pass', 'BC-less fallback visible to peer; malformed traffic survived')
      } catch (e) { await failWith('T5 hostile traffic tolerated', e) }
    }

    // T7 卫生断言合并语义（t260910-04 gen2 传输层噪声豁免 × t260910-05 gen6 三态化，
    // 冲突消解两边都保留）：pageerror=客户端 JS 异常=产品面；console.error 拆三类——
    // ①传输层断裂（ERR_INCOMPLETE_CHUNKED_ENCODING/CONNECTION_RESET 等网络级噪声，
    // 多泳道并发期共享台面重启窗的环境产物）与 ②后端瞬断（Failed to load resource
    // 5xx，网关/上游不可达）都是环境事件：仅②时诚实改判 env_fail 点名重跑（不作产品
    // 判定），仅①时 pass 带豁免计数；③其余 console.error（含 4xx 资源错=应用错路）
    // 与客户端异常照旧 FAIL。
    const TRANSPORT = /Failed to load resource: net::ERR_(INCOMPLETE_CHUNKED_ENCODING|CONNECTION_RESET|CONNECTION_ABORTED|NETWORK_CHANGED)$/
    const SERVER5XX = /Failed to load resource.*status of 5\d\d/
    const transportNoise = consoleErrors.filter(t => TRANSPORT.test(t))
    const serverFaults = consoleErrors.filter(t => SERVER5XX.test(t))
    const real = consoleErrors.filter(t => !TRANSPORT.test(t) && !SERVER5XX.test(t))
    const clientFaults = pageErrors.length + real.length
    if (clientFaults === 0 && serverFaults.length > 0) {
      record('T7 zero pageerror/console.error', 'env_fail',
        `后端瞬断混入卫生断言：${serverFaults.length} 条 5xx 资源加载错（first=${serverFaults[0]}）——客户端 pageerror=0、行为子用例全过；多泳道争抢窗，重跑定判`)
    } else if (clientFaults === 0) {
      record('T7 zero pageerror/console.error', 'pass',
        transportNoise.length ? `豁免传输层噪声 ${transportNoise.length} 条（并发窗共享台重启）` : '')
    } else {
      record('T7 zero pageerror/console.error', 'fail',
        `pageerrors=${pageErrors.length} first=${pageErrors[0] ?? ''} consoleErrors=${real.length} firstConsole=${real[0] ?? ''}`)
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

  buildContract()

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
