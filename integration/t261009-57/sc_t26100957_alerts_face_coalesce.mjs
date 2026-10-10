// sc_t26100957_alerts_face_coalesce.mjs — t261009-57 Alerts 面改版契约：默认 8 条可调×
// 同因合并 xN×相对时间优先 hover 绝对×全文可读×级别词保留（灰盒 L3，真浏览器 + API 桩，
// 零 docker，红线零接触 3099/7233；缝复用 t261003-06/lib_panel_seam.mjs——前置共享，非用例重复）。
//
// Intent（用户可感知行为；工单正文 261010 宿主令 + 派发规格 (1)-(5)）：
//   D1 默认 8 条：桩不声明 display_max 时，12 个不同条件的 payload 恰渲染 8 个合并行
//      （工单病灶=硬编码 50 条刷屏），且头部诚实标注截断（8 of 12 形）。
//   D2 旋钮可调不重启生效：settings 面声明 display_max=2 → 恰 2 行；=0 → 全部行
//      （0=show all 哨兵），同一桩只改声明值。
//   M1 同因合并：同 key 连续 10 拍 → 恰 1 行带 x10（不是 10 行）。
//   M2 清零重燃不跨合并：A×3、B×1、A×4 → 三行，A 的两段各自 x3/x4（不并成 A x7）。
//   M3 xN=1 不显示徽标；合并行同时可读 first/last 两个相对时间。
//   T1 相对时间优先：行时间文本 = "Nm ago / just now" 形，可见文本不含 MM-DD HH:MM
//      绝对形；绝对时刻在 hover（title 属性含本机绝对形）且 <time datetime> 在场。
//   R1 全文可读：超长标题全文出现在可见文本（wrap 或展开，工单病灶=nowrap+ellipsis
//      无处可读），且行 title 属性带全文。
//   L1 级别词可读：redline 与 warn 行各带级别词；night_muted 行带 night-muted 标记
//      （夜间消音语义不丢）。
//   W1 畸形行纪律：null at / 缺 key 行渲染显式降级（— 或原样单行），零 NaN、零页错。
//   A1 台账只读：整个旅程对 watchdog API 只发 GET（呈现层改动绝不写账/代签）。
//   X1 全旅程零 pageerror / console error。
//
// 三态纪律（t260904-12）：playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 家族）；
// 页面模块 / PANEL_PAGE_HTML 缺席=FAIL exit 1 点名（TDD 期红属预期，arbitrate/merge 期必须绿）。
// intent 分工（防 intent 级重复，已核对在册清单）：alerts 最新在前×时间带日期（t261004-13）
// 与列表契约渲染序（t261004-14）已有在册面，本条不重锁顺序与日期化；告警两出口/去重重播
// 纪律归 t260928-28；面板 payload 键集归 t260928-28-watchdog-status-surface。本条独占：
// display_max 旋钮语义（默认 8/可调/0 哨兵/合并行计数）、xN 同因合并与清零边界、相对时间
// 优先 hover 绝对、全文可读、级别词、台账只读。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const PROJ = 'alpha'
const MIN = 60_000
const NOW = Date.now() // fixtures ride the real clock: relTimeAgo judges against Date.now() at render — a fixed future stamp makes every honest row render the dash and the T1/M3 faces never exercise

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

function row(key, at, opts = {}) {
  return { key, rule: opts.rule || 'stall', target: 'p1', level: opts.level || 'warn', at, title: opts.title || key, ...(opts.night ? { night_muted: true } : {}) }
}

// display_max 的权威读面=status payload 的 alerts_display_max（与行同源不可漂移，
// 实现定稿面）；settings 面同时声明（宿主旋钮面）。判定锚「声明值生效」这一契约。
function stubServer(alerts, displayMax) {
  let nonGet = 0
  const server = createServer((req, res) => {
    if (req.method !== 'GET') nonGet++
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    const cfg = { enabled: true }
    if (displayMax !== undefined) { cfg.alerts = { display_max: displayMax }; cfg['alerts.display_max'] = displayMax }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      const payload = { declared: true, enabled: true, heartbeat: { alive: true }, liveness: { executor: { alive: true } }, alerts, wakes: [] }
      if (displayMax !== undefined) payload.alerts_display_max = displayMax
      return json({ ok: true, result: payload })
    }
    if (u.pathname.endsWith('/api/settings')) return json({ config: cfg, provenance: {} })
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, rows: [], degraded: false })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: PROJ, limit: 3, unlimited: false, at_work: 0, waiting: 0, holders: [], queue: [], audit: { ok: false } })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
    res.writeHead(404); res.end('{}')
  })
  server.nonGetCount = () => nonGet
  return server
}

async function launchBrowser(pw) {
  try { return await pw.chromium.launch({ headless: true }) } catch (e) {
    try { return await pw.chromium.launch({ headless: true, channel: 'chrome' }) } catch (e2) {
      throw new Error('browser-launch-unavailable: ' + String(e2).slice(0, 160))
    }
  }
}

async function openPanel(pw, html, stub) {
  const port = stub.address().port
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port
  const browser = await launchBrowser(pw)
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
  await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
  await page.waitForTimeout(600)
  return { browser, page, local, errors, stub }
}

async function closePanel(s) {
  if (s.browser) { try { await s.browser.close() } catch { /* noop */ } }
  s.local.close()
}

async function withSession(pw, html, alerts, displayMax, fn) {
  const stub = stubServer(alerts, displayMax)
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let s
  try { s = await openPanel(pw, html, stub) } catch (e) {
    stub.close(); throw e
  }
  try { await fn(s); return { nonGet: stub.nonGetCount() } } finally { await closePanel(s); stub.close() }
}

async function alertsFaceText(page) {
  try { await page.click('text=/^\\s*Alerts\\s*$/i') } catch { try { await page.click('text=Alerts') } catch { /* noop */ } }
  await page.waitForTimeout(250)
  return page.evaluate(() => document.body.innerText)
}

// 合并行计数：按本票合并语义，同 key 只出现一次；数「独立条件标题」在可见文本中的
// 行数（每个 cond-XX 标题计 1，xN 徽标不影响计数）。
function countDistinctTitles(text, titles) {
  return titles.filter(t => text.includes(t)).length
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts 缺席')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts 缺具名导出 PANEL_PAGE_HTML（缝契约；TDD 期红属预期）')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }
  const html = pageMod.PANEL_PAGE_HTML

  // ---- Leg 1：12 个不同条件，不声明 display_max → 默认 8 条 + 截断诚实标注 ----
  const twelve = Array.from({ length: 12 }, (_, i) => row(`cond-${String(i + 1).padStart(2, '0')}`, NOW - (i + 1) * 3 * MIN, { title: `condition-${String(i + 1).padStart(2, '0')}` }))
  const allTitles = Array.from({ length: 12 }, (_, i) => `condition-${String(i + 1).padStart(2, '0')}`)
  try {
    await withSession(pw, html, twelve, undefined, async (s) => {
      const text = await alertsFaceText(s.page)
      const shown = countDistinctTitles(text, allTitles)
      C.case('D1-default-8-coalesced-rows', shown === 8, `default leg shows ${shown} distinct conditions, want 8 (payload had 12)`)
      C.case('D1-truncation-honest-header', /8\s*of\s*12|12\s*conditions/i.test(text), `header must state the deeper window; got: ${(text.match(/.{0,40}conditions.{0,20}/i) || ['(none)'])[0]}`)
    })

    // ---- Leg 2：display_max=2 → 恰 2 行（旋钮即时生效）----
    await withSession(pw, html, twelve, 2, async (s) => {
      const text = await alertsFaceText(s.page)
      const shown = countDistinctTitles(text, allTitles)
      C.case('D2-knob-2-shows-2', shown === 2, `display_max=2 leg shows ${shown}, want 2`)
    })

    // ---- Leg 3：display_max=0 → 全部行（0=show all 哨兵）----
    await withSession(pw, html, twelve, 0, async (s) => {
      const text = await alertsFaceText(s.page)
      const shown = countDistinctTitles(text, allTitles)
      C.case('D2-zero-shows-all', shown === 12, `display_max=0 leg shows ${shown}, want all 12`)
    })

    // ---- Leg 4：合并 + 相对时间 + 全文 + 级别 + 台账只读 ----
    const longTail = '.executor 在等自己 spawning after park because the waiting_on_host deadline elapsed and the reconcile pass could not observe the queue mirror (window ' + 'x'.repeat(160) + ' end-of-title)'
    const merged = []
    for (let i = 0; i < 10; i++) merged.push(row('k-1', NOW - 60 * MIN + i * 10 * MIN, { title: 'book-unreadable' }))                       // A 连续 10 拍
    merged.push(row('k-2', NOW - 5 * MIN, { title: longTail, level: 'redline' }))                                                            // 清零边界：B 插入
    for (let i = 0; i < 4; i++) merged.push(row('k-1', NOW - 4 * MIN + i * MIN, { title: 'book-unreadable' }))                               // A 重燃 4 拍
    merged.push(row('k-3', NOW - 2 * MIN, { title: 'night-quiet', level: 'warn', night: true }))                                             // 夜间消音行
    merged.push({ key: 'k-bad', rule: 'stall', target: 'p1', level: 'warn', at: null, title: 'bad-at-row' })                                  // 畸形 at
    merged.push({ rule: 'stall', target: 'p1', level: 'warn', at: NOW - MIN, title: 'no-key-row' })                                           // 缺 key
    const leg4 = await withSession(pw, html, merged, undefined, async (s) => {
      const page = s.page
      const text = await alertsFaceText(page)
      // M1: book-unreadable 恰一行且带 x10（A 两段共 x10? 不——10+4 分两段：x10 与 x4）
      const marks = (text.match(/book-unreadable/g) || []).length
      C.case('M1-same-key-coalesced-to-one-row-per-run', marks === 2, `book-unreadable appears ${marks} times, want 2 (run x10 + refire x4, not 14 rows)`)
      C.case('M1-x10-badge', /x10\b/.test(text), 'x10 badge missing')
      C.case('M2-refire-kept-separate-x4', /x4\b/.test(text), 'refire run x4 badge missing (must not merge across the cleared period into x14)')
      C.case('M3-no-badge-at-count-1', !/x1\b/.test(text), 'x1 badge must be omitted at count 1')
      // M3: first/last 双相对时间
      C.case('M3-first-and-last-relative', /first\s+\S.*ago/i.test(text) && /last\s+\S.*ago/i.test(text), 'coalesced row must read first/last as relative times')
      // T1: 相对时间优先，绝对形只活在 hover
      C.case('T1-relative-time-first', /\b(just now|\d+\s*[smhd]\s+ago)\b/i.test(text), 'no relative "ago" wording found')
      C.case('T1-absolute-not-visible', !/\d{2}-\d{2} \d{2}:\d{2}/.test(text), 'absolute MM-DD HH:MM leaked into visible text (must be hover-only)')
      const timeEls = await page.evaluate(() => Array.from(document.querySelectorAll('time[datetime]')).map(e => ({ dt: e.getAttribute('datetime'), title: e.closest('[title]') ? e.closest('[title]').getAttribute('title') : (e.getAttribute('title') || '') })))
      C.case('T1-time-datetime-present', timeEls.length >= 2, `want >=2 <time datetime>, got ${timeEls.length}`)
      C.case('T1-absolute-on-hover', timeEls.some(e => /\d{1,2}:\d{2}/.test(e.title)), 'no hover title carries an absolute local time')
      // R1: 全文可读（长标题全文在可见文本 + 行 title 带全文）
      C.case('R1-full-text-visible', text.includes(longTail), 'long title truncated with no way to read the rest (ellipsis defect persists)')
      const titleAttrs = await page.evaluate(() => Array.from(document.querySelectorAll('[title]')).map(e => e.getAttribute('title')))
      C.case('R1-full-text-on-hover', titleAttrs.some(t => t.includes('end-of-title')), 'row title attribute does not carry the full text')
      // L1: 级别词 + 夜间消音
      C.case('L1-redline-word', /\bredline\b/i.test(text), 'no "redline" level word on the redline row')
      C.case('L1-warn-word', /\bwarn\b/i.test(text), 'no "warn" level word on warn rows')
      C.case('L1-night-muted-kept', /night-muted/i.test(text), 'night-muted marker lost')
      // W1: 畸形行降级，零 NaN
      C.case('W1-malformed-rows-degrade', /bad-at-row/.test(text) && !/NaN|Invalid Date/i.test(text), 'malformed rows must degrade honestly, never NaN')
      C.case('W1-malformed-no-pageerror', s.errors.length === 0, s.errors.slice(0, 3).join(' | '))
    }).catch((e) => { throw e })

    // A1 台账只读（真计数）：整个合并旅程对 watchdog API 的非 GET 请求必须为 0
    // ——呈现层改动绝不写账/代签（规格 4「ledger keeps every row」的页面侧）。
    C.case('A1-ledger-read-only-journey', leg4 && leg4.nonGet === 0, `non-GET requests during the coalesce journey: ${leg4 ? leg4.nonGet : 'leg failed'}`)
  } catch (e) {
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg); return C.exit()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: scenario crashed:', String(e).slice(0, 300)); process.exit(2) })
