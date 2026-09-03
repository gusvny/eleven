#!/usr/bin/env node
/**
 * i02_diff_forms_bounded.mjs —— 收口两形态 + 三渠道的大体量有界回归（t260902-04 集成验收）。
 *
 * 用户场景：diff 面板的有界性不能只保 squash 回放道——merge commit 旧票（存量形态）、
 * 泳道还在的进行中票（worktree 道，含未入库的大文件）、无泳道的主树对账票（main 道），
 * 任何一条渠道把无界内容塞进响应，用户看到的就是卡死/白屏。
 *
 * 三个独立 fixture 仓库：
 *   case A 存量 merge commit（2 父）夹带 >1MB modified → merged 道取 ^1，有界不抛错；
 *   case B 泳道还在（worktree='.'）→ worktree 道，untracked >256KB 代码/文档文件 → 有界；
 *   case C 主树道（无 worktree，base_ref+write_set）>1MB modified → base..HEAD 有界不抛错。
 *
 * 直跑：node integration/t260902-04/i02_diff_forms_bounded.mjs
 * 末行 SUMMARY pass=<n> skip=<m> fail=<k>；fail>0 exit 1；缺 git/node<22 干净 SKIP。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
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
const UNIFIED_CAP = 49 * 1024
const TEXT_CAP = 257 * 1024

const { computeTicketDiff } = await import(CHANGES_TS)
const roots = []
function makeRepo(tag) {
  const root = mkdtempSync(join(tmpdir(), `integ-t260902-04-i02-${tag}-`))
  roots.push(root)
  const repo = join(root, 'repo')
  execFileSync('git', ['init', '-q', '-b', 'main', repo])
  git(repo, 'config', 'user.email', 't@example')
  git(repo, 'config', 'user.name', 'i02')
  return { root, repo }
}

try {
  /* ---------- case A：merge commit（存量形态，2 父）+ 大体量 ---------- */
  console.log('case A：merge commit 旧票回放（取 ^1），>1MB modified 有界')
  {
    const { repo } = makeRepo('merge')
    mkdirSync(join(repo, 'src'), { recursive: true })
    writeFileSync(join(repo, 'src/app.js'), 'const base = 1\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'base')

    git(repo, 'checkout', '-qb', 'lane/t-old')
    writeFileSync(join(repo, 'src/app.js'),
      Array.from({ length: 70000 }, (_, i) => `const y${i} = ${i};\n`).join('')) // ~1.2MB，diff 超 1MB
    writeFileSync(join(repo, 'src/old-note.txt'), 'old lane\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'old lane change')
    git(repo, 'checkout', '-q', 'main')
    writeFileSync(join(repo, 'diverge.txt'), 'main diverge\n') // main 先分叉，防快进
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'main diverge')
    git(repo, 'merge', '--no-edit', '-q', 'lane/t-old')
    git(repo, 'branch', '-q', '-d', 'lane/t-old')

    const r = await computeTicketDiff(repo, {
      id: 't-old', worktree: '.worktrees/gone-t-old', base_ref: '', write_set: ['src'],
    })
    ok(r.source === 'merged', `merge 形态 source=merged（实际 ${r.source}）`)
    const app = (r.files ?? []).find(f => f.path === 'src/app.js')
    ok(app && app.status === 'modified', 'src/app.js = modified')
    ok(app && app.unifiedTruncated === true, '>1MB 条目带截断标记')
    ok(app && typeof app.unified === 'string' && app.unified.length <= UNIFIED_CAP,
      `unified ≤ ${UNIFIED_CAP}B（实际 ${app?.unified?.length ?? '无'}）`)
    const note = (r.files ?? []).find(f => f.path === 'src/old-note.txt')
    ok(note && note.unified && note.unified.includes('+old lane'), '同批小文件内容完整（不误伤）')
  }

  /* ---------- case B：worktree 道（泳道还在）+ untracked 大体量文件 ---------- */
  console.log('case B：worktree 道 untracked 大文件（readFile 无界入口）有界')
  {
    const { repo } = makeRepo('wt')
    mkdirSync(join(repo, 'docs'), { recursive: true })
    mkdirSync(join(repo, 'scratch'), { recursive: true })
    writeFileSync(join(repo, 'tracked.txt'), 'tracked\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'base')
    const baseSha = git(repo, 'rev-parse', 'HEAD').trim()

    // 未入库的大文件（模拟正在生成中的大体量产物）
    writeFileSync(join(repo, 'scratch/big.out.js'),
      Array.from({ length: 9000 }, (_, i) => `const z${i} = ${i};\n`).join('')) // ~350KB
    writeFileSync(join(repo, 'docs/draft.md'),
      Array.from({ length: 3000 }, (_, i) => `草稿 ${i} ${'字'.repeat(95)}\n`).join('')) // ~300KB

    const r = await computeTicketDiff(repo, {
      id: 't-wip', worktree: '.', base_ref: baseSha, // worktree='.' → 本仓库 worktree 道
    })
    ok(r.source === 'worktree', `worktree 道 source=worktree（实际 ${r.source}）`)
    const js = (r.files ?? []).find(f => f.path === 'scratch/big.out.js')
    ok(js && js.status === 'added', 'untracked 大 js = added')
    ok(js && js.unifiedTruncated === true && js.unified.length <= UNIFIED_CAP,
      `大 js unified 有界 ≤ ${UNIFIED_CAP}B 且带标记（实际 ${js?.unified?.length ?? '无'}）`)
    const md = (r.files ?? []).find(f => f.path === 'docs/draft.md')
    ok(md && md.kind === 'doc', 'untracked 大 md 走 doc 道')
    const mdTexts = (md?.blocks ?? []).flatMap(b => [b.oldText, b.newText]).filter(t => typeof t === 'string')
    ok(md && md.unifiedTruncated === true && mdTexts.every(t => t.length <= TEXT_CAP),
      `大 md 块文本 ≤ ${TEXT_CAP}B 且带标记`)
  }

  /* ---------- case C：主树道（base_ref + write_set，base..HEAD）---------- */
  console.log('case C：主树道 base..HEAD，>1MB modified 有界')
  {
    const { repo } = makeRepo('main')
    mkdirSync(join(repo, 'server'), { recursive: true })
    writeFileSync(join(repo, 'server/api.js'), 'const v0 = 0\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'base')
    const baseSha = git(repo, 'rev-parse', 'HEAD').trim()
    writeFileSync(join(repo, 'server/api.js'),
      Array.from({ length: 70000 }, (_, i) => `const v${i} = ${i};\n`).join('')) // ~1.2MB，diff 超 1MB
    writeFileSync(join(repo, 'server/small.js'), 'const s = 1\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'big change on main')

    const r = await computeTicketDiff(repo, {
      id: 't-main', worktree: '', base_ref: baseSha, write_set: ['server'],
    })
    ok(r.source === 'main', `主树道 source=main（实际 ${r.source}）`)
    const api = (r.files ?? []).find(f => f.path === 'server/api.js')
    ok(api && api.unifiedTruncated === true && api.unified.length <= UNIFIED_CAP,
      `主树道 >1MB 条目有界且带标记（实际 ${api?.unified?.length ?? '无'}）`)
    const small = (r.files ?? []).find(f => f.path === 'server/small.js')
    ok(small && small.unified && small.unified.length > 0 && small.unifiedTruncated !== true,
      '主树道小文件完整无标记')
  }
} finally {
  for (const r of roots) rmSync(r, { recursive: true, force: true })
}
ok(roots.every(r => !existsSync(r)), '全部 fixture 临时目录已清理')

console.log(`SUMMARY pass=${PASS} skip=0 fail=${FAIL}`)
process.exit(FAIL === 0 ? 0 : 1)
