#!/usr/bin/env node
/**
 * integration/t260922-06/sc_t260922_06_resume_seam_faces.mjs
 * —— headless-resume 插件装配面：fake-dsh 桩缝驱动 node.ts 全链（t260922-06 场景①，池=ro）。
 *
 * intent（灰盒 L2，守护的用户可感知行为——seam 矩阵 #5 resume 专项的插件半边）：
 *   dsh 0.1.1→0.1.5 的真接缝是形状面（Session.events 快照数组被移除，stock 改走
 *   eventAt(SessionSeq(seq)) 半开区间）；寻址口径两代无漂移（自定义 id 即真源）。
 *   用户可感知承诺（票面验收①②③的插件侧）：
 *   - 同 id 续上：stderr 一行「已恢复会话 <id>」，任务跑完 exit 0，自定义 id 原样
 *     进 agents.resume（不造 uuid、不查映射表）；
 *   - 没续上就大声说：「回落新建同 id 会话」「同 id 新建仍失败…改用全新会话 id
 *     （上下文不可恢复…）」逐级显式宣告，绝不让用户以为续上了（票面验收③禁静默）；
 *   - 形状漂移响亮点名不崩栈：agents.resume/create 返回缺 .agent、会话既无 eventAt
 *     也无 events 数组、v3 seq 缺口 → 「dsh: headless-resume: …」点名退出，绝不复现
 *     `events is not iterable` 裸崩栈（票面实证的真崩点形状，验收②）；
 *   - 0.1.1 legacy 路径（events 数组、dsh-session 无 SessionSeq 导出）行为不变（回归锚）。
 *
 * high-level steps（每面一个子进程：临时 fake-dsh 包树 + launcher 调真实 node.ts 的
 * 公共入口 apply()，收割 stderr/stdout/退出码/桩账本）：
 *   F1 legacy resume 成功 → exit 0、已恢复行、自定义 id 原样入桩账、零回落行、stdout=golden；
 *   F2 v3(0.1.5 形状) resume 成功 → 同 F1 且 stdout 与 F1 全等（双形状装配级等价）；
 *   F3 会话形状不识别（无 eventAt 无 events）→ 「形状不识别…拒绝静默猜测」exit 1；
 *   F4 agents.resume 返回缺 .agent → 「agents.resume 返回形状不识别」点名 + 「回落新建
 *      同 id 会话」显式宣告，同 id create 承接成功 exit 0（验收②+③合取）；
 *   F5 resume 失败 + 同 id create 失败（KI-059 撕裂链实况形状）→ 双行宣告「回落新建」+
 *      「改用全新会话 id（上下文不可恢复）」，fresh id 承接成功 exit 0（上下文丢失大声说）；
 *   F6 无 resumeId 一次性 create 返回 null → 「agents.create 返回形状不识别」exit 1
 *      （第四处调用点；桩只备 create，误走 resume 即裸 TypeError=当场红）；
 *   F7 v3 seq 缺口 → 「seq 7 不可读（已捕获长度 9）」exit 1（取舍①装配级）；
 *   F8 fresh-id create 也返回 null → 「agents.create 返回形状不识别」exit 1，且 F5 的
 *      两行宣告仍在场（第三处调用点守卫不吞宣告行）。
 *   全局判据（全部子用例）：stderr 每一行都属词汇表形状（dsh: / dsh-headless-resume: /
 *   headless-resume: 前缀），零裸栈、零「is not iterable」、零 TypeError 字样——
 *   「不得崩栈」的机械形式。
 *
 * intent 分工：developer L1（server/headless-resume/test/summarize.test.mjs）守
 *   summarize.js 纯函数语义（golden/畸形族）——本条守装配面（node.ts 四处调用点守卫、
 *   回落链次序与宣告、SessionSeq 注入、退出码语义），纯函数单测过≠守卫接线在
 *   （KI-046「测试在场≠测试生效」同族教训的对抗面）；t260916-24 / t260922-03 探针族
 *   守探针工具与 live 门槛判据（真 npm/真凭据/分钟级），本条零 live 零凭据零网络秒级；
 *   t260916-23 dualname 族守引擎/workbench 读侧，本条守写/续侧插件本体。
 *
 * 直跑：node integration/t260922-06/sc_t260922_06_resume_seam_faces.mjs（node ≥22.18）。
 * 临时目录/子进程不可用=ENV_FAIL exit 2 点名；插件 runner 缺席=产品红（探针同判：
 * runner 真源缺失不是环境缺件）。末行 SUMMARY pass=<n> fail=<k> env_fail=<e> na=0。
 */

import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = join(HERE, '..', '..')
const RUNNER = join(REPO, 'server', 'headless-resume', 'node.ts')

const ENV_ID = 't260922-06-sc-faces'
const GOLDEN = 'T260922 续写完成标记'

let pass = 0, fail = 0, envFail = 0
function ok(cond, face, label, detail) {
  if (cond) { pass++; return }
  fail++
  console.log(`FAIL [${face}] ${label}${detail ? '：' + detail : ''}`)
}
function envFailCase(face, reason) {
  envFail++
  console.log(`ENV_FAIL [${face}] ${reason}`)
}

// ---------- fake-dsh 桩树（包名=接缝契约面；桩只演被测缝，其余 fail-closed） ----------

const SESSION_STUB_V3 = [
  "export const SessionId = (id) => ({ custom: id })",
  "export const SessionSeq = (n) => {",
  "  if (!Number.isSafeInteger(n) || n < 0) throw new TypeError('SessionSeq: 非法 seq ' + n)",
  "  return n",
  "}",
  "",
].join('\n')
const SESSION_STUB_LEGACY = 'export const SessionId = (id) => ({ custom: id })\n'

async function buildFakeTree(dir, { withSessionSeq }) {
  const pkgs = {
    '@deepseek-ai/dsh-agent': 'export function installModelSelection() {}\n',
    '@deepseek-ai/dsh-llm':
      "export function createUserMessage(input) { return { __stub: 'user-message', input } }\n",
    '@deepseek-ai/dsh-session': withSessionSeq ? SESSION_STUB_V3 : SESSION_STUB_LEGACY,
    '@deepseek-ai/schemastery':
      'export default { object: () => ({}), string: () => ({ required: () => ({}) }) }\n',
  }
  for (const [name, code] of Object.entries(pkgs)) {
    const pkgDir = join(dir, 'node_modules', ...name.split('/'))
    await mkdir(pkgDir, { recursive: true })
    await writeFile(join(pkgDir, 'package.json'),
      JSON.stringify({ name, version: '0.0.0-stub', type: 'module', main: 'index.js' }))
    await writeFile(join(pkgDir, 'index.js'), code)
  }
}

/**
 * launcher 模板：调真实 node.ts 的公共入口 apply()（与 dsh 宿主同制式），appExit 记账
 * 退出码并把桩账本落盘。makeAgent 造的会话在 followup 时才追加本轮 turn 事件（与真
 * dsh 时序同形：firstSeq 在 followup 前捕获）。
 */
function launcherSrc(runnerUrl, resultPath, agentsExpr) {
  return [
    "import { writeFileSync } from 'node:fs'",
    'const RUNNER = ' + JSON.stringify(runnerUrl),
    'const RESULT = ' + JSON.stringify(resultPath),
    'const ENV_ID = ' + JSON.stringify(ENV_ID),
    'const GOLDEN = ' + JSON.stringify(GOLDEN),
    'const rec = { resume: [], create: [] }',
    'function makeAgent(kind) {',
    "  if (kind === 'legacy') {",
    '    const session = { seq: 6, events: [{ type: \'session\', seq: 0 }] }',
    '    return { whenIdle: async () => {}, followup: () => {',
    '      session.events.push(',
    "        { type: 'turn/start', seq: 6 },",
    "        { type: 'assistant/message', seq: 7, data: { message: { content: [{ type: 'text', text: GOLDEN }] } } },",
    "        { type: 'turn/end', seq: 8, data: { reason: { kind: 'completed' } } })",
    '      session.seq = 9',
    '    }, session }',
    '  }',
    "  if (kind === 'v3' || kind === 'v3gap') {",
    "    const bySeq = new Map([[0, { type: 'header', seq: 0 }]])",
    "    const session = { seq: 6, eventAt: (s) => (kind === 'v3gap' && s === 7 ? undefined : bySeq.get(s)) }",
    '    return { whenIdle: async () => {}, followup: () => {',
    "      bySeq.set(6, { type: 'turn/start', seq: 6 })",
    "      bySeq.set(7, { type: 'assistant/message', seq: 7, data: { message: { content: [{ type: 'text', text: GOLDEN }] } } })",
    "      bySeq.set(8, { type: 'turn/end', seq: 8, data: { reason: { kind: 'completed' } } })",
    '      session.seq = 9',
    '    }, session }',
    '  }',
    "  if (kind === 'unknown') return { whenIdle: async () => {}, followup: () => {}, session: {} }",
    "  throw new Error('stub: unknown session kind ' + kind)",
    '}',
    '// 每面一份桩实现（见场景文件头 F1-F8）；桩只演被测缝，误调用即失败形状。',
    'const agents = ' + agentsExpr,
    'const mod = await import(RUNNER)',
    'const ctx = { get: (k) => {',
    "  if (k === 'appExit') return (code) => {",
    '    writeFileSync(RESULT, JSON.stringify({ rec, exitCode: code }))',
    '    process.exitCode = code',
    '  }',
    "  if (k === 'agents') return agents",
    "  if (k === 'agentDefaultModel') return { currentSelection: () => ({ provider: 'stub-provider', model: 'stub-model' }) }",
    "  if (k === 'sessions') return { flush: async () => {} }",
    '  return undefined',
    '} }',
    "mod.apply(ctx, { task: 't260922-06 seam faces 探针任务' })",
    '',
  ].join('\n')
}

async function driveFace(name, { agentsExpr, withSessionSeq = false, clearEnv = false }) {
  const pre = { pass, fail, envFail }
  let dir = ''
  try {
    dir = await mkdtemp(join(tmpdir(), 't26092206-faces-'))
  } catch (e) {
    envFailCase(name, '临时目录不可用：' + e.message)
    return { pass: pass - pre.pass, fail: fail - pre.fail, envFail: envFail - pre.envFail, res: null }
  }
  let res
  try {
    await buildFakeTree(dir, { withSessionSeq })
    const resultPath = join(dir, 'result.json')
    const launcher = join(dir, 'launcher.mjs')
    await writeFile(launcher, launcherSrc(pathToFileURL(RUNNER).href, resultPath, agentsExpr))
    const env = { ...process.env }
    if (clearEnv) delete env.DSH_HEADLESS_SESSION
    else env.DSH_HEADLESS_SESSION = ENV_ID
    try {
      const r = await execFileP(process.execPath, [launcher],
        { env, timeout: 30000, maxBuffer: 1 << 20, windowsHide: true })
      res = { code: 0, stdout: r.stdout, stderr: r.stderr, result: null }
    } catch (e) {
      if (e && e.killed) {
        res = { code: 'TIMEOUT', stdout: e.stdout || '', stderr: e.stderr || '', result: null }
      } else if (e && typeof e.code === 'number') {
        res = { code: e.code, stdout: e.stdout || '', stderr: e.stderr || '', result: null }
      } else {
        envFailCase(name, '子进程启动失败：' + (e && e.message ? e.message : String(e)))
        return { pass: pass - pre.pass, fail: fail - pre.fail, envFail: envFail - pre.envFail, res: null }
      }
    }
    try { res.result = JSON.parse(await readFile(resultPath, 'utf8')) } catch { /* 缺账本=有判据面 */ }
  } catch (e) {
    envFailCase(name, '桩树/launcher 装配失败：' + (e && e.message ? e.message : String(e)))
    return { pass: pass - pre.pass, fail: fail - pre.fail, envFail: envFail - pre.envFail, res: null }
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {})
  }
  return { pass: pass - pre.pass, fail: fail - pre.fail, envFail: envFail - pre.envFail, res }
}

// ---------- 全局判据（每个子用例都必须过） ----------

const VOCAB_SHAPE = /^(dsh|dsh-headless-resume|headless-resume): /
const FORBIDDEN = ['is not iterable', 'TypeError', 'ERR_MODULE_NOT_FOUND', 'Cannot read properties']

function assertCommon(name, res) {
  const lines = res.stderr.split('\n').map((s) => s.trimEnd()).filter((s) => s.trim() !== '')
  ok(lines.length > 0 && lines.every((l) => VOCAB_SHAPE.test(l)),
    name, 'stderr 全行属词汇表形状（无裸栈）', JSON.stringify(lines.slice(0, 4)))
  const hit = FORBIDDEN.filter((m) => res.stderr.includes(m) || res.stdout.includes(m))
  ok(hit.length === 0, name, '零裸崩标记（' + FORBIDDEN.join(' / ') + '）', hit.join(','))
}

const has = (s, re) => re.test(s)

// ---------- 八个面 ----------

async function main() {
  // runner 真源缺席=产品红（对齐探针 check_resume 判法；这不是环境缺件）
  let runnerPresent = true
  try { await readFile(RUNNER) } catch { runnerPresent = false }
  if (!runnerPresent) {
    console.log('FAIL [前置] runner 真源缺席：' + RUNNER + '（headless-resume 插件真源缺失=产品红，探针同判）')
    console.log('SUMMARY pass=0 fail=1 env_fail=0 na=0')
    process.exit(1)
  }

  // F1 legacy（0.1.1 形状：events 数组；桩 dsh-session 无 SessionSeq 导出）——回归锚
  {
    const { res } = await driveFace('F1', {
      withSessionSeq: false,
      agentsExpr: `{
  resume: async (args) => { rec.resume.push(args); return { agent: makeAgent('legacy') } },
  create: async (args) => { rec.create.push(args); throw new Error('stub: create 不应被调用（resume 已成功）') },
}`,
    })
    if (res) {
      assertCommon('F1', res)
      ok(res.code === 0, 'F1', 'exit 0', 'code=' + res.code)
      ok(has(res.stderr, /已恢复会话 /) && res.stderr.includes(ENV_ID),
        'F1', '「已恢复会话 <id>」点名且带自定义 id', JSON.stringify(res.stderr.slice(0, 200)))
      ok(!res.stderr.includes('回落新建'), 'F1', '干净 resume 零回落噪声')
      ok(res.result && res.result.rec.resume.length === 1 &&
        res.result.rec.resume[0].resumeSessionId &&
        res.result.rec.resume[0].resumeSessionId.custom === ENV_ID,
        'F1', '自定义 id 原样进 agents.resume（不造 uuid）', JSON.stringify(res.result && res.result.rec.resume))
      ok(res.result && res.result.rec.create.length === 0, 'F1', 'resume 成功不触碰 create')
      ok(res.stdout === GOLDEN + '\n', 'F1', 'stdout=聚合 golden', JSON.stringify(res.stdout))
    }
  }

  // F2 v3（0.1.5 形状：无 events 数组、eventAt+SessionSeq）——resume 命中 0.1.5 真会话
  {
    const { res } = await driveFace('F2', {
      withSessionSeq: true,
      agentsExpr: `{
  resume: async (args) => { rec.resume.push(args); return { agent: makeAgent('v3') } },
  create: async (args) => { rec.create.push(args); throw new Error('stub: create 不应被调用（resume 已成功）') },
}`,
    })
    if (res) {
      assertCommon('F2', res)
      ok(res.code === 0, 'F2', 'exit 0', 'code=' + res.code)
      ok(has(res.stderr, /已恢复会话 /) && !res.stderr.includes('回落新建'),
        'F2', '0.1.5 形状 resume 直接成功零回落')
      ok(res.stdout === GOLDEN + '\n', 'F2', 'stdout=聚合 golden', JSON.stringify(res.stdout))
    }
  }

  // F2E 双形状装配级等价：F1 与 F2 的 stdout 全等（同一轮 turn 两种会话形状同一聚合）
  {
    const a = await driveFace('F2E-legacy', {
      withSessionSeq: false,
      agentsExpr: `{ resume: async (x) => { rec.resume.push(x); return { agent: makeAgent('legacy') } } }`,
    })
    const b = await driveFace('F2E-v3', {
      withSessionSeq: true,
      agentsExpr: `{ resume: async (x) => { rec.resume.push(x); return { agent: makeAgent('v3') } } }`,
    })
    if (a.res && b.res) {
      ok(a.res.stdout === b.res.stdout && a.res.stdout === GOLDEN + '\n',
        'F2E', 'legacy 与 v3 聚合输出装配级全等', JSON.stringify([a.res.stdout, b.res.stdout]))
    }
  }

  // F3 会话形状不识别 → 点名拒绝，不得裸崩（验收②）
  {
    const { res } = await driveFace('F3', {
      withSessionSeq: true,
      agentsExpr: `{ resume: async (x) => { rec.resume.push(x); return { agent: makeAgent('unknown') } } }`,
    })
    if (res) {
      assertCommon('F3', res)
      ok(res.code === 1, 'F3', 'exit 1', 'code=' + res.code)
      ok(has(res.stderr, /形状不识别/) && has(res.stderr, /拒绝静默猜测/),
        'F3', '形状漂移点名词在场', JSON.stringify(res.stderr.slice(0, 300)))
      ok(has(res.stderr, /已恢复会话 /), 'F3', 'resume 先成后崩：成功行仍在（诊断不失真）')
    }
  }

  // F4 agents.resume 返回缺 .agent → 守卫点名 + 回落宣告 + 同 id create 承接（验收②+③）
  {
    const { res } = await driveFace('F4', {
      withSessionSeq: true,
      agentsExpr: `{
  resume: async (args) => { rec.resume.push(args); return {} },
  create: async (args) => { rec.create.push(args); return { agent: makeAgent('v3') } },
}`,
    })
    if (res) {
      assertCommon('F4', res)
      ok(res.code === 0, 'F4', '回落链承接后 exit 0', 'code=' + res.code)
      ok(has(res.stderr, /agents\.resume 返回形状不识别/),
        'F4', '返回形状守卫点名 resume', JSON.stringify(res.stderr.slice(0, 300)))
      ok(has(res.stderr, /回落新建同 id 会话/) && res.stderr.includes(ENV_ID),
        'F4', '「未续上、已新建」显式宣告带 id（禁静默，验收③）')
      ok(res.result && res.result.rec.create.length === 1 &&
        res.result.rec.create[0].sessionId.custom === ENV_ID,
        'F4', '同 id create 承接（回落不是换 id）', JSON.stringify(res.result && res.result.rec.create))
      ok(res.stdout === GOLDEN + '\n', 'F4', '承接后流程跑完 stdout=golden', JSON.stringify(res.stdout))
    }
  }

  // F5 resume 失败 + 同 id create 失败（KI-059 撕裂链实况形状）→ 双宣告 + fresh id 承接
  {
    const { res } = await driveFace('F5', {
      withSessionSeq: true,
      agentsExpr: `{
  resume: async () => { throw new Error('session "' + ENV_ID + '" not found') },
  create: async (args) => {
    rec.create.push(args)
    if (args.sessionId && args.sessionId.custom === ENV_ID) {
      throw new Error('corrupt Zstandard session log: complete frame contains a torn JSONL record')
    }
    return { agent: makeAgent('v3') }
  },
}`,
    })
    if (res) {
      assertCommon('F5', res)
      ok(res.code === 0, 'F5', 'fresh id 兜底后 exit 0（流程不死）', 'code=' + res.code)
      ok(has(res.stderr, /回落新建同 id 会话/) && res.stderr.includes('not found'),
        'F5', '第一级宣告带原始错因（报错精确）')
      ok(has(res.stderr, /同 id 新建仍失败/) && res.stderr.includes('corrupt Zstandard'),
        'F5', '第二级宣告带撕裂错因（KI-059 形状）')
      ok(has(res.stderr, /全新会话 id/) && has(res.stderr, /上下文不可恢复/),
        'F5', '上下文丢失大声说（禁静默）')
      ok(res.result && res.result.rec.create.length === 2 &&
        typeof res.result.rec.create[1].sessionId.custom === 'string' &&
        res.result.rec.create[1].sessionId.custom.startsWith('session-'),
        'F5', '第二跳落全新 session-<uuid> id', JSON.stringify(res.result && res.result.rec.create))
      ok(res.stdout === GOLDEN + '\n', 'F5', '兜底后 stdout=golden', JSON.stringify(res.stdout))
    }
  }

  // F6 无 resumeId 一次性 create 返回 null → 守卫点名（第四处调用点；误走 resume 即裸崩当场红）
  {
    const { res } = await driveFace('F6', {
      withSessionSeq: true, clearEnv: true,
      agentsExpr: `{
  create: async (args) => { rec.create.push(args); return null },
}`,
    })
    if (res) {
      assertCommon('F6', res)
      ok(res.code === 1, 'F6', 'exit 1', 'code=' + res.code)
      ok(has(res.stderr, /agents\.create 返回形状不识别/),
        'F6', 'create 返回形状守卫点名', JSON.stringify(res.stderr.slice(0, 300)))
      ok(!res.stderr.includes('回落新建') && !has(res.stderr, /已恢复会话/),
        'F6', '一次性路径零 resume 噪声')
      ok(res.result && res.result.rec.create.length === 1, 'F6', 'create 确被调用（守卫非空转）')
    }
  }

  // F7 v3 seq 缺口（取舍①装配级）：eventAt 中段 undefined → 点名 seq 与已捕获长度
  {
    const { res } = await driveFace('F7', {
      withSessionSeq: true,
      agentsExpr: `{ resume: async (x) => { rec.resume.push(x); return { agent: makeAgent('v3gap') } } }`,
    })
    if (res) {
      assertCommon('F7', res)
      ok(res.code === 1, 'F7', 'exit 1', 'code=' + res.code)
      ok(has(res.stderr, /seq 7 不可读/) && has(res.stderr, /已捕获长度 9/),
        'F7', '点名 seq 与长度（不裸崩）', JSON.stringify(res.stderr.slice(0, 300)))
    }
  }

  // F8 fresh-id create 也返回 null → 第三处调用点守卫点名，且两级宣告行不吞
  {
    const { res } = await driveFace('F8', {
      withSessionSeq: true,
      agentsExpr: `{
  resume: async () => { throw new Error('session "' + ENV_ID + '" not found') },
  create: async (args) => {
    rec.create.push(args)
    if (args.sessionId && args.sessionId.custom === ENV_ID) {
      throw new Error('corrupt Zstandard session log: complete frame contains a torn JSONL record')
    }
    return null
  },
}`,
    })
    if (res) {
      assertCommon('F8', res)
      ok(res.code === 1, 'F8', 'exit 1', 'code=' + res.code)
      ok(has(res.stderr, /回落新建同 id 会话/) && has(res.stderr, /同 id 新建仍失败/),
        'F8', '两级宣告行先于守卫红（不吞宣告）')
      ok(has(res.stderr, /agents\.create 返回形状不识别/),
        'F8', 'fresh 位守卫点名', JSON.stringify(res.stderr.slice(0, 300)))
    }
  }

  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
  process.exit(envFail > 0 ? 2 : fail > 0 ? 1 : 0)
}

main().catch((e) => {
  console.log('ENV_FAIL: 场景自身崩溃（测试缺陷或环境缺件）: ' + (e && e.stack ? e.stack.split('\n')[0] : String(e)))
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail + 1} na=0`)
  process.exit(2)
})
