/**
 * sc_t26102512_queue_round_journey.mjs — t261025-12, part 1 of 3.
 *
 * intent (host ruling 261025 option c, §5 "Trigger a round", + ticket item A):
 *   The panel may REQUEST the next certification round without running it inside
 *   the HTTP request. The request queues through the engine's OWN seam (the
 *   line-round-force marker the tick consumes), says 'queued', shows what the
 *   queue waits on, is idempotent (two clicks never queue two rounds), and the
 *   recorded request names who asked and when. Judged from the READER side: the
 *   marker and the record row are read back from disk, not from the writer's
 *   word alone.
 *
 * failure surface (grey-box: what the developer likely gets wrong):
 *   - a route that RUNS the round or invents a second queue seam;
 *   - non-idempotency (two rows / marker clobbered);
 *   - a record row whose writer says 'host' but a caller-supplied by sneaks in
 *     unrecorded (KI-193 by/by_claimed discipline);
 *   - copy that claims the round is running (the tick may sit ~20 min);
 *   - a queue that answers 200 on a malformed body or without credentials
 *     (KI-193 write gate);
 *   - waits_on that guesses ('fine') instead of naming the blocker.
 *
 * layering / intent split:
 *   - route input validation matrices, stub-level idempotency truth tables and
 *     the queueStateRead parse matrices belong to developer L1
 *     (server/plugins/executor-panel/tests/t261025-12-cert-controls-*.test.mjs);
 *   - the tick CONSUMING the marker belongs to the engine's own suite
 *     (develop_certify); THIS entry owns the panel-side journey over the real
 *     route + real marker/record files on disk.
 *
 * offline: zero docker / Temporal server / browser, never touches 3099/7233.
 * pre-implement tree red (route 404) = the named TDD signal; green required at
 * the integration gate/merge. api.ts unimportable = ENV_FAIL exit 2.
 */
import { mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'

let failed = 0
const missing = []
function ok(cond, label) {
  if (cond) { console.log(`  ok  ${label}`) } else { failed++; console.log(`FAIL  ${label}`) }
}

let createApi
try {
  ;({ createApi } = await import('../../server/plugins/executor-panel/src/host/api.ts'))
} catch (e) {
  console.log(`ENV_FAIL: executor-panel api.ts unimportable: ${e && e.message}`)
  process.exit(2)
}

const ROUTE = '/sandbar-executor-panel/api/certification/queue'
const MARKER = 'line-round-force' // the engine's own seam name (develop_certify.FORCE_MARKER_NAME)

// ---- fixture project store --------------------------------------------------
const tmp = mkdtempSync(join(tmpdir(), 'sc-t26102512-queue-'))
try {
  const projects = join(tmp, 'projects')
  const ledgerDir = join(projects, 'proj-q', 'ledger')
  mkdirSync(ledgerDir, { recursive: true })
  // one declared line so the store is a real, readable project
  mkdirSync(join(projects, 'proj-q', 'data', 'develop'), { recursive: true })
  writeFileSync(join(projects, 'proj-q', 'data', 'develop', 'lines.json'), JSON.stringify([
    { line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' },
  ]))
  const env = {
    HOME: tmp,
    SANDBAR_PROJECTS_DIR: projects,
    // the engine's env contract: a FLAT DIRECTORY of <project>.jsonl files
    SANDBAR_DELIVERY_LEDGER_DIR: ledgerDir,
  }
  // the console credential the gate actually binds: cookie name is derived
  // from the Host header (dsh-auth-<base64url(sha256(host))>), value shape
  // v1.<sig>.<sig> — a named Host plus a correctly named cookie is the
  // credential-present premise; the gate's own matrices are L1 territory.
  const HOST = 'panel.sc.test'
  const AUTH_NAME = 'dsh-auth-' + createHash('sha256').update(HOST).digest('base64url')
  const auth = { cookie: `${AUTH_NAME}=v1.sig.sig`, host: HOST }

  // ---- A. the journey: click once -> queued, marker on disk, request recorded
  {
    const api = createApi(env, {})
    const r = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', auth)
    ok(r.status === 200 && r.json && r.json.ok === true,
      `A1 first click answers 200 ok (got ${r.status} ${JSON.stringify(r.json).slice(0, 120)})`)
    const markerPath = join(ledgerDir, MARKER)
    ok(existsSync(markerPath), 'A2 the engine marker file EXISTS on disk after the click (reader side)')
    if (existsSync(markerPath)) {
      const body = readFileSync(markerPath, 'utf8')
      ok(/requested_by/.test(body) && /at/.test(body),
        'A3 the marker body names who asked and when (forensics fields present)')
    }
    const rec = r.json && r.json.record
    ok(rec && typeof rec === 'object' && rec.at && rec.project === 'proj-q',
      'A4 the response carries the recorded request (at + project)')
    ok(rec && rec.by === 'host' && rec.by_claimed === undefined,
      'A5 the recorded writer is the credential identity host, no unrecorded caller-reported by')
    // reader side of the record: the file the route names actually holds the row
    const recFile = r.json && (typeof r.json.written === 'string' ? r.json.written : r.json.written && r.json.written.file)
    ok(typeof recFile === 'string' && existsSync(recFile) && readFileSync(recFile, 'utf8').includes('"project":"proj-q"'),
      'A6 the record row is READ BACK from the file the route names (writer receipt is not the evidence)')
  }

  // ---- B. idempotency: two clicks, one queue
  {
    const api = createApi(env, {})
    const r1 = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', auth)
    const markerPath = join(ledgerDir, MARKER)
    const before = existsSync(markerPath) ? readFileSync(markerPath, 'utf8') : null
    const recFile = r1.json && (typeof r1.json.written === 'string' ? r1.json.written : r1.json.written && r1.json.written.file)
    const recBefore = recFile && existsSync(recFile) ? readFileSync(recFile, 'utf8') : ''
    const r2 = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', auth)
    ok(r2.status === 200 && r2.json && r2.json.ok === true,
      'B1 the second click still answers ok (idempotent success, not an error)')
    ok(r2.json && r2.json.state === 'already_queued',
      `B2 the second click names already_queued (got ${r2.json && r2.json.state})`)
    const after = existsSync(markerPath) ? readFileSync(markerPath, 'utf8') : null
    ok(before !== null && after === before, 'B3 the marker was not rewritten by the second click')
    const recAfter = recFile && existsSync(recFile) ? readFileSync(recFile, 'utf8') : ''
    ok((recAfter.match(/"project":"proj-q"/g) || []).length === (recBefore.match(/"project":"proj-q"/g) || []).length,
      'B4 no second record row was appended (two clicks, one queued request)')
  }

  // ---- C. waits_on names the blocker, never claims the round is running
  {
    // a live round face that says a round is in flight -> the queue must name it
    const faceDir = join(tmp, 'faces')
    mkdirSync(faceDir, { recursive: true })
    writeFileSync(join(faceDir, 'face-live.json'), JSON.stringify({
      run_id: 'run-live', state: 'running', updated_at: Date.now(), counts: {}, outcome: {},
    }))
    const api = createApi({ ...env, SANDBAR_LINE_ROUND_FACE_DIR: faceDir }, {})
    const r = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', auth)
    const txt = JSON.stringify(r.json || {})
    ok(r.status === 200, 'C1 the queue face still answers when a round is in flight')
    ok(/waits_on|waiting|in_flight|already/.test(txt),
      `C2 the answer names what the queue waits on (got ${txt.slice(0, 160)})`)
    ok(!/"state"\s*:\s*"running"/.test(txt),
      'C3 the queued REQUEST itself is never labelled running (the tick picks it up later)')
  }

  // ---- D. malformed input is refused before any write
  {
    const api = createApi(env, {})
    const markerPath = join(ledgerDir, MARKER)
    const before = existsSync(markerPath) ? readFileSync(markerPath, 'utf8') : null
    const r1 = await api.handle('POST', ROUTE, new URLSearchParams(), 'not json at all', 'http://panel', auth)
    const r2 = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: '' }), 'http://panel', auth)
    const r3 = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({}), 'http://panel', auth)
    ok(r1.status === 400 && /json/i.test(r1.json && r1.json.error || ''),
      'D1 a non-JSON body is a named 400')
    ok(r2.status === 400 && (r2.json && r2.json.error || '').length > 0,
      'D2 an empty project key is a named 400')
    ok(r3.status === 400, 'D3 a body with no project is a named 400')
    const after = existsSync(markerPath) ? readFileSync(markerPath, 'utf8') : null
    ok(before === after, 'D4 malformed input writes nothing (marker byte-identical)')
  }

  // ---- E. no credential, no write (KI-193 carried onto the new route)
  {
    const api = createApi(env, {})
    const r = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', {})
    ok(r.status === 401, `E1 a credential-less POST is refused 401 (got ${r.status})`)
  }

  // ---- F. an unresolvable runner is named, never guessed
  {
    // a project whose ledger dir is unreadable -> waits_on must refuse by name
    const envBroken = { ...env, SANDBAR_DELIVERY_LEDGER_DIR: join(tmp, 'nope') } // a ledger root that does not exist
    const api = createApi(envBroken, {})
    const r = await api.handle('POST', ROUTE, new URLSearchParams(), JSON.stringify({ project: 'proj-q' }), 'http://panel', auth)
    const txt = JSON.stringify(r.json || {})
    ok(typeof r.json === 'object' && r.json !== null, 'F1 the unreadable-store case still answers an envelope')
    ok(/runner|unresolvable|not resolvable|ledger|reason|error/i.test(txt),
      `F2 the unresolvable face is NAMED, never a generic ok (got ${txt.slice(0, 160)})`)
  }

  // ---- G. the route is registered in the single route table
  {
    const { PANEL_API_ROUTES } = await import('../../server/plugins/executor-panel/src/host/api.ts')
    const entry = PANEL_API_ROUTES.find((x) => x.path === ROUTE)
    ok(entry !== undefined && entry.methods.includes('POST'),
      'G1 the queue route sits in PANEL_API_ROUTES (no side-door route)')
  }

  if (failed > 0) {
    missing.push(`${failed} queue-journey check(s) red`)
    console.log(`FAIL sc_t26102512_queue_round_journey: ${failed} red check(s)`)
    process.exit(1)
  }
  console.log('PASS sc_t26102512_queue_round_journey')
  process.exit(0)
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
