// sc_executor_panel_open_session.mjs — t261003-09 缺陷③：顶部行退场，Overview 内
// 恰一个小「打开会话」按钮（灰盒 L3，真浏览器 + 同源父页 + API 桩，零 docker，
// 红线零接触 3099）。
//
// Intent（用户可感知行为；工单派发规格 Defect 3）：
//   W1 Overview 会话条旁恰一个打开会话按钮（无第二个入口、无页签行形状）。
//   W2 已声明会话 → 按钮可用；点击 → 同源父页（console 的替身）收到
//      {type:'...open-session', sessionId:'exec-1'} 消息（打开动作留在 workbench 侧）。
//   W3 父页回执 ok → 按钮旁出现非空回执文案（成功/失败都显式，无静默路）。
//   W4 未声明会话 → 按钮禁用。
//   W5 独立打开（无父页，window.parent===window）→ 按钮禁用 + 一句 STE 说明
//      （提及从 console 打开；零缩略形式）。
//   W6 父页回执畸形（非预期形状）→ 面板不崩、零 pageerror（外部输入三态之畸形态）。
//   W7 全旅程零 pageerror。
//
// intent 分工：workbench 侧 Executor/Chat 行退场与监听器落在真 console 的面归
// t260929-22-executor-entry-console（本票已改写其 E2/E3）；本场景只锁面板页内按钮
// 与同源消息契约（父页=console 同源替身）。会话读出源（session chip 同源）由桩注入。
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
    const w1 = await frame.evaluate(() => {
      const btns = [...document.querySelectorAll('button')].filter(b => /open session/i.test(b.textContent || ''))
      return { count: btns.length, disabled: btns[0] ? btns[0].disabled : null }
    })
    if (w1.count !== 1) C.case('W1-exactly-one-open-session-button', false, `count=${w1.count}`)
    else {
      C.case('W1-exactly-one-open-session-button', true, 'count=1')
      // W2 点击 → 父页收到消息
      await frame.click('button:has-text("Open session")', { timeout: 5000 }).catch(() => {})
      await env.page.waitForTimeout(500)
      const got = await env.page.evaluate(() => window.__got)
      C.case('W2-click-posts-open-session-to-parent', !!got && typeof got.sessionId === 'string' && /open-session/.test(got.type || ''), JSON.stringify(got).slice(0, 160))
      // W3 父页回执 → 按钮旁非空回执文案
      const w3 = await frame.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find(b => /open session/i.test(b.textContent || ''))
        if (!btn) return ''
        const holder = btn.closest('div,section,span,p')?.parentElement || btn.parentElement
        return (holder?.innerText || '').replace(/open session/i, '').trim()
      })
      C.case('W3-parent-result-surfaced', w3.length > 0, `ack="${w3.slice(0, 120)}"`)
    }
    // W6 畸形回执不崩（重新装载父页、换回执模式）
    await env.page.evaluate(() => { window.__replyMode = 'garbage' })
    await frame.click('button:has-text("Open session")', { timeout: 5000 }).catch(() => {})
    await env.page.waitForTimeout(400)
    const alive = await frame.evaluate(() => document.querySelectorAll('button').length > 0)
    C.case('W6-garbage-reply-no-crash', alive, 'panel still interactive after malformed parent reply')
  } catch (e) {
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); s1.close(); return C.exit() }
    C.case('W-embedded-leg', false, msg)
  }
  if (env) { await env.browser.close().catch(() => {}) }
  s1.close()

  // ---- 嵌入形态（未声明会话）
  const s2 = await serveDual(html, UNDECLARED, PARENT_LISTENER)
  try {
    const e2 = await openParent(pw, `http://127.0.0.1:${s2.port}`, '/parent')
    const w4 = await e2.frame.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(b => /open session/i.test(b.textContent || ''))
      return btn ? btn.disabled : null
    })
    C.case('W4-no-session-disabled', w4 === true, `disabled=${w4}`)
    await e2.browser.close().catch(() => {})
  } catch (e) { C.case('W4-no-session-disabled', false, String(e).slice(0, 160)) }
  s2.close()

  // ---- 独立形态（无父页；直接开面板页）
  const s3 = await serveDual(html, GRANTED, '')
  try {
    const e3 = await openParent(pw, `http://127.0.0.1:${s3.port}`, '/panel?project=alpha&theme=light')
    const w5 = await e3.page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(b => /open session/i.test(b.textContent || ''))
      const txt = document.body.innerText
      return { disabled: btn ? btn.disabled : null, hint: /open this panel from the console/i.test(txt), contraction: /\b(don't|won't|can't|it's)\b/i.test(txt) }
    })
    C.case('W5-standalone-disabled-with-STE-hint', w5.disabled === true && w5.hint && !w5.contraction, JSON.stringify(w5))
    await e3.browser.close().catch(() => {})
  } catch (e) { C.case('W5-standalone-disabled-with-STE-hint', false, String(e).slice(0, 160)) }
  s3.close()

  C.case('W7-zero-pageerror', errors.length === 0, `errors=${errors.slice(0, 3).join(' | ').slice(0, 200)}`)
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
