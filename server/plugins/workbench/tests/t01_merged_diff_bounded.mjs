#!/usr/bin/env node
/**
 * t01_merged_diff_bounded.mjs —— squash 票 diff maxBuffer 修复回归（t260902-04）。
 *
 * 背景：t260902-01 squash 收口提交夹带 >1MB 产物（bundled lib/client.cjs、
 * vendor echarts），merged 回放路径的 per-file `git diff` 无 maxBuffer/无
 * try/catch，stdout 冲破 node 默认 1MB 缓冲 → diff 端点整单 500；gitShow
 * 静默吞错把 <C> 侧大 blob 读成空串；doc 道 diffBlocks / data 道 synthUnified
 * 输入无字符封顶。本测试在临时真 git 仓库造大体量 squash fixture，锁修复后的
 * 有界行为（大体量 fixture 锁规模，测试盲区回归）。
 *
 * fixture（临时真仓库，一次性 commit 混入）：
 *   - big-modified.txt  ~1.7MB 修改文件（per-file git diff >1MB，旧代码即抛错）
 *   - big-min.js        ~1.1MB 单行 minified 新增文件（git show 超 1MB + synth 无字符封顶）
 *   - docs/big-doc.md   ~300KB 修改文档（doc 道 diffBlocks 整块全文输入封顶）
 *   - app/public/data/big-bad.json  ~300KB 单行非法 JSON 新增（data 道 synthUnified 输入封顶）
 *   - giant-mod.txt     两侧各 ~10MB 单行修改（per-file diff ~20MB > 16MB 兜底 → --stat 一级降级）
 *   - small.txt / sp ace.txt  正常小文件（截断不误伤、文件名带空格）
 *   - case E：第二次 squash 提交只改 big-modified.txt 尾部（锁 newHash 截断前全文计算）
 * 畸形输入：坏 base_ref、非 commit ref、write_set 人话备注/空串。
 *
 * 直跑：node integration/t260902-04/t01_merged_diff_bounded.mjs
 * 末行 SUMMARY pass=<n> skip=<m> fail=<k>；fail>0 exit 1（integration/README.md 执行契约）。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..')
const CHANGES_TS = join(REPO_ROOT, 'server/plugins/workbench/src/host/changes.ts')
const { computeTicketDiff } = await import(CHANGES_TS)

let PASS = 0
let FAIL = 0
let SKIP = 0
function ok(cond, label) {
  if (cond) { PASS++; console.log(`  ok  ${label}`) }
  else { FAIL++; console.log(`  FAIL ${label}`) }
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' })
}

function makeRepo() {
  const root = mkdtempSync(join(tmpdir(), 'bounded-t01-'))
  const repo = join(root, 'repo')
  execFileSync('git', ['init', '-q', '-b', 'main', repo])
  git(repo, 'config', 'user.email', 't@example')
  git(repo, 'config', 'user.name', 't01')
  return { root, repo }
}

/** 重复行文本：lines 行 × ~20 字符。 */
function bigLines(prefix, lines) {
  return Array.from({ length: lines }, (_, i) => `${prefix}-line-${String(i).padStart(7, '0')}-padding`).join('\n') + '\n'
}

const MAX_UNIFIED = 48 * 1024
const MAX_TEXT = 256 * 1024
const MAX_SYNTH = 48 * 1024

console.log('fixture：临时真仓库造大体量 squash 收口提交（lane/t-bounded）')
const { root, repo } = makeRepo()
try {
  // ---- base 提交：小文件 + 将被大改的占位 ----
  writeFileSync(join(repo, 'big-modified.txt'), 'v0\n')
  mkdirSync(join(repo, 'docs'), { recursive: true })
  mkdirSync(join(repo, 'app/public/data'), { recursive: true })
  writeFileSync(join(repo, 'docs/big-doc.md'), '# base doc\n')
  writeFileSync(join(repo, 'giant-mod.txt'), 'A'.repeat(10 * 1024 * 1024) + '\n')
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'base')

  // ---- lane：一次性混入大体量改动 ----
  git(repo, 'checkout', '-qb', 'lane/t-bounded')
  // (a) ~1.7MB 修改文件：per-file git diff > 1MB，旧代码 maxBuffer 抛错点
  writeFileSync(join(repo, 'big-modified.txt'), bigLines('bigmod', 90000))
  // (b) ~1.1MB 单行 minified 新增：git show 超 1MB + synth 无字符封顶
  writeFileSync(join(repo, 'big-min.js'), `var x="${'a'.repeat(1_100_000)}";`)
  // (c) ~300KB 修改文档：doc 道 diffBlocks 整块全文输入封顶
  writeFileSync(join(repo, 'docs/big-doc.md'), '# big doc\n' + bigLines('doc', 16000))
  // (d) ~300KB 单行非法 JSON 新增：data 道 synthUnified 输入封顶
  writeFileSync(join(repo, 'app/public/data/big-bad.json'), `{"broken":"${'x'.repeat(300_000)}`)
  // giant：两侧各 10MB 单行修改 → per-file diff ~20MB > 16MB 兜底 → --stat 一级降级
  writeFileSync(join(repo, 'giant-mod.txt'), 'B'.repeat(10 * 1024 * 1024) + '\n')
  // 正常小文件 + 文件名带空格
  writeFileSync(join(repo, 'small.txt'), 'hello small\n')
  writeFileSync(join(repo, 'sp ace.txt'), 'space name\n')
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'squash closeout lane/t-bounded')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'merge', '-q', '--squash', 'lane/t-bounded')
  git(repo, 'commit', '-qm', 'squash closeout lane/t-bounded')
  git(repo, 'branch', '-qD', 'lane/t-bounded')

  const ticket = {
    id: 't-bounded',
    worktree: '.worktrees/gone-t-bounded', // 指向不存在路径 → merged 回放道
    base_ref: '',
    write_set: undefined,
  }

  console.log('case A：>1MB 修改文件——不再抛 maxBuffer，unified 有界且带截断标记')
  let rA
  let threw = ''
  try {
    rA = await computeTicketDiff(repo, ticket)
  } catch (err) {
    threw = String(err instanceof Error ? err.message : err)
  }
  ok(threw === '', `computeTicketDiff 不抛错（实际抛出：${threw.slice(0, 80) || '无'}）`)
  if (rA) {
    ok(rA.source === 'merged', `source=merged（实际 ${rA.source}）`)
    const f = rA.files.find(x => x.path === 'big-modified.txt')
    ok(f !== undefined, 'name-status 含 big-modified.txt')
    ok(f && f.unifiedTruncated === true, 'big-modified.txt unifiedTruncated=true')
    ok(f && typeof f.unified === 'string' && f.unified.length <= MAX_UNIFIED + 200,
      `big-modified.txt unified ≤ 48KB+文案（实际 ${f?.unified?.length}）`)
    ok(f && f.unified.includes('+bigmod-line-0000000-padding'),
      'big-modified.txt diff 头部内容正确（截断在前部之外）')
  }

  console.log('case B：>1MB 单行 minified 新增——synth 字符封顶')
  if (rA) {
    const f = rA.files.find(x => x.path === 'big-min.js')
    ok(f !== undefined, 'name-status 含 big-min.js')
    ok(f && f.status === 'added', 'big-min.js status=added')
    ok(f && f.unifiedTruncated === true, 'big-min.js unifiedTruncated=true')
    ok(f && typeof f.unified === 'string' && f.unified.length <= MAX_SYNTH + 200,
      `big-min.js unified ≤ 48KB+文案（实际 ${f?.unified?.length}）`)
    ok(f && f.newHash !== fnvEmpty(), 'big-min.js newHash 非空串哈希（<C> 侧 blob 真读到）')
  }

  console.log('case C：>256KB 修改文档——doc 道输入封顶 + 标记')
  if (rA) {
    const f = rA.files.find(x => x.path === 'docs/big-doc.md')
    ok(f !== undefined, 'name-status 含 docs/big-doc.md')
    ok(f && f.kind === 'doc' && Array.isArray(f.blocks), 'docs/big-doc.md 走 block diff')
    ok(f && f.unifiedTruncated === true, 'docs/big-doc.md unifiedTruncated=true（入口封顶标记）')
    ok(f && JSON.stringify(f.blocks).length <= MAX_TEXT * 2 + 4096,
      `docs/big-doc.md blocks 体量 ≤ 256KB×2+开销（实际 ${f ? JSON.stringify(f.blocks).length : 'N/A'}）`)
  }

  console.log('case D：>256KB 单行非法 JSON 新增——data 道退化视图输入封顶')
  if (rA) {
    const f = rA.files.find(x => x.path === 'app/public/data/big-bad.json')
    ok(f !== undefined, 'name-status 含 app/public/data/big-bad.json')
    ok(f && f.kind === 'code' && typeof f.unified === 'string',
      '非法 JSON 退化为行级 unified 视图（kind=code）')
    ok(f && f.unifiedTruncated === true, 'big-bad.json unifiedTruncated=true')
    ok(f && f.unified.length <= MAX_UNIFIED + 300,
      `big-bad.json unified ≤ 48KB+文案（实际 ${f?.unified?.length}）`)
    ok(f && f.unified.includes('JSON 解析失败'), 'big-bad.json 退化文案含「JSON 解析失败」')
  }

  console.log('case E：~20MB per-file diff > 16MB 兜底 → --stat 一级降级')
  if (rA) {
    const f = rA.files.find(x => x.path === 'giant-mod.txt')
    ok(f !== undefined, 'name-status 含 giant-mod.txt')
    ok(f && f.unifiedTruncated === true, 'giant-mod.txt unifiedTruncated=true')
    ok(f && typeof f.unified === 'string' && f.unified.includes('已降级为 --stat 摘要'),
      'giant-mod.txt 带一级降级文案「已降级为 --stat 摘要」')
    ok(f && f.unified.includes('giant-mod.txt'),
      'giant-mod.txt --stat 摘要含文件名')
    ok(f && f.unified.length <= MAX_UNIFIED + 300,
      `giant-mod.txt unified ≤ 48KB+文案（实际 ${f?.unified?.length}）`)
  }

  console.log('case F：正常小文件内容完整不误伤 + 文件名带空格')
  if (rA) {
    const f = rA.files.find(x => x.path === 'small.txt')
    // 文件以 \n 结尾 → split 出尾空行，合成 unified 形态为 '+hello small\n+'（既有口径）
    ok(f && f.unified === '+hello small\n+', `small.txt unified 完整精确（实际 ${JSON.stringify(f?.unified)}）`)
    ok(f && f.unifiedTruncated !== true, 'small.txt 未误标 truncated')
    const fs = rA.files.find(x => x.path === 'sp ace.txt')
    ok(fs && fs.unified === '+space name\n+', '文件名带空格解析正确')
  }

  console.log('case G：newHash 截断前全文计算——尾部改动必须改变哈希')
  if (rA) {
    const hashBefore = rA.files.find(x => x.path === 'big-modified.txt')?.newHash
    // 第二次 squash 提交：只改 big-modified.txt 尾部（>256KB 截断点之外）
    git(repo, 'checkout', '-qb', 'lane/t-hash')
    const lines = bigLines('bigmod', 90000).split('\n')
    lines[lines.length - 2] = 'TAIL-CHANGED-BY-CASE-G'
    writeFileSync(join(repo, 'big-modified.txt'), lines.join('\n'))
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'tail change lane/t-hash')
    git(repo, 'checkout', '-q', 'main')
    git(repo, 'merge', '-q', '--squash', 'lane/t-hash')
    git(repo, 'commit', '-qm', 'squash closeout lane/t-hash')
    git(repo, 'branch', '-qD', 'lane/t-hash')
    const rG = await computeTicketDiff(repo, { ...ticket, id: 't-hash' })
    const hashAfter = rG.files.find(x => x.path === 'big-modified.txt')?.newHash
    ok(typeof hashBefore === 'string' && hashBefore.length === 8, `第一次哈希可读（${hashBefore}）`)
    ok(hashBefore !== hashAfter,
      `尾部改动后 newHash 变化（${hashBefore} → ${hashAfter}）——证明哈希在截断前对全文计算`)
  }

  console.log('case H：畸形输入——坏 base_ref / 非 commit ref / write_set 人话备注与空串')
  const rBad = await computeTicketDiff(repo, {
    id: 't-never', worktree: '.worktrees/gone-x', base_ref: 'deadbeef',
    write_set: ['small.txt'],
  })
  ok(rBad.source === 'none', `找不到收口痕迹 → source=none（实际 ${rBad.source}）`)
  ok(rBad.emptyReason !== undefined, 'emptyReason 有人话原因')
  const rWs = await computeTicketDiff(repo, {
    ...ticket, write_set: ['small.txt（只读复用不修改）', ''],
  })
  ok(rWs.files.some(x => x.path === 'small.txt'),
    'write_set 含人话备注/空串时 small.txt 仍被解析命中')
  const rRef = await computeTicketDiff(repo, {
    id: 't-bounded', worktree: '.worktrees/gone-t-bounded',
    base_ref: 'deadbeef^{', // 非法 ref 字符 + 非 commit
    write_set: ['small.txt'],
  })
  ok(rRef.source === 'none' || rRef.base !== 'deadbeef^{',
    '非法 base_ref 不走 diff（不被注入）')
} finally {
  rmSync(root, { recursive: true, force: true })
}

function fnvEmpty() {
  // fnv1a('') = 0x811c9dc5
  return '811c9dc5'
}

console.log(`SUMMARY pass=${PASS} skip=${SKIP} fail=${FAIL}`)
process.exit(FAIL ? 1 : 0)
