/**
 * t261009-57-alerts-face.test.mjs —— Alerts 面重做 UT（纯 node，零 DOM/网络/3099）：
 *  - coalesce FIRST：同 key 连续运行段并一行 xN（first/last 皆取自 payload）；
 *  - 清除后再响 = 新运行段（绝跨清除期合并）；
 *  - capCoalesced：alerts.display_max 只数并排行；0=全显（显式分支，无 slice(-0)）；
 *  - relTimeAgo：相对优先（just now / Nm / Nh / Nd ago）；畸形/未来 at → '—'；
 *  - 窗口边诚实：首运行段触窗口底 → at_window_edge（面渲染 first ≥）；
 *  - 畸形行（null/串/缺 at/NaN）逐行透传 count=1，不抛；
 *  - 页面契约：<time datetime>、hover 绝对时刻、标题换行类、xN 徽标、级别词、
 *    设置旋钮行、头行 N of M conditions。
 * 畸形输入锚点内置（桩=固定数组，无外部源）。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML, coalesceAlerts, capCoalesced, relTimeAgo } from '../src/host/panel-page.ts'

let n = 0
const H = PANEL_PAGE_HTML
const NOW = 1_700_000_000_000
const mk = (key, at, i = 0, over = {}) => ({ key, rule: 'r', target: 't', level: 'warn', title: 'cond ' + key, at, night_muted: false, ...over })

// ---- 1. R1 acceptance pin: 30 same-key consecutive rows → 1 coalesced row x30 ----
{
  const rows = Array.from({ length: 30 }, (_, i) => mk('ledger:ledger', NOW - 60_000 * (30 - i), i))
  const g = coalesceAlerts(rows)
  assert(g.length === 1 && g[0].count === 30, '30 consecutive same-key rows coalesce to ONE row x30, got ' + JSON.stringify(g.map(x => x.count)))
  assert(g[0].first_at === NOW - 60_000 * 30 && g[0].last_at === NOW - 60_000, 'xN row keeps first_at and last_at from the payload')
  const cap = capCoalesced(g, 8)
  assert(cap.rows.length === 1 && cap.total === 1 && !cap.capped, 'display_max 8 with 1 group shows the 1 row, no truncation notice')
  n += 3
}
// ---- 2. R3 pin: cleared-and-refired same key = two groups; truncation keeps per-run counts ----
{
  const rows = [
    ...Array.from({ length: 10 }, (_, i) => mk('a:a', NOW - 60_000 * (26 - i))),
    mk('b:b', NOW - 60_000 * 15),
    ...Array.from({ length: 15 }, (_, i) => mk('a:a', NOW - 60_000 * (14 - i))),
  ]
  const g = coalesceAlerts(rows)
  assert(g.length === 3, 'a x10 / b / a x15 stay three groups (no merge across the cleared period), got ' + g.length)
  assert(g[0].count === 15 && g[1].key === 'b:b' && g[2].count === 10, 'newest-first groups: refire x15, b, older x10')
  const cap = capCoalesced(g, 2)
  assert(cap.rows.length === 2 && cap.capped && cap.total === 3, 'display_max 2 keeps the two newest groups and names the truncation')
  assert(cap.rows.every(r => r.count === 15 || r.key === 'b:b'), 'per-run counts survive the truncation intact')
  n += 3
}
// ---- 3. window-edge honesty ----
{
  const rows = [mk('a:a', NOW - 60_000 * 40), mk('a:a', NOW - 60_000 * 30), mk('b:b', NOW - 60_000 * 5)]
  const g = coalesceAlerts(rows)
  assert(g[1].at_window_edge === true && g[0].at_window_edge === false, 'the oldest group carries at_window_edge, interior groups do not')
  const noRows = coalesceAlerts([])
  assert(noRows.length === 0, 'empty payload coalesces to no groups')
  n += 2
}
// ---- 4. malformed rows pass through, never throw ----
{
  const rows = [null, 'junk', 42, { key: 'k', at: 'noon' }, { title: 'no at' }, { key: 'k2', at: NaN }, mk('ok:ok', NOW)]
  const g = coalesceAlerts(rows)
  assert(g.length === 7, 'every malformed row passes through as its own row, got ' + g.length)
  assert(g[0].count === 1 && Number.isNaN(g[0].last_at), 'malformed rows render as count-1 rows with NaN times (the dash face)')
  // W1 (arbitrate round 1): a bad at must not zero the record — readable fields survive.
  const badAt = coalesceAlerts([{ key: 'k-bad', rule: 'stall', target: 'sb', level: 'warn', title: 'bad-at-row', at: null }])
  assert(badAt.length === 1 && badAt[0].title === 'bad-at-row' && badAt[0].rule === 'stall' && badAt[0].level === 'warn' && Number.isNaN(badAt[0].last_at),
    'a row with a valid title but malformed at keeps title/rule/level and degrades only the time')
  const nonObj = coalesceAlerts([null, 42])
  assert(nonObj.length === 2 && nonObj.every(r => r.title === '' && Number.isNaN(r.last_at)), 'true non-object rows stay honest empty count-1 rows (nothing to keep)')
  assert(coalesceAlerts(undefined).length === 0 && coalesceAlerts('nope').length === 0, 'non-array payloads degrade to no rows (no throw)')
  n += 4
}
// ---- 5. relative time ----
{
  assert(relTimeAgo(NOW - 30_000, NOW) === 'just now', 'relTimeAgo 30s = just now')
  assert(relTimeAgo(NOW - 5 * 60_000, NOW) === '5m ago', 'relTimeAgo 5m')
  assert(relTimeAgo(NOW - 3 * 3600_000, NOW) === '3h ago', 'relTimeAgo 3h')
  assert(relTimeAgo(NOW - 2 * 24 * 3600_000, NOW) === '2d ago', 'relTimeAgo 2d')
  assert(relTimeAgo(NOW - 60_000, NOW) === '1m ago', 'relTimeAgo minute boundary')
  assert(relTimeAgo(NaN, NOW) === '—' && relTimeAgo('x', NOW) === '—' && relTimeAgo(null, NOW) === '—', 'relTimeAgo malformed = dash')
  assert(relTimeAgo(NOW + 10 * 60_000, NOW) === '—', 'relTimeAgo far-future = dash (no fabricated time)')
  n += 4
}
// ---- 6. capCoalesced sentinel and fallback ----
{
  const g = Array.from({ length: 12 }, (_, i) => ({ ...mk('k' + i, NOW - i), count: 1 }))
  assert(capCoalesced(g, 0).rows.length === 12 && capCoalesced(g, 0).capped === false, 'display_max 0 = show all (explicit branch)')
  assert(capCoalesced(g, 8).rows.length === 8 && capCoalesced(g, 8).capped === true, 'display_max 8 keeps the 8 newest coalesced rows')
  assert(capCoalesced(g, undefined).rows.length === 8, 'missing knob falls back to the factory 8 (defensive, payload normally carries it)')
  assert(capCoalesced(g, -1).rows.length === 8 && capCoalesced(g, 2.5).rows.length === 8, 'malformed knob falls back to 8 (never slice(-max))')
  n += 4
}
// ---- 7. page contract (static anchors; behavior above runs the real functions) ----
{
  assert(H.includes('function relTimeAgo') && H.includes('function coalesceAlerts') && H.includes('function capCoalesced'),
    'the face runs the same embedded implementation the UT just exercised')
  // t261009-37 lesson pinned: the embedded coalesce source is SELF-CONTAINED — no
  // reference to a module-level helper that the page scope does not carry.
  {
    const src = H.slice(H.indexOf('function coalesceAlerts'), H.indexOf('function capCoalesced'))
    assert(src.includes("const ok = (r") && !src.includes('isValidAlertRow'),
      'the embedded coalesce core is self-contained (no out-of-scope helper reference)')
  }
  assert(H.includes('coalesceAlerts(st.alerts||[])') && H.includes('capCoalesced(co, st.alerts_display_max)'),
    'render = coalesce FIRST, then cap by the payload-delivered host number (one source)')
  assert(H.includes('<time datetime='), 'rows carry <time datetime> for semantics')
  assert(H.includes("title=\"'+esc(localDateTime(at))+'\""), 'the absolute moment rides the hover title of the time element')
  assert(!/>Times are local\.<\/span><\/div>/.test(H.slice(H.indexOf('>Alerts</span>'), H.indexOf('>Recent actions</span>'))),
    'the Alerts header no longer claims absolute-only times')
  assert(H.includes('class="txt altxt"') && H.includes('.altxt{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-word;white-space:normal}'),
    'alert titles use the wrapping class (the ellipsis cut is gone); the shared .txt keeps its shape')
  assert(!/alertList[\s\S]{0,2000}text-overflow:ellipsis/.test(H) && H.includes("esc(a2.title)"),
    'alert rows render the full esc()d title, no ellipsis treatment applied to the alert face')
  assert(H.includes("x'+a2.count+'"), 'a count>1 group renders the xN badge')
  assert(H.includes("a2.at_window_edge?'first ≥ ':'first '"), 'a window-edge group renders first ≥ (honest lower bound)')
  assert(H.includes("a2.level==='redline' ? 'redline' : (a2.level==='warn' ? 'warn'"), 'the row names its level in words (redline/warn/info)')
  assert(H.includes("' · night-muted':'"), 'the night-muted marker keeps its meaning on the coalesced row')
  assert(H.includes("(isNaN(a2.last_at) ? '' : ' · ' + localDateTime(a2.last_at))"),
    'the hover tip adds no absolute when the row time is malformed (nothing fabricated from NaN)')
  assert(H.includes("['alerts.display_max','number','Coalesced alert rows to show. 0 shows all.']"),
    'the Settings face exposes the knob and states the 0 sentinel')
  assert(H.includes("rows.length+' of '+cap.total+' conditions'"), 'the header names rows-of-total when the knob truncated')
  n += 10
}
done(n)
