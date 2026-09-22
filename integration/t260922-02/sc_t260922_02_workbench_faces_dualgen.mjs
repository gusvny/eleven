/**
 * sc_t260922_02_workbench_faces_dualgen.mjs —— 0.1.5 会话类型面·workbench 三消费面
 * （实时面 readAgentLiveTail / 判据面 judgeSessionLines / 日志面 listAgentLogs，
 * 灰盒 L3，池=ro）。
 *
 * intent（用户可感知）：泳道详情页的「实时动态」「最近操作/会话注记」与
 * agent-usage 判据面对 0.1.5 会话必须认得出（attempt 上屏行、词表 +11）、
 * 拿得到（0.1.1 面板行/最近操作逐字不变=golden 锚）、缺得不静默（词表外
 * 类型 → judge.uncoveredTypes 点名 + 日志面 sessionNote 注记 + attempt 回扫
 * 非空——日志面遇中止形态不再静默空白）。
 *
 * 与 developer L1/L2（workbench/tests 内联对象夹具 UT、smoke 纯函数段）不同
 * 层：本条走真 zstd 档 + 真实 .dsh/sessions 三层树 → readAgentLiveTail/
 * listAgentLogs 公开入口整行为（解压通路+目录解析+行组装 L1 看不到）；0.1.1
 * 面板行逐字 golden 钉死（契约不变的措辞微调不得打破，措辞变更须改 golden=
 * 显式契约变更）。与 t260916-23（双名发现面）/t260917-05 H（发现面 suspect
 * 分流）intent 不同面：本条守类型词表两代差异的呈现与注记。
 *
 * 三态：zstd/python3 缺席、TS 直跑不可用（node 无 type-stripping）=ENV_FAIL
 * exit 2 点名；其余 FAIL exit 1。直跑：node integration/t260922-02/
 * sc_t260922_02_workbench_faces_dualgen.mjs（cwd=仓库根）。
 */
import { execFile } from 'node:child_process'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { makeResults } from './lib_results.mjs'

const P = promisify(execFile)
const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '../..')

const r = makeResults()

async function main() {
  // ---- 环境预检（缺供=ENV_FAIL exit 2 点名，绝不装绿）----
  try {
    await P('zstd', ['--version'])
  } catch {
    r.record('env-zstd', 'env_fail', 'zstd CLI 缺席（会话档解析通路依赖 zstd）')
    return r.summarize()
  }
  let live, logs
  try {
    live = await import(join(REPO, 'server/plugins/workbench/src/host/agent-live.ts'))
    logs = await import(join(REPO, 'server/plugins/workbench/src/host/agent-logs.ts'))
  } catch (e) {
    const msg = String((e && e.message) || e)
    const envLike = /ERR_UNKNOWN_FILE_EXTENSION|ERR_UNSUPPORTED_TYPESCRIPT|TYPESCRIPT_SYNTAX/.test(msg)
    if (envLike) {
      r.record('env-ts-import', 'env_fail', `node 无法直跑 .ts（需 >=22.18 type-stripping）: ${msg.slice(0, 160)}`)
    } else {
      r.record('ts-import', 'fail', `agent-live/agent-logs 导入失败: ${msg.slice(0, 300)}`)
    }
    return r.summarize()
  }
  let tmp
  try {
    tmp = await mkdtemp(join(tmpdir(), 'sc-t260922-02-wb-'))
  } catch (e) {
    r.record('env-tmpdir', 'env_fail', `临时目录不可用: ${String(e && e.message).slice(0, 160)}`)
    return r.summarize()
  }
  let built
  try {
    const out = await P('python3', [join(HERE, 'lib_t260922_02.py'), 'build', tmp], { timeout: 60000 })
    built = JSON.parse(out.stdout.split('\n').find(l => l.startsWith('{')) ?? '{}')
    if (!built || built.ok !== true) throw new Error('build 输出非 ok: ' + out.stdout.slice(0, 200))
  } catch (e) {
    r.record('env-fixture-build', 'env_fail', `python3 夹具构造失败: ${String(e && e.message).slice(0, 200)}`)
    return r.summarize()
  }
  const arc = (k) => built.workspaces[k][0]
  const wsOf = (k) => resolve(arc(k), '../../../../..') // <archive> 在 wt 下 5 层 → wt 根
  const linesOf = async (k) => (await P('zstd', ['-dc', arc(k)])).stdout.split('\n')

  // ---- 1. 实时面：0.1.1 面板行逐字 golden；0.1.5 attempt 上屏 + system/message 有意不上屏 ----
  const t011 = await live.readAgentLiveTail(arc('v011'), 50)
  const GOLDEN_011_EVENTS = [
    { ts: 0, type: 'user', summary: '用户：帮我看一下 t260922-02 的会话面' },
    { ts: 0, type: 'step', summary: '第 1 轮 · 第 1 步开始' },
    { ts: 0, type: 'tool', summary: 'read_file' },
    { ts: 0, type: 'result', summary: '结果：ok: 42 行' },
    { ts: 0, type: 'assistant', summary: '最终回答' },
  ]
  r.check(JSON.stringify(t011.exists ? t011.events : null) === JSON.stringify(GOLDEN_011_EVENTS),
    'live v011 面板行逐字 golden（0.1.1 行为不变锚）',
    `实得 ${JSON.stringify(t011.exists ? t011.events : t011.reason)}`)

  const t015 = await live.readAgentLiveTail(arc('v015'), 50)
  const types015 = t015.exists ? t015.events.map(e => e.type) : []
  r.check(JSON.stringify(types015) === JSON.stringify(['user', 'step', 'attempt', 'retry', 'assistant', 'assistant', 'tool', 'result']),
    'live v015：attempt 上屏行在序（user/step/attempt/retry/assistant×2/tool/result）',
    `实得 ${JSON.stringify(types015)}（exists=${t015.exists} reason=${t015.reason ?? ''}）`)
  const attemptRow = t015.exists ? t015.events.find(e => e.type === 'attempt') : null
  r.check(!!attemptRow && /未转正/.test(attemptRow.summary),
    'live v015：attempt 行人话点名「未转正」',
    `实得 ${JSON.stringify(attemptRow)}`)
  r.check(!t015.exists || !t015.events.some(e => /系统提示词/.test(e.summary)),
    'live v015：system/message 有意不上屏（命名处置钉死，非静默丢失——词表已认、呈现面有选择）')

  // ---- 2. 判据面：双代计数 golden + 未覆盖点名 ----
  const judgeOf = async (k) => {
    const j = live.judgeSessionLines(await linesOf(k))
    const { objs, ...rest } = j
    return rest
  }
  const GOLDEN_011_JUDGE = { blank: false, parsed: 12, knownTypes: 6, usageRecords: 1, usageWithoutKnownKeys: 0, uncoveredTypes: [], uncoveredCount: 0 }
  const j011 = await judgeOf('v011')
  r.check(JSON.stringify(j011) === JSON.stringify(GOLDEN_011_JUDGE),
    'judge v011 全字面 golden（0.1.1 计数/未覆盖恒空）', `实得 ${JSON.stringify(j011)}`)
  const GOLDEN_015_JUDGE = { blank: false, parsed: 26, knownTypes: 12, usageRecords: 2, usageWithoutKnownKeys: 0, uncoveredTypes: [], uncoveredCount: 0 }
  const j015 = await judgeOf('v015')
  r.check(JSON.stringify(j015) === JSON.stringify(GOLDEN_015_JUDGE),
    'judge v015：0.1.5 独有型全认（known=12）且健康零未覆盖', `实得 ${JSON.stringify(j015)}`)
  const ju = await judgeOf('unknown')
  r.check(JSON.stringify(ju.uncoveredTypes) === JSON.stringify(['v9/whatever']) && ju.uncoveredCount === 1,
    'judge unknown：词表外类型 uncoveredTypes 点名 + 计数', `实得 ${JSON.stringify({ u: ju.uncoveredTypes, c: ju.uncoveredCount })}`)

  // ---- 3. 日志面：最近操作 golden + attempt 回扫 + 未覆盖注记 ----
  const logsOf = async (k) => {
    const res = await logs.listAgentLogs(join(wsOf(k), '.suyou'))
    return { lastActivity: res.lastActivity, sessionNote: res.sessionNote ?? null }
  }
  const l011 = await logsOf('v011')
  r.check(l011.lastActivity === 'read_file' && l011.sessionNote === null,
    'logs v011「最近操作」逐字 golden 且无注记', `实得 ${JSON.stringify(l011)}`)
  const l015 = await logsOf('v015')
  r.check(l015.lastActivity === '搜索: SESSION_KNOWN_TYPES',
    'logs v015「最近操作」走 tool/call 分支 golden（既有行为不变）', `实得 ${JSON.stringify(l015)}`)
  const lab = await logsOf('abort')
  r.check(/未转正/.test(lab.lastActivity),
    'logs abort：尾事件=assistant/attempt → 「输出中(未转正)…」回扫非空（禁静默空白）',
    `实得 ${JSON.stringify(lab)}`)
  const lu = await logsOf('unknown')
  r.check(/未覆盖/.test(lu.sessionNote ?? '') && /v9\/whatever/.test(lu.sessionNote ?? ''),
    'logs unknown：sessionNote 显式注记未覆盖类型（禁静默）',
    `实得 ${JSON.stringify(lu)}`)

  return r.summarize()
}

main().catch(e => {
  console.log(`[FAIL] 场景未捕获异常 — ${String((e && e.stack) || e).slice(0, 400)}`)
  console.log('SUMMARY pass=0 fail=1 env_fail=0 na=0')
  process.exit(1)
})
