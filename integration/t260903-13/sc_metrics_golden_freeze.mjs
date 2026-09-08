#!/usr/bin/env node
/**
 * sc_metrics_golden_freeze.mjs —— t260903-13：度量响应形状对串行基线冻结。
 *
 * 用户故事：度量视图（time/delivery/token/health × 7d/30d/all）的响应形状
 * 在 t260903-09 修复与并发改造后不得静默漂移——tests/golden_serial/ 基线的
 * 逐字节比对（剔除 generated_at/cache.computed_at）是唯一冻结面。tests/golden.mjs
 * 被 run_tests.mjs 的 HELPERS 排除、全仓此前不存在任何自动跑点
 * （t260903-13 review 实锤的孤儿入口），本场景补上自动比对点，并机械守护两条纪律：
 *   1) 比对后 golden_serial/ 零 git 脏——--record 重录基线换绿必然在此现形；
 *   2) tests/ 无 stub-*.json 运行时残留（golden.mjs 自建自删的会话桩）。
 *
 * 判定口径（行为级，不钉案例数）：exit 0 + 存在逐案一致行 + 零「不一致/缺失」；
 * 基线案例面随实现窗口枚举自然扩展，不设数量快照锚。
 * 纯本地：SANDBAR_METRICS_DIR 走系统临时目录，零端口、零 3099、零网络。
 * Exit contract（三态，定稿 §7.3 闸内无 SKIP）：末行 SUMMARY pass=N fail=K
 * env_fail=E na=W；fail>0 或全 na→exit 1，env_fail>0→exit 2。
 */
import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const testsDir = join(repo, 'server/plugins/workbench/tests')

section('1. golden 基线逐字节比对（当前实现 vs golden_serial）')
const p = spawnSync('node', ['golden.mjs', '--compare'], { cwd: testsDir, encoding: 'utf8', timeout: 600000 })
const out = (p.stdout || '') + (p.stderr || '')
if (p.error) {
  ok(false, `golden.mjs 拉起失败：${p.error.message}`)
} else {
  ok(p.status === 0, `golden.mjs --compare exit=0${p.status !== 0 ? `（实得 ${p.status}）\n${out.split('\n').filter(Boolean).slice(-8).map(l => '    ' + l).join('\n')}` : ''}`)
  const agreed = (out.match(/compare \S+ 一致/g) || []).length
  const mismatch = (out.match(/不一致|缺失/g) || []).length
  ok(agreed > 0, `逐案一致行存在（${agreed} 案）`)
  ok(mismatch === 0, '无不一致/缺失')
}

section('2. 纪律机械守护（比对不得污染基线）')
const dirty = spawnSync('git', ['status', '--porcelain', '--', 'server/plugins/workbench/tests/golden_serial'], { cwd: repo, encoding: 'utf8' })
ok((dirty.stdout || '').trim() === '', `golden_serial/ 零 git 脏（无重录）${(dirty.stdout || '').trim() ? '：' + dirty.stdout.trim() : ''}`)
let leftovers = []
try { leftovers = readdirSync(testsDir).filter(f => /^stub-.*\.json$/.test(f)) } catch { /* tests 目录缺席由上方 exit 非 0 已红 */ }
ok(leftovers.length === 0, `tests/ 无 stub 残留${leftovers.length ? '：' + leftovers.join(', ') : ''}`)

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
process.exit(failed > 0 ? 1 : 0)
