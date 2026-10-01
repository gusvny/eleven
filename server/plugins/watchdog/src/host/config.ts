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

import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

/** 单项目配置形状（全部可缺省，缺省回落出厂默认）。 */
export interface WatchdogConfig {
  enabled: boolean
  /** 该项目 executor 会话 id（t260930-09：'' = 未声明——守望者按需代建并回写；
   *  非空 = 收养人的声明，绝不创建、绝不覆盖）。 */
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

/** 出厂默认（设计稿 260927 默认值表；改默认值改这里，不改代码逻辑）。
 *  enabled=false = 本项目的总停开关（t260930-09 scope 5）：不代建、不唤醒、节拍全停
 *  （面板 Settings 的 revoke 按钮就是它）——off 是显式人决策，机器不代拨。 */
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

/** 配置根目录（测试缝：SANDBAR_WATCHDOG_DIR 优先；缺省=~/.sandbar/projects）。
 *  同一根也是项目注册表根（<key>/project.yaml）——守望者的声明与注册表同住。 */
export function watchdogConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_WATCHDOG_DIR || join(env.HOME || '', '.sandbar', 'projects')
}

/** 数据根目录（心跳 / 告警账 / 执行器会话账都落此根；测试缝：SANDBAR_WATCHDOG_DATA 优先）。
 *
 *  260930 直修（宿主令·不开票；真机实报）：**唯一真源**。此前"同一个数据根"在三处各算
 *  一份（core.ts 的 Watchdog 实例、node.ts 的执行器会话账、node.ts 的状态读侧），其中
 *  core 那份读 `deps.configDirEnv`，而该 deps **生产恒不传** ⇒ HOME 取空 ⇒ 退化成相对
 *  路径 `.sandbar/watchdog`（落控制台进程 cwd = 仓根），与读侧的 `~/.sandbar/watchdog`
 *  永不相见 ⇒ 面板恒报「无心跳文件（守望者从未起过或已死）」——**写侧活着、读侧说它死**。
 *  为什么测试没抓住：测试一律注入 SANDBAR_WATCHDOG_DATA（tests/lib.mjs），生产那条兜底
 *  表达式一次都没被执行（注入即绕过）。凡路径/形状，三处一律调本函数，禁再各算一份。 */
export function watchdogDataDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_WATCHDOG_DATA || join(env.HOME || '', '.sandbar', 'watchdog')
}

/**
 * 只写 executor_session 一键的声明写入面（t260930-09：守望者按需代建会话后回写）。
 *
 * 纪律（与 panel settings.ts saveWatchdogDecl 同一正反面）：
 *  - 序列化结果先过真装载器 parseWatchdogConfig，被拒收=不落盘（不留会静默弄坏
 *    守望者的声明）；
 *  - tmp 写 → 回读字节再过装载器 → 原子 rename；任一步失败原文件逐字节不动；
 *  - 未声明项目（无 watchdog.json）：以空对象为基座落盘（只有 executor_session 一键，
 *    其余旋钮全出厂默认）——「文件存在即声明」，代建回写本身就是首次入册；
 *  - 畸形既有声明（config_error 非空）：拒绝回写并点名原因——绝不往一份坏声明上叠写。
 */
export function writeExecutorSession(
  key: string, sessionId: string, env: NodeJS.ProcessEnv = process.env,
): { written: boolean; file: string | null; reason?: string } {
  if (!isValidProjectKey(key)) return { written: false, file: null, reason: `项目 key 形状不合法：${String(key)}` }
  if (typeof sessionId !== 'string' || sessionId === '') {
    return { written: false, file: null, reason: 'executor_session 必须是非空字符串（守望者绝不写空会话回声明）' }
  }
  const file = join(watchdogConfigDir(env), key, 'watchdog.json')
  let base: Record<string, unknown> = {}
  if (existsSync(file)) {
    let raw: string
    try {
      raw = readFileSync(file, 'utf8')
    } catch (e) {
      return { written: false, file, reason: `watchdog.json 读取失败（拒绝回写）：${e instanceof Error ? e.message : String(e)}` }
    }
    const cur = parseWatchdogConfig(raw, file)
    if (cur.config_error !== null) return { written: false, file, reason: `既有声明畸形（拒绝在其上回写）：${cur.config_error}` }
    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) base = parsed
    } catch { /* parseWatchdogConfig 已拒绝，走不到这里 */ }
    if (cur.config.executor_session === sessionId) return { written: true, file } // 幂等：已是该 id，不重写
  }
  const next = JSON.stringify({ ...base, executor_session: sessionId }, null, 2) + '\n'
  const pre = parseWatchdogConfig(next, file)
  if (pre.config_error !== null) return { written: false, file, reason: `回写内容被装载器拒收：${pre.config_error}` }
  const tmp = file + '.tmp'
  try {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(tmp, next, 'utf8')
    const post = parseWatchdogConfig(readFileSync(tmp, 'utf8'), file)
    if (post.config_error !== null) {
      unlinkSync(tmp)
      return { written: false, file, reason: `回读校验被拒收（不落盘）：${post.config_error}` }
    }
    renameSync(tmp, file)
    return { written: true, file }
  } catch (e) {
    try { unlinkSync(tmp) } catch { /* tmp 可能未建成 */ }
    return { written: false, file, reason: `watchdog.json 写入失败：${e instanceof Error ? e.message : String(e)}` }
  }
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
