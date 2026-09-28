import { assert, done } from './lib.mjs'
// 插件面加载 UT：node.ts 可被 Node strip-mode 加载、导出面形状正确（不调用 apply——
// 宿主服务不可桩于此；apply 的路由/守卫逻辑由 surface 相关纯面 + statusFor 形状覆盖）。
let n = 0
const mod = await import('../node.ts')
assert(mod.name === 'sandbar-watchdog', 'plugin name exported')
assert(Array.isArray(mod.inject) && mod.inject.length === 0, 'no hard inject dependencies (headless standby)')
assert(typeof mod.apply === 'function', 'apply exported')
assert(typeof mod.makeBoardReader === 'function' && typeof mod.makeWakeIo === 'function', 'probe seams exported (S1-probe落点)')
// boardReader：坏 repo → 结构化失败（不裸抛）。
{
  const r = await mod.makeBoardReader('/nonexistent-repo')()
  assert(r.ok === false && typeof r.error === 'string' && r.error.length > 0, 'boardReader failure = structured, never throw')
}
// wakeIo：宿主服务不可达 → accepted:false + 点名（显式不可用，绝不静默）。
{
  const fakeCtx = { get: () => undefined }
  const io = mod.makeWakeIo(fakeCtx)
  const r = await io.prompt('executor-x', 'hello', 'queue')
  assert(r.accepted === false && (r.error ?? '').includes('不可达'), 'wakeIo unavailable = explicit refused with reason')
  assert(await io.queueDepth('executor-x') === null, 'queue mirror unwired = explicit null')
}
// 项目 key 白名单（路由 400 面）。
{
  const { isValidProjectKey } = await import('../src/host/config.ts')
  assert(isValidProjectKey('sandbar') && !isValidProjectKey('../evil'), 'route key whitelist rejects traversal shapes')
}
done(n + 4)
