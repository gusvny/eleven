#!/usr/bin/env node
/**
 * t260915-17-ticket-time-file.mjs —— 「本票时刻只读文件」读取面单测（t260915-17）。
 *
 * 直跑：node server/plugins/workbench/tests/t260915-17-ticket-time-file.mjs
 * 契约：exit 0 = 过；末行 SUMMARY pass=<n> skip=<m> fail=<k>（fail>0 exit 1）。
 *
 * fixture=临时真 git 仓（t260902-04 t01 同手法：mkdtemp + rmSync 终态回收 +
 * git 子进程单参无 shell）。造六种形态仓，锁 review C1/C2/C4/C5/N1 全部必改条件：
 *   A  merge 收口仓（分支删除）：改动文件 settle=git show 逐字、背景文件 base=逐字、
 *      「工作树放不同内容」证明 settle 不回落工作树、current=工作树当前版、
 *      二进制拒渲染、路径不在该版本、畸形路径/畸形 meta、截断、主树道 N1、base 无效
 *   A2 merge 收口仓（分支残留）：leg① branch-tip 对已收口票生效（teardown 残留面）
 *   B  squash 收口仓（C2 主子用例）：subject 不含 lane/<id>、只 body 含——只取 subject
 *      的实现会假 fail-closed，此仓锁「完整 message 匹配」
 *   C  撞库仓：main 上只有长 id 票（lane/t260915-17）的收口提交，查短 id 不命中
 *   D  在飞仓（C1 配套：泳道分支在场）：dispatched/rework 一律拒绝（分支在场也拒）
 *   E  泳道拆无收口仓：分支删了、main 无收口提交 → lane-gone 人话
 *   F  多仓仓：成员仓路径 settle 走条目 branch 归属；base=member-repo-no-base（C4③
 *      诚实降级钉死，不修成回落）；根仓条目 branch（lane/<id>-root）归属
 *   G  messageContainsBranch 边界直测（短 id 撞长 id / 单仓撞多仓后缀）
 *   Z  只读刚性源码锁：host 模块 git 子命令字面量 ⊆ {show,rev-parse,log,rev-list}，
 *      无 fs 写面
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const HOST_TS = join(HERE, '..', 'src', 'host', 'ticket-time-file.ts')
const { readTicketTimeFile, sanitizeRepoWorktrees, messageContainsBranch, TICKET_TIME_MAX_CHARS } = await import(HOST_TS)

let PASS = 0
let FAIL = 0
const CLEANUPS = []
function ok(cond, label) {
  if (cond) { PASS += 1; console.log(`  ok  ${label}`) }
  else { FAIL += 1; console.error(`  FAIL ${label}`) }
}
function summary() {
  console.log(`SUMMARY pass=${PASS} skip=0 fail=${FAIL}`)
  process.exit(FAIL > 0 ? 1 : 0)
}
process.on('exit', () => { for (const c of CLEANUPS) { try { c() } catch { /* 回收尽力 */ } } })

/* ── git fixture 工具（子进程全单参无 shell；临时仓退出时统一 rmSync） ── */
function g(cwd, ...args) {
  return execFileSync('git', ['-C', cwd, ...args], { encoding: 'utf8' })
}
function newRepo(dirName) {
  const root = mkdtempSync(join(tmpdir(), `ttt-${dirName}-`))
  CLEANUPS.push(() => rmSync(root, { recursive: true, force: true }))
  execFileSync('git', ['init', '-b', 'main', root], { encoding: 'utf8' })
  g(root, 'config', 'user.email', 'test@example.com')
  g(root, 'config', 'user.name', 'test')
  mkdirSync(join(root, 'docs'), { recursive: true }) // 各形态仓共用基线路径
  return root
}
function commitAll(root, msg) {
  g(root, 'add', '-A')
  g(root, 'commit', '-m', msg)
}
function gitShow(root, ref, path) {
  return execFileSync('git', ['-C', root, 'show', `${ref}:${path}`], { encoding: 'utf8' })
}

/* ── 共用内容（基点版 / 收口版 / 工作树当前版三态互异——逐字对照可判回落） ── */
const BASE_REF = '基点版内容 alpha（开票时点的 docs/ref.md）\n'
const SETTLE_REF = '收口版内容 omega（本票改动后的 docs/ref.md）\n'
const WORKTREE_REF = '工作树当前版 zeta（merge 后有人又改了未提交）\n'
const FEAT = "export const feat = '收口新增 feature.ts'\n"
const BASE_APP = 'const a = 1 // 基点\n'

/** merge 收口仓（keepBranch=是否残留泳道分支=leg① 对应面）。 */
function makeMergeRepo(name, keepBranch) {
  const root = newRepo(name)
  mkdirSync(join(root, 'docs'), { recursive: true })
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  mkdirSync(join(root, 'src'), { recursive: true })
  writeFileSync(join(root, 'src/app.ts'), BASE_APP)
  mkdirSync(join(root, 'bin'), { recursive: true })
  writeFileSync(join(root, 'bin/asset.bin'), Buffer.from([0x00, 0x01, 0x02, 0xff]))
  writeFileSync(join(root, 'big.txt'), 'x'.repeat(2_100_000))
  commitAll(root, 'base commit')
  const baseRef = g(root, 'rev-parse', 'HEAD').trim()
  g(root, 'branch', 'lane/t260915-17')
  g(root, 'checkout', 'lane/t260915-17')
  writeFileSync(join(root, 'docs/ref.md'), SETTLE_REF)
  writeFileSync(join(root, 'src/feat.ts'), FEAT)
  commitAll(root, 'lane work')
  g(root, 'checkout', 'main')
  g(root, 'merge', '--no-ff', 'lane/t260915-17', '-m', "Merge branch 'lane/t260915-17'")
  const mergeCommit = g(root, 'rev-parse', 'HEAD').trim()
  if (!keepBranch) g(root, 'branch', '-D', 'lane/t260915-17')
  // 工作树当前版：merge 后有人又改了未提交（三态互异的关键）
  writeFileSync(join(root, 'docs/ref.md'), WORKTREE_REF)
  return { root, baseRef, mergeCommit }
}

const MERGE_META = { id: 't260915-17', status: 'closed', lane: 'worktree', branch: 'lane/t260915-17' }

/* ── A：merge 收口仓（分支删除） ── */
{
  const { root, baseRef, mergeCommit } = makeMergeRepo('merge-del', false)
  console.log('# A merge 收口仓（分支已删）')

  // 正用例①：改动文件 settle 与 git show 逐字（且工作树是另一内容——逐字命中即证明未回落）
  const r1 = await readTicketTimeFile(root, MERGE_META, 'settle', 'docs/ref.md')
  ok(r1.ok === true && r1.content === SETTLE_REF && r1.content !== WORKTREE_REF,
    'A1: settle 改动文件=收口版逐字（工作树另有人改未提交，未回落）')
  ok(r1.ref === mergeCommit && r1.refSource === 'merge-commit', 'A1: ref=收口提交+来源=merge')
  ok(gitShow(root, mergeCommit, 'docs/ref.md') === r1.content, 'A1: 与 git show 逐字对照')

  // 正用例②：收口新增文件
  const r2 = await readTicketTimeFile(root, MERGE_META, 'settle', 'src/feat.ts')
  ok(r2.ok === true && r2.content === FEAT && gitShow(root, mergeCommit, 'src/feat.ts') === r2.content,
    'A2: settle 收口新增文件=git show 逐字')

  // 正用例③：背景文件 base 与 git show 逐字
  const r3 = await readTicketTimeFile(root, { ...MERGE_META, baseRef }, 'base', 'docs/ref.md')
  ok(r3.ok === true && r3.content === BASE_REF && gitShow(root, baseRef, 'docs/ref.md') === r3.content,
    'A3: base 背景文件=基点版逐字')
  ok(r3.refSource === 'base-ref', 'A3: refSource=base-ref')

  // 反用例：路径不在该版本
  const r4 = await readTicketTimeFile(root, MERGE_META, 'settle', 'src/nope.ts')
  ok(r4.ok === false && r4.content === undefined && /不在该版本/.test(r4.reason ?? ''),
    'A4: settle 路径不在该版本 → 人话且无内容（不回落）')
  const r4b = await readTicketTimeFile(root, { ...MERGE_META, baseRef }, 'base', 'src/feat.ts')
  ok(r4b.ok === false && /不在该版本/.test(r4b.reason ?? ''),
    'A4b: base 问收口期新增文件 → 路径不在基点版')

  // C5②：二进制拒渲染
  const r5 = await readTicketTimeFile(root, MERGE_META, 'settle', 'bin/asset.bin')
  ok(r5.ok === false && r5.content === undefined && /二进制/.test(r5.reason ?? ''),
    'A5: 二进制文件 → 人话拒渲染（不冒充文本）')

  // current：工作树当前版（唯一读工作树的口径）
  const r6 = await readTicketTimeFile(root, MERGE_META, 'current', 'docs/ref.md')
  ok(r6.ok === true && r6.content === WORKTREE_REF, 'A6: current=工作树当前版（C5①）')
  const r6b = await readTicketTimeFile(root, MERGE_META, 'current', 'gone/x.txt')
  ok(r6b.ok === false && /当前工作树不存在/.test(r6b.reason ?? ''), 'A6b: current 缺文件 → 人话')

  // 畸形路径（fail-closed，不抛）
  for (const [p, label] of [['../etc/passwd', '相对穿路径'], ['/abs/x', '绝对路径'], ['a\\b', '反斜杠'], ['', '空串'], [null, 'null'], ['a b.md', '含空格']]) {
    const r = await readTicketTimeFile(root, MERGE_META, 'settle', p)
    ok(r.ok === false && r.content === undefined, `A7: 畸形路径拒收（${label}）`)
  }

  // 畸形 meta（不抛，人话）
  const r8 = await readTicketTimeFile(root, { ...MERGE_META, status: 42 }, 'settle', 'docs/ref.md')
  ok(r8.ok === false && /status/.test(r8.reason ?? ''), 'A8: status 畸形 → 人话不抛')
  const r8b = await readTicketTimeFile(root, { ...MERGE_META, repoWorktrees: [42] }, 'settle', 'docs/ref.md')
  ok(r8b.ok === true && r8b.content === SETTLE_REF, 'A8b: repo_worktrees 畸形 → 单仓退化不 500')

  // 截断：超封顶 + truncated 标记（截断后仍是「该时刻内容的前缀」，不冒充完整）
  const r9 = await readTicketTimeFile(root, MERGE_META, 'settle', 'big.txt')
  ok(r9.ok === true && r9.truncated === true && r9.content.length === 2_000_000,
    'A9: 2.1MB 超封顶 → truncated 标记+截断到 2MB')
  ok(TICKET_TIME_MAX_CHARS === 2_000_000, 'A9: 封顶常量口径 2MB')

  // N1：主树道专门文案
  const r10 = await readTicketTimeFile(root, { ...MERGE_META, lane: 'main', branch: '' }, 'settle', 'docs/ref.md')
  ok(r10.ok === false && /主树道/.test(r10.reason ?? ''), 'A10: 主树道 → 专门人话（不误导「泳道已拆」）')
  const r10b = await readTicketTimeFile(root, { id: 'x', status: 'closed' }, 'settle', 'docs/ref.md')
  ok(r10b.ok === false && /主树道/.test(r10b.reason ?? ''), 'A10b: lane/branch 缺省老票 → 同主树道面')

  // base 无效/缺登记
  const r11 = await readTicketTimeFile(root, { ...MERGE_META, baseRef: 'deadbeefdead' }, 'base', 'docs/ref.md')
  ok(r11.ok === false && /ref 无效/.test(r11.reason ?? ''), 'A11: base_ref 无效 → 人话')
  const r11b = await readTicketTimeFile(root, { ...MERGE_META }, 'base', 'docs/ref.md')
  ok(r11b.ok === false && /未登记开票基点/.test(r11b.reason ?? ''), 'A11b: base_ref 缺省 → 人话')

  // lane 分支 token 畸形（注入面）：branch 以 - 开头不得进 argv
  const r12 = await readTicketTimeFile(root, { ...MERGE_META, branch: '--exec=evil' }, 'settle', 'docs/ref.md')
  ok(r12.ok === false && r12.content === undefined, 'A12: branch 选项注入形态 → 拒收不进 argv')
}

/* ── A2：merge 收口仓（分支残留=leg① 对应面） ── */
{
  const { root } = makeMergeRepo('merge-keep', true)
  console.log('# A2 merge 收口仓（分支残留）')
  const r = await readTicketTimeFile(root, MERGE_META, 'settle', 'docs/ref.md')
  ok(r.ok === true && r.refSource === 'branch-tip' && r.ref === 'lane/t260915-17' && r.content === SETTLE_REF,
    'A2: 已收口+分支残留 → branch tip=该票提交版本（逐字收口内容）')
}

/* ── B：squash 收口仓（C2 主子用例：subject 无 lane/<id>，只在 body） ── */
{
  const root = newRepo('squash')
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  mkdirSync(join(root, 'src'), { recursive: true })
  writeFileSync(join(root, 'src/app.ts'), BASE_APP)
  commitAll(root, 'base commit')
  g(root, 'branch', 'lane/t260915-17')
  g(root, 'checkout', 'lane/t260915-17')
  writeFileSync(join(root, 'docs/ref.md'), SETTLE_REF)
  writeFileSync(join(root, 'src/feat.ts'), FEAT)
  commitAll(root, 'lane work')
  g(root, 'checkout', 'main')
  g(root, 'merge', '--squash', 'lane/t260915-17')
  // C2：复刻 agent_activities _squash_merge 模板——subject 不含 lane/<id>，body「来源 lane/<id>」
  commitAll(root, 't260915-17 squash 收口（一单一提交，KI-006）\n\n来源 lane/t260915-17；审计真源在 Temporal；泳道内小步历史不进 main')
  g(root, 'branch', '-D', 'lane/t260915-17')
  console.log('# B squash 收口仓（C2）')

  const r = await readTicketTimeFile(root, MERGE_META, 'settle', 'docs/ref.md')
  ok(r.ok === true && r.content === SETTLE_REF && r.refSource === 'squash-commit',
    'B1: squash 票（subject 无 lane/<id>）→ 完整 message 命中，收口版逐字')
  const r2 = await readTicketTimeFile(root, MERGE_META, 'settle', 'src/feat.ts')
  ok(r2.ok === true && r2.content === FEAT, 'B2: squash 票收口新增文件逐字')
}

/* ── C：撞库仓（短 id 不命中长 id 票收口提交） ── */
{
  const root = newRepo('collision')
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  commitAll(root, 'base')
  g(root, 'branch', 'lane/t260915-170')
  g(root, 'checkout', 'lane/t260915-170')
  writeFileSync(join(root, 'docs/ref.md'), '别人的票内容\n')
  commitAll(root, "Merge branch 'lane/t260915-170' 的内容提交")
  g(root, 'checkout', 'main')
  g(root, 'merge', '--squash', 'lane/t260915-170')
  commitAll(root, 't260915-170 squash 收口（一单一提交，KI-006）\n\n来源 lane/t260915-170；审计真源在 Temporal')
  g(root, 'branch', '-D', 'lane/t260915-170')
  console.log('# C 撞库仓（main 只有 t260915-170 收口提交）')

  const r = await readTicketTimeFile(root, { ...MERGE_META }, 'settle', 'docs/ref.md')
  ok(r.ok === false && r.content === undefined && /找不到本票（t260915-17）/.test(r.reason ?? ''),
    'C1: 短 id 不命中长 id 票收口提交（读到别人的票=撒谎级，拒）')
}

/* ── D：在飞仓（C1 配套：泳道分支在场仍拒） ── */
{
  const root = newRepo('inflight')
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  commitAll(root, 'base')
  g(root, 'branch', 'lane/t260915-17')
  g(root, 'checkout', 'lane/t260915-17')
  writeFileSync(join(root, 'docs/ref.md'), '在飞泳道未收口内容\n')
  commitAll(root, 'wip')
  // 工作树停在泳道分支上（在飞常态）：拒绝时绝不回落到这份内容
  console.log('# D 在飞仓（泳道分支在场）')

  for (const status of ['dispatched', 'rework']) {
    const r = await readTicketTimeFile(root, { ...MERGE_META, status }, 'settle', 'docs/ref.md')
    ok(r.ok === false && r.content === undefined && /还在飞/.test(r.reason ?? ''),
      `D1: 在飞 status=${status} + 分支在场 → 人话拒绝（C1：分支存在性不可反证已收口）`)
  }
  // 对照：同仓 status 改 closed → leg① 命中（证明 D1 拒的是在飞语义而非分支缺席）
  const r2 = await readTicketTimeFile(root, { ...MERGE_META, status: 'closed' }, 'settle', 'docs/ref.md')
  ok(r2.ok === true && r2.refSource === 'branch-tip' && /在飞泳道未收口内容/.test(r2.content ?? ''),
    'D2: 同仓已收口态 → branch tip 正常可得（D1 拒绝的确实是在飞语义）')
}

/* ── E：泳道拆无收口仓（分支删、main 无收口提交） ── */
{
  const root = newRepo('lane-gone')
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  commitAll(root, 'base')
  g(root, 'branch', 'lane/t260915-17')
  g(root, 'checkout', 'lane/t260915-17')
  writeFileSync(join(root, 'docs/ref.md'), SETTLE_REF)
  commitAll(root, 'lane work')
  g(root, 'checkout', 'main')
  g(root, 'branch', '-D', 'lane/t260915-17')
  console.log('# E 泳道拆无收口仓')

  const r = await readTicketTimeFile(root, MERGE_META, 'settle', 'docs/ref.md')
  ok(r.ok === false && r.content === undefined && /泳道已拆除/.test(r.reason ?? ''),
    'E1: 拆且无收口提交 → lane-gone 人话（不回落工作树 main 版本）')
}

/* ── F：多仓仓（settle 逐仓归属；base=member-repo-no-base 诚实降级） ── */
{
  const root = newRepo('multirepo')
  writeFileSync(join(root, 'docs/ref.md'), BASE_REF)
  commitAll(root, 'base')
  // 成员仓（主树布局内的独立 git 仓）
  const member = join(root, 'member-repo')
  mkdirSync(member, { recursive: true })
  execFileSync('git', ['init', '-b', 'main', member], { encoding: 'utf8' })
  g(member, 'config', 'user.email', 'test@example.com')
  g(member, 'config', 'user.name', 'test')
  writeFileSync(join(member, 'm.md'), '成员仓基点\n')
  commitAll(member, 'member base')
  g(member, 'branch', 'lane/t260915-17-member-repo')
  g(member, 'checkout', 'lane/t260915-17-member-repo')
  writeFileSync(join(member, 'm.md'), '成员仓收口版\n')
  writeFileSync(join(member, 'm2.md'), '成员仓收口新增\n')
  commitAll(member, 'member lane work')
  g(member, 'checkout', 'main')
  g(member, 'merge', '--squash', 'lane/t260915-17-member-repo')
  commitAll(member, 't260915-17 squash 收口（一单一提交，KI-006）\n\n来源 lane/t260915-17-member-repo；审计真源在 Temporal')
  g(member, 'branch', '-D', 'lane/t260915-17-member-repo')
  // 根仓条目（repo=''branch=lane/<id>-root）
  g(root, 'branch', 'lane/t260915-17-root')
  g(root, 'checkout', 'lane/t260915-17-root')
  writeFileSync(join(root, 'docs/ref.md'), SETTLE_REF)
  commitAll(root, 'root lane work')
  g(root, 'checkout', 'main')
  g(root, 'merge', '--squash', 'lane/t260915-17-root')
  commitAll(root, 't260915-17 squash 收口（一单一提交，KI-006）\n\n来源 lane/t260915-17-root；审计真源在 Temporal')
  g(root, 'branch', '-D', 'lane/t260915-17-root')
  const rws = [
    { repo: '', name: 'root', branch: 'lane/t260915-17-root' },
    { repo: 'member-repo', name: 'member-repo', branch: 'lane/t260915-17-member-repo' },
  ]
  const meta = { ...MERGE_META, branch: 'lane/t260915-17', repoWorktrees: rws }
  console.log('# F 多仓仓')

  const r1 = await readTicketTimeFile(root, meta, 'settle', 'member-repo/m.md')
  ok(r1.ok === true && r1.content === '成员仓收口版\n', 'F1: 成员仓路径 settle=成员仓收口版（逐仓归属）')
  const r2 = await readTicketTimeFile(root, meta, 'settle', 'member-repo/m2.md')
  ok(r2.ok === true && r2.content === '成员仓收口新增\n', 'F2: 成员仓收口新增文件逐字')
  const r3 = await readTicketTimeFile(root, meta, 'settle', 'docs/ref.md')
  ok(r3.ok === true && r3.content === SETTLE_REF, 'F3: 根仓条目 branch（lane/<id>-root）归属收口')
  const r4 = await readTicketTimeFile(root, meta, 'base', 'member-repo/m.md')
  ok(r4.ok === false && /成员仓路径未登记开票基点/.test(r4.reason ?? '') && r4.content === undefined,
    'F4: 成员仓 base → member-repo-no-base（C4③ 诚实降级，不修成回落）')
  const r5 = await readTicketTimeFile(root, { ...meta, baseRef: g(root, 'rev-parse', 'HEAD~1').trim() }, 'base', 'docs/ref.md')
  ok(r5.ok === true && r5.content === BASE_REF, 'F5: 根仓路径 base=根仓票面 base_ref（C4① 不做归属）')
}

/* ── G：messageContainsBranch 边界直测 ── */
{
  console.log('# G 边界直测')
  ok(messageContainsBranch('来源 lane/t260915-17；审计真源在 Temporal', 'lane/t260915-17') === true,
    'G1: body 整串命中')
  ok(messageContainsBranch("Merge branch 'lane/t260915-17'", 'lane/t260915-17') === true,
    'G2: merge subject 命中')
  ok(messageContainsBranch("Merge branch 'lane/t260915-170'", 'lane/t260915-17') === false,
    'G3: 短 id 不命中长 id（后随数字拒）')
  ok(messageContainsBranch('来源 lane/t260915-24', 'lane/t260915-2') === false,
    'G4: t…-2 不命中 t…-24')
  ok(messageContainsBranch('来源 lane/t260915-17-root', 'lane/t260915-17') === false,
    'G5: 单仓 branch 不命中多仓后缀（后随连字符拒）')
  ok(messageContainsBranch('来源 lane/t260915-17-root', 'lane/t260915-17-root') === true,
    'G6: 多仓 branch 整串命中')
  ok(messageContainsBranch('xxlane/t260915-17', 'lane/t260915-17') === false,
    'G7: 前边界黏连拒（非独立 token）')
  ok(messageContainsBranch('', 'lane/t260915-17') === false && messageContainsBranch('x', '') === false,
    'G8: 空入参恒 false')
}

/* ── H：sanitizeRepoWorktrees 形状消毒 ── */
{
  console.log('# H 消毒')
  ok(sanitizeRepoWorktrees(undefined) === undefined && sanitizeRepoWorktrees([]) === undefined, 'H1: 缺省/空 → undefined')
  ok(sanitizeRepoWorktrees([{ repo: '', name: 'root', branch: 'lane/x-root' }]) !== undefined, 'H2: 合法条目过')
  ok(sanitizeRepoWorktrees([{ repo: '../evil', name: 'x', branch: 'lane/x' }]) === undefined, 'H3: 穿路径仓拒')
  ok(sanitizeRepoWorktrees([{ repo: '/abs', name: 'x', branch: 'lane/x' }]) === undefined, 'H4: 绝对路径仓拒')
  ok(sanitizeRepoWorktrees([{ repo: 'a', name: '', branch: 'lane/x' }]) === undefined, 'H5: 键缺失拒')
  ok(sanitizeRepoWorktrees([42]) === undefined, 'H6: 非对象条目拒')
}

/* ── Z：只读刚性源码锁 ── */
{
  console.log('# Z 源码锁')
  const src = readFileSync(HOST_TS, 'utf8')
  // Z1：git 写动词只认「args 数组首元素」形态 `['动词'`——票面字段值（lane==='worktree'）
  // 与来源标签（'branch-tip'）是数据不是命令，不在锁面。
  const forbidden = ['add', 'commit', 'push', 'checkout', 'reset', 'clean', 'rm', 'mv', 'apply', 'rebase', 'stash', 'cherry-pick', 'merge', 'worktree', 'branch', 'tag', 'config', 'init', 'clone', 'fetch', 'pull']
  const hits = forbidden.filter((w) => src.includes(`['${w}'`))
  ok(hits.length === 0, `Z1: host 模块无写性 git 子命令字面量（命中：${hits.join(',') || '无'}）`)
  // Z2：args 数组首元素（首字符须字母——排除 ['--merges'] 这类选项数组）⊆ 只读白名单。
  const used = [...src.matchAll(/\['([a-z][a-z-]*)'/g)].map((m) => m[1])
  const allow = new Set(['show', 'rev-parse', 'log', 'rev-list'])
  const bad = used.filter((u) => !allow.has(u))
  ok(bad.length === 0, `Z2: git 子命令字面量 ⊆ {show,rev-parse,log,rev-list}（越界：${bad.join(',') || '无'}）`)
  // Z3：无 fs 写面（词边界——truncated 变量名不算 truncate）。
  const fsBad = ['writeFile', 'appendFile', 'mkdir', 'unlink', 'truncate', 'rmdir']
    .filter((w) => new RegExp(`\\b${w}\\b`).test(src))
  ok(fsBad.length === 0, `Z3: 无 fs 写面（命中：${fsBad.join(',') || '无'}）`)
}

summary()
