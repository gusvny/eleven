/**
 * inspection-triggers.test.mjs — on-demand trigger write face tests (t261006-15, plan D3/D4).
 *  - input pre-check: named-criterion refusals (missing fields / blank / bad shape / over-bound; non-JSON body at the API layer);
 *  - attribution: writer fixed 'host'; a body by != host lands as by_claimed + writer_mismatch;
 *  - ledger: atomic append (tmp->rename); reader-side round trip (the row is read BACK —
 *    the append return value is not acceptance evidence); malformed rows counted; cap + hidden count;
 *  - spawn face (stub): good receipt (with ticket_id) / non-JSON receipt / non-{ok:true} receipt /
 *    non-zero exit / throw — all explicit failures with a reason; a failed trigger still lands attributed + 502;
 *  - KI-193: a credential-less POST is 401 and the ledger stays byte-identical (API-level assertion).
 * No real workflow spawn, zero network, never touches 3099.
 */
import assert from 'node:assert/strict'
import {
  validateTriggerInput, appendTriggerRecord, readTriggerRecords, triggerRecordsFile,
  TRIGGER_RECORDS_CAP, makeDefaultSpawnTrigger,
} from '../src/host/inspection-triggers.ts'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- memory io stub (atomic write is just set; readTail reads the tail) ----
function memIo() {
  const files = new Map()
  return {
    files,
    existsSync: (f) => files.has(f),
    readFileSync: (f) => { if (!files.has(f)) throw new Error('ENOENT'); return files.get(f) },
    writeFileAtomic: (f, c) => files.set(f, c),
    readTail: (f, max) => { const t = files.get(f) ?? ''; return t.length > max ? t.slice(t.length - max) : t },
  }
}

// ---- validation (named criterion) ----
for (const [body, frag] of [
  [null, 'JSON object'],
  ['x', 'JSON object'],
  [{}, 'project is required'],
  [{ project: 'BAD_KEY' }, 'project shape is invalid'],
  [{ project: 'sandbar' }, 'instance is required'],
  [{ project: 'sandbar', instance: 'BAD!' }, 'instance shape is invalid'],
  [{ project: 'sandbar', instance: 'integration-tests' }, 'scope is required'],
  [{ project: 'sandbar', instance: 'integration-tests', scope: '  ' }, 'scope is required'],
  [{ project: 'sandbar', instance: 'integration-tests', scope: 's'.repeat(201) }, 'scope is too long'],
  [{ project: 'sandbar', instance: 'integration-tests', scope: 'all' }, 'reason is required'],
  [{ project: 'sandbar', instance: 'integration-tests', scope: 'all', reason: ' '.repeat(3) }, 'reason is required'],
  [{ project: 'sandbar', instance: 'integration-tests', scope: 'all', reason: 'r'.repeat(501) }, 'reason is too long'],
]) {
  const v = validateTriggerInput(body)
  ok(v.ok === false && v.error.includes(frag), `named-criterion rejection: ${frag}`)
}
const good = validateTriggerInput({ project: 'sandbar', instance: 'integration-tests', scope: 'server/plugins only', reason: 'check the new panel code' })
ok(good.ok === true && good.value.instance === 'integration-tests', 'valid input accepted')
const spoof = validateTriggerInput({ project: 'sandbar', instance: 'simplify', scope: 'all', reason: 'r', by: 'executor' })
ok(spoof.ok === true && spoof.by_claimed === 'executor' && spoof.writer_mismatch === true, 'by spoof lands as by_claimed + writer_mismatch')

// ---- ledger append + reader-side round trip ----
const io = memIo()
const env = { SANDBAR_TRIGGER_RECORDS_DIR: '/tmp/t261006-15-test' }
const rec = {
  at: 1000, by: 'host', project: 'sandbar', instance: 'integration-tests',
  scope: 'server/plugins only', reason: 'check the new panel code', spawn: { ok: true, ticket_id: 'inspection-integration-tests-20261006' },
}
const w = appendTriggerRecord(io, env, 'sandbar', rec)
ok(w.ok === true, 'append ok')
// Reader-side acceptance: read it BACK through the read model (not the append return).
const r1 = readTriggerRecords(io, env, 'sandbar')
ok(r1.ok === true && r1.rows.length === 1, 'reader-side round trip: row read back')
ok(r1.rows[0].reason === 'check the new panel code' && r1.rows[0].spawn.ticket_id === 'inspection-integration-tests-20261006', 'row fields survive the round trip')
ok(r1.malformed_rows === 0 && r1.hidden_rows === 0, 'clean read counters')

// Newest first; malformed rows never enter the list but are counted (NaN serializes
// to null by JSON, a non-host writer fails the validity gate, torn lines fail parse).
appendTriggerRecord(io, env, 'sandbar', { ...rec, at: 2000 })
appendTriggerRecord(io, env, 'sandbar', { ...rec, at: NaN })
appendTriggerRecord(io, env, 'sandbar', { ...rec, at: 1500, by: 'not-host' })
io.files.set(triggerRecordsFile(env, 'sandbar'), io.files.get(triggerRecordsFile(env, 'sandbar')) + '\n{"torn json\n')
const r2 = readTriggerRecords(io, env, 'sandbar')
ok(r2.ok === true && r2.rows.map(x => x.at).join(',') === '2000,1000', 'newest first (malformed rows excluded from the list)')
ok(r2.malformed_rows === 3, `malformed rows counted, not dropped (${r2.malformed_rows})`)

// Cap from the contract + hidden counter.
const io2 = memIo()
for (let i = 0; i < TRIGGER_RECORDS_CAP + 3; i++) {
  appendTriggerRecord(io2, env, 'p', { ...rec, at: i })
}
const r3 = readTriggerRecords(io2, env, 'p')
ok(r3.rows.length === TRIGGER_RECORDS_CAP && r3.hidden_rows === 3, `cap ${TRIGGER_RECORDS_CAP} honored with hidden counter`)
ok(r3.rows[0].at === TRIGGER_RECORDS_CAP + 2, 'cap keeps the newest rows')

// Absent file = named empty state (not an error).
const r4 = readTriggerRecords(io, env, 'no-such-project')
ok(r4.ok === false && /no trigger record yet/.test(r4.reason), 'absent record file = named empty state')

// ---- API layer: routes parity, 401 without credential, trigger flow ----
ok(PANEL_API_ROUTES.some(r => r.path === '/sandbar-executor-panel/api/inspection/trigger'), 'trigger route declared')
ok(PANEL_API_ROUTES.some(r => r.path === '/sandbar-executor-panel/api/inspection/trigger-records'), 'records route declared')

const apiIo = memIo()
const api = createApi({ SANDBAR_TRIGGER_RECORDS_DIR: '/tmp/t261006-15-test' }, {
  triggerIo: apiIo,
  authFace: ({ cookie }) => cookie === 'good' ? { ok: true, why: '' } : { ok: false, why: 'no credential' },
  now: () => 42,
  spawnTrigger: async () => ({ ok: true, ticket_id: 'inspection-simplify-20261006' }),
})

// 401: nothing written, byte-for-byte.
const body = JSON.stringify({ project: 'sandbar', instance: 'simplify', scope: 'all', reason: 'why' })
const un = await api.handle('POST', '/sandbar-executor-panel/api/inspection/trigger', new URLSearchParams(''), body, '', {})
ok(un.status === 401, 'POST without credential is 401')
ok(apiIo.files.size === 0, '401 writes nothing')

// Malformed body shapes -> named 400, nothing written.
for (const raw of ['not json', '{}', '{"project":"sandbar"}']) {
  const res = await api.handle('POST', '/sandbar-executor-panel/api/inspection/trigger', new URLSearchParams(''), raw, '', { cookie: 'good' })
  ok(res.status === 400, `malformed body 400 (${raw.slice(0, 20)})`)
}
ok(apiIo.files.size === 0, 'rejections write nothing')

// Happy path: spawn ok -> record appended, GET reads it back.
const good2 = await api.handle('POST', '/sandbar-executor-panel/api/inspection/trigger', new URLSearchParams(''), body, '', { cookie: 'good' })
ok(good2.status === 200 && good2.json.ok === true, 'trigger accepted')
ok(good2.json.record.by === 'host' && good2.json.record.at === 42, 'record attributed: writer + when')
const back = await api.handle('GET', '/sandbar-executor-panel/api/inspection/trigger-records', new URLSearchParams('project=sandbar'), '', '', {})
ok(back.status === 200 && back.json.rows.length === 1 && back.json.rows[0].reason === 'why', 'reader-side acceptance via GET')

// Spawn failure -> still recorded (attempt is attributed), explicit 502.
const apiFail = createApi({ SANDBAR_TRIGGER_RECORDS_DIR: '/tmp/t261006-15-test2' }, {
  triggerIo: memIo(),
  authFace: () => ({ ok: true, why: '' }),
  now: () => 7,
  spawnTrigger: async () => ({ ok: false, error: 'inspection_trigger.py: instance simplify is not enabled in the declaration' }),
})
const fail = await apiFail.handle('POST', '/sandbar-executor-panel/api/inspection/trigger', new URLSearchParams(''), body, '', { cookie: 'good' })
ok(fail.status === 502 && /not enabled/.test(fail.json.error), 'failed trigger is an explicit 502 with the named error')
ok(fail.json.record.spawn.ok === false && fail.json.record.reason === 'why', 'failed attempt still lands attributed')

// GET records for a malformed project key -> named 400.
const badKey = await api.handle('GET', '/sandbar-executor-panel/api/inspection/trigger-records', new URLSearchParams('project=BAD'), '', '', {})
ok(badKey.status === 400 && /project/.test(badKey.json.error), 'records GET validates project shape')

// ---- default spawn face receipt validation (no real python needed: use a fake script) ----
{
  const tmpScript = '/tmp/t261006-15-fake-trigger.sh'
  const { writeFileSync, chmodSync } = await import('node:fs')
  const { spawn } = await import('node:child_process')
  // Fake "python": a shell script; face is given the interpreter explicitly.
  writeFileSync(tmpScript, '#!/bin/sh\necho \'{"ok": true, "result": {"ticket_id": "inspection-integration-tests-20261006"}}\'\n')
  chmodSync(tmpScript, 0o755)
  const face = makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript })
  const r = await face({ project: 'sandbar', instance: 'integration-tests', scope: 'all', reason: 'r' })
  ok(r.ok === true && r.ticket_id === 'inspection-integration-tests-20261006', 'good receipt parsed, ticket_id extracted')

  writeFileSync(tmpScript, '#!/bin/sh\necho "not json at all"\n')
  const r2 = await makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r2.ok === false && /receipt/.test(r2.error), 'non-JSON receipt refused with reason')

  writeFileSync(tmpScript, '#!/bin/sh\necho \'{"ok": false, "error": "instance i is not enabled"}\'\nexit 1\n')
  const r3 = await makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r3.ok === false && /not enabled/.test(r3.error), 'tool-named error surfaced verbatim')

  writeFileSync(tmpScript, '#!/bin/sh\necho "to stderr" >&2\nexit 3\n')
  const r4 = await makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r4.ok === false && /failed/.test(r4.error), 'non-zero exit named')

  writeFileSync(tmpScript, '#!/bin/sh\nexit 7\n')
  const r5 = await makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r5.ok === false, 'silent non-zero exit still explicit failure')

  writeFileSync(tmpScript, '#!/bin/sh\nsleep 5\n')
  const r6 = await makeDefaultSpawnTrigger({}, { python: '/bin/sh', script: tmpScript, timeoutMs: 150 })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r6.ok === false && /failed|receipt|exit/i.test(r6.error), 'timeout path terminates and resolves (no hang)')

  // Missing interpreter -> spawn error path resolves, never throws.
  const r7 = await makeDefaultSpawnTrigger({}, { python: '/nonexistent-python-bin', script: tmpScript })({ project: 'p', instance: 'i', scope: 's', reason: 'r' })
  ok(r7.ok === false && /failed/.test(r7.error), 'missing interpreter = explicit failure')
  void spawn
}


// ---- first-use on a fresh project: the append face creates the directory (arbitrate
// gen0 Red 2) — real fs, paths under this test's tmp dir ----
{
  const os = await import('node:os')
  const path = await import('node:path')
  const fsm = await import('node:fs')
  const root = fsm.mkdtempSync(path.join(os.tmpdir(), 'insp-first-use-'))
  try {
    const env2 = { SANDBAR_PROJECTS_DIR: root }
    const fsIo = (await import('../src/host/inspection-triggers.ts')).fsTriggerIo
    const rec2 = { at: 1, by: 'host', project: 'sandbar', instance: 'integration-tests', scope: 'all', reason: 'first use', spawn: { ok: true } }
    const w2 = appendTriggerRecord(fsIo, env2, 'sandbar', rec2)
    ok(w2.ok === true, 'first append on a fresh project succeeds (directory created)')
    ok(fsm.existsSync(path.join(root, 'sandbar', 'inspection', 'trigger-records.jsonl')), 'record file exists at <projects>/<key>/inspection/')
    const r5 = readTriggerRecords(fsIo, env2, 'sandbar')
    ok(r5.ok === true && r5.rows.length === 1 && r5.rows[0].reason === 'first use', 'reader-side round trip on the fresh project')
  } finally {
    fsm.rmSync(root, { recursive: true, force: true })
  }
}

console.log(`inspection-triggers.test: ${n} checks passed`)
