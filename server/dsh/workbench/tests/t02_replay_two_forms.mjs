#!/usr/bin/env node
/**
 * t02_replay_two_forms.mjs —— KI-006 工单台两形态回放冒烟（t260901-26）。
 *
 * 在临时真 git 仓库里同时造两种收口痕迹：
 *   - 存量形态：merge commit（Merge branch 'lane/t-old'，真合并）；
 *   - 新形态（KI-006）：squash 单提交（message 含 lane/t-new，单父）。
 * 泳道 worktree 均已拆除（ticket.worktree 指向仓库内不存在的路径 →
 * mergedTicketDiff 回放道）。直接 import 真源 changes.ts（node 原生
 * type-strip，node ≥ 23），跑 computeTicketDiff，断言两种形态都给出
 * source='merged' 的变更集、diff 内容正确。
 *
 * 直跑：node integration/t260901-26/t02_replay_two_forms.mjs
 * 末行 SUMMARY pass=<n> fail=<k>；fail>0 exit 1。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..')
const CHANGES_TS = join(REPO_ROOT, 'server/dsh/workbench/src/host/changes.ts')

let PASS = 0
let FAIL = 0
function ok(cond, label) {
  if (cond) { PASS++; console.log(`  ok  ${label}`) }
  else { FAIL++; console.log(`  FAIL ${label}`) }
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' })
}

function makeRepo() {
  const root = mkdtempSync(join(tmpdir(), 'replay-t02-'))
  const repo = join(root, 'repo')
  execFileSync('git', ['init', '-q', '-b', 'main', repo])
  git(repo, 'config', 'user.email', 't@example')
  git(repo, 'config', 'user.name', 't02')
  return { root, repo }
}

// ---- fixture：一仓两形态 ----
console.log('fixture：临时真仓库造 merge commit + squash 提交两种收口痕迹')
const { root, repo } = makeRepo()
try {
  // base 内容
  execFileSync('bash', ['-c', `echo base > ${repo}/base.txt`])
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'base')

  // 存量形态：lane/t-old 真合并（merge commit）。先开 lane 提交，main 再分叉——
  // 顺序必须如此，否则 lane 含 main 全部历史、合并是快进、不留 merge commit。
  git(repo, 'checkout', '-qb', 'lane/t-old')
  execFileSync('bash', ['-c', `echo old lane > ${repo}/old.txt`])
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'old lane change')
  git(repo, 'checkout', '-q', 'main')
  execFileSync('bash', ['-c', `echo main diverge > ${repo}/diverge.txt`])
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'main diverge')
  git(repo, 'merge', '--no-edit', 'lane/t-old')
  git(repo, 'branch', '-q', '-d', 'lane/t-old')

  // 新形态：lane/t-new squash 单提交（message 含 lane/<id>，模拟 _squash_merge 产物）
  git(repo, 'checkout', '-qb', 'lane/t-new')
  execFileSync('bash', ['-c', `echo new lane > ${repo}/new.txt`])
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'new lane step')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'merge', '--squash', 'lane/t-new')
  git(repo, 'commit', '-qm',
    't260901-99 squash 收口（一单一提交，KI-006）\n\n来源 lane/t-new；审计真源在 Temporal')
  git(repo, 'branch', '-q', '-D', 'lane/t-new')

  // 校验 fixture 形态：一个 merge commit + 一个单父 squash 提交
  const merges = git(repo, 'log', '--first-parent', '--merges', '--format=%s', 'main').trim()
  ok(merges.includes("Merge branch 'lane/t-old'"), 'fixture 含存量 merge commit')
  const squashParents = git(repo, 'rev-list', '--parents', '-1', 'HEAD').trim().split(/\s+/).length - 1
  ok(squashParents === 1, 'fixture 尾部为单父 squash 提交')

  // ---- 被测真源 ----
  const { computeTicketDiff } = await import(CHANGES_TS)

  console.log('case A 存量 merge commit 回放')
  const rOld = await computeTicketDiff(repo, {
    id: 't-old',
    worktree: '.worktrees/gone-t-old',
    base_ref: '',
    write_set: ['old.txt'],
  })
  ok(rOld.source === 'merged', `source=merged（实际 ${rOld.source}）`)
  ok(rOld.changed && rOld.files.length === 1, `恰 1 个文件（实际 ${rOld.files.length}）`)
  const fOld = rOld.files[0]
  ok(fOld && fOld.path === 'old.txt' && fOld.status === 'added', `old.txt added（实际 ${fOld?.path}/${fOld?.status}）`)
  ok(fOld && fOld.unified && fOld.unified.includes('+old lane'), 'unified 含 +old lane')

  console.log('case B 新 squash 单提交回放')
  const rNew = await computeTicketDiff(repo, {
    id: 't-new',
    worktree: '.worktrees/gone-t-new',
    base_ref: '',
    write_set: ['new.txt'],
  })
  ok(rNew.source === 'merged', `source=merged（实际 ${rNew.source}）`)
  ok(rNew.changed && rNew.files.length === 1, `恰 1 个文件（实际 ${rNew.files.length}）`)
  const fNew = rNew.files[0]
  ok(fNew && fNew.path === 'new.txt' && fNew.status === 'added', `new.txt added（实际 ${fNew?.path}/${fNew?.status}）`)
  ok(fNew && fNew.unified && fNew.unified.includes('+new lane'), 'unified 含 +new lane')

  console.log('case C 回放不受后续 main 演进污染（blob 读当时版本）')
  // main 再演进：改掉 old.txt，回放 t-old 仍应给出「当时合入的」内容
  execFileSync('bash', ['-c', `echo later edit > ${repo}/old.txt`])
  git(repo, 'commit', '-qam', 'later main edit')
  const rOld2 = await computeTicketDiff(repo, {
    id: 't-old',
    worktree: '.worktrees/gone-t-old',
    base_ref: '',
    write_set: ['old.txt'],
  })
  const fOld2 = rOld2.files[0]
  ok(rOld2.source === 'merged' && fOld2 && fOld2.unified.includes('+old lane'),
    '演进后回放仍读 merge commit blob 的 +old lane')

  console.log('case D 找不到收口痕迹 → source=none + 人话原因')
  const rNone = await computeTicketDiff(repo, {
    id: 't-never-merged',
    worktree: '.worktrees/gone-x',
    base_ref: '',
    write_set: ['x.txt'],
  })
  ok(rNone.source === 'none', `source=none（实际 ${rNone.source}）`)
  ok(rNone.emptyReason !== undefined && rNone.emptyReason.includes('t-never-merged'),
    'emptyReason 点明定位失败')
} finally {
  rmSync(root, { recursive: true, force: true })
}

console.log(`SUMMARY pass=${PASS} fail=${FAIL}`)
process.exit(FAIL ? 1 : 0)
