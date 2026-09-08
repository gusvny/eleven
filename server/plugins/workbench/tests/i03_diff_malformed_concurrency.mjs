#!/usr/bin/env node
/**
 * i03_diff_malformed_concurrency.mjs —— diff 回放异常输入与并发面（t260902-04 集成验收）。
 *
 * 用户场景：diff 面板面对「票没合并 / base 填错 / write_set 乱填」时应给出人话原因
 * （端点 200 + emptyReason 渲染），而不是 500；多个面板/轮询同时打同一端点时不互相
 * 干扰、不泄漏资源。
 *
 * 覆盖：
 *   - 找不到收口痕迹（未合并的票）→ source=none + emptyReason 点明定位失败
 *   - 坏 base ref（不存在的分支）→ hasBase=false + 人话原因，不抛错
 *   - 非 commit 的 ref（HEAD^{tree}）→ BASE_RE 拒收（{} 不在白名单），不抛错
 *   - 注入形态 ref（-evil 开头）→ BASE_RE 拒收（防 option 注入），不抛错
 *   - 主树道 write_set 全无效（人话/空串/../）→ source=none + emptyReason，不抛错
 *   - 并发：8 路 Promise.all 同时打同一 squash 大体量回放 → 全部成功且结果一致
 *     （execFile 子进程/缓冲无共享态串扰；fixture 用后清理 = 资源回收自查）
 *
 * 直跑：node integration/t260902-04/i03_diff_malformed_concurrency.mjs
 * 末行 SUMMARY pass=<n> skip=<m> fail=<k>；fail>0 exit 1；缺 git/node<22 干净 SKIP。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..')
const CHANGES_TS = join(REPO_ROOT, 'server/plugins/workbench/src/host/changes.ts')

let PASS = 0
let FAIL = 0
function ok(cond, label) {
  if (cond) { PASS++; console.log(`  ok  ${label}`) }
  else { FAIL++; console.log(`  FAIL ${label}`) }
}

try {
  execFileSync('git', ['--version'], { stdio: 'ignore' })
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('node < 22')
} catch {
  console.log('SKIP：需要 git 与 node >= 22（type-stripping 直跑 changes.ts）')
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

const { computeTicketDiff } = await import(CHANGES_TS)

const root = mkdtempSync(join(tmpdir(), 'integ-t260902-04-i03-'))
const repo = join(root, 'repo')
try {
  execFileSync('git', ['init', '-q', '-b', 'main', repo])
  git(repo, 'config', 'user.email', 't@example')
  git(repo, 'config', 'user.name', 'i03')
  mkdirSync(join(repo, 'src'), { recursive: true })

  writeFileSync(join(repo, 'src/a.js'), 'const a = 1\n')
  git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'base')
  const baseSha = git(repo, 'rev-parse', 'HEAD').trim()

  git(repo, 'checkout', '-qb', 'lane/t-c')
  writeFileSync(join(repo, 'src/a.js'),
    Array.from({ length: 12000 }, (_, i) => `const c${i} = ${i};\n`).join('')) // ~450KB，并发的负载
  git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'lane change')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'merge', '--squash', 'lane/t-c')
  git(repo, 'commit', '-qm', 't-c squash 收口\n\n来源 lane/t-c')
  git(repo, 'branch', '-q', '-D', 'lane/t-c')

  const squashTicket = { id: 't-c', worktree: '.worktrees/gone-t-c', base_ref: '', write_set: ['src'] }

  console.log('case A：找不到收口痕迹（未合并的票）')
  {
    const r = await computeTicketDiff(repo, {
      id: 't-never-merged', worktree: '.worktrees/gone-x', base_ref: '', write_set: ['src'],
    })
    ok(r.source === 'none', `source=none（实际 ${r.source}）`)
    ok(typeof r.emptyReason === 'string' && r.emptyReason.includes('t-never-merged'),
      'emptyReason 点明定位失败与票 id')
  }

  console.log('case B：坏 base ref / 非 commit ref / 注入形态 ref（worktree 道）')
  {
    const r1 = await computeTicketDiff(repo, { id: 't-b', worktree: '.', base_ref: 'no-such-ref' })
    ok(r1.hasBase === false && r1.source === 'worktree' && typeof r1.emptyReason === 'string',
      '不存在分支 → hasBase=false + 人话原因，不抛错')
    const r2 = await computeTicketDiff(repo, { id: 't-b', worktree: '.', base_ref: 'HEAD^{tree}' })
    ok(r2.hasBase === false && typeof r2.emptyReason === 'string',
      '非 commit ref（HEAD^{tree}）→ 拒收，不抛错')
    const r3 = await computeTicketDiff(repo, { id: 't-b', worktree: '.', base_ref: '-evil' })
    ok(r3.hasBase === false, '`-` 开头 ref → 拒收（option 注入防护），不抛错')
  }

  console.log('case C：主树道 write_set 全无效 → source=none + emptyReason')
  {
    const r = await computeTicketDiff(repo, {
      id: 't-d', worktree: '', base_ref: baseSha,
      write_set: ['（整段人话备注）', '', 'a/../b'],
    })
    ok(r.source === 'none' && typeof r.emptyReason === 'string' && r.emptyReason.includes('write_set'),
      'write_set 无有效 pathspec → none + 原因写明 write_set，不抛错')
  }

  console.log('case D：并发 8 路同打 squash 大体量回放')
  {
    const results = await Promise.all(
      Array.from({ length: 8 }, () => computeTicketDiff(repo, squashTicket)),
    )
    ok(results.every(r => r.source === 'merged' && r.changed), '8 路全部成功（不 500、不抛错）')
    const json = results.map(r => JSON.stringify(r))
    ok(json.every(j => j === json[0]), '8 路结果逐字节一致（无共享态串扰）')
    const entry = results[0].files.find(f => f.path === 'src/a.js')
    ok(entry && entry.unifiedTruncated === true, '并发下大文件条目仍带截断标记')
  }
} finally {
  rmSync(root, { recursive: true, force: true })
}
ok(!existsSync(root), 'fixture 临时目录已清理（execFile 子进程无残留占用）')

console.log(`SUMMARY pass=${PASS} skip=0 fail=${FAIL}`)
process.exit(FAIL === 0 ? 0 : 1)
