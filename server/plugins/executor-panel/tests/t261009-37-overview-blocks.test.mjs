/**
 * t261009-37-overview-blocks.test.mjs —— host order 261009 静态面 UT（纯 node，零 DOM/网络/3099）：
 *  - Alerts 页签退场，面居 Overview Alerts 区块（头行 = Alerts + 计数 + 'Times are local.'，
 *    体 = night-muted 横幅 + 告警行不变）；
 *  - source-event 入口与对话框退场，面居 Events 区块（头行 = Events + 计数 + 台账路径
 *    evfile，体 = 单行 health facts + wakes 行 + 窗口 footer + Show all 陈述位）；
 *  - Open session 按钮及其 postMessage 全链路退场（会话 chip 保留）；
 *  - 右列四区块定序：Concurrent limit / Alerts / Recent actions / Events，同款 .blk
 *    边框 + 计数入头行（'Running tickets' 不得回魂）；
 *  - refused 行：op 列红 refused 药丸 + 句子点名动作与原因；行列定宽（不靠 tooltip）；
 *  - 项目色：3px 顶栏 --proj，与徽章同源 projectIdentity（无第二哈希、无手挑色），
 *    灰默认 :root 在案（未解析项目 = 灰条，显式降级）；
 *  - 畸形输入面：wakes 非对象行守卫原样保留（诚实降级不回退）。
 * 畸形输入锚点按 house rule 内置（桩=页面源码常量，无外部源）。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'

let n = 0
const H = PANEL_PAGE_HTML

// ---- 1. Alerts tab out, face in ----
assert(!H.includes('data-tab="alerts"') && !H.includes('id="t-alerts"') && !H.includes('id="paneAlert"'),
  'no Alerts tab: no radio, no label, no pane')
assert(!/['"]t-alerts['"]/.test(H), 'no stale t-alerts wiring (PANES/loader)')
assert(H.includes('>Alerts</span>') && H.includes('id="alertHead"') && H.includes('id="alertBanner"') && H.includes('id="alertList"'),
  'the Alerts block carries the header count and the unchanged body (banner + rows)')
// t261009-57: the header count is coalesce-then-cap aware — rows-of-total named when
// the alerts.display_max knob truncated, the bare count otherwise.
assert(H.includes("cap.capped ? (rows.length+' of '+cap.total+' conditions') : String(rows.length)"),
  'the Alerts header names rows-of-total when truncated, the bare count otherwise')
assert(!H.includes("'Recent · '"), "the old 'Recent · N' header wording is gone")

// ---- 2. Events face in, entry and dialog out ----
assert(!H.includes('id="ledgerDlgBtn"') && !H.includes('Recent actions (view source event)'), 'the lone entry link is gone')
assert(!H.includes('id="ledgerDlg"') && !H.includes('setLedgerDlg') && !H.includes('ledgerDlgClose'), 'the dialog overlay, its state machine and close control are gone')
for (const id of ['ledgerHealth', 'ledgerFile', 'ledgerEvents', 'wakeCount']) {
  assert(H.includes('id="' + id + '"'), 'Events block element present: ' + id)
}
assert(H.includes('class="evfile" id="ledgerFile"'), 'the ledger path renders in the header as monospace ellipsised text')
assert(H.includes("el('ledgerFile').title = lg.path || ''"), 'the full path travels on the title (hover face)')
assert(H.includes("el('ledgerHealth').innerHTML") && H.includes('bad rows ·'), 'the health facts render as ONE line (rows / duplicates / bad rows / gaps)')
assert(!H.includes('id="ledgerGrid"'), 'the four-cell health grid is gone (one line replaces it)')
assert(H.includes('The watchdog status keeps the last 20 wakes.'), 'the footer still states the window')
// review #1: the show-all entry is a display of the full-list fact, NOT a control —
// pinned handler-free so it cannot silently grow behaviour later.
assert(H.includes('id="wakesShowAll"'), 'the footer carries the show-all entry')
assert(!/getElementById\('wakesShowAll'\)|querySelector[^;]*wakesShowAll/.test(H), 'the show-all entry has NO click handler wired')

// ---- 3. Open session button out ----
assert(!H.includes('id="openSessionBtn"') && !H.includes('function updateOpenBtn'), 'the button and its hint path are gone')
assert(!H.includes("'sandbar-executor-panel:open-session'"), 'no open-session postMessage producer')
assert(!H.includes("'sandbar-executor-panel:open-session-result'"), 'no open-session-result listener branch')
assert(H.includes('id="sessionChip"') && H.includes("'Session: ' + (sess ? sess : 'none')"), 'the session chip stays as the state display')

// ---- 4. Four blocks, counts in headers ----
{
  const order = ['id="concBlock"', '>Alerts</span>', '>Recent actions</span>', '>Events</span>'].map(s => H.indexOf(s))
  assert(order.every(i => i > 0) && order[0] < order[1] && order[1] < order[2] && order[2] < order[3],
    'right column order: Concurrent limit / Alerts / Recent actions / Events')
  assert(H.includes('class="colstk"'), 'the right column is a block stack')
  const c0 = H.indexOf('id="concBlock"')
  const block = H.slice(c0, H.indexOf('id="alertBanner"', c0))
  assert(block.includes('Concurrent limit') && !block.includes('Running tickets'), 'the limit block title is pinned (scenario wording)')
  assert(block.indexOf('id="concCounts"') < block.indexOf('class="bbd"'), 'the limit counts sit in the block HEADER row')
  assert(block.includes('id="concChip"') && block.includes('id="concSave"') && block.includes('id="limitRow"'),
    'the chip, the write path and the CL-1 read/refusal line all stay in the block')
  assert((H.match(/class="blk"/g) || []).length === 4, 'exactly four bordered blocks')
  assert(H.includes('.blk{') && H.includes('.blk .bhd{') && H.includes('.blk .bbd{'), 'one shared block chrome (border + header + body)')
  assert(H.includes('.cols>div:last-child{display:flex;flex-direction:column}') && !H.includes('height:calc(100vh - 230px)'),
    'the two columns start on the same line (no per-column height cap left)')
  // t261009-37 rework (arbitrate round 1): with the clipping .cols>div overflow rule
  // gone, long unbreakable meta lines must be bounded at the element itself, or their
  // min-content width propagates to the document and reintroduces horizontal page
  // scroll at narrow viewports (the t261004-16 T7 regression face).
  for (const frag of ['id="bridgeLine" class="meta" style="margin:-4px 0 6px 0;min-width:0;overflow:hidden;text-overflow:ellipsis"',
    '.blk .bhd .muted{font-size:11px;min-width:0;overflow:hidden;text-overflow:ellipsis}',
    'id="limitRow" class="meta" style="margin:6px 0 0;width:100%;min-width:0;overflow:hidden;text-overflow:ellipsis"']) {
    assert(H.includes(frag), 'long meta line is bounded (no page-level horizontal overflow): ' + frag.slice(0, 40))
  }
}

// ---- 5. Refused mark moved into the op column; fixed row columns ----
assert(!H.includes('<span class="dot red" title="Refused">'), 'no inline red dot before the time column')
assert(H.includes("cls = refused ? 'refused' :"), 'refused rows take the refused pill class')
assert(H.includes('.pill.refused{'), 'the refused pill carries the semantic red (danger) styling')
assert(H.includes("esc(x.action||'') + ' · ' + esc(x.reason||'no reason recorded')"), 'the sentence names what was refused and why (not tooltip-only)')
assert(H.includes('.blk .bbd .act .pill{flex:0 0 66px') && H.includes('.blk .bbd .act .t{flex:0 0 96px') && H.includes('.blk .bbd .act .tk{flex:0 0 88px'),
  'the row columns are fixed-width (time / op / ticket line up across rows)')

// ---- 6. Project colour from the SAME identity function ----
assert(H.includes(':root{--proj:#9ca3af}'), 'the grey default --proj is pinned in :root (fallback, review #2)')
assert(H.includes('.top::before{') && H.includes('height:3px') && H.includes('background:var(--proj)'), 'a 3px identity bar spans the top of the page')
assert(/setProperty\('--proj',\s*projectIdentity\(key\)\.color\)/.test(H),
  'the bar colour comes from the SAME projectIdentity() the badge uses (no second hash, no hand-picked value)')
{
  // t261009-37 defect pin: the embedded identity sources close over two module-private
  // constants (STREAM2_SALT / KEY_MAX_LEN) that project-identity.ts does not export.
  // The page embeds them as literals; this test pins the LITERALS against the real
  // module's BEHAVIOR, so a module-side change turns red here instead of silently
  // breaking the badge and the colour bar on the served page again.
  const id = await import('../../workbench/src/shared/project-identity.ts')
  const consts = H.slice(H.indexOf('var STREAM2_SALT'), H.indexOf('var KEY_MAX_LEN = 64;') + 'var KEY_MAX_LEN = 64;'.length)
  assert(H.includes("var STREAM2_SALT = " + JSON.stringify('\u0000wb-identity')), 'the embedded STREAM2_SALT literal matches the module constant')
  assert(id.isProjectKeyLike('k'.repeat(64)) === true && id.isProjectKeyLike('k'.repeat(65)) === false,
    'the module boundary really is 64 chars (the pinned KEY_MAX_LEN literal stays true)')
  for (const k of ['sandbar', 'alpha', 'proj-9', 'x'.repeat(64)]) {
    // the embedded closure needs fnv1a + the tables next to the consts, exactly like
    // the served page's script scope (IDENTITY_RUNTIME vars + embedded functions)
    const viaPage = new Function(consts
      + '\nvar PROJECT_PALETTE_12=' + JSON.stringify(id.PROJECT_PALETTE_12)
      + ',IDENTITY_OUTLINES=' + JSON.stringify(id.IDENTITY_OUTLINES)
      + ',IDENTITY_STRUCTURES=' + JSON.stringify(id.IDENTITY_STRUCTURES)
      + ';\n' + String(id.fnv1a) + '\nreturn (' + String(id.baseIdentity) + ')(' + JSON.stringify(k) + ')')()
    assert(JSON.stringify(viaPage) === JSON.stringify(id.baseIdentity(k)),
      'embedded baseIdentity (page consts) reproduces the module identity for ' + JSON.stringify(k.slice(0, 12)))
  }
}
{
  // Identity colour only on identity surfaces: no --proj anywhere else.
  const uses = [...H.matchAll(/var\(--proj\)/g)].length
  assert(uses === 1, 'identity colour is used on exactly one surface (the top bar), found ' + uses)
}

// ---- 7. Malformed input anchors survive (honest degradation, house rule) ----
{
  const fn = H.slice(H.indexOf('function renderAlertsLedger()'), H.indexOf('function renderLimitRow()'))
  assert(/var bad = !w2 \|\| typeof w2 !== 'object' \|\| Array\.isArray\(w2\)/.test(fn),
    'the wakes loop still guards non-object rows (a null row cannot abort the face)')
  assert(fn.includes("var when = bad ? '—' : localDateTime(w2.at)"), 'a malformed wake row still renders the dash time')
  assert(fn.includes("el('wakeCount').textContent='0'"), 'the no-status branch still clears the count and the health line')
  assert(fn.includes("el('ledgerHealth').textContent=''"), 'the no-status branch clears the health line (no stale numbers)')
}

n += 34
done(n)
