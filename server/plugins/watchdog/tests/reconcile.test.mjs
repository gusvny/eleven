// reconcile UT：比对（t261009-61 scope 收窄）/降级/缺行覆盖两桶/集合指纹去重键语义（t261004-13）。
import { compareStates, degradedResult, makeMissingRowsSpec, ledgerCoverage, fnv1a8 } from '../src/host/reconcile.ts'
import { parseLedgerLine } from '../src/host/ledger-tail.ts'
import { ledgerLine, assert, done } from './lib.mjs'

let n = 0
const row = (ticket, stageState) => parseLedgerLine(ledgerLine({ ticket, stage_state: stageState }))
// 一致 / 不一致 / scope 收窄（t261009-61）。
{
  const led = new Map([['t1', { stage: 'implement', stage_state: 'running' }], ['t2', { stage: 'review', stage_state: 'done' }]])
  const board = [{ id: 't1', stage: 'implement', stage_state: 'running' }, { id: 't2', stage: 'review', stage_state: 'done' }]
  assert(compareStates(led, board).length === 0, 'consistent states → no mismatch')
  const board2 = [{ id: 't1', stage: 'implement', stage_state: 'done' }, { id: 't2', stage: 'review', stage_state: 'done' }]
  const m = compareStates(led, board2)
  assert(m.length === 1 && m[0].ticket === 't1' && m[0].board_state === 'done', 'divergent state → mismatch with both sides')
  // t261009-61 Class B：账本独有 id（归档/剪枝 workflow）不再逐票计——缺行面拥有可行动方向。
  const board3 = [{ id: 't3', stage_state: 'x' }]
  assert(compareStates(led, board3).length === 0, 'ledger-only history (no board row) is suppressed, missing-rows face owns the actionable direction')
  const emptyLed = new Map()
  assert(compareStates(emptyLed, board2).length === 0, 'empty ledger vs board → not per-ticket mismatch (missing-rows face owns it)')
  n += 4
}
// t261009-61：630 票形态归零 + 真在飞分歧保留。
{
  // Class A：279 张收尾票 status=closed、stage_state=awaiting vs 账本末段 merge → 全部不数。
  const closedRows = new Map(Array.from({ length: 279 }, (_, i) => [`t2609xx-${i}`, { stage: 'implement', stage_state: 'merge' }]))
  const closedBoard = Array.from({ length: 279 }, (_, i) => ({ id: `t2609xx-${i}`, stage_state: 'awaiting', status: 'closed' }))
  assert(compareStates(closedRows, closedBoard).length === 0, 'terminal state-word drift (closed+awaiting vs merge) is structural → 0 mismatches')
  // verified 同理。
  assert(compareStates(new Map([['v1', { stage_state: 'merge' }]]), [{ id: 'v1', stage_state: 'awaiting', status: 'verified' }]).length === 0, 'verified rows suppressed the same way')
  // Class B 混合形态：账本独有 dispatcher-scan id → 不数。
  const mixed = new Map([['dispatcher-scan-2026-09-28T14:14:16Z', { stage: 'scan', stage_state: 'scan' }], ['t9', { stage_state: 'running' }]])
  const mixedBoard = [{ id: 't9', stage_state: 'done' }]
  const mm = compareStates(mixed, mixedBoard)
  assert(mm.length === 1 && mm[0].ticket === 't9', 'mixed input returns only the actionable in-flight divergence (scan id dropped)')
  // 真在飞分歧仍在（level/文案不动，scope 修）。
  const live = compareStates(new Map([['t5', { stage_state: 'merge' }]]), [{ id: 't5', stage_state: 'running', status: 'dispatched' }])
  assert(live.length === 1 && live[0].board_state === 'running' && live[0].ledger_state === 'merge', 'real in-flight divergence (dispatched) still counts')
  // status 缺席的历史票保守按在飞：分叉照数（宁多看一眼，不假报平安）。
  const nostat = compareStates(new Map([['h1', { stage_state: 'merge' }]]), [{ id: 'h1', stage_state: 'awaiting' }])
  assert(nostat.length === 1, 'status-less board row stays conservative in-flight (divergence counted)')
  // 畸形输入不炸不数：缺 id / 两侧态空。
  const bad = new Map([['', { stage_state: 'x' }], ['t6', {}], ['t7', { stage_state: 'running' }]])
  const badBoard = [{ stage_state: 'y' }, { id: 't6', stage_state: '' }, { id: 't7', stage_state: 'running' }]
  assert(compareStates(bad, badBoard).length === 0, 'malformed rows (blank id, empty states) neither throw nor count')
  n += 7
}
// 降级显式。
{
  const d = degradedResult('引擎不可达', 123)
  assert(d.state === 'degraded' && d.since === 123 && d.reason === '引擎不可达', 'board unreachable → explicit degraded with since+reason')
  n += 1
}
// 缺行覆盖两桶（t261004-13）：覆盖 = 账本有该票任意一行；终态票缺口不进告警桶。
{
  const board = [
    { id: 't1', stage_state: 'running' },
    { id: 't2', stage_state: 'running' },
    { id: 'c1', stage_state: 'done', status: 'closed' },
    { id: 'v1', stage_state: 'done', status: 'verified' },
    { id: 'h1', stage_state: 'done' }, // 无 status 标签的历史票：保守按在飞算
  ]
  // 账本只有 c1 一行（状态落后于看板也不影响覆盖判定——分叉归 reconcile_mismatch）。
  const rows = [row('c1', 'review_plan')]
  const cov = ledgerCoverage(board, rows)
  assert(cov.in_flight_missing.join(',') === 't1,t2,h1', 'in-flight uncovered = board tickets with zero ledger rows (status-less kept in flight)')
  assert(cov.terminal_missing.join(',') === 'v1', 'terminal uncovered = closed/verified with zero ledger rows')
  // 账本有行但状态与看板分叉 → 仍算覆盖（旧口径的 145/150 假警根因）。
  const divergent = [{ id: 't1', stage_state: 'done' }]
  assert(ledgerCoverage(divergent, [row('t1', 'running')]).in_flight_missing.length === 0, 'ledger row with divergent state still covers (divergence belongs to reconcile_mismatch)')
  assert(ledgerCoverage([], rows).in_flight_missing.length === 0 && ledgerCoverage([], rows).terminal_missing.length === 0, 'empty board → both buckets empty')
  // 空白票 id 不计数（没有可报的对象）。
  assert(ledgerCoverage([{ stage_state: 'running' }], []).in_flight_missing.length === 0, 'board row without ticket id is not counted')
  n += 5
}
// 集合指纹去重键（t261004-13）：键带 N+集合指纹；同集合同键（与顺序无关），集合变则键变。
{
  const s = makeMissingRowsSpec('sandbar', ['t2', 't1'])
  assert(s.rule === 'ledger_missing_rows', 'rule name unchanged')
  assert(s.target === `sandbar:2:${fnv1a8('t1,t2')}`, 'target carries N plus sorted-set fingerprint')
  assert(makeMissingRowsSpec('sandbar', ['t1', 't2']).target === s.target, 'same set in a different order → same key (deterministic dedupe)')
  assert(makeMissingRowsSpec('sandbar', ['t1']).target !== s.target, 'different set → different key (a genuinely new gap re-fires)')
  assert(makeMissingRowsSpec('sandbar', ['t1', 't2', 't3']).target !== s.target, 'set growth → new key')
  assert(s.level === 'warn', 'missing rows default warn level')
  assert(/^[0-9a-f]{8}$/.test(fnv1a8('t1,t2')), 'fingerprint is 8 hex chars')
  assert(fnv1a8('') === '811c9dc5', 'FNV-1a offset basis for empty input (known vector)')
  assert(!/[者账缺]/.test(s.title + s.detail), 'alert copy is English (host order 260925), no Chinese on the face')
  n += 8
}
// 项目过滤（KI-180）：对账/缺行两侧必须同 scope——看板行裁到本项目。
{
  const { filterBoardRowsToProject } = await import('../src/host/reconcile.ts')
  const mixed = [
    { id: 'a', project: 'sandbar', stage_state: 'running' },
    { id: 'b', project: 'dengzhufpv', stage_state: 'running' },
    { id: 'c', stage_state: 'running' },            // 无 SA 标签的历史票
    { id: 'd', project: null, stage_state: 'running' },
  ]
  const kept = filterBoardRowsToProject(mixed, 'sandbar')
  assert(kept.length === 3 && kept.every(r => r.id !== 'b'), 'rows of other projects dropped; own + label-less kept')
  assert(filterBoardRowsToProject(mixed, 'dengzhufpv').map(r => r.id).join(',') === 'b,c,d', 'per-project scope keeps only own + label-less rows')
  assert(filterBoardRowsToProject([], 'sandbar').length === 0, 'empty board stays empty')
  // 缺行覆盖消费过滤后的行：别家票不再恒等「缺行」。
  const led = [row('a', 'running')]
  const cov = ledgerCoverage(kept, led)
  assert(cov.in_flight_missing.join(',') === 'c,d' && cov.terminal_missing.length === 0, 'coverage now scoped to project (foreign tickets excluded)')
  n += 4
}
done(n)
