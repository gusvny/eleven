// ledger-tail UT：解析畸形族 / 增量 / 轮转不丢行（归档收残余）/ idem 去重 / FIFO / 不可读显式。
import { LedgerTailer, parseLedgerLine, deriveTicketStates, freshTailState } from '../src/host/ledger-tail.ts'
import { memTailIo, ledgerLine, assert, done } from './lib.mjs'

let n = 0
const ACTIVE = '/ledg/sandbar.jsonl'
const P = '/ledg'

// 解析畸形族。
{
  assert(parseLedgerLine(ledgerLine()) !== null, 'parse good line')
  assert(parseLedgerLine('{broken') === null, 'parse bad JSON → null')
  assert(parseLedgerLine('') === null, 'parse empty line → null')
  assert(parseLedgerLine('[]') === null, 'parse array → null')
  assert(parseLedgerLine(ledgerLine({ __drop: ['idem'] })) === null, 'parse missing idem → null')
  assert(parseLedgerLine(ledgerLine({ __drop: ['ticket'] })) === null, 'parse missing ticket → null')
  assert(parseLedgerLine(ledgerLine({ seq: 'x' })) === null, 'parse non-numeric seq → null')
  n += 7
}
// 增量 + 断行（半行等下次）。
{
  const files = { [ACTIVE]: { ino: 1, content: ledgerLine({ seq: 1 }) + '\n' + ledgerLine({ seq: 2, ticket: 't2' }) + '\n' } }
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  const o1 = await t.poll()
  assert(o1.rows.length === 2 && o1.unreadable === null, 'initial poll reads whole file')
  files[ACTIVE].content += ledgerLine({ seq: 3, ticket: 't3' }).slice(0, 10) // 半行
  const o2 = await t.poll()
  assert(o2.rows.length === 0 && o2.malformed === 0, 'half line waits for completion (offset at line boundary)')
  files[ACTIVE].content = files[ACTIVE].content // no-op
  files[ACTIVE].content += ledgerLine({ seq: 3, ticket: 't3' }).slice(10) + '\n'
  const o3 = await t.poll()
  assert(o3.rows.length === 1 && o3.rows[0].ticket === 't3', 'completed line consumed next poll')
  assert(t.state.offset === files[ACTIVE].content.length, 'watermark offset tracks file end')
  n += 4
}
// idem 去重（at-least-once 重投不成第二行）。
{
  const line = ledgerLine({ seq: 1 })
  const files = { [ACTIVE]: { ino: 1, content: line + '\n' + line + '\n' + line + '\n' } }
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  const o = await t.poll()
  assert(o.rows.length === 1 && o.dupes === 2 && t.state.dupesSkipped === 2, 'duplicate idem deduped, counted not swallowed silently')
  n += 1
}
// 轮转不丢行：活动被 rename（新 inode），残余行在归档里收齐。
{
  const ARCH = P + '/20260928-120000-ab.jsonl'
  const files = {
    [ACTIVE]: { ino: 1, content: ledgerLine({ seq: 1 }) + '\n' },
  }
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  await t.poll()
  // 轮转：旧文件带残余进归档，新活动文件 inode=2 从空开始。
  files[ARCH] = { ino: 1, content: ledgerLine({ seq: 1 }) + '\n' + ledgerLine({ seq: 2, ticket: 't2' }) + '\n' }
  files[ACTIVE] = { ino: 2, content: '' }
  const o = await t.poll()
  assert(o.rotated === true, 'rotation detected via inode change')
  assert(o.rows.length === 1 && o.rows[0].ticket === 't2', 'rotation-drain recovers residual row from archive (no silent loss)')
  assert(t.state.offset === 0, 'offset resets to new active file')
  files[ACTIVE].content += ledgerLine({ seq: 3, ticket: 't3' }) + '\n'
  const o2 = await t.poll()
  assert(o2.rows.length === 1 && o2.rows[0].ticket === 't3', 'new active file tailed normally after rotation')
  n += 4
}
// 轮转但归档收不到 → 显式未决位（不静默当没丢）。
{
  const files = { [ACTIVE]: { ino: 1, content: ledgerLine() + '\n' } }
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  await t.poll()
  files[ACTIVE] = { ino: 2, content: '' } // 无归档可收
  const o = await t.poll()
  assert(t.state.unresolvedRotateTail === true, 'undrained rotation leaves explicit unresolved flag')
  assert(o.rotated === true, 'rotation still reported')
  n += 2
}
// 不可读：显式 unreadable，状态不动（下轮重试）。
{
  const files = {}
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  const o = await t.poll()
  assert(o.unreadable !== null && o.rows.length === 0, 'missing ledger = explicit unreadable (not all-fine)')
  files[ACTIVE] = { ino: 1, content: ledgerLine() + '\n' }
  const o2 = await t.poll()
  assert(o2.rows.length === 1 && o2.unreadable === null, 'recovers once file appears')
  n += 2
}
// FIFO 逐出：seen 集有界，逐出后重投行不压制成新行? ——不，逐出后重投会再收（多计一次）
// 这与 event_ledger.py 语义一致：cap 是纯加速器，只可能多读不可能错压制。
{
  const t = new LedgerTailer(P, 'sandbar', memTailIo({ [ACTIVE]: { ino: 1, content: '' } }), 2)
  const files = { [ACTIVE]: { ino: 1, content: '' } }
  files[ACTIVE].content = [1, 2, 3].map(s => ledgerLine({ seq: s, ticket: 't' + s })).join('\n') + '\n'
  await t.poll()
  assert(t.state.seen.size <= 2, 'seen set bounded by cap')
  n += 1
}
// 真源行形状（ts ISO 字符串，对齐 event_ledger.py 落盘字段）→ last_row_at 可填充。
{
  const line = JSON.stringify({ v: 'event-ledger-v1', project: 'p', ticket: 't9', run_id: 'r1', seq: 1, stage: 'implement', stage_state: 'running', ts: '2026-09-28T10:00:00+08:00', idem: 'p|t9|r1|1' })
  const files = { [ACTIVE]: { ino: 1, content: line + '\n' } }
  const t = new LedgerTailer(P, 'sandbar', memTailIo(files))
  const o = await t.poll()
  assert(o.rows.length === 1 && t.state.lastRowAt === Date.parse('2026-09-28T10:00:00+08:00'), 'real ledger shape (ts ISO) fills lastRowAt (CF-1)')
  const badTs = JSON.stringify({ v: 'x', project: 'p', ticket: 't9', run_id: 'r1', seq: 2, ts: 'not-a-date', idem: 'p|t9|r1|2' })
  files[ACTIVE].content += badTs + '\n'
  await t.poll()
  assert(t.state.lastRowAt === Date.parse('2026-09-28T10:00:00+08:00'), 'unparsable ts = row valid, timestamp not faked')
  n += 2
}
// 推演态。
{
  const rows = [parseLedgerLine(ledgerLine({ seq: 1, ticket: 't1', stage_state: 'running' })), parseLedgerLine(ledgerLine({ seq: 2, ticket: 't1', stage_state: 'done' }))]
  const m = deriveTicketStates(rows)
  assert(m.get('t1').stage_state === 'done', 'derive keeps latest state per ticket')
  n += 1
}
done(n)
