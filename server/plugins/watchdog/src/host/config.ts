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
import { dirname, join, resolve } from 'node:path'

/** 单项目配置形状（全部可缺省，缺省回落出厂默认）。 */
export interface WatchdogConfig {
  enabled: boolean
  /** 该项目 executor 会话 id（t260930-09：'' = 未声明——守望者按需代建并回写；
   *  非空 = 收养人的声明，绝不创建、绝不覆盖）。 */
  executor_session: string
  stall_minutes: number
  /** 长回合阈值（t261004-12）：会话 running=true 期间的静默上限。rationale——executor
   *  在一个长回合内整段不落消息，守望者又不补发简报（上条未消化），账本也不动，静默
   *  是**预期形态**；所以 running=true 时不能按 stall_minutes（15）判停摆，要给一条
   *  明显更长的上限。默认 45 = 3×stall_minutes：远超实测正常回合长度（不至于每回合
   *  都报），又有界（真挂死但 running 位仍 true 的循环不会永远无声）。running=false
   *  的停摆判定仍用 stall_minutes，两条阈值互不借用。 */
  long_turn_minutes: number
  /** t261008-39 (host order 261008): the re-raise threshold (minutes) for a ticket
   *  stuck in blocked/refused — past it, with no recorded action, later wake briefs
   *  name the ticket again (still blocked, previously surfaced) instead of relying
   *  on the once-only briefing; a recorded action while still stuck moves the fire
   *  point to 2x the threshold (never punishes an attempt, but long non-progress
   *  still reaches the table). Default 30 = 2x stall_minutes, below
   *  long_turn_minutes (45), and below the live case's harm window (t261008-22 sat
   *  unnoticed for 59 minutes). awaiting-human is a queue, not a fault — it never
   *  enters the re-raise. */
  blocked_rerise_minutes: number
  reconcile_seconds: number
  /** t261004-08: self-lock escalation threshold (minutes) — an unanswered request
   *  raised by the executor session itself escalates to `waiting_on_itself` (redline)
   *  only past this threshold; inside it the verdict is `waiting` (status face only,
   *  no alert, no wake-level raise). It tunes "how long is too long", not the match
   *  predicate itself. Distinct knob from prose_backstop.idle_minutes: this one gates
   *  the escalation of an existing ledger row; that one gates how long a prose ask
   *  may sit in round text before the backstop files a row. */
  waiting_minutes: number
  /** t261004-08: prose backstop (prose-ask filing) switch + idle threshold.
   *  enabled=false = the whole filing face stops (no session text read, no row
   *  filed, no prose_ask_filed alert). */
  prose_backstop: { enabled: boolean; idle_minutes: number }
  /** t261005-02: the bounded un-park (self-heal) face. When the executor session sits
   *  on an unanswered ask past `park_minutes` while our wake briefing is still
   *  unconsumed in its queue, the watchdog cancels that turn once and re-delivers the
   *  briefing. enabled=false = the whole face stops (observation only, never cancel).
   *  park_minutes must stay above long_turn_minutes (cross-checked at parse time:
   *  a healthy long turn must never reach the cancel threshold). */
  self_heal: { enabled: boolean; park_minutes: number }
  /** t261004-30: one-shot executor sessions (bounded small work). retention_days =7
   *  (host default), lock_timeout_ms reclaims a dead session's object lock. The
   *  parallel cap is NOT here — it reads the project concurrency declaration via
   *  one-shot.ts readConcurrencyLimit (one knob, host decision 261004). */
  one_shot: { enabled: boolean; retention_days: number; lock_timeout_ms: number }
  /** t261004-44 (KI-196 judgement): the ask-mirror watch deadline (seconds) -- a
   *  session sitting on ask_user_question with no question row past this deadline
   *  raises the ask_unmirrored redline (message names the session and the ask face). */
  ask_mirror_deadline_s: number
  alerts: {
    enabled: boolean
    /** 面板消费位：本票不发声，只暴露「该响」的意图（dsh 无发声能力，已实证）。 */
    sound: boolean
    desktop: boolean
    night: { start: string; end: string; policy: 'silent' | 'redline-only' | 'normal' }
    redline: string[]
    keep_days: number
    /** t261009-57: how many COALESCED alert rows the panel Alerts face shows.
     *  0 = show all. Bounds the coalesced presentation only — the status payload
     *  carries the raw (buffer-bounded) rows and the ledger keeps every line. */
    display_max: number
  }
}

/** 出厂默认（设计稿 260927 默认值表；改默认值改这里，不改代码逻辑）。
 *  enabled=false = 本项目的总停开关（t260930-09 scope 5）：不代建、不唤醒、节拍全停
 *  （面板 Settings 的 revoke 按钮就是它）——off 是显式人决策，机器不代拨。 */
export const FACTORY_DEFAULTS: WatchdogConfig = {
  enabled: true,
  executor_session: '',
  stall_minutes: 15,
  long_turn_minutes: 45,
  blocked_rerise_minutes: 30,
  reconcile_seconds: 60,
  waiting_minutes: 5,
  prose_backstop: { enabled: true, idle_minutes: 10 },
  self_heal: { enabled: true, park_minutes: 60 },
  one_shot: { enabled: true, retention_days: 7, lock_timeout_ms: 30 * 60 * 1000 },
  ask_mirror_deadline_s: 120,
  alerts: {
    enabled: true,
    sound: true,
    desktop: true,
    night: { start: '23:00', end: '07:30', policy: 'redline-only' },
    redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall', 'executor_missing',
      'ask_unmirrored', 'deliver_refused', 'executor_awaiting_approval'],
    keep_days: 14,
    display_max: 8,
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
    if (typeof doc.enabled !== 'boolean') problems.push('enabled must be a boolean')
    else { cfg.enabled = doc.enabled; keys.enabled = `${file}#enabled` }
  }
  if ('executor_session' in doc) {
    if (typeof doc.executor_session !== 'string' || doc.executor_session === '') {
      problems.push('executor_session must be a non-empty string (session id)')
    } else { cfg.executor_session = doc.executor_session; keys.executor_session = `${file}#executor_session` }
  }
  if ('stall_minutes' in doc) {
    if (typeof doc.stall_minutes !== 'number' || !Number.isFinite(doc.stall_minutes) || doc.stall_minutes <= 0) {
      problems.push('stall_minutes must be a positive number (minutes)')
    } else { cfg.stall_minutes = doc.stall_minutes; keys.stall_minutes = `${file}#stall_minutes` }
  }
  if ('long_turn_minutes' in doc) {
    if (typeof doc.long_turn_minutes !== 'number' || !Number.isFinite(doc.long_turn_minutes) || doc.long_turn_minutes <= 0) {
      problems.push('long_turn_minutes must be a positive number (minutes)')
    } else { cfg.long_turn_minutes = doc.long_turn_minutes; keys.long_turn_minutes = `${file}#long_turn_minutes` }
  }
  if ('blocked_rerise_minutes' in doc) {
    if (typeof doc.blocked_rerise_minutes !== 'number' || !Number.isFinite(doc.blocked_rerise_minutes) || doc.blocked_rerise_minutes <= 0) {
      problems.push('blocked_rerise_minutes must be a positive number (minutes)')
    } else { cfg.blocked_rerise_minutes = doc.blocked_rerise_minutes; keys.blocked_rerise_minutes = `${file}#blocked_rerise_minutes` }
  }
  if ('reconcile_seconds' in doc) {
    if (typeof doc.reconcile_seconds !== 'number' || !Number.isFinite(doc.reconcile_seconds) || doc.reconcile_seconds < 5) {
      problems.push('reconcile_seconds must be a number >= 5 (seconds). A beat under 5 seconds only spins.')
    } else { cfg.reconcile_seconds = doc.reconcile_seconds; keys.reconcile_seconds = `${file}#reconcile_seconds` }
  }
  if ('ask_mirror_deadline_s' in doc) {
    if (typeof doc.ask_mirror_deadline_s !== 'number' || !Number.isFinite(doc.ask_mirror_deadline_s) || doc.ask_mirror_deadline_s <= 0) {
      problems.push('ask_mirror_deadline_s must be a positive number (seconds)')
    } else { cfg.ask_mirror_deadline_s = doc.ask_mirror_deadline_s; keys.ask_mirror_deadline_s = `${file}#ask_mirror_deadline_s` }
  }
  if ('waiting_minutes' in doc) {
    if (typeof doc.waiting_minutes !== 'number' || !Number.isFinite(doc.waiting_minutes) || doc.waiting_minutes <= 0) {
      problems.push('waiting_minutes must be a positive number (minutes)')
    } else { cfg.waiting_minutes = doc.waiting_minutes; keys.waiting_minutes = `${file}#waiting_minutes` }
  }
  if ('self_heal' in doc) {
    if (!isPlainObject(doc.self_heal)) {
      problems.push('self_heal must be an object ({enabled, park_minutes})')
    } else {
      const sh = doc.self_heal
      const out = cfg.self_heal
      if ('enabled' in sh) {
        if (typeof sh.enabled !== 'boolean') problems.push('self_heal.enabled must be a boolean')
        else { out.enabled = sh.enabled; keys['self_heal.enabled'] = `${file}#self_heal.enabled` }
      }
      if ('park_minutes' in sh) {
        if (typeof sh.park_minutes !== 'number' || !Number.isFinite(sh.park_minutes) || sh.park_minutes <= 0) {
          problems.push('self_heal.park_minutes must be a positive number (minutes)')
        } else { out.park_minutes = sh.park_minutes; keys['self_heal.park_minutes'] = `${file}#self_heal.park_minutes` }
      }
    }
  }
  if ('prose_backstop' in doc) {
    if (!isPlainObject(doc.prose_backstop)) {
      problems.push('prose_backstop must be an object ({enabled, idle_minutes})')
    } else {
      const pb = doc.prose_backstop
      const out = cfg.prose_backstop
      if ('enabled' in pb) {
        if (typeof pb.enabled !== 'boolean') problems.push('prose_backstop.enabled must be a boolean')
        else { out.enabled = pb.enabled; keys['prose_backstop.enabled'] = `${file}#prose_backstop.enabled` }
      }
      if ('idle_minutes' in pb) {
        if (typeof pb.idle_minutes !== 'number' || !Number.isFinite(pb.idle_minutes) || pb.idle_minutes <= 0) {
          problems.push('prose_backstop.idle_minutes must be a positive number (minutes)')
        } else { out.idle_minutes = pb.idle_minutes; keys['prose_backstop.idle_minutes'] = `${file}#prose_backstop.idle_minutes` }
      }
    }
  }
  if ('one_shot' in doc) {
    if (!isPlainObject(doc.one_shot)) {
      problems.push('one_shot must be an object ({enabled, retention_days, lock_timeout_ms})')
    } else {
      const os = doc.one_shot
      const out = cfg.one_shot
      if ('enabled' in os) {
        if (typeof os.enabled !== 'boolean') problems.push('one_shot.enabled must be a boolean')
        else { out.enabled = os.enabled; keys['one_shot.enabled'] = `${file}#one_shot.enabled` }
      }
      if ('retention_days' in os) {
        if (typeof os.retention_days !== 'number' || !Number.isFinite(os.retention_days) || os.retention_days < 0) {
          problems.push('one_shot.retention_days must be a number >= 0 (0 = never expire by age)')
        } else { out.retention_days = os.retention_days; keys['one_shot.retention_days'] = `${file}#one_shot.retention_days` }
      }
      if ('lock_timeout_ms' in os) {
        if (typeof os.lock_timeout_ms !== 'number' || !Number.isFinite(os.lock_timeout_ms) || os.lock_timeout_ms <= 0) {
          problems.push('one_shot.lock_timeout_ms must be a positive number (milliseconds)')
        } else { out.lock_timeout_ms = os.lock_timeout_ms; keys['one_shot.lock_timeout_ms'] = `${file}#one_shot.lock_timeout_ms` }
      }
      // Unknown keys inside the block fail closed (KI-149 family). The parallel
      // cap deliberately has no key here: it lives only in the shared project
      // concurrency declaration (one knob, host decision 261004) -- a cap key
      // hiding in one_shot would be a second knob and is refused.
      const osUnknown = Object.keys(os).filter(k => !['enabled', 'retention_days', 'lock_timeout_ms'].includes(k))
      if (osUnknown.length > 0) {
        problems.push(`one_shot: Unknown keys rejected (fail-closed; the parallel cap lives only in the shared concurrency declaration, not here): ${osUnknown.join(', ')}`)
      }
    }
  }
  if ('alerts' in doc) {
    if (!isPlainObject(doc.alerts)) problems.push('alerts must be an object')
    else {
      const a = doc.alerts
      const al = cfg.alerts
      if ('enabled' in a) {
        if (typeof a.enabled !== 'boolean') problems.push('alerts.enabled must be a boolean')
        else { al.enabled = a.enabled; keys['alerts.enabled'] = `${file}#alerts.enabled` }
      }
      if ('sound' in a) {
        if (typeof a.sound !== 'boolean') problems.push('alerts.sound must be a boolean')
        else { al.sound = a.sound; keys['alerts.sound'] = `${file}#alerts.sound` }
      }
      if ('desktop' in a) {
        if (typeof a.desktop !== 'boolean') problems.push('alerts.desktop must be a boolean')
        else { al.desktop = a.desktop; keys['alerts.desktop'] = `${file}#alerts.desktop` }
      }
      if ('keep_days' in a) {
        if (typeof a.keep_days !== 'number' || !Number.isFinite(a.keep_days) || a.keep_days < 0) {
          problems.push('alerts.keep_days must be a number >= 0 (0 = never expire by age)')
        } else { al.keep_days = a.keep_days; keys['alerts.keep_days'] = `${file}#alerts.keep_days` }
      }
      // t261009-57: one host-adjustable number for the Alerts face — it counts
      // COALESCED rows (coalesce first, cap second). 0 = show all (named sentinel).
      if ('display_max' in a) {
        if (typeof a.display_max !== 'number' || !Number.isInteger(a.display_max) || a.display_max < 0 || a.display_max > 1000) {
          problems.push('alerts.display_max must be an integer between 0 and 1000 (0 = show all)')
        } else { al.display_max = a.display_max; keys['alerts.display_max'] = `${file}#alerts.display_max` }
      }
      if ('redline' in a) {
        if (!Array.isArray(a.redline) || a.redline.some(r => typeof r !== 'string' || r === '')) {
          problems.push('alerts.redline must be a non-empty array of rule names (strings)')
        } else { al.redline = a.redline as string[]; keys['alerts.redline'] = `${file}#alerts.redline` }
      }
      if ('night' in a) {
        if (!isPlainObject(a.night)) problems.push('alerts.night must be an object')
        else {
          const n = a.night
          const bad: string[] = []
          if (typeof n.start !== 'string' || !HHMM_RE.test(n.start)) bad.push('start')
          if (typeof n.end !== 'string' || !HHMM_RE.test(n.end)) bad.push('end')
          if (!['silent', 'redline-only', 'normal'].includes(n.policy as string)) bad.push('policy')
          if (bad.length > 0) problems.push(`alerts.night shape is wrong (${bad.join('/')}; start/end need HH:MM, policy in silent|redline-only|normal)`)
          else {
            al.night = { start: n.start as string, end: n.end as string, policy: n.policy as WatchdogConfig['alerts']['night']['policy'] }
            keys['alerts.night'] = `${file}#alerts.night`
          }
        }
      }
    }
  }
  // t261005-02 cross-knob guard (review item 4): a cancel threshold at or below a
  // DECLARED long-turn threshold could fire on a healthy long turn — reject with both
  // knobs named. The check compares against an explicitly declared long_turn_minutes
  // only: the factory default (45) is not a declaration, and small park thresholds
  // (test fixtures, aggressive recovery profiles) stay valid without one.
  if ('long_turn_minutes' in doc && cfg.self_heal.park_minutes <= cfg.long_turn_minutes) {
    problems.push(`self_heal.park_minutes (${cfg.self_heal.park_minutes}) must stay above long_turn_minutes (${cfg.long_turn_minutes}) — a healthy long turn must never reach the cancel threshold`)
  }
  const unknown = Object.keys(doc).filter(k => !['enabled', 'executor_session', 'stall_minutes', 'long_turn_minutes', 'blocked_rerise_minutes', 'reconcile_seconds', 'waiting_minutes', 'prose_backstop', 'self_heal', 'one_shot', 'ask_mirror_deadline_s', 'alerts'].includes(k))
  if (unknown.length > 0) problems.push(`Unknown keys rejected (fail-closed, KI-149 family): ${unknown.join(', ')}`)

  if (problems.length > 0) {
    return {
      declared: true, enabled: false, config: FACTORY_DEFAULTS,
      provenance: { file, keys },
      config_error: `watchdog.json rejected. Problems: ${problems.join('; ')}`,
    }
  }
  return { declared: true, enabled: cfg.enabled, config: cfg, provenance: { file, keys }, config_error: null }
}

/** 实例的 dsh home（t261003-04：实例身份真源）。env DSH_HOME 优先；缺省 ~/.dsh。
 *  与 core.instanceScope（t261001-19 的 dedupe 隔离域）同一表达式——身份只算一份。 */
export function dshHome(env: NodeJS.ProcessEnv = process.env): string {
  return env.DSH_HOME || join(env.HOME || '', '.dsh')
}

/** 是否缺省实例（= 生产实例）：dsh home 解析后等于 ~/.dsh。场景/泳道实例带自己的
 *  DSH_HOME（临时目录），resolve 后必然不同 ⇒ 判为非缺省实例。
 *  resolve 归一（去尾斜杠/相对段），畸形 DSH_HOME 不至于把生产实例误判成隔离实例。
 *
 *  定案口径（t261003-04 打回，merge 人审Gate）：实例形态 = HOME 与 DSH_HOME **共同**
 *  决定，规则确定性、与进程环境解耦——
 *   - DSH_HOME 未设或即 $HOME/.dsh ⇒ 缺省实例（生产形态，根=$HOME/.sandbar，历史不变）；
 *   - DSH_HOME 设为其它路径 ⇒ 非缺省实例，根一律 <DSH_HOME>/sandbar/…（它自己 dsh home
 *     的树，绝不顺 $HOME 兜底摸进别人的树）。
 *  推论：只隔离 HOME、不隔离 DSH_HOME 的进程形态不被支持——根跟着 DSH_HOME 走（确定
 *  性、可预期）；测试构造「只有 HOME」的生产形态必须把 DSH_HOME 一并钉住（自夹具纪律，
 *  见 tests/data-root-single-source.test.mjs——本条回归=ambient DSH_HOME 把根拽到
 *  ~/.dsh/sandbar，套件在真会话里自红）。 */
export function isDefaultInstance(env: NodeJS.ProcessEnv = process.env): boolean {
  return resolve(dshHome(env)) === resolve(join(env.HOME || '', '.dsh'))
}

/**
 * 实例 sandbar 根（t261003-04 缺陷 A 的收口点）：**一个实例一个根**。
 *
 * 病灶（真机 261001-261003 实测）：声明根/账本根/数据根/请求账根是四个独立 env 旋钮、
 * 全部兜底 $HOME——只注入 DSH_HOME + SANDBAR_PROJECTS_DIR 的场景实例因此①读到生产声明
 * 起了守望者本体②盯自己不存在的账本每拍报 ledger_unreadable③把报警写进生产数据根
 * ④读生产请求账把生产执行器判成 waiting_on_itself（802/843 条生产台账报警来自临时实例）。
 *
 * 方案：四个根的**兜底**统一从本函数推导——
 *  - 缺省实例（生产，DSH_HOME 未设或即 ~/.dsh）：$HOME/.sandbar（历史路径逐字节不变，
 *    追加式历史照读）；
 *  - 非缺省实例（场景/泳道/并行台）：<DSH_HOME>/sandbar —— 与生产物理隔离，临时实例
 *    从根上读不到生产声明/数据/请求账，也绝不往生产写。
 * 显式 env 旋钮（SANDBAR_WATCHDOG_DIR / SANDBAR_WATCHDOG_DATA / SANDBAR_PROJECTS_DIR /
 * SANDBAR_PANEL_DIR）仍然最优先——显式指定=听调用方的，本函数只管兜底这一层。 */
export function instanceSandbarRoot(env: NodeJS.ProcessEnv = process.env): string {
  if (isDefaultInstance(env)) return join(env.HOME || '', '.sandbar')
  return join(dshHome(env), 'sandbar')
}

/** 实例的 projects 根兜底（声明/注册表/请求账/事件账共用的那一层）。
 *  executor-panel 的 requests/settings/api 三处经此取兜底——四根一词表，禁再各算一份。 */
export function instanceProjectsRoot(env: NodeJS.ProcessEnv = process.env): string {
  return join(instanceSandbarRoot(env), 'projects')
}

/** 配置根目录（测试缝：SANDBAR_WATCHDOG_DIR 优先；缺省=实例 projects 根，见
 *  instanceSandbarRoot——t261003-04 前缺省恒为 ~/.sandbar/projects，生产形态不变）。
 *  同一根也是项目注册表根（<key>/project.yaml）——守望者的声明与注册表同住。 */
export function watchdogConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_WATCHDOG_DIR || instanceProjectsRoot(env)
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
  return env.SANDBAR_WATCHDOG_DATA || join(instanceSandbarRoot(env), 'watchdog')
}

/** 注册表/项目根（t261001-12：与引擎 event_ledger._projects_root 同源同词表）。
 *  SANDBAR_PROJECTS_DIR 覆盖 > 实例 projects 根（t261003-04：非缺省实例兜底落在
 *  <DSH_HOME>/sandbar/projects——临时实例不再顺生产兜底读到/写进真注册表根）。 */
export function projectsRoot(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_PROJECTS_DIR || instanceProjectsRoot(env)
}

/** 事件账本活动文件路径（t261001-12 跨语言缝）：与引擎 event_ledger.ledger_path
 *  逐字同式，两种形状（tests 双向钉死，任一侧漂移即红）：
 *  - env SANDBAR_EVENT_LEDGER_DIR（平铺兼容缝，语义不变）⇒ `<dir>/<project>.jsonl`；
 *  - 缺省（生产形状）⇒ `<projects_root>/<project>/ledger/events.jsonl`。
 *  跨语言一致性锁：server/plugins/watchdog/tests/ledger-location.test.mjs 跑
 *  python3 解析器逐字比对，共享字面量不算锁。 */
export function eventLedgerFile(project: string, env: NodeJS.ProcessEnv = process.env): string {
  const flat = env.SANDBAR_EVENT_LEDGER_DIR
  if (flat) return join(flat, `${project}.jsonl`)
  return join(projectsRoot(env), project, 'ledger', 'events.jsonl')
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
