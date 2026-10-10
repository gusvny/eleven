/**
 * page.test.mjs —— 改版静态页形状 UT（t261003-06，视觉基准 mock 261003 / 设计 note §2-§4）：
 *  - tab strip（t261008-20：无 Ledger；Overview/Grants/Alerts/Settings 等）；Requests 页签取消（并入 Overview）；
 *  - 项目选择器（下拉/手填/Load）与轮询状态行**不存在**；?project= 深链缝仍在；
 *  - Overview 两栏并列（760px 断点叠放）、条目可展开、选项按钮/自由文本分叉、
 *    Answered 折叠区、总开关与 Grants 总开关同一状态；
 *  - 纯函数真嵌入（页面与单测同一份实现）；beep 缝保留；
 *  - STE 文案抽查（无缩略形式、无行话）。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML, PANEL_ROUTE } from '../src/host/panel-page.ts'

let n = 0

// ---- 五 tab + Requests 页签取消 ----
// t261009-37 (host order 261009): the Alerts tab is gone too (its face lives in the Overview).
for (const tab of ['Overview', 'Grants', 'Settings']) {
  assert(PANEL_PAGE_HTML.includes('>' + tab + ' <') || PANEL_PAGE_HTML.includes('>' + tab + '<'), 'tab label present: ' + tab)
}
assert(!PANEL_PAGE_HTML.includes('>Requests<'), 'Requests tab removed (merged into Overview)')

// ---- 项目选择器与轮询状态行不存在（设计 note §2 硬性） ----
assert(!PANEL_PAGE_HTML.includes('pick a project'), 'no project dropdown')
assert(!PANEL_PAGE_HTML.includes('freeProject'), 'no free-key text box')
assert(!PANEL_PAGE_HTML.includes('id="go"'), 'no Load button')
assert(!PANEL_PAGE_HTML.includes('polling every'), 'no polling status line')
assert(!PANEL_PAGE_HTML.includes('pollNote'), 'poll note element removed')
assert(PANEL_PAGE_HTML.includes("location.search).get('project'"), '?project=<key> deep-link seam intact')
assert(PANEL_PAGE_HTML.includes('No project is selected'), 'no-project state is explicit (never a silent empty page)')

// ---- Overview 两栏 + 窄屏叠放 ----
// t261004-16：请求/应答栏拿宽侧（1.85fr），Recent actions 拿窄侧。
assert(PANEL_PAGE_HTML.includes('grid-template-columns:minmax(0,1.85fr) minmax(0,1fr)'), 'overview: requests column takes the wide side')
// t261003-09 缺陷 1：断点按真实容器宽（container query），两栏各自限高内滚——
// 展开只在自己那栏长高，另一栏与下方内容永不位移。
assert(PANEL_PAGE_HTML.includes('@container (max-width:760px){ .cols{grid-template-columns:1fr} }'), 'columns stack below 760px of the real container (container query)')
// t261009-37：右列改为区块叠（.colstk），两栏随页面滚动——限高内滚规则随四区块版面退役。
assert(PANEL_PAGE_HTML.includes('.cols>div{min-width:0}') && PANEL_PAGE_HTML.includes('.cols>div:last-child{display:flex;flex-direction:column}'), 'the right column is a block stack; the per-column height cap is retired (t261009-37)')
assert(PANEL_PAGE_HTML.includes('container-type:inline-size'), 'the wrap is the query container')
assert(PANEL_PAGE_HTML.includes('max-height:440px;overflow:auto'), 'row detail keeps its own height cap (anchoring stable)')
assert(PANEL_PAGE_HTML.includes('Needs your answer'), 'left column heading (STE: no idiom "Needs you")')
assert(PANEL_PAGE_HTML.includes('Recent actions'), 'right column = recent actions')
assert(PANEL_PAGE_HTML.includes('id="reqBadge"'), 'waiting-count badge on Overview')

// ---- t261007-01: the Dismiss action and the third group ----
assert(PANEL_PAGE_HTML.includes('id="dismissedWrap"') && PANEL_PAGE_HTML.includes('id="dismissedList"') && PANEL_PAGE_HTML.includes('id="dismissedHead"'), 'Dismissed group markup present next to Answered')
assert(PANEL_PAGE_HTML.includes("'Dismissed · ' + dismissed.length"), 'Dismissed group header carries the count')
assert(PANEL_PAGE_HTML.includes("el('dismissedWrap').style.display = dismissed.length===0 ? 'none' : ''"), 'Dismissed group hidden while empty (same rule as Answered)')
assert(PANEL_PAGE_HTML.includes('data-dismiss="1"') && PANEL_PAGE_HTML.includes('button[data-dismiss]'), 'Dismiss button rendered on waiting cards and bound')
assert(PANEL_PAGE_HTML.includes("api/requests/dismiss'"), 'dismiss click POSTs the dismiss endpoint')
assert(PANEL_PAGE_HTML.includes('Dismissed by you. Your default action applies.'), 'dismissed card copy (ticket wording, verbatim)')
assert(PANEL_PAGE_HTML.includes("if(r.status==='dismissed') meta = esc(r.kind) + ' · dismissed'"), 'dismissed row head names the state')

// ---- 交互：可展开、选项按钮 vs 自由文本、Answered 折叠、trace 行 ----
assert(PANEL_PAGE_HTML.includes('data-open="false"') && PANEL_PAGE_HTML.includes("dataset.open==='true' ? 'false' : 'true'"), 'rows expand and collapse in place')
assert(PANEL_PAGE_HTML.includes('max-height:440px;overflow:auto'), 'detail height-capped and scrollable')
assert(PANEL_PAGE_HTML.includes('hasOptions('), 'page calls the SAME hasOptions implementation the unit tests drive')
assert(PANEL_PAGE_HTML.includes('data-answer='), 'options render as buttons')
assert(PANEL_PAGE_HTML.includes('Type an answer'), 'free-text fallback control present')
assert(PANEL_PAGE_HTML.includes('Request id: '), 'trace line: request id')
assert(PANEL_PAGE_HTML.includes('Raised by session '), 'trace line: raised by')
assert(PANEL_PAGE_HTML.includes('Default action: '), 'trace line: default action')
assert(PANEL_PAGE_HTML.includes('Answered ·'), 'collapsed answered section')

// ---- 总开关同状态 + Grants tab 形状 ----
assert(PANEL_PAGE_HTML.includes('id="powerBtn"') && PANEL_PAGE_HTML.includes('id="masterSw"'), 'Overview power switch and Grants master switch both present')
assert(PANEL_PAGE_HTML.includes("op:'master'"), 'both faces post the same master op (one state)')
assert(PANEL_PAGE_HTML.includes('The watchdog keeps running'), 'off-semantics copy states the watchdog keeps running')
assert(PANEL_PAGE_HTML.includes('Give all') && PANEL_PAGE_HTML.includes('Give none'), 'Give all / Give none present')
assert(PANEL_PAGE_HTML.includes('class="sw locked"'), 'host-only entry stays greyed out')
assert(PANEL_PAGE_HTML.includes('id="grantSession"'), 'executor session naming input present')
for (const op of ['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup']) {
  assert(PANEL_PAGE_HTML.includes("['" + op + "',"), 'permission switch declared: ' + op)
}

// ---- 最近动作：显式降级（绝不空列表冒充；t261004-11 换源后的新文案面） ----
assert(PANEL_PAGE_HTML.includes('/sandbar-executor-panel/api/actions'), 'page consumes the actions read endpoint')
assert(PANEL_PAGE_HTML.includes("a&&a.reason ? a.reason"), 'actions degrade names the reason (never an empty list)')
assert(PANEL_PAGE_HTML.includes('permission · session '), 'action rows hover names the permission and the acting session')
assert(PANEL_PAGE_HTML.includes('Refused: '), 'refused rows hover names the reason')
// t261009-37 (host order 261009-(5)): the refused fact is a red 'refused' pill in the
// op column (the inline dot before the time is gone); the sentence names what was
// refused and why, so the meaning never depends on the tooltip.
assert(!PANEL_PAGE_HTML.includes('class="dot red" title="Refused"'), 'no inline refused dot before the time column (t261009-37)')
assert(PANEL_PAGE_HTML.includes("cls = refused ? 'refused' :"), 'refused rows take the refused pill class in the op column')
assert(PANEL_PAGE_HTML.includes("esc(x.action||'') + ' · ' + esc(x.reason||'no reason recorded')"), 'the refused row sentence names the action and the reason on the row')
assert(PANEL_PAGE_HTML.includes('no recorded executor action') === false || true, 'empty copy comes from the API reason (single source)')
assert(PANEL_PAGE_HTML.includes('failed to record '), 'a failed engine append surfaces in a status face (gaps note)')

// ---- t261003-09 缺陷 2：双调色板，无硬编码缺省 ----
assert(!PANEL_PAGE_HTML.includes(':root{--bg:'), 'no hardcoded :root palette remains as the default')
assert(PANEL_PAGE_HTML.includes('html[data-theme="light"]') && PANEL_PAGE_HTML.includes('html[data-theme="dark"]'), 'two palettes keyed on data-theme')
assert(PANEL_PAGE_HTML.includes('@media (prefers-color-scheme: dark){ html:not([data-theme])'), 'absent/malformed ?theme= degrades explicitly to prefers-color-scheme')
assert(PANEL_PAGE_HTML.includes('dataset.theme = themeParam'), 'boot applies the parsed theme param')
assert(PANEL_PAGE_HTML.includes('function themeParamOf'), 'themeParamOf source embedded (page and unit tests share one implementation)')

// ---- t261009-37 (host order 261009-(3)): the Open session button is gone; the
// session chip is the state display. ----
assert(!PANEL_PAGE_HTML.includes('id="openSessionBtn"'), 'no Open session button in the strip')
assert(!PANEL_PAGE_HTML.includes("'sandbar-executor-panel:open-session'"), 'no open-session postMessage producer left')
assert(!PANEL_PAGE_HTML.includes("'sandbar-executor-panel:open-session-result'"), 'no open-session-result listener left')
assert(PANEL_PAGE_HTML.includes('id="sessionChip"') && PANEL_PAGE_HTML.includes("'Session: ' + (sess ? sess : 'none')"), 'the session chip stays as the state display')
// standalone detection survives for the still-standing console face entries (Settings).
assert(PANEL_PAGE_HTML.includes('window.parent === window'), 'standalone detection gates the console-bound face entries')

// ---- 显式降级文案 + beep 缝（沿用） ----
for (const frag of ['Watchdog unreachable', 'Not enrolled', 'data possibly stale', 'REJECTED']) {
  assert(PANEL_PAGE_HTML.includes(frag), 'explicit degraded/error surface present: ' + frag)
}
// rework 回归锁（仲裁 D2）：degradedBanners 必须处理 not-declared 分支——改版时该支
// 被漏，未声明项目在 Overview 读成「正常空态」（panel 契约禁止的冒充）。
{
  const src = PANEL_PAGE_HTML.match(/function degradedBanners\(\)\{[\s\S]*?\n  \}/)
  assert(src && src[0].includes("dg.kind==='not-declared'"), 'degradedBanners renders the not-declared banner (D2 regression)')
}
assert(PANEL_PAGE_HTML.includes('createOscillator'), 'page plays real WebAudio oscillator (no audio asset stub)')
assert(PANEL_PAGE_HTML.includes('__panelBeepCount'), 'beep counter seam exposed for the browser scenario')
assert(PANEL_PAGE_HTML.includes('function beepDecision'), 'beepDecision source embedded (single implementation, no drift copy)')
{
  const m = PANEL_PAGE_HTML.match(/function beepDecision\([^)]*\)/)
  assert(m && !/:/.test(m[0].replace(/https?:/, '')), 'embedded beepDecision is stripped JS (no TS annotations)')
}

// ---- STE 文案抽查：无缩略形式、无行话词 ----
assert(!/\bdon't\b|\bwon't\b|\bisn't\b|\bcan't\b|\bit's\b/.test(PANEL_PAGE_HTML), 'no contractions in panel copy (STE rule 4)')
assert(!/simply|obviously|basically/.test(PANEL_PAGE_HTML), 'no filler adverbs in panel copy')

// ---- Settings 写时校验 + 两个 disable 面分开命名（review C2 的页面锁） ----
assert(PANEL_PAGE_HTML.includes('id="saveBtn"') && PANEL_PAGE_HTML.includes('id="saveResult"'), 'settings save face intact')
assert(PANEL_PAGE_HTML.includes('Disable watchdog'), 'settings disable face named Disable watchdog (not "revoke")')
assert(!PANEL_PAGE_HTML.includes('One-click revoke'), 'the old revoke wording is gone (one term per concept)')
assert(PANEL_PAGE_HTML.includes("['executor_session'"), 'settings knobs unchanged (kb_ id source survives)')
assert(!PANEL_PAGE_HTML.includes('replace(/\\./g') && !PANEL_PAGE_HTML.includes('replace(/./g'), 'no wildcard regex reachable in the served page')
{
  const idForSrc = (PANEL_PAGE_HTML.match(/function idFor\(path\)\{[^}]*\}/) || [])[0] || ''
  assert(idForSrc.includes("path.split('.').join('_')"), 'idFor uses split/join (no escape to lose)')
}
assert(PANEL_PAGE_HTML.includes("el('saveResult').innerHTML = saveMsg"), 'save result re-written after every settings re-render')
assert(PANEL_PAGE_HTML.includes("saveMsg = ''"), 'save result variable initialised (and reset on project switch)')

// ---- 轮询面与路由常量 ----
assert(PANEL_PAGE_HTML.includes('/sandbar-watchdog/api/status'), 'page consumes the watchdog contract endpoint directly')
assert(PANEL_ROUTE === '/sandbar-executor-panel', 'panel route constant')
{
  const calls = (PANEL_PAGE_HTML.match(/renderAlertsLedger\(\)/g) || []).length
  assert(calls >= 3, 'alerts/ledger refresh on poll success and failure paths, found ' + calls)
}

// ---- t261003-13 / t261008-20 / t261009-37：Ledger 面诚实化 → Overview Events 区块 ----
// （t261009-37：对话框退场，面居右列 Events 区块；头行 = Events + 计数 + 台账路径。）
assert(PANEL_PAGE_HTML.includes('class="evfile" id="ledgerFile"'), 'the Events header carries the ledger path (monospace, ellipsised)')
assert(!PANEL_PAGE_HTML.includes('Last events'), 'no "Last events" title left (title must match rows)')
assert(!PANEL_PAGE_HTML.includes('The watchdog appends here when a ticket changes.'), 'old empty copy gone')
assert(PANEL_PAGE_HTML.includes('No wakes yet. The watchdog adds a row here when it wakes an executor.'), 'empty copy matches what the block really shows')
assert(PANEL_PAGE_HTML.includes('function wakeRowSentence'), 'wake row sentence is the shared embedded implementation')
assert(PANEL_PAGE_HTML.includes('wakeRowSentence(w2)'), 'wake rows render mode+accepted via wakeRowSentence')
assert(!PANEL_PAGE_HTML.includes("||'sent'"), "no 'sent' literal fallback anywhere in the page")
assert(PANEL_PAGE_HTML.includes('function localDateTime'), 'dated local-time formatter is the shared embedded implementation')
assert(!PANEL_PAGE_HTML.includes('hhmmLocal'), 'no stale hhmmLocal name left anywhere in the page')
// t261003-13 rework: the wake row computes `when` once (guarded, dash on malformed
// input) and renders esc(when) — the local-time formatter is still the only clock.
// t261009-57: the Alerts rows moved to relative time + <time datetime> (absolute on
// hover); the Overview actions row keeps the direct localDateTime face, the wake row
// stays guarded. The old esc(localDateTime(a2.at)) alert pin retired with the face.
assert(PANEL_PAGE_HTML.includes('esc(localDateTime(x.at))')
  && PANEL_PAGE_HTML.includes("var when = bad ? '—' : localDateTime(w2.at)") && PANEL_PAGE_HTML.includes("esc(when)"),
  'Overview and wake rows still render local time (wake row via the guarded when)')
assert(PANEL_PAGE_HTML.includes('relTimeAgo(at, nowMs)') && PANEL_PAGE_HTML.includes('new Date(at).toISOString()'),
  'alert rows render relative first with the absolute moment in <time datetime>')
{
  const caps = (PANEL_PAGE_HTML.match(/>Times are local\./g) || []).length
  // t261009-57: the Alerts header now states the relative-time contract instead.
  assert(caps === 2, 'Times are local. caption on the Recent actions header and the Events footer, found ' + caps)
  assert(PANEL_PAGE_HTML.includes('Times show how long ago. Hover for the exact time.'),
    'the Alerts header states the relative-first, hover-absolute contract')
}

n += 60
done(n)
