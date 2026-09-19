#!/usr/bin/env node
/**
 * sc_t260917_05_session_face_loud_host.mjs —— 会话发现面零静默降级·workbench 宿主面
 * （t260917-05 要求③的数据契约面，灰盒 L3，池=ro）。
 *
 * intent（用户可感知）：workbench 用量/发现面对「文件在、名字/格式对不上本版本解析面」
 * 必须响亮——UI 的提示行吃的就是这份 {exists, reason, suspect, suspectFiles} 契约，
 * 绝不静默 0/空白（渲染归组件 UT，本条守 UI 吃到的 API 数据契约本身）。
 *
 * 断言面（锚定 agent-usage.ts 模块契约，node 直跑 src/host=宿主半真实消费形态）：
 *  A 双名回归锚：两角色目录全取、他票不混入、加总 11/22（T1 已落行为的现状锚）；
 *  B 坏格式（合法 zstd 帧包非 JSON 文本）→ exists=false + reason 含票面例句 + suspect=true；
 *  C 混合态（好+坏）→ exists=true 金额来自好文件，suspect=true 且 reason 点名坏文件
 *    （部分降级不静默）；
 *  D usage 对象缺全部已知键 → suspect=true（dsh 升级改字段名形态）；
 *  E 刚启动边界（有事件无 usage / 空内容）→ 既有「刚启动」人话保留、suspect 不置位
 *    （防误报方向的对抗腿）；
 *  F 发现集空而目录有他票三层/旧扁平/未知名 → reason 三类分流点名（他票与旧代=未入
 *    统计、未知名=疑似 dsh 版本不匹配）+ suspectFiles 机器可读面含未知名。
 *
 * 实现段落地前红属预期（TDD 信号：B-F 的 suspect/suspectFiles 与分流 reason 未落地），
 * arbitrate/merge 期必须绿。与 smoke/agent-usage.mjs B/C 段 intent 不同面：smoke 守
 * 单点降级与防穿回归（解压失败类），本条守三态分流与混合合成的整结果契约。
 * Run: node integration/t260917-05/sc_t260917_05_session_face_loud_host.mjs（cwd=仓库根）
 */
import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { promisify } from 'node:util'
import { aggregateTicketUsage, resolveAllSessionFiles } from '../../server/plugins/workbench/src/host/agent-usage.ts'

const execFileP = promisify(execFile)

let passed = 0
const fails = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { fails.push(label); console.log(`  FAIL ${label}`) }
}
function done(name) {
  console.log(`\n${name}: ok=${passed} FAIL=${fails.length}`)
  return fails.length > 0 ? 1 : 0
}

// ---- 环境三态：缺供一律 ENV_FAIL exit 2，绝不装绿 ----
const nodeVer = process.versions.node.split('.').map(Number)
if (nodeVer[0] < 22 || (nodeVer[0] === 22 && nodeVer[1] < 18)) {
  console.log(`ENV_FAIL: node ${process.versions.node} 无原生 type-stripping（需 >= 22.18 直跑 .ts 模块）`)
  process.exit(2)
}
const zstdOn = await execFileP('zstd', ['-V']).then(() => true, () => false)
if (!zstdOn) {
  console.log('ENV_FAIL: zstd CLI 缺席（会话解压通路依赖 zstd，环境缺供）')
  process.exit(2)
}

const TICKET = 't260917-05'
const tmp = await mkdtemp(join(tmpdir(), 'sc-t26091705-host-'))

const jd = (o) => JSON.stringify(o) + '\n'
const healthy = (i = 10, o = 20, c = 5) => [
  jd({ type: 'session', version: 0, id: 's', createdAt: 1 }),
  jd({ type: 'request/context', seq: 1, data: { provider: 'p', model: 'm1' } }),
  jd({ type: 'assistant/message', seq: 2, data: { usage: { inputTokens: i, outputTokens: o, cacheReadTokens: c } } }),
]
async function putZ(root, parts, lines) {
  const fp = join(root, ...parts)
  await mkdir(dirname(fp), { recursive: true })
  const plain = join(tmp, `plain-${Math.random().toString(36).slice(2)}.jsonl`)
  await writeFile(plain, lines.join(''), 'utf8')
  await execFileP('zstd', ['-q', '-f', plain, '-o', fp])
  return fp
}
const sess = (wtName, ...rest) => ['.worktrees', wtName, '.dsh', 'sessions', ...rest]

// ---- 腿 A：双名回归锚（T1 现状锚）----
{
  const repo = join(tmp, 'repoA')
  await putZ(repo, sess('wtA', 'slugA', TICKET, 'session.jsonl.zstd'), healthy(10, 20, 5))
  await putZ(repo, sess('wtA', 'slugA', TICKET + '-developer', 'session.jsonl.zstd'), healthy(1, 2, 3))
  await putZ(repo, sess('wtA', 'slugA', 't9999-99', 'session.jsonl.zstd'), healthy(100, 100, 100))
  const r = await resolveAllSessionFiles(repo, TICKET, { worktree: '.worktrees/wtA' })
  ok(r.refused === undefined && r.paths.length === 2, 'A1 双名两档全取、他票不混入')
  const agg = await aggregateTicketUsage(r.paths, [])
  ok(agg.exists === true && agg.total.input === 11 && agg.total.output === 22, 'A2 双名加总 11/22（T1 回归锚）')
  ok(!agg.suspect, 'A3 健康态无 suspect')
}

// ---- 腿 B：坏格式（解压成功、内容不可解析）----
{
  const repo = join(tmp, 'repoB')
  const fp = await putZ(repo, sess('wtB', 'slugB', TICKET, 'session.jsonl.zstd'),
    ["ce n'est pas du json\n", 'nope neither\n'])
  const agg = await aggregateTicketUsage([fp], [])
  ok(agg.exists === false, 'B1 坏格式 → exists=false')
  ok((agg.reason ?? '').includes('格式不认识') && (agg.reason ?? '').includes('统计值不可信'),
    'B2 reason 含票面例句（非轻描 0）')
  ok(agg.suspect === true, 'B3 suspect=true')
}

// ---- 腿 C：混合态（好+坏）→ 部分降级不静默 ----
{
  const repo = join(tmp, 'repoC')
  const good = await putZ(repo, sess('wtC', 'slugC', TICKET, 'session.jsonl.zstd'), healthy(7, 0, 0))
  const bad = await putZ(repo, sess('wtC', 'slugC', TICKET + '-badsoup', 'session.jsonl.zstd'), ['garbage line\n'])
  const agg = await aggregateTicketUsage([good, bad], [])
  ok(agg.exists === true && agg.total.input === 7, 'C1 金额只来自好文件（一份坏不清零整体）')
  ok(agg.suspect === true, 'C2 混合态 suspect 仍置位')
  {
    // C3 锚「结果人话面」而非单一字段：混合态（exists=true）的点名通道是
    // suspectDetail（UI 悬停明细源），降级态才是 reason——两个公开通道任一在即契约
    // 成立（arbitrate 归因：原断言锚 reason 单字段属测试面误锚，非实现缺名）。
    const face = `${agg.reason ?? ''}；${agg.suspectDetail ?? ''}`
    ok(face.includes('badsoup') && face.includes('格式不认识'),
      'C3 结果人话面仍点名坏文件（reason/suspectDetail 通道，坏档不因好档有数被吞）')
  }
}

// ---- 腿 D：usage 对象缺全部已知键（dsh 改字段名形态）----
{
  const repo = join(tmp, 'repoD')
  const fp = await putZ(repo, sess('wtD', 'slugD', TICKET, 'session.jsonl.zstd'),
    [jd({ type: 'assistant/message', seq: 1, data: { usage: { tokens: 5, total_tokens: 9 } } })])
  const agg = await aggregateTicketUsage([fp], [])
  ok(agg.suspect === true && (agg.reason ?? '').includes('格式不认识'),
    'D usage 三键全缺 → suspect（usage 形状不认识）')
}

// ---- 腿 E：刚启动边界 → 不冤枉格式 ----
{
  const repo = join(tmp, 'repoE')
  const noUsage = await putZ(repo, sess('wtE', 'slugE', TICKET, 'session.jsonl.zstd'),
    [jd({ type: 'session', version: 0, id: 's', createdAt: 1 }),
     jd({ type: 'request/context', seq: 1, data: { provider: 'p', model: 'm' } })])
  const voidZ = await putZ(repo, sess('wtE', 'slugE', TICKET + '-void', 'session.jsonl.zstd'), [])
  const aggN = await aggregateTicketUsage([noUsage], [])
  ok(aggN.exists === false && (aggN.reason ?? '').includes('刚启动') && !aggN.suspect,
    'E1 有事件无 usage → 既有「刚启动」人话保留、suspect 不置位')
  const aggV = await aggregateTicketUsage([voidZ], [])
  ok(aggV.exists === false && !aggV.suspect && !(aggV.reason ?? '').includes('格式不认识'),
    'E2 空内容合法非格式违约')
}

// ---- 腿 F：发现集空而目录有会话样文件 → 三类分流点名 + suspectFiles ----
{
  const repo = join(tmp, 'repoF')
  await putZ(repo, sess('wtF', 'fslug-other', 't9999-99', 'session.jsonl.zstd'), healthy())
  await putZ(repo, sess('wtF', 'fslug-old', 'session-0425.zstd'), healthy())
  await putZ(repo, sess('wtF', 'fslug-new', 'x9', 'session.jsonl.zst'), ['k\n'])
  const r = await resolveAllSessionFiles(repo, TICKET, { worktree: '.worktrees/wtF' })
  ok(r.refused === undefined && (r.paths ?? []).length === 0, 'F1 发现集空')
  const rf = r.reason ?? ''
  ok(rf.includes('fslug-other') && rf.includes('未入统计'), 'F2 他票三层 → 点名+「未入统计」（不喊损坏）')
  ok(rf.includes('fslug-old'), 'F3 旧扁平（已知旧代）→ 点名在场')
  ok(rf.includes('fslug-new') && rf.includes('疑似 dsh 版本不匹配'), 'F4 未知名 → 点名+「疑似 dsh 版本不匹配」')
  ok(Array.isArray(r.suspectFiles) && r.suspectFiles.some((p) => p.includes('fslug-new')),
    'F5 suspectFiles 机器可读面含未知名')
}

process.exit(done('t260917-05-session-face-loud-host'))
