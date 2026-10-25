/**
 * t261025-12-cert-controls-route.test.mjs — the two certification controls'
 * API routes (ruling: executor-operational-envelope-v1 §5), with every engine
 * face STUBBED (a unit test never spawns the engine, Temporal, docker or 3099).
 *
 * Queue contract:
 *  - POST behind the KI-193 gate (credential-less = 401, before anything runs);
 *  - idempotent: a present marker answers already_queued; a concurrent second
 *    click loses the exclusive-create race at the filesystem (EEXIST) and gets
 *    the same answer — two clicks cannot queue two rounds;
 *  - every act (and every failed attempt) is recorded: at, by='host',
 *    by_claimed + writer_mismatch when the caller claims otherwise;
 *  - a failed marker write is an explicit 502 carrying the attribution row;
 *  - the queue-records GET reads the account back; malformed rows are counted.
 * Promote contract:
 *  - empty signer / missing line refused by name (400) BEFORE any write;
 *  - the engine's refusal travels VERBATIM (502) — never genericized;
 *  - the answer is the LEDGER read-back row; write-ok-but-read-back-empty or
 *    a different id is an explicit 502, never an optimistic guess.
 */
import { assert, done } from './lib.mjs'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0
const QUEUE = '/sandbar-executor-panel/api/certification/queue'
const QREC = '/sandbar-executor-panel/api/certification/queue-records'
const PROMOTE = '/sandbar-executor-panel/api/certification/promote'
const authPass = { authFace: () => ({ ok: true, why: '' }) }

// the three routes are registered (the route-parity lock keeps guarding both sides)
for (const [p, m] of [[QUEUE, 'POST'], [QREC, 'GET'], [PROMOTE, 'POST']]) {
  const e = PANEL_API_ROUTES.find((r) => r.path === p)
  assert(e !== undefined && e.methods.length === 1 && e.methods[0] === m, `route ${p} registered ${m}-only`)
  n++
}
function memQueueIo() {
  const files = new Map()
  return {
    files,
    existsSync: (f) => files.has(f),
    readFileSync: (f) => { const v = files.get(f); if (v === undefined) throw new Error('ENOENT'); return v },
    writeFileAtomic: (f, c) => files.set(f, c),
    writeMarkerExclusive: (f, c) => {
      if (files.has(f)) {
        const e = new Error('EEXIST')
        e.code = 'EEXIST'
        throw e
      }
      files.set(f, c)
    },
    mkdirSync: () => {},
  }
}

const state = () => ({
  ok: true, project: 'proj-x',
  marker: { present: false, path: '/store/proj-x/ledger/line-round-force' },
  guard: { held: false, path: '/store/proj-x/ledger/tick-anchor' },
  in_flight: { running: false, run: null, note: null },
  runners: [{ line: 'develop-buffer', state: 'resolvable' }],
})

function queueApi(io, extra = {}) {
  return createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certQueueIo: io,
    certQueueState: async () => state(),
    ...extra,
  })
}

// ---- queue: happy path + attribution + wait face ----
{
  const io = memQueueIo()
  const api = queueApi(io)
  const r = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  assert(r.status === 200 && r.json.ok === true && r.json.state === 'queued', 'first click queues: 200 queued')
  assert(io.files.has('/store/proj-x/ledger/line-round-force'), 'the engine marker lands (the seam the scan tick consumes)')
  assert(io.files.get('/store/proj-x/ledger/line-round-force').includes('requested_by=executor-panel'), 'the marker names who asked (forensics)')
  const recs = io.files.get('/store/proj-x/certification/queue-records.jsonl').trim().split('\n')
  const row = JSON.parse(recs[0])
  assert(row.by === 'host' && typeof row.at === 'string' && row.project === 'proj-x' && row.source === 'panel-queue', 'the record names who asked and when')
  assert(typeof r.json.note === 'string' && r.json.note.includes('scan tick'), 'the answer says queued and who picks it up (never running)')
  n += 5
}

// ---- queue: idempotency (present marker AND the concurrent EEXIST race) ----
{
  const io = memQueueIo()
  io.files.set('/store/proj-x/ledger/line-round-force', 'requested_by=other\n')
  const api = queueApi(io)
  const r = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  assert(r.status === 200 && r.json.state === 'already_queued', 'a present marker answers already_queued')
  const recs = io.existsSync('/store/proj-x/certification/queue-records.jsonl')
  assert(!recs, 'the idempotent click appends no second record (two clicks, one round)')

  const io2 = memQueueIo()
  const api2 = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certQueueIo: io2,
    // the marker appears BETWEEN the state read and the exclusive create —
    // the concurrent second click loses the race at the filesystem
    certQueueState: async () => state(),
  })
  io2.files.set('/store/proj-x/ledger/line-round-force', 'requested_by=other\n') // pre-seeded after state? simulate via io wrapper below
  // simulate the race: the exclusive create sees an existing marker even
  // though the state read reported present:false
  const racing = queueApi(io2, {})
  const r2 = await racing.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  // pre-seeded marker makes state() stale (present:false) but writeMarkerExclusive throws EEXIST
  assert(r2.status === 200 && r2.json.state === 'already_queued', 'the concurrent click loses the EEXIST race and still answers already_queued')
  assert(!io2.existsSync('/store/proj-x/certification/queue-records.jsonl'), 'the losing click records nothing (one act, one record)')
  n += 4
}

// ---- queue: the failed attempt is recorded and answered 502 ----
{
  const io = memQueueIo()
  const api = queueApi(io, {
    certQueueState: async () => ({ ok: false, reason: 'adapter failed: traceback' }),
  })
  const r = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  assert(r.status === 502 && r.json.error.includes('adapter failed'), 'an unreadable queue state is an explicit 502, never a silent skip')
  n += 1
}
{
  const io = memQueueIo()
  io.writeMarkerExclusive = () => { throw new Error('disk full') }
  const api = queueApi(io)
  const r = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  assert(r.status === 502 && r.json.error.includes('marker write failed') && r.json.record && r.json.record.by === 'host', 'a failed marker write is 502 WITH the attribution row (the attempt keeps its name)')
  n += 1
}

// ---- queue: boundary + by_claimed mismatch + records read face ----
{
  const io = memQueueIo()
  const api = queueApi(io)
  const unauth = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, { certQueueIo: io, certQueueState: async () => state() })
  const r401 = await unauth.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x' }), '', {})
  assert(r401.status === 401, 'credential-less queue POST: 401 (the write gate runs first)')
  const bad = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: '../escape' }), '', {})
  assert(bad.status === 400, 'malformed project key: 400')
  const junk = await api.handle('POST', QUEUE, new URLSearchParams(), '{not json', '', {})
  assert(junk.status === 400, 'malformed body: 400')
  const claimed = await api.handle('POST', QUEUE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', by: 'someone-else' }), '', {})
  const row = JSON.parse(io.files.get('/store/proj-x/certification/queue-records.jsonl').trim().split('\n').pop())
  assert(claimed.status === 200 && row.by === 'host' && row.by_claimed === 'someone-else' && row.writer_mismatch === true, 'a caller-reported by lands as by_claimed + writer_mismatch (never trusted)')
  const rec = await api.handle('GET', QREC, new URLSearchParams('project=proj-x'), '')
  assert(rec.status === 200 && rec.json.ok === true && rec.json.rows.length === 1, 'the records read face returns the account')
  const empty = await api.handle('GET', QREC, new URLSearchParams('project=proj-y'), '')
  assert(empty.status === 200 && empty.json.ok === false && Array.isArray(empty.json.rows), 'no record file yet: an ok:false with empty rows (degraded style)')
  const torn = memQueueIo()
  torn.files.set('/store/proj-x/certification/queue-records.jsonl', '{"at":"a","by":"host"}\nGARBAGE\n')
  const tornRead = await queueApi(torn).handle('GET', QREC, new URLSearchParams('project=proj-x'), '')
  assert(tornRead.json.malformed_rows === 1, 'a torn line is counted, never silently dropped')
  n += 8
}

// ---- promote: named refusals, read-back, inconsistency ----
{
  const api = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, { ...authPass })
  const noSigner = await api.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l' }), '', {})
  assert(noSigner.status === 400 && noSigner.json.error.includes('signer'), 'missing signer: 400 by name, before any write')
  const noLine = await api.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', signer: '徐辛' }), '', {})
  assert(noLine.status === 400 && noLine.json.error.includes('line'), 'missing line: 400 by name')
  const badKey = await api.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: '../x', line: 'l', signer: 'a' }), '', {})
  assert(badKey.status === 400, 'malformed project key: 400')
  n += 3

  const refused = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async () => ({ ok: false, reason: 'signer_is_agent_role_name:developer' }),
  })
  const r = await refused.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l', signer: 'developer' }), '', {})
  assert(r.status === 502 && r.json.error === 'signer_is_agent_role_name:developer', 'the engine\'s identity refusal travels VERBATIM (never genericized, never a UI check)')
  const refused2 = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async () => ({ ok: false, reason: 'promotion_not_fast_forward:sandbar' }),
  })
  const r2 = await refused2.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l', signer: '徐辛' }), '', {})
  assert(r2.status === 502 && r2.json.error === 'promotion_not_fast_forward:sandbar', 'the fast-forward refusal travels verbatim too')
  n += 2

  const row = { id: 'prom-01ABC', signer: '徐辛', certification: 'cert-01', line: 'develop-buffer', main_after: { sandbar: '6efc7b3e' } }
  const okApi = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async (p, l, s) => { assert(s === '徐辛' && l === 'develop-buffer', 'the act carries the confirmed signer and line'); return { ok: true, row } },
    certPromoteLatest: async () => ({ ok: true, project: 'proj-x', promotion: row, promotions: 1 }),
  })
  const ok = await okApi.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'develop-buffer', signer: '徐辛' }), '', {})
  assert(ok.status === 200 && ok.json.ok === true && ok.json.promotion.id === 'prom-01ABC', 'the happy act answers with the LEDGER read-back row')
  assert(ok.json.promotion.signer === '徐辛', 'the read-back row names the human signer')
  n += 2

  const ghost = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async () => ({ ok: true, row }),
    certPromoteLatest: async () => ({ ok: true, project: 'proj-x', promotion: null, promotions: 0 }),
  })
  const g = await ghost.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l', signer: '徐辛' }), '', {})
  assert(g.status === 502 && g.json.error.includes('does not confirm'), 'write-ok-but-ledger-empty: explicit 502, never an optimistic guess')
  const drift = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async () => ({ ok: true, row }),
    certPromoteLatest: async () => ({ ok: true, project: 'proj-x', promotion: { ...row, id: 'prom-OTHER' }, promotions: 1 }),
  })
  const d = await drift.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l', signer: '徐辛' }), '', {})
  assert(d.status === 502, 'a read-back id that is not the written id: explicit 502')
  const rbFail = createApi({ HOME: '/nonexistent', SANDBAR_PROJECTS_DIR: '/store' }, {
    ...authPass,
    certPromoteWrite: async () => ({ ok: true, row }),
    certPromoteLatest: async () => ({ ok: false, reason: 'delivery ledger has 1 malformed line(s): x' }),
  })
  const rb = await rbFail.handle('POST', PROMOTE, new URLSearchParams(), JSON.stringify({ project: 'proj-x', line: 'l', signer: '徐辛' }), '', {})
  assert(rb.status === 502 && rb.json.error.includes('malformed'), 'a failed read-back is an explicit 502')
  n += 3
}

done(n)
