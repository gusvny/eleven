/**
 * smoke/changes.mjs —— sandbar-workbench M9 PR 式审批台的宿主半冒烟。
 *
 * 直跑：node smoke/changes.mjs（node ≥22.18 原生 type-stripping，直接 import .ts，
 * 无需编译）。覆盖：
 *   A. computeTicketDiff（src/host/changes.ts，临时 git 仓库 + 真实 worktree）：
 *      泳道道：doc=block diff / code=unified / data=前后值对账 / 新增 untracked /
 *      删除文件 / 无变更→emptyReason / 坏 base→空且说明；
 *      主树道：write_set+base..HEAD 给变更集；无 base/write_set→「无变更记录」。
 *   B. review 端点（node.ts apply + mock webServer/req/res，临时目录）：
 *      GET 空→POST 存→GET 读回；坏 id 400（防穿）；坏 conclude 400；
 *      admin.log 审计留痕（actor=sandbar-workbench + run-id）。
 */

import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { computeTicketDiff, classifyPath } from '../src/host/changes.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const DOC_BASE = '# 测试文档\n\n第一段正文，讲一件事。\n\n第二段正文，讲另一件事。\n'
const CODE_BASE = 'export const a = 1\nexport const b = 2\n'
const DATA_BASE = JSON.stringify({ 名: '旧名', 章: [{ id: 'c1', v: 1 }, { id: 'c2', v: 2 }], 开关: true }, null, 2) + '\n'

/* ---------------------------------------------------------------- A. computeTicketDiff */

section('A0 classifyPath 归类')
{
  ok(classifyPath('docs/design/x.md') === 'doc', 'docs/*.md → doc')
  ok(classifyPath('app/public/data/params.json') === 'data', 'app/public/data/*.json → data')
  ok(classifyPath('server/dsh/workbench/node.ts') === 'code', '其余 → code')
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-changes-'))
try {
  const repo = await realpath(tmp)
  const git = (args, cwd = repo) => execFileSync('git', ['-C', cwd, ...args], { stdio: ['ignore', 'pipe', 'pipe'] }).toString()
  await mkdir(join(repo, 'docs/design'), { recursive: true })
  await mkdir(join(repo, 'src'), { recursive: true })
  await mkdir(join(repo, 'app/public/data'), { recursive: true })
  await mkdir(join(repo, 'server'), { recursive: true })
  await writeFile(join(repo, 'docs/design/x.md'), DOC_BASE, 'utf8')
  await writeFile(join(repo, 'src/code.ts'), CODE_BASE, 'utf8')
  await writeFile(join(repo, 'app/public/data/params.json'), DATA_BASE, 'utf8')
  await writeFile(join(repo, 'src/gone.ts'), 'export const dead = true\n', 'utf8')
  git(['init', '-q', '-b', 'main'])
  git(['add', '.'])
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'base'])
  const base = git(['rev-parse', 'HEAD']).trim()

  // 泳道 worktree：改 doc/code/data + 删 gone.ts + 新增 untracked
  git(['worktree', 'add', '.worktrees/wt', '-b', 'lane/smoke'])
  const wt = join(repo, '.worktrees/wt')
  await writeFile(join(wt, 'docs/design/x.md'), DOC_BASE.replace('讲一件事', '讲一件更大的事') + '\n## 新增小节\n\n全新段落。\n', 'utf8')
  await writeFile(join(wt, 'src/code.ts'), CODE_BASE.replace('b = 2', 'b = 3'), 'utf8')
  await writeFile(join(wt, 'app/public/data/params.json'),
    JSON.stringify({ 名: '新名', 章: [{ id: 'c1', v: 9 }, { id: 'c2', v: 2 }], 新键: 'x' }, null, 2) + '\n', 'utf8')
  await rm(join(wt, 'src/gone.ts'))
  await writeFile(join(wt, 'src/fresh.ts'), 'export const fresh = 1\n', 'utf8')

  section('A1 泳道道：worktree vs base_ref')
  {
    const r = await computeTicketDiff(repo, { id: 't-smoke-1', worktree: '.worktrees/wt', base_ref: base })
    ok(r.source === 'worktree' && r.hasBase === true, 'source=worktree 且 hasBase')
    ok(r.changed === true, 'changed=true')
    const byPath = new Map(r.files.map(f => [f.path, f]))
    const doc = byPath.get('docs/design/x.md')
    ok(doc?.kind === 'doc' && doc.status === 'modified', 'doc 文件 modified')
    ok((doc?.blocks ?? []).some(b => b.status === 'modified'), 'doc 有 modified 块')
    ok((doc?.blocks ?? []).some(b => b.status === 'added'), 'doc 有 added 块（新增小节）')
    ok((doc?.blocks ?? []).every(b => typeof b.key === 'string' && b.key !== ''), 'doc 块带稳定 key')
    const code = byPath.get('src/code.ts')
    ok(code?.kind === 'code' && typeof code.unified === 'string', 'code 带 unified diff')
    ok((code?.unified ?? '').includes('-export const b = 2') && (code?.unified ?? '').includes('+export const b = 3'), 'unified 含 -/+ 行')
    const data = byPath.get('app/public/data/params.json')
    ok(data?.kind === 'data' && Array.isArray(data.recon), 'data 带对账')
    const recon = data?.recon ?? []
    ok(recon.some(e => e.kind === 'changed' && e.path === '名' && (e.before ?? '').includes('旧名') && (e.after ?? '').includes('新名')), '对账：名 前→后')
    ok(recon.some(e => e.kind === 'added' && e.path === '新键'), '对账：新键 added')
    ok(recon.some(e => e.kind === 'removed' && e.path === '开关'), '对账：开关 removed')
    ok(recon.some(e => e.path === '章[c1].v' && e.kind === 'changed'), '对账：数组按 id 对齐到 章[c1].v')
    ok(!recon.some(e => e.path.startsWith('章[c2]')), '对账：未变元素不产条目')
    const gone = byPath.get('src/gone.ts')
    ok(gone?.status === 'removed', '删除文件 status=removed')
    const fresh = byPath.get('src/fresh.ts')
    ok(fresh?.status === 'added' && (fresh.unified ?? '').includes('+export const fresh = 1'), 'untracked 新文件合成 + 行')
    ok(r.files.every(f => /^[0-9a-f]{8}$/.test(f.newHash)), '每文件带内容哈希（意见 key 成分）')
  }

  section('A1b 泳道道：引擎运行时目录排除（.dsh/ .suyou/）')
  {
    // 在泳道里造 .dsh/ 和 .suyou/ 的 untracked 文件（模拟引擎运行时产物）
    await mkdir(join(wt, '.dsh'), { recursive: true })
    await mkdir(join(wt, '.suyou'), { recursive: true })
    await writeFile(join(wt, '.dsh/agent.log'), 'agent runtime log\n', 'utf8')
    await writeFile(join(wt, '.dsh/.credentials.yaml'), 'secret: xyz\n', 'utf8')
    await writeFile(join(wt, '.suyou/stage_implement_gen0.json'), '{"status":"ok"}\n', 'utf8')
    await writeFile(join(wt, '.suyou/cache.db'), 'binary', 'utf8')
    const rEx = await computeTicketDiff(repo, { id: 't-smoke-1', worktree: '.worktrees/wt', base_ref: base })
    const exPaths = rEx.files.map(f => f.path)
    ok(!exPaths.some(p => p.startsWith('.dsh/')), '未出现 .dsh/ 文件')
    ok(!exPaths.some(p => p.startsWith('.suyou/')), '未出现 .suyou/ 文件')
    ok(typeof rEx.excludedEngineFiles === 'number' && rEx.excludedEngineFiles === 4, 'excludedEngineFiles=4（2 .dsh/ + 2 .suyou/）')
    // 真变更不受影响：doc/code/data/fresh/gone 仍在
    ok(exPaths.includes('docs/design/x.md'), 'doc 仍在变更集')
    ok(exPaths.includes('src/code.ts'), 'code 仍在变更集')
    ok(exPaths.includes('src/fresh.ts'), 'untracked 新文件仍在变更集')
    ok(exPaths.includes('src/gone.ts'), '删除文件仍在变更集')
    // committed diff 侧也排除：如果 .dsh/ 下有已跟踪文件，git pathspec 会排除
    const committedNames = exPaths.filter(p => !['src/fresh.ts'].includes(p)) // fresh 是 untracked
    ok(committedNames.every(p => !p.startsWith('.dsh/') && !p.startsWith('.suyou/')), 'committed 侧也无引擎文件')
  }

  section('A2 泳道道：无变更 / 坏 base')
  {
    git(['worktree', 'add', '.worktrees/wt2', '-b', 'lane/smoke2'])
    const r0 = await computeTicketDiff(repo, { id: 't-smoke-2', worktree: '.worktrees/wt2', base_ref: base })
    ok(r0.changed === false && typeof r0.emptyReason === 'string', '无变更 → changed=false + emptyReason')
    const rBad = await computeTicketDiff(repo, { id: 't-smoke-3', worktree: '.worktrees/wt2', base_ref: 'deadbeef' })
    ok(rBad.changed === false && (rBad.emptyReason ?? '').includes('base'), '坏 base → 空 + 说明')
    const rNoBase = await computeTicketDiff(repo, { id: 't-smoke-3b', worktree: '.worktrees/wt2', base_ref: '' })
    ok(rNoBase.base === base, '缺 base_ref 回退 merge-base(HEAD, main)')
    const rGone = await computeTicketDiff(repo, { id: 't-smoke-3c', worktree: '.worktrees/not-exist', base_ref: base })
    ok(rGone.source === 'none' && (rGone.emptyReason ?? '').includes('merge commit'), 'worktree 已拆且无 merge commit → none + 明说')
  }

  section('A2b 收口工单：merge commit 回放（泳道已拆，260824 详情页「看不见 diff」修复）')
  {
    // 模拟 merge 收口：泳道提交 → main 上 merge commit → 拆 worktree + 删分支
    git(['worktree', 'add', '.worktrees/wt9', '-b', 'lane/t-smoke-9'])
    const wt9 = join(repo, '.worktrees/wt9')
    await writeFile(join(wt9, 'src/merged.ts'), 'export const merged = 1\n', 'utf8')
    git(['-C', wt9, 'add', 'src/merged.ts'])
    git(['-C', wt9, 'commit', '-m', 'smoke lane commit'])
    git(['merge', '--no-edit', '--no-ff', 'lane/t-smoke-9'])
    git(['worktree', 'remove', '.worktrees/wt9'])
    git(['branch', '-d', 'lane/t-smoke-9'])
    const rM = await computeTicketDiff(repo, { id: 't-smoke-9', worktree: '.worktrees/wt9', base_ref: base, write_set: ['src/merged.ts'] })
    ok(rM.source === 'merged' && rM.hasBase === true, 'source=merged 且 hasBase')
    const mf = rM.files.find(f => f.path === 'src/merged.ts')
    ok(mf?.status === 'added' && (mf.unified ?? '').includes('+export const merged = 1'), '回放含当时合入的新文件')
    // 新内容从 merge commit 的 blob 读：merge 后再改同文件，回放的仍是「当时合入的」
    await writeFile(join(repo, 'src/merged.ts'), 'export const merged = 2\n', 'utf8')
    git(['add', 'src/merged.ts'])
    git(['commit', '-m', 'later main change'])
    const rM2 = await computeTicketDiff(repo, { id: 't-smoke-9', worktree: '.worktrees/wt9', base_ref: base, write_set: ['src/merged.ts'] })
    const mf2 = rM2.files.find(f => f.path === 'src/merged.ts')
    ok((mf2?.unified ?? '').includes('+export const merged = 1') && !(mf2?.unified ?? '').includes('merged = 2'), '后续改动不污染回放（读 blob 不读工作树）')
    // write_set 之外的文件不进回放
    const rM3 = await computeTicketDiff(repo, { id: 't-smoke-9', worktree: '.worktrees/wt9', base_ref: base, write_set: ['src/other.ts'] })
    ok(rM3.files.length === 0 && typeof rM3.emptyReason === 'string', 'write_set 不符 → 空 + 明说')
  }

  section('A3 主树道：write_set + git log')
  {
    // 主树上再进一笔（相对 base 有变更）
    await writeFile(join(repo, 'docs/design/x.md'), DOC_BASE + '\n## 主树小节\n\n主树新增。\n', 'utf8')
    await writeFile(join(repo, 'src/outside.ts'), 'export const o = 1\n', 'utf8')
    git(['add', '.'])
    git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'main change'])
    const r = await computeTicketDiff(repo, { id: 't-smoke-4', base_ref: base, write_set: ['docs/'] })
    ok(r.source === 'main' && r.changed === true, '主树道 source=main 有变更')
    ok(r.files.length === 1 && r.files[0].path === 'docs/design/x.md', 'write_set pathspec 只圈 docs/（src/outside.ts 不进）')
    ok((r.files[0].blocks ?? []).some(b => b.status === 'added'), '主树 doc 变更加 added 块')
    const rAll = await computeTicketDiff(repo, { id: 't-smoke-4b', base_ref: base, write_set: ['docs/', 'src/'] })
    ok(rAll.files.some(f => f.path === 'src/outside.ts'), 'write_set 扩到 src/ 后新文件进变更集')
  }

  section('A4 给不出 → 无变更记录')
  {
    const r = await computeTicketDiff(repo, { id: 't-smoke-5' })
    ok(r.source === 'none' && r.changed === false, '无 worktree/base/write_set → none')
    ok((r.emptyReason ?? '').includes('无变更记录'), 'emptyReason 显「无变更记录」')
  }

  /* ------------------------------------------------------------ B. review 端点 */

  section('B review 端点（mock webServer）')
  {
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
    const mockReq = (url, method = 'GET', json) => ({
      url, method,
      async *[Symbol.asyncIterator]() { if (json !== undefined) yield Buffer.from(JSON.stringify(json)) },
    })
    const call = async (url, method, json) => {
      const res = mockRes()
      await prefix.handler(mockReq(url, method, json), res)
      return res
    }

    const pre = '/sandbar-workbench/api/wf/tickets'
    // GET review 空
    let r = await call(`${pre}/t-smoke-1/review`)
    ok(r.status === 200 && r.body.ok === true && r.body.result.rounds.length === 0, 'GET review 空 rounds（非错误）')
    // POST 存一轮
    r = await call(`${pre}/t-smoke-1/review`, 'POST', {
      base, conclude: 'changes-requested', reviewer: 'op-test',
      blocks: [
        { block_key: 'docs/design/x.md#paragraph:abc123', summary: '第一段', type: 'paragraph', status: 'modified', decision: 'reject', comment: '这里要改' },
        { block_key: `code:src/code.ts:${'0'.repeat(8)}`, summary: 'src/code.ts', type: 'code', status: 'modified', decision: 'approve' },
      ],
    })
    ok(r.status === 200 && r.body.ok === true && typeof r.body.run_id === 'string' && r.body.run_id !== '', 'POST review 200 + run-id')
    const saved = JSON.parse(await readFile(join(repo, 'server/dsh/reviews/t-smoke-1.json'), 'utf8'))
    ok(saved.rounds.length === 1 && saved.rounds[0].conclude === 'changes-requested', '落盘 server/dsh/reviews/<工单id>.json')
    ok(saved.rounds[0].blocks.length === 2 && saved.rounds[0].blocks[0].comment === '这里要改', '块意见逐字段落盘')
    ok(saved.rounds[0].reviewer === 'op-test', 'reviewer 落盘')
    // GET 读回
    r = await call(`${pre}/t-smoke-1/review`)
    ok(r.body.result.rounds.length === 1, 'GET review 读回一轮')
    // 第二轮（多轮迭代）
    r = await call(`${pre}/t-smoke-1/review`, 'POST', { base, conclude: 'approved', blocks: [] })
    ok(r.body.ok === true && r.body.result.rounds === 2, '第二轮追加 rounds=2')
    // 防穿：坏 id
    r = await call(`${pre}/${encodeURIComponent('..%2F..%2Fetc')}/review`, 'POST', { base: '', conclude: 'approved', blocks: [] })
    ok(r.status === 400, 'review POST 坏 id → 400（防穿）')
    r = await call(`${pre}/${encodeURIComponent('a/b')}/review`)
    ok(r.status === 400 || r.status === 404, 'review GET 坏 id → 拒绝（400/404，不到文件层）')
    // 坏 conclude
    r = await call(`${pre}/t-smoke-1/review`, 'POST', { base: '', conclude: 'lgtm', blocks: [] })
    ok(r.status === 400, '坏 conclude → 400')
    // 缺 block_key
    r = await call(`${pre}/t-smoke-1/review`, 'POST', { base: '', conclude: 'approved', blocks: [{ summary: 'x' }] })
    ok(r.status === 400, 'block 缺 block_key → 400')
    // diff 路由坏 id（在 spawn admin.py 之前就拒）
    r = await call(`${pre}/${encodeURIComponent('a/b')}/diff`)
    ok(r.status === 400 || r.status === 404, 'diff 坏 id → 拒绝（400/404，不到 spawn）')
    // review 不支持的方法
    r = await call(`${pre}/t-smoke-1/review`, 'PUT')
    ok(r.status === 405, 'review PUT → 405')
    // 审计留痕
    const log = await readFile(join(repo, 'server/admin.log'), 'utf8')
    const recs = log.trim().split('\n').map(l => JSON.parse(l))
    ok(recs.some(x => x.actor === 'sandbar-workbench' && x.name === 'review.save' && x.ok === true), 'admin.log 有 review.save 成功审计')
    ok(recs.some(x => x.ok === false), 'admin.log 有失败审计（坏输入也留痕）')
    ok(recs.every(x => typeof x.run_id === 'string' && x.run_id !== ''), '审计全带 run-id')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
