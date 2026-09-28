/**
 * watchdog 配置（t260928-28）——per-project 声明与出厂默认。
 *
 * 路径纪律（KI-149 同族雷区整块绕开）：配置放 `~/.sandbar/projects/<key>/watchdog.json`
 * （env SANDBAR_WATCHDOG_DIR 覆盖根目录），**不进 project.yaml、不碰注册表装载器
 * 顶层键白名单**。文件存在 = 项目声明；未声明项目 = 零行为（工单 scope 8）。
 *
 * 保证面 / 不保证面（KI-079 族自述纪律）：
 *  - 保证：缺键回落出厂默认；畸形 JSON / 形状错 fail-closed 显式报（config_error 状态，
 *    绝不静默回落默认冒充「配置正常」）；provenance 逐旋钮答「哪个文件哪条键定的」。
 *  - 不保证：文件被并发改写的原子性（读到半截 = config_error，由写方自校验）。
 */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/** 单项目配置形状（全部可缺省，缺省回落出厂默认）。 */
export interface WatchdogConfig {
  enabled: boolean
  /** 该项目 executor 会话 id（本票只唤醒/观测，不创建——身份是后续票）。 */
  executor_session: string
  stall_minutes: number
  reconcile_seconds: number
  alerts: {
    enabled: boolean
    /** 面板消费位：本票不发声，只暴露「该响」的意图（dsh 无发声能力，已实证）。 */
    sound: boolean
    desktop: boolean
    night: { start: string; end: string; policy: 'silent' | 'redline-only' | 'normal' }
    redline: string[]
    keep_days: number
  }
}

/** 出厂默认（设计稿 260927 默认值表；改默认值改这里，不改代码逻辑）。 */
export const FACTORY_DEFAULTS: WatchdogConfig = {
  enabled: true,
  executor_session: '',
  stall_minutes: 15,
  reconcile_seconds: 60,
  alerts: {
    enabled: true,
    sound: true,
    desktop: true,
    night: { start: '23:00', end: '07:30', policy: 'redline-only' },
    redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'],
    keep_days: 14,
  },
}

/** 单项目配置解析结果（declared=false = 未声明，调用方必须零行为）。 */
export interface ResolvedConfig {
  declared: boolean
  /** enabled=false = 声明了但停 → 状态面显式 stopped，非消失。 */
  enabled: boolean
  config: WatchdogConfig
  /** 溯源：文件路径 + 逐旋钮「<file>#<json-path>」或 factory-default（KI-148/149 教训）。 */
  provenance: { file: string | null; keys: Record<string, string> }
  /** 畸形声明显式报错（fail-closed）：declared=true 且 config_error 非空 = 守望者对该项目停。 */
  config_error: string | null
}

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/
const PROJECT_KEY_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 项目 key 形状白名单（与引擎 client.py ticket-list 的 project 白名单同词表）。 */
export function isValidProjectKey(key: unknown): key is string {
  return typeof key === 'string' && PROJECT_KEY_RE.test(key)
}

/** watchdog.json 的解析与校验（纯函数核，畸形输入全走 config_error）。 */
export function parseWatchdogConfig(raw: string, file: string): ResolvedConfig {
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return {
      declared: true, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file, keys: {} },
      config_error: `watchdog.json 不是合法 JSON：${e instanceof Error ? e.message : String(e)}`,
    }
  }
  if (!isPlainObject(doc)) {
    return {
      declared: true, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file, keys: {} },
      config_error: 'watchdog.json 顶层必须是 JSON 对象',
    }
  }
  const keys: Record<string, string> = {}
  const cfg: WatchdogConfig = structuredClone(FACTORY_DEFAULTS)
  const problems: string[] = []

  if ('enabled' in doc) {
    if (typeof doc.enabled !== 'boolean') problems.push('enabled 必须是 boolean')
    else { cfg.enabled = doc.enabled; keys.enabled = `${file}#enabled` }
  }
  if ('executor_session' in doc) {
    if (typeof doc.executor_session !== 'string' || doc.executor_session === '') {
      problems.push('executor_session 必须是非空字符串（会话 id）')
    } else { cfg.executor_session = doc.executor_session; keys.executor_session = `${file}#executor_session` }
  }
  if ('stall_minutes' in doc) {
    if (typeof doc.stall_minutes !== 'number' || !Number.isFinite(doc.stall_minutes) || doc.stall_minutes <= 0) {
      problems.push('stall_minutes 必须是正数（分钟）')
    } else { cfg.stall_minutes = doc.stall_minutes; keys.stall_minutes = `${file}#stall_minutes` }
  }
  if ('reconcile_seconds' in doc) {
    if (typeof doc.reconcile_seconds !== 'number' || !Number.isFinite(doc.reconcile_seconds) || doc.reconcile_seconds < 5) {
      problems.push('reconcile_seconds 必须是 ≥5 的数（秒）——低于 5 秒的对账节拍只会空转')
    } else { cfg.reconcile_seconds = doc.reconcile_seconds; keys.reconcile_seconds = `${file}#reconcile_seconds` }
  }
  if ('alerts' in doc) {
    if (!isPlainObject(doc.alerts)) problems.push('alerts 必须是对象')
    else {
      const a = doc.alerts
      const al = cfg.alerts
      if ('enabled' in a) {
        if (typeof a.enabled !== 'boolean') problems.push('alerts.enabled 必须是 boolean')
        else { al.enabled = a.enabled; keys['alerts.enabled'] = `${file}#alerts.enabled` }
      }
      if ('sound' in a) {
        if (typeof a.sound !== 'boolean') problems.push('alerts.sound 必须是 boolean')
        else { al.sound = a.sound; keys['alerts.sound'] = `${file}#alerts.sound` }
      }
      if ('desktop' in a) {
        if (typeof a.desktop !== 'boolean') problems.push('alerts.desktop 必须是 boolean')
        else { al.desktop = a.desktop; keys['alerts.desktop'] = `${file}#alerts.desktop` }
      }
      if ('keep_days' in a) {
        if (typeof a.keep_days !== 'number' || !Number.isFinite(a.keep_days) || a.keep_days < 0) {
          problems.push('alerts.keep_days 必须是 ≥0 的数（0 = 永不按期清理）')
        } else { al.keep_days = a.keep_days; keys['alerts.keep_days'] = `${file}#alerts.keep_days` }
      }
      if ('redline' in a) {
        if (!Array.isArray(a.redline) || a.redline.some(r => typeof r !== 'string' || r === '')) {
          problems.push('alerts.redline 必须是非空字符串数组（规则名）')
        } else { al.redline = a.redline as string[]; keys['alerts.redline'] = `${file}#alerts.redline` }
      }
      if ('night' in a) {
        if (!isPlainObject(a.night)) problems.push('alerts.night 必须是对象')
        else {
          const n = a.night
          const bad: string[] = []
          if (typeof n.start !== 'string' || !HHMM_RE.test(n.start)) bad.push('start')
          if (typeof n.end !== 'string' || !HHMM_RE.test(n.end)) bad.push('end')
          if (!['silent', 'redline-only', 'normal'].includes(n.policy as string)) bad.push('policy')
          if (bad.length > 0) problems.push(`alerts.night 形状错（${bad.join('/')}；start/end 需 HH:MM，policy ∈ silent|redline-only|normal）`)
          else {
            al.night = { start: n.start as string, end: n.end as string, policy: n.policy as WatchdogConfig['alerts']['night']['policy'] }
            keys['alerts.night'] = `${file}#alerts.night`
          }
        }
      }
    }
  }
  const unknown = Object.keys(doc).filter(k => !['enabled', 'executor_session', 'stall_minutes', 'reconcile_seconds', 'alerts'].includes(k))
  if (unknown.length > 0) problems.push(`未知键被拒收（fail-closed，防 KI-149 同族静默失效）：${unknown.join('、')}`)

  if (problems.length > 0) {
    return {
      declared: true, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file, keys },
      config_error: `watchdog.json 声明被拒收：${problems.join('；')}`,
    }
  }
  return { declared: true, enabled: cfg.enabled, config: cfg, provenance: { file, keys }, config_error: null }
}

/** 配置根目录（测试缝：SANDBAR_WATCHDOG_DIR 优先；缺省=~/.sandbar/projects）。 */
export function watchdogConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_WATCHDOG_DIR || join(env.HOME || '', '.sandbar', 'projects')
}

/** 单项目配置读面（存在即声明；读失败 = declared+config_error，不静默）。 */
export function loadWatchdogConfig(key: string, env: NodeJS.ProcessEnv = process.env): ResolvedConfig {
  if (!isValidProjectKey(key)) {
    return {
      declared: false, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file: null, keys: {} },
      config_error: `项目 key 形状不合法：${String(key)}`,
    }
  }
  const file = join(watchdogConfigDir(env), key, 'watchdog.json')
  if (!existsSync(file)) {
    return { declared: false, enabled: false, config: FACTORY_DEFAULTS, provenance: { file: null, keys: {} }, config_error: null }
  }
  let raw: string
  try {
    raw = readFileSync(file, 'utf8')
  } catch (e) {
    return {
      declared: true, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file, keys: {} },
      config_error: `watchdog.json 读取失败：${e instanceof Error ? e.message : String(e)}`,
    }
  }
  return parseWatchdogConfig(raw, file)
}
