/**
 * Baseline: empty-write-set declaration bridge (ticket t260901-01, group: user scenario).
 *
 * Intent (black-box, user-visible behavior):
 *   A user creating a ticket that truly changes no files used to hit a dead end:
 *   "Temporal 拒绝: 写集为空". The engine already honors allow_empty_write_set, but the
 *   bridge (agent-facing tool schema -> host create route -> client dialog) dropped the
 *   declaration, and the pre-run suggestion dropped its write_set. This baseline locks
 *   the user-facing promise end to end:
 *     (1) an agent/tool caller CAN pass allow_empty_write_set on create;
 *     (2) the workbench dialog offers the explicit "no file changes" declaration and
 *         attaches it to the POST body only when the write set is empty and checked;
 *     (3) the host forwards the declaration as-is and never fabricates it;
 *     (4) a pre-run suggestion's write_set survives into the cached suggestion;
 *     (5) without the declaration, an empty write set is still rejected with the
 *         two-way-out message (guardrail intact, not silently loosened).
 *
 * High-level steps:
 *   A. Tool-surface contract (offline): import server/tools/ticket.py TOOL schema and
 *      lock the _create payload forwarding of allow_empty_write_set (source lock).
 *   B. Client dialog contract (offline): import src/client/epics-model.ts and assert
 *      createWriteSetBlocked / buildCreatePayload semantics per the approved plan.
 *   C. Host bridge (offline): drive node.ts apply() HTTP harness with a recording
 *      admin.py stub; assert what the host actually forwards to the ticket tool.
 *   D. Pre-run suggestion write_set (needs temporalio SDK, else SKIP): assert
 *      _parse_suggest_result keeps/cleans write_set and done/failed stay unchanged.
 *   E. Env half, negative path (write-guarded): real client.py ticket-start with an
 *      empty write set and NO declaration is rejected BEFORE any workflow starts.
 *      (The positive real-creation path is owned by the ticket-validate baseline env
 *      half, which already creates a declared empty-write-set ticket; not duplicated.)
 *
 * Write-guard (this test refuses to touch production):
 *   SUYOU_TARGET_HOST unset            -> skip section E loudly (client.py would
 *                                         default to production 127.0.0.1:7233).
 *   SUYOU_TARGET_HOST == 127.0.0.1:7233 -> FAIL this test itself.
 *   Section E is rejected pre-connect, so no Temporal instance needs to be up.
 *
 * Contract source: approved plan of t260901-01 (create_plan gen1, reviewed gen1).
 * If the pure-function names/signatures drift from the plan, this baseline FAILs by
 * design -- that is the integration acceptance for the implement stage.
 */

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'
import { connect } from 'node:net'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function skipped(label) { skip++; console.log(`  SKIP ${label}`) }
function section(t) { console.log(`\n== ${t}`) }

const REPO = process.cwd()
const POC = join(REPO, 'server', 'dsh', 'temporal-poc')
const TOOLS = join(REPO, 'server', 'tools')
const PROD_ADDR = '127.0.0.1:7233'

/** Run a python snippet; forward output; return {stdout, status}. */
function runPy(python, code, env = {}) {
  const r = spawnSync(python, ['-c', code], { encoding: 'utf8', timeout: 120_000, env: { ...process.env, ...env } })
  process.stdout.write(r.stdout ?? '')
  if (r.stderr) process.stderr.write(r.stderr)
  return r
}

/** Probe for a python interpreter with the temporalio SDK. In a lane worktree the
 *  venv is absent, so also try the main checkout's venv (resolved via git common dir)
 *  -- importing worktree code with the main venv interpreter is safe (sys.path first). */
function probeSdkPython() {
  const venvPy = join(POC, '.venv', 'bin', 'python')
  const cands = existsSync(venvPy) ? [venvPy, 'python3'] : ['python3']
  const gitDir = spawnSync('git', ['rev-parse', '--git-common-dir'], { encoding: 'utf8', cwd: REPO })
  if (gitDir.status === 0) {
    const dotGit = gitDir.stdout.trim()
    const mainVenv = join(dirname(dotGit), 'server', 'dsh', 'temporal-poc', '.venv', 'bin', 'python')
    if (existsSync(mainVenv) && !cands.includes(mainVenv)) cands.unshift(mainVenv)
  }
  for (const py of cands) {
    const r = spawnSync(py, ['-c', 'import temporalio'], { encoding: 'utf8', timeout: 30_000 })
    if (r.status === 0) return py
  }
  return null
}

/* ------------------------------------------------------------ A. tool-surface contract */
section('A ticket tool schema + _create payload forwarding (offline, agent-facing surface)')
{
  const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(TOOLS)})
import ticket
props = ticket.TOOL['parameters']['properties']
out = {
  'has_flag': 'allow_empty_write_set' in props,
  'flag_type': props.get('allow_empty_write_set', {}).get('type'),
  'additional_props_closed': ticket.TOOL['parameters'].get('additionalProperties') is False,
  'op_enum': ticket.TOOL['parameters']['properties'].get('op', {}).get('enum'),
}
src = open(${JSON.stringify(join(TOOLS, 'ticket.py'))}, encoding='utf-8').read()
# Source lock: the create payload handed to ticket-start must carry the declaration
# (schema acceptance alone would not prove the value reaches the engine).
i = src.find("_poc('ticket-start'")
payload_region = src[i:i+2000] if i >= 0 else ''
out['payload_forwards_flag'] = 'allow_empty_write_set' in payload_region
print('ADONE ' + json.dumps(out))
`
  const r = runPy('python3', py)
  const m = /ADONE (\{.*\})/.exec(r.stdout ?? '')
  if (!m) {
    fail++
    console.error('  FAIL tool-surface probe failed (no ADONE summary; ticket.py import broken?)')
  } else {
    const o = JSON.parse(m[1])
    ok(o.has_flag === true, 'tool schema exposes allow_empty_write_set (path ② reachable for tool callers)')
    ok(o.flag_type === 'boolean', 'allow_empty_write_set typed boolean')
    ok(o.additional_props_closed === true, 'schema still additionalProperties:false (surface not loosened)')
    ok(Array.isArray(o.op_enum) && o.op_enum.includes('create'), 'op enum unchanged (create present)')
    ok(o.payload_forwards_flag === true, '_create forwards allow_empty_write_set into ticket-start payload (source lock)')
  }
}

/* ------------------------------------------------------------ B. client dialog contract */
section('B client dialog pure functions (offline, epics-model.ts per approved plan)')
try {
  const modUrl = pathToFileURL(join(REPO, 'server', 'dsh', 'workbench', 'src', 'client', 'epics-model.ts')).href
  const m = await import(modUrl)
  const blocked = m.createWriteSetBlocked
  const build = m.buildCreatePayload
  if (typeof blocked !== 'function' || typeof build !== 'function') {
    fail++
    console.error('  FAIL epics-model.ts does not export createWriteSetBlocked/buildCreatePayload (implement stage not done or drifted from approved plan)')
  } else {
    const emptyMsg = blocked('', false)
    ok(typeof emptyMsg === 'string' && emptyMsg.includes('写集为空'),
      'empty write set, unchecked -> blocked with message naming the problem')
    ok(emptyMsg.includes('两条出路') && emptyMsg.includes('allow_empty_write_set'),
      'blocked message carries BOTH ways out (① fill write set ② explicit declaration)')
    ok(blocked('', true) === '', 'empty write set, checked -> not blocked')
    ok(blocked('a.py', true) === '' && blocked('a.py', false) === '',
      'non-empty write set -> never blocked regardless of checkbox')

    const base = { workflow: 'dev-lane', title: 't', body: 'b', epic: 'demo-epic' }
    const p1 = build({ ...base }, '', true)
    ok(p1?.allow_empty_write_set === true, 'empty + checked -> payload carries allow_empty_write_set:true')
    ok(Array.isArray(p1?.write_set) && p1.write_set.length === 0, 'empty + checked -> write_set stays empty array')
    const p2 = build({ ...base }, '', false)
    ok(p2 != null && !('allow_empty_write_set' in p2),
      'empty + unchecked -> payload has NO declaration key (engine must stay the rejector)')
    const p3 = build({ ...base }, 'a.py\n  b.py  ', true)
    ok(JSON.stringify(p3?.write_set) === JSON.stringify(['a.py', 'b.py']),
      'non-empty write set parsed line-by-line with trim')
    ok(p3 != null && !('allow_empty_write_set' in p3),
      'non-empty + checked -> declaration NOT attached (write set wins, no false no_file_changes meta)')
    ok(p1?.workflow === 'dev-lane' && p1?.title === 't' && p1?.epic === 'demo-epic',
      'base fields preserved in payload')
  }
} catch (e) {
  fail++
  console.error(`  FAIL client dialog contract untestable: ${e?.message ?? e}`)
}

/* ------------------------------------------------------------ C. host bridge (HTTP level) */
section('C host bridge forwards the declaration (offline, node.ts apply + recording stub)')
try {
  const tmp = await mkdtemp(join(tmpdir(), 'integ-ws-declare-'))
  const recFile = join(tmp, 'tool-args.json')
  await mkdir(join(tmp, 'server', 'dsh'), { recursive: true })
  await writeFile(join(tmp, 'server', 'dsh', 'projects.yaml'),
    `projects:\n  - key: suyou\n    name: integ\n    dirs:\n      - ${tmp}\n`, 'utf8')
  // Recording stub: capture exactly the args the host hands to the ticket tool.
  await writeFile(join(tmp, 'server', 'admin.py'), `import json, sys, os
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'create':
    open(os.environ['STUB_REC'], 'w').write(json.dumps(args))
    print(json.dumps({"ok": True, "result": {"id": "t-new"}}))
    sys.exit(0)
print(json.dumps({"ok": True, "result": {"workflows": [{"id": "dev-lane", "name": "dev"}], "count": 0, "tickets": []}}))
sys.exit(0)
`, 'utf8')

  process.env.SUYOU_PROJECTS_YAML = join(tmp, 'server', 'dsh', 'projects.yaml')
  process.env.SUYOU_EPICS_DIR = join(tmp, 'notes', 'epics')
  process.env.STUB_REC = recFile
  const { apply } = await import(pathToFileURL(join(REPO, 'server', 'dsh', 'workbench', 'node.ts')).href)
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  apply({ effect: (fn) => fn(), logger: { info() {}, warn() {} }, get: (k) => (k === 'webServer' ? ws : undefined), on: () => () => {} }, { repo: tmp })
  const ticketsRoute = routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/wf/tickets')
  if (!ticketsRoute) {
    fail++
    console.error('  FAIL /wf/tickets route not mounted (harness broke?)')
  } else {
    const call = async (bodyObj) => {
      const res = { status: 0, body: null, writeHead(s) { this.status = s }, end(b) { this.body = b ? JSON.parse(b) : null } }
      const req = { url: '/sandbar-workbench/api/wf/tickets?project=suyou', method: 'POST', async *[Symbol.asyncIterator]() { yield Buffer.from(JSON.stringify(bodyObj)) } }
      await ticketsRoute.handler(req, res)
      return res
    }
    const base = { workflow: 'dev-lane', title: 'integ declaration bridge', body: '', epic: 'demo-epic' }

    const r1 = await call({ ...base, write_set: [], allow_empty_write_set: true })
    const rec1 = JSON.parse(await readFile(recFile, 'utf8'))
    ok(r1.status === 200 && r1.body?.ok === true && r1.body?.result?.id === 't-new',
      'declared empty-write-set create succeeds at host level')
    ok(rec1.allow_empty_write_set === true, 'host forwards allow_empty_write_set:true to the ticket tool')
    ok(!Array.isArray(rec1.write_set) || rec1.write_set.length === 0,
      'empty write set not fabricated into entries (host forwards it absent/empty; engine treats absent as empty)')

    await call({ ...base, write_set: [] })
    const rec2 = JSON.parse(await readFile(recFile, 'utf8'))
    ok(rec2.allow_empty_write_set !== true, 'no declaration in request -> host does not fabricate one (host 不代办)')

    await call({ ...base, write_set: ['a.py', 'b.py'], allow_empty_write_set: true })
    const rec3 = JSON.parse(await readFile(recFile, 'utf8'))
    ok(JSON.stringify(rec3.write_set) === JSON.stringify(['a.py', 'b.py']),
      'non-empty write_set forwarded intact')
    await rm(tmp, { recursive: true, force: true }).catch(() => {})
  }
} catch (e) {
  fail++
  console.error(`  FAIL host bridge section untestable: ${e?.message ?? e}`)
}

/* ------------------------------------------------------------ D. pre-run suggestion keeps write_set */
section('D pre-run suggestion write_set passthrough (needs temporalio SDK)')
{
  const py = probeSdkPython()
  if (!py) {
    skipped('temporalio SDK unavailable (no server/dsh/temporal-poc/.venv, no system temporalio) -- agent_activities.py not importable')
  } else {
    const r = runPy(py, `
import json, sys
sys.path.insert(0, ${JSON.stringify(POC)})
from agent_activities import _parse_suggest_result
mixed = ['b.py', 'a.py', 'b.py', '/bad', './../../../../integration/x', 'a\\\\b.py', 'C:/y', '  c.py ', 42, None, '']
kind, sug, err = _parse_suggest_result({'status': 'ok', 'workflow': 'dev-lane', 'title': 't', 'write_set': mixed})
out = {'kind': kind, 'ws': sug.get('write_set') if isinstance(sug, dict) else None}
k2, s2, _ = _parse_suggest_result({'status': 'ok', 'workflow': 'dev-lane', 'title': 't', 'write_set': 'not-a-list'})
out['kind2'] = k2
out['ws2'] = s2.get('write_set') if isinstance(s2, dict) else None
k3, s3, _ = _parse_suggest_result({'status': 'done', 'summary': 's'})
out['done_has_ws'] = isinstance(s3, dict) and 'write_set' in s3
k4, s4, _ = _parse_suggest_result({'status': 'failed', 'reason': 'r'})
out['failed_has_ws'] = isinstance(s4, dict) and 'write_set' in s4
# cache roundtrip: suggestion json must not strip write_set
out['roundtrip'] = json.loads(json.dumps({'write_set': out['ws']}))['write_set']
print('DDONE ' + json.dumps(out))
`)
    const m = /DDONE (\{.*\})/.exec(r.stdout ?? '')
    if (!m) {
      fail++
      console.error('  FAIL pre-run suggestion probe failed (no DDONE summary)')
    } else {
      const o = JSON.parse(m[1])
      ok(o.kind === 'ok' && JSON.stringify(o.ws) === JSON.stringify(['b.py', 'a.py', 'c.py']),
        'ok-form suggestion keeps write_set: valid entries only, trimmed, deduped, order kept')
      ok(o.kind2 === 'ok' && (o.ws2 === null || (Array.isArray(o.ws2) && o.ws2.length === 0)),
        'non-list write_set -> suggestion still ok with empty write_set (not blocked)')
      ok(o.done_has_ws === false && o.failed_has_ws === false, 'done/failed forms unchanged (no write_set key)')
      ok(JSON.stringify(o.roundtrip) === JSON.stringify(o.ws), 'suggestion json roundtrip preserves write_set (pre.json safe)')
    }
  }
}

/* ------------------------------------------------------------ E. env half: negative path (guarded) */
section('E real client.py: empty write set WITHOUT declaration is rejected pre-connect (write-guarded)')
{
  const target = process.env.SUYOU_TARGET_HOST
  if (target === PROD_ADDR) {
    fail++
    console.error(`  FAIL write-guard: SUYOU_TARGET_HOST explicitly points at production default ${PROD_ADDR} -- refusing to run (red line: production is read-only)`)
  } else if (target === undefined) {
    skipped(`write-guard refused to run: SUYOU_TARGET_HOST not set explicitly (client.py would default to production ${PROD_ADDR}); set it to the test env address to enable`)
  } else {
    const py = probeSdkPython()
    if (!py) {
      skipped('temporalio SDK unavailable -- client.py not runnable')
    } else {
      const r = spawnSync(py,
        [join(POC, 'client.py'), 'ticket-start', JSON.stringify({
          ticket_id: `integ-ws-neg-${Date.now().toString(36)}`, template_id: 'dev-lane',
          project: 'suyou', title: 'should never be created (no write set, no declaration)',
        })],
        { encoding: 'utf8', timeout: 120_000, env: { ...process.env, SUYOU_NAMESPACE: 'suyou-test' } })
      let res = null
      try { res = JSON.parse(r.stdout ?? '') } catch { /* parse failure falls through */ }
      ok(res?.ok === false && String(res?.error ?? '').includes('写集为空'),
        'empty write set, no declaration -> rejected with 写集为空 (before any workflow starts)')
      ok(String(res?.error ?? '').includes('write_set') && String(res?.error ?? '').includes('allow_empty_write_set'),
        'rejection message still names both ways out')
    }
  }
}

/* ------------------------------------------------------------ wrap up */
console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
