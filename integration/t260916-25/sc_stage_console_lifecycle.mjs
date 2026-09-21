#!/usr/bin/env node
// t260916-25 场景：stage 控制台一键主链路 + 终态回收（灰盒 L3，browser-free 池）。
//
// 用户场景（票面验收）：干净环境一条命令起 staging（独立端口/独立 DSH_HOME），自检全绿、
// 打印带 token 的 URL 与人工测试清单路径；stop 后端口释放、无残留进程。本场景用
// dsh 启动面测试桩（假 dsh-root + catch-all 桩控制台）把这条链在套件内跑通——零 docker、
// 零网络（npm 安装路）、零真 dsh、零 3099 接触；真版本（0.1.5-rc.2）全链归方案 S3/S4
// 实弹与 acceptance 走查，套件只锚 harness 自身的编排契约。
//
// 用例面：L0 交付物在位 → start（exit 0 + 带 token URL + 只读警示随 URL 同出）→
// staged home 组装面（profile 端口补丁/五插件软链/依赖软链/凭据/会话落位）→
// selfcheck 子命令 exit 0 → url 子命令再出 URL+警示 → checklist 子命令出清单 →
// start 幂等二跑（不二次起台）→ stop（端口释放+pidfile 清+残留进程=0）→ stop 幂等。
//
// 三态（t260912 契约）：stdout 末行 SUMMARY；fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现段落地前红属预期（TDD 信号：L0 交付物缺失=fail 点名），arbitrate/merge 期必须绿。
//
// intent 分界：异常终态（hang 超时/死 pid/僵 pidfile 误杀/URL 静默）归
// sc_stage_console_fault_paths；拒收与红线防呆归 sc_stage_console_guardrails；
// prepare 组装语义与凭据刷新分档归 sc_stage_console_prepare_refresh；自检三态透传归
// sc_stage_console_selfcheck_red。本条只锁 happy 主链 + 幂等 + 终态回收。

import {
  SCRIPT_PATH, ASSERT_LIB_PATH, PLUGIN_LINK_NAMES,
  pickFreePort, makeWorkspace, rmRf, writeSrcHome, makeStubRoot,
  runStep, listening, waitPort, pidsMatching, killPid, findPidFile, psAvailable,
  existsSync, readdirSync, readFileSync, join,
} from './lib_stage_fixture.mjs'

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

// ---------------------------------------------------------------- L0 交付物在位
if (!existsSync(SCRIPT_PATH)) {
  record('L0 交付物在位', 'fail', `${SCRIPT_PATH} 不存在——实现段未落地（TDD 预期红）；后续用例全部跳过`)
  summarize()
}
if (!existsSync(ASSERT_LIB_PATH)) {
  record('L0 交付物在位', 'fail', `${ASSERT_LIB_PATH} 不存在——selfcheck 的被调库缺失（TDD 预期红）；后续用例全部跳过`)
  summarize()
}
record('L0 交付物在位', 'pass', `${SCRIPT_PATH} + ${ASSERT_LIB_PATH} 在位`)
if (!psAvailable()) {
  record('进程表可观测', 'env_fail', 'ps 被环境拒绝——残留/幂等断言不可进行（fail-closed，不空转假绿）')
  summarize()
}

// ---------------------------------------------------------------- 夹具
const port = await pickFreePort()
if (!port) {
  record('端口可得', 'env_fail', '3511-3549 高位口全被占——环境面，不造假红')
  summarize()
}
const ws = makeWorkspace('lifecycle')
const stubRoot = makeStubRoot(ws, { port, mode: 'normal' })
const srcHome = join(ws, 'src-home')
const home = join(ws, 'stage-home')
const CREDS_V1 = 'providers:\n  fixture-key: sk-fixture-v1\n'
writeSrcHome(srcHome, {
  creds: CREDS_V1,
  settings: 'model: fixture-model\n',
  sessionNames: ['--fixture-legacy-a--', '--fixture-legacy-b--'],
})
const urlRe = new RegExp(`http://(127\\.0\\.0\\.1|localhost):${port}/\\?token=`)
const baseArgs = ['--dsh-root', stubRoot, '--port', String(port), '--home', home, '--src-home', srcHome, '--no-open']
try {
  // ---------------------------------------------------------------- start 主用例
  const up = await runStep(['start', ...baseArgs])
  record('start exit0', up.code === 0, `code=${up.code} stderr=${up.stderr.slice(0, 160)}`)
  record('start 出带 token URL', urlRe.test(up.stdout), '票面实测形态 http://127.0.0.1:<port>/?token=…')
  record('start 出只读警示', /只读|生产|警示/.test(up.stdout), '票面④：stage 连生产 Temporal/注册表，警示须随 URL 到达使用者')

  // ---------------------------------------------------------------- staged home 组装面
  const patchPath = join(home, 'profiles', 'sandbar-stage', 'cordis.patch.yml')
  let patchOk = false
  let patchNote = `${patchPath} 不存在`
  if (existsSync(patchPath)) {
    const patch = readFileSync(patchPath, 'utf8')
    const hasPort = new RegExp(`port:\\s*${port}\\b`).test(patch)
    const noProd = !/port:\s*3099\b/.test(patch)
    patchOk = hasPort && noProd
    patchNote = hasPort && noProd ? `port=${port} 且 3099 清零` : `hasPort=${hasPort} noProd=${noProd}`
  }
  record('profile 端口补丁', patchOk, patchNote + '（sed 失守=真台抢 3099 前半程，红线面）')
  const linkDir = join(home, 'profiles', 'sandbar-stage', 'node_modules')
  const linkMissing = PLUGIN_LINK_NAMES.filter((n) => !existsSync(join(linkDir, n)))
  record('五插件软链在位', linkDir ? linkMissing.length === 0 : false,
    linkMissing.length ? `缺 ${linkMissing.join(',')}` : `${PLUGIN_LINK_NAMES.length} 条全部可解析`)
  const depLinkOk = existsSync(join(home, 'profiles', 'node_modules'))
  record('profile 依赖软链在位', depLinkOk, 'profiles/node_modules → dsh-root/node_modules（票面「照此固化」捷径）')
  record('凭据落位', existsSync(join(home, '.credentials.yaml')), 'prepare 从 src-home 拷入')
  const sessDir = join(home, 'sessions')
  const sessCount = existsSync(sessDir) ? readdirSync(sessDir).length : 0
  record('旧代会话落位', sessCount >= 1, `sessions 目录数=${sessCount}（夹具拷入 2）`)

  // ---------------------------------------------------------------- selfcheck / url / checklist
  const sc = await runStep(['selfcheck', '--home', home, '--port', String(port)])
  record('selfcheck 全绿 exit0', sc.code === 0, `code=${sc.code} 尾部=${(sc.stdout + sc.stderr).slice(-200)}`)
  const urlCmd = await runStep(['url', '--home', home, '--port', String(port)])
  record('url 子命令再出 URL+警示', urlCmd.code === 0 && urlRe.test(urlCmd.stdout) && /只读|生产|警示/.test(urlCmd.stdout),
    `code=${urlCmd.code}（警示到达面：拿 URL 的人未必看启动终端）`)
  const ck = await runStep(['checklist'])
  record('checklist 子命令出清单', ck.code === 0 && /会话|用量|主题|console/.test(ck.stdout),
    `code=${ck.code} 输出字节=${ck.stdout.length}`)

  // ---------------------------------------------------------------- 幂等与终态回收
  const before = pidsMatching(ws)
  const up2 = await runStep(['start', ...baseArgs])
  const after = before === null ? null : pidsMatching(ws)
  if (before === null || after === null) {
    record('start 幂等二跑', 'env_fail',
      `code=${up2.code} 进程表中途失效（头部可观测门已过）——监听计数半边不可判定，env_fail 不崩不当 0`)
  } else {
    record('start 幂等二跑', up2.code === 0 && urlRe.test(up2.stdout) && after.length === before.length,
      `code=${up2.code} 监听进程 ${before.length}→${after.length}（不二次起台）`)
  }

  const stop = await runStep(['stop', '--home', home, '--port', String(port)])
  const portFree = await waitPort(port, false, 5000)
  const residue = pidsMatching(ws)
  const pidLeft = findPidFile(home)
  if (residue === null) {
    record('stop 终态回收', 'env_fail',
      `code=${stop.code} 端口释放=${portFree} 进程表中途失效——残留半边不可判定（pidfile=${pidLeft ? pidLeft.path : '无'}）`)
  } else {
    record('stop 终态回收', stop.code === 0 && portFree && residue.length === 0 && !pidLeft,
      `code=${stop.code} 端口释放=${portFree} 残留=${residue.length} pidfile残留=${pidLeft ? pidLeft.path : '无'}（KI-077「台没拆」家族回归面）`)
  }
  const stop2 = await runStep(['stop', '--home', home, '--port', String(port)])
  record('stop 幂等再跑', stop2.code === 0, `code=${stop2.code}`)
} finally {
  for (const p of (pidsMatching(ws) ?? [])) await killPid(p.pid)
  rmRf(ws)
}
summarize()
