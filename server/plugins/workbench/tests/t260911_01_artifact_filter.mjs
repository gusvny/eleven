#!/usr/bin/env node
/**
 * t260911_01_artifact_filter.mjs —— diff 面引擎过程物过滤（t260911-01 2b）自测。
 *
 * 直跑：node tests/t260911_01_artifact_filter.mjs
 * 覆盖：
 *   A. untracked 过程物全滤 + 点名（验收 c/d）：.sandbar/agent_*.log、.dsh/、嵌套
 *      a/b/__pycache__/x.pyc（M2）、out/x.pyc、node_modules/、.venv/；
 *   B. committed（已跟踪再改）过程物同样滤除（pathspec 预滤 + JS 真源双保险）；
 *   C. 合法文件不被误杀（.sandbar 目录名不波及 sandbox.txt 这类普通文件）；
 *   D. 契约真源：isProcessArtifact 纯函数边角（嵌套/顶层/相近名不误杀）；
 *   E. 反向护栏素材（R1）：过滤表 ⊇ 引擎表现有排除（.dsh/.sandbar/.suyou）。
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { computeTicketDiff, isProcessArtifact, PROCESS_ARTIFACT_TABLE } from './../src/host/changes.ts'

let passed = 0, failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

function git(args, cwd) {
  return execFileSync('git', ['-C', cwd, ...args], { stdio: ['ignore', 'pipe', 'pipe'] }).toString()
}

/** 写文件并自建父目录（过程物夹具常带多层目录）。 */
function put(file, content) {
  mkdirSync(join(file, '..'), { recursive: true })
  writeFileSync(file, content, 'utf8')
}

function initRepo(dir) {
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'README.md'), '# 夹具\n', 'utf8')
  git(['init', '-q', '-b', 'main'], dir)
  git(['add', '.'], dir)
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'base'], dir)
  return git(['rev-parse', 'HEAD'], dir).trim()
}

let seq = 0
function freshLane() {
  const rootDir = mkdtempSync(join(tmpdir(), `t26091101-af-${++seq}-`))
  const proj = join(rootDir, 'proj')
  initRepo(proj)
  const lane = join(proj, '.worktrees', `lane-${seq}`) // 仓根内（越根闸）
  git(['worktree', 'add', '-q', lane, '-b', `lane/af-${seq}`], proj)
  return { rootDir, proj, lane, base: git(['rev-parse', 'main'], proj).trim() }
}

section('A untracked 过程物全滤 + 点名（验收 c/d）')
{
  const fx = freshLane()
  try {
    put(join(fx.lane, 'real.py'), 'REAL = 1\n', 'utf8')
    put(join(fx.lane, '.sandbar', 'agent_dev.log'), 'log', 'utf8')
    put(join(fx.lane, '.sandbar', 'resume_patch_x.yml'), 'yml', 'utf8')
    put(join(fx.lane, '.dsh', 'sessions', 's.jsonl'), '{}', 'utf8')
    mkdirSync(join(fx.lane, 'pkg', '__pycache__'), { recursive: true })
    put(join(fx.lane, 'pkg', '__pycache__', 'sys.cpython-312.pyc'), 'pyc', 'utf8')
    mkdirSync(join(fx.lane, 'out', 'pycache'), { recursive: true })
    put(join(fx.lane, 'out', 'pycache', 'stdlib.pyc'), 'pyc', 'utf8')
    put(join(fx.lane, 'node_modules', 'leftpad', 'index.js'), 'js', 'utf8')
    put(join(fx.lane, '.venv', 'bin', 'python'), 'elf', 'utf8')
    const r = await computeTicketDiff(fx.proj, { id: 'af-01', worktree: fx.lane, base_ref: fx.base })
    const paths = r.files.map(f => f.path)
    for (const bad of ['.sandbar/agent_dev.log', '.sandbar/resume_patch_x.yml', '.dsh/sessions/s.jsonl',
      'pkg/__pycache__/sys.cpython-312.pyc', 'out/pycache/stdlib.pyc', 'node_modules/leftpad/index.js', '.venv/bin/python']) {
      ok(!paths.includes(bad), `过程物不进清单：${bad}`)
    }
    ok(paths.includes('real.py'), '合法文件不受牵连')
    ok((r.excludedEngineFiles ?? 0) >= 7, `排除计数 ≥7（实得 ${r.excludedEngineFiles}）`)
    ok(r.excludedPaths !== undefined && r.excludedPaths.includes('pkg/__pycache__/sys.cpython-312.pyc'),
      '嵌套 __pycache__ 被点名（M2 嵌套语义）')
    ok(r.excludedPaths !== undefined && r.excludedPaths.includes('.sandbar/agent_dev.log'), '点名单含 .sandbar 日志（验收 d）')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('B committed 过程物同样滤除')
{
  const fx = freshLane()
  try {
    // 基线里就有已跟踪的 out/cache.bin 与 __pycache__ 产物，工作树里改它
    put(join(fx.proj, 'out', 'cache.bin'), 'v2', 'utf8')
    mkdirSync(join(fx.proj, 'm', '__pycache__'), { recursive: true })
    put(join(fx.proj, 'm', '__pycache__', 'a.pyc'), 'v2', 'utf8')
    git(['add', '.'], fx.proj)
    git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'seed artifacts'], fx.proj)
    const base2 = git(['rev-parse', 'HEAD'], fx.proj).trim()
    put(join(fx.lane, 'out', 'cache.bin'), 'v3', 'utf8')
    put(join(fx.lane, 'm', '__pycache__', 'a.pyc'), 'v3', 'utf8')
    put(join(fx.lane, 'ok.txt'), 'ok\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, { id: 'af-02', worktree: fx.lane, base_ref: base2 })
    const paths = r.files.map(f => f.path)
    ok(!paths.includes('out/cache.bin') && !paths.includes('m/__pycache__/a.pyc'), 'committed 过程物不进清单')
    ok(paths.includes('ok.txt'), 'committed 合法文件正常')
    ok(r.excludedPaths !== undefined && r.excludedPaths.includes('out/cache.bin'), 'committed 过程物也点名')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('C 相近名不误杀')
{
  const fx = freshLane()
  try {
    put(join(fx.lane, 'sandbox.txt'), 'x\n', 'utf8')
    put(join(fx.lane, 'outer', 'keep.py'), 'k\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, { id: 'af-03', worktree: fx.lane, base_ref: fx.base })
    const paths = r.files.map(f => f.path)
    ok(paths.includes('sandbox.txt'), 'sandbox.txt 不因 .sandbar 前缀相近被误杀')
    ok(paths.includes('outer/keep.py'), '普通子目录文件不误杀')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('D isProcessArtifact 纯函数边角（契约真源）')
{
  ok(isProcessArtifact('.sandbar/x') && isProcessArtifact('a/b/__pycache__/x') && isProcessArtifact('out/x'), '顶层+嵌套全命中')
  ok(!isProcessArtifact('outputs/x') && !isProcessArtifact('src/vendor/y.js'), '相近前缀（outputs/ vendor/）不误杀')
  ok(PROCESS_ARTIFACT_TABLE.includes('.dsh/') && PROCESS_ARTIFACT_TABLE.includes('.sandbar/') && PROCESS_ARTIFACT_TABLE.includes('.suyou/'),
    '过滤表含引擎三目录（R1 反向护栏素材）')
}

console.log(`\nT260911_01_ARTIFACT_FILTER pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
