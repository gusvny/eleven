#!/usr/bin/env node
/**
 * t260911_01_multirepo_diff.mjs —— 工单 diff 面多仓逐仓汇总（t260911-01 2a）自测。
 *
 * 直跑：node tests/t260911_01_multirepo_diff.mjs（node ≥22.18 原生 type-stripping）。
 * 夹具=临时多仓项目（根仓 worktree 容器 + 成员仓 worktree 子树），零真实项目依赖。
 * 覆盖：
 *   A. 多仓票逐仓汇总：成员仓文件在 repos[].files 与顶层兼容层（<repo>/ 前缀），
 *      内容可展开（unified 非空）；每仓各自 base（条目 base_ref 优先，缺省 merge-base）。
 *   B. 逐仓三态点名：成员仓树未物化 / base_ref 无效 → 该仓 emptyReason 点名，不整体降级。
 *   C. 畸形 repo_worktrees（M1，消毒层=computeTicketDiff 直测，handler 仅透传）：
 *      非列表 / 条目缺 branch / repo 含 .. → 视同缺省走单仓路径（repos undefined，不 500）。
 *   D. 按仓封顶（R3/C1）：成员仓 >60 文件时成员仓仍可见且内容可取；顶层 filesTruncated
 *      =任一仓截断即置位；根仓不受挤出。
 *   E. 单仓零回归（R5 退化路径）：空/缺省 repo_worktrees → 单仓路径行为不变。
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { computeTicketDiff } from './../src/host/changes.ts'

let passed = 0, failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

function git(args, cwd) {
  return execFileSync('git', ['-C', cwd, ...args], { stdio: ['ignore', 'pipe', 'pipe'] }).toString()
}

/** 写文件并自建父目录（过程物/深路径夹具常带多层目录）。 */
function put(file, content) {
  mkdirSync(join(file, '..'), { recursive: true })
  writeFileSync(file, content, 'utf8')
}

/** 造一个最小 git 仓：main 一个基线提交，返回基线 sha。 */
function initRepo(dir) {
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'README.md'), '# 夹具\n', 'utf8')
  git(['init', '-q', '-b', 'main'], dir)
  git(['add', '.'], dir)
  git(['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'base'], dir)
  return git(['rev-parse', 'HEAD'], dir).trim()
}

let seq = 0
function freshProject() {
  const rootDir = mkdtempSync(join(tmpdir(), `t26091101-mr-${++seq}-`))
  const proj = join(rootDir, 'proj')
  mkdirSync(proj, { recursive: true })
  const baseRoot = initRepo(join(proj, '.self'))
  // 把根仓本身挪到 proj（worktree 容器在仓内更贴近实况）：直接以 proj 为根仓工作树
  rmSync(join(proj, '.self'), { recursive: true, force: true })
  initRepo(proj)
  const baseRoot2 = git(['rev-parse', 'HEAD'], proj).trim()
  void baseRoot
  const memberBase = initRepo(join(rootDir, 'member-src'))
  // 泳道容器 = 根仓 worktree（须在仓根内：computeTicketDiff 有越根闸）；成员仓树 = 容器/b
  const lane = join(proj, '.worktrees', `lane-t26091101-${seq}`)
  git(['worktree', 'add', '-q', lane, '-b', `lane/t26091101-${seq}-root`], proj)
  const memberTree = join(lane, 'b')
  git(['worktree', 'add', '-q', memberTree, '-b', `lane/t26091101-${seq}-b`], join(rootDir, 'member-src'))
  return { rootDir, proj, lane, memberTree, baseRoot: baseRoot2, memberBase }
}

section('A 多仓逐仓汇总：成员仓可见、内容可展开、各仓 base')
{
  const fx = freshProject()
  try {
    // 根仓树改动
    put(join(fx.lane, 'server/root.py'), 'print("root change")\n', 'utf8')
    // 成员仓改动
    put(join(fx.memberTree, 'src/lib.py'), 'VALUE = 42\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, {
      id: 't26091101-01',
      worktree: fx.lane,
      base_ref: fx.baseRoot,
      repo_worktrees: [
        { repo: '', name: 'root', branch: 'lane/x-root', base_ref: fx.baseRoot },
        { repo: 'b', name: 'b', branch: 'lane/x-b', base_ref: fx.memberBase },
      ],
    })
    ok(r.repos !== undefined && r.repos.length === 2, '多仓票产出 repos[]（两仓）')
    const rootRepo = r.repos?.find(x => x.repo === '')
    const memberRepo = r.repos?.find(x => x.repo === 'b')
    ok(rootRepo?.files.some(f => f.path === 'server/root.py') === true, '根仓树改动在根仓条目')
    ok(memberRepo?.files.some(f => f.path === 'src/lib.py') === true, '成员仓文件在 repos[].files（2a 主断言）')
    const memberFile = memberRepo?.files.find(f => f.path === 'src/lib.py')
    ok(typeof memberFile?.unified === 'string' && memberFile.unified.includes('+VALUE = 42'), '成员仓文件内容可展开（unified 含新增行）')
    ok(r.files.some(f => f.path === 'b/src/lib.py'), '顶层兼容层带 <repo>/ 前缀')
    ok(r.files.some(f => f.path === 'server/root.py'), '顶层兼容层根仓文件无前缀')
    ok(memberRepo?.base === fx.memberBase, '成员仓 base=条目 base_ref')
    ok(memberRepo?.changed === true && rootRepo?.changed === true, '两仓各自 changed=true')
    ok(r.filesTruncated === false, '无截断时顶层 filesTruncated=false')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('A2 成员仓 base_ref 缺省 → merge-base 回落')
{
  const fx = freshProject()
  try {
    put(join(fx.memberTree, 'src/x.py'), 'X = 1\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, {
      id: 't26091101-02', worktree: fx.lane,
      repo_worktrees: [{ repo: '', name: 'root', branch: 'lane/x-root' }, { repo: 'b', name: 'b', branch: 'lane/x-b' }],
    })
    const memberRepo = r.repos?.find(x => x.repo === 'b')
    ok(memberRepo !== undefined && memberRepo.base !== '', '成员仓缺 base_ref 时回落 merge-base（非空）')
    ok(memberRepo?.files.some(f => f.path === 'src/x.py') === true, '回落基线下成员仓改动仍可见')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('B 逐仓三态点名：树未物化 / base 无效（不整体降级）')
{
  const fx = freshProject()
  try {
    put(join(fx.lane, 'a.txt'), 'hi\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, {
      id: 't26091101-03', worktree: fx.lane, base_ref: fx.baseRoot,
      repo_worktrees: [
        { repo: '', name: 'root', branch: 'lane/x-root', base_ref: fx.baseRoot },
        { repo: 'ghost', name: 'ghost', branch: 'lane/x-ghost' },
        { repo: 'b', name: 'b', branch: 'lane/x-b', base_ref: 'not/a..valid..ref!!' },
      ],
    })
    ok(r.repos !== undefined && r.repos.length === 3, '三仓条目全在')
    ok((r.repos?.[1].emptyReason ?? '').includes('not materialized'), '未物化仓 emptyReason 点名（英文，t261008-23）')
    ok((r.repos?.[2].emptyReason ?? '').includes('base ref invalid'), 'base 无效仓 emptyReason 点名（M1 三态，英文 t261008-23）')
    ok(r.repos?.[0].files.some(f => f.path === 'a.txt') === true, '健康仓不受坏仓拖累（不整体降级）')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('C 畸形 repo_worktrees 消毒（M1）：视同缺省走单仓，不 500')
{
  const fx = freshProject()
  try {
    put(join(fx.lane, 'm.txt'), 'm\n', 'utf8')
    const baseTicket = { id: 't26091101-04', worktree: fx.lane, base_ref: fx.baseRoot }
    const cases = [
      ['非列表', 'not-a-list'],
      ['条目非对象', [42]],
      ['条目缺 branch', [{ repo: '', name: 'root' }]],
      ['repo 含 ..', [{ repo: '../evil', name: 'evil', branch: 'b' }]],
      ['repo 绝对路径', [{ repo: '/etc', name: 'evil', branch: 'b' }]],
      ['空列表', []],
    ]
    for (const [label, malformed] of cases) {
      const r = await computeTicketDiff(fx.proj, { ...baseTicket, repo_worktrees: malformed })
      ok(r.repos === undefined && r.source === 'worktree' && r.files.some(f => f.path === 'm.txt'),
        `畸形（${label}）→ 单仓路径零变化`)
    }
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('D 按仓封顶（R3/C1）：成员仓 61 文件仍可见，顶层截断标记置位')
{
  const fx = freshProject()
  try {
    for (let i = 0; i < 61; i++) put(join(fx.memberTree, `gen/f${String(i).padStart(3, '0')}.py`), `# ${i}\n`, 'utf8')
    put(join(fx.lane, 'root-note.md'), '# root\n', 'utf8')
    const r = await computeTicketDiff(fx.proj, {
      id: 't26091101-05', worktree: fx.lane, base_ref: fx.baseRoot,
      repo_worktrees: [{ repo: '', name: 'root', branch: 'lane/x-root', base_ref: fx.baseRoot }, { repo: 'b', name: 'b', branch: 'lane/x-b', base_ref: fx.memberBase }],
    })
    const memberRepo = r.repos?.find(x => x.repo === 'b')
    const rootRepo = r.repos?.find(x => x.repo === '')
    ok(memberRepo?.files.length === 60 && memberRepo?.filesTruncated === true, '成员仓按仓封顶 60 + 自带截断标记')
    ok(memberRepo?.files.some(f => f.path === 'gen/f000.py') === true, '成员仓文件在清单（未被全局 cap 挤出）')
    ok(typeof memberRepo?.files[0].unified === 'string', '成员仓文件内容可展开（截断场景）')
    ok(rootRepo?.files.some(f => f.path === 'root-note.md') === true && rootRepo?.filesTruncated === false, '根仓不受成员仓超量影响')
    ok(r.filesTruncated === true, '顶层 filesTruncated=任一仓截断即置位（C1）')
    ok(r.files.filter(f => f.path.startsWith('b/gen/')).length === 60, '顶层兼容层含成员仓封顶后全量（不再全局 slice）')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

section('E 单仓零回归（R5 退化路径）：空/缺省明细 → 今日行为')
{
  const fx = freshProject()
  try {
    put(join(fx.lane, 'single.txt'), 's\n', 'utf8')
    const rDefault = await computeTicketDiff(fx.proj, { id: 't26091101-06', worktree: fx.lane, base_ref: fx.baseRoot })
    ok(rDefault.repos === undefined && rDefault.files.some(f => f.path === 'single.txt'), '缺省明细 → 单仓路径（repos undefined）')
    ok(rDefault.excludedEngineFiles === undefined, '无过程物时不带排除计数')
  } finally { rmSync(fx.rootDir, { recursive: true, force: true }) }
}

console.log(`\nT260911_01_MULTIREPO_DIFF pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
