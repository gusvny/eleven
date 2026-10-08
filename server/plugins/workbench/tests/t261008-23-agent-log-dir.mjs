/**
 * tests/t261008-23-agent-log-dir.mjs —— agent 日志目录解析 UT（t261008-23 缺陷 4）。
 *
 * 直跑：node server/plugins/workbench/tests/t261008-23-agent-log-dir.mjs
 * 根因：读面旧名 '.suyou'，引擎写名已切 '.sandbar'（shared.py DOT_DIR_NEW），
 * DOT_DIR 常量不动——本测试锁读面候选序行为：
 *   A. resolveAgentBaseDirs：三道（worktree / workspace.worktree / workspace.dir /
 *      主树道兜底）各出候选序 [.sandbar, .suyou]；越界仍拒绝。
 *   B. listAgentLogs 候选探测：日志只在 .sandbar → 列出，base=实际探测的
 *      .sandbar 路径（票面要求「报实际探测目录」）；只在 .suyou → 兜底可读
 *      （compat read 不拆）；两边都无 → exists=false + reason 点名全部候选。
 *   C. 负向断言（merged 票 worktree 已拆）：worktree 字段仍在但目录不存在时，
 *      经 /tmp/sandbar-ws/<id>/ 幸存路径不可达——如实降级（exists=false + 全候选
 *      点名），不捏造日志（ticket「or states precisely why it cannot」）。
 * 全程临时目录，跑完回收，不碰 3099。
 */
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { resolveAgentBaseDirs, resolveAgentBaseDir, listAgentLogs } from '../src/host/agent-logs.ts'

let passed = 0, failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}
const tmp = await mkdtemp(join(tmpdir(), 'wb-al23-'))
try {
  const repo = join(tmp, 'repo')
  await mkdir(join(repo, 'worktrees', 'wt-1'), { recursive: true })

  /* A 候选序 */
  const r1 = resolveAgentBaseDirs(repo, 't-1', { worktree: 'worktrees/wt-1' })
  ok(r1.dirs.length === 2 && r1.dirs[0] === join(repo, 'worktrees/wt-1', '.sandbar') && r1.dirs[1] === join(repo, 'worktrees/wt-1', '.suyou'), `worktree branch: [.sandbar, .suyou] (got ${r1.dirs})`)
  const r2 = resolveAgentBaseDirs(repo, 't-1', { workspace: { type: 'worktree', path: 'worktrees/wt-1' } })
  ok(r2.dirs[0].endsWith('.sandbar'), 'workspace.worktree branch: new name first')
  const r3 = resolveAgentBaseDirs(repo, 't-1', { workspace: { type: 'dir', path: join('/tmp/sandbar-ws', 't-1') } })
  ok(r3.dirs[0] === join('/tmp/sandbar-ws', 't-1', '.sandbar') && r3.dirs[1].endsWith('.suyou'), 'isolated-dir branch: [.sandbar, .suyou]')
  const r4 = resolveAgentBaseDirs(repo, 't-1', null)
  ok(r4.dirs[0] === join('/tmp/sandbar-ws', 't-1', '.sandbar'), 'main-tree fallback branch: new name first')
  const r5 = resolveAgentBaseDirs(repo, 't-1', { worktree: '../../escape' })
  ok(r5.dirs.length === 0 && typeof r5.reason === 'string', 'escape guard unchanged (refused)')
  const legacy = resolveAgentBaseDir(repo, 't-1', { worktree: 'worktrees/wt-1' })
  ok(legacy.base === join(repo, 'worktrees/wt-1', '.sandbar'), 'compat wrapper returns the primary (new-name) candidate')

  /* B1 日志只在 .sandbar（实报 t261008-12 形状） */
  const ws = join(repo, 'worktrees', 'wt-1')
  await mkdir(join(ws, '.sandbar'), { recursive: true })
  await writeFile(join(ws, '.sandbar', 'agent_create_plan_gen0.log'), 'hello from the agent\n')
  await writeFile(join(ws, '.sandbar', 'stage_create_plan_gen0.json'), JSON.stringify({ status: 'ok', summary: 's' }))
  const l1 = await listAgentLogs(r1.dirs)
  ok(l1.exists === true && l1.files.length === 2, `logs under .sandbar listed (${l1.files.length} files)`)
  ok(l1.base === join(ws, '.sandbar'), `probed directory reported in the response (${l1.base})`)
  ok(l1.files.some(f => f.name === 'agent_create_plan_gen0.log' && f.content?.includes('hello from the agent')), 'log content readable')

  /* B2 日志只在 .suyou（老票 compat read 不拆） */
  const ws2 = join(repo, 'worktrees', 'wt-legacy')
  await mkdir(join(ws2, '.suyou'), { recursive: true })
  await writeFile(join(ws2, '.suyou', 'agent_implement_gen0.log'), 'legacy log\n')
  const l2 = await listAgentLogs(resolveAgentBaseDirs(repo, 't-2', { worktree: 'worktrees/wt-legacy' }).dirs)
  ok(l2.exists === true && l2.files.length === 1 && l2.base === join(ws2, '.suyou'), `legacy-only logs still readable through the fallback (${l2.base})`)

  /* B3 两边都无 → exists=false + 全候选点名，不捏造 */
  const l3 = await listAgentLogs(resolveAgentBaseDirs(repo, 't-3', { worktree: 'worktrees/wt-none' }).dirs)
  ok(l3.exists === false && l3.files.length === 0, 'no log dir → honest empty face')
  ok((l3.reason ?? '').includes('.sandbar') && (l3.reason ?? '').includes('.suyou'), `reason names every candidate probed (${l3.reason})`)

  /* C 负向：merged 票 worktree 已拆、隔离区也无日志 */
  const gone = { worktree: 'worktrees/wt-gone', workspace: null }
  const l4 = await listAgentLogs(resolveAgentBaseDirs(repo, 't-4', gone).dirs)
  const isolated = await listAgentLogs(resolveAgentBaseDirs(repo, 't-4', { workspace: { type: 'dir', path: join('/tmp/sandbar-ws', 't-4') } }).dirs)
  ok(l4.exists === false && isolated.exists === false, 'merged ticket with worktree removed AND no surviving isolated logs → exists=false on both paths')
  ok((l4.reason ?? '').includes(join(repo, 'worktrees', 'wt-gone')), 'the refusal names the probed worktree path (precise why-it-cannot, no fabricated logs)')
  // 幸存路径成立时（隔离区有日志、worktree 已拆）：读面走 workspace.dir 道。
  await mkdir(join('/tmp/sandbar-ws', 't-5', '.sandbar'), { recursive: true })
  await writeFile(join('/tmp/sandbar-ws', 't-5', '.sandbar', 'agent_merge_gen0.log'), 'merged-ticket log\n')
  const l5 = await listAgentLogs(resolveAgentBaseDirs(repo, 't-5', { workspace: { type: 'dir', path: join('/tmp/sandbar-ws', 't-5') } }).dirs)
  ok(l5.exists === true && l5.base === join('/tmp/sandbar-ws', 't-5', '.sandbar') && l5.files.length === 1, 'surviving isolated workspace still resolves logs after the worktree is gone')
  await rm(join('/tmp/sandbar-ws', 't-5'), { recursive: true, force: true })
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\nAGENT_LOG_DIR ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
