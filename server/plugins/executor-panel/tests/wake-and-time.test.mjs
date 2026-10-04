/**
 * wake-and-time.test.mjs —— t261003-13 Ledger 页诚实化 UT：
 *  - localDateTime：本地时区「YYYY-MM-DD HH:MM」格式锁定（t261004-14 起带日期）（固定时间戳，期望值用同一套本地 Date API 推出，
 *    不写死字面量——review 意见 #2）；另起子进程在 TZ=UTC / TZ=Asia/Shanghai 下各验一次，
 *    与 UTC 切片的差值方向断言时区真的生效（锁口径，不锁机器）。
 *  - 畸形输入：NaN / garbage 字符串 / null / undefined / 空串 → 显式「—」。
 *  - wakeRowSentence：mode+accepted 组合、缺 mode、缺 accepted、非布尔 accepted、
 *    空串 mode、非对象输入（null/字符串/数字/数组）——任一缺席都显式 unknown /
 *    「未报告」，绝不落成句子样兜底词（旧实现 'sent' 的病根）。
 *  - STE：输出无缩略形式。
 * 零 DOM、零网络、零 3099 触碰。
 */
import { spawnSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, done } from './lib.mjs'
import { localDateTime, newestFirst, dateTimeLocal, wakeRowSentence } from '../src/host/page-logic.ts'

const here = dirname(fileURLToPath(import.meta.url))
let n = 0

// ---- localDateTime：格式锁定（期望值由同一套本地 API 推出，防时区依赖假红/假绿） ----
// t261004-14：行时间必须带日期（旧 hhmmLocal 只出 HH:MM），更名 localDateTime，旧名不留。
const FIXED = Date.UTC(2026, 9, 3, 11, 50, 0) // 2026-10-03 11:50 UTC
const d = new Date(FIXED)
const p2 = (x) => (x < 10 ? '0' + x : String(x))
const expected = d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate())
  + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes())
assert(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(localDateTime(FIXED)), 'localDateTime returns YYYY-MM-DD HH:MM')
assert(localDateTime(FIXED) === expected, 'localDateTime matches local date+time of the same Date (' + expected + ')')
assert(localDateTime(FIXED) === localDateTime(new Date(FIXED).toISOString()), 'number and ISO string inputs agree')
// DST 边界（3 月最后一个周日附近，本地与 UTC 普遍相差非整日）——仍须是合法「日期 时间」且非 UTC 字面值格式逃逸
assert(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(localDateTime(Date.UTC(2026, 2, 29, 0, 30))), 'DST-boundary timestamp still formats date+time')
// localDateTime 不得再走 UTC 切片：至少存在一个固定时间戳在 TZ≠UTC 机器上两者必然不同
// （此处仅锁「非 toISOString().slice(11,16) 的实现痕迹」——嵌入页的源码里不再有该切片）
const { readFileSync } = await import('node:fs')
const pageSrc = readFileSync(join(here, '../src/host/panel-page.ts'), 'utf8')
assert(!pageSrc.includes('toISOString()).slice(11,16)'), 'page no longer slices UTC from toISOString for row times')
assert(!pageSrc.includes("||'sent'"), "page no longer carries the 'sent' fallback")

// ---- localDateTime：时区真生效（子进程钉 TZ）----
function runWithTz(tz) {
  const r = spawnSync(process.execPath, ['--experimental-strip-types', join(here, 'tzprobe.mjs'), String(FIXED)],
    { env: { ...process.env, TZ: tz }, encoding: 'utf8' })
  assert(r.status === 0, 'tz probe exits 0 under TZ=' + tz)
  return r.stdout.trim()
}
assert(runWithTz('UTC') === '2026-10-03 11:50', 'TZ=UTC renders 2026-10-03 11:50')
const sh = runWithTz('Asia/Shanghai')
assert(sh === '2026-10-03 19:50', 'TZ=Asia/Shanghai renders 2026-10-03 19:50 (got ' + sh + ')')

// ---- localDateTime：畸形输入 ----
for (const bad of [NaN, 'not a time', null, undefined, '', {}, new Date('garbage')]) {
  assert(localDateTime(bad) === '—', 'localDateTime degrades to — for ' + JSON.stringify(bad))
}

// ---- newestFirst：最新在前统一排序（t261004-14；review 条件 4：并列稳定、畸形 at 排最后） ----
{
  const rows = [
    { id: 'a', at: 2000 },
    { id: 'b', at: 3000 },
    { id: 'c', at: 2000 },           // 与 a 并列——保持原相对顺序（稳定）
    { id: 'd', at: 'not a time' },   // 畸形 at——排最后，不抛错
    { id: 'e' },                     // 缺 at——排最后
    { id: 'f', at: '2026-10-03T00:00:00Z' }, // 字符串形式照常解析参与排序
  ]
  const out = newestFirst(rows)
  const ids = out.map((r) => r.id)
  assert(ids.join(',') === 'f,b,a,c,d,e', 'full newest-first order (f=' + ids.join(',') + ')')
  assert(out[0].id === 'f', 'parsed ISO-string at competes on the same clock as numeric at')
  assert(ids.indexOf('a') < ids.indexOf('c'), 'equal at keeps original relative order (stable)')
  assert(rows[0].id === 'a', 'newestFirst does not mutate the input array')
  assert(newestFirst([]).length === 0, 'empty list sorts to empty')
  assert(newestFirst([{ id: 'x', at: null }, { id: 'y' }, { id: 'z', at: 1 }]).map((r) => r.id).join('') === 'zxy', 'null at sorts last like missing')
}

// ---- dateTimeLocal（t261004-13）：本地时区 MM-DD HH:MM，跨天可辨 ----
const expectedDated = p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes())
assert(/^\d{2}-\d{2} \d{2}:\d{2}$/.test(dateTimeLocal(FIXED)), 'dateTimeLocal returns MM-DD HH:MM')
assert(dateTimeLocal(FIXED) === expectedDated, 'dateTimeLocal matches local MM-DD HH:MM of the same Date (' + expectedDated + ')')
assert(dateTimeLocal(FIXED) === dateTimeLocal(new Date(FIXED).toISOString()), 'number and ISO string inputs agree')
// 跨天两条告警在屏上必然可辨（日期部分不同，或至少格式带日期字段）。
// 跨天两条告警在屏上必然可辨（t261004-14 起行时间统一走 localDateTime 的 YYYY-MM-DD 形，
// 日期部分必然不同；此处锁「日期字段在场」的可判对面——hhmmLocal 已随 t261004-14 退役）。
assert(dateTimeLocal(Date.UTC(2026, 0, 5, 8, 0)) !== dateTimeLocal(Date.UTC(2025, 11, 30, 8, 0)),
  'cross-day timestamps render distinguishable dated strings')
assert(/^\d{2}-\d{2} \d{2}:\d{2}$/.test(dateTimeLocal(Date.UTC(2026, 2, 29, 0, 30))), 'DST-boundary timestamp still formats MM-DD HH:MM')
// 畸形输入与 hhmmLocal 同契约：显式「—」。
for (const bad of [NaN, 'not a time', null, undefined, '', {}, new Date('garbage')]) {
  assert(dateTimeLocal(bad) === '—', 'dateTimeLocal degrades to — for ' + JSON.stringify(bad))
}

// ---- wakeRowSentence：真实字段组合 ----
assert(wakeRowSentence({ at: FIXED, ticket: 't1', mode: 'queue', accepted: true })
  === 'Mode: queue. The executor accepted the wake.', 'accepted wake sentence')
assert(wakeRowSentence({ at: FIXED, ticket: 't1', mode: 'queue', accepted: false })
  === 'Mode: queue. The executor did not accept the wake.', 'rejected wake sentence')

// ---- wakeRowSentence：字段缺席/畸形（外部输入纪律：畸形用例桩内复现） ----
assert(wakeRowSentence({ ticket: 't1', accepted: true })
  === 'Mode: unknown. The executor accepted the wake.', 'missing mode renders unknown, not a word')
assert(wakeRowSentence({ ticket: 't1', mode: 'queue' })
  === 'Mode: queue. The watchdog did not report whether the executor accepted the wake.', 'missing accepted renders not-reported')
assert(wakeRowSentence({ ticket: 't1' })
  === 'Mode: unknown. The watchdog did not report whether the executor accepted the wake.', 'both missing')
assert(wakeRowSentence({ mode: 'queue', accepted: 'yes' })
  === 'Mode: queue. The watchdog did not report whether the executor accepted the wake.', 'non-boolean accepted = not reported')
assert(wakeRowSentence({ mode: '  ', accepted: true })
  === 'Mode: unknown. The executor accepted the wake.', 'blank mode renders unknown')
for (const bad of [null, 'wake', 42, [], true]) {
  assert(wakeRowSentence(bad)
    === 'Mode: unknown. The watchdog did not report whether the executor accepted the wake.',
    'non-object input (' + JSON.stringify(bad) + ') degrades to explicit unknown sentence')
}

// ---- STE：无缩略形式 ----
for (const s of [wakeRowSentence({}), wakeRowSentence({ mode: 'queue', accepted: false })]) {
  assert(!/\b\w+'(t|re|s|ll|ve|d|m)\b/i.test(s), 'no contractions in: ' + s)
}

done(n + 27)
