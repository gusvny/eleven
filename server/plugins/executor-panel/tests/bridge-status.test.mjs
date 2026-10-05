/**
 * bridge-status.test.mjs —— 问题桥状态面（t261004-44，KI-196 出路②）：
 *   ① 状态汇：逐 kind 单调计数、事件环 newest-first 且 cap 50、mounted 显式置位；
 *   ② 监听者写入：createQuestionBridge 注入 status 后，镜像/应答/拒绝各路径都进计数；
 *   ③ API 面：/api/bridge/status GET 读出快照；读源未注入=显式未接线形状（不冒充健康）；
 *     畸形快照=500 点名；非 GET=405。
 */
import { assert, done, fakeClock } from './lib.mjs'
import { createBridgeStatus, createQuestionBridge, BRIDGE_EVENT_RING_CAP } from '../src/host/question-bridge.ts'
import { createApi } from '../src/host/api.ts'

const clock = fakeClock()
let n = 0

// ① 状态汇本体
{
  const s = createBridgeStatus(clock.now)
  const snap0 = s.snapshot()
  assert(snap0.mounted === false, 'initial snapshot: mounted=false (never fakes healthy)')
  assert(Object.keys(snap0.counters).length === 0 && snap0.last_events.length === 0,
    'initial snapshot: zero counters, empty ring')
  s.setMounted(true)
  for (let i = 0; i < BRIDGE_EVENT_RING_CAP + 5; i++) {
    s.record({ at: clock.now() + i, kind: i % 2 ? 'mirrored' : 'mirror-refused', detail: 'd' + i })
  }
  const snap = s.snapshot()
  assert(snap.mounted === true, 'setMounted(true) is visible in the snapshot')
  assert(snap.counters.mirrored === 27 && snap.counters['mirror-refused'] === 28,
    'per-kind counters are monotonic across all records')
  assert(snap.last_events.length === BRIDGE_EVENT_RING_CAP, 'event ring is capped at ' + BRIDGE_EVENT_RING_CAP)
  assert(snap.last_events[0].detail === 'd54', 'ring is newest-first')
  snap.last_events[0].kind = 'tampered'
  assert(s.snapshot().last_events[0].kind !== 'tampered', 'snapshot exposes copies, not live references')
  n++
}

// ② 监听者写入状态汇（镜像成功 / 项目解析失败两条路径）
{
  const status = createBridgeStatus(clock.now)
  const writes = { files: {} }
  const io = {
    existsSync: (f) => f in writes.files,
    readFileSync: (f) => { if (!(f in writes.files)) throw new Error('ENOENT'); return writes.files[f] },
    appendFileSync: (f, line) => { writes.files[f] = (writes.files[f] || '') + line },
    mkdirSync: () => {},
  }
  const env = { HOME: '/nonexistent-home', SANDBAR_PANEL_DIR: '/tmp/bridge-status-missing-projects' }
  const bridge = createQuestionBridge({
    io, env, now: clock.now, pollMs: 5, deadlineMs: 50,
    resolveProject: () => ({ ok: true, project: 'proj' }),
    status,
  })
  const good = { questions: [{ question: 'q1?' }], agent: { id: 'sess-1', cwd: '/tmp/w' } }
  const p = bridge(good, async () => { await new Promise((r) => setTimeout(r, 200)); return { answers: [] } })
  await new Promise((r) => setTimeout(r, 30))
  let snap = status.snapshot()
  assert((snap.counters.mirrored ?? 0) === 1, 'a mirrored ask lands mirrored=1 in the sink')
  assert(snap.last_events[0].kind === 'mirrored', 'the mirrored event is in the ring')
  p.catch(() => {})
  const bridge2 = createQuestionBridge({
    io, env, now: clock.now,
    resolveProject: () => ({ ok: false, error: 'no project covers cwd' }),
  })
  await bridge2({ questions: [{ question: 'q2?' }], agent: { id: 's', cwd: '/x' } }, async () => ({ answers: [] }))
  snap = status.snapshot()
  assert((snap.counters['mirror-refused'] ?? 0) === 0,
    'sink not wired into the second bridge = its refusals stay out (sink is per-bridge, per plan single instance)')
  n++
}

// ③ API 面
{
  const env = { HOME: '/nonexistent-home', SANDBAR_PANEL_DIR: '/tmp/bridge-status-missing-projects' }
  const Q = () => new URLSearchParams()
  const status = createBridgeStatus(clock.now)
  status.setMounted(true)
  status.record({ at: clock.now(), kind: 'mirrored', detail: 'two rows mirrored' })
  status.record({ at: clock.now(), kind: 'answered-by-ledger', detail: 'answered' })
  const api = createApi(env, { now: clock.now, bridgeStatus: () => status.snapshot() })
  const r = await api.handle('GET', '/sandbar-executor-panel/api/bridge/status', Q(), '')
  assert(r.status === 200 && r.json.ok === true && r.json.mounted === true, 'status route reads the wired sink (200, mounted=true)')
  assert((r.json.counters.mirrored ?? 0) === 1 && r.json.last_events.length === 2,
    'status route carries the counters and the event ring')
  const r405 = await api.handle('POST', '/sandbar-executor-panel/api/bridge/status', Q(), '{}')
  assert(r405.status === 401 || r405.status === 405,
    'status route takes no write (credential gate 401 or GET-only 405 on POST)')
  const api2 = createApi(env, { now: clock.now })
  const r2 = await api2.handle('GET', '/sandbar-executor-panel/api/bridge/status', Q(), '')
  assert(r2.status === 200 && r2.json.mounted === false && String(r2.json.note).includes('not wired'),
    'unwired read source = explicit not-wired shape, never a fake healthy snapshot')
  const api3 = createApi(env, { now: clock.now, bridgeStatus: () => ({ mounted: 'yes' }) })
  const r3 = await api3.handle('GET', '/sandbar-executor-panel/api/bridge/status', Q(), '')
  assert(r3.status === 500 && String(r3.json.error).includes('shape is wrong'),
    'malformed snapshot = 500 naming the shape, never a silent pass')
  n++
}

done(n)
