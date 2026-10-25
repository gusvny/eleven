#!/usr/bin/env node
/**
 * i01_merged_squash_bigdiff_bounded.mjs —— squash 收口票大体量变更集回放有界（t260902-04 集成验收）。
 *
 * 用户场景：工单台打开一张已 squash 收口的工单，diff 面板应给出有界、带显式截断
 * 标记的变更集，而不是 502 白屏（生产事故：t260902-01 diff 端点 stdout maxBuffer
 * exceeded，端点整单 500）。
 *
 * fixture：临时真 git 仓库，base 提交后 lane 分支单提交夹带大体量产物，main 上
 * `git merge --squash` 收口（单父、message 含 lane/<id>，模拟 _squash_merge 产物）。
 * 走 computeTicketDiff 的 merged 回放道（ticket.worktree 指向仓库内不存在路径）。
 *
 * 覆盖（用户可感知行为）：
 *   - >1MB modified 代码文件：不抛错、unifiedTruncated=true、unified ≤ 49KB（锁 48KB 封顶）
 *   - >1MB 单行 minified 新增文件：unifiedTruncated=true、unified ≤ 49KB（锁字符封顶）
 *   - >256KB modified 文档（doc 道）：不抛错、块文本 ≤ 257KB（锁输入封顶，diffBlocks 不爆）
 *   - >256KB 单行非法 JSON（data 道退化）：不抛错、unified 有界、带截断标记
 *   - 正常小文件：diff 完整、无截断标记（截断不误伤）
 *   - newHash 锁：>256KB 文件只改尾部（截断点之后），两次回放 newHash 必须不同
 *     （锁「哈希在截断前对全文计算」，防审批意见「已过期」漏判）
 *   - write_set 含人话备注/空串：正常剥离，文件不丢
 *   - write_set 缺省（全量回放）：文件名带空格的条目不 crash、内容正确
 *
 * 直跑：node integration/t260902-04/i01_merged_squash_bigdiff_bounded.mjs
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

// ---- 环境探测：缺依赖干净 SKIP（integration/README.md 执行契约） ----
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

// 封顶断言的宽容上界（方案常量 48KB/256KB + 文案/换行余量）
const UNIFIED_CAP = 49 * 1024
const TEXT_CAP = 257 * 1024
const SYNTH_CAP = 520 * 1024

// ---- fixture：squash 收口 + 大体量产物 ----
console.log('fixture：临时真仓库造 squash 收口提交（夹带大体量产物）')
const root = mkdtempSync(join(tmpdir(), 'integ-t260902-04-i01-'))
const repo = join(root, 'repo')
try {
  execFileSync('git', ['init', '-q', '-b', 'main', repo])
  git(repo, 'config', 'user.email', 't@example')
  git(repo, 'config', 'user.name', 'i01')
  mkdirSync(join(repo, 'src'), { recursive: true })
  mkdirSync(join(repo, 'docs'), { recursive: true })
  mkdirSync(join(repo, 'app/public/data'), { recursive: true })
  mkdirSync(join(repo, 'dir with space'), { recursive: true })

  // base 提交：小文件
  writeFileSync(join(repo, 'src/client.js'), 'const base = 1\n')
  writeFileSync(join(repo, 'docs/guide.md'), '# guide\n\nsmall\n')
  writeFileSync(join(repo, 'app/public/data/seed.json'), '{"seed": true}\n')
  writeFileSync(join(repo, 'small.txt'), 'hello\n')
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'base')

  // lane 提交：夹带大体量产物（模拟 bundled/minified 入库）
  git(repo, 'checkout', '-qb', 'lane/t-big')
  writeFileSync(join(repo, 'src/client.js'),
    Array.from({ length: 70000 }, (_, i) => `const x${i} = ${i};\n`).join('')) // ~1.2MB modified，diff 输出超 1MB（原默认 maxBuffer 触发面）
  writeFileSync(join(repo, 'lib.min.js'), 'var x=1;' + ';x++'.repeat(400000)) // ~1.6MB 单行新增
  writeFileSync(join(repo, 'docs/guide.md'),
    Array.from({ length: 2999 }, (_, i) => `第 ${i} 节 ${'文'.repeat(90)}\n`).join('') +
    'TAIL-' + 'A'.repeat(90) + '\n') // ~300KB modified，尾标在 256KB 截断点之后
  writeFileSync(join(repo, 'app/public/data/seed.json'), '{"broken":"' + 'y'.repeat(300000)) // ~300KB 单行非法 JSON
  writeFileSync(join(repo, 'small2.txt'), 'world\n')
  writeFileSync(join(repo, 'dir with space/new file.txt'), 'space file\n')
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 'lane big change')

  // main 上 squash 收口：单父提交，message 含 lane/t-big
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'merge', '--squash', 'lane/t-big')
  git(repo, 'commit', '-qm', 't-big squash 收口（一单一提交）\n\n来源 lane/t-big；审计真源在 Temporal')
  git(repo, 'branch', '-q', '-D', 'lane/t-big')

  // 第二个 squash 提交：只改 guide.md 尾部（TAIL-AAAA→TAIL-BBBB，位置在 256KB 之后），
  // 用于锁「newHash 在截断前对全文计算」。
  const guideV2 = Array.from({ length: 2999 }, (_, i) => `第 ${i} 节 ${'文'.repeat(90)}\n`).join('') +
    'TAIL-' + 'B'.repeat(90) + '\n'
  writeFileSync(join(repo, 'docs/guide.md'), guideV2)
  git(repo, 'add', '.')
  git(repo, 'commit', '-qm', 't-hash-b squash 收口\n\n来源 lane/t-hash-b')

  // fixture 自检：尾部单父、message 含 lane/t-hash-b
  const parents = git(repo, 'rev-list', '--parents', '-1', 'HEAD').trim().split(/\s+/).length - 1
  ok(parents === 1, 'fixture 尾部为单父 squash 提交')
  ok(git(repo, 'log', '-1', '--format=%B').includes('lane/t-hash-b'), 'fixture 收口 message 含 lane/<id>')

  // ---- 被测真源 ----
  const { computeTicketDiff } = await import(CHANGES_TS)

  console.log('case A：write_set 带人话备注/空串的 squash 回放（生产事故场景）')
  const ticketA = {
    id: 't-big',
    worktree: '.worktrees/gone-t-big', // 不存在 → merged 回放道
    base_ref: '',
    write_set: ['src/client.js（主改动）', 'lib.min.js', '', 'docs/guide.md', 'app/public/data/seed.json', 'small2.txt'],
  }
  let rA
  let threw = null
  try {
    rA = await computeTicketDiff(repo, ticketA)
  } catch (e) {
    threw = e
  }
  ok(threw === null, `computeTicketDiff 不抛错（实际 ${threw ? String(threw).slice(0, 80) : '正常返回'}）`)
  ok(rA && rA.source === 'merged', `source=merged（实际 ${rA?.source}）`)
  ok(rA && rA.hasBase === true && rA.changed === true, 'hasBase 且 changed')

  const byPath = new Map((rA?.files ?? []).map(f => [f.path, f]))
  ok(byPath.size === 5, `write_set 五个文件全在（实际 ${byPath.size}）：备注/空串剥离正确`)

  const bigJs = byPath.get('src/client.js')
  ok(bigJs && bigJs.status === 'modified', 'src/client.js = modified')
  ok(bigJs && bigJs.unifiedTruncated === true, '>1MB 修改文件条目带 unifiedTruncated 标记')
  ok(bigJs && typeof bigJs.unified === 'string' && bigJs.unified.length > 0 && bigJs.unified.length <= UNIFIED_CAP,
    `unified 非空且 ≤ ${UNIFIED_CAP}B（实际 ${bigJs?.unified?.length ?? '无'}）`)

  const minJs = byPath.get('lib.min.js')
  ok(minJs && minJs.status === 'added', 'lib.min.js = added')
  ok(minJs && minJs.unifiedTruncated === true, '>1MB 单行新增文件带 unifiedTruncated 标记')
  ok(minJs && typeof minJs.unified === 'string' && minJs.unified.length <= UNIFIED_CAP,
    `新增文件 unified ≤ ${UNIFIED_CAP}B（实际 ${minJs?.unified?.length ?? '无'}）`)

  const guide = byPath.get('docs/guide.md')
  ok(guide && guide.kind === 'doc', 'docs/guide.md = doc 道')
  ok(guide && guide.unifiedTruncated === true, '>256KB 文档条目带截断标记')
  // t261026-03: source note copy migrated to English (CLAUDE.md rule 3) — pin the live string.
  ok(guide && typeof guide.note === 'string' && guide.note.includes('shown truncated'),
    '截断文案 UI 可见（note 带 "shown truncated"）')
  const blockTexts = (guide?.blocks ?? []).flatMap(b => [b.oldText, b.newText]).filter(t => typeof t === 'string')
  ok(blockTexts.length > 0 && blockTexts.every(t => t.length <= TEXT_CAP),
    `doc 道每块文本 ≤ ${TEXT_CAP}B（最大实际 ${blockTexts.length ? Math.max(...blockTexts.map(t => t.length)) : '无块'}）`)

  const seed = byPath.get('app/public/data/seed.json')
  ok(seed && typeof seed.unified === 'string' && seed.unified.includes('JSON parse failed'),
    '非法 JSON 走显式退化（文案不静默）')
  ok(seed && seed.unified.length <= SYNTH_CAP,
    `data 道退化 unified ≤ ${SYNTH_CAP}B（实际 ${seed?.unified?.length ?? '无'}）`)
  ok(seed && seed.unifiedTruncated === true, '>256KB 非法 JSON 条目带截断标记')

  const small = byPath.get('small2.txt')
  ok(small && small.status === 'added' && small.unified.startsWith('+world'), '小文件 diff 完整无误伤（+world）')
  ok(small && small.unifiedTruncated !== true, '小文件不带截断标记')

  console.log('case B：newHash 锁——只改尾部（截断点之后），哈希必须变化')
  const rB = await computeTicketDiff(repo, {
    id: 't-hash-b', worktree: '.worktrees/gone-t-big', base_ref: '', write_set: ['docs/guide.md'],
  })
  const guideB = rB.files.find(f => f.path === 'docs/guide.md')
  ok(guideB && guideB.unifiedTruncated === true, 't-hash-b 回放的大文档条目带截断标记')
  ok(guide && guideB && guide.newHash !== guideB.newHash,
    '尾部差异（截断点之后）newHash 不同（锁截断前全文哈希）')

  console.log('case C：write_set 缺省 = 全量回放，文件名带空格不 crash')
  const rC = await computeTicketDiff(repo, { id: 't-big', worktree: '.worktrees/gone-t-big', base_ref: '' })
  ok(rC.source === 'merged' && rC.changed, '全量回放 source=merged 且 changed')
  const spaced = (rC.files ?? []).find(f => f.path === 'dir with space/new file.txt')
  ok(spaced !== undefined, '空格文件名条目在全量回放中出现')
  ok(spaced && spaced.status === 'added' && spaced.unified.includes('+space file'),
    '空格文件名条目内容正确（+space file）')

  console.log('case D：回放不受后续 main 演进污染（blob 读当时版本）')
  // main 再演进：在 guide.md 头部插入一行（属于另一个工单的后续合并）
  const guideNow = guideV2 // 当前工作树即 v2
  writeFileSync(join(repo, 'docs/guide.md'), '# later main edit\n' + guideNow)
  git(repo, 'commit', '-qam', 'later main edit (other ticket)')
  const rA2 = await computeTicketDiff(repo, ticketA)
  const bigJs2 = rA2.files.find(f => f.path === 'src/client.js')
  ok(rA2.source === 'merged' && bigJs2 && bigJs2.unifiedTruncated === true,
    '演进后重放仍成功且大文件条目仍带截断标记（不 502）')

  // ---- 测试自身资源回收 ----
  ok(existsSync(repo), 'fixture 仓库在用期间存在')
} finally {
  rmSync(root, { recursive: true, force: true })
}
ok(!existsSync(root), 'fixture 临时目录已清理（测试自身资源回收）')

console.log(`SUMMARY pass=${PASS} skip=0 fail=${FAIL}`)
process.exit(FAIL === 0 ? 0 : 1)
