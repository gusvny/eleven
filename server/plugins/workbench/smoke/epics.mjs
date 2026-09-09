/**
 * smoke/epics.mjs — host half-smoke for the read-only epic API (epic-linkage Tier 2, t260825-04).
 *
 * Run: node smoke/epics.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. parseEpicMeta / listEpics (src/host/epics.ts pure functions): title = first # line
 *      (the 「立项单：」 prefix stripped), status/start date = field-table rows (tolerant of
 *      missing ''); directory missing/empty -> empty array, no error; non-.md files / codes
 *      with an illegal shape are not listed; sorted by code.
 *   B. readEpicMarkdown: valid -> full text + meta; malformed shape (uppercase / dots /
 *      overlong) -> 400; resolve escape-guard double-checked (the path must stay inside
 *      epicsDir); missing -> 404 with the list of existing codes.
 *   C. Routes (node.ts apply + mock webServer/req/res + stub admin.py):
 *      GET /api/epics (SANDBAR_EPICS_DIR pointing at a temp dir / empty dir / default
 *      <repo>/notes/epics); GET /api/epics/<code> (200 full text / 400 shape / 4xx escape
 *      guard for ..%2f style / 404 missing); GET /api/epics/<code>/tickets (status buckets +
 *      ticket row fields; both degradation paths — admin.py returns ok:false and admin.py
 *      crashing non-JSON — end at 200 {degraded:true, reason containing the underlying error
 *      text}, never 502); the epic field shows through on existing ticket list/detail
 *      responses (with epic -> carries the code, without epic -> ''); POST -> 405.
 */

import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { EPIC_CODE_RE, listEpics, parseEpicMeta, readEpicMarkdown, resolveEpicsDir } from '../src/host/epics.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const EPIC_MD = `# 立项单：demo-epic

| 字段 | 值 |
| --- | --- |
| 代号 | \`demo-epic\` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-08-25 |

## 目标

做个示范。
`

const tmp = await mkdtemp(join(tmpdir(), 'wb-epics-'))
const savedEnv = process.env.SANDBAR_EPICS_DIR
try {
  /* ------------------------------------------------------------ A. Pure functions: parsing and listing */
  section('A parseEpicMeta / listEpics')
  {
    const meta = parseEpicMeta(EPIC_MD)
    ok(meta.title === 'demo-epic' && meta.status === '已立项（执行中）' && meta.created === '2026-08-25',
      '标题=首个 # 行（剥「立项单：」前缀）、状态/立项日期=表格行')
    const bare = parseEpicMeta('# 随便一个标题\n\n没有表格。\n')
    ok(bare.title === '随便一个标题' && bare.status === '' && bare.created === '', '缺表格 → 状态/日期容错为空串')
    const odd = parseEpicMeta('没有标题行\n| 状态 | 已归档 |\n')
    ok(odd.title === '' && odd.status === '已归档', '缺 # 行 → 标题空串不拒收')

    const dir = join(tmp, 'epics-a')
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, 'demo-epic.md'), EPIC_MD, 'utf8')
    await writeFile(join(dir, 'aaa.md'), '# 立项单：aaa\n\n| 状态 | 已归档 |\n| 立项日期 | 2026-08-01 |\n', 'utf8')
    await writeFile(join(dir, 'README.md'), '# 说明\n', 'utf8')       // wrong shape (uppercase) → not listed
    await writeFile(join(dir, 'notes.txt'), '不是立项单\n', 'utf8')   // not a .md → not listed
    const list = await listEpics(dir)
    ok(list.length === 2 && list[0].code === 'aaa' && list[1].code === 'demo-epic',
      '只收形状合法的 *.md，按代号排序')
    ok(list[1].status === '已立项（执行中）' && list[1].created === '2026-08-25', '列表带状态/立项日期')
    ok((await listEpics(join(tmp, 'no-such-dir'))).length === 0, '目录不存在 → 空数组不报错')
    const emptyDir = join(tmp, 'epics-empty')
    await mkdir(emptyDir, { recursive: true })
    ok((await listEpics(emptyDir)).length === 0, '空目录 → 空数组不报错')
  }

  /* ------------------------------------------------------------ B. readEpicMarkdown */
  section('B readEpicMarkdown 单份读取 + 防穿')
  {
    const dir = join(tmp, 'epics-a')
    const r = await readEpicMarkdown(dir, 'demo-epic')
    ok(r.ok === true && r.markdown.includes('## 目标') && r.title === 'demo-epic', '合法代号 → 全文+元信息')
    for (const bad of ['Demo-epic', '..', 'a b', 'a/b', 'x'.repeat(42), '']) {
      const rb = await readEpicMarkdown(dir, bad)
      ok(rb.ok === false && rb.status === 400, `形状非法 '${bad.slice(0, 12)}…' → 400`)
    }
    ok(EPIC_CODE_RE.test('demo-epic') && !EPIC_CODE_RE.test('..%2f..%2fetc'), 'EPIC_CODE_RE 与 shared.py 同款')
    const r404 = await readEpicMarkdown(dir, 'no-such-epic')
    ok(r404.ok === false && r404.status === 404 && r404.error.includes('demo-epic'),
      '不存在 → 404 人话附现有代号清单')
  }

  /* ------------------------------------------------------------ C. Routes */
  section('C /sandbar-workbench/api/epics* 路由')
  {
    // Shared mock pieces (same pattern as agent-logs.mjs)
    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })
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
        exactEpics: routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/epics'),
        prefixEpics: routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/epics'),
        exactTickets: routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/wf/tickets'),
        prefixTickets: routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets'),
      }
    }
    const call = async (handler, url, method = 'GET') => {
      const res = mockRes()
      await handler.handler(mockReq(url, method), res)
      return res
    }
    // stub admin.py: answers ticket list (filtered by epic) / workflow list / ticket show
    const LIST_OK = 'print(json.dumps({"ok": True, "result": {"count": 2, "tickets": [\n' +
      '        {"id": "t260825-01", "title": "ticket-list --epic 过滤", "status": "closed",\n' +
      '         "stage": "settled", "stage_state": "done", "epic": "epic-linkage"},\n' +
      '        {"id": "t260825-04", "title": "workbench 立项单 API 路由", "status": "dispatched",\n' +
      '         "stage": "implement", "stage_state": "running", "epic": "epic-linkage"}\n' +
      '    ]}}))'
    const LIST_CRASH = "sys.stderr.write('temporal unreachable: connection refused'); sys.exit(2)"
    const writeStub = async (repo, { listPayload, listFails }) => {
      const listBranch = listFails ? LIST_CRASH : LIST_OK
      await mkdir(join(repo, 'server'), { recursive: true })
      await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'list':
    ${listBranch}
    sys.exit(0)
if tool == 'workflow' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"workflows": []}}))
    sys.exit(0)
if tool == 'ticket' and args.get('op') == 'show':
    print(json.dumps({"ok": True, "result": ${JSON.stringify(listPayload)}}))
    sys.exit(0)
print(json.dumps({"ok": False, "error": "temporal unreachable: connection refused"}))
sys.exit(1)
`, 'utf8')
    }

    /* --- C1 list route: env override / empty dir / default <repo>/notes/epics --- */
    const repoC = join(tmp, 'repo-c')
    await writeStub(repoC, { listPayload: {} })
    process.env.SANDBAR_EPICS_DIR = join(tmp, 'epics-a')
    const r1 = setup(repoC)
    ok(r1.exactEpics !== undefined && r1.prefixEpics !== undefined, 'epics exact+prefix 路由已挂')
    let r = await call(r1.exactEpics, '/sandbar-workbench/api/epics')
    ok(r.status === 200 && r.body.ok === true && r.body.result.count === 2
      && r.body.result.epics[0].code === 'aaa', 'GET /epics → 2 条（env 指向临时目录）')
    process.env.SANDBAR_EPICS_DIR = join(tmp, 'epics-empty')
    const r1b = setup(repoC)
    r = await call(r1b.exactEpics, '/sandbar-workbench/api/epics')
    ok(r.status === 200 && r.body.result.count === 0 && Array.isArray(r.body.result.epics),
      'GET /epics 空目录（env 指向）→ 200 空数组不报错')
    delete process.env.SANDBAR_EPICS_DIR
    const repoD = join(tmp, 'repo-d')
    await mkdir(join(repoD, 'notes', 'epics'), { recursive: true })
    await writeFile(join(repoD, 'notes', 'epics', 'demo-epic.md'), EPIC_MD, 'utf8')
    await writeStub(repoD, { listPayload: {} })
    const r1c = setup(repoD)
    r = await call(r1c.exactEpics, '/sandbar-workbench/api/epics')
    ok(r.status === 200 && r.body.result.count === 1 && r.body.result.epics[0].code === 'demo-epic',
      '缺省 <repo>/notes/epics 目录解析正确')

    /* --- C2 detail route: 200 / 400 / escape-guard 4xx / 404 / 405 --- */
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/demo-epic')
    ok(r.status === 200 && r.body.result.markdown.includes('## 目标')
      && r.body.result.path === 'notes/epics/demo-epic.md', 'GET /epics/<code> → 全文+path')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/Demo-Epic')
    ok(r.status === 400, '大写代号 → 400')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/..%2f..%2fetc')
    ok(r.status >= 400 && r.status < 500, '..%2f..%2fetc 穿路径 → 4xx')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/%2e%2e%2f%2e%2e%2fpasswd')
    ok(r.status >= 400 && r.status < 500, '%2e%2e 编码穿路径 → 4xx')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic')
    ok(r.status === 404 && r.body.error.includes('不存在'), '不存在代号 → 404 人话')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/demo-epic', 'POST')
    ok(r.status === 405, 'POST 详情 → 405（只读）')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/bogus-op')
    ok(r.status === 404, '未知子路径 → 404 人话')

    /* --- C3 /tickets aggregation: buckets + row fields --- */
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
    ok(r.status === 200 && r.body.ok === true && r.body.result.count === 2, 'GET /tickets → 2 张工单')
    ok(r.body.result.buckets.closed === 1 && r.body.result.buckets.dispatched === 1,
      '按 status 分桶计数（closed=1, dispatched=1）')
    const row = r.body.result.tickets.find(t => t.id === 't260825-04')
    ok(row !== undefined && row.title === 'workbench 立项单 API 路由' && row.status === 'dispatched'
      && row.stage === 'implement' && row.stage_state === 'running',
      '工单行字段齐（id/title/status/stage/stage_state）')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic/tickets')
    ok(r.status === 404, '/tickets 不存在代号 → 404（前置拦，不到引擎）')
    r = await call(r1c.prefixEpics, '/sandbar-workbench/api/epics/BAD/tickets')
    ok(r.status === 400, '/tickets 形状非法 → 400')

    /* --- C4 /tickets degradation: both paths — ok:false and spawn crash — end at 200 degraded, never 502 --- */
    const repoE = join(tmp, 'repo-e')
    await mkdir(join(repoE, 'notes', 'epics'), { recursive: true })
    await writeFile(join(repoE, 'notes', 'epics', 'demo-epic.md'), EPIC_MD, 'utf8')
    await writeStub(repoE, { listPayload: {}, listFails: true })   // the ticket-list branch fails outright (stderr + exit 2, non-JSON)
    const r1d = setup(repoE)
    r = await call(r1d.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
    ok(r.status === 200 && r.body.ok === true && r.body.result.degraded === true
      && String(r.body.result.reason).includes('connection refused'),
      'admin.py 崩（非 JSON）→ 200 degraded，reason 含底层 error 原文')
    // ok:false path: ticket list recognized but explicitly returns failure
    await writeFile(join(repoE, 'server', 'admin.py'), `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
if sys.argv[2] == 'ticket' and args.get('op') == 'list':
    print(json.dumps({"ok": False, "error": "ticket-list 失败: temporal unreachable: connection refused"}))
    sys.exit(1)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')
    r = await call(r1d.prefixEpics, '/sandbar-workbench/api/epics/demo-epic/tickets')
    ok(r.status === 200 && r.body.result.degraded === true
      && String(r.body.result.reason).includes('connection refused'),
      'admin.py 回 ok:false → 200 degraded，reason 透传底层 error 原文')

    /* --- C5 epic field shows through on existing ticket list/detail --- */
    const repoF = join(tmp, 'repo-f')
    await writeStub(repoF, {
      listPayload: { id: 't260825-04', title: '本工单', epic: 'epic-linkage', stage_state: 'running' },
    })
    const r1e = setup(repoF)
    r = await call(r1e.exactTickets, '/sandbar-workbench/api/wf/tickets?project=suyou')
    ok(r.status === 200 && r.body.result.tickets[0].epic === 'epic-linkage',
      '工单列表行带 epic 字段（有 epic 显示代号）')
    r = await call(r1e.prefixTickets, '/sandbar-workbench/api/wf/tickets/t260825-04')
    ok(r.status === 200 && r.body.result.epic === 'epic-linkage', '工单详情带 epic 字段')
  }
} finally {
  if (savedEnv === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
