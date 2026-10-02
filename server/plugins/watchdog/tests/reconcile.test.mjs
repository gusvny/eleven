// reconcile UT：比对/降级/缺行计数/N 键重响语义。
import { compareStates, degradedResult, makeMissingRowsSpec, countMissingRows } from '../src/host/reconcile.ts'
import { parseLedgerLine } from '../src/host/ledger-tail.ts'
import { ledgerLine, assert, done } from './lib.mjs'

let n = 0
const row = (ticket, stageState) => parseLedgerLine(ledgerLine({ ticket, stage_state: stageState }))
// 一致 / 不一致 / 看板缺票。
{
  const led = new Map([['t1', { stage: 'implement', stage_state: 'running' }], ['t2', { stage: 'review', stage_state: 'done' }]])
  const board = [{ id: 't1', stage: 'implement', stage_state: 'running' }, { id: 't2', stage: 'review', stage_state: 'done' }]
  assert(compareStates(led, board).length === 0, 'consistent states → no mismatch')
  const board2 = [{ id: 't1', stage: 'implement', stage_state: 'done' }, { id: 't2', stage: 'review', stage_state: 'done' }]
  const m = compareStates(led, board2)
  assert(m.length === 1 && m[0].ticket === 't1' && m[0].board_state === 'done', 'divergent state → mismatch with both sides')
  const board3 = [{ id: 't3', stage_state: 'x' }]
  const m2 = compareStates(led, board3)
  assert(m2.length === 2 && m2[0].board_state === '<absent>', 'ledger ticket absent from board = mismatch (board is truth)')
  const emptyLed = new Map()
  assert(compareStates(emptyLed, board2).length === 0, 'empty ledger vs board → not per-ticket mismatch (missing-rows face owns it)')
  n += 4
}
// 降级显式。
{
  const d = degradedResult('引擎不可达', 123)
  assert(d.state === 'degraded' && d.since === 123 && d.reason === '引擎不可达', 'board unreachable → explicit degraded with since+reason')
  n += 1
}
// 缺行计数与 N 键（覆盖 = 账本有行把票带到看板当前状态；落后仍算缺）。
{
  const board = [{ id: 't1', stage_state: 'running' }, { id: 't2', stage_state: 'running' }, { id: 't3', stage_state: 'running' }]
  const rows = [row('t1', 'running')]
  assert(countMissingRows(board, rows) === 2, 'missing rows = board tickets not carried to board state by ledger')
  const behind = [row('t1', 'review_plan')]
  assert(countMissingRows([board[0]], behind) === 1, 'ticket present but behind board state still counts as missing')
  assert(countMissingRows([], rows) === 0, 'empty board → zero missing (nothing to reconcile against)')
  const s5 = makeMissingRowsSpec('sandbar', 5)
  const s7 = makeMissingRowsSpec('sandbar', 7)
  assert(s5.rule === 'ledger_missing_rows' && s5.target === 'sandbar:5', 'missing-rows dedupe key carries N (N change = new key = re-alert)')
  assert(s5.target !== s7.target, 'N=5 vs N=7 are distinct keys')
  assert(s5.level === 'warn', 'missing rows default warn level')
  n += 5
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
  // 缺行计数消费过滤后的行：别家票不再恒等「缺行」。
  const led = [row('a', 'running')]
  assert(countMissingRows(kept, led) === 2, 'missing count now scoped to project (foreign tickets excluded)')
  n += 4}
done(n)
