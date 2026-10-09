// sc_executor_panel_open_session.mjs — t261003-09 缺陷③原锁「恰一个打开会话按钮」；
// t261009-37 host order 261009-(3) 把该面整体退役（deliberate口径 change，非静默
// 松绑）——本场景改锁退役契约（灰盒 L3，真浏览器 + 同源父页 + API 桩，零 docker，
// 红线零接触 3099）。
//
// Intent（用户可感知行为；host order (3)）：
//   W1' 任何形态（嵌入/未声明/独立）都没有 Open session 按钮——退役是全形态的。
//   W2' 页面源里没有 open-session postMessage 发送面（引号字面量零命中；注释不算面）。
//   W4' 会话 chip 仍在场——状态展示不随按钮退役（「chip 即状态显示」）。
//   W5' 独立打开（无父页）没有 STE 提示句——提示路径随按钮一起退场，页面照常渲染。
//   W7 全旅程零 pageerror。
//
// intent 分工：workbench 侧 Executor/Chat 行退场与监听器落在真 console 的面归
// t260929-22-executor-entry-console；本场景只锁面板页内退役面与会话 chip 在场。
// 会话读出源（session chip 同源）由桩注入。
import { PANEL_PAGE_PATH, makeCase, loadPw, REPO } from './lib_panel_stub.mjs'
import { existsSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { pathToFileURL } from 'node:url'

const C = makeCase()
const PROJ = 'alpha'
const MSG = 'sandbar-executor-panel:open-session'
const RESULT = 'sandbar-executor-panel:open-session-result'

/** 同源双路服务：/panel=面板页原文；/parent=含 iframe 的父页（console 同源替身）。 */
async function serveDual(html, grants, parentScript) {
  const server = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const htmlRes = (b) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(b) }
    if (u.pathname === '/panel') return htmlRes(html)
    if (u.pathname === '/parent') return htmlRes(`<!doctype html><html><body>
<iframe id="panel" src="/panel?project=${PROJ}&theme=light" style="width:860px;height:700px;border:0"></iframe>
<script>${parentScript}<\/script></body></html>`)
    // API：面板页同源取数 → 直接在本地服务上桩
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json(grants)
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/watchdog/status') || u.pathname === '/status') return json({ declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x', unreadable: false, counts: { lines: 1, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } } })
    res.writeHead(404); res.end('{}')
  })
  await new Promise(r => server.listen(0, '127.0.0.1', r))
  return { port: server.address().port, close: () => server.close() }
}

const PARENT_LISTENER = `
window.__got = null; window.__replies = [];
window.addEventListener('message', (e) => {
  const d = e.data;
  if (d && d.type === '${MSG}' && typeof d.sessionId === 'string') {
    window.__got = d;
    if (window.__replyMode !== 'garbage') e.source.postMessage({ type: '${RESULT}', ok: true }, '*');
    else e.source.postMessage({ totally: 'unexpected' }, '*');
  }
});`

const GRANTED = { granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: '' }
const UNDECLARED = { granted_count: 0, total: 6, executor_sessions: [], session_state: 'none', note: '' }

async function openParent(pw, base, path) {
  const browser = await pw.chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 900 } })
  const page = await ctx.newPage()
  await page.goto(`${base}${path}`)
  const frame = page.frame({ url: /\/panel/ })
  await page.waitForTimeout(800)
  return { browser, ctx, page, frame: frame ?? page.frames()[1] }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) { C.case('page-module-present', false, PANEL_PAGE_PATH + ' 缺席'); return C.exit() }
  const pw = await loadPw(REPO)
  if (!pw) { C.envFail('playwright-present', 'playwright-core 缺失（KI-036 家族）'); return C.exit() }
  const html = (await import(pathToFileURL(PANEL_PAGE_PATH).href)).PANEL_PAGE_HTML

  const errors = []
  // ---- 嵌入形态（有父页；会话已声明）
  let s1 = await serveDual(html, GRANTED, PARENT_LISTENER)
  let env = null
  try {
    env = await openParent(pw, `http://127.0.0.1:${s1.port}`, '/parent')
    env.page.on('pageerror', e => errors.push(String(e)))
    const frame = env.frame
    await frame.waitForTimeout(400)
    // W1' 嵌入形态：无任何 Open session 按钮（退役是全形态的）。
    const w1 = await frame.evaluate(() => [...document.querySelectorAll('button')].filter(b => /open session/i.test(b.textContent || '')).length)
    C.case('W1-open-session-entry-retired', w1 === 0, `count=${w1}`)
    // W4' 会话 chip 仍是状态显示。
    C.case('W4-session-chip-stays', await frame.evaluate(() => !!document.getElementById('sessionChip')), 'the session chip remains the state display')
  } catch (e) {
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); s1.close(); return C.exit() }
    C.case('W-embedded-leg', false, msg)
  }
  if (env) { await env.browser.close().catch(() => {}) }
  s1.close()

  // W2' 页面源里没有 open-session 消息发送面（引号字面量级；注释不算面）。
  C.case('W2-no-open-session-postMessage-in-source', !/['"]open-session['"]/.test(html),
    'no quoted open-session literal in the served page source (the retired sender cannot come back unnoticed)')

  // ---- 嵌入形态（未声明会话）
  const s2 = await serveDual(html, UNDECLARED, PARENT_LISTENER)
  try {
    const e2 = await openParent(pw, `http://127.0.0.1:${s2.port}`, '/parent')
    const w4 = await e2.frame.evaluate(() => ({
      btns: [...document.querySelectorAll('button')].filter(b => /open session/i.test(b.textContent || '')).length,
      chip: !!document.getElementById('sessionChip'),
    }))
    C.case('W4-undeclared-no-button-chip-stays', w4.btns === 0 && w4.chip, JSON.stringify(w4))
    await e2.browser.close().catch(() => {})
  } catch (e) { C.case('W4-undeclared-no-button-chip-stays', false, String(e).slice(0, 160)) }
  s2.close()

  // ---- 独立形态（无父页；直接开面板页）
  const s3 = await serveDual(html, GRANTED, '')
  try {
    const e3 = await openParent(pw, `http://127.0.0.1:${s3.port}`, '/panel?project=alpha&theme=light')
    const w5 = await e3.page.evaluate(() => {
      const btns = [...document.querySelectorAll('button')].filter(b => /open session/i.test(b.textContent || '')).length
      const txt = document.body.innerText
      return { btns, hint: /open this panel from the console/i.test(txt), chip: !!document.getElementById('sessionChip') }
    })
    // W5' 独立形态：按钮与 STE 提示路径一起退役；页面照常渲染，chip 在场。
    C.case('W5-standalone-retired-no-hint', w5.btns === 0 && !w5.hint && w5.chip, JSON.stringify(w5))
    await e3.browser.close().catch(() => {})
  } catch (e) { C.case('W5-standalone-retired-no-hint', false, String(e).slice(0, 160)) }
  s3.close()

  C.case('W7-zero-pageerror', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
