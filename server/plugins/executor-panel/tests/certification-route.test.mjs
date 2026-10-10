/**
 * certification-route.test.mjs — t261009-44 Slice 2, the API route's UT.
 *
 * Contract:
 *  - the route is in PANEL_API_ROUTES (the single table source) as GET-only;
 *  - 200 {ok:true, project, line, lines, face, raw} on a readable store (stub);
 *  - 200 {ok:false, reason} with the reader's named reason verbatim on every
 *    refusal (the ONE-envelope rule, same as the concurrency read face);
 *  - 400 on a malformed project key; POST: 401 (write gate first) then 405 (GET-only);
 *  - the route-parity lock keeps guarding the table automatically.
 */
import { assert, done } from './lib.mjs'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0
const ROUTE = '/sandbar-executor-panel/api/certification'
const Q = (s = '') => new URLSearchParams(s)

// the table carries the route, GET-only
{
  const entry = PANEL_API_ROUTES.find((r) => r.path === ROUTE)
  assert(entry !== undefined, 'route is registered in PANEL_API_ROUTES')
  assert(entry.methods.length === 1 && entry.methods[0] === 'GET', 'route is GET-only (no write path in this slice)')
  n += 2
}

function apiWithRead(read, extra = {}) {
  return createApi({ HOME: '/nonexistent-home', SANDBAR_PANEL_DIR: '/nonexistent-projects' }, {
    certificationRead: async (args) => read(args),
    ...extra,
  })
}

// the happy shape: the derived face plus the raw input arrays
{
  const api = apiWithRead(async (args) => ({
    ok: true, project: args.project, line: args.line ?? 'develop-buffer',
    lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
    face: { ok: true, reason: '', lineId: 'develop-buffer', state: 'GREEN', frozen: false, frozenFace: null, deliveredTotal: 1, certified: [], waiting: [], promotable: 0, boundary: null, rounds: [], roundState: 'idle' },
    raw: { certs: [], runs: [], outcomes: [] },
    notes: [],
  }))
  const r = await api.handle('GET', ROUTE, Q('project=proj-x'), '')
  assert(r.status === 200 && r.json.ok === true && r.json.project === 'proj-x', 'happy read: 200 ok envelope')
  assert(r.json.face && r.json.face.lineId === 'develop-buffer', 'the derived face rides along')
  assert(Array.isArray(r.json.raw.certs) && Array.isArray(r.json.raw.runs), 'raw input arrays ride along for links')
  assert(Array.isArray(r.json.lines) && r.json.lines[0].line_id === 'develop-buffer', 'line list rides along for the picker')
  assert(typeof r.json.note === 'string' && r.json.note.length > 0, 'the face states its engine provenance')
  // the ?line= deep choice reaches the reader
  const r2 = await api.handle('GET', ROUTE, Q('project=proj-x&line=other'), '')
  assert(r2.status === 200 && r2.json.line === 'other', 'the ?line= query reaches the reader')
  n += 6
}

// the refusal envelope: the reader's named reason travels verbatim
{
  const api = apiWithRead(async () => ({ ok: false, reason: 'delivery ledger has 1 malformed line(s): garbage {' }))
  const r = await api.handle('GET', ROUTE, Q('project=proj-x'), '')
  assert(r.status === 200 && r.json.ok === false, 'refusal: 200 ok:false (the editor works, the face degrades)')
  assert(r.json.reason === 'delivery ledger has 1 malformed line(s): garbage {', 'the named reason travels verbatim (never rewritten)')
  assert(typeof r.json.note === 'string' && r.json.note.length > 0, 'the degrade states itself')
  n += 3
}

// the boundary refusals
{
  const api = apiWithRead(async () => ({ ok: false, reason: 'unused' }))
  const bad = await api.handle('GET', ROUTE, Q('project=../escape'), '')
  assert(bad.status === 400, 'malformed project key: 400')
  const noKey = await api.handle('GET', ROUTE, Q(''), '')
  assert(noKey.status === 400, 'missing project key: 400')
  // The KI-193 write-credential gate runs BEFORE the method check (the family
  // convention: every write method passes the gate first) — so an unauthenticated
  // POST is 401, and a credentialed POST reaches the route's own 405.
  const post401 = await api.handle('POST', ROUTE, Q('project=p'), '{}')
  assert(post401.status === 401, 'POST without a console credential: 401 (the write gate runs first)')
  const apiOk = apiWithRead(async () => ({ ok: false, reason: 'unused' }), { authFace: () => ({ ok: true, why: '' }) })
  const post = await apiOk.handle('POST', ROUTE, Q('project=p'), '{}')
  assert(post.status === 405, 'POST (credentialed): 405 (no write path on this route)')
  n += 3
}

done(n)
