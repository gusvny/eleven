/**
 * 判活（t260928-28，纯函数核）——三个显式带时间戳状态。
 *
 * ① watchdog 自身心跳：interval touch `watchdog/<key>.heartbeat.json`；面板（或本插件
 *    重挂后）读 mtime 判「守望者死了」——心跳是守望者唯一能自证活着的东西。
 * ② 引擎存活：7233 端口探 + worker pidfile（只读；照 workbench temporal-health 判形，
 *    不重启不占用——3099/7233 红线）。
 * ③ executor 推进判定：**进展驱动**（账本新行 / 会话文件 size-mtime 前进 / 最近唤醒
 *    任一 = 有进展），墙钟（默认 15min，260ee79 教训）只作偏宽上限兜底；「我这边没
 *    信号（no_signal）」与「它卡住了（stalled）」分开报，休眠场景两者同现时不混报
 *    （KI-138）。时钟注入（nowMs 参数），测试可换桩。
 * ④ executor 的 running 位（t261004-12）：会话在跑（长回合中）≠ 卡住。长回合整段
 *    不落消息、守望者也不补发简报（上条未消化）、账本不动——三个旧信号全静默，但
 *    会话明明在跑。旧判定把这种拍在 stall_minutes 后误判 stalled（假红线），真卡住
 *    与之同形。修法：把会话 running 位作为**加法信号**喂进判定——
 *      - running=true 且无推进：不是停摆；静默未超 long_turn 阈值照常 advancing，
 *        超过报独立态 long_turn（自己的措辞，不是 stall）；
 *      - running=false：旧的 stall_minutes 路径逐字保留（真卡住照报）；
 *      - running 位读不到（null）：显式 unknown（no_signal），绝不冒充正常、也绝不
 *        据一条读不到的位打红线。真死的会话仍由 missing/executor_missing 报。
 *    静默计时基准 last_progress_at 只在 progressed 分支拨动——宽限拍与 long_turn 拍
 *    都不动它（t261001-19 缺陷 A 同形雷：宽限拍回拨时钟 ⇒ 后续分支永不可达）。
 */

export type ExecutorLivenessState = 'advancing' | 'stalled' | 'no_signal' | 'missing' | 'long_turn'

export interface ExecutorLiveness {
  state: ExecutorLivenessState
  last_progress_at: number | null
  stall_minutes: number
  /** 本拍读到的会话 running 位（null = 没读到，显式 unknown；t261004-12 状态面暴露位）。 */
  session_running: boolean | null
  evidence: string
  checked_at: number
}

export interface ProgressSignals {
  /** 是否配置了 executor 会话（未配置/会话不存在 = missing，显式）。 */
  sessionKnown: boolean
  /** 本轮对账周期内账本有新行（任何票）。 */
  ledgerAdvanced: boolean
  /** executor 会话文件（size,mtime）相对上次有前进；null = 没读到（显式 no-signal 来源）。 */
  sessionProgress: boolean | null
  /** 最近一次成功唤醒的时刻（null = 没有）。 */
  lastWakeAt: number | null
  /** executor 会话本拍是否在跑（宿主 session API 的 running 位）；null = 本拍没读到
   *  （list 缺席/调用失败/会话不在列）——显式 unknown，绝不折叠成「正常」。 */
  sessionRunning: boolean | null
}

/** 推进判定（纯函数）。墙钟只在「有信号但无推进」时兜底判 stalled。
 *  longTurnMinutes 缺省 = stallMinutes × 3（与 config 出厂默认 45 = 3×15 同式；
 *  调用方（core）显式传配置值）。 */
export function judgeExecutor(
  signals: ProgressSignals,
  nowMs: number,
  stallMinutes: number,
  lastProgressAt: number | null,
  longTurnMinutes: number = stallMinutes * 3,
): ExecutorLiveness {
  const base: ExecutorLiveness = {
    state: 'advancing', last_progress_at: lastProgressAt, stall_minutes: stallMinutes,
    session_running: signals.sessionRunning ?? null,
    evidence: '', checked_at: nowMs,
  }
  if (!signals.sessionKnown) {
    return { ...base, state: 'missing', evidence: '该项目未声明 executor_session（或会话尚未建立）——显式 missing，不冒充正常' }
  }
  const progressed = signals.ledgerAdvanced || signals.sessionProgress === true ||
    (signals.lastWakeAt !== null && (lastProgressAt === null || signals.lastWakeAt > lastProgressAt))
  if (progressed) {
    const ev = [
      signals.ledgerAdvanced ? '账本新行' : null,
      signals.sessionProgress === true ? '会话文件前进' : null,
      signals.lastWakeAt !== null && (lastProgressAt === null || signals.lastWakeAt > lastProgressAt) ? '最近有唤醒' : null,
    ].filter(Boolean).join(' + ')
    return { ...base, state: 'advancing', last_progress_at: nowMs, evidence: ev }
  }
  // —— 以下全为「无推进」拍；除 no_signal 例外，静默计时都从 last_progressAt 起算，
  // 且**不**拨动 last_progress_at（回灌安全，见文件头④）。
  // running 位读不到 = 显式 unknown：绝不据读不到的位判 stalled（假红线反方向），
  // 也不冒充正常；真死的会话由 missing/executor_missing 规则另报。
  if (signals.sessionRunning !== true && signals.sessionRunning !== false) {
    return { ...base, state: 'no_signal', evidence: '无推进且会话 running 位不可读（本拍 list 缺席/调用失败/会话不在列）——显式 unknown，不判停摆也不冒充正常' }
  }
  if (lastProgressAt === null) {
    return { ...base, state: 'no_signal', evidence: '从无推进记录——历史不可读，数据可能过期' }
  }
  if (signals.sessionProgress === null) {
    return { ...base, state: 'no_signal', evidence: '守望者读不到会话推进信号（会话文件不可读）且账本无新行——数据可能过期（宿主休眠/守望者停摆），不等于它卡住了' }
  }
  const silentMs = nowMs - lastProgressAt
  const silentMin = Math.round(silentMs / 60_000)
  if (signals.sessionRunning === true) {
    // 会话在跑（长回合中）：不是停摆。静默超长回合阈值报独立态 long_turn（自己的
    // state + 自己的措辞），levels/alerts 由调用方按 state 分流。
    if (silentMs >= longTurnMinutes * 60_000) {
      return {
        ...base, state: 'long_turn',
        evidence: `会话 running=true 且 ${silentMin} 分钟无消息/账本推进（长回合阈值 ${longTurnMinutes} 分钟；stall 阈值 ${stallMinutes} 分钟）——判定来源：running 位，非停摆，长回合偏长需人看一眼`,
      }
    }
    return {
      ...base, state: 'advancing',
      evidence: `无新推进但会话 running=true（长回合进行中；静默 ${silentMin} < 长回合阈值 ${longTurnMinutes} 分钟）——判定来源：running 位，非停摆`,
    }
  }
  // running=false：旧的 stall 路径逐字保留（真卡住照报，不因新信号弱化）。
  if (silentMs >= stallMinutes * 60_000) {
    return {
      ...base, state: 'stalled',
      evidence: `会话 running=false 且 ${silentMin} 分钟无推进（阈值 ${stallMinutes} 分钟；进展=账本/会话文件/唤醒三源任一），墙钟只作偏宽兜底——判定来源：running=false 位`,
    }
  }
  // t261001-19 缺陷 A：宽限拍显式声明 state='advancing'（不再隐式吃 base 默认值）。
  // 语义 =「有信号但在停摆宽限窗内」；state==='advancing' 在这里**不**意味着时钟可以
  // 重新起算——静默计时以 last_progress_at 为准，由调用方从返回值回灌（core 侧修复）。
  return {
    ...base, state: 'advancing',
    evidence: `无新推进但未达阈值（静默 ${silentMin} < ${stallMinutes} 分钟；会话 running=false）`,
  }
}

/** 心跳文件的读写形状（io 注入；坏/缺文件显式 stale，不静默当新鲜）。 */
export interface HeartbeatIo {
  write(path: string, data: string): Promise<void>
  read(path: string): Promise<string>
  mtimeMs(path: string): Promise<number | null>
}

export async function touchHeartbeat(io: HeartbeatIo, path: string, nowMs: number): Promise<void> {
  // 写失败由调用方点名（fail-open 且 LOUD，照 event_ledger 先例）：心跳写不进本身就是
  // 「守望者将不可自证」的故障，抛给 core 计数。
  await io.write(path, JSON.stringify({ last_beat: nowMs }))
}

/** 读心跳判活：stalenessMs 内 = alive；读不到/解析坏 = alive:false + reason（显式）。 */
export async function readHeartbeat(
  io: HeartbeatIo, path: string, nowMs: number, stalenessMs: number,
): Promise<{ last_beat: number | null; age_seconds: number | null; alive: boolean; reason: string | null }> {
  let raw: string | null = null
  try {
    raw = await io.read(path)
  } catch { /* 无文件 */ }
  if (raw !== null) {
    try {
      const doc = JSON.parse(raw) as { last_beat?: unknown }
      if (typeof doc.last_beat === 'number' && Number.isFinite(doc.last_beat)) {
        const age = (nowMs - doc.last_beat) / 1000
        return { last_beat: doc.last_beat, age_seconds: age, alive: age * 1000 <= stalenessMs, reason: null }
      }
    } catch { /* 坏文件 → 落 reason */ }
  }
  const mtime = await io.mtimeMs(path).catch(() => null)
  if (mtime !== null) {
    const age = (nowMs - mtime) / 1000
    return { last_beat: null, age_seconds: age, alive: age * 1000 <= stalenessMs, reason: '心跳文件存在但内容不可解析——按 mtime 判活' }
  }
  return { last_beat: null, age_seconds: null, alive: false, reason: '无心跳文件（守望者从未起过或已死）——显式降级，不是一切正常' }
}
