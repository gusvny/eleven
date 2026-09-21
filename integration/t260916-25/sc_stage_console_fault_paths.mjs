#!/usr/bin/env node
// t260916-25 场景：stage 控制台故障路注入与资源回收对抗（灰盒 L3，browser-free 池，桩面）。
//
// 用户场景（票面验收负半边）：「停脚本后端口释放、无残留进程」不只对 happy 路成立——
// 僵 pidfile、死 pid、start 超时、URL 静默四条异常终态里，脚本都必须：不误杀无辜、
// 自己起的进程自己收、报错响亮点名（报错必须精确），绝不静默吞或留悬空进程。
//
// 用例面：pidfile 记账在位（探不到=fail 点名「安全用例不可注入」，不猜位置）→
// 僵 pidfile 误杀防护（无辜 sleep 进程 pid 入 pidfile→stop 必须让它活下来）→
// 死 pid pidfile（stop 幂等清理不误报）→ start 超时路（hang 桩+CAP=4s：CAP 内非零
// 退出+响亮点名+自起 stub 零残留）→ URL 静默路（nolog 桩：端口在听但 URL 行缺：
// 非零响亮+零残留，绝不静默无 URL 假成）。
//
// 三态：stdout 末行 SUMMARY；fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// intent 分界：happy 主链/幂等归 lifecycle；拒收面归 guardrails；本条全是异常终态。
// KI 对齐：KI-077（「只杀 node 进程、拆台钩子没跑」→ 台面残骸堆积）同族回归面；
// review R3（spawn 的每个终态都要有回收）与 R5（console.log 畸形/缺失/迟到须响亮）落地钉。

import {
  SCRIPT_PATH,
  pickFreePort, makeWorkspace, rmRf, writeSrcHome, makeStubRoot,
  runStep, waitPort, pidsMatching, killPid, findPidFile, pidAlive, psAvailable,
  writeFileSync, existsSync, join,
} from './lib_stage_fixture.mjs'
import { spawn } from 'node:child_process'

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (typeof status === 'boolean') status = status ? 'pass' : 'fail' // 用例断言自然产出布尔：归一为三态词，不弱化语义
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const f = results.filter(r => r.status === 'fail').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

if (!existsSync(SCRIPT_PATH)) {
  record('L0 交付物在位', 'fail', `${SCRIPT_PATH} 不存在——实现段未落地（TDD 预期红）；后续用例全部跳过`)
  summarize()
}
record('L0 交付物在位', 'pass', SCRIPT_PATH)
if (!psAvailable()) {
  record('进程表可观测', 'env_fail', 'ps 被环境拒绝——残留/误杀断言不可进行（fail-closed，不空转假绿）')
  summarize()
}

const workspaces = []
function newWs(label) { const ws = makeWorkspace(label); workspaces.push(ws); return ws }
function baseArgs(ws, stubRoot, srcHome, home, port) {
  return ['--dsh-root', stubRoot, '--port', String(port), '--home', home, '--src-home', srcHome, '--no-open']
}

try {
  // ---------------------------------------------------------------- A/B：pidfile 面对抗（先起一次真台拿记账面）
  const portA = await pickFreePort()
  if (!portA) {
    record('pidfile 记账在位', 'env_fail', '高位口耗尽——环境面')
  } else {
    const wsA = newWs('fault-a')
    const stubA = makeStubRoot(wsA, { port: portA, mode: 'normal' })
    const srcA = join(wsA, 'src-home')
    const homeA = join(wsA, 'stage-home')
    writeSrcHome(srcA, { creds: 'k: v\n', settings: 'm: f\n', sessionNames: ['--legacy-a--'] })
    const argsA = baseArgs(wsA, stubA, srcA, homeA, portA)
    const up = await runStep(['start', ...argsA])
    const pf = up.code === 0 ? findPidFile(homeA) : null
    record('pidfile 记账在位', !!pf,
      pf ? pf.path : `start code=${up.code}；stage home 下未发现「纯 pid 内容且 pid 存活」文件——pidfile 位置在契约面之外，误杀防护用例不可注入`)

    if (pf) {
      // 子用例 A：僵 pidfile 误杀防护——无辜进程（cmdline 不含 stage home）必须活下来
      await runStep(['stop', '--home', homeA, '--port', String(portA)])
      const decoy = spawn('sleep', ['120'])
      writeFileSync(pf.path, String(decoy.pid))
      const r = await runStep(['stop', '--home', homeA, '--port', String(portA)], { timeoutMs: 30000 })
      const decoyAlive = pidAlive(decoy.pid)
      record('僵 pidfile 不误杀', r.code === 0 && decoyAlive,
        `code=${r.code} 无辜进程存活=${decoyAlive}（「只杀自己 pidfile 且 ps 核对 cmdline」契约的对抗面）`)
      try { decoy.kill('SIGKILL') } catch { /* 已退 */ }
      // pidfile 清理面（僵 pidfile 被 stop 消化）
      const pfAfter = findPidFile(homeA)
      record('stop 消化僵 pidfile', !pfAfter || pfAfter.pid !== decoy.pid, pfAfter ? `仍在：${pfAfter.path}` : '已清')

      // 子用例 B：死 pid pidfile——stop 幂等清理不误报
      const deadChild = spawn('true')
      const deadPid = deadChild.pid
      await new Promise((r) => deadChild.on('close', r))
      if (pidAlive(deadPid)) {
        record('死 pid pidfile 幂等清理', 'na', '死 pid 被系统即时复用（系统状态用例，本环境不可注入）')
      } else {
        writeFileSync(pf.path, String(deadPid))
        const r2 = await runStep(['stop', '--home', homeA, '--port', String(portA)], { timeoutMs: 30000 })
        record('死 pid pidfile 幂等清理', r2.code === 0, `code=${r2.code}（对已死 pid 的记账：清理即可，不误报在役不崩）`)
      }
    }
  }

  // ---------------------------------------------------------------- C：start 超时路（hang 桩）
  const portC = await pickFreePort()
  if (!portC) {
    record('start 超时自回收', 'env_fail', '高位口耗尽——环境面')
  } else {
    const wsC = newWs('fault-c')
    const stubC = makeStubRoot(wsC, { port: portC, mode: 'hang' })
    const srcC = join(wsC, 'src-home')
    const homeC = join(wsC, 'stage-home')
    writeSrcHome(srcC, { creds: 'k: v\n', settings: 'm: f\n' })
    const r = await runStep(['start', ...baseArgs(wsC, stubC, srcC, homeC, portC)],
      // 预算=runStep 缺省 90s（其余子用例同值）：CAP=4 空载实测 7s 自回收（260921 复现），
      // 跑批重载下 lsof 轮询/子进程调度秒级放大曾破人为压缩的 25s 被兜底误杀——
      // 预算只是机械余量非断言；断言仍锁「脚本自己退出+响亮输出+零残留」不变。
      { timeoutMs: 90000, env: { SANDBAR_STAGE_CONSOLE_UP_CAP_S: '4' } })
    const residue = pidsMatching(wsC)
    if (residue === null) {
      record('start 超时自回收', 'env_fail',
        `code=${r.code} 兜底击杀=${r.killed} 进程表中途失效——残留半边不可判定，env_fail 不崩不当 0`)
    } else {
      record('start 超时自回收',
        r.code !== 0 && !r.killed && (r.stdout + r.stderr).trim().length > 0 && residue.length === 0,
        `code=${r.code} 兜底击杀=${r.killed} 输出非空=${(r.stdout + r.stderr).trim().length > 0} 残留=${residue.length}`
        + '（CAP=4s 内非零退出+响亮点名+自己起的 hang 桩自己收；兜底击杀=true=CAP 旋钮不生效或超时路挂死）')
    }
  }

  // ---------------------------------------------------------------- D：URL 静默路（nolog 桩）
  const portD = await pickFreePort()
  if (!portD) {
    record('URL 静默响亮红', 'env_fail', '高位口耗尽——环境面')
  } else {
    const wsD = newWs('fault-d')
    const stubD = makeStubRoot(wsD, { port: portD, mode: 'nolog' })
    const srcD = join(wsD, 'src-home')
    const homeD = join(wsD, 'stage-home')
    writeSrcHome(srcD, { creds: 'k: v\n', settings: 'm: f\n' })
    const r = await runStep(['start', ...baseArgs(wsD, stubD, srcD, homeD, portD)],
      { timeoutMs: 30000, env: { SANDBAR_STAGE_CONSOLE_UP_CAP_S: '8' } })
    const residue = pidsMatching(wsD)
    if (residue === null) {
      record('URL 静默响亮红', 'env_fail',
        `code=${r.code} 输出非空=${(r.stdout + r.stderr).trim().length > 0} 进程表中途失效——残留半边不可判定，env_fail 不崩不当 0`)
    } else {
      record('URL 静默响亮红',
        r.code !== 0 && (r.stdout + r.stderr).trim().length > 0 && residue.length === 0,
        `code=${r.code} 输出非空=${(r.stdout + r.stderr).trim().length > 0} 残留=${residue.length}`
        + '（端口在听但 URL 行缺：绝不静默无 URL 假成，也不留悬空台）')
    }
    const freed = await waitPort(portD, false, 4000)
    record('URL 静默路端口释放', freed, `端口 ${portD} 释放=${freed}`)
  }
} finally {
  for (const ws of workspaces) for (const p of (pidsMatching(ws) ?? [])) await killPid(p.pid)
  for (const ws of workspaces) rmRf(ws)
}
summarize()
