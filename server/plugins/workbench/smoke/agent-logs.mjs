/**
 * smoke/agent-logs.mjs —— sandbar-workbench M12「Agent 日志」的宿主半冒烟。
 *
 * 直跑：node smoke/agent-logs.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. resolveAgentBaseDir（src/host/agent-logs.ts）：泳道工单 → <repo>/<worktree>/.suyou
 *      （防穿：越界 worktree → reason 拒绝）；workspace.dir 的 /tmp/sandbar-ws/ 隔离目录；
 *      无泳道 → /tmp/sandbar-ws/<id>/.suyou 兜底 + reason。
 *   B. listAgentLogs（临时目录）：不存在/空目录 → exists=false + reason；agent_*.log 与
 *      stage_*.json 按 (stage, gen) 排序；log 取尾部内容、result 解析 JSON；坏 JSON →
 *      parseError；junk 文件不入；超大文件截断标记。
 *   C. /sandbar-workbench/api/wf/tickets/<id>/agent-logs 路由（node.ts apply + mock
 *      webServer/req/res + stub admin.py）：坏 id → 400（不到文件层）；真工单 →
 *      200 + 泳道 .suyou 文件列表与内容；无 .suyou 目录 → 200 + reason 降级（不抛错）。
 */

import { mkdir, mkdtemp, rm, symlink, utimes, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { listAgentLogs, resolveAgentBaseDir, _sessionKbFast } from '../src/host/agent-logs.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = await mkdtemp(join(tmpdir(), 'wb-al-'))
try {
  /* ------------------------------------------------------------ A. resolveAgentBaseDir */
  section('A resolveAgentBaseDir 定目录')
  {
    const repo = join(tmp, 'repo')
    const r1 = resolveAgentBaseDir(repo, 't-x', { worktree: '.worktrees/wt' })
    ok(r1.base === join(repo, '.worktrees/wt', '.suyou') && r1.reason === undefined, '泳道 worktree → <repo>/<worktree>/.suyou')
    const r2 = resolveAgentBaseDir(repo, 't-x', { worktree: '..' })
    ok(r2.base === '' && (r2.reason ?? '').includes('越界'), 'worktree 越界 → 拒绝（防穿）')
    const r3 = resolveAgentBaseDir(repo, 't-x', { worktree: '', workspace: { type: 'dir', path: '/tmp/sandbar-ws/t-x' } })
    ok(r3.base === '/tmp/sandbar-ws/t-x/.suyou', 'workspace.dir /tmp/sandbar-ws/ 隔离目录')
    const r4 = resolveAgentBaseDir(repo, 't-x', { workspace: { type: 'dir', path: '/etc/passwd' } })
    ok(r4.base === join('/tmp/sandbar-ws', 't-x', '.suyou') && r4.reason !== undefined,
      '非 /tmp/sandbar-ws 的 dir → 兜底隔离目录 + reason')
    const r5 = resolveAgentBaseDir(repo, 't-x', null)
    ok(r5.base === join('/tmp/sandbar-ws', 't-x', '.suyou') && (r5.reason ?? '').includes('主树道'),
      '无泳道/无 workspace → 主树道兜底 /tmp/sandbar-ws/<id>/.suyou')
  }

  /* ------------------------------------------------------------ B. listAgentLogs */
  section('B listAgentLogs 列目录')
  {
    const suyou = join(tmp, 'ws', 't-b', '.suyou')
    const missing = await listAgentLogs(join(tmp, 'ws', 't-missing', '.suyou'))
    ok(missing.exists === false && (missing.reason ?? '').includes('不存在'), '目录不存在 → exists=false + reason')

    await mkdir(suyou, { recursive: true })
    const empty = await listAgentLogs(suyou)
    ok(empty.exists === true && empty.files.length === 0 && empty.reason !== undefined, '空目录 → 无文件 + reason')

    await writeFile(join(suyou, 'agent_develop_gen1.log'), 'dsh: EPERM bootstrap 失败\nline2\n', 'utf8')
    await writeFile(join(suyou, 'agent_develop_gen2.log'), '第二遍重跑\n', 'utf8')
    await writeFile(join(suyou, 'agent_verify_gen1.log'), 'verify 段日志\n', 'utf8')
    await writeFile(join(suyou, 'stage_develop_gen1.json'), JSON.stringify({
      status: 'ok', summary: '开发完成', deliverables: ['server/plugins/ui/node.ts'], files_changed: ['a.ts'], evidence: 'smoke 全绿',
    }), 'utf8')
    await writeFile(join(suyou, 'stage_develop_gen2.json'), '{bad json', 'utf8')
    await writeFile(join(suyou, 'notes.txt'), '不是日志', 'utf8')

    const r = await listAgentLogs(suyou)
    ok(r.files.length === 5, '只收 agent_*.log + stage_*.json（notes.txt 不入）')
    const names = r.files.map(f => f.name)
    ok(names.join(',') === 'agent_develop_gen1.log,stage_develop_gen1.json,agent_develop_gen2.log,stage_develop_gen2.json,agent_verify_gen1.log',
      '按 (stage, gen, kind) 排序——同代 gen 内 log 流在前 result 结算在后')
    ok(names[4] === 'agent_verify_gen1.log', 'verify 段排在 develop 段后')
    const log1 = r.files[0]
    ok(log1.kind === 'log' && (log1.content ?? '').includes('EPERM'), 'log 带尾部内容')
    const res1 = r.files[1]
    ok(res1.kind === 'result' && res1.result?.summary === '开发完成' && res1.result?.deliverables?.[0] === 'server/plugins/ui/node.ts',
      'result 解析 JSON（summary/deliverables）')
    const res2 = r.files[3]
    ok(res2.parseError !== undefined && res2.result === undefined, '坏 JSON → parseError 不解析')
    ok(r.files.every(f => f.size > 0 && f.mtime > 0), '每文件带尺寸/时间')

    // 超大 log：截断标记 + 尾部保留
    const big = join(tmp, 'ws', 't-c', '.suyou')
    await mkdir(big, { recursive: true })
    await writeFile(join(big, 'agent_develop_gen1.log'), 'x'.repeat(70_000) + 'TAIL-MARK', 'utf8')
    const rb = await listAgentLogs(big)
    ok(rb.files[0].contentTruncated === true && (rb.files[0].content ?? '').endsWith('TAIL-MARK'),
      '超大 log 截断（取尾部）')
  }

  /* ------------------------------------------------------------ C. 路由 */
  section('C /sandbar-workbench/api/wf/tickets/<id>/agent-logs 路由')
  {
    const repo = join(tmp, 'repo-route')
    await mkdir(join(repo, 'server'), { recursive: true })
    await mkdir(join(repo, '.worktrees', 'wt'), { recursive: true })
    await mkdir(join(repo, '.worktrees', 'wt', '.suyou'), { recursive: true })
    await writeFile(join(repo, '.worktrees', 'wt', '.suyou', 'agent_develop_gen1.log'), 'stub agent 日志行\n', 'utf8')
    await writeFile(join(repo, '.worktrees', 'wt', '.suyou', 'stage_develop_gen1.json'),
      JSON.stringify({ status: 'ok', summary: 'stub 完成' }), 'utf8')
    // stub admin.py：只应答 call ticket show（返回带 worktree 的工单详情）
    await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
if len(sys.argv) >= 4 and sys.argv[1] == 'call' and sys.argv[2] == 'ticket':
    args = json.loads(sys.argv[3])
    if args.get('op') == 'show':
        print(json.dumps({"ok": True, "result": {"id": "t-smoke-1", "worktree": ".worktrees/wt",
            "stage": "develop", "status": "dispatched", "stage_state": "running"}}))
        sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`, 'utf8')

    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const prefix = routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets')
    ok(prefix !== undefined, 'tickets prefix 路由已挂')

    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })
    const call = async (url) => {
      const res = mockRes()
      await prefix.handler(mockReq(url), res)
      return res
    }

    const pre = '/sandbar-workbench/api/wf/tickets'
    // 坏 id → 400（在 spawn admin.py 之前就拒，防穿）
    let r = await call(`${pre}/${encodeURIComponent('..%2F..%2Fetc')}/agent-logs`)
    ok(r.status === 400, '坏 id → 400（防穿，不到文件层）')
    r = await call(`${pre}/t-smoke-1/agent-logs`)
    ok(r.status === 200 && r.body.ok === true, 'GET 200')
    ok(r.body.result.base.endsWith('.worktrees/wt/.suyou'), 'base 定到泳道 .suyou')
    ok(r.body.result.files.length === 2, '列出 2 个文件')
    ok(r.body.result.files[0].name === 'agent_develop_gen1.log'
      && (r.body.result.files[0].content ?? '').includes('stub agent 日志行'), 'log 内容透传')
    ok(r.body.result.files[1].result?.summary === 'stub 完成', 'result 解析透传')

    // 泳道 .suyou 不存在 → 200 + reason 降级（不抛错）
    const routes2 = []
    const ws2 = { register: (r) => { routes2.push(r); return () => {} } }
    const ctx2 = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws2 : undefined),
      on: () => () => {},
    }
    apply(ctx2, { repo: join(tmp, 'repo-route2') })
    const prefix2 = routes2.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets')
    const stub2 = `import json, sys
if len(sys.argv) >= 4 and sys.argv[1] == 'call' and sys.argv[2] == 'ticket':
    args = json.loads(sys.argv[3])
    if args.get('op') == 'show':
        print(json.dumps({"ok": True, "result": {"id": "t-smoke-2", "worktree": ".worktrees/wt"}}))
        sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`
    await mkdir(join(tmp, 'repo-route2', 'server'), { recursive: true })
    await writeFile(join(tmp, 'repo-route2', 'server', 'admin.py'), stub2, 'utf8')
    const res2 = mockRes()
    await prefix2.handler(mockReq(`${pre}/t-smoke-2/agent-logs`), res2)
    ok(res2.status === 200 && res2.body.ok === true && res2.body.result.exists === false
      && res2.body.result.reason !== undefined, '无 .suyou → 200 + reason 降级')
  }

  /* ------------------------------------- D. _sessionKbFast 选中语义（t260825-03 返工） */
  section('D _sessionKbFast 按 mtime 最新选中活跃会话')
  {
    // 多角色接力泳道：旧角色会话 size 大但已死，新角色会话 size 小但在涨——
    // 必须选中 mtime 最新者（按 size 选会显示死会话 KB 并误报停涨）。
    const sessRoot = join(tmp, 'ws', 't-d', '.dsh', 'sessions')
    const slug = '--tmp-x--'
    await mkdir(join(sessRoot, slug, 't-d-developer'), { recursive: true })
    await mkdir(join(sessRoot, slug, 't-d-integration'), { recursive: true })
    const oldFile = join(sessRoot, slug, 't-d-developer', 'session.jsonl.zstd')
    const newFile = join(sessRoot, slug, 't-d-integration', 'session.jsonl.zstd')
    await writeFile(oldFile, 'x'.repeat(4096), 'utf8')   // 4KB 死会话
    await writeFile(newFile, 'y'.repeat(1536), 'utf8')   // 1.5KB 活会话
    const old = new Date(Date.now() - 3600_000)
    await utimes(oldFile, old, old)
    const r = await _sessionKbFast(sessRoot)
    ok(r.path === newFile && r.kb === 1 && r.alive === true,
      '两会话不同 size/mtime → 选中 mtime 最新者（1KB 活会话，非 4KB 死会话）')

    // 旧扁平布局兜底仍可用
    const flatRoot = join(tmp, 'ws', 't-flat', '.dsh', 'sessions')
    await mkdir(join(flatRoot, slug), { recursive: true })
    await writeFile(join(flatRoot, slug, 'session-abc123.zstd'), 'z'.repeat(2048), 'utf8')
    const rf = await _sessionKbFast(flatRoot)
    ok(rf.kb === 2 && rf.path.endsWith('session-abc123.zstd'), '旧扁平布局 session-*.zstd 兜底')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)

// t260903-11 跨项目守卫放宽：extraRoots=票项目注册目录，命中放行、双失守拒
{
  const rOk = resolveAgentBaseDir(repo, 't-x11', { worktree: '/otherproj/.lane/t-x11' }, ['/otherproj'])
  ok(rOk.base === '/otherproj/.lane/t-x11/.suyou' && rOk.reason === undefined, 'extraRoots 命中 → 放行（跨项目票）')
  const rNo = resolveAgentBaseDir(repo, 't-x11', { worktree: '/otherproj/.lane/t-x11' })
  ok(rNo.base === '' && (rNo.reason ?? '').includes('越界'), 'extraRoots 缺省 → 仍拒（旧行为）')
  const rEvil = resolveAgentBaseDir(repo, 't-x11', { worktree: '/etc' }, ['/otherproj'])
  ok(rEvil.base === '' && (rEvil.reason ?? '').includes('越界'), 'extraRoots 外路径 → 仍拒（防穿越硬项）')
}
