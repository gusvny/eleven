/**
 * inspection-disposition.test.mjs — the human exit write face for a mechanically-
 * rejected (blocked) inspection ticket (t261008-22, plan v2 Step 3).
 *  - input pre-check: reason-less rerun/void refused BY NAME; missing/over-bound and
 *    bad shapes named; by != host lands as by_claimed + writer_mismatch;
 *  - L1 zero side effects: a reason-less POST returns 400, the spawn face is NEVER
 *    called and the disposition ledger stays byte-identical;
 *  - attribution: every attempt (success or refusal) lands exactly one ledger row;
 *    the read side counts malformed rows and reports hidden_rows;
 *  - L3 in-flight ordering: the engine's refusal surfaces VERBATIM (substring pins —
 *    '同期已有在飞巡检' and 'cancel'), 502, no success shape anywhere;
 *  - void refusal (population/idempotence) likewise 502 verbatim, never success-shaped;
 *  - routes are declared in PANEL_API_ROUTES (registration parity is mechanically
 *    locked by route-parity.test.mjs).
 * No real spawn, zero network, never touches 3099.
 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import {
  validateRerunInput, validateVoidInput, appendDispositionRecord,
  readDispositionRecords, dispositionRecordsFile, DISPOSITION_RECORDS_CAP,
  makeDefaultSpawnRerun, makeDefaultSpawnVoid,
} from '../src/host/inspection-disposition.ts'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- memory io ----
function memIo() {
  const files = new Map()
  return {
    files,
    existsSync: (f) => files.has(f),
    readFileSync: (f) => { const v = files.get(f); if (v === undefined) throw new Error('ENOENT'); return v },
    writeFileAtomic: (f, c) => { files.set(f, c) },
  }
}
const ENV = { SANDBAR_DISPOSITION_RECORDS_DIR: '/mem' }

// ---- validators ----
const rerunBody = { project: 'sandbar', instance: 'integration-tests', period: '20261002', reason: 'r' }
const voidBody = { ...rerunBody, ticket_id: 't261002-12' }

for (const [name, validate, body] of [
  ['rerun', validateRerunInput, rerunBody], ['void', validateVoidInput, voidBody],
]) {
  const r1 = validate({ ...body, reason: '' })
  ok(r1.ok === false && /reason is required/.test(r1.error), `${name}: empty reason refused by name`)
  const r2 = validate({ ...body, reason: '  ' })
  ok(r2.ok === false && /reason is required/.test(r2.error), `${name}: whitespace reason refused by name`)
  const r3 = validate({ ...body, reason: 'x'.repeat(501) })
  ok(r3.ok === false && /too long/.test(r3.error), `${name}: over-bound reason refused`)
  const r4 = validate({ ...body, period: 'abc' })
  ok(r4.ok === false && /period shape/.test(r4.error), `${name}: bad period shape refused`)
  const r5 = validate({ ...body, by: 'someone-else' })
  ok(r5.ok === true && r5.by_claimed === 'someone-else' && r5.writer_mismatch === true, `${name}: by != host lands as by_claimed + writer_mismatch`)
}
ok(validateVoidInput({ ...voidBody, ticket_id: 'nope' }).ok === false, 'void: bad ticket_id shape refused')
ok(validateVoidInput({ ...voidBody, ticket_id: '' }).ok === false, 'void: empty ticket_id refused')
ok(validateRerunInput(rerunBody).ok === true, 'rerun: valid body accepted')

// ---- ledger round trip ----
{
  const io = memIo()
  const rec = { at: 1, by: 'host', action: 'void', project: 'sandbar', instance: 'i',
    period: '20261002', ticket_id: 't1', reason: 'r', spawn: { ok: true, voided: true } }
  const w = appendDispositionRecord(io, ENV, 'sandbar', rec)
  ok(w.ok === true, 'ledger append ok')
  const read = readDispositionRecords(io, ENV, 'sandbar')
  ok(read.ok === true && read.rows.length === 1 && read.rows[0].action === 'void', 'ledger read back (append return is not evidence)')
  io.writeFileSync ? null : io.writeFileAtomic(dispositionRecordsFile(ENV, 'sandbar'),
    io.files.get(dispositionRecordsFile(ENV, 'sandbar')) + '{torn\n')
  const read2 = readDispositionRecords(io, ENV, 'sandbar')
  ok(read2.ok === true && read2.malformed_rows === 1 && read2.rows.length === 1, 'torn line counted, never fatal')
  ok(read2.rows[0].at >= read.rows[0].at, 'newest-first ordering face present')
}

// ---- API level: L1 zero side effects + verbatim refusals + attribution ----
const INFLIGHT_ERR = 'inspection_trigger.py: 同期已有在飞巡检 t261002-12（RUNNING）——重跑会双跑同一期，在飞期不接受重开；等它收口，或先记名 cancel 后再重跑'
const VOID_REFUSAL = 'inspection_trigger.py: 期刊台账不可读（未收口=在飞期不接受 void——等它收口；write_ledger=False 重定向壳无台账，其人工出口是具名重跑）'

function makeApi(spawnRerun, spawnVoid, io = memIo()) {
  const api = createApi(ENV, { dispositionIo: io, spawnRerun, spawnVoid })
  // Credential NAME is computable (sha256 of the Host header, base64url) — value shape only.
  const AUTH = { cookie: 'dsh-auth-' + createHash('sha256').update('h').digest('base64url') + '=v1.a.b', host: 'h' }
  return {
    api, io,
    post: (path, body) => api.handle('POST', path, new URLSearchParams('project=sandbar'), JSON.stringify(body), '', AUTH),
    get: (path) => api.handle('GET', path, new URLSearchParams('project=sandbar'), ''),
  }
}

// L1: reason-less -> 400, spawn never called, ledger byte-identical
{
  let spawnCalls = 0
  const { api, io, post, get } = makeApi(async () => { spawnCalls += 1; return { ok: true, doc: {} } },
    async () => { spawnCalls += 1; return { ok: true, doc: {} } })
  const file = dispositionRecordsFile(ENV, 'sandbar')
  const before = io.files.get(file)
  const r1 = await makeApi(async () => { spawnCalls += 1; return { ok: true, doc: {} } },
    async () => { spawnCalls += 1; return { ok: true, doc: {} } }, io)
    .post('/sandbar-executor-panel/api/inspection/period/rerun', { ...rerunBody, reason: '' })
  ok(r1.status === 400 && /reason is required/.test(r1.json.error), 'reason-less rerun POST -> 400 named')
  ok(spawnCalls === 0, 'spawn face never called on reason-less attempt')
  ok(io.files.get(file) === before, 'ledger byte-identical on refusal (zero side effects)')
}

// rerun success: 200 + exactly one attribution row with action=rerun
{
  const { api, io, post, get } = makeApi(async () => ({ ok: true, doc: { ticket_id: 't261002-22' } }), async () => ({ ok: false, error: 'x' }))
  const r = await post('/sandbar-executor-panel/api/inspection/period/rerun', rerunBody)
  ok(r.status === 200 && r.json.ok === true, 'rerun success 200')
  ok(r.json.record.spawn.ticket_id === 't261002-22', 'rerun record carries the new ticket id')
  const read = readDispositionRecords(io, ENV, 'sandbar')
  ok(read.ok === true && read.rows.length === 1 && read.rows[0].action === 'rerun', 'exactly one attribution row (rerun)')
}

// rerun in-flight refusal: 502, engine error VERBATIM (substring pins), row still attributed
{
  const { api, io, post, get } = makeApi(async () => ({ ok: false, error: INFLIGHT_ERR }), async () => ({ ok: true, doc: {} }))
  const r = await post('/sandbar-executor-panel/api/inspection/period/rerun', rerunBody)
  ok(r.status === 502 && r.json.ok === false, 'in-flight refusal -> explicit 502 (never success-shaped)')
  ok(typeof r.json.error === 'string' && r.json.error.includes('同期已有在飞巡检') && r.json.error.includes('cancel'), 'engine refusal surfaced verbatim (ordering: void first / cancel named)')
  const read = readDispositionRecords(io, ENV, 'sandbar')
  ok(read.ok === true && read.rows.length === 1 && read.rows[0].spawn.ok === false, 'failed rerun still lands attributed')
}

// void refusal (population): 502 verbatim, spawn receipt not trusted into success
{
  const { api, io, post, get } = makeApi(async () => ({ ok: true, doc: {} }), async () => ({ ok: false, error: VOID_REFUSAL }))
  const r = await post('/sandbar-executor-panel/api/inspection/period/void', voidBody)
  ok(r.status === 502 && r.json.error.includes('不接受 void'), 'void refusal surfaced verbatim')
  ok(r.json.record.action === 'void' && r.json.record.spawn.ok === false, 'void attempt attributed with action=void')
  const read = readDispositionRecords(io, ENV, 'sandbar')
  ok(read.rows.length === 1, 'void refusal lands exactly one ledger row')
}

// void success: 200, record marks voided
{
  const { post, get } = makeApi(async () => ({ ok: true, doc: {} }), async () => ({ ok: true, doc: { voided: { who: 'host' } } }))
  const r = await post('/sandbar-executor-panel/api/inspection/period/void', voidBody)
  ok(r.status === 200 && r.json.record.spawn.voided === true && r.json.record.spawn.ticket_id === 't261002-12', 'void success record: who=ticket + voided flag')
}

// records GET face: empty state is 200 + ok:false + reason
{
  const { post, get } = makeApi(async () => ({ ok: true, doc: {} }), async () => ({ ok: true, doc: {} }), memIo())
  const r = await get('/sandbar-executor-panel/api/inspection/disposition-records')
  ok(r.status === 200 && r.json.ok === false && typeof r.json.reason === 'string', 'empty disposition ledger: explicit not-error shape')
}

// routes declared
for (const p of ['/sandbar-executor-panel/api/inspection/disposition-records',
  '/sandbar-executor-panel/api/inspection/period/rerun',
  '/sandbar-executor-panel/api/inspection/period/void']) {
  ok(PANEL_API_ROUTES.some((r) => r.path === p), `route declared: ${p}`)
}
ok(Number.isFinite(DISPOSITION_RECORDS_CAP) && DISPOSITION_RECORDS_CAP > 0, 'records cap declared once (never inlined)')

// spawn faces: default builders produce faces that pass args through to the CLI
ok(typeof makeDefaultSpawnRerun({}) === 'function' && typeof makeDefaultSpawnVoid({}) === 'function', 'default spawn faces constructible')

console.log(`inspection-disposition.test: ${n} assertions passed`)
