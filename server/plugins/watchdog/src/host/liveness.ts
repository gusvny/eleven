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
 */

export type ExecutorLivenessState = 'advancing' | 'stalled' | 'no_signal' | 'missing'

export interface ExecutorLiveness {
  state: ExecutorLivenessState
  last_progress_at: number | null
  stall_minutes: number
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
}

/** 推进判定（纯函数）。墙钟只在「有信号但无推进」时兜底判 stalled。 */
export function judgeExecutor(
  signals: ProgressSignals,
  nowMs: number,
  stallMinutes: number,
  lastProgressAt: number | null,
): ExecutorLiveness {
  const base: ExecutorLiveness = {
    state: 'advancing', last_progress_at: lastProgressAt, stall_minutes: stallMinutes,
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
  if (signals.sessionProgress === null && !signals.ledgerAdvanced) {
    return { ...base, state: 'no_signal', evidence: '守望者读不到任何推进信号（账本无新行 + 会话文件不可读）——数据可能过期（宿主休眠/守望者停摆），不等于它卡住了' }
  }
  const last = lastProgressAt ?? 0
  const silentMs = nowMs - last
  if (lastProgressAt === null) {
    return { ...base, state: 'no_signal', evidence: '从无推进记录——历史不可读，数据可能过期' }
  }
  if (silentMs >= stallMinutes * 60_000) {
    return {
      ...base, state: 'stalled',
      evidence: `有信号但 ${Math.round(silentMs / 60_000)} 分钟无推进（阈值 ${stallMinutes} 分钟；进展=账本/会话文件/唤醒三源任一），墙钟只作偏宽兜底`,
    }
  }
  // t261001-19 缺陷 A：宽限拍显式声明 state='advancing'（不再隐式吃 base 默认值）。
  // 语义 =「有信号但在停摆宽限窗内」；state==='advancing' 在这里**不**意味着时钟可以
  // 重新起算——静默计时以 last_progress_at 为准，由调用方从返回值回灌（core 侧修复）。
  return {
    ...base, state: 'advancing',
    evidence: `无新推进但未达阈值（静默 ${Math.round(silentMs / 60_000)} < ${stallMinutes} 分钟）`,
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
