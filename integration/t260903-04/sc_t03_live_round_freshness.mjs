/**
 * integration/t260903-04/sc_t03_live_round_freshness.mjs
 * —— 动态流静默窗新鲜度契约（KI-024②，t260903-04）。
 *
 * 用户场景（KI-024 实案 t260903-01，两次误诊在案）：spawn→首句叙述间的静默窗里，
 * 实时动态面板零新增行——同期会话文件持续写入证明 agent 在干活，值守却把面板静默
 * 读成「停摆」。根因：宿主端点对会话事件流只上屏 user/assistant/tool/result 四类，
 * step/*、llm/retry 等轮级事件全被过滤。工单口径「收敷新鲜度即可，不追求完整」。
 *
 * 跨组件契约（本场景守的接缝）：会话落盘事件流（引擎侧泳道产物）→ 宿主提炼
 * readAgentLiveTail（/agent-live 端点宿主半）→ 用户可感知的行。断言：
 *   F1 每个 step/start 出一行（type='step'，summary 非空）——轮级新鲜度。
 *   F2 LLM 重试事件（llm/retry / llm/retry-started）出重试行——静默窗可见「仍在干活」。
 *   F3 tool/call → 🔧 工具行回归不破（summary 含工具名）。
 *   F4 静默窗整链（spawn→首句叙述之间）非空：首个 assistant 行之前已有 step/retry/tool 行。
 *   F5 故障面：坏 JSON 行/空行/未知未来类型 → 不崩、不产行。
 *   F6 降级回归：会话文件缺失 → exists:false + 人话 reason（设计文档降级口径）。
 *
 * 直跑：node integration/t260903-04/sc_t03_live_round_freshness.mjs（node ≥22.18）。
 * zstd 不在 PATH → 干净 SKIP（exit 0，原因上屏）。末行 SUMMARY pass=<n> skip=<m> fail=<k>。
 */

import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { readAgentLiveTail } from '../../server/dsh/workbench/src/host/agent-live.ts'

const execFileP = promisify(execFile)

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function sk(label) { skip++; console.log(`  SKIP ${label}`) }
function section(t) { console.log(`\n== ${t} ==`) }

/* fixture：静默窗叙事——派活后 agent 逐轮干活：轮开始→上游重试→读文件→思考流→
 * 首句叙述→轮结束→第二轮开始。中间插坏行（非 JSON/空行/未知未来类型）。 */
const EVENTS = [
  { type: 'step/start', time: 1000, data: {} },
  { type: 'llm/retry-started', time: 1100, data: {} },
  { type: 'llm/retry', time: 1200, data: {} },
  { type: 'tool/call', time: 1300, data: { name: 'Read', arguments: { file_path: '/x/y.py' } } },
  { type: 'tool/result', time: 1400, data: { message: { content: 'ok' } } },
  { type: 'reasoning-chunks', time: 1500, data: {} },
  { type: 'assistant/chunk', time: 1600, data: {} },
  { type: 'assistant/message', time: 1700, data: { message: { content: '首句叙述' } } },
  { type: 'step/end', time: 1800, data: {} },
  { type: 'step/start', time: 1900, data: {} },
]
const BAD_LINES = ['not-json{{{', '', JSON.stringify({ type: 'unknown/future', time: 2000, data: {} })]
const jsonl = [
  JSON.stringify(EVENTS[0]), BAD_LINES[0], JSON.stringify(EVENTS[1]), BAD_LINES[1],
  JSON.stringify(EVENTS[2]), JSON.stringify(EVENTS[3]), JSON.stringify(EVENTS[4]),
  JSON.stringify(EVENTS[5]), JSON.stringify(EVENTS[6]), JSON.stringify(EVENTS[7]),
  JSON.stringify(EVENTS[8]), JSON.stringify(EVENTS[9]), BAD_LINES[2],
].join('\n') + '\n'

let zstdOk = true
try { await execFileP('zstd', ['--version']) } catch { zstdOk = false }

const tmp = await mkdtemp(join(tmpdir(), 't260903-04-live-'))
try {
  if (!zstdOk) {
    section('环境')
    sk('zstd 不在 PATH——提炼契约无法对真压缩 fixture 验证（与 smoke/agent-live 同口径）')
  } else {
    const sessDir = join(tmp, 'sess')
    await mkdir(sessDir, { recursive: true })
    const jsonlPath = join(sessDir, 'session.jsonl')
    await writeFile(jsonlPath, jsonl, 'utf8')
    // 显式 -o 指定 <名>.zstd：zstd CLI 默认后缀是 .zst（v1.5.7 实测），会话定位契约要 .zstd。
    await execFileP('zstd', ['-q', '-f', jsonlPath, '-o', jsonlPath + '.zstd'])
    const sessPath = jsonlPath + '.zstd'

    section('F1-F4 静默窗新鲜度（真 zstd 压 fixture）')
    const r = await readAgentLiveTail(sessPath, 30)
    ok(r.exists === true, 'exists=true（fixture 命中）')

    const stepLines = (r.events || []).filter(e => e.type === 'step')
    ok(stepLines.length >= 2,
       `每个 step/start 出一行（2 次轮开始 → ${stepLines.length} 条 step 行，静默窗有动静）`)
    ok(stepLines.every(e => typeof e.summary === 'string' && e.summary.length > 0),
      'step 行 summary 非空（轮次可读，不只占位）')

    const retryLines = (r.events || []).filter(e => e.type === 'retry')
    ok(retryLines.length >= 1,
       `LLM 重试出重试行（llm/retry(-started) → ${retryLines.length} 条 retry 行）`)
    ok(retryLines.every(e => typeof e.summary === 'string' && e.summary.length > 0),
      'retry 行 summary 非空（「仍在干活」人话）')

    const toolLines = (r.events || []).filter(e => e.type === 'tool')
    ok(toolLines.length === 1 && toolLines[0].summary.includes('Read'),
      '🔧 工具行回归不破（tool/call → 含工具名的既有口径）')

    const firstAssistant = (r.events || []).findIndex(e => e.type === 'assistant')
    const beforeAssistant = firstAssistant >= 0 ? (r.events || []).slice(0, firstAssistant) : []
    ok(firstAssistant > 0
      && beforeAssistant.some(e => e.type === 'step')
      && beforeAssistant.some(e => e.type === 'retry')
      && beforeAssistant.some(e => e.type === 'tool'),
      '静默窗整链非空：首个 agent 叙述行之前已有 step/retry/tool 行（spawn→首句不再零行）')
  }

  section('F5-F6 故障面与降级')
  {
    // 坏行已被主 fixture 覆盖（不崩不出行）：这里断言坏行确实没产行——total 行数恰好
    // = 合法感兴趣事件数，坏 JSON/空行/未知类型一个不漏网。
    if (zstdOk) {
      const sessDir = join(tmp, 'sess')
      const r = await readAgentLiveTail(join(sessDir, 'session.jsonl.zstd'), 30)
      // 感兴趣行全保 + 噪声零泄漏：上屏 type 白名单恰为既有五类；坏 JSON/空行/未知
      // 类型/流式块（reasoning-chunks、assistant/chunk）、step/end 一个不漏网。
      // retry-started 与 retry 是否合并一行是实现自由度（工单口径「收敷新鲜度即可」），
      // 不锚行数——锚 step 恰 2、tool/result/assistant 各恰 1、retry ≥1。
      const types = new Set((r.events || []).map(e => e.type))
      const allowed = new Set(['step', 'retry', 'tool', 'result', 'assistant', 'user'])
      ok([...types].every(t => allowed.has(t)),
        `上屏 type 白名单内（actual=${[...types].join(',')}——坏行/流式块/未知类型不上屏）`)
      const by = t => (r.events || []).filter(e => e.type === t).length
      ok(by('step') === 2 && by('tool') === 1 && by('result') === 1 && by('assistant') === 1
        && by('retry') >= 1,
        `感兴趣行全保（step=2 tool=1 result=1 assistant=1 retry=${by('retry')}）`)
    } else {
      sk('坏行断言随 zstd 缺失一并 SKIP')
    }

    const miss = await readAgentLiveTail(join(tmp, 'nope', 'session.jsonl.zstd'), 30)
    ok(miss.exists === false && typeof miss.reason === 'string' && miss.reason.length > 0,
      '会话缺失 → exists:false + 人话 reason（降级口径，不抛错）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
