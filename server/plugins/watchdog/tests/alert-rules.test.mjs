// alert-rules UT：夜间口径（含跨午夜/边界）/ 红线例外 / 冷却节流 / 重放重建（重启不重播）。
import { makeKey, isNight, nightMuted, cooldownExpired, replayDedupe, judgeAlert, applyDedupe } from '../src/host/alert-rules.ts'
import { FACTORY_DEFAULTS } from '../src/host/config.ts'
import { assert, done } from './lib.mjs'

let n = 0
const baseCfg = FACTORY_DEFAULTS
const at = (h, m) => { const d = new Date(1_700_000_000_000); d.setHours(h, m, 0, 0); return d.getTime() }
const spec = (rule, level) => ({ rule, target: 't1', level, title: 'x' })

// 夜间判定：窗内/窗外/跨午夜/边界/零长窗。
{
  const night = { start: '23:00', end: '07:30', policy: 'redline-only' }
  assert(isNight(night, at(23, 0)) === true, 'night boundary start inclusive')
  assert(isNight(night, at(7, 29)) === true, 'night cross-midnight early morning inside')
  assert(isNight(night, at(7, 30)) === false, 'night boundary end exclusive (counted once)')
  assert(isNight(night, at(12, 0)) === false, 'daytime outside window')
  assert(isNight({ start: '09:00', end: '18:00', policy: 'silent' }, at(12, 0)) === true, 'non-crossing window works')
  assert(isNight({ start: '08:00', end: '08:00', policy: 'silent' }, at(12, 0)) === false, 'zero-length window = never night (explicit)')
  n += 6
}
// 夜间策略 × 红线例外。
{
  const night = { start: '23:00', end: '07:30', policy: 'redline-only' }
  const cfg = { ...baseCfg, alerts: { ...baseCfg.alerts, night } }
  assert(nightMuted(cfg, spec('stall', 'redline'), at(23, 30)) === false, 'redline still speaks at night (factory redline-only)')
  assert(nightMuted(cfg, spec('stall', 'warn'), at(23, 30)) === true, 'warn muted at night (redline-only)')
  assert(nightMuted(cfg, spec('wake_failed', 'redline'), at(23, 30)) === true, 'redline level but rule not in redline list → muted')
  const silent = { ...baseCfg, alerts: { ...baseCfg.alerts, night: { ...night, policy: 'silent' } } }
  assert(nightMuted(silent, spec('stall', 'redline'), at(23, 30)) === true, 'silent policy mutes even redline (config, not hardcoded)')
  const normal = { ...baseCfg, alerts: { ...baseCfg.alerts, night: { ...night, policy: 'normal' } } }
  assert(nightMuted(normal, spec('x', 'info'), at(23, 30)) === false, 'normal policy speaks at night')
  assert(nightMuted(cfg, spec('stall', 'redline'), at(12, 0)) === false, 'daytime never muted')
  n += 6
}
// 冷却节流 + 状态更新。
{
  const clockAt = 1_700_000_000_000
  const state = new Map()
  const s = spec('stall', 'redline')
  const j1 = judgeAlert(baseCfg, s, state, clockAt, 60_000)
  assert(j1.record === true, 'first alert records')
  applyDedupe(state, j1.key, clockAt)
  const j2 = judgeAlert(baseCfg, s, state, clockAt + 30_000, 60_000)
  assert(j2.record === false, 'same key within cooldown does not re-alert (一声就够)')
  const j3 = judgeAlert(baseCfg, s, state, clockAt + 61_000, 60_000)
  assert(j3.record === true, 'cooldown expiry re-alerts')
  const j4 = judgeAlert(baseCfg, { ...s, target: 't2' }, state, clockAt + 1_000, 60_000)
  assert(j4.record === true, 'different target = different key = independent')
  assert(j4.key === makeKey('stall', 't2'), 'key shape rule:target')
  n += 5
}
// 实例隔离域（t261001-19 缺陷 B 回归钉）：scope 进 key；临时 home 与真宿主互不静音；
// 空/缺 scope 保持历史形状（旧账重放兼容）。
{
  assert(makeKey('r', 't', '/a') === 'r:t@/a', 'scoped key shape rule:target@scope')
  assert(makeKey('r', 't') === 'r:t' && makeKey('r', 't', '') === 'r:t', 'missing/empty scope keeps historical key shape')
  const state = new Map()
  const clockAt = 1_700_000_000_000
  const sa = { rule: 'executor_session_refused', target: 'sandbar', level: 'redline', title: 'x', scope: '/tmp/scene-home' }
  const j1 = judgeAlert(baseCfg, sa, state, clockAt, 60_000)
  assert(j1.record === true && j1.key === 'executor_session_refused:sandbar@/tmp/scene-home', 'scoped alert records with scoped key')
  applyDedupe(state, j1.key, clockAt)
  const sb = { ...sa, scope: '/Users/xingu/.dsh' }
  const j2 = judgeAlert(baseCfg, sb, state, clockAt + 1000, 60_000)
  assert(j2.record === true, 'same rule+target from a different instance scope still records (temp-home must not mute real host)')
  applyDedupe(state, j2.key, clockAt + 1000)
  const j3 = judgeAlert(baseCfg, sa, state, clockAt + 2000, 60_000)
  assert(j3.record === false, 'same scope within cooldown stays deduped')
  const j4 = judgeAlert(baseCfg, { rule: 'executor_session_refused', target: 'sandbar', level: 'redline', title: 'x' }, state, clockAt + 3000, 60_000)
  assert(j4.record === true && j4.key === 'executor_session_refused:sandbar', 'unscoped (legacy) key independent of scoped keys')
  n += 6
}
// 重放重建：重启不重播 12 小时；畸形行不入状态；保留窗外的行不进。
{
  const now = 1_700_100_000_000
  const rows = [
    { key: 'stall:s1', at: now - 3600_000 },          // 1h 前：在状态里（冷却内不重播）
    { key: 'stall:s1', at: now - 1800_000 },          // 同 key 二次：count 累加、lastAt 取新
    { key: 'stall:s2', at: now - 20 * 24 * 3600_000 }, // 20 天前：超 14d 保留窗 → 不入
    { key: '', at: now - 1000 },                       // 畸形：无 key
    { key: 'x:y', at: 'not-a-number' },                // 畸形：坏时刻
  ]
  const st = replayDedupe(rows, 14, now)
  assert(st.get('stall:s1')?.count === 2 && st.get('stall:s1')?.lastAt === now - 1800_000, 'replay merges same key, keeps latest at')
  assert(!st.has('stall:s2'), 'replay drops beyond keep_days window (restart must not replay old history)')
  assert(st.size === 1, 'replay skips malformed rows')
  const fresh = replayDedupe([], 14, now)
  assert(fresh.size === 0, 'replay of empty ledger = empty state')
  n += 4
}
done(n)
