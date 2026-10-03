/**
 * wake-and-time.test.mjs —— t261003-13 Ledger 页诚实化 UT：
 *  - hhmmLocal：本地时区 HH:MM 格式锁定（固定时间戳，期望值用同一套本地 Date API 推出，
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
import { hhmmLocal, wakeRowSentence } from '../src/host/page-logic.ts'

const here = dirname(fileURLToPath(import.meta.url))
let n = 0

// ---- hhmmLocal：格式锁定（期望值由同一套本地 API 推出，防时区依赖假红/假绿） ----
const FIXED = Date.UTC(2026, 9, 3, 11, 50, 0) // 2026-10-03 11:50 UTC
const d = new Date(FIXED)
const p2 = (x) => (x < 10 ? '0' + x : String(x))
const expected = p2(d.getHours()) + ':' + p2(d.getMinutes())
assert(/^\d{2}:\d{2}$/.test(hhmmLocal(FIXED)), 'hhmmLocal returns HH:MM')
assert(hhmmLocal(FIXED) === expected, 'hhmmLocal matches local HH:MM of the same Date (' + expected + ')')
assert(hhmmLocal(FIXED) === hhmmLocal(new Date(FIXED).toISOString()), 'number and ISO string inputs agree')
// DST 边界（3 月最后一个周日附近，本地与 UTC 普遍相差非整日）——仍须是合法 HH:MM 且非 UTC 字面值格式逃逸
assert(/^\d{2}:\d{2}$/.test(hhmmLocal(Date.UTC(2026, 2, 29, 0, 30))), 'DST-boundary timestamp still formats HH:MM')
// hhmmLocal 不得再走 UTC 切片：至少存在一个固定时间戳在 TZ≠UTC 机器上两者必然不同
// （此处仅锁「非 toISOString().slice(11,16) 的实现痕迹」——嵌入页的源码里不再有该切片）
const { readFileSync } = await import('node:fs')
const pageSrc = readFileSync(join(here, '../src/host/panel-page.ts'), 'utf8')
assert(!pageSrc.includes('toISOString()).slice(11,16)'), 'page no longer slices UTC from toISOString for row times')
assert(!pageSrc.includes("||'sent'"), "page no longer carries the 'sent' fallback")

// ---- hhmmLocal：时区真生效（子进程钉 TZ）----
function runWithTz(tz) {
  const r = spawnSync(process.execPath, ['--experimental-strip-types', join(here, 'tzprobe.mjs'), String(FIXED)],
    { env: { ...process.env, TZ: tz }, encoding: 'utf8' })
  assert(r.status === 0, 'tz probe exits 0 under TZ=' + tz)
  return r.stdout.trim()
}
assert(runWithTz('UTC') === '11:50', 'TZ=UTC renders 11:50')
const sh = runWithTz('Asia/Shanghai')
assert(sh === '19:50', 'TZ=Asia/Shanghai renders 19:50 (got ' + sh + ')')

// ---- hhmmLocal：畸形输入 ----
for (const bad of [NaN, 'not a time', null, undefined, '', {}, new Date('garbage')]) {
  assert(hhmmLocal(bad) === '—', 'hhmmLocal degrades to — for ' + JSON.stringify(bad))
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
