/**
 * sc_t26102112_epic_tickets_time_payload.mjs — t261021-12: the epic tickets
 * payload carries each ticket's last-modified time, converted once at the API
 * boundary.
 *
 * Grey-box L3 (integration-owned). The REAL workbench route face
 * (server/plugins/workbench/node.ts, mounted via apply()) over a fixture epic
 * directory (SANDBAR_EPICS_DIR) with a fake ticket-list CLI (repoA/server/admin.py,
 * same technique as sc_t26101912_epics_api_store_move.mjs) emitting rows whose
 * updated_ts is epoch SECONDS — the unit the engine row actually carries.
 * Offline seconds, zero docker/Temporal/browser, never touches 3099/7233.
 *
 * User-perceivable contract under test (ticket t261021-12 "Required" block):
 *   A THE FIELD — GET /sandbar-workbench/api/epics/<code>/tickets carries each
 *     ticket's last-modified time: a valid source value arrives converted to
 *     milliseconds exactly once (seconds * 1000, no recomputation downstream).
 *   B THE ABSENT RULE — a malformed source value (missing, non-numeric, zero or
 *     negative after the engine's 0-fallback) yields an ABSENT key, never 0 and
 *     never a fabricated now.
 *   C THE REST OF THE ROW — the legacy fields (id/title/status/stage/stage_state)
 *     and the buckets/count envelope survive the mapping untouched.
 *
 * Intent split (no intent-level duplication): the Epics-tab ORDER and the
 * normal-case render face belong to sc_t26102112_epics_tab_case_and_order
 * (browser); the /api/epics list shape and the dead close/status routes belong
 * to t261019-12-epics-api-store-move; the page-side sort helpers are developer
 * L1. This entry uniquely owns the boundary conversion + absent rule on the
 * endpoint the page consumes.
 *
 * Pre-implement tree: A red (the field is stripped today) = the named TDD
 * signal; green required at the integration gate / merge.
 * node or node.ts unresolvable = ENV_FAIL exit 2. PASS/FAIL/ENV_FAIL only.
 */

import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
let mod
try {
  mod = await import(join(ROOT, 'server/plugins/workbench/node.ts'))
} catch (e) {
  console.error(`ENV_FAIL: workbench node.ts unresolvable: ${e && e.message}`)
  process.exit(2)
}
const { apply } = mod

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  const find = (kind, path) => routes.find(r => r.kind === kind && r.path === path)
  return { prefixEpics: find('prefix', '/sandbar-workbench/api/epics') }
}
const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const call = async (handler, url, method = 'GET', bodyObj) => {
  const res = mockRes()
  const payload = bodyObj === undefined ? [] : [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* payload } }
  await handler.handler(req, res)
  return res
}

const DOC = (code) =>
  `---\ncode: ${code}\nretired: false\nsummary: ${code} takes tickets.\nstarted: 2026-10-21\n---\n\n# ${code}\n\nIntent.\n`

// Source rows in the ENGINE's unit: epoch seconds. t-good-* are valid; the rest
// probe the absent rule (missing / wrong type / zero / negative / NaN / null).
const NOW_S = Math.floor(Date.now() / 1000)
const SOURCE_TICKETS = [
  { id: 't-good-new', title: 'Newest', status: 'running', stage: 'implement', stage_state: 'running', updated_ts: NOW_S - 60 },
  { id: 't-good-old', title: 'Older', status: 'closed', stage: 'verify', stage_state: 'awaiting', updated_ts: NOW_S - 86400 },
  { id: 't-missing', title: 'No field', status: 'open', stage: 'plan', stage_state: 'awaiting' },
  { id: 't-string', title: 'String value', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: 'not-a-number' },
  { id: 't-null', title: 'Null value', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: null },
  { id: 't-zero', title: 'Zero fallback', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: 0 },
  { id: 't-negative', title: 'Negative', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: -5 },
  { id: 't-float', title: 'Fractional', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: (NOW_S - 120) + '.5' },
]
const FAKE_ADMIN = 'import json\n'
  + 'TICKETS = json.loads(' + JSON.stringify(JSON.stringify(SOURCE_TICKETS)) + ')\n'
  + 'print(json.dumps({"ok": True, "result": {"count": len(TICKETS), "tickets": TICKETS}}))\n'

const tmp = await mkdtemp(join(tmpdir(), 'integ-t26102112-'))
const savedEnv = process.env.SANDBAR_EPICS_DIR
try {
  section('A+B the payload carries last-modified in ms; malformed is absent, never 0/now')
  const epicsDir = join(tmp, 'docs', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'live-epic.md'), DOC('live-epic'), 'utf8')
  const repoA = join(tmp, 'repo-a')
  await mkdir(join(repoA, 'server'), { recursive: true })
  await writeFile(join(repoA, 'server', 'admin.py'), FAKE_ADMIN, 'utf8')
  process.env.SANDBAR_EPICS_DIR = epicsDir
  const h = makeHarness(repoA)
  ok(h.prefixEpics !== undefined, 'epics prefix route mounted')

  const r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/live-epic/tickets')
  ok(r.status === 200 && r.body && r.body.ok === true, 'GET /tickets -> 200 ok')
  const rows = (r.body && r.body.result && r.body.result.tickets) || []
  ok(Array.isArray(rows) && rows.length === SOURCE_TICKETS.length,
    `every source row surfaces (${rows.length}/${SOURCE_TICKETS.length})`)
  const byId = {}
  for (const row of rows) byId[row.id] = row

  // A: valid values arrive in ms, converted exactly once from the seconds source.
  ok(byId['t-good-new'] && byId['t-good-new'].updated_ts === (NOW_S - 60) * 1000,
    'valid source -> milliseconds (seconds * 1000), exact')
  ok(byId['t-good-old'] && byId['t-good-old'].updated_ts === (NOW_S - 86400) * 1000,
    'second valid source -> milliseconds, exact')

  // B: malformed is ABSENT — never 0, never now, never a string.
  const absentIds = ['t-missing', 't-string', 't-null', 't-zero', 't-negative', 't-float']
  for (const id of absentIds) {
    const row = byId[id]
    ok(row && !('updated_ts' in row), `${id}: updated_ts key absent`)
    if (row && 'updated_ts' in row) {
      ok(row.updated_ts !== 0, `${id}: not 0`)
      ok(!(typeof row.updated_ts === 'number' && Math.abs(row.updated_ts - Date.now()) < 60000),
        `${id}: not a fabricated now`)
    }
  }

  // C: the legacy row shape and the envelope survive.
  ok(byId['t-good-new'] && byId['t-good-new'].title === 'Newest'
    && byId['t-good-new'].stage === 'implement' && byId['t-good-new'].stage_state === 'running',
    'legacy fields (title/stage/stage_state) survive the mapping')
  ok((r.body?.result?.buckets) && typeof r.body.result.count === 'number',
    'buckets + count envelope intact')
} catch (e) {
  console.error(`FAIL harness exception: ${e && e.stack || e}`)
  fail++
} finally {
  if (savedEnv === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nPASS=${pass} FAIL=${fail}`)
process.exit(fail === 0 ? 0 : 1)
