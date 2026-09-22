/**
 * t260922-06 summarize.js 单测（node --test；零外部依赖，不碰真 dsh）。
 *
 * 覆盖面（与 summarize.js 头注取舍表逐项对锚）：
 * - 取舍① seq 缺口响亮点名；② 半开区间/空 range；③ SessionSeq 校验原样透传不包装；
 *   ④ content 形状守卫（stock 裸 TypeError 的加固位）；⑤ 聚合语义 golden（双形状等价）；
 * - 形状面：未知形状/events 非数组/缺 SessionSeq/seq 非法 → ShapeError 点名，绝不裸崩；
 * - 词汇表 golden：现行四条 stderr 文案逐字（0.1.1 回归锚）。
 * 畸形输入族全部用桩/固定文件式构造，不依赖任何外部源。
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { summarizeSession, ShapeError, messages } from '../summarize.js'

// ---------- 桩构造 ----------

/** 造一条事件。 */
function ev(seq, type, data) {
  return { seq, type, data }
}

/** legacy（0.1.1）形状：events 快照数组。 */
function legacySession(events) {
  return { events }
}

/** v3（0.1.5+）形状：eventAt(seq) + seq 长度位；gaps=不可读 seq 集合（取舍①）。 */
function v3Session(events, { gaps = [], seqOverride } = {}) {
  return {
    seq: seqOverride === undefined ? events.length : seqOverride,
    eventAt: (s) => (gaps.includes(s) ? undefined : events[s]),
  }
}

/** stock 0.1.5 dsh-session SessionSeq 的同款校验（测试桩：证明「原样透传、不二次包装」）。 */
function strictSessionSeq(value) {
  if (!Number.isSafeInteger(value) || value < 0 || Object.is(value, -0)) {
    throw new TypeError(`SessionSeq must be a non-negative safe integer, got ${String(value)}`)
  }
  return value
}

/** 一段标准事件流：firstSeq=2 起算一轮 turn。 */
function sampleEvents() {
  return [
    ev(0, 'request/context', { provider: 'p', model: 'm' }),
    ev(1, 'turn/start', {}),                       // firstSeq 之前 → 不消费
    ev(2, 'turn/start', {}),                       // 本轮起点
    ev(3, 'assistant/message', { message: { content: [
      { type: 'text', text: '第一段' },
      { type: 'tool_use', text: '不该进文本' },
      { type: 'text', text: '第二段' },
    ] } }),
    ev(4, 'assistant/message', { message: { content: [
      { type: 'text', text: '' },                  // 空拼接不覆盖前值
    ] } }),
    ev(5, 'turn/end', { reason: { kind: 'completed' } }),
    ev(6, 'turn/start', {}),                       // 第二轮
    ev(7, 'assistant/message', { message: { content: [
      { type: 'text', text: '最终答复' },
    ] } }),
    ev(8, 'turn/end', { reason: { kind: 'error', error: { code: 'X', message: 'y' } } }),
  ]
}

const GOLDEN = { text: '最终答复', reason: { kind: 'error', error: { code: 'X', message: 'y' } } }

// ---------- 取舍⑤ 聚合语义 golden（双形状等价） ----------

test('取舍⑤ 聚合语义 golden：legacy 形状', () => {
  assert.deepEqual(summarizeSession(legacySession(sampleEvents()), 2), GOLDEN)
})

test('取舍⑤ 聚合语义 golden：v3 形状与 legacy 等价', () => {
  assert.deepEqual(summarizeSession(v3Session(sampleEvents()), 2, strictSessionSeq), GOLDEN)
})

test('取舍⑤ turn/start 之前的事件不消费（门控）', () => {
  const events = [
    ev(0, 'assistant/message', { message: { content: [{ type: 'text', text: '轮前' }] } }),
    ev(1, 'turn/end', { reason: { kind: 'completed' } }),
    ev(2, 'turn/start', {}),
    ev(3, 'assistant/message', { message: { content: [{ type: 'text', text: '轮内' }] } }),
  ]
  assert.deepEqual(summarizeSession(legacySession(events), 0),
    { text: '轮内', reason: undefined })
  assert.deepEqual(summarizeSession(v3Session(events), 0, strictSessionSeq),
    { text: '轮内', reason: undefined })
})

test('取舍② 半开区间 [firstSeq, seq)：firstSeq==seq 为空 range', () => {
  const events = sampleEvents()
  assert.deepEqual(summarizeSession(legacySession(events), 99), { text: '', reason: undefined })
  assert.deepEqual(summarizeSession(v3Session(events), 99, strictSessionSeq),
    { text: '', reason: undefined })
})

test('取舍② firstSeq 截掉前缀事件（legacy 过滤与 v3 半开区间同义）', () => {
  const events = sampleEvents()
  // firstSeq=6：只吃第二轮（seq 6..8）
  assert.deepEqual(summarizeSession(legacySession(events), 6),
    { text: '最终答复', reason: GOLDEN.reason })
  assert.deepEqual(summarizeSession(v3Session(events), 6, strictSessionSeq),
    { text: '最终答复', reason: GOLDEN.reason })
})

// ---------- 取舍① seq 缺口 ----------

test('取舍① seq 缺口 → ShapeError 点名 seq 与长度（不裸崩）', () => {
  const events = sampleEvents()
  const session = v3Session(events, { gaps: [4] })
  assert.throws(() => summarizeSession(session, 2, strictSessionSeq), (err) => {
    assert.ok(err instanceof ShapeError)
    assert.match(err.message, /seq 4 不可读/)
    assert.match(err.message, /已捕获长度 9/)
    return true
  })
})

// ---------- 取舍③ SessionSeq 校验原样透传 ----------

test('取舍③ SessionSeq 校验异常原样透传（不二次包装、非 ShapeError）', () => {
  const events = sampleEvents()
  assert.throws(() => summarizeSession(v3Session(events), -1, strictSessionSeq), (err) => {
    assert.ok(err instanceof TypeError)
    assert.ok(!(err instanceof ShapeError))
    assert.equal(err.message,
      'SessionSeq must be a non-negative safe integer, got -1')
    return true
  })
})

// ---------- 取舍④ content 形状守卫 ----------

test('取舍④ content 非数组 → ShapeError 点名 type/seq', () => {
  const events = [
    ev(0, 'turn/start', {}),
    ev(1, 'assistant/message', { message: { content: '不是数组' } }),
  ]
  for (const session of [legacySession(events), v3Session(events)]) {
    assert.throws(() => summarizeSession(session, 0, strictSessionSeq), (err) => {
      assert.ok(err instanceof ShapeError)
      assert.match(err.message, /type=assistant\/message seq=1/)
      assert.match(err.message, /data\.message\.content 非数组/)
      return true
    })
  }
})

test('取舍④ data.message 链断裂 → ShapeError 点名（stock 裸 TypeError 的加固位）', () => {
  // 每个起点都带 turn/start（轮前事件被门控跳过是既有语义，不属守卫半径）
  const events = [
    ev(0, 'turn/start', {}),
    ev(1, 'assistant/message', { message: null }),
    ev(2, 'turn/start', {}),
    ev(3, 'assistant/message', {}),
  ]
  const session = legacySession(events)
  assert.throws(() => summarizeSession(session, 0), (err) => {
    assert.ok(err instanceof ShapeError)
    assert.match(err.message, /seq=1/)
    return true
  })
  assert.throws(() => summarizeSession(session, 2), (err) => {
    assert.ok(err instanceof ShapeError)
    assert.match(err.message, /seq=3/)
    return true
  })
})

test('取舍④ text 块缺 text 字段 → 容忍（join 语义记空串，非崩点）', () => {
  const events = [
    ev(0, 'turn/start', {}),
    ev(1, 'assistant/message', { message: { content: [{ type: 'text' }, { type: 'text', text: '有字' }] } }),
    ev(2, 'turn/end', { reason: { kind: 'completed' } }),
  ]
  assert.deepEqual(summarizeSession(legacySession(events), 0),
    { text: '有字', reason: { kind: 'completed' } })
})

// ---------- 形状面：未知形状一律响亮点名 ----------

test('形状不识别族（无 eventAt 无 events / events 非数组 / null）→ ShapeError', () => {
  for (const session of [{}, { events: '不是数组' }, { eventAt: '不是函数' }, null, undefined]) {
    assert.throws(() => summarizeSession(session, 0, strictSessionSeq), (err) => {
      assert.ok(err instanceof ShapeError)
      assert.match(err.message, /会话事件读取面形状不识别/)
      assert.match(err.message, /拒绝静默猜测/)
      return true
    })
  }
})

test('eventAt 在场但 SessionSeq 未注入 → ShapeError 点名（0.1.1 下不会走到 v3 判定）', () => {
  const events = [ev(0, 'turn/start', {})]
  assert.throws(() => summarizeSession(v3Session(events), 0, undefined), (err) => {
    assert.ok(err instanceof ShapeError)
    assert.match(err.message, /SessionSeq 铸造器不在场/)
    return true
  })
})

test('session.seq 非非负安全整数 → ShapeError 点名', () => {
  for (const bad of [undefined, -1, 1.5, Number.NaN, '3']) {
    // seq 非法位直接显式构造（不走桩的缺省回退），守卫必须在迭代前点名
    const session = { seq: bad, eventAt: () => undefined }
    assert.throws(() => summarizeSession(session, 0, strictSessionSeq), (err) => {
      assert.ok(err instanceof ShapeError)
      assert.match(err.message, /session\.seq 非非负安全整数/)
      return true
    })
  }
})

// ---------- 词汇表 golden（0.1.1 回归锚：现行文案逐字） ----------

test('messages golden：现行四条 stderr 文案逐字（对照改前 node.ts 原文）', () => {
  assert.equal(messages.resumed('t260922-06-developer'),
    'dsh-headless-resume: 已恢复会话 t260922-06-developer\n')
  assert.equal(
    messages.resumeFailedFallbackCreate('t260922-06-developer',
      'session "t260922-06-developer" not found'),
    'dsh-headless-resume: 恢复会话 t260922-06-developer 失败（回落新建同 id 会话）：' +
    'session "t260922-06-developer" not found\n')
  assert.equal(
    messages.sameIdCreateFailedFresh('zstd: corrupted frame'),
    'dsh-headless-resume: 同 id 新建仍失败（zstd: corrupted frame）' +
    '——会话存储疑似损坏，改用全新会话 id（上下文不可恢复，工单侧应检疫坏文件）\n')
  assert.equal(messages.fail('boom'), 'dsh: boom\n')
})

test('messages 形状面文案自点名（组件前缀 + 拒绝静默声明）', () => {
  for (const m of [
    messages.agentReturnShape('resume'),
    messages.agentReturnShape('create'),
    messages.sessionShapeUnknown(),
    messages.sessionSeqMissing(),
    messages.seqNotReadable(3, 9),
    messages.eventCorrupt('assistant/message', 3, 'x'),
  ]) {
    assert.match(m, /^headless-resume: /)
    assert.match(m, /——/)
  }
  assert.match(messages.agentReturnShape('resume'), /agents\.resume/)
  assert.match(messages.agentReturnShape('create'), /agents\.create/)
})
