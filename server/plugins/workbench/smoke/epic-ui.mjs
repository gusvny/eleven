/**
 * smoke/epic-ui.mjs — smoke for the epic Tier 3 UI (t260826-02) pure functions + the create-ticket route.
 *
 * Run: node smoke/epic-ui.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. src/client/epics-model.ts pure functions:
 *      bucketOf (closed/verified->「已完成」 (done), terminated->「已终止」 (terminated), everything
 *      else including unknown->「进行中」 (in progress)); sortBucketKeys (in progress -> done ->
 *      terminated -> unknown in dictionary order); sortEpicTickets (in progress first,
 *      closed last, each by id descending; empty array / missing fields tolerated);
 *      epicBadgeOf three states (has code / empty string / undefined -> 「未归档」 (not archived),
 *      code=null); epicCreateNote (contains the code + the do-not-type-by-hand hint).
 *   B. POST /sandbar-workbench/api/wf/tickets (node.ts handleTickets method branch +
 *      handleTicketCreate, stub admin.py + mock webServer/req/res, same pattern as section C
 *      of smoke/epics.mjs):
 *      missing project/workflow/title -> 400; valid body -> admin.py receives op=create with
 *      epic/project/workflow/title/body passed through byte-identical (the stub writes
 *      last-call.json as evidence) -> 200 with the new id; admin.py returns ok:false -> 200
 *      with the error text passed through; admin.py crashes (non-JSON) -> 502; PUT -> 405;
 *      the GET list regression is unaffected.
 */

import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  bucketOf, epicBadgeOf, epicCreateNote, mergeBuckets, sortBucketKeys, sortEpicTickets,
} from '../src/client/epics-model.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = await mkdtemp(join(tmpdir(), 'wb-epic-ui-'))
try {
  /* ------------------------------------------------------------ A. Pure functions */
  section('A epics-model 纯函数')

  ok(bucketOf('closed') === '已完成' && bucketOf('verified') === '已完成'
    && bucketOf('terminated') === '已终止'
    && bucketOf('dispatched') === '进行中' && bucketOf('running-whatever') === '进行中'
    && bucketOf('') === '进行中' && bucketOf('未知状态') === '进行中',
    'bucketOf：closed/verified→已完成、terminated→已终止、其余（含空/未知）→进行中')

  {
    const keys = sortBucketKeys(['已完成', 'zzz-未知', '已终止', '进行中', 'aaa-未知'])
    ok(keys.join(',') === '进行中,已完成,已终止,aaa-未知,zzz-未知',
      'sortBucketKeys：进行中→已完成→已终止→未知桶字典序')
    ok(JSON.stringify(sortBucketKeys([])) === '[]', 'sortBucketKeys 空数组不抛')
  }

  {
    const merged = mergeBuckets({ closed: 2, verified: 1, dispatched: 3, terminated: 1, running: 1 })
    ok(merged['进行中'] === 4 && merged['已完成'] === 3 && merged['已终止'] === 1
      && Object.keys(merged).length === 3,
      'mergeBuckets：原始 status 按 bucketOf 归并求和（dispatched+running→进行中 等）')
    ok(JSON.stringify(mergeBuckets({})) === '{}' && JSON.stringify(mergeBuckets(undefined)) === '{}',
      'mergeBuckets 空/缺入参容错')
    const bad = mergeBuckets({ closed: 'x' })
    ok(bad['已完成'] === 0, 'mergeBuckets 非数字值归 0 不抛')
  }

  {
    const rows = [
      { id: 't260825-01', title: 'a', status: 'closed', stage: 'settled', stage_state: 'done' },
      { id: 't260826-02', title: 'b', status: 'dispatched', stage: 'implement', stage_state: 'running' },
      { id: 't260825-04', title: 'c', status: 'closed', stage: 'settled', stage_state: 'done' },
      { id: 't260826-01', title: 'd', status: 'running', stage: 'x', stage_state: 'running' },
      { id: 't260824-09', title: 'e', status: 'terminated', stage: '', stage_state: '' },
    ]
    const sorted = sortEpicTickets(rows).map(r => r.id).join(',')
    ok(sorted === 't260826-02,t260826-01,t260825-04,t260825-01,t260824-09',
      'sortEpicTickets：进行中前（id 降序）→ 已完成（id 降序）→ 已终止')
    ok(JSON.stringify(sortEpicTickets([])) === '[]', 'sortEpicTickets 空数组不抛')
    const ragged = sortEpicTickets([{ id: 't1' }, {}])
    ok(ragged.length === 2, 'sortEpicTickets 缺字段行容错不抛')
  }

  {
    const withEpic = epicBadgeOf('epic-linkage')
    ok(withEpic.label === 'epic-linkage' && withEpic.code === 'epic-linkage', 'epicBadgeOf：有代号 → 可点 chip')
    const empty1 = epicBadgeOf('')
    const empty2 = epicBadgeOf(undefined)
    const empty3 = epicBadgeOf('  ')
    ok(empty1.label === '未归档' && empty1.code === null
      && empty2.label === '未归档' && empty2.code === null
      && empty3.label === '未归档' && empty3.code === null,
      'epicBadgeOf：空串/undefined/纯空白 → 灰「未归档」chip（code=null）')
  }

  {
    const note = epicCreateNote('demo-epic')
    ok(note.includes('demo-epic') && note.includes('不可修改'),
      'epicCreateNote：含代号 + 禁手输提示')
  }

  /* ------------------------------------------------------------ B. POST /wf/tickets create route */
  section('B POST /sandbar-workbench/api/wf/tickets（handleTicketCreate）')
  {
    // Shared mock pieces (same pattern as section C of smoke/epics.mjs; yields one chunk when the POST carries a body)
    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET', payload) => ({
      url, method,
      async *[Symbol.asyncIterator]() {
        if (payload !== undefined) yield Buffer.from(JSON.stringify(payload))
      },
    })
    const setup = (repo) => {
      const routes = []
      const ws = { register: (r) => { routes.push(r); return () => {} } }
      const ctx = {
        effect: (fn) => { fn() },
        logger: { info() {}, warn() {} },
        get: (k) => (k === 'webServer' ? ws : undefined),
        on: () => () => {},
      }
      apply(ctx, { repo })
      return {
        exactTickets: routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/wf/tickets'),
      }
    }
    const call = async (handler, url, method = 'GET', payload) => {
      const res = mockRes()
      await handler.handler(mockReq(url, method, payload), res)
      return res
    }
    // stub admin.py: the create branch writes the received args to last-call.json (pass-through
    // evidence) and answers by createMode: ok:true (with new id) / ok:false (epic strict-validation
    // rejection style) / crashes with non-JSON; list answers normally.
    const writeStub = async (repo, createMode) => {
      const createBranch =
        createMode === 'ok'
          ? 'print(json.dumps({"ok": True, "result": {"id": "t260826-99", "epic": args.get("epic", ""), "status": "dispatched"}}))'
          : createMode === 'fail'
            ? 'print(json.dumps({"ok": False, "error": "立项代号不存在：\\\'no-such\\\'（notes/epics/ 无此档案）"}))\n    sys.exit(1)'
            : "sys.stderr.write('temporal unreachable: connection refused'); sys.exit(2)"
      await mkdir(join(repo, 'server'), { recursive: true })
      await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'create':
    with open(${JSON.stringify(join(repo, 'last-call.json'))}, 'w') as f:
        json.dump(args, f)
    ${createBranch}
    sys.exit(0)
if tool == 'ticket' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"count": 0, "tickets": []}}))
    sys.exit(0)
if tool == 'workflow' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"workflows": []}}))
    sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')
    }

    /* --- B1 parameter validation: missing project / workflow / title -> 400 (never reaches the engine) --- */
    const repoA = join(tmp, 'repo-a')
    await writeStub(repoA, 'ok')
    const s1 = setup(repoA)
    ok(s1.exactTickets !== undefined, 'exact /wf/tickets 路由已挂')
    let r = await call(s1.exactTickets, '/sandbar-workbench/api/wf/tickets', 'POST', { workflow: 'dev-lane', title: 'x' })
    ok(r.status === 400 && r.body.error.includes('project'), 'POST 缺 project → 400')
    r = await call(s1.exactTickets, '/sandbar-workbench/api/wf/tickets?project=bogus-project', 'POST', { workflow: 'dev-lane', title: 'x' })
    ok(r.status === 400, 'POST 未知 project → 400（注册表白名单）')
    r = await call(s1.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', { title: 'x' })
    ok(r.status === 400 && r.body.error.includes('workflow'), 'POST 缺 workflow → 400 人话')
    r = await call(s1.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', { workflow: 'dev-lane', title: '  ' })
    ok(r.status === 400 && r.body.error.includes('title'), 'POST 纯空白 title → 400 人话')
    r = await call(s1.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', 'not-json')
    // 'not-json' gets wrapped into valid JSON by JSON.stringify; to send an illegal body it must be sent raw — here we assert valid JSON with missing fields also gets 400
    ok(r.status === 400, 'POST 合法 JSON 但缺 workflow → 400')

    /* --- B2 valid create: op=create + epic/project/workflow/title/body passed through byte-identical --- */
    const repoB = join(tmp, 'repo-b')
    await writeStub(repoB, 'ok')
    const s2 = setup(repoB)
    r = await call(s2.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', {
      workflow: 'dev-lane', title: '测试单', body: '所属立项：demo-epic\n正文', epic: 'demo-epic',
    })
    ok(r.status === 200 && r.body.ok === true && r.body.result.id === 't260826-99',
      'POST 合法 → 200 带新工单 id')
    const lastCall = JSON.parse(await readFile(join(repoB, 'last-call.json'), 'utf8'))
    ok(lastCall.op === 'create' && lastCall.epic === 'demo-epic' && lastCall.project === 'suyou'
      && lastCall.workflow === 'dev-lane' && lastCall.title === '测试单'
      && lastCall.body === '所属立项：demo-epic\n正文',
      'admin.py 收到 op=create，epic/project/workflow/title/body 原样透传（last-call.json 取证）')

    /* --- B3 engine failure, two paths: ok:false -> 200 passes the error through; crash -> 502 --- */
    const repoC = join(tmp, 'repo-c')
    await writeStub(repoC, 'fail')
    const s3 = setup(repoC)
    r = await call(s3.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', {
      workflow: 'dev-lane', title: 'x', epic: 'no-such',
    })
    ok(r.status === 200 && r.body.ok === false && r.body.error.includes('立项代号不存在'),
      'admin.py 回 ok:false（epic 强校验拒收）→ 200 透传 error 原文')
    const repoD = join(tmp, 'repo-d')
    await writeStub(repoD, 'crash')
    const s4 = setup(repoD)
    r = await call(s4.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'POST', {
      workflow: 'dev-lane', title: 'x',
    })
    ok(r.status === 502 && String(r.body.error).includes('connection refused'),
      'admin.py 崩（非 JSON）→ 502 含底层 error 原文')

    /* --- B4 method branch: PUT -> 405; GET list regression --- */
    r = await call(s2.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou', 'PUT', {})
    ok(r.status === 405, 'PUT → 405')
    r = await call(s2.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou')
    ok(r.status === 200 && r.body.ok === true && Array.isArray(r.body.result.tickets),
      'GET 列表回归不受影响')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
