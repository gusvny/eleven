#!/usr/bin/env node
/**
 * ki025_show_error_split.mjs —— ticket show 失败 HTTP 分级裁定单测（t260903-06 KI-025）。
 *
 * 被测：src/host/ticket-error.ts（node.ts sendTicketShowError 的裁定核心，纯函数）。
 * 覆盖（方案验收口径：404 只能由明确 NotFound 语义触发）：
 *   A. kind=not_found → 404（唯一「不存在」来源）。
 *   B. kind=transient → 503 + retryable（UI 据此保留快照静默重试）。
 *   C. kind=terminal → 410（终态永久，刷新无效）。
 *   D. kind=internal / 缺失 / 未知值 / 非字符串 → 500 非 404
 *      （kind 断链时宁可「读取失败」绝不谎报不存在——默认分支非 404 是硬口径）。
 *
 * 直跑：node server/plugins/workbench/tests/ki025_show_error_split.mjs
 * 全链路（client kind 产出 → ticket.py QueryError → tools_registry 并入）归
 * integration/t260903-06/sc_query_kind_no_lie.py；本文件守 node 消费端的分流面。
 */
import { ticketShowHttpVerdict } from '../src/host/ticket-error.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('A not_found → 404（唯一不存在语义）')
{
  const v = ticketShowHttpVerdict('not_found')
  ok(v.status === 404 && v.retryable === false, '404 且不可重试')
}

section('B transient → 503 + retryable')
{
  const v = ticketShowHttpVerdict('transient')
  ok(v.status === 503 && v.retryable === true, '503 且 retryable（UI 保留快照静默重试的判据）')
}

section('C terminal → 410（永久，刷新无效）')
{
  const v = ticketShowHttpVerdict('terminal')
  ok(v.status === 410 && v.retryable === false, '410 且不可重试（死票不得诱导重试）')
}

section('D internal/缺失/未知 → 500 非 404（默认分支硬口径）')
{
  for (const k of ['internal', '', undefined, null, 'weird-unknown', 42, {}]) {
    const v = ticketShowHttpVerdict(k)
    ok(v.status === 500 && v.retryable === false,
       `kind=${JSON.stringify(k) ?? 'undefined'} → 500 非 404`)
  }
}

console.log(`\nki025_show_error_split: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
