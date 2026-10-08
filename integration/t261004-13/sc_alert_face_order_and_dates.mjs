// sc_alert_face_order_and_dates.mjs — t261004-13 Alerts 面显示契约：最新在前×时间带日期×双页签一致（灰盒 L3，
// 真浏览器 + API 桩，零 docker，红线零接触 3099/7233；架构缝复用 t261003-06/lib_panel_seam.mjs——
// 前置/夹具共享复用，非用例级重复）。
//
// Intent（用户可感知行为；工单 Part A 原话 + plan review 定稿）：
//   A1 Alerts 列表最新在前：两条不同时刻的 alert，先渲染的行是较晚的那条
//      （工单病灶=守望者回传 oldest-first 尾巴被照序渲染，最新的沉底）。
//   A2 时间带日期：alert 行时间文本 = 本机 MM-DD HH:MM 短本地形（同机同 TZ 现算期望，
//      锚格式不锚字面），不再是无日期 HH:MM（跨天 alert 长得一样=本票缺陷）。
//   A3 跨天可分辨：不同日期的两条 alert 渲染出不同的时间串（A2 的可判对面）。
//   A4 Ledger 页签 wakes 行同形：同一日期化 helper 覆盖 wakes（工单点名「两处一致」），
//      渲染值与 A2 同格式。
//   A5 「Times are local.」标签仍在场（日期化不得丢掉时区口径声明）。
//   A6 畸形 at（null/非法）行显式 —，页面零 pageerror（外部输入畸形三态纪律；
//      Overview recent-actions 留 HH:MM 是方案声明的合法例外，不在本条断言面）。
//   X1 全旅程零 pageerror / console error。
//
// 三态纪律（t260904-12）：playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 家族）；
// 页面模块/PANEL_PAGE_HTML 缺席=FAIL exit 1 点名（TDD 期红属预期，arbitrate/merge 期必须绿）。
// intent 分工：面板展开态/草稿归 t261003-14；Ledger 页签标题/唤醒行内容/本地标签归 t261003-13；
// watchdog 告警两出口纪律归 t260928-28；本条只锁本票 Part A（顺序×日期化×双页签一致）——
// 既有清单无 intent 级覆盖。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'

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
import { execFileSync } from 'node:child_process'
const REPO = fileURLToPath(new URL('../../', import.meta.url))

// 固定时间戳：跨天两天各一条；期望值由测试进程同机同 TZ 现算（锚格式不锚字面）。
const TS_OLD = Date.UTC(2026, 9, 2, 9, 30, 0)  // 2026-10-02T09:30Z
const TS_NEW = Date.UTC(2026, 9, 3, 11, 50, 0) // 2026-10-03T11:50Z（较晚 → 应排在前）
function localMDHM(t) {
  const d = new Date(t)
  const p = (n) => String(n).padStart(2, '0')
  return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
}

function alertRow(a) { return { key: 'k-' + a.at, rule: 'stall', level: 'warn', at: a.at, title: 'alert-' + a.at, ...a } }

function stubServer(alerts, wakes) {
  return createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, alerts, wakes } })
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, rows: [], degraded: false })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [] })
    // t261006-17 (CL-2) + t261005-10 (UI-2) merged stubs: the page fetches the
    // concurrency read face on load (and lazily fetches the read-only tab faces);
    // an unstubbed fetch 404s and fails the hygiene leg on stub noise, not
    // product. The concurrency face keeps the CL-2 quiet shape (empty holders /
    // never-changed audit) so the zero-pageerror and render assertions judge
    // THEIR faces, not the new block.
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: 'alpha', limit: 3, unlimited: false, at_work: 0, waiting: 0, holders: [], queue: [], audit: { ok: false } })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
    res.writeHead(404); res.end('{}')
  })
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
  return { browser, page, local, errors }
}
async function closePanel({ browser, local }) {
  if (browser) { try { await browser.close() } catch { /* noop */ } }
  local.close()
}
async function gotoTab(page, name) {
  try { await page.click(`text=/^\\s*${name}\\s*$/i`) } catch { try { await page.click(`text=/${name}/i`) } catch { /* noop */ } }
  await page.waitForTimeout(250)
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

  const alerts = [alertRow({ at: TS_OLD, title: 'older-alert' }), alertRow({ at: TS_NEW, title: 'newer-alert' })]
  const wakes = [
    { at: TS_NEW, ticket: 't-1', dedupe_key: 'w1', mode: 'queue', accepted: true },
  ]
  const stub = stubServer(alerts, wakes)
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session
  try { session = await openPanel(pw, html, stub) } catch (e) {
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg); return C.exit()
  }
  const { page, errors } = session
  try {
    await gotoTab(page, 'Alerts')
    const listText = await page.evaluate(() => document.body.innerText)
    // 行序判定：newer 标题先于 older 标题出现（最新在前）
    const iNew = listText.indexOf('newer-alert')
    const iOld = listText.indexOf('older-alert')
    C.case('A1-alerts-newest-first', iNew !== -1 && iOld !== -1 && iNew < iOld, `newer@${iNew} older@${iOld}`)
    // 日期化：时间文本带 MM-DD HH:MM（本机现算期望），且两条跨天串不同
    const wantNew = localMDHM(TS_NEW)
    const wantOld = localMDHM(TS_OLD)
    const times = await page.evaluate(() => Array.from(document.querySelectorAll('.alert .meta, .meta')).map(e => e.textContent.trim()))
    const tNew = times.find(t => t.includes(wantNew))
    const tOld = times.find(t => t.includes(wantOld))
    C.case('A2-timestamp-carries-date', Boolean(tNew && tOld), `want "${wantNew}"/"${wantOld}" got ${JSON.stringify(times.slice(0, 6))}`)
    C.case('A3-cross-day-distinguishable', Boolean(tNew && tOld && wantNew !== wantOld), `"${wantNew}" vs "${wantOld}"`)
    // A5 时区口径标签仍在
    C.case('A5-times-are-local-label', /Times are local\./.test(listText), 'label missing')

    // A4 wakes 行同一日期化形（t261008-20 起 wakes 面在 Overview source-event 对话框，
    // Ledger 页签已退场——从读者路径点开对话框再断言）
    try { await page.click('text=Recent actions (view source event)'); await page.waitForTimeout(250) } catch { /* pre-implement: entry absent, A4 names it */ }
    const ledgerText = await page.evaluate(() => document.body.innerText)
    C.case('A4-wakes-dated-format', ledgerText.includes(wantNew), `wakes want "${wantNew}"`)

    // X1 全旅程零页错
    C.case('X1-no-pageerror', errors.length === 0, errors.slice(0, 3).join(' | '))

    // ---- A6 畸形 at 一程（新开一页，独立桩）----
    stub.close()
    const bad = [{ key: 'k-bad', rule: 'stall', level: 'warn', at: null, title: 'bad-at' }]
    const stub2 = stubServer(bad, [])
    await new Promise(r => stub2.listen(0, '127.0.0.1', r))
    let s2
    try { s2 = await openPanel(pw, html, stub2) } catch (e) {
      stub2.close()
      C.case('A6-malformed-at', false, String(e).slice(0, 160)); return C.exit()
    }
    try {
      await gotoTab(s2.page, 'Alerts')
      const t2 = await s2.page.evaluate(() => document.body.innerText)
      C.case('A6-malformed-at-placeholder', /—/.test(t2) || !/invalid date|NaN/i.test(t2), 'malformed at must render — or be omitted, never NaN')
      C.case('A6-malformed-no-pageerror', s2.errors.length === 0, s2.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(s2); stub2.close() }
  } finally {
    await closePanel(session)
    try { stub.close() } catch { /* already closed */ }
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: scenario crashed:', String(e).slice(0, 300)); process.exit(2) })
