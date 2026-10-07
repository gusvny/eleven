/**
 * smoke/session-handles.mjs — smoke for the session handle pure-function layer
 * (console-ui UI-5, t261005-06).
 *
 * Run: node smoke/session-handles.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Under test: src/shared/session-handles.ts — short codes (design note §2.3), idempotent
 * handle assignment (4→6 collision extension, executor excluded from the code space),
 * sessions.json parse/serialize tolerance (bad JSON / wrong shape / wrong version / dirty
 * entries → empty or cleaned, never throw), id-union merge (R4 concurrency stance:
 * newer last_opened_at wins, unmentioned entries survive), executor projection
 * (derived display, not persisted; grants stay the source of who-is-executor).
 */

import {
  EXECUTOR_HANDLE,
  SHORT_CODE_LEN,
  assignHandles,
  displayHandle,
  mergeExecutorSessions,
  mergeLedgerEntries,
  parseSessionLedgerFile,
  serializeSessionLedgerFile,
  shortCodeOf,
} from '../src/shared/session-handles.ts'
import { CHARTER_MARKER } from '../src/host/session-charter.ts'
import { isCharterRawTitle } from '../src/shared/charter-title.ts'
import { rowLabelOf } from '../src/shared/sessions.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('shortCodeOf：剥前缀取十六进制前 4 位（设计 §2.3 原例）')
{
  ok(shortCodeOf('session-09ca0247-aaaa-bbbb') === '09ca', 'session- 前缀剥掉，取 09ca')
  ok(shortCodeOf('09ca0247-aaaa') === '09ca', '裸 uuid 同规则')
  ok(shortCodeOf('session-ab') === 'ab', '短 id 取全部（不造假位）')
  ok(shortCodeOf('') === '' && shortCodeOf(undefined) === '' && shortCodeOf(42) === '', '非 string/空串=空码（不造假码）')
  ok(shortCodeOf('session-09ca0247', 6) === '09ca02', '扩展位按长度取')
  ok(SHORT_CODE_LEN === 4, '基准长度=4（设计定值）')
}

section('assignHandles：幂等分配 + 撞码扩位 + executor 不进码域')
{
  const a = { session_id: 'session-09ca0247-1' }
  const b = { session_id: 'session-09ca9999-2' }
  const one = assignHandles([a])
  ok(one[0].handle === '09ca', '分配 4 位短码')
  ok(assignHandles(one)[0].handle === '09ca', '幂等：已分配不重排')
  // collision: both start 09ca -> second extends to 6
  const c = { session_id: 'session-09ca0247-2' }
  const two = assignHandles([a, c])
  ok(two[0].handle === '09ca' && two[1].handle === '09ca02', '撞码扩到 6 位')
  // executor fixed name is excluded from the code space
  const ex = { session_id: 'session-09ca0247-3', handle: EXECUTOR_HANDLE }
  const three = assignHandles([ex, a, c])
  ok(three[0].handle === 'executor', 'executor 固定名保留')
  ok(three[1].handle === '09ca' && three[2].handle === '09ca02', 'executor 不占短码域（09ca 仍可用）')
  // dirty entries pass through untouched
  const dirty = assignHandles([null, {}, { session_id: '' }, { session_id: 'session-beef0000' }])
  ok(dirty[0] === null && dirty[1] !== undefined && dirty[2].handle === undefined, '脏条目不崩不造假码')
  ok(dirty[3].handle === 'beef', '健康条目照常分配')
  // input not mutated
  const src = [{ session_id: 'session-beef0000' }]
  assignHandles(src)
  ok(src[0].handle === undefined, '不改入参')
}

section('displayHandle：已分配用已分配，未分配短码兜底（只显示不落盘）')
{
  ok(displayHandle({ session_id: 'session-09ca0247' }) === '09ca', '未分配=短码兜底')
  ok(displayHandle({ session_id: 'session-09ca0247', handle: 'executor' }) === 'executor', '已分配=原样')
  ok(displayHandle(undefined) === '' && displayHandle({ session_id: '' }) === '', '脏输入=空串')
}

section('parseSessionLedgerFile：畸形输入全容错（桩复现，不靠真外部源）')
{
  ok(parseSessionLedgerFile(null).length === 0 && parseSessionLedgerFile('').length === 0, '空输入=空册')
  ok(parseSessionLedgerFile('not json {').length === 0, '坏 JSON=空册不抛')
  ok(parseSessionLedgerFile('[1,2]').length === 0, '顶层非对象=空册')
  ok(parseSessionLedgerFile('{"version":2,"sessions":[]}').length === 0, 'version 不对=空册（schema 收口）')
  ok(parseSessionLedgerFile('{"version":1}').length === 0, '缺 sessions=空册')
  ok(parseSessionLedgerFile('{"version":1,"sessions":"x"}').length === 0, 'sessions 非数组=空册')
  const doc = JSON.stringify({
    version: 1,
    sessions: [
      { session_id: 'session-09ca0247', handle: '09ca', title: 't', opened_at: 1, last_opened_at: 2, cwd: '/x' },
      { session_id: '' },              // dirty: empty id -> dropped
      'not-an-object',                 // dirty: non-object -> dropped
      { session_id: 'session-beef0000', last_opened_at: 'x' }, // dirty ts dropped, entry kept
      { session_id: 'session-cafe0000', unknown_field: 'kept? no' }, // unknown field dropped
    ],
  })
  const entries = parseSessionLedgerFile(doc)
  ok(entries.length === 3, `脏条目剔掉（3 条存活，实得 ${entries.length}）`)
  ok(entries[0].handle === '09ca' && entries[0].cwd === '/x' && entries[0].last_opened_at === 2, '健康条目字段全收')
  ok(entries[1].last_opened_at === undefined, '畸形时间戳剔字段不崩')
  ok(entries[2].unknown_field === undefined, '未知字段不透传')
  // round-trip
  ok(parseSessionLedgerFile(serializeSessionLedgerFile(entries)).length === 3, 'serialize→parse round-trip')
  ok(serializeSessionLedgerFile(undefined).includes('"version"'), 'serialize 容错：非数组按空册')
}

section('mergeLedgerEntries：id-union（R4 并发契约）')
{
  const existing = [
    { session_id: 'a', handle: 'aaaa', last_opened_at: 100 },
    { session_id: 'b', handle: 'bbbb', last_opened_at: 50 },
  ]
  const m1 = mergeLedgerEntries(existing, { session_id: 'c', handle: 'cccc', last_opened_at: 9 })
  ok(m1.length === 3 && m1[0].session_id === 'c', '新 id 插头（MRU）')
  const m2 = mergeLedgerEntries(existing, { session_id: 'a', handle: 'zzzz', last_opened_at: 200 })
  ok(m2.length === 2 && m2.find(e => e.session_id === 'a').handle === 'zzzz', '已有 id：last_opened_at 新者胜')
  const m3 = mergeLedgerEntries(existing, { session_id: 'a', handle: 'old', last_opened_at: 1 })
  ok(m3.find(e => e.session_id === 'a').handle === 'aaaa', '旧时间戳不改写存量（丢新窗口收敛）')
  ok(m2.find(e => e.session_id === 'b').handle === 'bbbb', '未被提及的存量条目原样保留')
  ok(mergeLedgerEntries(existing, { session_id: '' }).length === 2 && mergeLedgerEntries(null, { session_id: 'x' }).length === 1, '脏入参容错')
}

section('mergeExecutorSessions：执行器投影（派生显示，不落文件）')
{
  const base = [{ session_id: 'session-1111', handle: '1111' }]
  const m = mergeExecutorSessions(base, ['session-2222', 'session-1111', '', 42])
  ok(m.length === 2, '重复/空/非 string 的声明 id 不重复投影')
  ok(m[0].session_id === 'session-2222' && m[0].handle === 'executor', '投影条目 handle=executor 且排最前')
  ok(m[1] === base[0], '普通条目原样保留（同引用，无复制开销）')
  ok(mergeExecutorSessions(base, 'not-array').length === 1, '非数组声明=无投影不崩')
}

section('charter 原文标题判定与行标签替身（t261008-01 Measure 1）')
{
  // isCharterRawTitle：只认注入自身的注释形（marker 整行/前缀、点名 charter 的注释）。
  ok(isCharterRawTitle(`${CHARTER_MARKER}\n<!-- doc -->\n正文`) === true, '旧注入形（marker 首行）命中')
  ok(isCharterRawTitle(`<!-- workbench:kind:charter xxx -->`) === true, 'marker 变体注释命中')
  ok(isCharterRawTitle(`<!-- session_charter.md —— 说明 -->`) === true, 'charter 文件头注释命中')
  ok(isCharterRawTitle('Project session — sandbar (sandbar)') === false, '新注入首行（人读标题）不命中')
  ok(isCharterRawTitle('普通会话标题') === false, '普通标题不命中')
  ok(isCharterRawTitle('<!-- 随手写的注释 -->') === false, '无关 HTML 注释不命中（保守判据）')
  ok(isCharterRawTitle('') === false && isCharterRawTitle(null) === false && isCharterRawTitle(42) === false, '空/非字符串容错 false')
  // rowLabelOf：charter 原文标题 → handle 替身；普通标题零行为变化。
  const row = { displayTitle: `${CHARTER_MARKER}\n<!-- session_charter.md -->\n正文` }
  ok(rowLabelOf(row, 'session-09ca0247', '09ca') === '09ca', 'charter 原文标题 → handle 替身')
  ok(rowLabelOf(row, 'session-09ca0247', EXECUTOR_HANDLE) === 'executor', 'executor 会话 → 固定名 executor')
  ok(rowLabelOf(row, 'session-09ca0247', '') === 'session-09ca0247', 'handle 缺位 → 兜底 id（不做本地猜测）')
  ok(rowLabelOf(row, 'session-09ca0247', undefined) === 'session-09ca0247', 'handle 未传 → 兜底 id')
  ok(rowLabelOf({ displayTitle: '普通标题' }, 's1', '09ca') === '普通标题', '普通标题走 labelOf 原口径')
  ok(rowLabelOf(undefined, 'session-09ca0247', '09ca') === 'session-09ca0247', '无标题行 → id 兜底')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
