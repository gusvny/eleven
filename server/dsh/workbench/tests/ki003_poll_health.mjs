#!/usr/bin/env node
/**
 * ki003_poll_health.mjs —— 轮询健康度状态机单测（t260903-06 KI-003③ UI 优雅降级）。
 *
 * 被测：src/client/poll-health.ts（纯函数，无 React 无 IO）。
 * 覆盖（方案验收口径）：
 *   A. classifyPollBody 判据：只认 body.kind 机器字段——ok:true → ok；
 *      kind=not_found/terminal → 致命类；kind=transient/internal/未知/缺失/
 *      非对象/null → 一律 retryable（网络抖动绝不冒充不存在，KI-025 口径）。
 *   B. nextPollState 转移：ok 清零；retryable 累加、连续 3 次才升错误态；
 *      致命类立即错误态（不诱导重试）；错误态后一次成功即恢复。
 *   C. worstOutcome 同拍多路取最坏。
 *   D. 畸形输入：null/undefined/非预期形状 → 不抛错按 retryable 降级。
 *
 * 直跑：node server/dsh/workbench/tests/ki003_poll_health.mjs（node ≥22.18 原生 type-stripping）。
 */
import {
  classifyPollBody,
  nextPollState,
  worstOutcome,
  INITIAL_POLL_STATE,
  POLL_FAIL_THRESHOLD,
} from '../src/client/poll-health.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------- A. classifyPollBody 判据 */
section('A classifyPollBody：判据=body.kind 机器字段（apiGet 不透状态码）')
ok(classifyPollBody({ ok: true }) === 'ok', 'ok:true → ok')
ok(classifyPollBody({ ok: false, kind: 'not_found' }) === 'not_found', 'kind=not_found → not_found')
ok(classifyPollBody({ ok: false, kind: 'terminal' }) === 'terminal', 'kind=terminal → terminal')
ok(classifyPollBody({ ok: false, kind: 'transient' }) === 'retryable', 'kind=transient → retryable')
ok(classifyPollBody({ ok: false, kind: 'internal' }) === 'retryable', 'kind=internal → retryable')
ok(classifyPollBody({ ok: false }) === 'retryable', 'kind 缺失 → retryable（绝不按不存在处理）')
ok(classifyPollBody({ ok: false, kind: 'weird-unknown' }) === 'retryable', 'kind 未知值 → retryable')
ok(classifyPollBody(null) === 'retryable', 'null → retryable')
ok(classifyPollBody(undefined) === 'retryable', 'undefined → retryable')
ok(classifyPollBody('garbage') === 'retryable', '非对象 → retryable 不抛错')

/* ---------------------------------- B. nextPollState 转移 */
section(`B nextPollState：连续 ${POLL_FAIL_THRESHOLD} 次失败才错误态`)
ok(POLL_FAIL_THRESHOLD === 3, '阈值=3（≈15s @5s 节拍）')
let s = { ...INITIAL_POLL_STATE }
ok(s.failStreak === 0 && s.degraded === false, '初始态干净')
s = nextPollState(s, 'retryable')
ok(s.failStreak === 1 && s.degraded === false, '第 1 次失败：静默（保留快照）')
s = nextPollState(s, 'retryable')
ok(s.failStreak === 2 && s.degraded === false, '第 2 次失败：仍静默')
s = nextPollState(s, 'retryable')
ok(s.failStreak === 3 && s.degraded === true, '第 3 次失败：升错误态')
s = nextPollState(s, 'retryable')
ok(s.failStreak === 4 && s.degraded === true, '继续失败维持错误态')
s = nextPollState(s, 'ok')
ok(s.failStreak === 0 && s.degraded === false, '成功即清零恢复（滞后角标熄灭）')
const s0 = { ...INITIAL_POLL_STATE }
const sf = nextPollState(s0, 'not_found')
ok(sf.degraded === true, 'not_found 致命类立即错误态（不诱导重试）')
ok(sf.failStreak === 0, '致命类不累计 retryable 计数')
ok(nextPollState(s0, 'terminal').degraded === true, 'terminal 致命类立即错误态')

/* ---------------------------------- C. worstOutcome 同拍取最坏 */
section('C worstOutcome：列表+详情同拍取最坏')
ok(worstOutcome('ok', 'ok') === 'ok', 'ok+ok → ok')
ok(worstOutcome('ok', 'retryable') === 'retryable', 'ok+retryable → retryable')
ok(worstOutcome('retryable', 'not_found') === 'not_found', 'retryable+not_found → not_found')
ok(worstOutcome('ok', 'terminal') === 'terminal', 'ok+terminal → terminal')
ok(worstOutcome('not_found', 'terminal') === 'not_found' || worstOutcome('not_found', 'terminal') === 'terminal',
  '双致命类取其一（同级）')

/* ---------------------------------- D. 状态机纯度 */
section('D 状态机纯度：不改入参（函数式，便于推理）')
const prev = { failStreak: 2, degraded: false }
nextPollState(prev, 'retryable')
ok(prev.failStreak === 2 && prev.degraded === false, '入参状态对象不被原地修改')

console.log(`\nk i003_poll_health: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
