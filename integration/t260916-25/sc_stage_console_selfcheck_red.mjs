#!/usr/bin/env node
// t260916-25 场景：自检三态经壳出口透传 + 不造假绿（灰盒 L3，browser-free 池，桩面）。
//
// 用户场景（票面交付②「脚本内跑自检」）：人跑 `stage_console.sh selfcheck` 看到的那个
// 退出码必须可信——台好=0 全绿；台降级=1 红（绝不吞成 0 假绿）；台不可达=2 环境红
// （三态不缺位，t260904-12 契约）。壳是自检的唯一出口，透传断了三态就是装饰。
//
// 用例面：绿对照（正常桩台 exit 0——对照有效性自证，防场景永红自我失效）→ 降级台
//（badapi 桩：workbench API 恒 500，端口/URL 正常）exit 1 → 会话空（删 staged sessions，
// FS 用例红）exit 1 → 台不可达（未起台端口）exit 2。
//
// 三态：stdout 末行 SUMMARY；fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// intent 分界：与 developer L1（断言库 --selftest 进程内桩：500/慢响应/截断 HTML/
// 非 JSON/空 bundle 等解析健壮性）不同层不同面——彼锁库内部，本条锁壳子命令的透传出口
// 与真 HTTP 面的三态语义；与 lifecycle 的 selfcheck-green 用例分面（彼只证绿通）。
// 桩控制台供全五插件名超集，对断言名集的 R1 校准免疫。

import {
  SCRIPT_PATH,
  pickFreePort, makeWorkspace, rmRf, writeSrcHome, makeStubRoot,
  runStep, pidsMatching, killPid,
  existsSync, readdirSync, join,
} from './lib_stage_fixture.mjs'
import { rmSync } from 'node:fs'

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

const workspaces = []
async function bootConsole(mode) {
  const port = await pickFreePort()
  if (!port) return null
  const ws = makeWorkspace(`selfchk-${mode}`)
  workspaces.push(ws)
  const stubRoot = makeStubRoot(ws, { port, mode })
  const src = join(ws, 'src-home')
  const home = join(ws, 'stage-home')
  writeSrcHome(src, { creds: 'k: v\n', settings: 'm: f\n', sessionNames: ['--legacy--'] })
  const args = ['--dsh-root', stubRoot, '--port', String(port), '--home', home, '--src-home', src, '--no-open']
  const up = await runStep(['start', ...args])
  return { ws, port, home, up }
}

try {
  // 绿对照：正常桩台
  const g = await bootConsole('normal')
  if (!g || g.up.code !== 0) {
    record('绿对照 exit0', 'fail', g ? `start code=${g.up.code}（对照台起不来=场景自身面，先查夹具）` : '高位口耗尽')
  } else {
    const sc = await runStep(['selfcheck', '--home', g.home, '--port', String(g.port)])
    record('绿对照 exit0', sc.code === 0, `code=${sc.code}（对照有效性自证）`)
    // 会话空（目录在、数据空）：FS 用例产品红。刺激物必须无歧义——lib 分类学实测为
    // 「整目录缺失=前提红 2（探针实证）/数据空=产品红 1」，本用例钉后者（假绿捕获面）。
    for (const n of readdirSync(join(g.home, 'sessions'))) {
      rmSync(join(g.home, 'sessions', n), { recursive: true, force: true })
    }
    const sc2 = await runStep(['selfcheck', '--home', g.home, '--port', String(g.port)])
    record('会话空=红不假绿', sc2.code === 1, `code=${sc2.code}（清空 staged sessions 数据后 FS 用例必须产品红；自检不得静默回填突变台面）`)
  }

  // 降级台：badapi 桩（workbench API 恒 500）
  const b = await bootConsole('badapi')
  if (!b || b.up.code !== 0) {
    record('降级台=红透传', 'fail', b ? `badapi 台 start code=${b.up.code}（降级台仍须可起：端口/URL 正常才谈自检红）` : '高位口耗尽')
  } else {
    const sc = await runStep(['selfcheck', '--home', b.home, '--port', String(b.port)])
    record('降级台=红透传', sc.code === 1, `code=${sc.code}（API 500 → exit 1，绝不吞成 0）`)
  }

  // 台不可达：干净前提（已组装 home：凭据/会话在位）+ 未起台端口 → 环境红出口。
  // 前提必须干净——否则 FS 红混入会把「纯环境红应 exit 2」的判据污染成 1。
  const port = await pickFreePort()
  if (!port) {
    record('不可达=环境红', 'env_fail', '高位口耗尽——环境面')
  } else {
    const ws = makeWorkspace('selfchk-dead')
    workspaces.push(ws)
    const stubRoot = makeStubRoot(ws, { port, mode: 'normal' })
    const src = join(ws, 'src-home')
    const home = join(ws, 'stage-home')
    writeSrcHome(src, { creds: 'k: v\n', settings: 'm: f\n', sessionNames: ['--legacy--'] })
    const pr = await runStep(['prepare', '--dsh-root', stubRoot, '--port', String(port),
      '--home', home, '--src-home', src])
    const sc = await runStep(['selfcheck', '--home', home, '--port', String(port)])
    record('不可达=环境红', pr.code === 0 && sc.code === 2,
      `prepare=${pr.code} selfcheck=${sc.code}（三态出口契约：检测层已打 ENV_RED 标签，纯环境红聚合退出码必须=2，不冒充产品红/绿）`)
  }
} finally {
  for (const ws of workspaces) for (const p of (pidsMatching(ws) ?? [])) await killPid(p.pid)
  for (const ws of workspaces) rmRf(ws)
}
summarize()
