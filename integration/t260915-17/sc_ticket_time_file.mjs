#!/usr/bin/env node
/**
 * sc_ticket_time_file.mjs —— 「文件行=链接」本票时刻只读读取面契约（t260915-17，mock 260904 标注 D）。
 *
 * 用户可感知契约（工单验收①②③ + review_plan 条件 C1/C2/C4/C5 钉死）：
 *   给定票 + 路径 + 时刻口径（settle=收口版 / base=开票基点版 / current=当前版）：
 *   1) settle：改动文件读到「本票收口提交」的版本，逐字=git show <C>:<path>——
 *      squash 形态 lane/<id> 只在 message body（「来源 lane/<id>」），merge 形态在
 *      subject（真票 t260915-05 实证 subject 不含 lane/<id>）→ 定位必须匹配完整 message；
 *   2) 短 id 不得命中长 id 票的收口提交（changes.ts --grep 子串缺陷家族的注入回归）；
 *   3) fail-closed 铁律：票在飞（status dispatched/rework，分支在场与否不影响——
 *      review C1）/泳道拆且无收口提交/路径不在该版本 → 200+ok:false 人话点名，
 *      绝不回落工作树内容（回落=把「现在」冒充「本票时刻」）；
 *   4) base：基点版=base_ref 版本；未登记/无效 → 人话；与在飞无关（时刻=定值）；
 *   5) current：唯一允许读工作树的口径，明示「现在」；
 *   6) 畸形输入（../、绝对路径、反斜杠、空、未知 mode）→ 人话不抛不 500 不回落；
 *   7) 二进制不透传乱码冒充内容；大文件封顶+truncated 标记不静默截断；
 *   8) 只读刚性：宿主计算核（src/host、src/shared）零写性 git 子命令字面量；
 *      端点非 GET 拒绝分支在场（405 源码锁，动态腿留浏览器台）。
 *
 * 三依据：①工单原始验收口径四条；②KI 触及面=无未闭合项直接触及（KI-070 项目锚
 * 链按其修复方向走 query>票面>默认仓，ki057-project-anchor.mjs 管既有端点锚，
 * 本场景 S1 锁新端点注册形态，intent 不重复）；③组件对外契约=上列 1-8。
 *
 * 驱动方式（灰盒）：直 import 方案承诺的宿主读面模块 micro 回放（t01 直 import
 * changes.ts 同款）；导出函数名方案未钉死——按「恰一个 async 函数导出」探测，
 * 调用形状协商锁定；实现缺席/签名漂移=FAIL 点名（TDD 网：本段先于 implement 落地，
 * 当前红=预期，implement 后须全绿）。
 *
 * 直跑：node integration/t260915-17/sc_ticket_time_file.mjs（cwd=仓库根）
 * 三态：SUMMARY pass=X fail=Y env_fail=Z na=W；exit 0=全过 / 1=产品红 / 2=环境红。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const REPO_ROOT = resolve(HERE, '..', '..')
const HOST_DIR = join(REPO_ROOT, 'server/plugins/workbench/src/host')
const SHARED_DIR = join(REPO_ROOT, 'server/plugins/workbench/src/shared')
const NODE_TS = join(REPO_ROOT, 'server/plugins/workbench/node.ts')
const READER_TS = join(HOST_DIR, 'ticket-time-file.ts')

let PASS = 0, FAIL = 0, ENVFAIL = 0, NA = 0
function ok(cond, label) { if (cond) { PASS++; console.log('  ok  ' + label) } else { FAIL++; console.log('  FAIL ' + label) } }
function envFail(label) { ENVFAIL++; console.log('  ENV_FAIL ' + label) }
function section(t) { console.log('\n== ' + t + ' ==') }

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' })
}

/* ---------------- G0 环境腿（缺 git = ENV_FAIL exit 2） ---------------- */
section('G0 环境')
try { execFileSync('git', ['--version'], { encoding: 'utf8' }); ok(true, 'git 在场') } catch { envFail('git 不可用——本场景全部腿依赖本地 git fixture'); console.log('SUMMARY pass=' + PASS + ' fail=' + FAIL + ' env_fail=' + ENVFAIL + ' na=' + NA); process.exit(2) }

/* ---------------- G1 结构锁：宿主只读刚性 + 端点形态（离线源码级） ---------------- */
section('G1 结构锁（宿主计算核零写动词 / 端点注册+405 形态）')
import { readFileSync, readdirSync } from 'node:fs'
const WRITE_LITERAL = /['"`](commit|push|reset|rebase|checkout|revert|cherry-pick|stash|apply|am|merge|branch|tag)['"`]/
function stripComments(t) { return t.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ') }
let writeHits = []
for (const dir of [HOST_DIR, SHARED_DIR]) {
  for (const f of readdirSync(dir).filter(n => n.endsWith('.ts'))) {
    const t = stripComments(readFileSync(join(dir, f), 'utf8'))
    for (const m of t.split('\n').entries()) {
      const [i, line] = m
      if (WRITE_LITERAL.test(line)) writeHits.push(`${f}:${i + 1}`)
      // worktree 双义：读（worktree list）允许，写（add/remove/prune）拒绝
      if (/['"`]worktree['"`]/.test(line) && !/worktree['"]\s*,\s*['"`]list/.test(line) && /['"`](add|remove|prune)['"]/.test(line)) writeHits.push(`${f}:${i + 1} (worktree 写形态)`)
    }
  }
}
ok(writeHits.length === 0, '宿主计算核（host+shared）零写性 git 子命令字面量' + (writeHits.length ? '——命中：' + writeHits.slice(0, 5).join(', ') : ''))
const nodeTsSrc = readFileSync(NODE_TS, 'utf8')
{ // 路由形态出现处（头注释/注册/handler 均可命中）邻近窗口内：
  // ①非 GET 拒绝（405）分支；②投影键→模块键映射证据（base_ref/baseRef 同窗）——
  // 引擎投影链是 snake、模块 meta 是 camel，漏映射=全票假「未登记开票基点」（撒谎级静默降级）
  let found = false, have405 = false, haveMap = false
  for (const m of nodeTsSrc.matchAll(/tickets\/[^'"`\n]*\/file/g)) {
    const win = nodeTsSrc.slice(m.index, m.index + 2600)
    if (/405/.test(win)) have405 = true
    if (/base_ref/.test(win) && /baseRef/.test(win)) haveMap = true
    found = true
  }
  ok(found, '本票时刻读取端点注册形态在场（tickets/<id>/file）')
  ok(have405, '端点非 GET 拒绝分支（405）在处理窗口内在场')
  ok(haveMap, '端点窗口含投影键→模块键映射证据（base_ref/baseRef 同窗）')
}
{ // C1 顺序锁：在飞判定必须先于分支定位（行序断言）——在飞票泳道分支必然在场
  // （teardown 收口才删），分支存在性不可反证已收口；防未来重排把「leg① 先行」
  // 的矛盾带回来（review C1 的源码级钉死）。锚=在飞闸行之后的首个定位调用
  // （分支 rev-parse / 收口提交搜索），函数定义行不计。
  const tts = readFileSync(READER_TS, 'utf8').split('\n')
  const inflightLine = tts.findIndex(l => /if \(isInFlightStatus\(/.test(l))
  let locateLine = -1
  for (let i = inflightLine + 1; i < tts.length; i++) {
    if (/await findSettleCommit\(|\['rev-parse',\s*'--verify'/.test(tts[i])) { locateLine = i; break }
  }
  ok(inflightLine > 0 && locateLine > inflightLine, 'C1 顺序锁：在飞判定（L' + (inflightLine + 1) + '）先于分支定位（L' + (locateLine + 1) + '）')
}

/* ---------------- 被测读面探测（形状协商） ---------------- */
let reader = null, invoke = null, readerGone = ''
try {
  const mod = await import(READER_TS)
  const fns = Object.entries(mod).filter(([, v]) => typeof v === 'function' && v.constructor?.name === 'AsyncFunction').map(([k]) => k)
  if (fns.length !== 1) {
    readerGone = `宿主读面导出探测失败：期望恰一个 async 函数导出，实得 [${Object.keys(mod).join(', ')}]（方案承诺 ticket-time-file.ts 只导出读函数）`
  } else {
    reader = mod[fns[0]]
  }
} catch (e) { readerGone = '宿主读面模块缺席/不可导入（' + READER_TS.replace(REPO_ROOT + '/', '') + '）：' + String(e).slice(0, 160) }

/* 形状协商（正例探测）：负例参数错位也会返回 ok:false（空转绿陷阱），所以
 * 用「必成功的 settle 读」锁形状——首个 ok:true 且内容相等的形状胜出。 */
const SHAPES = [
  ['(repo, meta, mode, path)', (t, r, k, p, m) => r(t, k, m, p)],
  ['(repo, meta, path, mode)', (t, r, k, p, m) => r(t, k, p, m)],
  ['(repo, {meta, path, mode})', (t, r, k, p, m) => r(t, { meta: k, path: p, mode: m })],
  ['(repo, {meta, mode, path})', (t, r, k, p, m) => r(t, { meta: k, mode: m, path: p })],
  ['({repoRoot, meta, path, mode})', (t, r, k, p, m) => r({ repoRoot: t, meta: k, path: p, mode: m })],
  ['({repoRoot, meta, mode, path})', (t, r, k, p, m) => r({ repoRoot: t, meta: k, mode: m, path: p })],
]
let shape = null
if (reader) { ok(true, '宿主读面探测：单 async 函数导出在场') } else { ok(false, '宿主读面探测——' + readerGone) }

/* ---------------- G2 fixture：一仓覆盖全形态（真 git 仓，tmp 自清理） ---------------- */
const SQUASH_MSG = (id) => `${id} squash 收口（一单一提交，KI-006）\n\n来源 lane/${id}；审计真源在 Temporal；泳道内小步历史不进 main`
function mkFixture() {
  const repo = mkdtempSync(join(tmpdir(), 't260915-17-'))
  const cfg = ['-c', 'user.email=t@sandbar', '-c', 'user.name=t']
  const w = (p, s) => { mkdirSync(join(repo, p, '..'), { recursive: true }); writeFileSync(join(repo, p), s); git(repo, 'add', p) }
  const cm = (msg) => git(repo, ...cfg, 'commit', '-m', msg)
  git(repo, 'init', '-b', 'main')
  w('docs/base.md', 'BASE-CONTENT\n'); cm('B0 基点')
  const baseRef = git(repo, 'rev-parse', 'HEAD').trim()
  // 短 id 陷阱：先 settle t260915-1（旧），再 settle t260915-17（新）——
  // 子串实现 --grep lane/t260915-1 会先命中 t260915-17 的提交（log 第一条）→ 杀缺陷
  git(repo, 'checkout', '-b', 'lane/t260915-1'); w('one.md', 'ONE-SETTLED\n'); cm('one work')
  git(repo, 'checkout', 'main'); git(repo, 'merge', '--squash', 'lane/t260915-1'); cm(SQUASH_MSG('t260915-1'))
  git(repo, 'checkout', '-b', 'lane/t260915-17'); w('seventeen.md', 'SEVENTEEN-SETTLED\n'); cm('seventeen work')
  git(repo, 'checkout', 'main'); git(repo, 'merge', '--squash', 'lane/t260915-17'); cm(SQUASH_MSG('t260915-17'))
  const c17 = git(repo, 'rev-parse', 'HEAD').trim()
  // merge 形态（subject 含 lane/<id>）
  git(repo, 'checkout', '-b', 'lane/tMRG'); w('mrg.md', 'MRG-MERGED\n'); cm('mrg work')
  git(repo, 'checkout', 'main'); git(repo, 'merge', '--no-ff', '-m', "Merge branch 'lane/tMRG'", 'lane/tMRG')
  // 在飞票：分支在场不拆，工作树放诱饵（回落侦测）
  git(repo, 'checkout', '-b', 'lane/tINF'); w('inf.md', 'INF-IN-FLIGHT\n')
  git(repo, 'checkout', 'main'); git(repo, 'branch', '-D', 'lane/t260915-1') // 拆道（与引擎 teardown 同形态；17 与 MRG 的分支留场测 leg① 残留面）
  writeFileSync(join(repo, 'inf.md'), 'INF-WORKTREE-DECOY-当前内容\n') // 未跟踪诱饵
  // 拆道且无收口提交：main 上无 lane 字样的普通提交
  w('gone.md', 'GONE-PLAIN\n'); cm('plain commit without lane ref')
  // 后加文件：收口之后才出现在 main
  w('late.md', 'LATE-ADDED\n'); cm('post-settle add')
  // 二进制+大文件（一分支一 squash 收口）
  git(repo, 'checkout', '-b', 'lane/tBIN')
  writeFileSync(join(repo, 'bin.dat'), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0x0a, 0xff, 0x00])); git(repo, 'add', 'bin.dat')
  w('big.md', 'X'.repeat(2 * 1024 * 1024 + 100))
  cm('bin work')
  git(repo, 'checkout', 'main'); git(repo, 'merge', '--squash', 'lane/tBIN'); cm(SQUASH_MSG('tBIN'))
  return { repo, baseRef, c17 }
}
const fx = mkFixture()

/* meta 夹具：以引擎投影风格（snake）为源，自动派生模块局部契约键（camel，
 * TicketTimeMetaInput）——不硬绑哪边的键名风格，覆盖项写 snake 即可。 */
const tk = (over) => {
  const m = { id: 'tX', status: 'closed', stage_state: 'awaiting', lane: 'worktree', branch: '', base_ref: '', worktree: '', repo_worktrees: [], refs: [], ...over }
  return { ...m, stageState: m.stage_state, baseRef: m.base_ref, repoWorktrees: m.repo_worktrees }
}
async function drive(ticket, path, mode, repo) { return shape.call((repo || fx.repo), reader, ticket, path, mode) }
function isHumanReason(res) {
  return res && res.ok === false && typeof res.reason === 'string' && res.reason.length >= 4 && !/at\s+\S+:\d+/.test(res.reason)
}
function noDecoy(res) { return !JSON.stringify(res).includes('DECOY') }

if (reader) {
  section('G2 形状协商（正例探测：current 读 fixture 工作树现值，与定位器解耦）')
  const probeTk = tk({ id: 'tPROBE', status: 'closed' })
  const errs = []
  for (const [name, call] of SHAPES) {
    try {
      const res = await call(fx.repo, reader, probeTk, 'gone.md', 'current')
      if (res && res.ok === true && res.content === 'GONE-PLAIN\n') { shape = { name, call }; break }
      errs.push(name + ' → ' + JSON.stringify(res).slice(0, 110))
    } catch (e) { errs.push(name + ' → ' + String(e).slice(0, 90)) }
  }
  if (shape.name) { ok(true, '读面调用形状锁定（正例）：' + shape.name) }
  else ok(false, '读面签名/正例协商全灭（签名漂移或 current 面断）——' + errs.join(' | '))
}
if (reader && shape.name) {
  section('G2a settle 正腿（squash body 匹配 / merge subject / 残留分支）')
  let r = await drive(tk({ id: 't260915-17', status: 'closed', branch: 'lane/t260915-17' }), 'seventeen.md', 'settle')
  ok(r.ok === true && r.content === 'SEVENTEEN-SETTLED\n', 'squash 形态：settle 读数=收口提交版本（message body 定位，C2）')
  r = await drive(tk({ id: 't260915-1', status: 'closed', branch: 'lane/t260915-1' }), 'one.md', 'settle')
  ok(r.ok === true && r.content === 'ONE-SETTLED\n', '短 id 不命中长 id 票收口提交（边界正则杀 --grep 子串缺陷）')
  r = await drive(tk({ id: 'tMRG', status: 'verified', branch: 'lane/tMRG' }), 'mrg.md', 'settle')
  ok(r.ok === true && r.content === 'MRG-MERGED\n', 'merge 形态（subject Merge branch lane/<id>）settle 读数正确')

  section('G2b settle fail-closed（在飞 C1 / 拆道无收口 / 路径不在该版本 / 不回落铁律）')
  r = await drive(tk({ id: 'tINF', status: 'dispatched', stage_state: 'running', branch: 'lane/tINF' }), 'inf.md', 'settle')
  ok(isHumanReason(r), '在飞票 settle → 人话点名（分支在场也不给 tip，C1 前置在飞判定）')
  ok(noDecoy(r), '在飞票 settle 响应不含工作树诱饵内容（不回落铁律）')
  r = await drive(tk({ id: 'tGONE', status: 'closed', branch: 'lane/tGONE' }), 'gone.md', 'settle')
  ok(isHumanReason(r), '泳道拆且 main 无本票收口提交 → 人话点名（不断言「还在飞」假因）')
  ok(noDecoy(r), '拆道无收口响应不含工作树内容')
  r = await drive(tk({ id: 'tNOBR', status: 'closed', branch: '' }), 'seventeen.md', 'settle')
  ok(isHumanReason(r) && noDecoy(r), 'branch 字段缺失（legacy/主树道面）→ 人话 fail-closed 不回落')
  r = await drive(tk({ id: 't260915-17', status: 'closed', branch: 'lane/t260915-17' }), 'late.md', 'settle')
  ok(isHumanReason(r), '路径不在该版本（收口后才出现）→ 人话点名')
  ok(noDecoy(r), '路径不在该版本响应不含工作树内容（late.md 现值 LATE-ADDED 不回流）')
  r = await drive(tk({ id: 'tREWORK', status: 'rework', stage_state: 'running', branch: 'lane/t260915-17' }), 'seventeen.md', 'settle')
  ok(isHumanReason(r) && noDecoy(r), 'rework 在飞同样 fail-closed')

  section('G2c base / current（基点定值 / 唯一工作树口径）')
  r = await drive(tk({ id: 't260915-17', status: 'closed', base_ref: fx.baseRef }), 'docs/base.md', 'base')
  ok(r.ok === true && r.content === 'BASE-CONTENT\n', 'base=基点版逐字（开票基线，与在飞无关）')
  r = await drive(tk({ id: 'tNOBASE', status: 'closed', base_ref: '' }), 'docs/base.md', 'base')
  ok(isHumanReason(r), '未登记基点 → 人话点名（不硬造）')
  r = await drive(tk({ id: 'tBADBASE', status: 'closed', base_ref: '0123456789abcdef0123456789abcdef01234567' }), 'docs/base.md', 'base')
  ok(isHumanReason(r), '基点 ref 无效 → 人话点名')
  r = await drive(tk({ id: 't260915-17', status: 'closed' }), 'late.md', 'current')
  ok(r.ok === true && r.content === 'LATE-ADDED\n', 'current=工作树当前版（唯一允许读工作树的口径）')

  section('G2d 二进制 / 大文件封顶')
  r = await drive(tk({ id: 'tBIN', status: 'closed', branch: 'lane/tBIN' }), 'bin.dat', 'settle')
  ok(r.ok !== true || typeof r.content !== 'string' || !r.content.includes('\x00'), '二进制不透传 NUL 乱码冒充时刻版内容')
  r = await drive(tk({ id: 'tBIN', status: 'closed', branch: 'lane/tBIN' }), 'big.md', 'settle')
  const capped = r.ok === true && typeof r.content === 'string' && r.content.length <= 2 * 1024 * 1024 + 65536
  ok(capped && r.truncated === true, '大文件封顶 2MB 且 truncated 标记在场（不静默截断）')

  section('G2e 畸形输入（人话不抛不回落）')
  for (const [p, label] of [['../escape.md', '../ 穿越'], ['/abs.md', '绝对路径'], ['a\\..\\win.md', '反斜杠'], ['', '空路径']]) {
    r = await drive(tk({ id: 't260915-17', status: 'closed' }), p, 'settle')
    ok(isHumanReason(r) && noDecoy(r), '畸形路径（' + label + '）→ 人话 fail-closed')
  }
  r = await drive(tk({ id: 't260915-17', status: 'closed' }), 'seventeen.md', 'bogus-mode')
  ok(isHumanReason(r), '未知 mode → 人话 fail-closed（mode 词表判定）')

  section('G3 真票腿（t260915-05，独立复算对照）')
  try {
    const log = git(REPO_ROOT, 'log', '--first-parent', '--format=%H%x00%B%x1e', 'main')
    const entries = log.split('\x1e').map(s => s.trim()).filter(Boolean)
    const re = /(^|[^0-9-])lane\/t260915-05(?![0-9-])/
    let c05 = ''
    for (const e of entries) { const [h, ...body] = e.split('\x00'); if (re.test(body.join('\x00'))) { c05 = h; break } }
    if (!c05) { ok(false, '真票 t260915-05 收口提交未在本仓 main 定位到（历史不变断言被破坏？）') }
    else {
      const expect = git(REPO_ROOT, 'show', c05 + ':server/engine/dev_lane.py')
      r = await drive(tk({ id: 't260915-05', status: 'closed', branch: 'lane/t260915-05' }), 'server/engine/dev_lane.py', 'settle', REPO_ROOT)
      ok(r.ok === true && r.content === expect, '真票 settle 读数与 git show 逐字相等（' + c05.slice(0, 8) + '，body 匹配定位）')
    }
  } catch (e) { ok(false, '真票腿异常：' + String(e).slice(0, 120)) }
} else if (reader) {
  section('G2/G3 回放腿随形状协商失败全部未跑（FAIL 已计入，无 N/A 腿）')
}

rmSync(fx.repo, { recursive: true, force: true })
console.log('\nSUMMARY pass=' + PASS + ' fail=' + FAIL + ' env_fail=' + ENVFAIL + ' na=' + NA)
process.exit(ENVFAIL > 0 ? 2 : FAIL > 0 ? 1 : 0)
