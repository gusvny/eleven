// reconcile UT：比对/降级/缺行覆盖两桶/集合指纹去重键语义（t261004-13）。
import { compareStates, degradedResult, makeMissingRowsSpec, ledgerCoverage, fnv1a8 } from '../src/host/reconcile.ts'
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
