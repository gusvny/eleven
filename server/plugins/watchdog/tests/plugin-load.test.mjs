import { assert, done } from './lib.mjs'
// 插件面加载 UT：node.ts 可被 Node strip-mode 加载、导出面形状正确（不调用 apply——
// 宿主服务不可桩于此；apply 的路由/守卫逻辑由 surface 相关纯面 + statusFor 形状覆盖）。
let n = 0
const mod = await import('../node.ts')
assert(mod.name === 'sandbar-watchdog', 'plugin name exported')
assert(Array.isArray(mod.inject) && mod.inject.length === 0, 'no hard inject dependencies (headless standby)')
assert(typeof mod.apply === 'function', 'apply exported')
assert(typeof mod.makeBoardReader === 'function' && typeof mod.makeWakeIo === 'function', 'host-API seams exported (t260929-04: real sessionController)')
// boardReader：坏 repo → 结构化失败（不裸抛）；无 project 选项 = 全局读面（t260929-07
// 真形锁 sc C 段契约：makeBoardReader(repo) 单参调用必须照常工作，rows 不被裁空）。
{
  const r = await mod.makeBoardReader('/nonexistent-repo')()
  assert(r.ok === false && typeof r.error === 'string' && r.error.length > 0, 'boardReader failure = structured, never throw')
  const r2 = await mod.makeBoardReader('/nonexistent-repo', { project: 'sandbar' })()
  assert(r2.ok === false && typeof r2.error === 'string' && r2.error.length > 0, 'boardReader with project option: same structured failure')
}
// wakeIo：宿主服务不可达 → accepted:false + 点名（显式不可用，绝不静默）。
{
  const fakeCtx = { get: () => undefined }
  const io = mod.makeWakeIo(fakeCtx)
  const r = await io.prompt('executor-x', 'hello', 'queue')
  assert(r.accepted === false && (r.error ?? '').includes('不可达'), 'wakeIo unavailable = explicit refused with reason')
  assert(await io.queueDepth('executor-x') === null, 'queue mirror unwired = explicit null')
}
// wakeIo：mock 宿主 sessionController → 真 API 形状走通（t260929-04）：
// prompt 收到 {requestId:'watchdog-*', sessionId, mode, content:[{type:'text',text}]}；
// 队列镜像从 control() 流认领 rpcId；digest 后 ourBriefPending=false。
{
  const q = []
  let ended = false
  const stream = {
    push(f) { q.push(f) },
    end() { ended = true },
    [Symbol.asyncIterator]() {
      return {
        next: async () => {
          for (;;) {
            if (q.length > 0) return { value: q.shift(), done: false }
            if (ended) return { value: undefined, done: true }
            await new Promise(r => setTimeout(r, 1))
          }
        },
      }
    },
  }
  const pushes = []
  const controller = {
    prompt: async (req) => { pushes.push(req); return { accepted: true } },
    control: () => stream,
  }
  const io = mod.makeWakeIo({ get: (k) => (k === 'sessionController' ? controller : undefined) })
  const r = await io.prompt('executor-x', 'brief body', 'queue')
  assert(r.accepted === true && typeof r.requestId === 'string' && r.requestId.startsWith('watchdog-'), 'real prompt path accepted, client-minted watchdog- requestId returned')
  assert(pushes.length === 1 && pushes[0].sessionId === 'executor-x' && pushes[0].mode === 'queue'
    && Array.isArray(pushes[0].content) && pushes[0].content[0].type === 'text' && pushes[0].content[0].text === 'brief body'
    && pushes[0].requestId === r.requestId, 'SessionPromptRequest shape matches dsh .d.ts (requestId/sessionId/mode/content)')
  assert(await io.queueDepth('executor-x') === null, 'mirror before baseline = explicit null (no-signal)')
  stream.push({ type: 'baseline', value: { queues: {} } })
  await new Promise(r2 => setTimeout(r2, 20))
  stream.push({ type: 'queue', sessionId: 'executor-x', items: [{ id: 'i1', placement: 'queued', rpcId: r.requestId }] })
  await new Promise(r2 => setTimeout(r2, 20))
  assert(await io.queueDepth('executor-x') === 1, 'mirror live: our queued brief visible')
  assert(await io.ourBriefPending('executor-x', r.requestId) === true, 'our brief pending via rpcId claim')
  assert((io.transportState?.() ?? '').includes('live'), 'transportState reports live mirror')
  stream.push({ type: 'queue', sessionId: 'executor-x', items: [] })
  await new Promise(r2 => setTimeout(r2, 20))
  assert(await io.ourBriefPending('executor-x', r.requestId) === false, 'after digestion our brief no longer pending (wake can resume)')
  stream.end()
  await io.dispose?.()
}
// 项目 key 白名单（路由 400 面）。
{
  const { isValidProjectKey } = await import('../src/host/config.ts')
  assert(isValidProjectKey('sandbar') && !isValidProjectKey('../evil'), 'route key whitelist rejects traversal shapes')
}
done(n + 11)
