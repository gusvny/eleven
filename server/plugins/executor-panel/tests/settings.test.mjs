/**
 * settings.test.mjs —— Settings 写面 UT：写时回读校验（两道闸）、每个拒收类
 * 盘上文件逐字节不动、溯源透传、夜间覆盖判定与到期、一键收回、睡觉开关。
 * 用真实 fs + 隔离临时根（SANDBAR_WATCHDOG_DIR/SANDBAR_PANEL_DIR），零 ~/.sandbar。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { assert, done, freshDir, cleanup, isolatedEnv, fakeClock } from './lib.mjs'
import {
  readSettings, saveWatchdogDecl, revokeAll, sleepToggle, readPanelState,
  nightOverrideVerdict, FACTORY_DEFAULTS,
} from '../src/host/settings.ts'
import { loadWatchdogConfig } from '../../watchdog/src/host/config.ts'

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const clock = fakeClock()
let n = 0

const good = { enabled: true, executor_session: 'sess-1', stall_minutes: 15, reconcile_seconds: 60, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['stall'], keep_days: 14 } }

// 未声明读面。
const before = readSettings('proj', env, clock.now())
assert(before.declared === false && before.config_error === null, 'undeclared project reads declared:false, no error')

// 合法保存：两道闸全过 → 盘上文件 = 回读过装载器的声明。
const okSave = saveWatchdogDecl('proj', good, env)
assert(okSave.saved === true, 'valid declaration saves')
const file = join(wd, 'proj', 'watchdog.json')
const reloaded = loadWatchdogConfig('proj', env)
assert(reloaded.declared === true && reloaded.config.executor_session === 'sess-1' && reloaded.config_error === null, 'saved declaration round-trips through the REAL watchdog loader')
assert(reloaded.provenance.keys.enabled === file + '#enabled' && reloaded.provenance.keys['alerts.sound'] === file + '#alerts.sound', 'provenance names file + json path per knob')
assert(reloaded.provenance.keys['alerts.keep_days'] === file + '#alerts.keep_days', 'nested knob provenance names json path (alerts.keep_days)')

// 拒收类逐个：坏 JSON 形状 / 未知键 / 形状错 —— 盘上文件逐字节不动（票面硬规则 b）。
const bytesBefore = readFileSync(file, 'utf8')
const rejects = [
  ['unknown key (fail-closed, KI-149)', { ...good, mystery: 1 }],
  ['bad night policy', JSON.parse(JSON.stringify(good).replace('redline-only', 'loud-all-night'))],
  ['negative stall_minutes', { ...good, stall_minutes: -5 }],
  ['bad redline array', JSON.parse(JSON.stringify({ ...good, alerts: { ...good.alerts, redline: [42] } }))],
  ['non-object config', 'just a string'],
  ['bad hh:mm', JSON.parse(JSON.stringify({ ...good, alerts: { ...good.alerts, night: { ...good.alerts.night, start: '24:99' } } }))],
]
for (const [label, bad] of rejects) {
  const out = saveWatchdogDecl('proj', bad, env)
  assert(out.saved === false && typeof out.reason === 'string' && out.reason.length > 0, 'reject on write: ' + label + ' (human-readable reason)')
  assert(readFileSync(file, 'utf8') === bytesBefore, 'on-disk file byte-identical after rejected save: ' + label)
}
assert(!existsSync(file + '.tmp'), 'tmp file cleaned up on every rejection path (no half declarations left)')

// 读面带溯源 + config_error。
const rs = readSettings('proj', env, clock.now())
assert(rs.ok === true && rs.provenance && rs.factory_defaults, 'readSettings returns provenance + factory defaults')
assert(rs.config.stall_minutes === 15, 'readSettings returns effective config')
n += 0

// 一键收回：enabled:false 单键声明（派生清单渲染成全收回，无手工清单可漂移）。
const rev = revokeAll('proj', env)
assert(rev.saved === true, 'revoke saves enabled:false through the same validate-on-write path')
assert(loadWatchdogConfig('proj', env).enabled === false, 'revoke effective on reload')

// 夜间覆盖判定：active / expired（显式，不静默回切）。
assert(nightOverrideVerdict({ night_override: null }, 1).active === false, 'no override = inactive')
const ov = nightOverrideVerdict({ night_override: { policy: 'silent', until: 1000 } }, 999)
assert(ov.active === true && ov.policy === 'silent', 'override active before until')
const ovExp = nightOverrideVerdict({ night_override: { policy: 'silent', until: 1000 } }, 1001)
assert(ovExp.active === false && ovExp.expired === true && ovExp.policy === 'silent', 'expired override reports expired explicitly with current policy')

// 睡觉开关：合法切档写声明 + panel.json 记到期。
const sl = sleepToggle('proj', 'silent', clock.now() + 3600_000, env, clock.now())
assert(sl.ok === true && sl.override.until === clock.now() + 3600_000, 'sleep toggle writes override with expiry')
assert(loadWatchdogConfig('proj', env).config.alerts.night.policy === 'silent', 'sleep toggle switches night policy through the loader (config-driven, effective immediately)')
assert(readPanelState('proj', env).night_override.policy === 'silent', 'panel state records the override')

// 睡觉开关拒绝面：坏 policy / 过去时刻 / 未声明项目。
assert(sleepToggle('proj', 'blast', 9e15, env, clock.now()).ok === false, 'sleep toggle rejects unknown policy')
assert(sleepToggle('proj', 'silent', clock.now() - 1, env, clock.now()).ok === false, 'sleep toggle rejects past expiry')
assert(sleepToggle('ghost', 'silent', 9e15, env, clock.now()).ok === false && sleepToggle('ghost', 'silent', 9e15, env, clock.now()).error.includes('未声明'), 'sleep toggle rejects undeclared project (no silent enrollment)')

// 坏 key 拒收（POST 面防线）。
assert(saveWatchdogDecl('../evil', good, env).saved === false, 'save rejects traversal-shaped project key')
assert(existsSync(join(pan, 'proj', 'panel.json')), 'panel state lives under the PANEL root, only for touched projects')

// 空串 executor_session = 「未设会话」：编辑面语义下落盘时剔除（=回落工厂缺省，
// 溯源显式 factory-default），不误成拒收理由——装载器把空串判形状错，全量 merged
// 序列化会把「没设过」变成「声明被拒」，这里显式钉住该映射。
{
  const withBlank = JSON.parse(JSON.stringify(good)); withBlank.executor_session = ''
  const out = saveWatchdogDecl('proj', withBlank, env)
  assert(out.saved === true, 'blank executor_session saves as unset (not a rejection)')
  const rl = loadWatchdogConfig('proj', env)
  assert(rl.provenance.keys.executor_session === undefined, 'blank session not in provenance (factory-default shown)')
  // 恢复声明供后续用例使用。
  saveWatchdogDecl('proj', good, env)
}

// 部分声明：未声明的旋钮溯源显式 factory-default（KI-148/149：逐旋钮可答「谁定的」）。
{
  saveWatchdogDecl('part', { stall_minutes: 5 }, env)
  const rp = readSettings('part', env, clock.now())
  assert(rp.provenance.keys.stall_minutes.endsWith('#stall_minutes'), 'declared knob provenance = file#path')
  assert(rp.provenance.keys['alerts.sound'] === 'factory-default', 'undeclared knob provenance = factory-default (explicit)')
  assert(rp.config_provenance.keys['alerts.sound'] === 'factory-default', 'config_provenance alias exposed')
}

// FACTORY_DEFAULTS 原样透传（页面 Settings 的出厂对照列）。
assert(FACTORY_DEFAULTS.alerts.night.policy === 'redline-only', 'factory defaults exported for the settings view')

cleanup([wd, pan])
n += 26
done(n)
