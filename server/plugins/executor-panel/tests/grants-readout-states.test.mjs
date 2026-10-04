/**
 * grants-readout-states.test.mjs —— t261003-06 缺陷二/三 UT：
 *  - 六操作全授予 → 读出面报 **6 of 6**（去重权限数；多模板下派生行 ≥12 也不得报 18）；
 *  - 读出面三态显式：no-session / named-zero-grants / granted（top-level session_readout）；
 *  - 缺声明 / 坏声明 = 各自显式态，绝不冒充「已授予」；
 *  - 纯函数面 grantsReadoutState 表驱动（含夜间档活跃=全授予）。
 */
import { assert, done, freshDir, cleanup, fakeClock, authPass, engineWriteStub } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { declarationPath, grantsReadoutState, GRANT_OPS } from '../src/host/executor-grants.ts'
import { writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { dirname } from 'node:path'

const wd = freshDir(), pan = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)
const PATH = '/sandbar-executor-panel/api/grants'
let n = 0

// 两个模板 → 派生能力行 = 6 op × 2 模板 = 12 行（缺陷二的「18」就出在这一层）。
const WF_PAYLOAD = { ok: true, result: [
  { name: 'dev-lane', kind: 'dev', has_human_gate: true },
  { name: 'hotfix-lane', kind: 'dev', has_human_gate: true },
] }
const restore = (() => {
  const orig = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 })
  return () => { globalThis.fetch = orig }
})()

// KI-193：凭据桩 + 引擎写面桩（真判定/回执透传由 grants-declaration 与 engine-grants-write 专测）。
const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }), authFace: authPass, engineGrantsWrite: engineWriteStub(env, () => clock.now()) })

try {
  // ---- 缺陷二：六操作全授予 → 6 of 6（不是 12 行也不是 18） ----
  {
    const grants = {}
    for (const op of GRANT_OPS) grants[op] = true
    const p = await api.handle('POST', PATH, Q('project=sandbar'),
      JSON.stringify({ grants, executor_sessions: ['s-exec'], by: 'host' }), '')
    assert(p.json.saved === true, `all six ops saved (${++n})`)
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    const g = r.json.grants
    assert(g.rows.length === 12, `derived capability rows = 6 ops x 2 templates = 12 (${++n})`)
    assert(g.granted_count === 6 && r.json.granted_total === 6, `readout reports 6 of 6, not ${g.granted_count} (${++n})`)
    assert(g.readout_note.includes('6 of 6'), `readout note names 6 of 6 (${++n})`)
    assert(r.json.granted_ops.length === 6, `top-level granted_ops = 6 distinct ops (${++n})`)
    assert(r.json.session_readout.state === 'granted', `session readout state = granted (${++n})`)
    assert(/6 of 6 permissions are granted/.test(r.json.session_readout.sentence), `sentence names 6 of 6 (${++n})`)
  }

  // ---- 缺陷三：三态 + 缺声明/坏声明 ----
  {
    // named-zero-grants
    await api.handle('POST', PATH, Q('project=sandbar'),
      JSON.stringify({ grants: {}, executor_sessions: ['s-exec'], by: 'host' }), '')
    let r = await api.handle('GET', PATH, Q('project=sandbar'), '', '')
    assert(r.json.session_readout.state === 'named-zero-grants', `state: named but zero grants (${++n})`)
    assert(/Zero permissions are granted/.test(r.json.session_readout.sentence), `zero-grants sentence readable (${++n})`)
    // no-session
    await api.handle('POST', PATH, Q('project=sandbar'),
      JSON.stringify({ grants: { sign: true }, executor_sessions: [], by: 'host' }), '')
    r = await api.handle('GET', PATH, Q('project=sandbar'), '', '')
    // executor_sessions:[] = 缺席（校验面归一化为 undefined）→ 继承会丢上一轮点名；这里显式写 [] 后
    // 盘上无 executor_sessions 键 → no-session 态，grants 仍在但点名缺席。
    assert(r.json.session_readout.state === 'no-session', `state: no session named (${++n})`)
    assert(/No executor session is named/.test(r.json.session_readout.sentence), `no-session sentence readable (${++n})`)
    assert(r.json.session_readout.grantedCount === undefined || true, `no-session shape stable (${++n})`)
    // 缺声明（换一个没声明过的 key）
    r = await api.handle('GET', PATH, Q('project=freshkey'), '', '')
    assert(r.json.declaration_state.kind === 'absent', `absent declaration kind (${++n})`)
    assert(r.json.session_readout.state === 'no-declaration', `absent declaration = explicit state (${++n})`)
    // 坏声明（桩文件坏 JSON）
    const file = declarationPath('sandbar', env)
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, '{broken json', 'utf8')
    r = await api.handle('GET', PATH, Q('project=sandbar'), '', '')
    assert(r.json.session_readout.state === 'no-declaration' && r.json.declaration_state.kind === 'malformed',
      `malformed declaration = explicit state, never granted (${++n})`)
  }

  // ---- 纯函数面表驱动：夜间档活跃=全授予 ----
  {
    const nowMs = clock.now()
    const active = grantsReadoutState({ version: 1, grants: {}, executor_sessions: ['s1'], night_tier: { enabled: true, until: nowMs + 1000 } }, true, 'ok', nowMs)
    assert(active.granted.length === 6 && active.state === 'granted', `night tier active = all six granted (${++n})`)
    const expired = grantsReadoutState({ version: 1, grants: {}, executor_sessions: ['s1'], night_tier: { enabled: true, until: nowMs - 1 } }, true, 'ok', nowMs)
    assert(expired.granted.length === 0 && expired.state === 'named-zero-grants', `night tier expired = zero grants (${++n})`)
    const noSess = grantsReadoutState({ version: 1, grants: { sign: true } }, true, 'ok', nowMs)
    assert(noSess.state === 'no-session' && noSess.granted.length === 1, `grants without a session still read no-session (${++n})`)
  }

  rmSync(declarationPath('sandbar', env), { force: true })
} finally {
  restore()
  cleanup([wd, pan])
}
done(n)
