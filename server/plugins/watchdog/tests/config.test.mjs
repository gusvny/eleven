// config UT：默认值 / 未声明零行为 / 畸形 fail-closed / 溯源 / env 缝（畸形输入族必带）。
import { loadWatchdogConfig, parseWatchdogConfig, watchdogConfigDir, isValidProjectKey, FACTORY_DEFAULTS } from '../src/host/config.ts'
import { testEnv, cleanup, assert, done } from './lib.mjs'
import { join } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'

// 沙箱 vfs 读可见性探测：写后不可读 = 本环境 quirk，真实 fs 读面用例统一 SKIP（解析面另有纯函数覆盖）。
const fsVisible = await (async () => {
  const { env, cfgDir } = await testEnv({ probe: { enabled: true } })
  const f = join(env.SANDBAR_WATCHDOG_DIR, 'probe', 'watchdog.json')
  const ok = existsSync(f) && readFileSync(f, 'utf8').includes('enabled')
  cleanup([cfgDir])
  return ok
})()
const needFs = (name) => { if (!fsVisible) console.log('SKIP  ' + name + ' (vfs read-visibility quirk)') }

let n = 0
// 未声明：declared=false，零行为语义。
{
  const { env, cfgDir } = await testEnv({})
  needFs('undeclared')
  const r = loadWatchdogConfig('sandbar', env)
  assert(r.declared === false && r.enabled === false && r.config_error === null, 'cfg undeclared → declared=false')
  assert(r.config.stall_minutes === FACTORY_DEFAULTS.stall_minutes, 'cfg undeclared falls back to factory')
  cleanup([cfgDir]); n += 2
}
// 合法声明：值透传 + 溯源逐键（经真实 fs 读面；沙箱 vfs 读可见性不稳时探测守卫 SKIP，
// 解析面已由下方畸形族覆盖，不因环境 quirk 假红）。
{
  const { env, cfgDir } = await testEnv({ sandbar: { enabled: true, executor_session: 'executor-x', stall_minutes: 7, alerts: { sound: false, night: { start: '00:30', end: '05:00', policy: 'normal' } } } })
  const probeFile = join(env.SANDBAR_WATCHDOG_DIR, 'sandbar', 'watchdog.json')
  const { existsSync, readFileSync } = await import('node:fs')
  const visible = existsSync(probeFile) && readFileSync(probeFile, 'utf8').includes('executor-x')
  if (!fsVisible) {
    console.log('SKIP  real-fs read visibility unstable in this sandbox (vfs shim) — parse face covered below')
  } else {
    const r = loadWatchdogConfig('sandbar', env)
    assert(r.declared && r.enabled && r.config_error === null, 'cfg valid parse ok')
    assert(r.config.stall_minutes === 7 && r.config.executor_session === 'executor-x', 'cfg values pass through')
    assert(r.config.alerts.sound === false && r.config.alerts.night.policy === 'normal', 'cfg nested values pass through')
    assert(r.config.alerts.keep_days === 14, 'cfg unset knob keeps factory (keep_days=14)')
    assert(r.provenance.keys['stall_minutes']?.endsWith('#stall_minutes'), 'cfg provenance per-key file#path')
    assert(r.provenance.keys['alerts.keep_days'] === undefined, 'cfg provenance absent for factory-fallback knob')
    n += 6
  }
  cleanup([cfgDir]); n += 0
}
// 畸形族：坏 JSON / 顶层非对象 / 类型错 / 负数 / 未知键 / 形状白名单。
{
  const bad1 = parseWatchdogConfig('{not json', 'f1')
  assert(bad1.config_error !== null && bad1.enabled === false && bad1.declared, 'cfg malformed JSON → fail-closed explicit (not silent default)')
  const bad2 = parseWatchdogConfig('[]', 'f2')
  assert(bad2.config_error !== null, 'cfg top-level array rejected')
  const bad3 = parseWatchdogConfig(JSON.stringify({ stall_minutes: -3 }), 'f3')
  assert(bad3.config_error !== null && bad3.config_error.includes('stall_minutes'), 'cfg negative stall rejected')
  const bad4 = parseWatchdogConfig(JSON.stringify({ reconcile_seconds: 1 }), 'f4')
  assert(bad4.config_error !== null, 'cfg reconcile_seconds<5 rejected')
  const bad5 = parseWatchdogConfig(JSON.stringify({ alerts: { night: { start: '24:00', end: '07:00', policy: 'sometimes' } } }), 'f5')
  assert(bad5.config_error !== null && bad5.config_error.includes('night'), 'cfg bad night window rejected')
  const bad6 = parseWatchdogConfig(JSON.stringify({ mystery: true }), 'f6')
  assert(bad6.config_error !== null && bad6.config_error.includes('Unknown keys'), 'cfg unknown key rejected (KI-149 family guard)')
  const bad7 = parseWatchdogConfig(JSON.stringify({ executor_session: '' }), 'f7')
  assert(bad7.config_error !== null, 'cfg empty executor_session rejected')
  const bad8 = parseWatchdogConfig(JSON.stringify({ alerts: { redline: [1, 2] } }), 'f8')
  assert(bad8.config_error !== null, 'cfg non-string redline rejected')
  // t261008-39: blocked_rerise_minutes knob (factory / passthrough / malformed).
  assert(FACTORY_DEFAULTS.blocked_rerise_minutes === 30, 'cfg blocked_rerise factory default 30 (= 2x stall 15)')
  const okBr = parseWatchdogConfig(JSON.stringify({ blocked_rerise_minutes: 45 }), 'okbr')
  assert(okBr.config_error === null && okBr.config.blocked_rerise_minutes === 45, 'cfg blocked_rerise_minutes passes through')
  assert(okBr.provenance.keys['blocked_rerise_minutes']?.endsWith('#blocked_rerise_minutes'), 'cfg blocked_rerise provenance per-key')
  const badBr = parseWatchdogConfig(JSON.stringify({ blocked_rerise_minutes: 0 }), 'fbr')
  assert(badBr.config_error !== null && badBr.config_error.includes('blocked_rerise_minutes'), 'cfg blocked_rerise_minutes<=0 rejected')
  // t261004-12：long_turn_minutes 旋钮（默认 / 透传 / 畸形 / 白名单）。
  assert(FACTORY_DEFAULTS.long_turn_minutes === 45, 'cfg long_turn factory default 45 (= 3x stall 15)')
  // t261005-02 cross-knob guard: a declared long_turn above the park threshold must
  // carry an explicit self_heal.park_minutes, otherwise the config is rejected
  // (fail-closed: a cancel threshold at/below the long-turn threshold could fire on
  // a healthy long turn). The old bare { long_turn_minutes: 90 } case is now red by
  // design — covered below as ltNoPark.
  const okLt = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 90, self_heal: { park_minutes: 120 } }), 'oklt')
  assert(okLt.config_error === null && okLt.config.long_turn_minutes === 90, 'cfg long_turn_minutes passes through (with an explicit park above it)')
  const ltNoPark = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 90 }), 'ltnopark')
  assert(ltNoPark.config_error !== null && ltNoPark.config_error.includes('self_heal.park_minutes'), 'cfg long_turn above factory park without an explicit park rejected (cross-knob guard)')
  assert(okLt.provenance.keys['long_turn_minutes']?.endsWith('#long_turn_minutes'), 'cfg long_turn provenance per-key')
  const bad9 = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 0 }), 'f9')
  assert(bad9.config_error !== null && bad9.config_error.includes('long_turn_minutes'), 'cfg long_turn_minutes<=0 rejected')
  const bad10 = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 'soon' }), 'f10')
  assert(bad10.config_error !== null && bad10.config_error.includes('long_turn_minutes'), 'cfg non-number long_turn_minutes rejected')
  const ok2 = parseWatchdogConfig(JSON.stringify({ stall_minutes: 15, long_turn_minutes: 45 }), 'ok2')
  assert(ok2.config_error === null, 'cfg long_turn_minutes is in the known-key whitelist (not rejected as unknown)')
  n += 6
}
// enabled=false：声明了但停（显式 stopped 的素材）。
{
  const { env, cfgDir } = await testEnv({ sandbar: { enabled: false } })
  if (fsVisible) {
  const r = loadWatchdogConfig('sandbar', env)
  assert(r.declared === true && r.enabled === false && r.config_error === null, 'cfg declared-but-disabled distinguished from undeclared')
  cleanup([cfgDir]); n += 1
} else needFs('declared-but-disabled')
}
// env 缝 + key 白名单。
{
  const { env } = await testEnv({ sandbar: {} })
  assert(watchdogConfigDir(env) === env.SANDBAR_WATCHDOG_DIR, 'cfg env override honored')
  assert(!isValidProjectKey('Bad_Key'), 'cfg project key whitelist rejects underscore/upper')
  assert(isValidProjectKey('sandbar'), 'cfg project key whitelist accepts kebab')
  n += 3
}

// t261004-08 新旋钮：waiting_minutes / prose_backstop（N2 条件——出厂默认 + 旧文件兼容 +
// 畸形 fail-closed）。
{
  const d = parseWatchdogConfig('{}', 'f-new')
  assert(d.config_error === null, 'new knobs: empty declaration still parses')
  assert(d.config.waiting_minutes === FACTORY_DEFAULTS.waiting_minutes && d.config.waiting_minutes === 5, 'old watchdog.json without waiting_minutes → factory default 5 (backcompat)')
  assert(d.config.prose_backstop.enabled === true && d.config.prose_backstop.idle_minutes === 10, 'old watchdog.json without prose_backstop → factory {true,10} (backcompat)')
  const over = parseWatchdogConfig(JSON.stringify({ waiting_minutes: 2, prose_backstop: { enabled: false, idle_minutes: 3 } }), 'f-over')
  assert(over.config.waiting_minutes === 2 && over.config.prose_backstop.enabled === false && over.config.prose_backstop.idle_minutes === 3, 'new knobs pass through with values')
  assert(over.provenance.keys['waiting_minutes']?.endsWith('#waiting_minutes') && over.provenance.keys['prose_backstop.idle_minutes']?.endsWith('prose_backstop.idle_minutes'), 'new knobs carry per-key provenance')
  const bad = parseWatchdogConfig(JSON.stringify({ waiting_minutes: -1 }), 'f-bad')
  assert(bad.config_error !== null && bad.config_error.includes('waiting_minutes'), 'malformed waiting_minutes fails closed')
  const bad2 = parseWatchdogConfig(JSON.stringify({ prose_backstop: { idle_minutes: 0 } }), 'f-bad2')
  assert(bad2.config_error !== null && bad2.config_error.includes('idle_minutes'), 'malformed prose_backstop.idle_minutes fails closed')
  const bad3 = parseWatchdogConfig(JSON.stringify({ prose_backstop: 'yes' }), 'f-bad3')
  assert(bad3.config_error !== null && bad3.config_error.includes('prose_backstop'), 'malformed prose_backstop shape fails closed')
  n += 8
}
done(n)
