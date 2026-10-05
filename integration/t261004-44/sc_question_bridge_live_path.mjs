#!/usr/bin/env node
/**
 * sc_question_bridge_live_path.mjs — t261004-44 KI-196 live-path scenario (grey-box L3,
 * offline seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Intent (user-perceivable): a session asking ask_user_question must land as a question
 * row under the instance projects root, the row ids must round-trip back to the asking
 * session, and a bridge that does not fire must not be silent (readable state face).
 *
 * Contract under test (ticket A): real cordis app + real plugin apply + real agent-scoped
 * `user-questions/request` dispatch + real fs ledger io — NOT injected-dependency UT.
 * Steps: S0 resolve real cordis (missing = ENV_FAIL exit 2); S1 seed a temp instance
 * projects root with a real project registry; S2 apply the production plugin on a real
 * cordis Context and attach the panel route surface; S3 emit a genuine two-question
 * agent-scoped request; S4 assert rows on disk (kind/group_id/raised_by); S5 answer via
 * the real route handlers and assert the round-trip promise resolves in question order;
 * S6 assert the state face (mounted / counters / last events) on the bridge status route.
 *
 * TDD note: red expected before the implement stage lands (status route absent etc.).
 */
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import os from 'node:os'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'

const REPO = process.cwd()
let fails = 0
const fail = (m) => { console.error('FAIL ' + m); fails += 1 }

// ── S0: real cordis (never a fake app; missing dependency = ENV_FAIL exit 2) ──
function resolveCordis() {
  // Installed dsh tree lives under the user home; never a literal home path (L17).
  const roots = [join(os.homedir(), '.sandbar', 'dsh-015', 'lib', 'node_modules', '@deepseek-ai', 'dsh')]
  const envRoot = process.env.SANDBAR_DSH_PKG_ROOT
  if (envRoot) roots.unshift(envRoot)
  for (const r of roots) {
    try {
      const req = createRequire(join(r, 'package.json'))
      const p = req.resolve('@deepseek-ai/cordis')
      if (p) return { require: req, path: p }
    } catch { /* try next root */ }
  }
  return null
}
const cordis = resolveCordis()
if (!cordis) {
  console.error('ENV_FAIL: real cordis package not resolvable from the installed dsh tree ' +
    '(set SANDBAR_DSH_PKG_ROOT to the installed @deepseek-ai/dsh package dir); integration gate decides')
  process.exit(2)
}
const { Context } = await import(pathToFileURL(cordis.path).href)

// ── S1: temp instance projects root + real project registry ──
const home = mkdtempSync(join(tmpdir(), 'sc-qbridge-'))
const root = join(home, 'projects')
const projDir = join(home, 'work', 'myproj')
mkdirSync(join(root, 'demo-proj'), { recursive: true })
mkdirSync(projDir, { recursive: true })
writeFileSync(join(root, 'demo-proj', 'project.yaml'), `name: demo-proj\ndirs:\n  - ${projDir}\n`)
process.env.HOME = home
// The resolver root (SANDBAR_PROJECTS_DIR) and the ledger root (SANDBAR_PANEL_DIR)
// are two declared env faces — both must point at the temp instance root.
process.env.SANDBAR_PROJECTS_DIR = root
process.env.SANDBAR_PANEL_DIR = root
// The answer route pushes a wake to the watchdog over real HTTP (t261004-29) and
// awaits it inline (receipt travels with the answer response). In production the
// base is the same-origin console where the watchdog answers; offline the base must
// be pinned to a real local wake stub — leaving it unpinned resolves it from the
// fake Host header to an unresolvable origin, whose 5s abort timeout delays every
// answer past the round-trip cap (an environment stall, not the face under test).
const wakeStub = createServer((req, res) => {
  let body = ''
  req.on('data', (c) => { body += c })
  req.on('end', () => {
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ ok: true, wake: { attempted: true, woke: false,
      reason: 'sc wake stub: offline scenario, no engine listening (wake attempted, nothing to wake)' } }))
  })
})
wakeStub.listen(0, '127.0.0.1')
await new Promise((r) => wakeStub.once('listening', r))
const wakeBase = `http://127.0.0.1:${wakeStub.address().port}`
process.env.SANDBAR_WORKBENCH_BASE = wakeBase

try {
  // ── S2: real plugin apply on a real cordis context; collect the route surface ──
  const nodeUrl = pathToFileURL(join(REPO, 'server/plugins/executor-panel/node.ts')).href
  const plugin = await import(nodeUrl)
  const app = new Context()
  const routes = new Map() // path -> handler
  const webServer = {
    register: (o) => { routes.set(o.path, o.handler); return () => routes.delete(o.path) },
  }
  plugin.apply(app, {})
  // The panel attaches late via the internal/service event (same as production web
  // profiles where webServer arrives after plugin load) — fire it after apply.
  app.emit('internal/service', 'webServer', webServer)
  const ROUTE = '/sandbar-executor-panel/api'
  // KI-193 write gate: a shape-valid console session cookie (name = dsh-auth- +
  // base64url(sha256(host)); value passes the shape gate — the repo never verifies HMAC).
  const HOST = 'sc.local'
  const cookieFor = (host) => 'dsh-auth-' + createHash('sha256').update(host).digest('base64url') +
    '=v1.cGFuZWwtdGVzdA.c2lnbmF0dXJlLXNoYXBlLW9ubHk'
  const callRoute = async (path, { method = 'GET', body = '', cookie = cookieFor(HOST) } = {}) => {
    const handler = routes.get(ROUTE + path)
    if (!handler) return { status: 404, json: { error: 'route not registered: ' + path } }
    // Minimal node:http-shaped req/res over the REAL registered handler — the route
    // registry is the public surface; the socket is not under test here.
    const realReq = {
      method, url: ROUTE + path,
      headers: { host: HOST, cookie },
      on(ev, cb) {
        if (ev === 'data' && body) cb(Buffer.from(body))
        if (ev === 'end') cb()
        return realReq
      },
    }
    const chunks = []
    const res = {
      status: undefined,
      writeHead(s) { this.status = s },
      end(b) { if (b != null) chunks.push(Buffer.isBuffer(b) ? b : Buffer.from(String(b))) },
      destroy() {},
    }
    await handler(realReq, res)
    const raw = Buffer.concat(chunks).toString('utf8')
    let json = null
    try { json = JSON.parse(raw) } catch { json = { _raw: raw } }
    return { status: res.status, json }
  }

  // ── S3: genuine agent-scoped dispatch (the real cordis emit, not a function call) ──
  const AGENT = { id: 'session-sc44-live', cwd: projDir }
  const QUESTIONS = [
    { id: 'q1', question: 'Grant writes now?', detail: 'live-path probe q1', options: [{ label: 'Grant now' }, { label: 'Wait' }] },
    { id: 'q2', question: 'Restart the worker?', detail: 'live-path probe q2', options: [{ label: 'Restart' }, { label: 'Hold' }] },
  ]
  const payload = { questions: QUESTIONS, agent: AGENT, deadline_ms: 60_000 }
  // Production shape (dsh-user-questions): the asking session runs the event through
  // the real waterfall with a no-answerer fallback — the bridge is a waterfall listener.
  const noAnswerer = () => Promise.reject(new Error('NO_PROVIDER: sc fallback (nobody answered through the waterfall)'))
  const roundTrip = app.waterfall('user-questions/request', payload, noAnswerer)
  // Let the mirror (async ledger io) land.
  await new Promise((r) => setTimeout(r, 400))

  // ── S4: rows on disk under the instance projects root ──
  const ledgerPath = join(root, 'demo-proj', 'requests.jsonl')
  if (!existsSync(ledgerPath)) {
    fail(`A1 no ledger under the instance projects root: ${ledgerPath} — the session ask never landed (KI-196 shape)`)
  } else {
    const rows = readFileSync(ledgerPath, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l) } catch { return null } })
    const qrows = rows.filter((r) => r && r.kind === 'question')
    if (qrows.length !== 2) fail(`A2 expected 2 question rows, got ${qrows.length}`)
    else {
      if (new Set(qrows.map((r) => r.group_id)).size !== 1 || !qrows[0].group_id)
        fail('A3 the two rows do not share one bridge-written group_id (hand-posted rows carry none — that is the incident fingerprint)')
      if (qrows.some((r) => r.raised_by !== AGENT.id))
        fail('A4 raised_by does not carry the asking session id ' + AGENT.id)
      if (![qrows[0].question, qrows[1].question].every((q, i) => q === QUESTIONS[i].question))
        fail('A5 question text/order not preserved from the session ask')

      // ── S5: answer via the real route surface; ids round-trip to the asking session ──
      const resolve = roundTrip && typeof roundTrip.then === 'function' ? roundTrip : null
      if (!resolve) fail('B1 the waterfall did not return a promise the asking session could await (no round-trip path)')
      else {
        const answerAll = (async () => {
          for (const r of qrows) {
            const res = await callRoute('/requests/answer', { method: 'POST', body: JSON.stringify({ project: 'demo-proj', id: r.id, answer: `answer:${r.id}` }) })
            if (res.status !== 200) fail(`B2 answer for row ${r.id} refused by the route (status ${res.status})`)
            // The answer receipt carries the wake push result (t261004-29 additive
            // receipt): the real fetch against the pinned stub must report attempted.
            const wake = res.json && res.json.wake
            if (!wake || wake.attempted !== true) fail(`B7 answer receipt for row ${r.id} carries no attempted wake push: ${JSON.stringify(wake)}`)
          }
        })()
        const got = await Promise.race([
          resolve.catch((e) => ({ __err: String(e) })),
          // 30s cap (t261004-44 arbitrate): the post-merge answer route also awaits the
          // t261004-29 wake push, which offline burns its full fetch timeout per answer —
          // the round-trip legitimately takes ~10-12s offline. The cap still bounds the
          // contract (a session must get its answers back); it only stops mistaking the
          // wake-path latency for a broken round-trip.
          new Promise((r) => setTimeout(() => r({ __timeout: true }), 30000)),
        ])
        await answerAll
        if (!got || got.__timeout) fail('B3 the asking session never received its answers via the row-id round-trip (30s cap)')
        else if (got.__err) fail('B4 round-trip promise rejected: ' + got.__err)
        else {
          const answers = Array.isArray(got) ? got : (got.answers ?? got.responses ?? null)
          if (!answers || answers.length !== 2) fail('B5 round-trip did not deliver both answers: ' + JSON.stringify(got).slice(0, 200))
          else {
            // AskAnswer shape: one entry per question, in question order, each carrying
            // the human's answer text filed under its row id.
            const okPair = qrows.every((r, i) => {
              const a = answers[i] ?? {}
              const text = [a.custom, a.answer].find((v) => typeof v === 'string') ?? JSON.stringify(a)
              return text === `answer:${r.id}`
            })
            if (!okPair) fail('B6 answers not in question order / wrong row ids: ' + JSON.stringify(answers))
          }
        }
      }
    }
  }

  // ── S6: the state face — a bridge that does not fire must not be silent ──
  const st = await callRoute('/bridge/status')
  if (st.status === 404) {
    fail(`C1 bridge state face absent (GET ${ROUTE}/bridge/status -> 404): mounted/counters/events unreadable — the KI-196 silence face is still open`)
  } else if (st.status !== 200) {
    fail('C2 bridge state face not ok: status ' + st.status + ' ' + JSON.stringify(st.json).slice(0, 200))
  } else {
    const j = st.json
    const mounted = j.mounted ?? j.status?.mounted
    if (mounted !== true) fail('C3 state face does not report mounted=true after a successful ctx.on registration: ' + JSON.stringify(j).slice(0, 200))
    const counters = j.counters ?? j.status?.counters
    if (!counters || (counters.mirrored ?? 0) < 1) fail('C4 state face mirror counter shows no mirrored event: ' + JSON.stringify(counters))
    const events = j.last_events ?? j.events ?? j.status?.last_events
    if (!Array.isArray(events) || events.length < 1) fail('C5 state face carries no recent events ring')
    else if (!events.some((e) => (e.kind ?? e) === 'mirrored')) fail('C6 event ring does not contain the mirrored event kind')
  }
} finally {
  try { wakeStub.close() } catch { /* stub best effort */ }
  try { rmSync(home, { recursive: true, force: true }) } catch { /* temp best effort */ }
}

console.log(`SC_QUESTION_BRIDGE_LIVE_PATH fails=${fails}`)
process.exit(fails === 0 ? 0 : 1)
