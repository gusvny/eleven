/**
 * i02_replay_two_forms.mjs —— KI-006 工单台变更回放两形态黑盒（t260901-26，integration 侧）。
 *
 * 用户故事：泳道收口后 worktree 与分支都被清理，管理员在工单台回看某张已收口
 * 工单的变更集。存量工单是 merge commit 形态、本拍板后的新工单是 squash 单提交
 * 形态，两种都必须能回放，且回放的是「当时合入的内容」而不是「现在工作树的内容」
 * （后续别的单可能改过同一文件）。
 *
 * 黑盒手法：node 直 import 真源 server/dsh/workbench/src/host/changes.ts
 * （宿主半只跑在 node 上，type-stripping 直跑），喂临时真 git 仓库 fixture：
 *   - tA：存量形态（真 merge commit，2 个泳道小步提交），收口后 main 又改过同文件；
 *   - tB：新形态（squash 单提交，message 含 lane/tB），收口前后 main 都前进过；
 *   - tC：真 merge，只动 docs/ 与 code/（write_set pathspec 限定用）；
 *   - live：还活着的泳道（回放触发条件：worktree 没了才回放 main）。
 *
 * 直跑：node integration/t260901-26/i02_replay_two_forms.mjs
 * 末行 SUMMARY pass=<n> skip=<m> fail=<k>；fail>0 exit 1。
 */
import { execFile } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'

const execFileP = promisify(execFile)
const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')

let PASS = 0, SKIP = 0, FAIL = 0
const ok = (cond, label) => {
  if (cond) { PASS++; console.log('  ok  %s', label) }
  else { FAIL++; console.log('  FAIL %s', label) }
}

let computeTicketDiff
try {
  ;({ computeTicketDiff } = await import(join(REPO, 'server/dsh/workbench/src/host/changes.ts')))
} catch (e) {
  console.log('SKIP 真源 changes.ts 无法直跑（node type-stripping 不可用）：%s', (e && e.message) || e)
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

const root = mkdtempSync(join(tmpdir(), 't26-i02-'))
const repo = join(root, 'repo')

async function git(cwd, ...args) {
  const { stdout } = await execFileP('git', ['-C', cwd, ...args], { encoding: 'utf8' })
  return stdout
}

function write(base, rel, text) {
  const p = join(base, rel)
  mkdirSync(dirname(p), { recursive: true })
  writeFileSync(p, text, 'utf8')
}

async function laneWorktree(name) {
  const wt = join(repo, '.worktrees', name)
  await git(repo, 'worktree', 'add', '-q', wt, '-b', `lane/${name}`)
  await git(wt, 'config', 'user.email', 'i02@example')
  await git(wt, 'config', 'user.name', 'i02')
  return wt
}

async function dropLane(wt, name, force = false) {
  await git(repo, 'worktree', 'remove', '--force', wt)
  await git(repo, 'branch', force ? '-D' : '-d', `lane/${name}`)
}

async function buildFixture() {
  await execFileP('git', ['init', '-q', '-b', 'main', repo])
  await git(repo, 'config', 'user.email', 'i02@example')
  await git(repo, 'config', 'user.name', 'i02')
  write(repo, 'a.py', '# base\n')
  write(repo, 'docs/d.md', '# doc\n')
  write(repo, 'z.txt', 'z0\n')
  await git(repo, 'add', '.')
  await git(repo, 'commit', '-qm', 'base')

  // tA：存量形态——2 个泳道小步提交 + 真 merge commit。
  // 注意先让 main 前进一步再合：泳道没分叉时 git merge 会快进、不留 merge commit，
  // 「存量形态」就造不出来了。
  {
    const wt = await laneWorktree('tA')
    write(wt, 'a.py', '# base\n# laneA\n')
    await git(wt, 'commit', '-qam', 'step a1')
    write(wt, 'b.py', '# b\n')
    await git(wt, 'add', '.')
    await git(wt, 'commit', '-qm', 'step a2')
    write(repo, 'z.txt', 'z0\nmain z\n')
    await git(repo, 'commit', '-qam', 'main z advance')
    await git(repo, 'merge', '-q', '--no-edit', 'lane/tA')
    await dropLane(wt, 'tA')
  }
  // tA 收口后 main 又改过同一文件（回放必须读当时 blob，不是现在工作树）
  write(repo, 'a.py', '# base\n# laneA\n# later-main\n')
  await git(repo, 'commit', '-qam', 'later main work')

  // tB：新形态——squash 单提交；收口前 main 有 later-main、收口后又前进（base=C~1 判别用）
  {
    const wt = await laneWorktree('tB')
    write(wt, 'a.py', '# base\n# laneA\n# later-main\n# laneB\n')
    write(wt, 'code/c.py', '# c\n')
    await git(wt, 'add', '.')
    await git(wt, 'commit', '-qm', 'step b1')
    await git(repo, 'merge', '-q', '--squash', 'lane/tB')
    await git(repo, 'commit', '-qm',
      't260901-26 squash 收口（一单一提交，KI-006）\n\n来源 lane/tB；审计真源在 Temporal；泳道内小步历史不进 main')
    await dropLane(wt, 'tB', true)
  }
  write(repo, 'a.py', '# base\n# laneA\n# later-main\n# laneB\n# post-squash\n')
  await git(repo, 'commit', '-qam', 'post squash main')

  // tC：真 merge（同样先让 main 前进防快进），只动 docs/ 与 code/（write_set 用）
  {
    const wt = await laneWorktree('tC')
    write(wt, 'docs/d.md', '# doc\nmore doc\n')
    write(wt, 'code/c2.py', '# c2\n')
    await git(wt, 'add', '.')
    await git(wt, 'commit', '-qm', 'step c1')
    write(repo, 'z.txt', 'z0\nmain z\nmain z2\n')
    await git(repo, 'commit', '-qam', 'main z advance 2')
    await git(repo, 'merge', '-q', '--no-edit', 'lane/tC')
    await dropLane(wt, 'tC')
  }

  // 活着的泳道（回放触发条件：worktree 没了才回放 main）
  const liveWt = await laneWorktree('live')
  write(liveWt, 'z.txt', 'z0\nlive\n')
  await git(liveWt, 'commit', '-qam', 'live step')
}

const fileOf = (r, p) => r.files.find(f => f.path === p)

/** unified diff 里的增行（+ 前缀、排除 +++ 文件头）——上下文行不算数。 */
const addedLines = (uni) =>
  uni.split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++'))

async function main() {
  await buildFixture()

  console.log('case A 存量 merge commit 形态回放（含 blob 读）')
  {
    const r = await computeTicketDiff(repo, { id: 'tA', worktree: '.worktrees/gone-tA' })
    ok(r.source === 'merged', `source='merged'（实际 ${r.source}）`)
    ok(r.hasBase && r.changed, 'hasBase 且 changed')
    ok(fileOf(r, 'a.py')?.status === 'modified', 'a.py modified')
    ok(fileOf(r, 'b.py')?.status === 'added', 'b.py added')
    const uni = fileOf(r, 'a.py')?.unified || ''
    ok(addedLines(uni).some(l => l.includes('# laneA')), 'a.py diff 增行含泳道改动')
    ok(!addedLines(uni).some(l => l.includes('# later-main')), 'a.py diff 增行不含收口后的 later-main（blob 读）')
  }

  console.log('case B squash 单提交形态回放（base=C~1 判别）')
  {
    const r = await computeTicketDiff(repo, { id: 'tB', worktree: '.worktrees/gone-tB' })
    ok(r.source === 'merged', `source='merged'（实际 ${r.source}）`)
    ok(fileOf(r, 'a.py')?.status === 'modified', 'a.py modified')
    ok(fileOf(r, 'code/c.py')?.status === 'added', 'code/c.py added')
    const uni = fileOf(r, 'a.py')?.unified || ''
    ok(addedLines(uni).some(l => l.includes('# laneB')), 'a.py diff 增行含本单改动')
    ok(!addedLines(uni).some(l => l.includes('# later-main')), '增行不含 C~1 之前的 main 改动（base 判别正确）')
    ok(!addedLines(uni).some(l => l.includes('# post-squash')), '增行不含收口后的 post-squash（blob 读）')
    const located = (await git(repo, 'log', '--first-parent', '--no-merges', '--grep', 'lane/tB', '--format=%H', 'main')).split('\n')[0].trim()
    ok(located !== '', 'fixture 里能 grep 到 lane/tB')
    ok(r.base === located, `result.base 定位到 squash 提交本身（${String(r.base).slice(0, 8)}…）`)
  }

  console.log('case C write_set pathspec 限定')
  {
    const r = await computeTicketDiff(repo, { id: 'tC', worktree: '.worktrees/gone-tC', write_set: ['docs/'] })
    ok(r.source === 'merged' && r.files.length > 0, '回放成功且有文件')
    ok(r.files.every(f => f.path.startsWith('docs/')), 'write_set=docs/ 时全部文件在 docs/ 内')
    const r2 = await computeTicketDiff(repo, { id: 'tC', worktree: '.worktrees/gone-tC2' })
    ok(fileOf(r2, 'code/c2.py')?.status === 'added', '无 write_set 时 code/c2.py 也回放出来')
  }

  console.log('case D 未收口工单：老实说没有')
  {
    const r = await computeTicketDiff(repo, { id: 'tZZ', worktree: '.worktrees/gone-tZZ' })
    ok(r.source === 'none', `未知工单 source='none'（实际 ${r.source}）`)
    ok((r.emptyReason || '') !== '', 'emptyReason 给原因')
  }

  console.log('case E 畸形工单 id（正则元字符）：不崩、落 none')
  {
    let threw = null
    let r = null
    try { r = await computeTicketDiff(repo, { id: 'x[', worktree: '.worktrees/gone-x' }) } catch (e) { threw = e }
    ok(threw === null, `不抛异常${threw ? `（${threw.message}）` : ''}`)
    ok(r !== null && r.source === 'none', `落 source='none'（实际 ${r && r.source}）`)
  }

  console.log('case F 泳道还活着时不走 main 回放')
  {
    const r = await computeTicketDiff(repo, { id: 'live', worktree: '.worktrees/live' })
    ok(r.source === 'worktree', `活泳道 source='worktree'（实际 ${r.source}）`)
  }
}

try {
  await main()
} catch (e) {
  FAIL++
  console.log('  FAIL 夹具/执行异常: %s', (e && e.stack) || e)
} finally {
  rmSync(root, { recursive: true, force: true })
}
console.log('SUMMARY pass=%d skip=%d fail=%d', PASS, SKIP, FAIL)
process.exit(FAIL > 0 ? 1 : 0)
