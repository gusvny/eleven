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
 *   S5 泳道内显式腿（t260911-06/KI-073 验收 a/b）：重建产物 == HEAD committed
 *      产物（显式 sha256 对比 + 失败时 diff 首 40 行点名）。判定前提=构建输入
 *      （src/config/双 lock/构建脚本/兄弟包 knowledge|providers 的 src）全部与
 *      HEAD 同批；implement 期工作树输入常带票内未落盘改动 → na 属预期时点
 *      （arbitrate/merge 期输入已落盘必可判）；na 记入 na=W 不假绿，全 na →
 *      exit 1（t260904-12 exit contract）。套件跑在泳道时 root 即泳道树，
 *      本腿即「泳道内」重建一致性；
 *   S6 入口唯一性腿（t260911-06/KI-073）：构建实际解析的 tsdown/rolldown 版本
 *      （构建 stdout 版本留痕）≡ lockfile 锁定版本 ≡ node_modules 安装版本
 *      ——绕开 npm ci 的入口（npx 回落/陈旧 node_modules/别的全局 tsdown）
 *      在此点名，而不是以 4 行压缩器写法抖动的形式漏进 diff。判定核心纯函数
 *      化并先红绿自证（合成不符样必咬、畸形 lockfile/坏 JSON 缺条目 FAIL 点名
 *      不 crash，同 sc_toolchain_pinned「合成锁样必咬」先例）；
 *   S7 终态自证：git status 对 lib/ 仍为空——场景净零副作用，不污染同闸兄弟
 *      场景的判定面。
 *
 * S3 的判红语义：若 HEAD 产物并非锁定工具链可复现（如历史由漂移版本构建），
 * 本腿红=工单要消除的病灶实锤；实施段校准重建（一次性真实 diff）后恒绿。
 *
 * 与 developer L1（workbench/tests/build-determinism.mjs）intent 分工：L1 随
 * 实现交付、不作契约网；本场景是闸内常驻契约网，断言只落在公开接口（npm run
 * build）与用户可感知终态（磁盘产物字节、git 状态），构建脚本内部实现重构不
 * 打破本场景。与 t260903-04-client-bundle-sync（src≡lib 同步面）、
 * t260903-13-workbench-bundle-loads（产物形态合同/可加载面）、
 * t260911-06-artifact-provenance（票型触发的闸侧归因点名：手改/未同批重建/
 * 工具链漂移三分）intent 不同面：本条守「重建必然逐字节可复现」这一常驻回归面。
 *
 * 资源口径：同步子进程 wait 全终态、无定时器/fd 残留；产物写入净零（S3/S7
 * 自证）；HEAD blob 借位临时目录在 finally 里强制回收（正常/抛错都走清理）。
 * git 调用全部只读。零 3099/7233 接触。
 * Exit contract（三态，t260904-12 定稿闸内无 SKIP）：末行 SUMMARY pass=N fail=K
 * env_fail=E na=W；fail>0 或全 na → exit 1；env_fail>0 → exit 2。
 */
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
let envFail = 0
let naCount = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function na(label) {
  naCount++
  console.log(`  na ${label}`)
}
function section(t) { console.log(`\n== ${t}`) }
function tail(s, n = 6) {
  return (s || '').split('\n').filter(Boolean).slice(-n).map((l) => '    | ' + l).join('\n')
}
const sha256 = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')
const sha256Buf = (buf) => createHash('sha256').update(buf).digest('hex')

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
  console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${naCount}`)
  process.exit(2)
}
ok(true, 'npm ci 成功（lockfile 精确装）')

/* 版本留痕行解析（纯函数）：先剥 ANSI 色彩码再取版本。套件执行环境（CI/
 * FORCE_COLOR 族变量在位）下 tsdown 横幅带色，裸正则会把 escape 吃进版本串——
 * 260911 仲裁实锤：解析得 '0.22.2\x1b[39m' ≠ lockfile '0.22.2'、rolldown null，
 * 判红文案「构建绕开锁定工具链」与事实相反（报错必须精确纪律）。 */
function bannerVersions(raw) {
  const out = String(raw).replace(/\x1b\[[0-9;]*[A-Za-z]/g, '')
  return {
    tsdownVer: (out.match(/tsdown v(\d[^\s]*)/) || [])[1] || null,
    rolldownVer: (out.match(/powered by rolldown v(\d[^\s]*)/) || [])[1] || null,
  }
}

/* 构建一次并取两产物指纹 + 构建实际解析的工具链版本（S6 用）。
 * 构建失败（依赖已在位）=产品红。 */
function buildOnce(label) {
  const r = spawnSync('npm', ['run', 'build'], { cwd: wb, encoding: 'utf8', timeout: 300000 })
  if (r.error || (r.status ?? 1) !== 0) {
    failed++
    console.log(`  FAIL ${label} 构建非零退出（status=${r.status}）——依赖在位时构建失败属仓内问题，尾段：\n${tail((r.stderr || '') + (r.stdout || ''))}`)
    return null
  }
  if (!existsSync(cjsPath) || !existsSync(jsPath)) {
    failed++
    console.log(`  FAIL ${label} 构建后产物缺件（cjs=${existsSync(cjsPath)} js=${existsSync(jsPath)}）——build-client.sh 仅在失败路径拆旧产物，成功退出后缺件=构建未产出，尾段：\n${tail((r.stderr || '') + (r.stdout || ''))}`)
    return null
  }
  const v = bannerVersions((r.stdout || '') + (r.stderr || ''))
  return {
    cjs: sha256(cjsPath),
    js: sha256(jsPath),
    // 「构建实际解析的版本」取自构建进程自身的版本留痕行（tsdown 横幅），
    // 而非仅 node_modules 状态——后者被 npm ci 归一化，测不出绕过入口的构建。
    tsdownVer: v.tsdownVer,
    rolldownVer: v.rolldownVer,
  }
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

/* S3 重建后落仓干净（验收②）＝与落仓产物一致 + 无计划外副产物
 * （两意图并锚一条 porcelain：porcelain 对 untracked 同样计数，副产物新文件
 * 与「产物 ≠ 落仓」都表现为非空；显式 sha 对比在 S5 分腿）。 */
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

/* S5 泳道内显式腿（KI-073 验收 a/b）：重建 == HEAD committed（显式 sha 对比）。
 * na 时点口径见文件头注：构建输入与 HEAD 非同批（implement 期常态）→ na，
 * arbitrate/merge 期必可判；产物不在 HEAD=FAIL（产物未入版本库是产品红）。 */
const BUILD_INPUT_PATHS = [
  `${wbRel}/build-client.sh`,
  `${wbRel}/tsdown.config.ts`,
  `${wbRel}/package.json`,
  `${wbRel}/package-lock.json`,
  `${wbRel}/pnpm-lock.yaml`,
  `${wbRel}/src/`,
  'server/plugins/knowledge/src/',
  'server/plugins/providers/src/',
]
/* HEAD blob 只读取：exit 非 0（路径不在 HEAD）返回 null。 */
function headBlob(rel) {
  const r = spawnSync('git', ['show', `HEAD:${rel}`],
    { cwd: root, encoding: 'buffer', timeout: 60000, maxBuffer: 64 * 1024 * 1024 })
  return r.status === 0 ? r.stdout : null
}
/* HEAD 字节 vs 磁盘产物的 unified diff 首 40 行（判红证据；临时目录 finally 强制回收）。 */
function headDiff40(headBytes, diskPath) {
  const tmp = mkdtempSync(join(tmpdir(), 'sc-repro-head-'))
  try {
    const headCopy = join(tmp, 'head-blob')
    writeFileSync(headCopy, headBytes)
    const r = spawnSync('git', ['diff', '--no-index', '-U1', '--', headCopy, diskPath],
      { cwd: root, encoding: 'utf8', timeout: 60000 })
    return (r.stdout || '').split('\n').slice(0, 40).join('\n').slice(0, 4000)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
}
section('S5. 泳道内重建 == HEAD committed 产物（显式 sha 对比，KI-073）')
{
  const dirtyInputs = execFileSync('git', ['status', '--porcelain', '--', ...BUILD_INPUT_PATHS],
    { cwd: root, encoding: 'utf8' }).trim()
  if (!b1) {
    na('前置构建未完成，S5 不判（根因已在 S2 点名）')
  } else if (dirtyInputs !== '') {
    na(`构建输入与 HEAD 非同批（票内改动未落盘属 implement 期常态；arbitrate/merge 期输入已落盘必可判）：\n    ${dirtyInputs.split('\n').join('\n    ')}`)
  } else {
    for (const [rel, diskPath, got] of [
      [`${wbRel}/lib/client.cjs`, cjsPath, b1.cjs],
      [`${wbRel}/lib/client.js`, jsPath, b1.js],
    ]) {
      const head = headBlob(rel)
      if (head === null) {
        ok(false, `${rel} 不在 HEAD（产物未入版本库，S5 无对比基线）`)
        continue
      }
      const headSha = sha256Buf(head)
      if (headSha === got) {
        ok(true, `${rel} 泳道内重建 == HEAD committed（${got.slice(0, 12)}…）`)
      } else {
        ok(false, `${rel} 泳道内重建 != HEAD committed——压缩器写法抖动/手改实锤（KI-073 病灶），diff 首 40 行：\n${headDiff40(head, diskPath)}`)
      }
    }
  }
}

/* S6 入口唯一性（KI-073）：构建实际解析版本 ≡ lockfile 锁定 ≡ node_modules 安装。
 * 判定核心纯函数化；先红绿自证（同版必绿 / 漂移必咬 / 畸形 FAIL 点名不 crash），
 * 再量真树。 */
function chainMismatch({ lock, installed, actual }) {
  const bad = []
  const verRe = /^\d+\.\d+\.\d+/
  for (const tool of ['tsdown', 'rolldown']) {
    const l = lock?.[tool]
    const i = installed?.[tool]
    const a = actual?.[tool]
    if (typeof l !== 'string' || !verRe.test(l)) bad.push(`${tool} lockfile 锁定版本缺失/畸形：${JSON.stringify(l) ?? 'undefined'}`)
    if (typeof i !== 'string' || !verRe.test(i)) bad.push(`${tool} node_modules 安装版本缺失/畸形：${JSON.stringify(i) ?? 'undefined'}`)
    if (typeof a !== 'string' || !verRe.test(a)) bad.push(`${tool} 构建实际解析版本缺失/畸形（构建 stdout 无版本留痕）：${JSON.stringify(a) ?? 'undefined'}`)
    else {
      if (l !== i) bad.push(`${tool} node_modules 安装 ${i} ≠ lockfile 锁定 ${l}（依赖树未按 lockfile 安装）`)
      if (l !== a) bad.push(`${tool} 构建实际解析 ${a} ≠ lockfile 锁定 ${l}（构建绕开了锁定工具链=KI-073 漂移入口）`)
    }
  }
  return bad
}
section('S6. 入口唯一性：构建解析版本 ≡ lockfile ≡ node_modules（KI-073）')
{
  const good = chainMismatch({
    lock: { tsdown: '0.22.2', rolldown: '1.1.5' },
    installed: { tsdown: '0.22.2', rolldown: '1.1.5' },
    actual: { tsdown: '0.22.2', rolldown: '1.1.5' },
  })
  ok(good.length === 0, '判定器红绿自证：三连同版锁样必绿')
  const bite = chainMismatch({
    lock: { tsdown: '0.22.2', rolldown: '1.1.5' },
    installed: { tsdown: '0.22.2', rolldown: '1.1.5' },
    actual: { tsdown: '0.22.14', rolldown: '1.2.0' },
  })
  ok(bite.length === 2, `判定器负腿自证：实际解析漂移必咬恰 2 处（实际 ${bite.length} 处）`)
  const malformed = chainMismatch({
    lock: { tsdown: null, rolldown: undefined },
    installed: {},
    actual: { tsdown: 'garbage!', rolldown: '' },
  })
  ok(malformed.length === 6, `判定器畸形输入自证：缺条目/坏版本 FAIL 点名不 crash（实际 ${malformed.length} 处）`)
  const ansi = bannerVersions('ℹ tsdown v0.22.2\x1b[39m powered by rolldown v1.1.5\x1b[39m')
  ok(ansi.tsdownVer === '0.22.2' && ansi.rolldownVer === '1.1.5',
    `判定器色彩码自证：带 ANSI 横幅剥出干净版本（实际 ${JSON.stringify(ansi)}）`)
  const absentBanner = bannerVersions('无版本留痕面的构建输出')
  ok(absentBanner.tsdownVer === null && absentBanner.rolldownVer === null,
    '判定器自证：无横幅 → 双 null（交由 chainMismatch FAIL 点名，不误报漂移方向）')

  let lock
  try {
    const lockJson = JSON.parse(readFileSync(join(wb, 'package-lock.json'), 'utf8'))
    lock = {
      tsdown: lockJson?.packages?.['node_modules/tsdown']?.version ?? null,
      rolldown: lockJson?.packages?.['node_modules/rolldown']?.version ?? null,
    }
  } catch (e) {
    lock = { tsdown: `<package-lock.json 不可解析：${e.message}>`, rolldown: null }
  }
  const installed = {}
  for (const tool of ['tsdown', 'rolldown']) {
    try {
      installed[tool] = JSON.parse(readFileSync(join(wb, `node_modules/${tool}/package.json`), 'utf8'))?.version ?? null
    } catch (e) {
      installed[tool] = `<node_modules/${tool}/package.json 不可读：${e.message}>`
    }
  }
  if (!b1) {
    na('前置构建未完成，构建实际解析版本无从留痕（根因已在 S2 点名）')
  } else {
    const bad = chainMismatch({ lock, installed, actual: { tsdown: b1.tsdownVer, rolldown: b1.rolldownVer } })
    ok(bad.length === 0, `真树三连一致：tsdown ${b1.tsdownVer} / rolldown ${b1.rolldownVer}${bad.length ? '：\n    ' + bad.join('\n    ') : ''}`)
  }
}

/* S7 终态自证：净零副作用 */
section('S7. 终态：lib/ 回到干净（场景净零副作用）')
{
  const dirty = libDirty()
  ok(dirty === '', `场景结束时 lib/ 仍与落仓一致${dirty ? '：\n    ' + dirty.split('\n').join('\n    ') : ''}`)
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${naCount}`)
process.exit(failed > 0 ? 1 : (passed === 0 && naCount > 0 ? 1 : (envFail > 0 ? 2 : 0)))
