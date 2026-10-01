#!/usr/bin/env node
// t260916-25 场景：stage home 组装口径 + 凭据刷新/会话稳定的幂等分档（灰盒 L3，browser-free）。
//
// 用户场景：stage 是给人做升级验收的台面——凭据必须是真源的**最新**快照（旧凭据跑出的
// auth 失败会被误读成「升级 break」），而拷入的旧代会话是**测试数据**，重跑 prepare
// 绝不能删改。两条幂等语义必须分档：凭据/settings=真源强制刷新；sessions=已存在则复用不重拷。
//（措辞注记：会话幂等语义只用中文表述——integration/ 树的 .py/.mjs 对英文跳过词
// 字面零残留（t260904-12 防线，禁词含大小写与一切连字形态），写注释时同样不得引述。）
//
// 用例面：prepare 组装（profile 端口补丁含所选口且 3099 清零/五插件软链/依赖软链/凭据落位）
// → 凭据 v1→v2 强制刷新（「目标已存在即跳过」形态在此即红）→ settings 同口径 →
// 旧会话字节不变（不删不毁不重拷）→ prepare 幂等重跑 exit 0。
//
// 三态：stdout 末行 SUMMARY；fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// intent 分界：与 lifecycle 分面（彼锁 start 一键链，本条锁 prepare 组装语义与刷新分档）。
// KI 对齐：KI-016「_copy_creds 目标已存在即跳过→凭据快照永不刷新」（open）同族回归钉——
// 新 harness 重新实现复制语义时不得把同一病灶带进来（review R2 硬条件的机械执行点）。

import {
  SCRIPT_PATH, PLUGIN_LINK_NAMES,
  runWithFreshPort, makeWorkspace, rmRf, writeSrcHome,
  runStep, pidsMatching, killPid,
  existsSync, readFileSync, readdirSync, writeFileSync, join,
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

if (!existsSync(SCRIPT_PATH)) {
  record('L0 交付物在位', 'fail', `${SCRIPT_PATH} 不存在——实现段未落地（TDD 预期红）；后续用例全部跳过`)
  summarize()
}
record('L0 交付物在位', 'pass', SCRIPT_PATH)

const ws = makeWorkspace('prep')
const src = join(ws, 'src-home')
const home = join(ws, 'stage-home')
const CREDS_V1 = 'providers:\n  fixture-key: sk-fixture-v1\n'
const CREDS_V2 = 'providers:\n  fixture-key: sk-fixture-v2\n  new-provider: sk-new\n'
const SET_V1 = 'model: fixture-model\n'
const SET_V2 = 'model: fixture-model-v2\n'
const SESSION_BODY_V1 = 'v0 legacy transcript line A\n'
writeSrcHome(src, {
  creds: CREDS_V1, settings: SET_V1,
  sessionNames: ['--fixture-legacy-a--', '--fixture-legacy-b--'],
  sessionBody: SESSION_BODY_V1,
})
// 260930 直修（宿主令，并发竞态）：端口不再"探一次钉死"——并发下别的场景会先探后占，
// 而被测脚本对"端口已被占用"是硬拒 exit 2。故每一步都走 runWithFreshPort：撞口换口重做，
// 后续断言一律用**实际生效的那个口**（p1.port / p1.stubRoot）。
const prepArgsFor = (port, stubRoot) => ['prepare', '--dsh-root', stubRoot, '--port', String(port), '--home', home, '--src-home', src]
const stagedCreds = () => readFileSync(join(home, '.credentials.yaml'), 'utf8')
const stagedSettings = () => readFileSync(join(home, 'settings.yaml'), 'utf8')
const stagedSessionA = () => readFileSync(join(home, 'sessions', '--fixture-legacy-a--', 'session.jsonl'), 'utf8')

try {
  const p1 = await runWithFreshPort(ws, {
    buildArgs: prepArgsFor,
    onRetry: (p, i) => console.log(`[retry] 端口 ${p} 被并发占走——换口重做（第 ${i + 1} 次）`),
  })
  if (!p1.port) {
    record('端口可得', 'env_fail', '3511-3599 高位口全被占/耗尽——环境面')
    summarize()
  }
  const port = p1.port
  const prepArgs = prepArgsFor(port, p1.stubRoot)
  const kitOk = p1.code === 0
    && existsSync(join(home, '.credentials.yaml'))
    && existsSync(join(home, 'profiles', 'sandbar-stage', 'cordis.patch.yml'))
    && PLUGIN_LINK_NAMES.every((n) => existsSync(join(home, 'profiles', 'sandbar-stage', 'node_modules', n)))
    && existsSync(join(home, 'profiles', 'node_modules'))
    && (readdirSync(join(home, 'sessions')).length >= 2)
  record('prepare 组装 exit0', kitOk, `code=${p1.code}（profile 拷贝/端口补丁/五软链/依赖软链/凭据/会话一次到位）`)

  const patch = existsSync(join(home, 'profiles', 'sandbar-stage', 'cordis.patch.yml'))
    ? readFileSync(join(home, 'profiles', 'sandbar-stage', 'cordis.patch.yml'), 'utf8') : ''
  record('profile 端口补丁口径',
    new RegExp(`port:\\s*${port}\\b`).test(patch) && !/port:\s*3099\b/.test(patch),
    `含所选口=${new RegExp(`port:\\s*${port}\\b`).test(patch)} 3099 清零=${!/port:\\s*3099\\b/.test(patch)}（sed 失守=真台抢 3099 前半程，红线面）`)

  record('凭据 v1 初拷', p1.code === 0 && stagedCreds() === CREDS_V1, '与 src-home 逐字节一致')
  const p2pre = stagedSessionA()

  // 凭据刷新钉（KI-016 同族）：src 改 v2 → 再 prepare → staged 必须跟到 v2
  writeFileSync(join(src, '.credentials.yaml'), CREDS_V2)
  writeFileSync(join(src, 'settings.yaml'), SET_V2)
  const p2 = await runStep(prepArgs)
  record('凭据强制刷新（KI-016 钉）', p2.code === 0 && stagedCreds() === CREDS_V2,
    `code=${p2.code} staged=src v2？${stagedCreds() === CREDS_V2}（「目标已存在即跳过」形态在此即红）`)
  record('settings 强制刷新', stagedSettings() === SET_V2, '与凭据同口径：配置真源每次 prepare 重拷')

  // 会话数据稳定钉：src 改已有会话内容 → 再 prepare → staged 旧会话字节不变
  writeFileSync(join(src, 'sessions', '--fixture-legacy-a--', 'session.jsonl'), '被篡改的源会话\n')
  const p3 = await runStep(prepArgs)
  record('旧会话数据稳定（已存在则复用）', p3.code === 0 && stagedSessionA() === p2pre,
    `code=${p3.code} staged 字节不变=${stagedSessionA() === p2pre}（测试数据不随 prepare 刷新被删改）`)

  const p4 = await runStep(prepArgs)
  record('prepare 幂等重跑', p4.code === 0, `code=${p4.code}`)
} finally {
  for (const p of (pidsMatching(ws) ?? [])) await killPid(p.pid)
  rmRf(ws)
}
summarize()
