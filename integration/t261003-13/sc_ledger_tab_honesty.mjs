// sc_ledger_tab_honesty.mjs — t261003-13 Ledger 页签诚实性（灰盒 L3，真浏览器 + API 桩，
// 零 docker，红线零接触 3099；架构缝同 t261003-06 sc_executor_panel_page_redesign，
// 复用其 lib_panel_seam.mjs 公共缝——前置/夹具共享复用，非用例级重复）。
//
// Intent（用户可感知行为；工单派发规格三缺陷 + 方案 .sandbar/plan-t261003-13.md 定稿）：
//   H1 Ledger 区块标题不再谎报：只渲染守望者唤醒行时，标题是「Last wakes」，
//      旧标题「Last events」与旧空态文案「The watchdog appends here when a ticket
//      changes.」退场（标题许诺账本事件而展示唤醒 = 本票根缺陷）。
//   H2 空态文案与内容一致：零唤醒时空态明说没有唤醒（方案定稿措辞「No wakes yet」族）。
//   H3 唤醒行展示 mode + accepted（STE 句），硬编码字面量 'sent' 退场——唤醒行本无
//      stage/stage_state 字段，任何回退词把字面量冒充数据 = 缺陷②。
//   H4 畸形唤醒行三态（缺陷②回归电池）：缺 mode / 缺 accepted / 双缺 / accepted 非布尔 /
//      at 非法——显式 unknown 或 —，绝不静默变成句状词；页面零 pageerror。
//   H5 时间诚实（缺陷③）：唤醒时间渲染 == 本机 HH:MM（测试进程同机同 TZ 计算），
//      且 Ledger 与 Alerts 页签都有可见「Times are local.」标签；宿主 TZ 非 UTC 时
//      加一条负形：渲染值 != UTC 切片（TZ=UTC 主机上两形不可分，该负形子用例按系统
//      状态条件 vacuous 通过并点名，不冒充已验）。
//   S1 新文案 STE 抽查：渲染文本零缩略形式、零 40+ 词马拉松句（§4 口径）。
//   X1 全旅程零 pageerror / console error。
//
// 三态纪律（t260904-12）：playwright/chromium 缺席=ENV_FAIL exit 2（KI-036 家族）；
// 页面模块/PANEL_PAGE_HTML 缺席=FAIL 点名（TDD 期红属预期，arbitrate/merge 期必须绿）。
// intent 分工：五页签/布局/请求交互/全面板 STE 抽查归 t261003-06-executor-panel-page-redesign；
// recent-actions 数据面归 t261003-06-executor-panel-recent-actions；本条只锁本票三缺陷
// （标题诚实 / 唤醒行内容 / 时间标签）——三者在既有清单均无 intent 级覆盖。
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
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

// 固定时间戳：锚格式不锚字面——期望值由测试进程同机同 TZ 现算。
const TS = Date.UTC(2026, 9, 3, 11, 50, 0) // 2026-10-03T11:50Z；宿主 TZ 偏移非零时本地读数必异于 UTC 切片
function localHHMM(t) {
  const d = new Date(t)
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}
function utcHHMM(t) { return String(new Date(t).toISOString()).slice(11, 16) }

function stubServer(wakes) {
  return createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes } })
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, rows: [], degraded: false })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [] })
    // t261005-10 UI-2 follow-up: the panel overview now fetches the concurrency
    // read face and lazily fetches the read-only tab faces; an unstubbed fetch
    // 404s and fails the hygiene leg on stub noise, not product. Honest empty /
    // undeclared shapes only (no fabricated facts).
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: 'stub', declared: false, limit: null, unlimited: false, path: '(stub: no declaration)' })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })

    res.writeHead(404); res.end('{}')
  })
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
  // 页签可点：按文本点 tab（Ledger / Alerts）；点不到按失败处理由调用方断言暴露。
  try { await page.click(`text=/^\\s*${name}\\s*$/i`) } catch { try { await page.click(`text=/${name}/i`) } catch { /* noop */ } }
  await page.waitForTimeout(250)
}

async function launchBrowser(pw) {
  try { return await pw.chromium.launch({ headless: true }) } catch (e) {
    // chromium 二进制缺席（KI-036 家族形态）→ 本机稳定版 Chrome 回落（同为真浏览器）；
    // 两者都缺席才算环境红。
    try { return await pw.chromium.launch({ headless: true, channel: 'chrome' }) } catch (e2) {
      throw new Error('browser-launch-unavailable: ' + String(e2).slice(0, 160))
    }
  }
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

  // ---- 第一程：合法唤醒行（mode + accepted 全齐）----
  const good = [
    { at: TS, ticket: 't261002-10', dedupe_key: 'k1', mode: 'queue', accepted: true },
    { at: TS, ticket: 't261003-01', dedupe_key: 'k2', mode: 'queue', accepted: false },
  ]
  let stub = stubServer(good)
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session
  try { session = await openPanel(pw, html, stub) } catch (e) {
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg); return C.exit()
  }
  try {
    const { page, errors } = session
    // Ledger 页签
    await gotoTab(page, 'ledger')
    const ledgerText = await page.evaluate(() => document.body.innerText)
    const lt = ledgerText.toLowerCase()

    // H1 标题诚实：唤醒区块标题=Last wakes；旧标题/旧空态退场
    C.case('H1-heading-says-wakes', lt.includes('last wakes'), `heading "Last wakes" in ledger tab=${lt.includes('last wakes')}`)
    C.case('H1b-old-title-and-copy-gone', !lt.includes('last events') && !ledgerText.includes('appends here when a ticket changes'),
      `old title present=${lt.includes('last events')} old empty copy present=${ledgerText.includes('appends here when a ticket changes')}`)

    // H3 唤醒行内容：mode 与 accepted 进 STE 句；'sent' 不作为行内容出现
    C.case('H3-row-shows-mode', /mode:\s*queue/i.test(ledgerText), 'wake rows carry "Mode: queue."')
    C.case('H3b-row-shows-accepted', /accepted the wake/i.test(ledgerText) && /did not accept the wake/i.test(ledgerText),
      `accepted sentence=${/accepted the wake/i.test(ledgerText)} rejected sentence=${/did not accept the wake/i.test(ledgerText)}`)
    const sentWord = await page.evaluate(() => {
      const els = [...document.querySelectorAll('#ledgerEvents, [id*="ledger" i], [class*="ledger" i]')]
      const scope = els.length ? els.map(e => e.textContent).join('\n') : document.body.innerText
      return /\bsent\b/i.test(scope)
    })
    C.case('H3c-no-sent-fallback-word', !sentWord, `literal "sent" in wake block=${sentWord}`)

    // H5 时间诚实：唤醒行时间 == 本机 HH:MM；「Times are local.」标签可见
    C.case('H5-time-renders-local', ledgerText.includes(localHHMM(TS)), `expected local=${localHHMM(TS)} utc-slice=${utcHHMM(TS)}`)
    C.case('H5b-times-local-label-on-ledger', /times are local/i.test(ledgerText), `caption in ledger tab=${/times are local/i.test(ledgerText)}`)
    const nonUtc = new Date(TS).getTimezoneOffset() !== 0
    if (nonUtc) {
      const utcInText = ledgerText.includes(utcHHMM(TS)) && !ledgerText.includes(localHHMM(TS))
      C.case('H5c-non-utc-host-not-utc-render', !utcInText, 'host TZ≠UTC: rendered time must not read as the UTC slice')
    } else {
      C.case('H5c-non-utc-host-not-utc-render', true, 'host TZ=UTC — local and UTC slices coincide, negative branch vacuous (system-state conditional)')
    }

    // Alerts 页签：同款标签（口径一致）
    await gotoTab(page, 'alerts')
    const alertsText = await page.evaluate(() => document.body.innerText)
    C.case('H5d-times-local-label-on-alerts', /times are local/i.test(alertsText), `caption in alerts tab=${/times are local/i.test(alertsText)}`)

    // S1 新文案 STE 抽查（两页签拼接面）
    const allText = ledgerText + '\n' + alertsText
    const badContraction = /\b(don't|won't|can't|isn't|doesn't|didn't|shouldn't|couldn't|it's|that's|there's)\b/i.test(allText)
    C.case('S1a-no-contractions', !badContraction, `hits=${(allText.match(/\b(don't|won't|can't|it's|that's)\b/gi) || []).join(',')}`)
    const marathon = allText.split(/[.!?\n]/).map(s => s.trim()).filter(s => s.split(/\s+/).length > 40)
    C.case('S1b-no-marathon-sentences', marathon.length === 0, `over-40-word sentences=${marathon.length}`)

    // X1
    C.case('X1-zero-pageerror-good-path', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)
  } finally { await closePanel(session); stub.close() }

  // ---- 第二程：畸形唤醒行电池（缺字段 / 非布尔 / 非对象 / 非法时间）----
  const bad = [
    { at: TS, ticket: 't1', mode: 'queue' },            // 缺 accepted
    { at: TS, ticket: 't2', accepted: false },          // 缺 mode
    { at: TS, ticket: 't3' },                            // 双缺
    { at: TS, ticket: 't4', mode: 'queue', accepted: 'yes' }, // accepted 非布尔
    { at: 'not-a-time', ticket: 't5', mode: 'queue', accepted: true }, // 非法时间
    null,                                                // 非对象行
  ]
  stub = stubServer(bad)
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session2
  try { session2 = await openPanel(pw, html, stub) } catch (e) {
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch-2', msg); return C.exit() }
    C.case('scenario-ran-2', false, msg); return C.exit()
  }
  try {
    const { page, errors } = session2
    await gotoTab(page, 'ledger')
    const ledgerText = await page.evaluate(() => document.body.innerText)
    // H4 畸形行不产生句状词；显式 unknown / — 顶位；'sent' 仍不得出现
    C.case('H4-malformed-no-bare-word', !/\bsent\b/i.test(ledgerText), `literal "sent" under malformed wakes=${/\bsent\b/i.test(ledgerText)}`)
    C.case('H4b-missing-fields-explicit', /unknown/i.test(ledgerText), `explicit "unknown" present=${/unknown/i.test(ledgerText)}`)
    C.case('H4c-bad-time-dash', ledgerText.includes('—'), 'unparseable at renders — (dash), not a wrong clock')
    C.case('H4d-zero-pageerror-malformed', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)
  } finally { await closePanel(session2); stub.close() }

  // ---- 第三程：零唤醒 → 空态与内容一致（H2）----
  stub = stubServer([])
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session3
  try { session3 = await openPanel(pw, html, stub) } catch (e) {
    stub.close()
    C.case('scenario-ran-3', false, String(e).slice(0, 200)); return C.exit()
  }
  try {
    const { page, errors } = session3
    await gotoTab(page, 'ledger')
    const ledgerText = await page.evaluate(() => document.body.innerText)
    C.case('H2-empty-state-honest', /no wakes yet/i.test(ledgerText) && !/no recent events/i.test(ledgerText),
      `wakes empty copy=${/no wakes yet/i.test(ledgerText)} old copy=${/no recent events/i.test(ledgerText)}`)
    C.case('X1b-zero-pageerror-empty', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)
  } finally { await closePanel(session3); stub.close() }

  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
