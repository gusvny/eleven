#!/usr/bin/env node
/**
 * build-determinism.mjs —— 票 t260910-15：构建产物抖动钉死的确定性自测。
 *
 * 目标：同源码 + 同工具版本（tsdown 0.22.2 三处锁定）+ 同参数（全部来自
 * tsdown.config.ts）→ 重建产物逐字节稳定。断言面：
 *
 *   A. 验收①：同一份 src 连续两次完整构建，lib/client.cjs 与 lib/client.js 的
 *      sha256 两次相等，且每次构建内 cjs≡js（onSuccess 复制完整性，半新产物=红）。
 *   B. 验收②：构建后 `git status --porcelain` 对 server/plugins/workbench/lib/
 *      为空——src 未改时重建不产生 diff（产物=仓内 tracked 字节）。
 *   C. 锁定负锁：package.json 的 specifier 无 ^/~ 且恰 0.22.2；package-lock.json
 *      与 pnpm-lock.yaml 的 tsdown 均恰 0.22.2；三份锁定面无 0.22.14 残留
 *      （旧 pnpm 锁漂移版本，复燃入口的负锁）。
 *   D. 形状自检（畸形输入桩，不靠真外部源）：锁定解析辅助对 caret/tilde/空串/
 *      坏 JSON/缺字段等 malformed 输入显式拒，不误绿。
 *
 * 网络纪律（docs/testing-guide.md 单测硬律①：结果不得依赖网络）：node_modules/tsdown
 * 在位时零网络完成全部断言；缺席时尝试一次 npm ci（--ignore-scripts，本依赖树
 * hasInstallScript=0），失败=ENV_FAIL 点名环境原因 exit 2，不做假红不静默降级。
 * 装/建解耦：安装只装一次，两次构建共用同一份 node_modules（控制变量：registry
 * 漂移不混入确定性断言）。
 *
 * 资源纪律：子进程全走 spawnSync（同步等待全终态，无 fd/定时器残留）；构建产物
 * 与仓内 tracked 字节一致（A/B 绿即零残留），测试不改 src、不写 .git。
 * 退出契约（integration/README.md）：stdout 末行 `SUMMARY pass=N skip=M fail=K`；
 * fail>0 → exit 1；环境缺席 → exit 2。
 */

import { readFileSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const workbench = dirname(dirname(fileURLToPath(import.meta.url))) // server/plugins/workbench
const repo = resolve(workbench, '..', '..')
const libDir = join(workbench, 'lib')
const ARTIFACTS = ['client.cjs', 'client.js']
const PINNED = '0.22.2'
const DRIFT_LEGACY = '0.22.14'

// ---- 纯函数辅助（D 段对它们做畸形输入桩自检）----

/** 精确版本钉死判定：恰为 PINNED 才算钉死；^/~ 范围、空、缺字段一律不钉。 */
function isPinnedExact(spec) {
  return typeof spec === 'string' && spec.trim() === PINNED
}

/** 解析 package-lock（lockfileVersion 3）里的 tsdown 实锁版本；坏形返回 null。 */
function parseNpmLockTsdown(text) {
  let json
  try { json = JSON.parse(text) } catch { return null }
  const entry = json && json.packages && json.packages['node_modules/tsdown']
  return entry && typeof entry.version === 'string' ? entry.version : null
}

/** 解析 pnpm-lock（lockfileVersion 9）importers 段的 tsdown specifier+version；坏形返回 null。 */
function parsePnpmLockTsdown(text) {
  const m = text.match(/tsdown:\s*\n\s*specifier:\s*(\S+)\s*\n\s*version:\s*(\S+)/)
  return m ? { specifier: m[1], version: m[2] } : null
}

function sha256(buf) { return createHash('sha256').update(buf).digest('hex') }

// ---- D 段：畸形输入桩自检（先于真文件断言，解析器坏形不误绿）----

section('D. 畸形输入桩自检（解析辅助，不靠真外部源）')
ok(isPinnedExact(PINNED) === true, '桩 "0.22.2" 判定为已钉死')
ok(isPinnedExact('^0.22.2') === false, '桩 "^0.22.2"（caret 范围）判为未钉死')
ok(isPinnedExact('~0.22.2') === false, '桩 "~0.22.2"（tilde 范围）判为未钉死')
ok(isPinnedExact('0.22.14') === false, '桩 "0.22.14"（漂移版本）判为未钉死')
ok(isPinnedExact('') === false, '桩 空串判为未钉死')
ok(isPinnedExact(undefined) === false, '桩 缺字段（undefined）判为未钉死')
ok(parseNpmLockTsdown('not json {{{') === null, '桩 坏 JSON 的 package-lock 解析得 null 不抛穿')
ok(parseNpmLockTsdown('{"packages":{}}') === null, '桩 缺 node_modules/tsdown 条目解析得 null')
ok(parsePnpmLockTsdown('importers:\n  .:\n    devDependencies:\n      tsdown:\n        specifier: ^0.22.2\n') === null,
  '桩 pnpm 锁缺 version 行解析得 null（半截文件不误绿）')

// ---- 环境自检 + 依赖就位（装/建解耦，网络只在依赖缺席时出现一次）----

section('ENV. 依赖就位（node_modules/tsdown 在位则零网络）')
const tsdownBin = join(workbench, 'node_modules', '.bin', 'tsdown')
if (!existsSync(tsdownBin)) {
  console.log('  node_modules/tsdown 缺席，尝试一次 npm ci（--ignore-scripts）…')
  const ci = spawnSync('npm', ['ci', '--no-audit', '--ignore-scripts'], { cwd: workbench, encoding: 'utf8' })
  if (ci.error || ci.status !== 0) {
    console.error(`ENV_FAIL npm ci 失败（离线且缓存不可用？）：${ci.error || ('exit=' + ci.status)}`)
    console.error('SUMMARY pass=' + passed + ' skip=0 fail=0 (env-fail)')
    process.exit(2)
  }
}
const tsdownVer = spawnSync(tsdownBin, ['--version'], { cwd: workbench, encoding: 'utf8' })
const verLine = (tsdownVer.stdout || '').trim().split('\n').filter(Boolean).pop() || ''
ok(verLine.includes('tsdown/' + PINNED), `本机 tsdown 恰 ${PINNED}（实测：${verLine || '无输出'}）`)

// ---- A 段：同源码连续两次构建，sha256 逐字节相等 ----

function buildOnce(tag) {
  const r = spawnSync(tsdownBin, ['-c', 'tsdown.config.ts'], { cwd: workbench, encoding: 'utf8' })
  if (r.error || r.status !== 0) {
    console.error(`FAIL 构建（第 ${tag} 次）未完成：${r.error || (r.stderr || '').slice(-400) || 'exit=' + r.status}`)
    console.error('SUMMARY pass=' + passed + ' skip=0 fail=' + (failed + 1))
    process.exit(1)
  }
  const digests = {}
  for (const name of ARTIFACTS) {
    const p = join(libDir, name)
    if (!existsSync(p)) {
      console.error(`FAIL 构建产物缺失：lib/${name}（第 ${tag} 次）`)
      console.error('SUMMARY pass=' + passed + ' skip=0 fail=' + (failed + 1))
      process.exit(1)
    }
    digests[name] = sha256(readFileSync(p))
  }
  ok(digests['client.cjs'] === digests['client.js'], `第 ${tag} 次构建 cjs≡js 逐字节一致（onSuccess 复制完整）`)
  return digests
}

section('A. 同源码连续两次构建逐字节相同（验收①）')
const d1 = buildOnce(1)
const d2 = buildOnce(2)
for (const name of ARTIFACTS) {
  ok(d1[name] === d2[name], `lib/${name} 两次构建 sha256 相等（${d1[name].slice(0, 16)}…）`)
}

// ---- B 段：src 未改时重建后 git status 对 lib/ 为空（验收②）----

section('B. 重建后 lib 无 git diff（验收②）')
const relLib = 'server/plugins/workbench/lib'
const st = spawnSync('git', ['status', '--porcelain', '--', relLib], { cwd: repo, encoding: 'utf8' })
ok(!st.error && st.status === 0 && (st.stdout || '').trim() === '',
  `git status --porcelain -- ${relLib} 为空${(st.stdout || '').trim() ? `（实测：${st.stdout.trim().split('\n').join(' | ')}）` : ''}`)

// ---- C 段：锁定负锁（三处锁定面 + 漂移版本残留扫描）----

section('C. tsdown 版本三处钉死 + 漂移残留负锁')
const pkgText = readFileSync(join(workbench, 'package.json'), 'utf8')
let pkg = null
try { pkg = JSON.parse(pkgText) } catch { /* 坏形走下方断言点名 */ }
const spec = pkg && pkg.devDependencies && pkg.devDependencies.tsdown
ok(isPinnedExact(spec), `package.json specifier 恰 "${PINNED}" 无 ^/~（实测：${String(spec)}）`)

const npmVer = parseNpmLockTsdown(readFileSync(join(workbench, 'package-lock.json'), 'utf8'))
ok(npmVer === PINNED, `package-lock.json 实锁 tsdown==${PINNED}（实测：${String(npmVer)}）`)

const pnpmParsed = parsePnpmLockTsdown(readFileSync(join(workbench, 'pnpm-lock.yaml'), 'utf8'))
ok(!!pnpmParsed && pnpmParsed.specifier === PINNED && pnpmParsed.version === PINNED,
  `pnpm-lock.yaml specifier/version 均 ${PINNED}（实测：${pnpmParsed ? pnpmParsed.specifier + '→' + pnpmParsed.version : '解析失败'}）`)

for (const f of ['package.json', 'package-lock.json', 'pnpm-lock.yaml']) {
  const text = readFileSync(join(workbench, f), 'utf8')
  ok(!text.includes(DRIFT_LEGACY), `${f} 无漂移版本 ${DRIFT_LEGACY} 残留`)
}

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
