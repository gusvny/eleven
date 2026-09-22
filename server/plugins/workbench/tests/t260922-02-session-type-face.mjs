/**
 * tests/t260922-02-session-type-face.mjs —— 双代会话词表面 UT（t260922-02）。
 *
 * 直跑：node server/plugins/workbench/tests/t260922-02-session-type-face.mjs
 * 覆盖：
 *   A. 词表形状：SESSION_KNOWN_TYPES 17=6+11（0.1.5 独有 11 项）、
 *      SESSION_TWO_GEN_TYPES 63（两代目录并集 59 ∪ session 头行 ∪ chunk 存储行 3）、
 *      S1 ⊆ 超集；两代都在列的 0.1.1 已识型不进 S1（0.1.1 计数不变的可证明口径）。
 *   B. judgeSessionLines 判据（夹具与 engine 侧 py 测试同构对账）：0.1.1 夹具
 *      golden 逐字（known=6/uncoved 空）、0.1.5 夹具识别（known 5→16）、
 *      预派发中止形态（无 session 头行，旧码假 S1→新码识别）、词表外反向注入
 *      uncovered 点名不混 S1、畸形输入不抛。
 *   C. summarizeEvent 分派面：0.1.1 行 golden 逐字（六行原样）、0.1.5 attempt 行
 *      （三级提取：chunk.text 直取→chunk 块数组→记录本体；畸形不抛）、
 *      system/message 有意不上屏（钉死注释级处置，防将来被「顺手」上屏）。
 *   D. readAgentLiveTail 端到端（zstd 临时档）：0.1.1 六行逐字 + uncoveredTypes
 *      缺省；词表外档 reason 人话点名 + uncoveredTypes。
 *   E. 双向词表锁（TS←py 方向；对侧锁在 engine tests/test_t260922_02_session_type_face.py）：
 *      读 agent_activities.py 源码提取两张 frozenset 字面量对拍本侧集合——
 *      正则不命中→响亮 FAIL（禁静默跳过）、既有键独立锚（防噪声守卫被拆）、
 *      仓根以 CLAUDE.md 上溯定位（不依赖机器路径）。
 * 全程零 3099/零网络：夹具内嵌，zstd 用系统 CLI。
 */
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

const { judgeSessionLines, sessionFaceS1Text, summarizeEvent, readAgentLiveTail,
        SESSION_KNOWN_TYPES, SESSION_TWO_GEN_TYPES } =
  await import(join(repo, 'server/plugins/workbench/src/host/agent-live.ts'))

const execFileP = promisify(execFile)
let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed++ } else { failed++; console.error(`  ✗ ${name}`) }
}
const lines = fs => fs.map(o => JSON.stringify(o))

/* ── 双代夹具（与 engine tests/test_t260922_02_session_type_face.py 同构对账；
      形状真源=两代 GENERATED 目录 types.d.ts + 真 0.1.5 样本 + 真 0.1.1 直方图） ── */
const V011 = [
  { type: 'session', version: 1, id: 's1', createdAt: 1000 },
  { type: 'request/context', seq: 1, time: 1100, data: { provider: 'p', model: 'm' } },
  { type: 'request/header', seq: 2, time: 1200, data: { header: { config: { provider: 'p', model: 'm' } } } },
  { type: 'permission/preset', seq: 3, time: 1300, data: { preset: 'workspace-write' } },
  { type: 'sandbox/mode', seq: 4, time: 1400, data: { mode: 'workspace-write' } },
  { type: 'approval/policy', seq: 5, time: 1500, data: { policy: 'ask' } },
  { type: 'session/title', seq: 6, time: 1600, data: { title: 't', source: { kind: 'fallback' } } },
  { type: 'turn/start', seq: 7, time: 1700, data: { turn: 1 } },
  { type: 'step/start', seq: 8, time: 1800, data: { turn: 1, step: 1 } },
  { type: 'user/message', seq: 9, time: 1900, data: { content: [{ type: 'text', text: 'hi' }] } },
  { type: 'reasoning-chunks', seq: 10, time: 2000, data: { texts: ['a'] } },
  { type: 'text-chunks', seq: 11, time: 2100, data: { texts: ['b'] } },
  { type: 'assistant/chunk', seq: 12, time: 2200, data: { chunk: { type: 'text' } } },
  { type: 'assistant/message', seq: 13, time: 2300, data: { message: { role: 'assistant', content: [{ type: 'text', text: 'ok' }] }, usage: { inputTokens: 7, outputTokens: 8, cacheReadTokens: 1 } } },
  { type: 'tool/call', seq: 14, time: 2400, data: { name: 'read', arguments: '{}' } },
  { type: 'tool/result', seq: 15, time: 2500, data: { message: { role: 'toolResult', content: [{ type: 'text', text: 'r' }] } } },
  { type: 'step/end', seq: 16, time: 2600, data: { turn: 1, step: 1 } },
  { type: 'turn/end', seq: 17, time: 2700, data: { turn: 1, reason: 'end' } },
  { type: 'session/end-seed', data: {} },
  { type: 'agent/inbox/spliced', seq: 18, time: 2800, data: { target: 'next-turn', start: 0, inserted: [] } },
  { type: 'llm/retry', seq: 19, time: 2900, data: { provider: 'zai' } },
  { type: 'llm/retry-started', seq: 20, time: 2950, data: { retry: 1 } },
  { type: 'tool-call-chunks', data: {} },
  { type: 'tool/code-dispatch', data: {} },
  { type: 'tool/code-dispatch-start', data: {} },
]
const V015 = [
  { type: 'session', version: 3, id: 's2', createdAt: 1000 },
  { type: 'permission/preset', seq: 0, time: 1100, data: { preset: 'workspace-write' } },
  { type: 'sandbox/mode', seq: 1, time: 1200, data: { mode: 'workspace-write' } },
  { type: 'approval/policy', seq: 2, time: 1300, data: { policy: 'ask' } },
  { type: 'session/title-llm-request', seq: 3, time: 1400, data: { titleProvider: 'session-title-first-prompt-llm', route: { provider: 'p' } } },
  { type: 'agent/inbox/spliced', seq: 4, time: 1500, data: { target: 'next-turn', start: 0, inserted: [] } },
  { type: 'turn/start', seq: 5, time: 1600, data: { turn: 1 } },
  { type: 'step/start', seq: 6, time: 1700, data: { turn: 1, step: 1 } },
  { type: 'system/message', seq: 7, time: 1800, data: { turn: 1, step: 1, message: { role: 'system', content: [{ type: 'text', text: 'sys' }] } } },
  { type: 'user/message', seq: 8, time: 1900, data: { content: [{ type: 'text', text: 'q' }] } },
  { type: 'request/header', seq: 9, time: 2000, data: { header: { config: { provider: 'p', model: 'm' } } } },
  { type: 'request/context', seq: 10, time: 2100, data: { provider: 'p', model: 'm' } },
  { type: 'session/title', seq: 11, time: 2200, data: { title: 't', source: { kind: 'fallback' } } },
  { type: 'assistant/attempt', seq: 12, time: 2300, data: { turn: 1, step: 1, stream: [{ type: 'chunk', time: 2301, chunk: { type: 'text', text: 'partial' } }] } },
  { type: 'assistant/message', seq: 13, time: 2400, data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'done' }] }, stream: [], usage: { inputTokens: 11, outputTokens: 13 } } },
  { type: 'tool/call', seq: 14, time: 2500, data: { name: 'read', arguments: '{}' } },
  { type: 'tool/result', seq: 15, time: 2600, data: { message: { role: 'toolResult', content: [{ type: 'text', text: 'r' }] } } },
  { type: 'step/end', seq: 16, time: 2700, data: { turn: 1, step: 1 } },
  { type: 'turn/end', seq: 17, time: 2800, data: { turn: 1, reason: 'end' } },
  { type: 'deliverables/presented', data: {} },
  { type: 'feedback/message-delete', data: {} },
  { type: 'feedback/message-put', data: {} },
  { type: 'model/selection', data: {} },
  { type: 'session-log-deepseek/delivery-accepted', data: {} },
  { type: 'subagent/catalog', data: {} },
  { type: 'subagent/model-selection-policy', data: {} },
  { type: 'tool/ptc-dispatch', data: {} },
  { type: 'tool/ptc-dispatch-start', data: {} },
]
const PREDISPATCH = [ // 无 session 头行的超早期中止形态（CC1(a) 识别钉）
  { type: 'turn/start', data: { turn: 1 } },
  { type: 'step/start', data: { turn: 1, step: 1 } },
  { type: 'system/message', data: { turn: 1, step: 1, message: { role: 'system', content: [{ type: 'text', text: 'sys' }] } } },
  { type: 'assistant/attempt', data: { turn: 1, step: 1, stream: [] } },
]
const UNCOV = [ // 反向注入：词表外类型——「缺得不静默」的机械钉
  { type: 'request/context', data: { provider: 'p', model: 'm' } },
  { type: 'v9/whatever', data: {} },
]

/* ── A. 词表形状 ── */
{
  ok(SESSION_KNOWN_TYPES.size === 17, 'A: S1 集 17=6+11')
  ok(SESSION_TWO_GEN_TYPES.size === 63, 'A: 超集 63=59+1+3')
  ok([...SESSION_KNOWN_TYPES].every(t => SESSION_TWO_GEN_TYPES.has(t)), 'A: S1 ⊆ 超集')
  const only15 = ['assistant/attempt', 'system/message', 'deliverables/presented',
    'feedback/message-delete', 'feedback/message-put', 'model/selection',
    'session-log-deepseek/delivery-accepted', 'subagent/catalog',
    'subagent/model-selection-policy', 'tool/ptc-dispatch', 'tool/ptc-dispatch-start']
  ok(only15.every(t => SESSION_KNOWN_TYPES.has(t)), 'A: 0.1.5 独有 11 项全进 S1')
  // 两代目录都在列、0.1.1 真会话在产——进 S1 会改 0.1.1 计数，只能进超集
  ok(['agent/inbox/spliced', 'session/title-llm-request'].every(
    t => !SESSION_KNOWN_TYPES.has(t) && SESSION_TWO_GEN_TYPES.has(t)),
    'A: 两代共有型不进 S1 只进超集（0.1.1 计数不变口径）')
  ok(['session', 'text-chunks', 'reasoning-chunks', 'tool-call-chunks'].every(
    t => SESSION_TWO_GEN_TYPES.has(t)), 'A: 头行标签+chunk 存储行在超集（目录外补集）')
  // 结构性噪声守卫①：超集逐型喂行 → uncovered 恒空（常量自洽，字面量膨胀不烂）
  const noisy = [...SESSION_TWO_GEN_TYPES].filter(
    t => judgeSessionLines([JSON.stringify({ type: t, data: {} })]).uncoveredCount !== 0)
  ok(noisy.length === 0, 'A: 超集逐型自检零误报（噪声守卫①）')
}

/* ── B. judgeSessionLines 判据 ── */
{
  const j11 = judgeSessionLines(lines(V011))
  ok(j11.parsed === 25 && j11.knownTypes === 6, 'B: 0.1.1 golden 计数逐字（25/6）')
  ok(j11.usageRecords === 1 && j11.usageWithoutKnownKeys === 0, 'B: 0.1.1 usage 计数逐字')
  ok(j11.uncoveredTypes.length === 0 && j11.uncoveredCount === 0, 'B: 0.1.1 零误注（20 型全在超集）')
  ok(sessionFaceS1Text('v011.zstd', j11) === null, 'B: 0.1.1 不假 S1')

  const j15 = judgeSessionLines(lines(V015))
  ok(j15.parsed === 28 && j15.knownTypes === 16, 'B: 0.1.5 识别 known 5→16')
  ok(j15.usageRecords === 1 && j15.usageWithoutKnownKeys === 0,
    'B: 0.1.5 usage 缺可选 cacheReadTokens 不误报缺键')
  ok(j15.uncoveredCount === 0 && sessionFaceS1Text('v015.zstd', j15) === null,
    'B: 0.1.5 不假 S1 零误注')

  const jp = judgeSessionLines(lines(PREDISPATCH))
  ok(jp.knownTypes === 2 && sessionFaceS1Text('pred.zstd', jp) === null,
    'B: 预派发中止形态（无 session 头行）识别不假 S1（旧码 known=0 假 S1）')

  const ju = judgeSessionLines(lines(UNCOV))
  ok(ju.knownTypes === 1 && ju.uncoveredCount === 1 && ju.uncoveredTypes[0] === 'v9/whatever',
    'B: 词表外反向注入→uncovered 点名')
  ok(sessionFaceS1Text('uncov.zstd', ju) === null, 'B: uncovered 不混 S1 语义（加性不致命）')

  const bad = judgeSessionLines([123, null, 'not json', '[1,2]', '{"type": 42}', '{"no_type": 1}', '"str"', '   '])
  ok(bad.parsed === 2 && bad.knownTypes === 0 && bad.uncoveredCount === 0,
    'B: 畸形行不抛、type 非串/缺型不入任何词表')
  ok(JSON.stringify(judgeSessionLines(null).uncoveredTypes) === '[]', 'B: 非 array 输入不抛')
}

/* ── C. summarizeEvent 分派面 ── */
{
  // 0.1.1 golden 六行逐字（改码前快照；session/request/permission/sandbox/approval/
  // title/turn/step-end/turn-end/end-seed/inbox-spliced/retry-started/chunk 族等均 null）
  const rows11 = V011.map(o => summarizeEvent(o)).filter(r => r !== null)
  const want11 = [
    { ts: 1, type: 'step', summary: '第 1 轮 · 第 1 步开始' },
    { ts: 1, type: 'user', summary: '用户：hi' },
    { ts: 2, type: 'assistant', summary: 'ok' },
    { ts: 2, type: 'tool', summary: '读取 文件' },
    { ts: 2, type: 'result', summary: '结果：r' },
    { ts: 2, type: 'retry', summary: 'LLM 重试中（zai），仍在干活' },
  ]
  ok(JSON.stringify(rows11) === JSON.stringify(want11), 'C: 0.1.1 面板行 golden 逐字不变')

  // 0.1.5 attempt 行：真样本三级形状（chunk.text 直取）
  const a1 = summarizeEvent(V015[13])
  ok(a1 !== null && a1.type === 'attempt' &&
    a1.summary === '第 1 轮 · 第 1 步 · 模型尝试未转正（重试/失败/中断），输出片段：partial',
    'C: attempt 行认得出拿得到（真样本 chunk.text 形状）')
  const a2 = summarizeEvent({ type: 'assistant/attempt', time: 2300, data: { turn: 1, step: 2, stream: [{ chunk: [{ type: 'text', text: 'blk' }] }] } })
  ok(a2.summary.endsWith('输出片段：blk'), 'C: attempt 三级提取之中——chunk 块数组')
  const a3 = summarizeEvent({ type: 'assistant/attempt', time: 2300, data: { turn: 1, step: 3, stream: [{ text: 'top' }] } })
  ok(a3.summary.endsWith('输出片段：top'), 'C: attempt 三级提取之三——记录本体')
  // 真错误 attempt（本泳道 0.1.5 探针原样行：finish/error，无文本）→ 定位行不带半截预览
  const a4 = summarizeEvent({ type: 'assistant/attempt', seq: 15, time: 1790012367888,
    data: { turn: 1, step: 1, stream: [{ type: 'chunk', time: 1790012367888, chunk: { type: 'finish', reason: { kind: 'error', error: { message: 'no api key' } } } }] } })
  ok(a4 !== null && a4.ts === 1790012367 &&
    a4.summary === '第 1 轮 · 第 1 步 · 模型尝试未转正（重试/失败/中断）',
    'C: 真错误 attempt（finish/error 无文本）出定位行不编预览')
  // 畸形不抛：非数组 stream / 缺 data / 垃圾元素混合
  const junk = [summarizeEvent({ type: 'assistant/attempt', data: { stream: 'x' } }),
    summarizeEvent({ type: 'assistant/attempt' }),
    summarizeEvent({ type: 'assistant/attempt', data: { stream: [null, 42, { chunk: { text: '' } }], turn: 'x', step: null } })]
  ok(junk.every(r => r !== null && r.type === 'attempt' && !r.summary.includes('undefined')),
    'C: attempt 畸形输入不抛不出半截行')

  // system/message 有意不上屏（元信息同 request/*；词表进、分派面点名——防被顺手改上屏）
  ok(summarizeEvent(V015[8]) === null, 'C: system/message 有意不上屏（处置钉死）')
  // 其余 0.1.5 独有型认知级：落 default 过滤不炸
  ok(V015.slice(19).map(o => summarizeEvent(o)).every(r => r === null),
    'C: 其余 0.1.5 独有型认知级过滤（deliverables/presented 等 9 项）')
}

/* ── D. readAgentLiveTail 端到端（zstd 临时档） ── */
{
  const tmp = await mkdtemp(join(tmpdir(), 't260922-02-'))
  const zstdOf = async name => {
    const src = join(tmp, name + '.jsonl')
    await writeFile(src, lines(name === 'V011' ? V011 : name === 'V015' ? V015 : UNCOV).join('\n') + '\n', 'utf8')
    const z = join(tmp, name + '.jsonl.zstd')
    await execFileP('zstd', ['-q', '-f', src, '-o', z])
    return z
  }
  const z11 = await zstdOf('V011')
  const r11 = await readAgentLiveTail(z11, 30)
  ok(r11.exists === true && r11.truncated === false, 'D: 0.1.1 档存在不截断')
  ok(JSON.stringify(r11.events) === JSON.stringify([
    { ts: 1, type: 'step', summary: '第 1 轮 · 第 1 步开始' },
    { ts: 1, type: 'user', summary: '用户：hi' },
    { ts: 2, type: 'assistant', summary: 'ok' },
    { ts: 2, type: 'tool', summary: '读取 文件' },
    { ts: 2, type: 'result', summary: '结果：r' },
    { ts: 2, type: 'retry', summary: 'LLM 重试中（zai），仍在干活' },
  ]), 'D: 0.1.1 端到端六行逐字（golden 复现）')
  ok(r11.uncoveredTypes === undefined, 'D: 0.1.1 健康档不加 uncoveredTypes 键')

  const z15 = await zstdOf('V015')
  const r15 = await readAgentLiveTail(z15, 30)
  ok(r15.events.some(e => e.type === 'attempt') && r15.events.some(e => e.type === 'assistant'),
    'D: 0.1.5 档 attempt 与 assistant 行并存')
  ok(r15.uncoveredTypes === undefined, 'D: 0.1.5 健康档不加 uncoveredTypes 键')

  const zu = await zstdOf('UNCOV')
  const ru = await readAgentLiveTail(zu, 30)
  ok(Array.isArray(ru.uncoveredTypes) && ru.uncoveredTypes.length === 1 &&
    ru.uncoveredTypes[0] === 'v9/whatever', 'D: 词表外档 uncoveredTypes 点名')
  ok(typeof ru.reason === 'string' && ru.reason.includes('未覆盖') &&
    ru.reason.includes('v9/whatever'), 'D: 零事件+未覆盖 → reason 人话点名（绝不静默空白）')
  await rm(tmp, { recursive: true, force: true })
}

/* ── E. 双向词表锁（TS←py 方向） ── */
{
  const engSrc = readFileSync(join(repo, 'server/engine/agent_activities.py'), 'utf8')
  const extractPy = name => {
    // 正则不命中 → 返回 null → 断言响亮 FAIL（禁静默跳过）
    const m = engSrc.match(new RegExp(`${name} = frozenset\\(\\{([\\s\\S]*?)\\}\\)`))
    if (m === null) return null
    // 词表含多段斜杠型（agent/inbox/spliced、team/message/*）→ 段数不设上限
    const toks = [...m[1].matchAll(/"([a-z0-9-]+(?:\/[a-z0-9-]+)*)"/g)].map(x => x[1])
    return new Set(toks)
  }
  const pyKnown = extractPy('SESSION_KNOWN_TYPES')
  const pyTwo = extractPy('SESSION_TWO_GEN_TYPES')
  ok(pyKnown !== null && pyKnown.size === SESSION_KNOWN_TYPES.size &&
    [...pyKnown].every(t => SESSION_KNOWN_TYPES.has(t)) &&
    [...SESSION_KNOWN_TYPES].every(t => pyKnown.has(t)),
    'E: 锁① SESSION_KNOWN_TYPES py==ts 逐项互等')
  ok(pyTwo !== null && pyTwo.size === SESSION_TWO_GEN_TYPES.size &&
    [...pyTwo].every(t => SESSION_TWO_GEN_TYPES.has(t)) &&
    [...SESSION_TWO_GEN_TYPES].every(t => pyTwo.has(t)),
    'E: 锁② SESSION_TWO_GEN_TYPES py==ts 逐项互等')
  // C5② 独立锚：原 6 项 + 超集关键成员未被顺手清理（先例 workflow-list-topology D 段）
  const anchors1 = ['request/context', 'request/header', 'assistant/message',
    'assistant/chunk', 'session', 'tool/call']
  ok(anchors1.every(t => SESSION_KNOWN_TYPES.has(t)), 'E: 锚 t260917-05 原 6 项原样')
  const anchors2 = ['text-chunks', 'reasoning-chunks', 'tool-call-chunks', 'session',
    'permission/preset', 'sandbox/mode', 'approval/policy', 'session/title',
    'llm/retry-started', 'tool/code-dispatch']
  ok(anchors2.every(t => SESSION_TWO_GEN_TYPES.has(t)), 'E: 锚 超集关键成员原样')
  // 文档注释互指锚：改动提示两侧必须同批（KI-046 双向锁的语义面）
  ok(engSrc.includes('agent-live.ts') && engSrc.includes('t260922-02-session-type-face.mjs'),
    'E: engine 注释互指 TS 侧与对侧测试（同批变更提醒在场）')
}

console.log(`\nT260922_02_SESSION_TYPE_FACE_TESTS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
