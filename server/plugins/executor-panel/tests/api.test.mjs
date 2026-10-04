/**
 * api.test.mjs —— API 层 UT（review 意见 #2 的落点）：POST 端点消费外部输入，
 * 畸形输入全在 API 级显式拒绝——非 JSON 体、缺必填字段、坏 project key、二次应答；
 * 另盖 settings 保存/拒收回路与 grants 注入桩、405/404 面。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { assert, done, freshDir, cleanup, isolatedEnv, fakeClock, authPass, engineWriteStub } from './lib.mjs'
import { createApi } from '../src/host/api.ts'

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const clock = fakeClock()
// KI-193：写面要过凭据门（defaultAuthFace 的拒绝路径由 auth-gate.test.mjs 专测）；
// 授权写面走引擎入口的桩（spawn 面由 engine-grants-write.test.mjs 专测）。
const api = createApi(env, { now: () => clock.now(), fetchTemplateFacts: async () => ({ ok: false, reason: 'stub: template facts unavailable', source: 'workbench-workflows' }), authFace: authPass, engineGrantsWrite: engineWriteStub(env, () => clock.now()) })
let n = 0
const Q = (s = '') => new URLSearchParams(s)

// ---- requests append（POST 消费外部输入）----
let r = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), 'not json at all')
assert(r.status === 400 && r.json.error.includes('JSON'), 'append: non-JSON body → 400 with reason')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), '{"project":"alpha"}')
assert(r.status === 422, 'append: missing required fields → 422')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), JSON.stringify({ project: '../evil', kind: 'sign', question: 'q?' }))
assert(r.status === 400, 'append: traversal project key → 400')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), JSON.stringify({ project: 'alpha', kind: '', question: 'q?' }))
assert(r.status === 422, 'append: empty kind → 422')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), JSON.stringify({ project: 'alpha', kind: 'sign', question: 'Merge T-1?', default_action: 'approve', expires_at: new Date(clock.now() + 60_000).toISOString() }))
assert(r.status === 200 && r.json.ok === true, 'append: valid request stored')
const rid = r.json.row.id
r = await api.handle('PUT', '/sandbar-executor-panel/api/requests', Q(), '')
assert(r.status === 405, 'requests: DELETE/PUT → 405')

// ---- answer（二次应答显式拒绝，review #2）----
r = await api.handle('POST', '/sandbar-executor-panel/api/requests/answer', Q(), '[]')
assert(r.status === 400, 'answer: non-object body → 400')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests/answer', Q(), JSON.stringify({ project: 'alpha' }))
assert(r.status === 400, 'answer: missing id/answer → 400')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests/answer', Q(), JSON.stringify({ project: 'alpha', id: rid, answer: 'ok' }))
assert(r.status === 200, 'answer: first answer ok')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests/answer', Q(), JSON.stringify({ project: 'alpha', id: rid, answer: 'again' }))
assert(r.status === 409 && r.json.error.includes('拒绝二次应答'), 'answer: second answer → 409 explicit rejection')
r = await api.handle('POST', '/sandbar-executor-panel/api/requests/answer', Q(), JSON.stringify({ project: 'alpha', id: 'req-ghost', answer: 'x' }))
assert(r.status === 404, 'answer: unknown id → 404')

// ---- requests read：分组 + urgency + malformed 计数 ----
r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q('project=alpha'), '')
assert(r.status === 200 && r.json.groups.length === 1 && r.json.groups[0].rows[0].status === 'answered', 'read: grouped by project, merged answer')
assert(Array.isArray(r.json.rows) && r.json.rows.length === 1, 'read: top-level rows exposed (single-project consumer shape)')
assert(r.json.groups[0].rows[0].urgency.waiting_ms >= 0, 'read: waiting time computed server-side')
r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q('project=BAD_KEY'), '')
assert(r.status === 400, 'read: invalid project key → 400')
r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q(), '')
assert(r.status === 200 && Array.isArray(r.json.groups), 'read: no project = all panel projects (grouping source)')

// ---- settings：GET / save / 拒收回路（盘上字节不动）/ revoke / sleep ----
r = await api.handle('GET', '/sandbar-executor-panel/api/settings', Q('project=alpha'), '')
assert(r.status === 200 && r.json.declared === false, 'settings read: undeclared = declared:false')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=BAD'), '{"op":"save","config":{}}')
assert(r.status === 400, 'settings save: invalid key → 400')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), '{bad json')
assert(r.status === 400, 'settings save: non-JSON body → 400')
const goodCfg = { enabled: true, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['stall'], keep_days: 14 } }
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ declaration: goodCfg }))
assert(r.status === 200 && r.json.saved === true, 'settings save: valid config saved (declaration body shape accepted)')
const file = join(wd, 'alpha', 'watchdog.json')
const bytes = readFileSync(file, 'utf8')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ op: 'save', config: { ...goodCfg, mystery: true } }))
assert(r.status === 200 && r.json.saved === false && r.json.error.length > 0, 'settings save: unknown key rejected-on-write (saved:false + human-readable reason, KI-149)')
assert(readFileSync(file, 'utf8') === bytes, 'rejected save leaves the on-disk declaration byte-identical')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ op: 'revoke' }))
assert(r.status === 200 && r.json.saved === true, 'settings revoke: one-click revoke via validate-on-write')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ declaration: goodCfg }))
assert(r.status === 200 && r.json.saved === true, 'settings re-save restores full declaration')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ op: 'sleep', policy: 'silent', until: clock.now() + 1000 }))
assert(r.status === 200, 'settings sleep: valid toggle ok')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ op: 'sleep', policy: 'silent', until: clock.now() - 5 }))
assert(r.status === 422, 'settings sleep: past expiry rejected')
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q('project=alpha'), JSON.stringify({ op: 'explode' }))
assert(r.status === 422, 'settings: unknown op rejected')
r = await api.handle('GET', '/sandbar-executor-panel/api/settings', Q('project=alpha'), '')
assert(r.status === 200 && r.json.night_override_active === true, 'settings read: override active flag exposed')

// ---- grants：注入桩（不可达=显式降级；形状漂移=显式降级）----
r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=alpha'), '')
assert(r.status === 200 && r.json.degraded === true && r.json.grants.ok === false && r.json.grants.reason.includes('stub'), 'grants: template facts unavailable → explicit degraded flag + object, not an empty list')
const api2 = createApi(env, {
  now: () => clock.now(),
  fetchTemplateFacts: async () => ({ ok: true, facts: [{ name: 'dev-lane', kind: 'dev', has_human_gate: true }] }),
})
r = await api2.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=alpha'), '')
const rows = r.json.grants.rows
assert(r.json.grants.ok === true && rows.length > 0, 'grants: facts present → derived rows')
assert(r.json.degraded === false, 'grants: healthy derivation is not flagged degraded')
assert(typeof r.json.grants.filtered === 'number', 'grants: filtered count exposed for the derivation note')

// ---- 404/405 刚性 ----
r = await api.handle('GET', '/sandbar-executor-panel/api/unknown', Q(), '')
assert(r.status === 404, 'unknown panel route → 404')
// t260930-14：grants 面从 GET-only 变成读写编辑器——POST=声明写面（合法），
// 其余写方法仍 405；空体 POST=非 JSON → 400。
r = await api.handle('POST', '/sandbar-executor-panel/api/grants', Q('project=alpha'), '')
assert(r.status === 400, 'grants: POST with non-JSON body → 400 (editor write face, t260930-14)')
r = await api.handle('DELETE', '/sandbar-executor-panel/api/grants', Q('project=alpha'), '')
assert(r.status === 405, 'grants: DELETE → 405')

cleanup([wd, pan])
n += 30
done(n)
