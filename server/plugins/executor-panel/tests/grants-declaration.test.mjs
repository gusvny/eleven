/**
 * grants-declaration.test.mjs —— grants API 声明面 UT（t260930-14）：
 *  - GET /api/grants 带 declaration + declaration_state + provenance（溯源杆）；
 *  - POST /api/grants 编辑器写面：保存成功 / 拒收=200+saved:false / 非 JSON=400 /
 *    坏 project=400 / 元权限反锁=拒收；
 *  - settings revoke：收回变真——watchdog enabled:false + 授权声明清空；
 *  - 模板事实不可达时声明面照常可读（派生面降级不掩盖声明面）。
 * 零真实 ~/.sandbar、零 3099、零真网络（fetch 桩）。
 */
import { assert, done, freshDir, cleanup, fakeClock } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { declarationPath, auditPath, EXECUTOR_SURFACE } from '../src/host/executor-grants.ts'
import { readFileSync, existsSync } from 'node:fs'

const wd = freshDir(), pan = freshDir()
const env = { HOME: '/nonexistent-home', SANDBAR_WATCHDOG_DIR: wd, SANDBAR_PANEL_DIR: pan, SANDBAR_PROJECTS_DIR: wd }
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)
const PATH = '/sandbar-executor-panel/api/grants'
let n = 0

const WF_PAYLOAD = { workflows: [{ name: 'dev-lane', kind: 'dev', has_human_gate: true }] }
const stubFetch = () => {
  const orig = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 })
  return () => { globalThis.fetch = orig }
}

try {
  const restore = stubFetch()
  const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })

  // ---- GET：声明缺席时 declaration_state.kind=absent，派生面照常 ----
  {
    const r = await api.handle('GET', PATH, Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    assert(r.status === 200 && r.json.ok === true, `get: 200 (${++n})`)
    assert(r.json.declaration === null && r.json.declaration_state.kind === 'absent',
        `get: absent declaration named (${++n})`)
    assert(r.json.provenance.keys.sign.includes('no-usable-declaration'),
        `get: provenance names no-usable-declaration (${++n})`)
    assert(r.json.grants.ok === true, `get: derived rows intact (${++n})`)
  }

  // ---- POST：保存 → GET 读回 + 溯源变 granted ----
  {
    const r = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { sign: true }, by: 'host' }), '')
    assert(r.status === 200 && r.json.saved === true, `post: saved (${++n})`)
    const g = await api.handle('GET', PATH, Q('project=sandbar'), '', '')
    assert(g.json.declaration.grants.sign === true, `get: declaration roundtrip (${++n})`)
    assert(g.json.provenance.keys.sign.includes('grants.sign'), `get: provenance granted (${++n})`)
    const rows = readFileSync(auditPath('sandbar', env), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
    assert(rows.length === 1 && rows[0].action === 'grant-change' && rows[0].who === 'host',
        `post: audit row (${++n})`)
  }

  // ---- POST：编辑器拒收面（坏 op / 缺 by / 非 JSON / 坏 project） ----
  {
    const r1 = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { fly: true }, by: 'host' }), '')
    assert(r1.status === 200 && r1.json.saved === false && r1.json.reason.includes('fly'),
        `post: unknown op refused as 200+saved:false (${++n})`)
    const r2 = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { sign: true } }), '')
    assert(r2.status === 200 && r2.json.saved === false && r2.json.reason.includes('by'),
        `post: missing by refused (${++n})`)
    const r3 = await api.handle('POST', PATH, Q('project=sandbar'), 'not-json', '')
    assert(r3.status === 400, `post: non-JSON body 400 (${++n})`)
    const r4 = await api.handle('POST', PATH, Q('project=BAD_KEY'), JSON.stringify({ grants: {}, by: 'h' }), '')
    assert(r4.status === 400, `post: malformed project key 400 (${++n})`)
  }

  // ---- POST：元权限反锁（executor 身份标记在场即拒） ----
  {
    const r = await api.handle('POST', PATH, Q('project=sandbar'),
        JSON.stringify({ grants: { cleanup: true }, by: 'executor', caller_surface: EXECUTOR_SURFACE }), '')
    assert(r.status === 200 && r.json.saved === false && r.json.reason.includes('反锁'),
        `post: executor widening refused (${++n})`)
  }

  // ---- settings revoke：收回变真（watchdog + 授权声明一起清） ----
  {
    const r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=sandbar'),
        JSON.stringify({ op: 'revoke', by: 'host' }), '')
    assert(r.status === 200 && r.json.saved === true, `revoke: 200 saved (${++n})`)
    const g = await api.handle('GET', PATH, Q('project=sandbar'), '', '')
    assert(g.json.declaration && Object.keys(g.json.declaration.grants).length === 0,
        `revoke: grants declaration cleared (${++n})`)
    assert(g.json.provenance.keys.sign.includes('not-declared'),
        `revoke: provenance shows default-refuse (${++n})`)
  }

  restore()
} finally {
  cleanup([wd, pan])
}
done(n)
