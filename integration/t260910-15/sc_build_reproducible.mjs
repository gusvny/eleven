#!/usr/bin/env node
/**
 * sc_build_reproducible.mjs —— t260910-15：同源码重建逐字节稳定（构建可复现契约）。
 *
 * 用户故事：工单台前端产物 lib/client.{cjs,js} 提交进 git、console 直接加载。
 * 260910 宿主在 t260908-01 的 diff 里被 300+ 行压缩器化妆噪音淹没（「这些奇怪
 * 代码是干什么的」）。用户可感知承诺：同一份 src、经组件公开构建入口
 * （npm run build → 仓内唯一构建脚本）连续构建，产物逐字节稳定、与落仓产物
 * 一致、无计划外副产物文件、mtime 不入产物——review 看到的 lib diff 就是真实
 * 改动。断言腿：
 *   S1 依赖安装走 lockfile（npm ci）；安装因网络/缓存失败=ENV_FAIL（exit 2）
 *      点名尾段，不假红——环境红不诬产品；
 *   S2 同一 node_modules 连续两次构建 → lib 两产物 sha256 逐字节相等（验收①；
 *      装一次建两次=registry 漂移不混入断言）；
 *   S3 构建后 git status 对 lib/ 为空 = 重建产物与落仓产物一致 + 无 map/gzip
 *      等计划外副产物文件（验收②；porcelain 对 untracked 同样计数）；
 *   S4 mtime 注入：改 src 文件 mtime 不改内容 → 第三次构建 → sha256 仍相等
 *      （门禁/证据类断言的 mtime 干扰面：工具链不得把时间戳带进产物）；
 *   S5 终态自证：git status 对 lib/ 仍为空——场景净零副作用，不污染同闸兄弟
 *      场景的判定面。
 *
 * S3 的判红语义：若 HEAD 产物并非锁定工具链可复现（如历史由漂移版本构建），
 * 本腿红=工单要消除的病灶实锤；实施段校准重建（一次性真实 diff）后恒绿。
 *
 * 与 developer L1（workbench/tests/build-determinism.mjs）intent 分工：L1 随
 * 实现交付、不作契约网；本场景是闸内常驻契约网，断言只落在公开接口（npm run
 * build）与用户可感知终态（磁盘产物字节、git 状态），构建脚本内部实现重构不
 * 打破本场景。与 t260903-04-client-bundle-sync（src≡lib 同步面）、
 * t260903-13-workbench-bundle-loads（产物形态合同/可加载面）intent 不同面：
 * 本条守「重建必然逐字节可复现」。
 *
 * 资源口径：同步子进程 wait 全终态、无定时器/fd 残留；产物写入净零（S3/S5
 * 自证）。git 调用全部只读。零 3099/7233 接触。
 * Exit contract（三态，t260904-12 定稿闸内无 SKIP）：末行 SUMMARY pass=N fail=K
 * env_fail=E na=W；fail>0 或全 na → exit 1；env_fail>0 → exit 2。
 */
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, readFileSync, utimesSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
let envFail = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function tail(s, n = 6) {
  return (s || '').split('\n').filter(Boolean).slice(-n).map((l) => '    | ' + l).join('\n')
}
const sha256 = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const wbRel = 'server/plugins/workbench'
const wb = join(root, wbRel)
const cjsPath = join(wb, 'lib/client.cjs')
const jsPath = join(wb, 'lib/client.js')
const entrySrc = join(wb, 'src/client/index.tsx')

const LIB_GIT_PATH = `${wbRel}/lib/`
function libDirty() {
  const out = execFileSync('git', ['status', '--porcelain', '--', LIB_GIT_PATH],
    { cwd: root, encoding: 'utf8' })
  return out.trim()
}

/* S1 依赖安装：lockfile 精确装。失败=环境红（网络/缓存），点名尾段 exit 2。 */
section('S1. npm ci（lockfile 精确装）')
const ci = spawnSync('npm', ['ci', '--no-audit', '--ignore-scripts'],
  { cwd: wb, encoding: 'utf8', timeout: 420000 })
if (ci.error || (ci.status ?? 1) !== 0) {
  envFail++
  console.log(`ENV_FAIL: npm ci 失败（status=${ci.status} err=${ci.error || ''}）——构建可复现场景无法取到锁定依赖树；尾段：\n${tail((ci.stderr || '') + (ci.stdout || ''))}`)
  console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=0`)
  process.exit(2)
}
ok(true, 'npm ci 成功（lockfile 精确装）')

/* 构建一次并取两产物指纹。构建失败（依赖已在位）=产品红。 */
function buildOnce(label) {
  const r = spawnSync('npm', ['run', 'build'], { cwd: wb, encoding: 'utf8', timeout: 300000 })
  if (r.error || (r.status ?? 1) !== 0) {
    failed++
    console.log(`  FAIL ${label} 构建非零退出（status=${r.status}）——依赖在位时构建失败属仓内问题，尾段：\n${tail((r.stderr || '') + (r.stdout || ''))}`)
    return null
  }
  if (!existsSync(cjsPath) || !existsSync(jsPath)) {
    failed++
    console.log(`  FAIL ${label} 构建后产物缺件（cjs=${existsSync(cjsPath)} js=${existsSync(jsPath)}）`)
    return null
  }
  return { cjs: sha256(cjsPath), js: sha256(jsPath) }
}

/* S2 双构建逐字节稳定 */
section('S2. 同 node_modules 连续两次构建 → sha256 相等（验收①）')
const b1 = buildOnce('第 1 次')
const b2 = b1 ? buildOnce('第 2 次') : null
if (b1 && b2) {
  ok(b1.cjs === b2.cjs, `client.cjs 两次构建 sha256 相等\n    ${b1.cjs}`)
  ok(b1.js === b2.js, `client.js  两次构建 sha256 相等\n    ${b1.js}`)
  ok(b1.cjs === b1.js, 'client.cjs ≡ client.js 同体（onSuccess 复制在位）')
} else {
  ok(false, '双构建未完成（见上点名）')
}

/* S3 重建后落仓干净（验收②）＝与落仓产物一致 + 无计划外副产物 */
section('S3. 构建后 git status 对 lib/ 为空（验收②）')
{
  const dirty = libDirty()
  ok(dirty === '', `重建不产生 diff、无 map/gzip 等副产物新文件${dirty ? '：\n    ' + dirty.split('\n').join('\n    ') : ''}`)
}

/* S4 mtime 注入：改 mtime 不改内容 → 重建 sha 不变 */
section('S4. mtime 注入：时间戳不入产物')
if (!b1) {
  console.log('  -- 前置双构建未完成，mtime 腿不重复计分（根因已在 S2 点名）')
} else if (!existsSync(entrySrc)) {
  ok(false, `mtime 注入对象缺失：src/client/index.tsx 不在场`)
} else {
  const before = { cjs: b1.cjs, js: b1.js }
  const now = new Date()
  utimesSync(entrySrc, now, now) // 只动 mtime/atime，内容零变化
  const b3 = buildOnce('mtime 注入后')
  if (b3) {
    ok(b3.cjs === before.cjs && b3.js === before.js,
      'mtime 变更后重建 sha256 不变（工具链不把时间戳带进产物）')
  } else {
    ok(false, 'mtime 注入腿构建未完成（见上点名）')
  }
}

/* S5 终态自证：净零副作用 */
section('S5. 终态：lib/ 回到干净（场景净零副作用）')
{
  const dirty = libDirty()
  ok(dirty === '', `场景结束时 lib/ 仍与落仓一致${dirty ? '：\n    ' + dirty.split('\n').join('\n    ') : ''}`)
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=0`)
process.exit(failed > 0 ? 1 : (envFail > 0 ? 2 : 0))
