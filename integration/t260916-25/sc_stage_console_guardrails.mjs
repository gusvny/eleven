#!/usr/bin/env node
// t260916-25 场景：stage 控制台红线与防呆拒收（灰盒 L3，browser-free 池，桩面零真台）。
//
// 用户场景（票面交付⑤+只读护栏的运行时行为半边）：「绝对不碰 3099 生产 console」——
// 脚本对禁区端口、被占端口、危险 home、畸形参数必须拒在先、零副作用：不落盘、不起进程、
// 不误伤占用者。本场景全部用例都是「拒收干净」断言，被拒的 start 绝不允许留下任何痕迹。
//
// 用例面：端口禁区三连（3099/7233/8233 非零+stage home 不落盘+零残留）→ 缺省口被占
// 即拒不抢不杀（decoy 存活+输出点名端口）→ home 防呆两形（--home=~/.dsh 且真 home
// 零污染；--home==--src-home）→ 畸形参数全拒（--port abc/0/99999、start 缺
// --version|--dsh-root、未知子命令）。
//
// 三态：stdout 末行 SUMMARY；fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// intent 分界：与 lifecycle（happy 主链）/fault_paths（异常终态回收）/
// prepare_refresh（组装语义）/selfcheck_red（三态透传）分面——本条只锁「拒收干净」。
// 与 verify.yaml guard-3099-redline 机械闸不同层：彼扫 bin/server 源码字面
// （pkill|kill -9 × 3099），本条测运行时行为，互不替代。
// KI 对齐：KI-036「测试通道直连 3099」家族（红线纪律的运行时回归面）。

import {
  SCRIPT_PATH, FORBIDDEN_PORTS,
  pickFreePort, makeWorkspace, rmRf, writeSrcHome, makeStubRoot,
  runStep, pidsMatching, killPid, psAvailable,
  existsSync, join,
} from './lib_stage_fixture.mjs'
import { createServer } from 'node:net'
import { homedir, tmpdir } from 'node:os'
import { mkdtempSync } from 'node:fs'

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
  record('进程表可观测', 'env_fail', 'ps 被环境拒绝——零副作用断言不可进行（fail-closed，不空转假绿）')
  summarize()
}

const ws = makeWorkspace('guard')
const stubRoot = makeStubRoot(ws, { port: 3510 + 0, mode: 'normal' }) // 桩只作合法参数来源，本场景从不真起台
const srcHome = join(ws, 'src-home')
writeSrcHome(srcHome, { creds: 'k: v\n', settings: 'm: f\n' })
const offenders = []
let psBlind = false // ps 中途失效=残留半边不可判定（t260912 三态：归 env_fail，不崩不当 0）
try {
  // ---------------------------------------------------------------- 端口禁区三连
  for (const bad of [3099, 7233, 8233]) {
    const home = join(ws, `refused-${bad}`)
    const r = await runStep(['start', '--dsh-root', stubRoot, '--port', String(bad),
      '--home', home, '--src-home', srcHome, '--no-open'])
    const plist = pidsMatching(ws)
    if (plist === null) { psBlind = true; break }
    const clean = !existsSync(home) && plist.length === 0
    if (!(r.code !== 0 && clean)) offenders.push(`port=${bad} code=${r.code} home落盘=${existsSync(home)}`)
  }
  if (psBlind) {
    record('端口禁区三连拒收且零副作用', 'env_fail',
      `ps 中途失效（头部可观测门已过）——已拒端口 ${offenders.length ? '前有 offender：' + offenders.join('；') : '暂无'}，残留半边不可判定`)
  } else {
    record('端口禁区三连拒收且零副作用', offenders.length === 0,
      offenders.length ? offenders.join('；') : '3099/7233/8233 全部非零退出+home 不落盘+零进程残留（护栏先于落盘/spawn）')
  }

  // ---------------------------------------------------------------- 被占即拒不抢不杀
  const port = await pickFreePort()
  if (!port) {
    record('被占即拒不抢不杀', 'env_fail', '高位口耗尽——环境面')
  } else {
    const decoy = createServer()
    let decoyUp = false
    decoy.once('error', () => { decoyUp = false })
    decoyUp = await new Promise((done) => decoy.listen(port, '127.0.0.1', () => done(true)))
    const home = join(ws, 'refused-occupied')
    const r = await runStep(['start', '--dsh-root', stubRoot, '--port', String(port),
      '--home', home, '--src-home', srcHome, '--no-open'], { timeoutMs: 30000 })
    const decoyAlive = decoy.listening
    decoy.close()
    record('被占即拒不抢不杀',
      r.code !== 0 && decoyAlive && (r.stdout + r.stderr).includes(String(port)) && !existsSync(home),
      `code=${r.code} decoy存活=${decoyAlive} 输出点名端口=${(r.stdout + r.stderr).includes(String(port))} home落盘=${existsSync(home)}（拒收文案走 stderr——die_usage >&2，实弹 260918 实证 stdout 恒空）`)
  }

  // ---------------------------------------------------------------- home 防呆两形
  const userHome = join(homedir(), '.dsh')
  const probe = join(userHome, 'profiles', 'sandbar-stage')
  const probeBefore = existsSync(probe) // 生产 home 若已有同名 profile（意外环境），污染断言降级 na
  const rHome = await runStep(['start', '--dsh-root', stubRoot, '--port', '3548',
    '--home', userHome, '--src-home', srcHome, '--no-open'])
  const probeAfter = existsSync(probe)
  record('--home=真 home 拒收且零污染', rHome.code !== 0 && (probeBefore ? true : !probeAfter),
    `code=${rHome.code} 真home profile ${probeBefore ? '先已存在(污染断言降na)' : probeAfter ? '被新建=污染!' : '保持缺席'}`)
  const rEq = await runStep(['start', '--dsh-root', stubRoot, '--port', '3548',
    '--home', srcHome, '--src-home', srcHome, '--no-open'])
  record('--home==--src-home 拒收', rEq.code !== 0, `code=${rEq.code}（自我吞并拒收：stage home 不能吃掉凭据真源）`)

  // ---------------------------------------------------------------- 畸形参数全拒
  const badCmds = [
    ['start', '--dsh-root', stubRoot, '--port', 'abc', '--home', join(ws, 'b1'), '--src-home', srcHome],
    ['start', '--dsh-root', stubRoot, '--port', '0', '--home', join(ws, 'b2'), '--src-home', srcHome],
    ['start', '--dsh-root', stubRoot, '--port', '99999', '--home', join(ws, 'b3'), '--src-home', srcHome],
    ['start', '--home', join(ws, 'b4'), '--src-home', srcHome, '--port', '3547'], // 缺 --version|--dsh-root
    ['frobnicate'], // 未知子命令
  ]
  const notRejected = []
  for (let i = 0; i < badCmds.length; i++) {
    // eslint-disable-next-line no-await-in-loop
    const r = await runStep(badCmds[i], { timeoutMs: 30000 })
    if (r.code === 0) notRejected.push(`#${i}(${badCmds[i][0]} ${badCmds[i].slice(1, 3).join('')}…) exit0`)
  }
  record('畸形参数全拒', notRejected.length === 0,
    notRejected.length ? `被放行的坏输入：${notRejected.join('；')}` : '5 类坏输入（非数字/0/越界端口、缺版本或 root、未知子命令）全部非零退出')
} finally {
  for (const p of (pidsMatching(ws) ?? [])) await killPid(p.pid)
  rmRf(ws)
}
summarize()
