/**
 * settings.ts —— Settings 写入面（t260929-03）：读声明+溯源透传、**写时回读校验**、
 * 夜间覆盖（panel 自有状态）。
 *
 * 硬规则（票面两条）：
 *  (a) 每个旋钮显示「哪份声明哪条键定的」——溯源直接透传 watchdog loader 的
 *      config_provenance（KI-148/149 教训），本模块不二次推导、不制造第二真源；
 *  (b) 保存=先经 watchdog 真装载器校验，再写 tmp → 回读字节再校验 → 原子 rename。
 *      任一步被拒收：tmp 删除、盘上原文件逐字节不动、返回人话理由——**绝不留下
 *      一份静默禁用/弄坏守望者的声明**（正面先例：安装器 project add 写时装载器自检）。
 *
 * 校验单一真源：直接 import watchdog 插件的 parseWatchdogConfig（review 议点，
 * 备选=复制 loader+漂移测试，更差）。夜间覆盖的到期放在 panel 自有 panel.json：
 * 合并版 watchdog schema 对未知键 fail-closed 拒收（KI-149），本票不改守望者——
 * 到期后界面显式「已过期（仍是 <policy>）——回切？」，不做页面静默自动回写。
 */

import { existsSync, readFileSync, writeFileSync, renameSync, unlinkSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { malformedProjectMessage } from './project-key.ts'
import {
  parseWatchdogConfig, loadWatchdogConfig, watchdogConfigDir, isValidProjectKey,
  FACTORY_DEFAULTS, instanceProjectsRoot, type WatchdogConfig,
} from '../../../watchdog/src/host/config.ts'

export { FACTORY_DEFAULTS, isValidProjectKey, loadWatchdogConfig, watchdogConfigDir }

export type NightPolicy = 'silent' | 'redline-only' | 'normal'

/** panel 自有夜间覆盖状态（到期记账面；只影响显示与回切建议，不改守望者判定）。 */
export interface PanelState {
  night_override: { policy: NightPolicy; until: number } | null
}

export function panelStateFile(key: string, env: NodeJS.ProcessEnv = process.env): string {
  // t261003-04：兜底走实例 projects 根（非缺省实例 = <DSH_HOME>/sandbar/projects）。
  const root = env.SANDBAR_PANEL_DIR || instanceProjectsRoot(env)
  return join(root, key, 'panel.json')
}

export function readPanelState(key: string, env: NodeJS.ProcessEnv = process.env): PanelState {
  const file = panelStateFile(key, env)
  if (!existsSync(file)) return { night_override: null }
  try {
    const doc = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>
    const ov = doc.night_override
    if (typeof ov === 'object' && ov !== null) {
      const o = ov as Record<string, unknown>
      if (typeof o.policy === 'string' && typeof o.until === 'number') {
        return { night_override: { policy: o.policy as NightPolicy, until: o.until } }
      }
    }
    return { night_override: null }
  } catch {
    return { night_override: null } // 状态文件坏了=无覆盖（覆盖是增益面，坏了退默认并留在读数里）
  }
}

export function writePanelState(key: string, state: PanelState, env: NodeJS.ProcessEnv = process.env): void {
  const file = panelStateFile(key, env)
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(state, null, 2) + '\n', 'utf8')
}

/** 覆盖生效判定（纯函数）：未到期=active；到期=expired（显式，不静默回切）。 */
export function nightOverrideVerdict(
  state: PanelState, nowMs: number,
): { active: boolean; expired: boolean; policy: NightPolicy | null; until: number | null } {
  const ov = state.night_override
  if (!ov) return { active: false, expired: false, policy: null, until: null }
  const expired = nowMs > ov.until
  return { active: !expired, expired, policy: ov.policy, until: ov.until }
}

/** 全旋钮路径（=编辑面可改的每一项；溯源必须逐项可答「谁定的」——KI-148/149）。 */
export const KNOB_PATHS = [
  'enabled', 'executor_session', 'stall_minutes', 'reconcile_seconds',
  'alerts.enabled', 'alerts.sound', 'alerts.desktop', 'alerts.night',
  'alerts.redline', 'alerts.keep_days',
] as const

/** Settings 读面：声明+溯源（未声明旋钮显式 factory-default）+config_error+夜间覆盖判定。 */
export function readSettings(key: string, env: NodeJS.ProcessEnv, nowMs: number): Record<string, unknown> {
  if (!isValidProjectKey(key)) return { ok: false, error: malformedProjectMessage(key) }
  const resolved = loadWatchdogConfig(key, env)
  const state = readPanelState(key, env)
  const override = nightOverrideVerdict(state, nowMs)
  const keys: Record<string, string> = {}
  for (const p of KNOB_PATHS) keys[p] = resolved.provenance.keys[p] ?? 'factory-default'
  return {
    ok: true,
    declared: resolved.declared,
    enabled: resolved.enabled,
    config: resolved.config,
    factory_defaults: FACTORY_DEFAULTS,
    provenance: { file: resolved.provenance.file, keys },
    config_provenance: { file: resolved.provenance.file, keys },
    config_error: resolved.config_error,
    night_override: state.night_override,
    night_override_active: override.active,
    night_override_expired: override.expired,
    effective_night_policy: resolved.config.alerts.night.policy,
    file: resolved.provenance.file,
  }
}

export interface SaveOutcome {
  saved: boolean
  reason?: string
  resolved?: { declared: boolean; enabled: boolean; config: WatchdogConfig; config_error: string | null }
}

/** 保存声明（写时回读校验，全失败路径原文件逐字节不动）。 */
export function saveWatchdogDecl(key: string, next: unknown, env: NodeJS.ProcessEnv): SaveOutcome {
  if (!isValidProjectKey(key)) return { saved: false, reason: malformedProjectMessage(key) }
  if (typeof next !== 'object' || next === null || Array.isArray(next)) {
    return { saved: false, reason: '声明顶层必须是 JSON 对象' }
  }
  const file = join(watchdogConfigDir(env), key, 'watchdog.json')
  const tmp = file + '.tmp'
  // 空串 executor_session（工厂缺省）不落盘：装载器把它判为形状错，序列化全量
  // merged 对象会把「未设会话」误成「拒收理由」——落盘只落显式声明过的键。
  const pruned = { ...(next as Record<string, unknown>) }
  if (pruned.executor_session === '') delete pruned.executor_session
  const serialized = JSON.stringify(pruned, null, 2) + '\n'
  // 第 1 道闸：序列化结果过真装载器（拒收=不落盘，人话理由透传）。
  const pre = parseWatchdogConfig(serialized, file)
  if (pre.config_error !== null) return { saved: false, reason: pre.config_error }
  // 落 tmp → 回读字节 → 第 2 道闸（「parse the file back through the loader」票面原文）。
  try {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(tmp, serialized, 'utf8')
    const back = readFileSync(tmp, 'utf8')
    const post = parseWatchdogConfig(back, file)
    if (post.config_error !== null) {
      unlinkSync(tmp)
      return { saved: false, reason: `回读校验被拒收（不留下会静默弄坏守望者的声明）：${post.config_error}` }
    }
    renameSync(tmp, file)
    return { saved: true, resolved: { declared: true, enabled: post.enabled, config: post.config, config_error: null } }
  } catch (e) {
    try { if (existsSync(tmp)) unlinkSync(tmp) } catch { /* tmp 收尸失败不掩盖主错 */ }
    return { saved: false, reason: `写盘失败：${e instanceof Error ? e.message : String(e)}` }
  }
}

/** 一键收回（授权是派生的——收回=声明面 enabled:false + 会话清空，经同一校验路径）。 */
export function revokeAll(key: string, env: NodeJS.ProcessEnv): SaveOutcome {
  const cur = loadWatchdogConfig(key, env)
  const next: Record<string, unknown> = { enabled: false }
  return saveWatchdogDecl(key, next, env) // enabled:false 形状合法（loader 允许单键声明）
}

/** 睡觉开关：夜间口径切档 + panel.json 记到期（毫秒）。 */
export function sleepToggle(
  key: string, policy: NightPolicy, untilMs: number, env: NodeJS.ProcessEnv, nowMs: number,
): { ok: boolean; error?: string; override?: PanelState['night_override'] } {
  if (!['silent', 'redline-only', 'normal'].includes(policy)) {
    return { ok: false, error: `policy 必须 ∈ silent|redline-only|normal（收到 ${String(policy)}）` }
  }
  if (!Number.isFinite(untilMs) || untilMs <= nowMs) {
    return { ok: false, error: 'until 必须是晚于当前时刻的毫秒时间戳（过期直接拒收，不落一份立即过期的开关）' }
  }
  const cur = loadWatchdogConfig(key, env)
  if (!cur.declared) return { ok: false, error: '项目未声明守望者（无 watchdog.json）——先在 Settings 保存一份声明再开夜间档' }
  const merged: WatchdogConfig = { ...cur.config, alerts: { ...cur.config.alerts, night: { ...cur.config.alerts.night, policy } } }
  const saved = saveWatchdogDecl(key, merged, env)
  if (!saved.saved) return { ok: false, error: saved.reason }
  const state: PanelState = { night_override: { policy, until: untilMs } }
  writePanelState(key, state, env)
  return { ok: true, override: state.night_override }
}
