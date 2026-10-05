// one-shot UT（t261004-30）：对象键词表 / 锁表解析与超时回收 / 持锁人释放 /
// 准入（held > cap；unlimited） / 全终态松锁（ok / throw） / 保留期清扫
// （7 天 / 删前摘要 / 被引用不删 / retention 0=不删） / 并发旋钮唯一读点 /
// config one_shot 块（缺省 / 合法声明 / 畸形 fail-closed / 未知键仍拒）。
// 全部走桩，零真实宿主、零 ~/.sandbar、零 3099/7233。
import {
  deriveObjectKey, parseLockTable, serializeLockTable, reclaimStaleLocks,
  releaseLock, admitUnit, readConcurrencyLimit, runOneShotUnit,
  readRuns, reapExpiredRuns, collectReferencedSessions, reapSessions,
  validateOneShotBlock,
  lockFilePath, runsPath, reapedPath, DEFAULT_LOCK_TIMEOUT_MS,
} from '../src/host/one-shot.ts'
import { parseWatchdogConfig } from '../src/host/config.ts'
import { assert, done, freshDir, cleanup } from './lib.mjs'

let n = 0
const T0 = 1_700_000_000_000
const DAY = 24 * 60 * 60 * 1000

// ---------- 对象键 ----------

{
  let r = deriveObjectKey({ kind: 'ticket', id: 't261004-19' })
  assert(r.ok && r.key === 'ticket:t261004-19', 'ticket key')
  r = deriveObjectKey({ kind: 'request', id: 'req-1-0001' })
  assert(r.ok && r.key === 'request:req-1-0001', 'request key')
  r = deriveObjectKey({ kind: 'alert', id: 'stall:sandbar' })
  assert(r.ok && r.key === 'alert:stall:sandbar', 'alert key with colon id')
  n += 4

  const bads = [
    { kind: 'widget', id: 'x', why: 'unknown kind' },
    { kind: 'ticket', id: '', why: 'empty id' },
    { kind: 'ticket', id: 'a b', why: 'whitespace id' },
    { kind: 'ticket', id: 'x'.repeat(121), why: 'overlong id' },
    { kind: 'ticket', id: 42, why: 'non-string id' },
  ]
  for (const b of bads) {
    assert(!deriveObjectKey(b).ok, 'malformed unit refused: ' + b.why)
    n += 1
  }
}

// ---------- 锁表 ----------

const LOCK = { object_key: 'ticket:t1', session_id: 's1', acquired_at: T0, heartbeat_at: T0 }
const table1 = { v: 1, locks: [LOCK] }

{
  const p = parseLockTable(serializeLockTable(table1))
  assert(p.ok && p.table.locks.length === 1, 'lock table round-trips')
  assert(!parseLockTable('not json').ok, 'malformed JSON refused')
  assert(!parseLockTable('{"v":2,"locks":[]}').ok, 'wrong version refused')
  assert(!parseLockTable('{"v":1,"locks":[{}]}').ok, 'malformed entry refused')
  n += 4

  // 超时回收：心跳新鲜留下，过期限摘除并点名。
  const fresh = reclaimStaleLocks(table1, T0 + DEFAULT_LOCK_TIMEOUT_MS - 1, DEFAULT_LOCK_TIMEOUT_MS)
  assert(fresh.reclaimed.length === 0 && fresh.table.locks.length === 1, 'fresh lock kept')
  const stale = reclaimStaleLocks(table1, T0 + DEFAULT_LOCK_TIMEOUT_MS + 1, DEFAULT_LOCK_TIMEOUT_MS)
  assert(stale.reclaimed.length === 1 && stale.table.locks.length === 0, 'stale lock reclaimed and named')
  assert(stale.reclaimed[0].includes('s1'), 'reclaim names the dead session')
  n += 3

  // 释放：持锁人可以，别人不行，没锁不行。
  const rel = releaseLock(table1, 'ticket:t1', 's1')
  assert(rel.ok && rel.table.locks.length === 0, 'holder releases')
  assert(!releaseLock(table1, 'ticket:t1', 's2').ok, 'non-holder cannot release')
  assert(!releaseLock(table1, 'ticket:none', 's1').ok, 'releasing an unheld object fails')
  n += 3

  // 准入：held > cap；不同对象并行；unlimited。
  const held = admitUnit({ objectKey: 'ticket:t1', table: table1, limit: 2, nowMs: T0 })
  assert(held.action === 'object-held', 'same object held while locked')
  const other = admitUnit({ objectKey: 'ticket:t2', table: table1, limit: 2, nowMs: T0 })
  assert(other.action === 'start', 'different object admitted (per-object, not global)')
  const capped = admitUnit({ objectKey: 'ticket:t3', table: { v: 1, locks: [LOCK, { ...LOCK, object_key: 'ticket:t2', session_id: 's2' }] }, limit: 2, nowMs: T0 })
  assert(capped.action === 'at-cap', 'cap blocks when full')
  const unlim = admitUnit({ objectKey: 'ticket:t3', table: { v: 1, locks: [LOCK, { ...LOCK, object_key: 'ticket:t2', session_id: 's2' }] }, limit: null, nowMs: T0 })
  assert(unlim.action === 'start', 'unlimited never caps')
  n += 4
}

// ---------- 编排：全终态松锁 ----------

function stubIo(files) {
  return {
    async readText(p) {
      if (!(p in files)) { const e = new Error('ENOENT ' + p); e.code = 'ENOENT'; throw e }
      return files[p]
    },
    async writeText(p, d) { files[p] = d },
    async append(p, line) { files[p] = (files[p] || '') + line },
  }
}

function stubSessions(impl) {
  let seq = 0
  return {
    async create() {
      if (impl.createFail) return { ok: false, error: impl.createFail }
      return { ok: true, sessionId: impl.sessionId || ('oneshot-' + (++seq)) }
    },
    async runTurn() {
      if (impl.throwInTurn) throw new Error(impl.throwInTurn)
      return { ok: !!impl.ok, summary: impl.summary || 'did the thing' }
    },
  }
}

async function lifecycle() {
  const files = {}
  const io = stubIo(files)
  const lock = lockFilePath('/d', 'p')
  const deps = { project: 'p', dataDir: '/d', cwd: '/proj', unit: { kind: 'ticket', id: 't1' }, limit: 2, io }

  // 正常路径：锁上→跑→松锁→落运行记录。
  let out = await runOneShotUnit({ ...deps, sessions: stubSessions({ ok: true }) , nowMs: T0 })
  assert(out.action === 'done' && out.outcome === 'ok', 'normal path done/ok')
  assert(JSON.parse(files[lock]).locks.length === 0, 'lock released on normal path')
  const runs = readRuns(files[runsPath('/d', 'p')])
  assert(runs.runs.length === 1 && runs.malformed_rows === 0, 'run record appended')
  n += 3

  // 回合抛错：锁仍释放（finally），outcome=failed，错误进 summary。
  out = await runOneShotUnit({ ...deps, sessions: stubSessions({ throwInTurn: 'boom' }), nowMs: T0 + 1 })
  assert(out.action === 'done' && out.outcome === 'failed' && out.summary.includes('boom'), 'throw path failed with reason')
  assert(JSON.parse(files[lock]).locks.length === 0, 'lock released on error path')
  n += 2

  // 同对象在飞：第二单不建会话（object-held）。
  const busyIo = stubIo(files)
  const busy = { project: 'p', dataDir: '/d', cwd: '/proj', unit: { kind: 'ticket', id: 't9' }, limit: 5, io: busyIo, sessions: stubSessions({ ok: true }), nowMs: T0 + 2 }
  const holder = await runOneShotUnit({ ...busy, sessions: stubSessions({ ok: true, sessionId: 'long-1' }) })
  assert(holder.action === 'done', 'long unit runs')
  // 手动把它顶住：写回一把未过期的锁。
  files[lock] = serializeLockTable({ v: 1, locks: [{ object_key: 'ticket:t9', session_id: 'long-1', acquired_at: T0 + 2, heartbeat_at: T0 + 2 }] })
  let creates = 0
  const counting = stubSessions({ ok: true })
  const origCreate = counting.create.bind(counting)
  counting.create = async (...a) => { creates += 1; return origCreate(...a) }
  out = await runOneShotUnit({ ...busy, sessions: counting })
  assert(out.action === 'object-held' && creates === 0, 'held object: no session created')
  n += 3

  // 满载：at-cap。
  files[lock] = serializeLockTable({ v: 1, locks: [
    { object_key: 'ticket:a', session_id: 's1', acquired_at: T0, heartbeat_at: T0 },
    { object_key: 'ticket:b', session_id: 's2', acquired_at: T0, heartbeat_at: T0 },
  ] })
  out = await runOneShotUnit({ ...busy, unit: { kind: 'ticket', id: 't3' }, limit: 2 })
  assert(out.action === 'at-cap', 'cap refuses with reason')
  n += 1

  // 死会话遗留锁：超时回收后放行。
  files[lock] = serializeLockTable({ v: 1, locks: [{ object_key: 'ticket:t9', session_id: 'dead', acquired_at: T0, heartbeat_at: T0 }] })
  out = await runOneShotUnit({ ...busy, lockTimeoutMs: 1000, nowMs: T0 + 2000 })
  assert(out.action === 'done', 'stale lock reclaimed, unit admitted')
  n += 1

  // 锁表损坏：fail-closed，不建会话不洗锁。
  files[lock] = 'not json'
  creates = 0
  out = await runOneShotUnit({ ...busy, sessions: counting })
  assert(out.action === 'refused' && out.reason.includes('not valid JSON') && creates === 0, 'corrupt lock table fail-closed')
  n += 2

  // 建会话失败：不上锁。
  files[lock] = serializeLockTable({ v: 1, locks: [] })
  out = await runOneShotUnit({ ...busy, sessions: stubSessions({ createFail: 'preset missing' }) })
  assert(out.action === 'refused' && out.reason.includes('preset missing'), 'create failure named')
  assert(JSON.parse(files[lock]).locks.length === 0, 'no lock written when create fails')
  n += 2
}
await lifecycle()

// ---------- 并发旋钮：唯一读点 ----------

{
  const files = {}
  const io = stubIo(files)
  const f = '/d/concurrency.json'
  let r = await readConcurrencyLimit(io, f)
  assert(r.ok && r.limit === 2 && r.source === 'default', 'absent declaration = default 2')
  io.writeText(f, JSON.stringify({ max_running: 5 }))
  r = await readConcurrencyLimit(io, f)
  assert(r.ok && r.limit === 5, 'declared 1-10 read')
  io.writeText(f, JSON.stringify({ max_running: 'unlimited' }))
  r = await readConcurrencyLimit(io, f)
  assert(r.ok && r.limit === null, 'unlimited = null (never caps)')
  io.writeText(f, JSON.stringify({ max_running: 11 }))
  assert(!(await readConcurrencyLimit(io, f)).ok, '11 refused')
  // admit: limit <= 0 = unlimited too (the declared form flows through).
  const unlimited0 = admitUnit({ objectKey: 'ticket:z', table: { v: 1, locks: [LOCK, { ...LOCK, object_key: 'ticket:y', session_id: 's9' }] }, limit: 0, nowMs: T0 })
  assert(unlimited0.action === 'start', 'limit 0 admits (unlimited)')
  io.writeText(f, JSON.stringify({ max_running: 0 }))
  r = await readConcurrencyLimit(io, f)
  assert(r.ok && r.limit === null, '0 = unlimited (declared form)')
  io.writeText(f, 'nope')
  assert(!(await readConcurrencyLimit(io, f)).ok, 'malformed declaration refused')
  n += 7
}

// ---------- 保留期清扫 ----------

async function retention() {
  const files = {}
  const io = stubIo(files)
  const runsFile = runsPath('/d', 'p')
  const reapedFile = reapedPath('/d', 'p')
  const rows = [
    { session_id: 'old-free', project: 'p', object_key: 'ticket:1', started_at: T0, ended_at: T0 - 10 * DAY, outcome: 'ok', summary: 'old, unreferenced' },
    { session_id: 'old-ref', project: 'p', object_key: 'ticket:2', started_at: T0, ended_at: T0 - 10 * DAY, outcome: 'ok', summary: 'old, referenced' },
    { session_id: 'new', project: 'p', object_key: 'ticket:3', started_at: T0, ended_at: T0 - 1 * DAY, outcome: 'failed', summary: 'recent' },
  ]
  const raw = rows.map((r) => JSON.stringify(r) + '\n').join('') + 'garbage line\n'
  const refs = collectReferencedSessions([['old-ref'], null, []])
  assert(refs.size === 1 && refs.has('old-ref'), 'reference union collects and skips null')
  n += 1

  let out = await reapExpiredRuns(io, { runsRaw: raw, runsFile, reapedFile, nowMs: T0, retentionDays: 7, referencedSessionIds: refs })
  assert(out.deleted === 1 && out.kept_referenced === 1 && out.summaries_written === 1, 'reap: only old unreferenced deleted')
  assert(out.malformed_rows === 1, 'malformed row counted')
  const kept = readRuns(files[runsFile])
  assert(kept.runs.length === 2 && kept.runs.some(r => r.session_id === 'old-ref') && kept.runs.some(r => r.session_id === 'new'), 'referenced and recent kept')
  const summary = JSON.parse(files[reapedFile].trim().split('\n').pop())
  assert(summary.type === 'one-shot-reap-summary' && summary.session_id === 'old-free' && summary.summary === 'old, unreferenced', 'summary written before delete')
  n += 4

  // retention_days = 0 = 永不删。
  out = await reapExpiredRuns(io, { runsRaw: raw, runsFile, reapedFile, nowMs: T0, retentionDays: 0, referencedSessionIds: new Set() })
  assert(out.deleted === 0, 'retention 0 never deletes')
  n += 1
}
await retention()

// ---------- 纯清扫决策（reapSessions，harness seam 同源） ----------

{
  const refs = new Set(['os-2'])
  let r = reapSessions({ sessions: [
    { session_id: 'os-1', ended_at: T0 - 10 * DAY },
    { session_id: 'os-2', ended_at: T0 - 10 * DAY },
    { session_id: 'os-3', ended_at: T0 - 1 * DAY },
  ], nowMs: T0, retentionDays: 7, referencedSessionIds: refs, summarizeOk: true })
  assert(JSON.stringify(r.deleted) === '["os-1"]' && JSON.stringify(r.summaries) === '["os-1"]', 'reapSessions deletes the expired unreferenced one, summary first')
  assert(r.skipped.length === 0, 'nothing skipped when summaries ok')
  r = reapSessions({ sessions: [{ session_id: 'os-9', ended_at: T0 - 10 * DAY }], nowMs: T0, retentionDays: 7, referencedSessionIds: new Set(), summarizeOk: false })
  assert(r.deleted.length === 0 && r.skipped[0] === 'os-9', 'summarize failure skips, never deletes')
  r = reapSessions({ sessions: [{ session_id: 'os-9', ended_at: T0 - 10 * DAY }], nowMs: T0, retentionDays: 0, referencedSessionIds: new Set(), summarizeOk: true })
  assert(r.deleted.length === 0, 'retention 0 never reaps')
  n += 4
}

// ---------- one_shot 块纯校验（harness oneshot_config 同源） ----------

{
  assert(validateOneShotBlock({ enabled: true, retention_days: 7, lock_timeout_ms: 1 }).ok, 'factory keys accepted')
  const bad = validateOneShotBlock({ enabled: true, parallel_cap: 4 })
  assert(!bad.ok && bad.error.includes('parallel_cap'), 'a cap hiding in one_shot is refused (no second knob)')
  assert(!validateOneShotBlock('x').ok, 'non-object refused')
  n += 3
}

// ---------- config one_shot 块 ----------

{
  const f = 'watchdog.json'
  let r = parseWatchdogConfig('{}', f)
  assert(r.config_error === null, 'empty declaration valid')
  assert(r.config.one_shot.enabled === true && r.config.one_shot.retention_days === 7 && r.config.one_shot.lock_timeout_ms === DEFAULT_LOCK_TIMEOUT_MS, 'one_shot factory defaults')
  r = parseWatchdogConfig('{"one_shot":{"enabled":false,"retention_days":14,"lock_timeout_ms":60000}}', f)
  assert(r.config_error === null && r.config.one_shot.enabled === false && r.config.one_shot.retention_days === 14 && r.config.one_shot.lock_timeout_ms === 60000, 'one_shot declared values parsed with provenance')
  assert(r.provenance.keys['one_shot.retention_days'] === 'watchdog.json#one_shot.retention_days', 'one_shot provenance recorded')
  assert(parseWatchdogConfig('{"one_shot":{"retention_days":-1}}', f).config_error !== null, 'negative retention refused')
  assert(parseWatchdogConfig('{"one_shot":{"lock_timeout_ms":0}}', f).config_error !== null, 'zero lock timeout refused')
  assert(parseWatchdogConfig('{"one_shot":{"enabled":"yes"}}', f).config_error !== null, 'non-boolean enabled refused')
  assert(parseWatchdogConfig('{"one_shot":[]}', f).config_error !== null, 'non-object one_shot refused')
  assert(parseWatchdogConfig('{"one_shot_k":1}', f).config_error !== null, 'unknown top-level key still fail-closed')
  n += 8
}

cleanup([freshDir('unused-')])
done(n)
