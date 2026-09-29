#!/usr/bin/env node
// host-session-signals-bench.mjs — t260929-08 验收：守望者三个真信号在真宿主上的内证（不是桩）。
//
// 起一次性隔离 dsh web 台（临时 DSH_HOME + 临时 profile + 自选空闲端口，绝不碰 3099、
// 绝不动用户控制台），在真宿主内加载 bench 插件（bench-plugin-signals/bench-plugin-signals.ts）：
// 它拿真 ctx.sessionController 走完整证据链——
//   list().updatedAt 真推进（executor 推进真源）→ stalled 判定（真 updatedAt + 阈值时钟）
//   → 面板请求账真追加 raised_by 请求 → waiting_on_itself（不等超时）
//   → 引擎探针真 socket online/offline。
// 结果 JSON 落盘 + 退出码承载；orchestrator 负责拆台（SIGTERM→SIGKILL→删临时目录，
// process exit 钩子兜底，全终态）。
//
// 借入 host-prompt-bench.mjs 骨架（fault-mode 取舍清单见 .sandbar 方案 gen1 §Borrowed A：
// teardown 钩子/击杀序/3099 拒跑/ENV_FAIL 三态/日志尾部诊断全部照带；单次 pickFreePort
// 竞态是上游已知行为，照带不修）。环境缺件 = exit 2 + [ENV_FAIL]，绝不假绿。
// 用法：node server/plugins/watchdog/bench/host-session-signals-bench.mjs
import { spawn, spawnSync } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync, readFileSync, readdirSync, realpathSync, rmSync, mkdtempSync, writeFileSync, mkdirSync, symlinkSync, copyFileSync, openSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN_DIR = join(HERE, '..') // server/plugins/watchdog
const REPO_ROOT = join(PLUGIN_DIR, '..', '..', '..')
const REPO_PROFILE = join(REPO_ROOT, 'server', 'profile')

let tmpHome = null
let tmpPanel = null
let benchCwd = null // 顶部置 null：早期 ENV_FAIL 路径 teardown 不踩 TDZ
let child = null
let tornDown = false
function teardown() {
  if (tornDown) return
  tornDown = true
  if (child !== null && child.exitCode === null) { try { child.kill('SIGTERM') } catch {} }
  if (engineSrv !== null) { try { engineSrv.close() } catch {} }
  for (const dir of [tmpHome, tmpPanel, benchCwd]) {  // benchCwd 一并收（gen5 打回：每跑泄漏一个 /tmp/wd-sig-cwd-*）
    if (dir !== null) { try { rmSync(dir, { recursive: true, force: true }) } catch {} }
  }
}
process.on('exit', teardown)
process.on('SIGINT', () => { teardown(); process.exit(130) })
process.on('SIGTERM', () => { teardown(); process.exit(143) })

const envFail = (msg) => { console.error('[ENV_FAIL] ' + msg); teardown(); process.exit(2) }
const fail = (msg) => { console.error('[FAIL] ' + msg); teardown(); process.exit(1) }

function pickFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer()
    srv.listen(0, '127.0.0.1', () => { const p = srv.address().port; srv.close(() => res(p)) })
    srv.on('error', rej)
  })
}

// ── 环境自检（缺任何一件 = ENV_FAIL，不假绿） ─────────────────────────────
let dshCmd = process.env.SANDBAR_BENCH_DSH || join(process.env.HOME || '', '.sandbar', 'dsh-015', 'bin', 'dsh')
if (!existsSync(dshCmd)) {
  const onPath = spawnSync('dsh', ['--version'], { encoding: 'utf8' })
  if (onPath.status !== 0) envFail(`dsh 可执行不在场（${dshCmd} 也不在 PATH）：真宿主 bench 起不来`)
  dshCmd = 'dsh'
}
if (!existsSync(REPO_PROFILE)) envFail(`repo profile 不在场（${REPO_PROFILE}）——bench profile 无复制源`)
const repoNm = join(REPO_PROFILE, 'node_modules')
if (!existsSync(join(repoNm, 'sandbar-watchdog'))) envFail(`profile node_modules 缺 sandbar-watchdog 软链（${repoNm}）——bench 插件依赖它`)

const port = await pickFreePort()
if (port === 3099) envFail('自选端口撞上 3099（用户控制台红线）——不该发生，点名拒跑')

// 子用例分支面（integration/t260929-08 三条包装场景的消费契约）：--leg progress|selflock|engine。
const legIdx = process.argv.indexOf('--leg')
const leg = legIdx >= 0 ? process.argv[legIdx + 1] : 'all'
if (!['progress', 'selflock', 'engine', 'all'].includes(leg)) envFail(`--leg 不认识：${leg}（progress|selflock|engine|all）`)

// engine 分支：SANDBAR_ENGINE_PORT 指向本脚本自管的真实监听口（零 7233/3099 接触；
// 畸形/越界端口 = ENV_FAIL 显式点名——部署承诺面，绝不静默回落）。
let engineSrv = null
let enginePort = null
if (leg === 'engine' || leg === 'all') {
  engineSrv = createServer()
  enginePort = await new Promise((res, rej) => {
    engineSrv.listen(0, '127.0.0.1', () => res(engineSrv.address().port))
    engineSrv.on('error', rej)
  }).catch(() => null)
  if (!enginePort) envFail('engine 分支自管监听口起不来（127.0.0.1 bind 失败）')
}

// ── 组临时 profile（照 host-prompt-bench 同款机制：软链，无 pnpm install） ──
tmpHome = mkdtempSync('/tmp/wd-sig-home-')
tmpPanel = mkdtempSync('/tmp/wd-sig-panel-')
const profDir = join(tmpHome, 'profiles', 'sandbar-bench')
mkdirSync(profDir, { recursive: true })
copyFileSync(join(REPO_PROFILE, 'cordis.yml'), join(profDir, 'cordis.yml'))
copyFileSync(join(REPO_PROFILE, 'package.json'), join(profDir, 'package.json'))
// 端口必须写进 patch（dsh 不吃 web --port——照 stage_console.sh 先例）。
const patch = [
  { id: 'webserver', config: { host: '127.0.0.1', port } },
  { insert: [{ id: 'sandbar-watchdog', name: 'sandbar-watchdog' }, { id: 'sandbar-watchdog-bench-signals', name: 'sandbar-watchdog-bench-signals' }] },
]
writeFileSync(join(profDir, 'cordis.patch.yml'), JSON.stringify(patch, null, 2))
const nm = join(profDir, 'node_modules')
mkdirSync(nm, { recursive: true })
for (const name of readdirSync(repoNm)) {
  try { symlinkSync(realpathSync(join(repoNm, name)), join(nm, name)) } catch { /* 坏软链跳过 */ }
}
symlinkSync(join(PLUGIN_DIR, 'bench', 'bench-plugin-signals'), join(nm, 'sandbar-watchdog-bench-signals'))
benchCwd = mkdtempSync('/tmp/wd-sig-cwd-')
const resultPath = join(tmpHome, 'bench-result.json')

// ── 起台（一次性；端口只由本脚本决定，绝不复用/占用任何既有面） ──
const logPath = join(tmpHome, 'console.log')
const logFd = openSync(logPath, 'a')
// --no-open 同族直修（ebb52c9 修了 host-prompt-bench，漏了本文件——dsh 缺省 openBrowser=true，
// 不加则每跑弹一个随机 token URL 的浏览器窗）。
child = spawn(dshCmd, ['--profile', 'sandbar-bench', '--no-open'], {
  env: {
    ...process.env, DSH_HOME: tmpHome, SANDBAR_BENCH_RESULT: resultPath, SANDBAR_BENCH_CWD: benchCwd,
    SANDBAR_REPO: REPO_ROOT, SANDBAR_WATCHDOG_DIR: join(tmpHome, 'watchdog-projects'),
    SANDBAR_PANEL_DIR: tmpPanel, // 自锁真源：请求账落临时目录（真 fs，不碰 ~/.sandbar/projects）
    SANDBAR_BENCH_LEG: leg,
    ...(enginePort !== null ? { SANDBAR_ENGINE_PORT: String(enginePort) } : {}),
  },
  stdio: ['ignore', logFd, logFd],
})

// 等结果文件（bench 插件写完即退出宿主）；超时 = FAIL + 日志尾部点名。
const DEADLINE_MS = 300_000
const t0 = Date.now()
let tail = ''
while (Date.now() - t0 < DEADLINE_MS) {
  if (child.exitCode !== null) break
  if (existsSync(resultPath)) break
  await new Promise(r => setTimeout(r, 500))
}
try { tail = readFileSync(logPath, 'utf8').slice(-1200) } catch { /* 日志读不到 */ }
if (!existsSync(resultPath)) {
  fail(`bench 插件 ${DEADLINE_MS}ms 内未产出结果（宿主 exit=${child.exitCode}）。console.log 尾部：\n${tail || '（无日志）'}`)
}
let result
try { result = JSON.parse(readFileSync(resultPath, 'utf8')) } catch (e) {
  fail(`结果文件解析失败：${e}。console.log 尾部：\n${tail}`)
}
let passN = 0
let failN = 0
for (const c of result.checks ?? []) {
  console.log(`${c.pass ? 'ok   ' : 'FAIL '} ${c.name}${c.detail ? ` — ${c.detail}` : ''}`)
  if (c.pass) passN += 1; else failN += 1
}
// 输出契约（集成场景消费面）：显式计数行——不可判定=红，不假绿。
console.log(`PASS=${passN} FAIL=${failN}`)
// 反证标记（t260929-08 验收 d）：结论由 bench 插件经 result JSON 结构化通道回传
// （antiproof_ok 字段）——宿主子进程的 stdout 被重定向进临时日志，wrapper grep 不到，
// 契约标记只能由本 orchestrator（自身 stdout）打印（验收打回的跨进程教训）。
if (leg === 'progress' || leg === 'selflock' || leg === 'all') {
  if (result.antiproof_ok === true) console.log('ANTIPROOF=ok')
  else fail('bench 未回传 antiproof_ok=true（反证分支不可判定=红，不假绿）')
}
if (child.exitCode === null) { child.kill('SIGTERM') }
await new Promise(r => setTimeout(r, 1500))
if (child.exitCode === null) { try { child.kill('SIGKILL') } catch {} }
if (!result.ok) fail(`bench 有断言未过（见上）`)
console.log(`PASS host-session-signals-bench[leg=${leg}]: real list().updatedAt progress + stall judge + real-file raised_by self-lock + engine probe, all against a real host session`)
teardown()
process.exit(0)
