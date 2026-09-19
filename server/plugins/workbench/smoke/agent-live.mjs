/**
 * smoke/agent-live.mjs — host half-smoke for the agent live panel (t260825-03).
 *
 * Run: node smoke/agent-live.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. projectDirKey (src/host/agent-live.ts): the cwd-slug rule must match the dsh side —
 *      separator collapse / strip leading '-' / escape odd chars as ~XXXX / truncate at 251 /
 *      wrap as `--...--`; checked against this lane's real cwd (the real directory name is known).
 *   B. resolveSessionFile: lane ticket -> <wsRoot>/.dsh/sessions/<slug>/<id>-<role>/
 *      session.jsonl.zstd hit; wrong role falls back to a prefix scan picking the newest mtime;
 *      worktree='..' escape -> refused (path guard); no sessions dir / no session for this
 *      ticket -> a human-readable reason.
 *   C. readAgentLiveTail + the /sandbar-workbench/api/wf/tickets/<id>/agent-live route
 *      (node.ts apply + mock webServer/req/res + stub admin.py): real zstd-compressed fixture
 *      (if zstd is not on PATH, section C is skipped with a note); bad id -> 400; escaped-
 *      worktree ticket -> 400; normal ticket -> 200 + last N event summaries (assistant
 *      truncated / tool call name + target path); missing session file -> 200 {exists:false,
 *      reason}; the n param is clamped.
 */

import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { projectDirKey, readAgentLiveTail, resolveSessionFile } from '../src/host/agent-live.ts'
import { apply } from '../node.ts'

const execFileP = promisify(execFile)

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const tmp = await mkdtemp(join(tmpdir(), 'wb-live-'))
try {
  /* ------------------------------------------------------------ A. projectDirKey */
  section('A projectDirKey（cwd-slug 规则与 dsh 侧一致）')
  {
    // Check against the real directory name (measured in this lane on 260907: .lane/<ticket> layout): /Users/user/Documents/sandbar/.lane/t260907-01
    const real = projectDirKey('/Users/user/Documents/sandbar/.lane/t260907-01')
    ok(real === '--Users-user-Documents-sandbar-.lane-t260907-01--', `真实泳道 cwd → ${real}`)
    ok(projectDirKey('/a//b\\\\c:d') === '--a-b-c-d--', '分隔符 / \\ : 连续串坍缩成一个 -')
    ok(projectDirKey('/tmp/a~b') === '--tmp-a~007Eb--', '~ → ~XXXX 转义')
    ok(projectDirKey('/') === '--root--', '全分隔符 → root')
    const long = projectDirKey('/' + 'x'.repeat(400))
    ok(long.length === 2 + 251 + 2, '可读串截断 251 字符')
    let threw = false
    try { projectDirKey('') } catch { threw = true }
    ok(threw, '空 cwd 抛错（与 dsh 侧一致）')
  }

  /* ------------------------------------------------------------ B. resolveSessionFile */
  section('B resolveSessionFile 定位会话文件')
  const repo = join(tmp, 'repo')
  {
    const wt = join(repo, '.worktrees', 'wt')
    const slug = projectDirKey(wt)
    const sessDir = join(wt, '.dsh', 'sessions', slug)
    await mkdir(join(sessDir, 't-b-developer'), { recursive: true })
    await writeFile(join(sessDir, 't-b-developer', 'session.jsonl.zstd'), 'fake', 'utf8')
    await mkdir(join(sessDir, 't-b-integration'), { recursive: true })
    await writeFile(join(sessDir, 't-b-integration', 'session.jsonl.zstd'), 'fake2', 'utf8')
    await mkdir(join(sessDir, 'other-ticket-developer'), { recursive: true })
    await writeFile(join(sessDir, 'other-ticket-developer', 'session.jsonl.zstd'), 'fake3', 'utf8')

    const r1 = await resolveSessionFile(repo, 't-b', { worktree: '.worktrees/wt', role: 'developer' })
    ok(r1.path !== undefined && r1.path.endsWith(join('t-b-developer', 'session.jsonl.zstd')),
      'role 精确匹配命中 <id>-developer')
    ok(r1.refused === undefined && r1.reason === undefined, '命中时无 reason/refused')

    const r2 = await resolveSessionFile(repo, 't-b', { worktree: '.worktrees/wt', role: 'integration' })
    ok(r2.path !== undefined && r2.path.includes('t-b-integration'), 'role=integration 命中对应会话')

    const r3 = await resolveSessionFile(repo, 't-b', { worktree: '.worktrees/wt' })
    ok(r3.path !== undefined && r3.path.includes('t-b-'), '无 role → 前缀扫描兜底（本工单会话）')
    ok(!r3.path.includes('other-ticket'), '别工单的会话不混入')

    const r4 = await resolveSessionFile(repo, 't-b', { worktree: '..' })
    ok(r4.refused === true && (r4.reason ?? '').includes('越界'), 'worktree=.. 越界 → refused（防穿）')

    const r5 = await resolveSessionFile(repo, 't-nope', { worktree: '.worktrees/wt' })
    ok(r5.path === undefined && r5.refused === undefined && (r5.reason ?? '').includes('无本工单会话'),
      '无本工单会话 → reason 人话降级')
    // t260917-05 S3：发现集空但目录有他票会话 → 按类点名 + suspectFiles（绝不静默）
    ok((r5.reason ?? '').includes('他票会话')
      && (r5.suspectFiles ?? []).some(f => f.endsWith('other-ticket-developer/session.jsonl.zstd')),
      '发现集空+他票会话在场 → reason 点名 + suspectFiles（验收①态B）')

    const r6 = await resolveSessionFile(repo, 't-x', { worktree: '.worktrees/wt-missing' })
    ok(r6.path === undefined && (r6.reason ?? '').includes('不存在'), 'sessions 目录不存在 → reason 降级')
  }

  /* ------------------------------------------------------------ C. readAgentLiveTail + route */
  section('C readAgentLiveTail + agent-live 路由')
  let hasZstd = true
  try { await execFileP('zstd', ['--version']) } catch { hasZstd = false }
  if (!hasZstd) {
    console.log('  （跳过 C 段：zstd 不在 PATH；路由降级路径已在 B 段覆盖）')
  } else {
    const wt = join(repo, '.worktrees', 'wt')
    const slug = projectDirKey(wt)
    const sessPath = join(wt, '.dsh', 'sessions', slug, 't-smoke-1-developer', 'session.jsonl.zstd')
    await mkdir(join(wt, '.dsh', 'sessions', slug, 't-smoke-1-developer'), { recursive: true })
    const events = [
      { type: 'session', version: 0, id: 't-smoke-1-developer', createdAt: 1000 },
      { type: 'user/message', seq: 1, time: 61000, data: { content: [{ type: 'text', text: '请实现运行脉搏行' }] } },
      { type: 'assistant/chunk', seq: 2, time: 62000, data: { chunk: { type: 'block-start' } } },
      { type: 'assistant/message', seq: 3, time: 63000, data: { message: { content: [{ type: 'text', text: '好的，我先读一下现有代码' }] } } },
      { type: 'tool/call', seq: 4, time: 64000, data: { name: 'read', arguments: '{"file_path":"/x/y/server/plugins/workbench/node.ts"}' } },
      { type: 'tool/result', seq: 5, time: 65000, data: { message: { content: [{ type: 'tool-result', content: [{ type: 'text', text: '文件内容……' }] }] } } },
      { type: 'step/end', seq: 6, time: 66000, data: { turn: 1, step: 1 } },
    ]
    const jsonl = events.map(e => JSON.stringify(e)).join('\n') + '\n'
    await writeFile(join(tmp, 'fixture.jsonl'), jsonl, 'utf8')
    await execFileP('zstd', ['-q', '-f', join(tmp, 'fixture.jsonl'), '-o', sessPath])

    const tail = await readAgentLiveTail(sessPath, 30)
    ok(tail.exists === true && tail.events.length === 4, '过滤后剩 4 条（chunk/step/session 头不上屏）')
    ok(tail.events[0].type === 'user' && tail.events[0].summary.includes('请实现运行脉搏行'), 'user/message → 用户摘要')
    ok(tail.events[1].type === 'assistant' && tail.events[1].summary.includes('先读一下'), 'assistant 文本摘要')
    ok(tail.events[2].type === 'tool' && tail.events[2].summary === '读取 plugins/workbench/node.ts',
      'tool/call → 工具名+目标路径（尾部三段，既有 _describeAction 口径）')
    ok(tail.events[3].type === 'result' && tail.events[3].summary.startsWith('结果：'), 'tool/result → 结果摘要')
    ok(tail.events[0].ts === 61, '时间戳 ms → epoch 秒')
    ok((tail.sizeKb ?? 0) >= 0 && (tail.mtime ?? 0) > 0, '带 sizeKb/mtime')
    ok(tail.truncated === false, '未超 n 不标 truncated')

    const tail2 = await readAgentLiveTail(sessPath, 2)
    ok(tail2.events.length === 2 && tail2.truncated === true
      && tail2.events[0].type === 'tool' && tail2.events[1].type === 'result',
      'n=2 → 只取尾部 2 条且 truncated=true')

    const miss = await readAgentLiveTail(join(tmp, 'nope.zstd'), 30)
    ok(miss.exists === false && (miss.reason ?? '').includes('不存在'), '文件缺失 → exists=false + reason')

    // Route (mock webServer + stub admin.py)
    await mkdir(join(repo, 'server'), { recursive: true })
    await writeFile(join(repo, 'server', 'admin.py'), `import json, sys
if len(sys.argv) >= 4 and sys.argv[1] == 'call' and sys.argv[2] == 'ticket':
    args = json.loads(sys.argv[3])
    if args.get('op') == 'show':
        tid = args.get('id')
        if tid == 't-escape':
            print(json.dumps({"ok": True, "result": {"id": tid, "worktree": ".."}}))
            sys.exit(0)
        print(json.dumps({"ok": True, "result": {"id": tid, "worktree": ".worktrees/wt",
            "role": "developer", "stage": "develop", "status": "dispatched", "stage_state": "running"}}))
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
    let r = await call(`${pre}/${encodeURIComponent('..%2F..%2Fetc')}/agent-live`)
    ok(r.status === 400, '坏 id（../ 逃逸）→ 400（防穿，不到文件层）')

    r = await call(`${pre}/t-escape/agent-live`)
    ok(r.status === 400, '工单 worktree=.. 逃逸 → 400（验收硬性要求）')

    r = await call(`${pre}/t-smoke-1/agent-live`)
    ok(r.status === 200 && r.body.ok === true, 'GET 200')
    ok(r.body.result.exists === true && r.body.result.events.length === 4, '返回尾部事件流')
    ok(r.body.result.events[2].summary === '读取 plugins/workbench/node.ts', '摘要形状透传')
    ok(typeof r.body.result.sizeKb === 'number' && typeof r.body.result.mtime === 'number', '带 sizeKb/mtime')

    r = await call(`${pre}/t-smoke-1/agent-live?n=1`)
    ok(r.body.result.events.length === 1 && r.body.result.events[0].type === 'result', 'n=1 只取尾 1 条')

    r = await call(`${pre}/t-smoke-1/agent-live?n=99999`)
    ok(r.body.result.events.length === 4, 'n 超上限钳制（不爆）')

    r = await call(`${pre}/t-no-session/agent-live`)
    ok(r.status === 200 && r.body.result.exists === false && r.body.result.reason !== undefined,
      '无会话文件 → 200 {exists:false,reason} 降级不抛错')
  }

  /* ------------------------------------------------------------ D. per-round freshness line (KI-024)
   * Same block as section C (reuses the ctx/routes/mock route fixture). */
  section('D 轮级新鲜度行（KI-024，t260903-04）：step/start / llm/retry 上屏')
  if (!hasZstd) {
    console.log('  （跳过 D 段：zstd 不在 PATH）')
  } else {
    const wt = join(repo, '.worktrees', 'wt')
    const slug = projectDirKey(wt)
    const sessPath = join(wt, '.dsh', 'sessions', slug, 't-smoke-2-developer', 'session.jsonl.zstd')
    await mkdir(join(wt, '.dsh', 'sessions', slug, 't-smoke-2-developer'), { recursive: true })
    // Stub fixture: mirrors the event shape of the t260903-01 silent window (line-by-line
    // checked against a real session via zstd -dc) — during agent spawn bootstrap only
    // session/request/step meta info and the chunk stream appear; llm/retry is the upstream
    // rate-limit/timeout auto-retry. Expect: one row each for step/start and llm/retry,
    // nothing else on screen.
    const events = [
      { type: 'session', version: 0, id: 't-smoke-2-developer', createdAt: 1000 },
      { type: 'request/context', seq: 1, time: 2000, data: {} },
      { type: 'step/start', seq: 2, time: 3000, data: { turn: 1, step: 1 } },
      { type: 'reasoning-chunks', seq: 3, time: 4000, data: {} },
      { type: 'assistant/chunk', seq: 4, time: 5000, data: {} },
      { type: 'step/end', seq: 5, time: 6000, data: { turn: 1, step: 1 } },
      { type: 'step/start', seq: 6, time: 7000, data: { turn: 1, step: 2 } },
      { type: 'llm/retry', seq: 7, time: 8000, data: { retryId: 'r1', turn: 1, step: 2, provider: 'zai', mode: 'normal' } },
      { type: 'llm/retry-started', seq: 8, time: 8500, data: { retryId: 'r1', turn: 1, step: 2, retry: 1 } },
      { type: 'step/start', seq: 9, time: 9000, data: {} },
    ]
    const jsonl = events.map(e => JSON.stringify(e)).join('\n')
      + '\n' + '{bad json line' + '\n'   // malformed line: bad JSON is skipped without crashing
    await writeFile(join(tmp, 'fixture-rounds.jsonl'), jsonl, 'utf8')
    await execFileP('zstd', ['-q', '-f', join(tmp, 'fixture-rounds.jsonl'), '-o', sessPath])

    const tail = await readAgentLiveTail(sessPath, 30)
    ok(tail.exists === true, '静默窗 fixture 可读')
    const rows = tail.events
    ok(rows.length === 4, `只上屏 3 条 step/start + 1 条 llm/retry（got ${rows.length}）`)
    ok(rows[0].type === 'step' && rows[0].summary === '第 1 轮 · 第 1 步开始',
      `step/start → 轮界行（got ${rows[0]?.type}: ${rows[0]?.summary}）`)
    ok(rows[1].type === 'step' && rows[1].summary === '第 1 轮 · 第 2 步开始', '第二个轮界行')
    ok(rows[2].type === 'retry' && rows[2].summary === 'LLM 重试中（zai），仍在干活',
      `llm/retry → 重试行带 provider（got ${rows[2]?.summary}）`)
    ok(rows[3].type === 'step' && rows[3].summary === '新一轮开始',
      'step/start 缺 turn/step 字段 → 软降级通用文案（畸形输入不崩）')
    ok(!rows.some(e => e.type === 'result'), 'step/end / llm/retry-started / chunk 流不上屏')
    ok(rows.every(e => Number.isFinite(e.ts) && e.ts > 0), '每行带 epoch 秒时间戳')

    // End-to-end: the route passes new row types through (the frontend LIVE_TYPE_LABEL/CSS consume type=step/retry)
    const mockRes2 = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq2 = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })
    const pre2 = '/sandbar-workbench/api/wf/tickets'
    const routes2 = []
    const ws2 = { register: (r) => { routes2.push(r); return () => {} } }
    const ctx2 = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws2 : undefined),
      on: () => () => {},
    }
    apply(ctx2, { repo })
    const prefix2 = routes2.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/wf/tickets')
    const res2 = mockRes2()
    await prefix2.handler(mockReq2(`${pre2}/t-smoke-2/agent-live`), res2)
    ok(res2.status === 200 && res2.body.ok === true
      && res2.body.result.events.some(e => e.type === 'step')
      && res2.body.result.events.some(e => e.type === 'retry'),
      '路由透传 step/retry 行型（前端标签/配色按 type 消费）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
