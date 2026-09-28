/**
 * dsh-headless-resume 的会话事件读取/聚合纯函数层（t260922-06，seam 矩阵 #5 resume 专项）。
 *
 * 为什么拆这个文件：node.ts 顶层经 createRequire 动态 import dsh 内部包，脱离 dsh
 * 运行时无法加载 → 无法单测。本文件零依赖（不 import 任何包），node --test 直接可测；
 * node.ts 以显式 URL 动态 import 本文件（绕开 TS loader 的相对导入别名面，见 node.ts 头注）。
 *
 * 背景一句话：dsh 0.1.5 移除了 `Session.events` 快照数组（stock runner 改走
 * `session.eventAt(SessionSeq(seq))` 半开区间 `[firstSeq, session.seq)`），旧插件在
 * 0.1.5 下每次 spawn 收尾抛 `events is not iterable`（跑完再崩、退出码 1）——这就是
 * t260922-06 的真崩点。0.1.1/0.1.5 的会话 id 寻址口径无漂移（自定义 id 原生全链路
 * 有效：目录名=encodeSegment(id)、头记录 id=自定义 id、resume 按该 id 全项目扫描），
 * 单点真源=自定义 id 本身，无需任何映射表（源码证据链见
 * .sandbar/plan_t260922-06_resume_addressing.md）。
 *
 * 对标实现的故障模式取舍（参考实现 = stock dsh 0.1.5 headless runner 的 summarize；
 * 格式先例 = docs/design/dsh-seam-requirements-v1.md「对标实现的故障模式取舍」表）：
 *
 * | stock 0.1.5 故障模式                                   | 带进本实现？ | 理由与测试锚 |
 * | ------------------------------------------------------ | ---- | ---- |
 * | ① seq 缺口：eventAt→undefined 时响亮抛「cannot read seq X below captured length Y」 | 带（文案改插件点名体） | 基础设施漂移必须响亮点名 seq/长度；测试 `取舍① seq 缺口` |
 * | ② 半开区间 [firstSeq, session.seq)：stock 循环语义       | 带 | 与 0.1.1 events 数组 + seq 过滤语义等价；测试 `取舍② 半开区间`/`空 range` |
 * | ③ SessionSeq 品牌铸造校验（非负安全整数，非法抛 TypeError 且消息自点名） | 带照搬，不二次包装 | node.ts 注入 dsh 真 SessionSeq；本层只透传其异常（fail() 单点兜住）；测试 `取舍③ SessionSeq 校验原样透传` |
 * | ④ assistant/message 的 content 非数组 / data.message 链断裂：stock 无防护（裸 TypeError） | 不带裸崩，加固为响亮点名 | 本实现是 stock 超集：点名字段与 seq，绝不裸崩；测试 `取舍④ content 形状守卫` |
 * | ⑤ turn/start 门控、多 text 块拼接、空拼接不覆盖前值（joined!==''） | 带（golden 逐字锚） | 聚合语义 0.1.1→0.1.5 零漂移；测试 `取舍⑤ 聚合语义 golden` |
 * | ⑥ 聚合层无 try/catch 冒泡顶层                            | 带 | node.ts apply() 的 fail() 单点 catch-all 兜住一切（`dsh: <msg>` + exit 1）；集成面行为，本层不重复捕 |
 *
 * 实现纪律：本层不做 IO、不读环境变量、不打日志；一切形状违约 = 抛 ShapeError
 * （消息自点名、带 `headless-resume: ` 前缀），由 node.ts fail() 单点落 stderr。
 * 0.1.1 回归锚：legacy 路径的 stderr 文案经 messages 词汇表逐字保持（golden 测试锁死）。
 */

/** 形状违约专用错误：消息必须自点名（组件前缀 + 漂移面 + 拒绝静默声明）。 */
export class ShapeError extends Error {}

/** stderr 词汇表（单点真源）：现行四条逐字锚 + 新增形状面点名。node.ts 只从这里取文案。 */
export const messages = {
  /** resume 成功（现行 :104 逐字）。 */
  resumed: (id) => `dsh-headless-resume: 已恢复会话 ${id}\n`,
  /** resume 失败回落同 id 新建（现行 :106-108 逐字——禁静默：「回落新建」显式点名）。 */
  resumeFailedFallbackCreate: (id, err) =>
    `dsh-headless-resume: 恢复会话 ${id} 失败（回落新建同 id 会话）：${err}\n`,
  /** 同 id 新建也失败 → 换全新 id（现行 :120-122 逐字——上下文丢失大声说）。 */
  sameIdCreateFailedFresh: (err) =>
    `dsh-headless-resume: 同 id 新建仍失败（${err}）` +
    `——会话存储疑似损坏，改用全新会话 id（上下文不可恢复，工单侧应检疫坏文件）\n`,
  /** 意外故障统一出口（现行 fail() :82 逐字）。 */
  fail: (err) => `dsh: ${err}\n`,

  // ---- 新增形状面点名（t260922-06 验收②：响亮报错点名，不得崩栈）----

  /** agents.resume / agents.create 返回形状漂移（缺 .agent；判式 r?.agent == null 兼抓 null/undefined）。 */
  agentReturnShape: (op) =>
    `headless-resume: agents.${op} 返回形状不识别（缺 .agent 字段）` +
    `——dsh 版本接缝漂移（矩阵 #5 resume 专项），拒绝静默猜测`,
  /** 会话对象既无 eventAt 也无 events 数组（0.1.x 之外的未知形状）。 */
  sessionShapeUnknown: () =>
    `headless-resume: 会话事件读取面形状不识别（session.eventAt(seq) 与 session.events 数组均不在场）` +
    `——dsh 版本接缝漂移（0.1.x Session 形状变更？），拒绝静默猜测`,
  /** eventAt 在场但 SessionSeq 铸造器未注入（0.1.5 语义下不该发生 → 点名）。 */
  sessionSeqMissing: () =>
    `headless-resume: session.eventAt 在场但 SessionSeq 铸造器不在场` +
    `——dsh 版本接缝漂移，拒绝静默猜测`,
  /** session.seq 非非负安全整数（v3 路径长度位漂移）。 */
  seqBad: (v) =>
    `headless-resume: session.seq 非非负安全整数（${String(v)}）` +
    `——会话形状漂移，拒绝静默猜测`,
  /** v3 路径 seq 缺口（取舍①，对齐 stock 响亮语义）。 */
  seqNotReadable: (seq, length) =>
    `headless-resume: 会话事件 seq ${seq} 不可读（已捕获长度 ${length}）` +
    `——事件面形状/内容漂移`,
  /** 事件内容形状违约（取舍④加固位；type/seq 定位到条）。 */
  eventCorrupt: (type, seq, why) =>
    `headless-resume: 会话事件形状不识别（type=${type} seq=${seq}：${why}）` +
    `——事件内容漂移，拒绝静默猜测`,
}

/** v3（0.1.5+）形状判定：eventAt 函数在场。 */
function hasEventAt(session) {
  return session !== null && typeof session === 'object' &&
    typeof session.eventAt === 'function'
}

/** legacy（0.1.1）形状判定：events 快照数组在场。 */
function hasLegacyEvents(session) {
  return session !== null && typeof session === 'object' &&
    Array.isArray(session.events)
}

/**
 * 把会话对象归一成事件序列（生成分配最小化）：
 * - v3：按半开区间 [firstSeq, session.seq) 逐条 eventAt(SessionSeq(seq))——取舍②；
 *   SessionSeq 原样注入调用（取舍③，异常透传不包装）；缺口响亮点名（取舍①）。
 * - legacy：events 数组全量遍历、seq < firstSeq 跳过——与现行 node.ts 逐字同语义。
 * - 两者皆否：ShapeError（形状面点名，绝不裸 `events is not iterable`）。
 */
function* iterSessionEvents(session, firstSeq, sessionSeq) {
  if (hasEventAt(session)) {
    if (typeof sessionSeq !== 'function') throw new ShapeError(messages.sessionSeqMissing())
    const length = session.seq
    if (!Number.isSafeInteger(length) || length < 0 || Object.is(length, -0)) {
      throw new ShapeError(messages.seqBad(length))
    }
    for (let seq = firstSeq; seq < length; seq++) {
      const event = session.eventAt(sessionSeq(seq))
      if (event === undefined || event === null) {
        throw new ShapeError(messages.seqNotReadable(seq, length))
      }
      yield event
    }
    return
  }
  if (hasLegacyEvents(session)) {
    for (const event of session.events) {
      if (event.seq < firstSeq) continue
      yield event
    }
    return
  }
  throw new ShapeError(messages.sessionShapeUnknown())
}

/**
 * 聚合一轮产出（firstSeq 之后的 turn）：最终 assistant 文本 + turn 结局。
 * 语义 = 现行 node.ts summarize 与 stock 0.1.5 summarize 的公共交集（取舍⑤）：
 * - turn/start 之前的事件不消费；
 * - assistant/message 取全部 text 块拼接，非空才覆盖前值；
 * - turn/end 的 data.reason 作为结局（最后一轮为准）；
 * - 内容形状违约响亮点名（取舍④），不裸崩。
 *
 * @param session dsh 会话对象（agent.session）
 * @param firstSeq 起始 seq（node.ts 在 followup 前取的 agent.session.seq）
 * @param sessionSeq dsh-session 的 SessionSeq 铸造函数（仅 v3 路径需要；0.1.1 下为
 *   undefined——legacy 判定在前则不受影响，v3 判定缺它则响亮点名）
 * @returns {{text: string, reason: any}}
 */
export function summarizeSession(session, firstSeq, sessionSeq) {
  let started = false
  let text = ''
  let reason
  for (const event of iterSessionEvents(session, firstSeq, sessionSeq)) {
    const type = event.type
    if (type === 'turn/start') {
      started = true
      continue
    }
    if (!started) continue
    if (type === 'assistant/message') {
      // 取舍④：content 链断裂 = 点名（stock 裸 TypeError 的加固位）
      const data = event.data
      const message = data === null || typeof data !== 'object' ? undefined : data.message
      const content = message === null || typeof message !== 'object' ? undefined : message.content
      if (!Array.isArray(content)) {
        throw new ShapeError(messages.eventCorrupt(
          type, event.seq, 'data.message.content 非数组'))
      }
      const joined = content
        .filter((block) => block !== null && typeof block === 'object' && block.type === 'text')
        .map((block) => block.text)
        .join('')
      if (joined !== '') text = joined
    }
    if (type === 'turn/end') {
      const data = event.data
      reason = data === null || typeof data !== 'object' ? undefined : data.reason
    }
  }
  return { text, reason }
}
