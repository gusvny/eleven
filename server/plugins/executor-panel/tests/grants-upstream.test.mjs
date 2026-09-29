/**
 * grants-upstream.test.mjs —— GAP B 反证（t260929-22）：grants 的上游基址必须有
 * 真生产者——普通生产形态控制台（无 SANDBAR_WORKBENCH_BASE、无 config）经**请求
 * 来源（Host）推同源基址**可解析，模板事实可得 → 授权面**不降级**。
 *
 * 纪律分层：
 *   - 显式降级只留给真不可达（fetch 失败/非 200/形状认不出）——照旧点名原因；
 *   - Host 可信边界：仅取 `http://<host>` 原样拼接，不注入凭据不跟随路径；
 *     伪造 Host 只会让上游不可达 → 落进既有的显式降级（可接受失败模式）。
 * 全部 fetch 走本进程桩（globalThis.fetch 替换，收尾还原），零真实网络。
 */
import { assert, done, freshDir, cleanup, isolatedEnv, fakeClock } from './lib.mjs'
import { createApi } from '../src/host/api.ts'

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)
let n = 0

const WF_PAYLOAD = { workflows: [
  { name: 'dev-lane', kind: 'dev', has_human_gate: true },
  { name: 'inspection', kind: 'inspection', has_human_gate: false },
] }

/** 装一个 fetch 桩：记录收到的 URL，按判定回。返回 [restore, urls]。 */
function stubFetch(reply) {
  const urls = []
  const orig = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : String(input.url)
    urls.push({ url, init })
    return reply(url, init)
  }
  return () => { globalThis.fetch = orig; return urls }
}

// ---- 生产形态：env 无基址、无 config，仅请求来源 → 同源可解析 → 不降级 ----
{
  const restore = stubFetch((url) => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 }))
  try {
    const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })
    const r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '', 'http://127.0.0.1:3099')
    assert(r.status === 200, `origin-default: HTTP 200 (${++n})`)
    assert(r.json.ok === true && r.json.degraded === false, `origin-default: NOT degraded (${++n})`)
    assert(r.json.grants.ok === true && Array.isArray(r.json.grants.rows) && r.json.grants.rows.length > 0, `origin-default: derived rows (${++n})`)
    const urls = restore()
    assert(urls.length === 1 && urls[0].url === 'http://127.0.0.1:3099/sandbar-workbench/api/wf/workflows', `origin-default: same-origin workflows URL (${++n})`)
    assert(Boolean(urls[0].init?.signal), `origin-default: fetch carries timeout signal (${++n})`)
  } catch (e) { restore(); throw e }
}

// ---- 显式优先级：config workbenchBase > env > 来源（node.ts 旧死接线补测）----
{
  const restore = stubFetch((url) => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 }))
  try {
    const api = createApi(env, { now: () => clock.now(), workbenchBase: 'http://cfg-host:1', declaredEnabled: () => ({ declared: true, enabled: true }) })
    await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '', 'http://req-origin:2')
    const urls = restore()
    assert(urls[0].url.startsWith('http://cfg-host:1/'), `config base beats origin (${++n})`)
  } catch (e) { restore(); throw e }
}
{
  process.env.SANDBAR_WORKBENCH_BASE = 'http://env-host:3'
  const restore = stubFetch((url) => new Response(JSON.stringify(WF_PAYLOAD), { status: 200 }))
  try {
    const api = createApi(process.env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })
    await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '', 'http://req-origin:4')
    const urls = restore()
    assert(urls[0].url.startsWith('http://env-host:3/'), `env base beats origin (${++n})`)
  } catch (e) { restore(); throw e } finally { delete process.env.SANDBAR_WORKBENCH_BASE }
}

// ---- 真不可达仍显式降级（点名原因），绝不空表冒充 ----
{
  const restore = stubFetch(async () => { throw new Error('ECONNREFUSED (stub)') })
  try {
    const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })
    const r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '', 'http://127.0.0.1:1')
    assert(r.status === 200 && r.json.degraded === true && String(r.json.reason).includes('unreachable'), `unreachable: explicit degrade named (${++n})`)
    restore()
  } catch (e) { restore(); throw e }
}
// ---- 非 200 / 形状认不出 → 显式降级 ----
{
  const restore = stubFetch(() => new Response('{"nope":1}', { status: 200 }))
  try {
    const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })
    const r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '', 'http://127.0.0.1:2')
    assert(r.json.degraded === true, `shape drift: explicit degrade (${++n})`)
    restore()
  } catch (e) { restore(); throw e }
}
// ---- 无来源（老调用形状）且无任何基址 → 降级但点名缺什么 ----
{
  const restore = stubFetch(() => { throw new Error('must not fetch') })
  try {
    const api = createApi(env, { now: () => clock.now(), declaredEnabled: () => ({ declared: true, enabled: true }) })
    const r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q('project=sandbar'), '')
    assert(r.json.degraded === true && String(r.json.reason).includes('origin'), `no origin no base: degrade names the gap (${++n})`)
    restore()
  } catch (e) { restore(); throw e }
}

cleanup([wd, pan])
done(n)
