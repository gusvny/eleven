#!/usr/bin/env node
// host-prompt-bench.mjs — t260929-04 验收⑥：真宿主上的排队简报投递（不是桩）。
//
// 起一次性隔离 dsh web 台（临时 DSH_HOME + 临时 profile + 自选空闲端口，绝不碰 3099、
// 绝不动用户控制台），在真宿主内加载 bench 插件（bench-plugin/bench-plugin.ts）：
// 它拿真 ctx.sessionController 构造 watchdog 的 makeWakeIo，走完整链
//   queue 简报 → accepted → control 流 rpcId 认领（不丢）→ updateQueue remove（消化）
//   → 认领翻 false（已消化窗关闭）。
// 结果 JSON 落盘 + 退出码承载；orchestrator 负责拆台（SIGTERM→SIGKILL→删临时目录，
// process exit 钩子兜底，全终态）。
//
// 三态契约（t260912 口径）：环境缺件 = exit 2 + [ENV_FAIL]（点名缺什么），绝不假绿。
// 用法：node server/plugins/watchdog/bench/host-prompt-bench.mjs
import { spawn, spawnSync } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync, readFileSync, readdirSync, realpathSync, rmSync, mkdtempSync, writeFileSync, mkdirSync, symlinkSync, copyFileSync, openSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN_DIR = join(HERE, '..') // server/plugins/watchdog
const REPO_ROOT = join(PLUGIN_DIR, '..', '..', '..')
const REPO_PROFILE = join(REPO_ROOT, 'server', 'profile')

let tmpHome = null
let child = null
let tornDown = false
function teardown() {
  if (tornDown) return
  tornDown = true
  if (child !== null && child.exitCode === null) { try { child.kill('SIGTERM') } catch {} }
  if (tmpHome !== null) { try { rmSync(tmpHome, { recursive: true, force: true }) } catch {} }
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

// ── 组临时 profile（照 capture-lane.buildTempProfile 同款机制：软链，无 pnpm install） ──
tmpHome = mkdtempSync('/tmp/wd-bench-home-')
const profDir = join(tmpHome, 'profiles', 'sandbar-bench')
mkdirSync(profDir, { recursive: true })
copyFileSync(join(REPO_PROFILE, 'cordis.yml'), join(profDir, 'cordis.yml'))
copyFileSync(join(REPO_PROFILE, 'package.json'), join(profDir, 'package.json'))
// 端口必须写进 patch（`dsh web` 子命令不接受 --profile；dsh 不吃 web --port——
// 照 stage_console.sh 先例：webserver 端口由 profile patch 决定，本脚本自选空闲口写死）。
const patch = [
  { id: 'webserver', config: { host: '127.0.0.1', port } },
  { insert: [{ id: 'sandbar-watchdog', name: 'sandbar-watchdog' }, { id: 'sandbar-watchdog-bench', name: 'sandbar-watchdog-bench' }] },
]
writeFileSync(join(profDir, 'cordis.patch.yml'), JSON.stringify(patch, null, 2))
const nm = join(profDir, 'node_modules')
mkdirSync(nm, { recursive: true })
for (const name of readdirSync(repoNm)) {
  try { symlinkSync(realpathSync(join(repoNm, name)), join(nm, name)) } catch { /* 坏软链跳过 */ }
}
symlinkSync(join(PLUGIN_DIR, 'bench', 'bench-plugin'), join(nm, 'sandbar-watchdog-bench'))
const benchCwd = mkdtempSync('/tmp/wd-bench-cwd-')
const resultPath = join(tmpHome, 'bench-result.json')

// ── 起台（一次性；端口只由本脚本决定，绝不复用/占用任何既有面） ──
// --no-open 必带（260929 宿主实报「浏览器不停跳新窗口」的元凶就是本行缺它：
// dsh 默认 openBrowser=true，起台即把带 token 的地址交给宿主默认浏览器）。
const logPath = join(tmpHome, 'console.log')
const logFd = openSync(logPath, 'a')
child = spawn(dshCmd, ['--profile', 'sandbar-bench', '--no-open'], {
  env: {
    ...process.env, DSH_HOME: tmpHome, SANDBAR_BENCH_RESULT: resultPath, SANDBAR_BENCH_CWD: benchCwd,
    SANDBAR_REPO: REPO_ROOT, SANDBAR_WATCHDOG_DIR: join(tmpHome, 'watchdog-projects'),
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
// 输出契约（sc_wake_real_session_bench 消费面）：显式计数行——不可判定=红，不假绿。
console.log(`PASS=${passN} FAIL=${failN}`)
if (child.exitCode === null) { child.kill('SIGTERM') }
await new Promise(r => setTimeout(r, 1500))
if (child.exitCode === null) { try { child.kill('SIGKILL') } catch {} }
if (!result.ok) fail(`bench 有断言未过（见上）`)
console.log('PASS host-prompt-bench: queued brief delivered into a real host session via ctx.sessionController (accepted → rpcId claimed → digested → claim cleared)')
teardown()
process.exit(0)
