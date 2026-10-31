#!/usr/bin/env node
/**
 * sc_t261030_35_artifact_face.mjs — t261030-35 (epic artifact-face, slice 2: the
 * console lists the declared artifacts and renders the frame), grey-box L3,
 * "ro" pool, seconds.
 *
 * User-perceivable faces under test (ticket text "list the declared artifacts,
 * render the frame, keep the frame out of project hands"; plan D5/D5a/D6/D6a/
 * D6b/D6c, acceptance A1-A12):
 *
 *   A READ-ONLY — both artifact routes answer only GET. Any other method is a
 *     named 405, and it never returns a byte of the file.
 *   B THE INVENTORY — one GET lists every declared row in stage order then
 *     declaration order. Each row carries its `<stage>/<id>` key and a named
 *     state. A row is NEVER dropped because its bytes are unusable (missing,
 *     over the cap, not UTF-8, a URL source, an absolute source, an escape, or
 *     a member repo this ticket does not own). A ticket that declares nothing
 *     answers an explicit empty list, not an error. When the snapshot also
 *     carries the engine's flat list, that list is the one listed (the forward
 *     compatible branch).
 *   C THE CLIENT-TO-HOST KEY (the seam) — the key the console model mints
 *     (`deriveArtifactRows` -> row.key) is the address the byte route accepts,
 *     and the bytes it answers equal the declared file on disk (sha256), for a
 *     text row and an image row.
 *   D THE STATUS FAMILY — an undeclared id or stage is 404; an id declared twice
 *     in one stage is 409; an over-cap source is 413; a path-shaped id is 400
 *     (including the double-decode shape `a%252Fb`). A DECLARED but unusable
 *     source is a named 4xx that is NOT 404 — the host can tell "not declared"
 *     from "declared, cannot be served". Every refusal names the check.
 *   E THE RESPONSE CONTRACT — every answer carries `x-content-type-options:
 *     nosniff` and `cache-control: no-store`; text kinds are `text/plain`
 *     (never `text/html`); a PNG stays `image/png`; an SVG declared as an image,
 *     an unknown kind and an `external` kind leave as an octet-stream download.
 *   F THE PROJECT ANCHOR (KI-057 family) — the same ticket id resolved under a
 *     second registered project serves THAT project's bytes; an unregistered key
 *     is a named 400 (never a silent fallback to the engine repo); a file that
 *     exists only in the other project's tree is never served.
 *   G THE OLD DISPATCH IS INTACT — the detail route answers exactly what it
 *     answered before, and an unknown op still gets the family's own answer (the
 *     two new routes did not shadow the ticket prefix).
 *   H MALFORMED INPUT NEVER THROWS — a snapshot with a non-object `results`, a
 *     non-object stage receipt, a non-object descriptor entry and a blank
 *     `source` answers 200 with the good row still listed and the rest named by
 *     a refusal line (no 5xx, nothing vanishes silently).
 *   I THE READ POOL RECOVERS — concurrent byte reads are each either served or
 *     refused BY NAME (never silently dropped), and the pool is free afterwards.
 *   J THE UNIT BATTERY IS LIVE — the delivered L1 battery exists, runs, and is
 *     green (an absent or red battery is the ticket's own product gap:
 *     mechanism liveliness, precedent t260916-05 / t261009-30).
 *
 * Harness: the REAL workbench plugin (`server/plugins/workbench/node.ts`,
 * mounted through `apply()`) over a mkdtemp project pair, with a fake
 * `server/admin.py` that answers `call ticket {"op":"show"}` — the seam
 * `runAdminCli` already provides (`<repo>/server/admin.py`); the technique of
 * `integration/t261021-12/sc_t26102112_epic_tickets_time_payload.mjs`. The
 * project registry is a temp per-key directory (`.migrated` marker), the
 * technique of `integration/t260907-11/lib_wb_anchor.mjs`.
 *
 * Zero docker, zero Temporal, zero browser, never touches 3099/7233.
 *
 * Pre-implement tree: A-J red by name (the routes, the model and the battery do
 * not exist yet) = the named TDD signal; green required at the integration gate
 * / merge. node or node.ts unresolvable = ENV_FAIL exit 2.
 *
 * Intent split (no intent-level repetition): the derivation truth tables (order,
 * refusals, legacy labels, state vocabulary), the cap arithmetic, the content
 * type table and the slot helper belong to developer L1
 * (`server/plugins/workbench/tests/t261030-35-artifact-face.mjs`). This entry
 * owns the assembled seam only: the route table, the per-request project anchor,
 * the client-model key reaching the host route, the served HTTP contract, and
 * the existing dispatch staying intact.
 */

import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
const TICKETS = '/sandbar-workbench/api/wf/tickets'
const L1_BATTERY = 'server/plugins/workbench/tests/t261030-35-artifact-face.mjs'

let pass = 0
let fail = 0
let envfail = 0
let na = 0

function ok(label, cond, detail) {
  if (cond) {
    pass += 1
    console.log(`  ok ${label}`)
  } else {
    fail += 1
    console.log(`  FAIL ${label}${detail ? ' — ' + detail : ''}`)
  }
}
function section(title) { console.log(`\n== ${title}`) }
function envFail(label, why) { envfail += 1; console.log(`ENV_FAIL ${label} — ${why}`) }
function report() {
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envfail} na=${na}`)
  process.exit(fail > 0 ? 1 : (envfail > 0 ? 2 : 0))
}

/* ------------------------------------------------------------------ fixtures */

/** A 1x1 PNG. The console never decodes it; only the served bytes matter. */
const PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
  '0000000a49444154789c6360000002000100ffff03000006000557bfabd40000' +
  '000049454e44ae426082', 'hex')

/** One engine-shaped descriptor (snake_case keys, as the snapshot stores them). */
function desc(stage, id, title, kind, source, extra) {
  return {
    id, title, kind, kind_known: kind !== 'hologram', source, repo: '',
    stage, note: '', open: '', shape: '', optional: false, legacy: false,
    round: null, ...(extra || {}),
  }
}

/** The artifacts stage order the console passes in (the template's order). */
const TOPOLOGY = { nodes: [{ id: 'plan' }, { id: 'implement' }], edges: [], groups: [] }

/** detail of the main fixture ticket: 21 declarations across two stages. */
function mainDetail(project) {
  return {
    id: 't-anchor', project, title: 'artifact fixture', status: 'running',
    stage: 'implement', stage_state: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    repo_worktrees: [
      { repo: '', name: 'root', branch: 'main' },
      { repo: 'member-a', name: 'member-a', branch: 'main' },
    ],
    topology: TOPOLOGY,
    gate_runs: [{ stage: 'plan', label: 'plan gate', green: true, red_count: 0, exit_code: 0 }],
    results: {
      plan: {
        status: 'ok', gen: 1, summary: 'plan done', deliverables: [],
        artifact_descriptors: [
          desc('plan', 'notes', 'Notes', 'text', 'art/notes.txt', { note: 'read me' }),
          desc('plan', 'chart', 'Chart', 'image', 'art/chart.png'),
          desc('plan', 'vector', 'Vector', 'image', 'art/vector.svg'),
          desc('plan', 'gone', 'Gone', 'text', 'art/gone.txt'),
          desc('plan', 'big', 'Big text', 'text', 'art/big.txt'),
          desc('plan', 'bigimg', 'Big image', 'image', 'art/big.png'),
          desc('plan', 'latin', 'Latin', 'text', 'art/latin1.txt'),
          desc('plan', 'linkabs', 'Link abs', 'text', 'art/abs-link.txt'),
          desc('plan', 'linkrel', 'Link rel', 'text', 'art/rel-link.txt'),
          desc('plan', 'trav', 'Traversal', 'text', '../outside-repo.txt'),
          desc('plan', 'abs', 'Absolute', 'text', '/etc/hosts'),
          desc('plan', 'url', 'Remote', 'text', 'https://example.invalid/x.txt'),
          desc('plan', 'empty', 'Empty', 'text', 'art/empty.txt'),
          desc('plan', 'onlya', 'Only in project A', 'text', 'art/only-a.txt'),
          desc('plan', 'shrink', 'Shrink attempt', 'text', 'art/notes.txt', { hidden: true, order: 0 }),
          desc('plan', 'backslash', 'Backslash id', 'text', 'art/notes.txt', { id: 'a\\b' }),
          desc('plan', 'percent', 'Percent id', 'text', 'art/notes.txt', { id: 'a%2Fb' }),
        ],
      },
      implement: {
        status: 'ok', gen: 2, summary: 'implement done', deliverables: [],
        artifact_descriptors: [
          desc('implement', 'notes', 'Impl notes', 'text', 'art/notes.txt'),
          desc('implement', 'member', 'Member report', 'text', 'art/report.txt', { repo: 'member-a' }),
          desc('implement', 'orphan', 'Orphan repo', 'text', 'art/x.txt', { repo: 'member-x' }),
          desc('implement', 'weird', 'Hologram', 'hologram', 'art/notes.txt'),
        ],
      },
    },
  }
}

function dupeDetail(project) {
  return {
    id: 't-dupe', project, title: 'duplicate id', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    results: {
      plan: {
        status: 'ok', gen: 1, deliverables: [],
        artifact_descriptors: [
          desc('plan', 'dupe', 'First', 'text', 'art/notes.txt'),
          desc('plan', 'dupe', 'Second', 'text', 'art/report.txt'),
        ],
      },
    },
  }
}

function legacyDetail(project) {
  return {
    id: 't-legacy', project, title: 'legacy paths only', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    results: { plan: { status: 'ok', gen: 1, deliverables: ['out/report.md', 'out/gone.png'] } },
  }
}

function emptyDetail(project) {
  return {
    id: 't-empty', project, title: 'no artifacts', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    results: { plan: { status: 'ok', gen: 1, deliverables: [], artifact_descriptors: [] } },
  }
}

/** ENGINE-SHAPED receipt (walkthrough 1): the engine writes an empty descriptor list with
 *  shape `absent` for a stage that declares nothing, and keeps its paths in `deliverables`.
 *  Reading the empty array as an explicit declaration hid those paths. */
function absentShapeDetail(project) {
  return {
    id: 't-absent', project, title: 'engine-shaped absent receipt', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    results: {
      plan: {
        status: 'ok', gen: 2, deliverables: ['out/report.md', 'out/gone.png'],
        artifact_descriptors: [], artifact_descriptors_shape: 'absent',
      },
    },
  }
}

/** A reworked stage: the canonical list is built from the HANDOFF history, so an earlier
 *  round's declarations stay visible even when the latest receipt declares nothing. The
 *  `ui_evidence` stage is the live shape of a stage the history never names: it records
 *  a receipt and no handoff, so the receipt is its only record. */
function reworkedDetail(project) {
  return {
    id: 't-rework', project, title: 'reworked stage', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    gens: { implement: 3 },
    handoffs: [
      { stage: 'implement', gen: 1, artifacts: ['art/notes.txt'], artifact_descriptors: [desc('implement', 'code', 'Code', 'text', 'art/notes.txt')] },
      { stage: 'implement', gen: 3, artifacts: ['out/report.md'] },
    ],
    results: {
      implement: {
        status: 'ok', gen: 3, deliverables: ['out/report.md'],
        artifact_descriptors: [], artifact_descriptors_shape: 'absent',
      },
      ui_evidence: { status: 'ok', gen: 0, deliverables: ['console-board.png'] },
    },
  }
}

/** A malformed HANDOFF history: the canonical source must stay total and must not
 *  swallow the stages it cannot read (a malformed entry names itself, and a stage it
 *  does not claim still lists its receipt). */
function badHandoffDetail(project) {
  return {
    id: 't-badhandoff', project, title: 'malformed handoff history', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    handoffs: [
      'not-an-object',
      { stage: 'implement', artifacts: 'not-a-list' },
      { stage: 'implement', artifact_descriptors: [{ id: 'x', source: '   ' }] },
    ],
    results: {
      plan: {
        status: 'ok', gen: 1,
        artifact_descriptors: [desc('plan', 'notes', 'Notes', 'text', 'art/notes.txt')],
      },
      implement: {
        status: 'ok', gen: 2, deliverables: [],
        artifact_descriptors: [desc('implement', 'code', 'Code', 'text', 'art/notes.txt')],
      },
    },
  }
}

/** One id declared in TWO rounds with different sources (the live `create_plan/plan` shape):
 *  the byte address carries no round, so only the row the lookup returns may offer the link. */
function roundSplitDetail(project) {
  return {
    id: 't-rounds', project, title: 'two rounds of one artifact', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    gens: { plan: 2 },
    handoffs: [
      { stage: 'plan', gen: 1, artifacts: [], artifact_descriptors: [desc('plan', 'plan', 'Plan', 'text', 'out/report.md')] },
      { stage: 'plan', gen: 2, artifacts: [], artifact_descriptors: [desc('plan', 'plan', 'Plan', 'text', 'art/notes.txt')] },
    ],
  }
}

function malformedDetail(project) {
  return {
    id: 't-bad', project, title: 'malformed snapshot', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    results: {
      plan: 'this receipt is not an object',
      implement: {
        gen: 'not-a-number',
        artifact_descriptors: [42, { source: '   ' }, desc('implement', 'good', 'Good', 'text', 'art/notes.txt')],
      },
    },
  }
}

function aggregateDetail(project) {
  return {
    id: 't-agg', project, title: 'engine flat list present', status: 'running',
    workspace: { type: 'lane', path: 'lanes/t-anchor' }, worktree: 'lanes/t-anchor',
    artifact_descriptors: [desc('plan', 'agg', 'Aggregated', 'text', 'art/notes.txt')],
    results: {
      plan: { status: 'ok', gen: 1, artifact_descriptors: [desc('plan', 'receipt', 'Receipt only', 'text', 'art/report.txt')] },
    },
  }
}

/** The fake `admin.py`: it answers `call ticket {"op":"show"}` for this repo. */
function fakeAdmin(details) {
  return [
    'import json, sys',
    `DETAILS = json.loads(${JSON.stringify(JSON.stringify(details))})`,
    'args = sys.argv[1:]',
    'if args[:2] == ["call", "ticket"]:',
    '    a = json.loads(args[2])',
    '    if a.get("op") == "show":',
    '        d = DETAILS.get(a.get("id"))',
    '        if d is None:',
    '            print(json.dumps({"ok": False, "error": "no such ticket: %s" % a.get("id"), "kind": "not_found"}))',
    '        else:',
    '            print(json.dumps({"ok": True, "result": d}))',
    '    else:',
    '        print(json.dumps({"ok": False, "error": "unsupported op: %s" % a.get("op")}))',
    'else:',
    '    print(json.dumps({"ok": False, "error": "unsupported argv: %r" % (args,)}))',
    '',
  ].join('\n')
}

function projectYaml(key, name, dir) {
  return `schema: v1\nproject:\n  - key: ${key}\n    name: ${name}\n    dirs:\n      - ${dir}\n`
}

/* ------------------------------------------------------- request/response IO */

function makeRes() {
  const res = {
    status: 0, headers: {}, chunks: [], raw: null, body: null, ended: false,
    writeHead(status, headers) {
      res.status = status
      if (Array.isArray(headers)) {
        for (const pair of headers) {
          if (Array.isArray(pair) && pair.length >= 2) res.headers[String(pair[0]).toLowerCase()] = pair[1]
        }
      } else if (headers && typeof headers === 'object') {
        for (const k of Object.keys(headers)) res.headers[k.toLowerCase()] = headers[k]
      }
      return res
    },
    setHeader(k, v) { res.headers[String(k).toLowerCase()] = v },
    getHeader(k) { return res.headers[String(k).toLowerCase()] },
    write(chunk) {
      if (chunk !== undefined && chunk !== null) res.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)))
      return true
    },
    end(chunk) {
      if (chunk !== undefined && chunk !== null) res.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)))
      res.raw = res.chunks.length > 0 ? Buffer.concat(res.chunks) : Buffer.alloc(0)
      try { res.body = JSON.parse(res.raw.toString('utf8')) } catch { res.body = null }
      res.ended = true
      return res
    },
  }
  return res
}

function routeFor(routes, url) {
  const path = url.split('?')[0]
  const exact = routes.find(r => r.kind === 'exact' && r.path === path)
  if (exact !== undefined) return exact
  const hits = routes.filter(r => r.kind === 'prefix' && path.startsWith(r.path))
  hits.sort((a, b) => b.path.length - a.path.length)
  return hits[0]
}

function makeHarness(apply, repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {}, error() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  return {
    routes,
    async call(url, method = 'GET') {
      const r = routeFor(routes, url)
      if (r === undefined) return { missingRoute: true, status: 0, headers: {}, raw: Buffer.alloc(0), body: null }
      const res = makeRes()
      const req = { url, method, async *[Symbol.asyncIterator]() { /* no request body */ } }
      await r.handler(req, res)
      return res
    },
  }
}

const sha = (b) => createHash('sha256').update(b).digest('hex')
const text = (res) => (res.raw ? res.raw.toString('utf8') : '')
const hdr = (res, name) => {
  const v = res.headers[String(name).toLowerCase()]
  return v === undefined ? '' : String(v)
}
const named = (res) => res.body !== null && typeof res.body === 'object'
  && res.body.ok === false && typeof res.body.error === 'string' && res.body.error.trim() !== ''
const isBytesOf = (res, file) => res.status === 200 && sha(res.raw) === sha(file)

/* --------------------------------------------------------------------- main */

let nodeMod = null
try {
  nodeMod = await import(join(ROOT, 'server/plugins/workbench/node.ts'))
} catch (e) {
  envFail('workbench node.ts unresolvable', String(e && e.stack || e).split('\n')[0])
}

let model = null
try {
  model = await import(join(ROOT, 'server/plugins/workbench/src/client/artifact-face-model.ts'))
} catch (e) {
  model = null
  ok('C0 the declared console model is present (src/client/artifact-face-model.ts)', false,
    String(e && e.message || e).split('\n')[0])
}

const FILES = {
  notes: Buffer.from('alpha notes line\n', 'utf8'),
  report: Buffer.from('member report line\n', 'utf8'),
  vector: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>\n', 'utf8'),
  outReport: Buffer.from('# legacy report\n', 'utf8'),
  empty: Buffer.alloc(0),
  latin1: Buffer.from([0x41, 0xff, 0xfe, 0x42]),
}

async function seedProject(dir, notesBody) {
  const art = join(dir, 'lanes', 't-anchor', 'art')
  await mkdir(art, { recursive: true })
  await mkdir(join(dir, 'lanes', 't-anchor', 'out'), { recursive: true })
  await mkdir(join(dir, 'lanes', 't-anchor', 'member-a', 'art'), { recursive: true })
  await mkdir(join(dir, 'server'), { recursive: true })
  await writeFile(join(art, 'notes.txt'), notesBody, 'utf8')
  await writeFile(join(art, 'chart.png'), PNG)
  await writeFile(join(art, 'vector.svg'), FILES.vector)
  await writeFile(join(art, 'big.txt'), Buffer.alloc(1024 * 1024 + 1, 0x61))
  await writeFile(join(art, 'big.png'), Buffer.alloc(8 * 1024 * 1024 + 1, 0x7f))
  await writeFile(join(art, 'latin1.txt'), FILES.latin1)
  await writeFile(join(art, 'empty.txt'), FILES.empty)
  await writeFile(join(dir, 'lanes', 't-anchor', 'out', 'report.md'), FILES.outReport)
  await writeFile(join(dir, 'lanes', 't-anchor', 'member-a', 'art', 'report.txt'), FILES.report)
  await writeFile(join(art, 'only-a.txt'), Buffer.from('only in project A\n', 'utf8'))
  return art
}

async function main() {
  // The fake ticket CLI is a python3 script (`runAdminCli` runs the project's
  // server/admin.py). Absent interpreter = environment fact, named once and never
  // reported as a product red.
  try {
    execFileSync('python3', ['-V'], { stdio: 'ignore', timeout: 10000 })
  } catch (e) {
    envFail('python3 absent, the fake ticket CLI cannot run', String(e && e.message || e).split('\n')[0])
    return
  }
  const tmp = await mkdtemp(join(tmpdir(), 'integ-t261030-35-'))
  const savedRegistry = process.env.SANDBAR_PROJECTS_DIR
  try {
    const repoA = join(tmp, 'repo-a')
    const repoB = join(tmp, 'repo-b')
    const outside = join(tmp, 'outside-repo.txt')
    await writeFile(outside, 'outside the project root\n', 'utf8')

    const artA = await seedProject(repoA, FILES.notes)
    await symlink(outside, join(artA, 'abs-link.txt'))
    await symlink('../../../../outside-repo.txt', join(artA, 'rel-link.txt'))

    const artB = await seedProject(repoB, Buffer.from('beta notes line\n', 'utf8'))
    await rm(join(artB, 'only-a.txt'), { force: true })

    await writeFile(join(repoA, 'server', 'admin.py'), fakeAdmin({
      't-anchor': mainDetail('fixture-a'),
      't-dupe': dupeDetail('fixture-a'),
      't-legacy': legacyDetail('fixture-a'),
      't-empty': emptyDetail('fixture-a'),
      't-bad': malformedDetail('fixture-a'),
      't-agg': aggregateDetail('fixture-a'),
      't-absent': absentShapeDetail('fixture-a'),
      't-rework': reworkedDetail('fixture-a'),
      't-rounds': roundSplitDetail('fixture-a'),
      't-badhandoff': badHandoffDetail('fixture-a'),
    }), 'utf8')
    await writeFile(join(repoB, 'server', 'admin.py'), fakeAdmin({
      't-anchor': mainDetail('fixture-b'),
    }), 'utf8')

    // Temp per-key project registry (the .migrated marker stops seed migration).
    const regDir = join(tmp, 'projects')
    for (const [key, dir] of [['fixture-a', repoA], ['fixture-b', repoB]]) {
      await mkdir(join(regDir, key), { recursive: true })
      await writeFile(join(regDir, key, 'project.yaml'), projectYaml(key, key, dir), 'utf8')
    }
    await writeFile(join(regDir, '.migrated'), 'fixture\n', 'utf8')
    process.env.SANDBAR_PROJECTS_DIR = regDir

    const h = makeHarness(nodeMod.apply, repoA)
    const detailUrl = `${TICKETS}/t-anchor`
    const listUrl = `${TICKETS}/t-anchor/artifacts`
    const bytesUrl = (key, id) =>
      `${TICKETS}/t-anchor/artifacts/${encodeURIComponent(String(key ?? '').split('/')[0])}/${encodeURIComponent(String(id ?? ''))}/bytes`

    section('L0 harness self-check')
    const detail0 = await h.call(detailUrl)
    ok('L0a the ticket prefix route is mounted and the fake CLI answers `ticket show`',
      detail0.status === 200 && detail0.body && detail0.body.ok === true && detail0.body.result
      && detail0.body.result.id === 't-anchor', `status=${detail0.status}`)

    section('A read-only: no method but GET')
    for (const method of ['POST', 'PUT', 'DELETE']) {
      const r = await h.call(listUrl, method)
      ok(`A1 ${method} on the inventory is a named 405`, r.status === 405 && named(r), `status=${r.status}`)
      const b = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes`, method)
      ok(`A2 ${method} on the bytes route is a named 405 and returns no bytes`,
        b.status === 405 && named(b) && sha(b.raw) !== sha(FILES.notes), `status=${b.status} len=${b.raw.length}`)
    }

    section('B the inventory lists every declared row and never drops one')
    const inv = await h.call(listUrl)
    ok('B1 inventory answers 200 ok', inv.status === 200 && inv.body && inv.body.ok === true, `status=${inv.status}`)
    const invRows = (inv.body && inv.body.result && Array.isArray(inv.body.result.rows)) ? inv.body.result.rows : []
    const invText = text(inv)
    const declaredKeys = [
      'plan/notes', 'plan/chart', 'plan/vector', 'plan/gone', 'plan/big', 'plan/bigimg',
      'plan/latin', 'plan/linkabs', 'plan/linkrel', 'plan/trav', 'plan/abs', 'plan/url',
      'plan/empty', 'plan/onlya', 'plan/shrink', 'plan/a\\b', 'plan/a%2Fb',
      'implement/notes', 'implement/member', 'implement/orphan', 'implement/weird',
    ]
    const esc = (v) => JSON.stringify(String(v)).slice(1, -1)
    for (const key of declaredKeys) {
      ok(`B2 row ${key} is listed (a row never vanishes)`, invText.includes(esc(key)))
    }
    ok('B3 the inventory carries one row per declaration', invRows.length === declaredKeys.length,
      `rows=${invRows.length} declared=${declaredKeys.length}`)
    const stats = (inv.body && inv.body.result && inv.body.result.stats) || undefined
    // The payload joins a row to its metadata through the row's own LISTING key
    // (`rowKey`; one row per round can share the same `<stage>/<id>` address), never
    // through the address alone. A row without a listing key falls back to its address,
    // so this leg stays honest whether the payload carries one row per address or many.
    const lookupOf = (r) => (typeof r.rowKey === 'string' && r.rowKey !== '' ? r.rowKey : r.key)
    const rowFor = (key) => invRows.find(r => r.key === key)
    const statOf = (key) => {
      const row = rowFor(key)
      if (row === undefined || stats === undefined || typeof stats !== 'object') return undefined
      return stats[lookupOf(row)]
    }
    ok('B4 the readable text row is ok with the real size',
      statOf('plan/notes') && statOf('plan/notes').state === 'ok'
      && statOf('plan/notes').sizeBytes === FILES.notes.length,
      JSON.stringify(statOf('plan/notes') || null))
    ok('B4b every listed row has its own metadata entry (no row renders blank)',
      stats !== undefined && Object.keys(stats).length === invRows.length
      && invRows.every(r => stats[lookupOf(r)] !== undefined),
      `stats=${stats === undefined ? 'absent' : Object.keys(stats).length} rows=${invRows.length}`)
    const unusable = ['plan/gone', 'plan/big', 'plan/bigimg', 'plan/latin', 'plan/linkabs', 'plan/linkrel',
      'plan/trav', 'plan/abs', 'plan/url', 'implement/orphan']
    for (const key of unusable) {
      const st = statOf(key)
      ok(`B5 ${key}: an unavailable row keeps a NAMED state (not ok, reason present)`,
        st !== undefined && typeof st.state === 'string' && st.state !== 'ok'
        && typeof st.reason === 'string' && st.reason.trim() !== '',
        JSON.stringify(st || null))
    }
    ok('B6 a descriptor claiming frame-owned keys (hidden/order) is still listed and the refusal is named',
      invText.includes('plan/shrink') && /hidden|order|frame/i.test(invText))
    const emptyInv = await h.call(`${TICKETS}/t-empty/artifacts`)
    const emptyRows = (emptyInv.body && emptyInv.body.result && emptyInv.body.result.rows) || []
    ok('B7 a ticket that declares nothing answers 200 with an explicit empty list (no error, no fabricated row)',
      emptyInv.status === 200 && emptyInv.body && emptyInv.body.ok === true && emptyRows.length === 0,
      `status=${emptyInv.status} rows=${emptyRows.length}`)
    const emptyRefusals = (emptyInv.body && emptyInv.body.result && emptyInv.body.result.refusals) || []
    ok('B7b an explicitly empty declaration list is NOT reported as a refused list (no false diagnosis)',
      Array.isArray(emptyRefusals) && emptyRefusals.length === 0, JSON.stringify(emptyRefusals))
    const absentInv = await h.call(`${TICKETS}/t-absent/artifacts`)
    const absentRows = (absentInv.body && absentInv.body.result && absentInv.body.result.rows) || []
    ok('B9 an engine-shaped absent receipt (empty list + shape absent) lists its deliverables',
      absentInv.status === 200 && absentRows.length === 2
      && absentRows.every(r => r.legacy === true),
      `status=${absentInv.status} rows=${absentRows.length}`)
    ok('B9b the absent-shape fallback names no refusal (a false diagnosis would mislead)',
      Array.isArray(absentInv.body && absentInv.body.result && absentInv.body.result.refusals)
      && absentInv.body.result.refusals.length === 0,
      JSON.stringify(absentInv.body && absentInv.body.result && absentInv.body.result.refusals))
    const reworkInv = await h.call(`${TICKETS}/t-rework/artifacts`)
    const reworkRows = (reworkInv.body && reworkInv.body.result && reworkInv.body.result.rows) || []
    // Match on the row's declared identity (`stage/id`), never on the listing-key label:
    // the label format is not part of the contract, the identity is.
    const reworkIds = reworkRows.map(r => `${r.stage}/${r.id}`)
    const implRounds = reworkRows.filter(r => r.stage === 'implement').map(r => r.round)
    ok('B10 a reworked stage keeps the earlier round\'s declaration AND the newest round\'s paths',
      reworkInv.status === 200 && reworkIds.includes('implement/code')
      && reworkIds.includes('implement/out-report-md')
      && implRounds.includes(1) && implRounds.includes(3),
      `ids=${JSON.stringify(reworkIds)} rounds=${JSON.stringify(implRounds)}`)
    ok('B10b a stage the handoff history never names lists its receipt deliverables',
      reworkInv.status === 200 && reworkIds.includes('ui_evidence/console-board-png'),
      JSON.stringify(reworkIds))
    ok('B10c the served list names both readers (the history and the un-named receipts)',
      String((reworkInv.body && reworkInv.body.result && reworkInv.body.result.listSource) || '') === 'handoffs+receipts',
      String(reworkInv.body && reworkInv.body.result && reworkInv.body.result.listSource))
    const roundsInv = await h.call(`${TICKETS}/t-rounds/artifacts`)
    const roundsRows = (roundsInv.body && roundsInv.body.result && roundsInv.body.result.rows) || []
    const r1 = roundsRows.find(r => r.round === 1)
    const r2 = roundsRows.find(r => r.round === 2)
    ok('B11 both rounds of one id are listed with their own listing identity',
      roundsInv.status === 200 && roundsRows.length === 2 && r1 && r2 && r1.rowKey !== r2.rowKey,
      JSON.stringify(roundsRows.map(r => `${r.rowKey}|${r.source}`)))
    ok('B11b ONLY the row the byte route serves offers the link (walkthrough 2, A8)',
      Boolean(r2) && r2.servable === true && Boolean(r1) && r1.servable === false,
      `r1.servable=${r1 && r1.servable} r2.servable=${r2 && r2.servable}`)
    ok('B11c the older row names the round it does not serve',
      Boolean(r1) && /round 2/.test(String(r1.byteRefusal || '')),
      `byteRefusal=${r1 && r1.byteRefusal}`)
    const roundsBytes = await h.call(`${TICKETS}/t-rounds/artifacts/plan/plan/bytes`)
    ok('B11d the address still serves the newest round, and it is the round the linked row names',
      roundsBytes.status === 200 && sha(roundsBytes.raw) === sha(FILES.notes),
      `status=${roundsBytes.status}`)
    const aggInv = await h.call(`${TICKETS}/t-agg/artifacts`)
    const aggText = text(aggInv)
    ok('B8 the engine flat list wins when the snapshot carries one (forward compatible branch)',
      aggInv.status === 200 && aggText.includes('plan/agg') && !aggText.includes('plan/receipt'),
      `status=${aggInv.status}`)

    section('C the client key is the host address (the seam)')
    if (model && typeof model.deriveArtifactRows === 'function') {
      const derived = model.deriveArtifactRows(mainDetail('fixture-a'), ['plan', 'implement'])
      const keys = (derived.rows || []).map(r => r.key)
      ok('C1 the console model mints the same row set the host lists', keys.length === declaredKeys.length
        && declaredKeys.every(k => keys.includes(k)), `model=${keys.length} declared=${declaredKeys.length}`)
      const notesRow = (derived.rows || []).find(r => r.title === 'Notes')
      const chartRow = (derived.rows || []).find(r => r.title === 'Chart')
      ok('C2 the model marks an addressable row servable', notesRow !== undefined && notesRow.servable === true)
      if (notesRow !== undefined) {
        const r = await h.call(bytesUrl(notesRow.key, notesRow.id))
        ok('C3 the model key addresses the byte route and the served bytes equal the file (text)',
          isBytesOf(r, FILES.notes), `status=${r.status} sha=${sha(r.raw).slice(0, 12)}`)
      }
      if (chartRow !== undefined) {
        const r = await h.call(bytesUrl(chartRow.key, chartRow.id))
        ok('C4 the same seam serves the image bytes unchanged', isBytesOf(r, PNG), `status=${r.status}`)
      }
    } else {
      ok('C1-C4 the declared console model is importable and exposes deriveArtifactRows', false)
    }
    const legacy = await h.call(`${TICKETS}/t-legacy/artifacts`)
    const legacyText = text(legacy)
    ok('C5 a pre-slice-1 ticket (deliverables only) lists its paths as guessed-kind rows',
      legacy.status === 200 && legacyText.includes('out/report.md') && legacyText.includes('out/gone.png'),
      `status=${legacy.status}`)
    const legacyBytes = await h.call(`${TICKETS}/t-legacy/artifacts/plan/out-report-md/bytes`)
    ok('C6 the legacy row is addressable by its derived id and serves the file',
      legacyBytes.status === 200 && sha(legacyBytes.raw) === sha(FILES.outReport),
      `status=${legacyBytes.status}`)

    section('D the status family and the named refusals')
    const undeclared = await h.call(`${TICKETS}/t-anchor/artifacts/plan/nosuchid/bytes`)
    ok('D1 an undeclared id is 404 and names the miss', undeclared.status === 404 && named(undeclared),
      `status=${undeclared.status}`)
    const wrongStage = await h.call(`${TICKETS}/t-anchor/artifacts/nosuchstage/notes/bytes`)
    ok('D2 an undeclared stage is 404 (the stage is part of the address)', wrongStage.status === 404 && named(wrongStage),
      `status=${wrongStage.status}`)
    const noTicket = await h.call(`${TICKETS}/t-nosuchticket/artifacts`)
    ok('D3 an unknown ticket is the family 404, never an empty list', noTicket.status === 404 && named(noTicket),
      `status=${noTicket.status}`)
    const dupe = await h.call(`${TICKETS}/t-dupe/artifacts/plan/dupe/bytes`)
    ok('D4 an id declared twice in one stage is 409 and the body names it (no first match)',
      dupe.status === 409 && named(dupe) && String(dupe.body.error).includes('dupe'),
      `status=${dupe.status} error=${dupe.body ? dupe.body.error : ''}`)
    const overCap = await h.call(`${TICKETS}/t-anchor/artifacts/plan/big/bytes`)
    ok('D5 an over-cap text source is 413 and names the cap', overCap.status === 413 && named(overCap),
      `status=${overCap.status}`)
    const overCapImg = await h.call(`${TICKETS}/t-anchor/artifacts/plan/bigimg/bytes`)
    ok('D6 an over-cap image source is 413 too', overCapImg.status === 413 && named(overCapImg),
      `status=${overCapImg.status}`)
    const backslash = await h.call(`${TICKETS}/t-anchor/artifacts/plan/a%5Cb/bytes`)
    ok('D7 a backslash id is a named 400, never a served file',
      backslash.status === 400 && named(backslash) && sha(backslash.raw) !== sha(FILES.notes),
      `status=${backslash.status}`)
    const doubleDecode = await h.call(`${TICKETS}/t-anchor/artifacts/plan/a%252Fb/bytes`)
    ok('D8 a percent id (the double-decode shape) is a named 400, never a served file',
      doubleDecode.status === 400 && named(doubleDecode) && sha(doubleDecode.raw) !== sha(FILES.notes),
      `status=${doubleDecode.status}`)
    const unusableIds = {
      'plan/gone': 'a declared but missing source',
      'plan/latin': 'a declared non-UTF-8 text source',
      'plan/linkabs': 'a symlink escaping the root (absolute target)',
      'plan/linkrel': 'a symlink escaping the root (relative target)',
      'plan/trav': 'a source that traverses out of the root',
      'plan/abs': 'an absolute source',
      'plan/url': 'a URL source (never fetched)',
      'implement/orphan': 'a member repo this ticket does not own',
    }
    for (const [key, label] of Object.entries(unusableIds)) {
      const r = await h.call(`${TICKETS}/t-anchor/artifacts/${key}/bytes`)
      ok(`D9 ${label} is a named 4xx that is NOT 404 and carries no bytes`,
        r.status >= 400 && r.status < 500 && r.status !== 404 && named(r)
        && sha(r.raw) !== sha(FILES.notes) && sha(r.raw) !== sha(FILES.report),
        `status=${r.status} error=${r.body && r.body.error ? String(r.body.error).slice(0, 90) : ''}`)
    }

    section('E the served response contract')
    const okText = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes`)
    ok('E1 a text artifact is served as text/plain (never text/html)',
      okText.status === 200 && /^text\/plain/.test(hdr(okText, 'content-type'))
      && !/html/i.test(hdr(okText, 'content-type')), `ct=${hdr(okText, 'content-type')}`)
    ok('E2 the text answer carries nosniff', /nosniff/i.test(hdr(okText, 'x-content-type-options')),
      hdr(okText, 'x-content-type-options'))
    ok('E3 the text answer is not cached', /no-store/i.test(hdr(okText, 'cache-control')),
      hdr(okText, 'cache-control'))
    const okPng = await h.call(`${TICKETS}/t-anchor/artifacts/plan/chart/bytes`)
    ok('E4 a PNG stays image/png and keeps the byte identity',
      okPng.status === 200 && /^image\/png/.test(hdr(okPng, 'content-type')) && isBytesOf(okPng, PNG),
      `ct=${hdr(okPng, 'content-type')}`)
    const svg = await h.call(`${TICKETS}/t-anchor/artifacts/plan/vector/bytes`)
    ok('E5 an SVG declared as an image leaves as an octet-stream download (never inline)',
      svg.status === 200 && /octet-stream/i.test(hdr(svg, 'content-type'))
      && /attachment/i.test(hdr(svg, 'content-disposition')),
      `ct=${hdr(svg, 'content-type')} cd=${hdr(svg, 'content-disposition')}`)
    const unknown = await h.call(`${TICKETS}/t-anchor/artifacts/implement/weird/bytes`)
    ok('E6 an unknown kind leaves as an octet-stream download',
      unknown.status === 200 && /octet-stream/i.test(hdr(unknown, 'content-type'))
      && /attachment/i.test(hdr(unknown, 'content-disposition')),
      `ct=${hdr(unknown, 'content-type')}`)
    ok('E7 every refusal answer also carries nosniff and no-store',
      /nosniff/i.test(hdr(undeclared, 'x-content-type-options')) && /no-store/i.test(hdr(undeclared, 'cache-control')),
      `ct-headers=${JSON.stringify(undeclared.headers)}`)

    section('F the project anchor decides the tree (KI-057 family)')
    const viaProject = await h.call(`${listUrl}?project=fixture-b`)
    ok('F1 the same ticket id under the second project lists rows (the anchor is per request)',
      viaProject.status === 200 && viaProject.body && viaProject.body.ok === true, `status=${viaProject.status}`)
    const bNotes = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes?project=fixture-b`)
    ok('F2 with ?project=fixture-b the bytes come from THAT project tree',
      bNotes.status === 200 && sha(bNotes.raw) === sha(Buffer.from('beta notes line\n', 'utf8'))
      && sha(bNotes.raw) !== sha(FILES.notes), `status=${bNotes.status}`)
    const noFallback = await h.call(`${listUrl}?project=no-such-project`)
    ok('F3 an unregistered project key is a named 400, never a silent fallback',
      noFallback.status === 400 && named(noFallback), `status=${noFallback.status}`)
    const onlyInA = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes?project=fixture-a`)
    ok('F4 project A serves its own bytes (the isolation face is both ways)',
      onlyInA.status === 200 && sha(onlyInA.raw) === sha(FILES.notes), `status=${onlyInA.status}`)
    const onlyA = await h.call(`${TICKETS}/t-anchor/artifacts/plan/onlya/bytes?project=fixture-a`)
    ok('F5 the artifact that exists only in project A is served under project A',
      onlyA.status === 200 && sha(onlyA.raw) === sha(Buffer.from('only in project A\n', 'utf8')),
      `status=${onlyA.status}`)
    const absentInB = await h.call(`${TICKETS}/t-anchor/artifacts/plan/onlya/bytes?project=fixture-b`)
    ok('F6 the same artifact is never served under project B (no cross-project read)',
      absentInB.status >= 400 && sha(absentInB.raw) !== sha(Buffer.from('only in project A\n', 'utf8'))
      && named(absentInB), `status=${absentInB.status}`)

    section('G the existing dispatch is intact')
    const detailNow = await h.call(detailUrl)
    ok('G1 the detail route is unchanged (same payload, same status)',
      detailNow.status === 200 && detailNow.body.result.stage === 'implement'
      && detailNow.body.result.results.plan.artifact_descriptors.length === 17,
      `status=${detailNow.status}`)
    // The family answers an unknown GET op with its own 405 ("the op face is POST"): the
    // leg pins the UNCHANGED answer, so a new route that swallowed the prefix would show
    // up here as a 200/404 instead of the family's 405.
    const unknownOp = await h.call(`${TICKETS}/t-anchor/nosuchop`)
    ok('G2 an unknown op still gets the family answer (the new routes did not shadow the prefix)',
      unknownOp.status === 405 && named(unknownOp), `status=${unknownOp.status}`)

    section('H malformed external input never throws')
    const bad = await h.call(`${TICKETS}/t-bad/artifacts`)
    const badText = text(bad)
    ok('H1 a malformed snapshot answers 200 ok (no 5xx)', bad.status === 200 && bad.body && bad.body.ok === true,
      `status=${bad.status}`)
    ok('H2 the good row in the same malformed snapshot is still listed', badText.includes('implement/good'),
      badText.slice(0, 200))
    ok('H3 the malformed entries are named by a refusal line', /refus|not an object|malformed|blank/i.test(badText),
      badText.slice(0, 200))
    if (model && typeof model.deriveArtifactRows === 'function') {
      let threw = ''
      for (const raw of [null, undefined, 42, 'text', { results: null }, { results: { plan: 7 } },
        { results: { plan: { artifact_descriptors: 'nope' } } }, { results: { plan: { artifact_descriptors: [null] } } },
        { handoffs: 'not-a-list' }, { handoffs: [null, { artifacts: 'x' }] }]) {
        try { model.deriveArtifactRows(raw) } catch (e) { threw = String(e && e.message || e) }
      }
      ok('H4 the console model never throws on a malformed snapshot', threw === '', threw)
    }
    const badH = await h.call(`${TICKETS}/t-badhandoff/artifacts`)
    const badHText = text(badH)
    ok('H5 a malformed HANDOFF history never throws and never swallows a stage it cannot read',
      badH.status === 200 && badH.body && badH.body.ok === true
      && badHText.includes('plan/notes') && badHText.includes('implement/code'),
      `status=${badH.status}`)
    ok('H5b the malformed handoff entries are named (a non-list list and a bad entry)',
      /not a list|not an object/i.test(badHText), badHText.slice(0, 200))

    section('I the read pool recovers')
    const baseline = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes`)
    ok('I0 baseline byte read still green before the concurrency leg', isBytesOf(baseline, FILES.notes),
      `status=${baseline.status}`)
    const many = await Promise.all(Array.from({ length: 6 }, () =>
      h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes`)))
    const served = many.filter(r => r.status === 200 && sha(r.raw) === sha(FILES.notes)).length
    const busy = many.filter(r => r.status === 503 && named(r)).length
    ok('I1 every concurrent read is either served with the file or refused BY NAME (never silently dropped)',
      served + busy === many.length, `served=${served} busy=${busy} statuses=${many.map(r => r.status).join(',')}`)
    const after = await h.call(`${TICKETS}/t-anchor/artifacts/plan/notes/bytes`)
    ok('I2 the pool is free afterwards (a later read is served)', isBytesOf(after, FILES.notes),
      `status=${after.status}`)
    if (model && typeof model.deriveArtifactRows === 'function') {
      const shape = model.deriveArtifactRows(mainDetail('fixture-a'), ['plan', 'implement'])
      ok('I3 the model still derives the same rows after the concurrent reads (no shared-state drift)',
        (shape.rows || []).length === declaredKeys.length)
    }

    section('J the delivered unit battery is live')
    try {
      const out = execFileSync('node', [join(ROOT, L1_BATTERY)], {
        cwd: ROOT, encoding: 'utf8', timeout: 120000, stdio: ['ignore', 'pipe', 'pipe'],
      })
      const lines = String(out).split('\n').filter(Boolean)
      const fails = lines.filter(l => /^FAIL\b/.test(l) || /^\s+FAIL\b/.test(l))
      ok('J1 the ticket L1 battery runs and is green', fails.length === 0,
        `${L1_BATTERY}: ${lines.slice(-2).join(' | ')}`)
    } catch (e) {
      const code = e && e.code
      const tail = String((e && (e.stdout || '')) + (e && (e.stderr || ''))).split('\n').filter(Boolean).slice(-2).join(' | ')
      if (code === 'ENOENT') envFail('node absent, cannot run the L1 battery', String(e.message || e))
      else if (e && e.code === 'ETIMEDOUT') envFail('the L1 battery did not finish inside 120s', tail)
      else ok('J1 the ticket L1 battery exists and is green', false, `${L1_BATTERY} not green: ${tail}`)
    }
  } finally {
    if (savedRegistry === undefined) delete process.env.SANDBAR_PROJECTS_DIR
    else process.env.SANDBAR_PROJECTS_DIR = savedRegistry
    await rm(tmp, { recursive: true, force: true }).catch(() => {})
  }
}

if (nodeMod !== null) {
  try {
    await main()
  } catch (e) {
    fail += 1
    console.log(`  FAIL harness exception — ${String(e && e.stack || e).split('\n').slice(0, 3).join(' | ')}`)
  }
}
report()
