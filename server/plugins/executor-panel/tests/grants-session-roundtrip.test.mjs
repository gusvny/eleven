/**
 * grants-session-roundtrip.test.mjs —— t261003-06 缺陷一回归 UT：
 *  - 保存携带 executor_sessions → 盘上声明含点名（保存回执 saved:true 且真落盘）；
 *  - 此后任何一次保存（不带回点名）**不再抹掉**点名（继承语义）；
 *  - 总开关关（op:'master' enabled:false）→ grants 清空、点名保留、**watchdog.json 仍 enabled:true**
 *    （设计 note §7「收回授权只影响授权」——review C3 的 L3 注入用例）；
 *  - 总开关开 → 六操作全授予、点名仍保留；
 *  - settings 的 op=revoke（禁守望者面）→ 授权声明也清 grants、点名保留（两面不混）。
 * 畸形输入（坏会话 id 数组）在保存面被拒收、盘上原文件逐字节不动。
 */
import { assert, done, freshDir, cleanup, fakeClock, authPass, engineWriteStub } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { declarationPath } from '../src/host/executor-grants.ts'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'

const wd = freshDir(), pan = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)
const GRANTS = '/sandbar-executor-panel/api/grants'
const SETTINGS = '/sandbar-executor-panel/api/settings'
let n = 0

// KI-193：凭据桩 + 引擎写面桩（真判定/回执透传由 grants-declaration 与 engine-grants-write 专测）。
const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }), authFace: authPass, engineGrantsWrite: engineWriteStub(env, () => clock.now()) })
const declFile = () => declarationPath('rodalpha', env)
const readDecl = () => JSON.parse(readFileSync(declFile(), 'utf8'))

try {
  // watchdog 声明先在场且 enabled:true（C3 的前置：守望者在跑）。
  mkdirSync(join(wd, 'rodalpha'), { recursive: true })
  const wapi = await api.handle('POST', SETTINGS, Q('project=rodalpha'),
    JSON.stringify({ op: 'save', config: { enabled: true, stall_minutes: 15 } }), '')
  assert(wapi.json.saved === true, `watchdog declared enabled:true (${++n})`)

  // ① 保存带 executor_sessions → 盘上有点名。
  {
    const p = await api.handle('POST', GRANTS, Q('project=rodalpha'),
      JSON.stringify({ grants: { sign: true }, executor_sessions: ['session-09ca0247'], by: 'host' }), '')
    assert(p.json.saved === true, `save with session naming reports success (${++n})`)
    const d = readDecl()
    assert(Array.isArray(d.executor_sessions) && d.executor_sessions[0] === 'session-09ca0247',
      `written declaration carries the session naming (${++n})`)
    assert(d.grants.sign === true, `grants written alongside (${++n})`)
  }

  // ② 此后一次不带回点名的保存 → 点名仍在（缺陷一的第二后果被堵死）。
  {
    const p = await api.handle('POST', GRANTS, Q('project=rodalpha'),
      JSON.stringify({ grants: { sign: true, rerun: true }, by: 'host' }), '')
    assert(p.json.saved === true, `later save without sessions succeeds (${++n})`)
    const d = readDecl()
    assert(d.executor_sessions?.[0] === 'session-09ca0247', `later save KEEPS the session naming (${++n})`)
    assert(d.grants.rerun === true, `later save applies the grant edit (${++n})`)
  }

  // ③ 总开关关 → grants 清空、点名保留、watchdog.json 仍 enabled:true。
  {
    const p = await api.handle('POST', GRANTS, Q('project=rodalpha'),
      JSON.stringify({ op: 'master', enabled: false, by: 'host' }), '')
    assert(p.json.saved === true, `master off saved (${++n})`)
    const d = readDecl()
    assert(Object.keys(d.grants).length === 0, `master off clears all grants (${++n})`)
    assert(d.executor_sessions?.[0] === 'session-09ca0247', `master off KEEPS the session naming (${++n})`)
    const wd2 = JSON.parse(readFileSync(join(wd, 'rodalpha', 'watchdog.json'), 'utf8'))
    assert(wd2.enabled === true, `watchdog.json still enabled:true after master off — watchdog keeps running (${++n})`)
    const r = await api.handle('GET', GRANTS, Q('project=rodalpha'), '', '')
    assert(r.json.granted_ops.length === 0, `readout shows zero grants after master off (${++n})`)
    assert(r.json.session_readout.state === 'named-zero-grants', `readout state = named but zero grants (${++n})`)
  }

  // ④ 总开关开 → 六操作全授予、点名保留。
  {
    const p = await api.handle('POST', GRANTS, Q('project=rodalpha'),
      JSON.stringify({ op: 'master', enabled: true, by: 'host' }), '')
    assert(p.json.saved === true, `master on saved (${++n})`)
    const d = readDecl()
    assert(['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup'].every((k) => d.grants[k] === true),
      `master on grants all six ops (${++n})`)
    assert(d.executor_sessions?.[0] === 'session-09ca0247', `master on KEEPS the session naming (${++n})`)
  }

  // ⑤ settings 的 op=revoke（禁守望者面）→ grants 清空、点名保留（两面语义不混、字段不互吞）。
  {
    const p = await api.handle('POST', SETTINGS, Q('project=rodalpha'),
      JSON.stringify({ op: 'revoke' }), '')
    assert(p.json.saved === true, `legacy settings revoke saved (${++n})`)
    const d = readDecl()
    assert(Object.keys(d.grants ?? {}).length === 0, `legacy revoke clears grants (${++n})`)
    assert(d.executor_sessions?.[0] === 'session-09ca0247', `legacy revoke KEEPS the session naming (${++n})`)
    const wd2 = JSON.parse(readFileSync(join(wd, 'rodalpha', 'watchdog.json'), 'utf8'))
    assert(wd2.enabled === false, `legacy revoke still disables the watchdog (semantics unchanged) (${++n})`)
  }

  // ⑥ 畸形输入：坏会话数组拒收、盘上原文件不动。
  {
    const before = readFileSync(declFile(), 'utf8')
    const p = await api.handle('POST', GRANTS, Q('project=rodalpha'),
      JSON.stringify({ grants: {}, executor_sessions: [' '], by: 'host' }), '')
    assert(p.json.saved === false && /executor_sessions/.test(p.json.error), `blank session item rejected (${++n})`)
    assert(readFileSync(declFile(), 'utf8') === before, `rejected save left the file byte-identical (${++n})`)
    assert(!existsSync(declFile() + '.tmp'), `no tmp residue after rejection (${++n})`)
  }
} finally {
  cleanup([wd, pan])
}
done(n)
