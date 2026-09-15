/**
 * project-tag-index-visibility.mjs —— t260915-10 gen7：兜底自取/nudge 强取的可见性门 UT。
 *
 * 背景（仲裁第 9 轮判别探针终裁）：multi-tab T3「hidden tab stops polling」间歇红，
 * 探针实证隐藏模拟补丁在场而泄漏持续=可见性门放行=产品面缺陷。t260901-15 已把
 * 「定时轮询统一收口可见性门」（visibility-poll.ts），但后加取数路径（chat 芯片装饰
 * 器族，t260903-07/t260911-06）漏收口：startProjectIndexFallback 的 setTimeout 自排
 * 程链与 nudge() 强取全程无门——隐藏页签照常拉 /wf/projects + /wf/tickets（KI-003
 * 族：后台页签放大查询通道压力）。本 UT 锁修后的门语义（对齐 startVisibleInterval
 * 契约「页签不可见即停表、零请求；重新可见立即补刷一次并恢复节拍」）：
 *   V1 隐藏时 schedule 周期到点不取数（周期照排、取数被门住）；
 *   V2 回可见立即补跑一次（零请求窗口结束的恢复语义）；
 *   V3 隐藏时 nudge 强取被门住，且不消耗最小间隔额度（回可见后真需求仍可立即强取）；
 *   V4 stop 全终态回收：visibilitychange 监听随 stop 移除（泄漏监听=复活入口）；
 *   V5 document 未定义环境（node/smoke 裸跑）行为不变：视为可见、取数照常（不静默
 *      改语义——与 visibility-poll.ts 故障口径一致；既有 chat-project-tag-refresh
 *      UT 即在此环境跑，本条以挂桩前后对照自证）。
 *
 * 桩口径：globalThis.document 最小桩（visibilityState 可翻转 + addEventListener/
 * removeEventListener 收集 handler 供手动派发）；测毕恢复原值。Run:
 * node tests/project-tag-index-visibility.mjs（exit 0 = 过）。
 */
import {
  _resetProjectTagIndex, startProjectIndexFallback,
} from '../src/client/project-tag-index.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function tick(ms) { return new Promise(r => setTimeout(r, ms)) }

/* ---- document 桩：可见性可翻转 + 事件 handler 可手动派发 ---- */
const originalDocument = globalThis.document
function makeDocStub(initialVisibility) {
  const listeners = {}
  const stub = {
    visibilityState: initialVisibility,
    addEventListener(kind, fn) { (listeners[kind] ??= []).push(fn) },
    removeEventListener(kind, fn) {
      const arr = listeners[kind] ?? []
      const i = arr.indexOf(fn)
      if (i >= 0) arr.splice(i, 1)
    },
    /** 测试辅助：翻转可见性并派发事件（模拟浏览器行为）。 */
    flip(state) {
      stub.visibilityState = state
      for (const fn of listeners.visibilitychange ?? []) fn()
    },
    listenerCount(kind) { return (listeners[kind] ?? []).length },
  }
  return stub
}
function installDoc(stub) { globalThis.document = stub }
function restoreDoc() {
  if (originalDocument === undefined) delete globalThis.document
  else globalThis.document = originalDocument
}

/* ---- 计数 fetch 桩：projects 恒成功（有数据），tickets 也成功；记次数与 URL ---- */
function countingFetch() {
  const calls = []
  const fn = (url) => {
    calls.push(String(url))
    const body = String(url).includes('/wf/tickets')
      ? { ok: true, result: { tickets: [{ id: 't260915-01' }] } }
      : { ok: true, result: { projects: [{ key: 'p1', dirs: ['/tmp/p1'] }] } }
    return Promise.resolve({ json: () => Promise.resolve(body) })
  }
  fn.calls = calls
  return fn
}

/* ---- 每节独占：重置单态（externallyPublished/hasData 会互相污染） ---- */
function freshFallback(fetchImpl, extra = {}) {
  _resetProjectTagIndex()
  return startProjectIndexFallback({
    fetchImpl,
    initialDelayMs: 0,
    retryIntervalMs: 40,
    maxAttempts: 1000,
    nudgeMinIntervalMs: 60_000,
    ...extra,
  })
}

section('V1 隐藏时 schedule 周期到点不取数（门住，零请求）')
{
  const doc = makeDocStub('hidden')
  installDoc(doc)
  const f = countingFetch()
  const fb = freshFallback(f)
  await tick(220) // ≥5 个 40ms 周期
  const hiddenCalls = f.calls.length
  fb.stop()
  restoreDoc()
  ok(hiddenCalls === 0, `隐藏全窗零请求（got ${hiddenCalls}）`)
}

section('V2 回可见立即补跑一次（恢复语义）')
{
  const doc = makeDocStub('hidden')
  installDoc(doc)
  const f = countingFetch()
  const fb = freshFallback(f)
  await tick(120)
  const beforeVisible = f.calls.length
  doc.flip('visible') // 隐藏→可见：监听应补跑一轮（projects+tickets）
  await tick(60)
  const afterVisible = f.calls.length
  fb.stop()
  restoreDoc()
  ok(beforeVisible === 0, `隐藏期间零请求（got ${beforeVisible}）`)
  ok(afterVisible >= 2, `回可见补跑发生（projects+tickets，got +${afterVisible - beforeVisible}）`)
}

section('V3 隐藏时 nudge 被门住且不消耗间隔额度，回可见后立即可强取')
{
  const doc = makeDocStub('hidden')
  installDoc(doc)
  const f = countingFetch()
  const fb = freshFallback(f, { retryIntervalMs: 10_000 }) // 排除 schedule 链干扰
  await tick(30)
  const base = f.calls.length
  fb.nudge() // 隐藏：应被门住
  await tick(30)
  const afterHiddenNudge = f.calls.length
  doc.flip('visible') // 回可见：监听补跑也会发生，为隔离只看 nudge 前后差
  await tick(60)
  const afterRestore = f.calls.length
  fb.nudge() // 可见：最小间隔额度未被隐藏期的 nudge 消耗 → 应立即强取
  await tick(40)
  const afterVisibleNudge = f.calls.length
  fb.stop()
  restoreDoc()
  ok(afterHiddenNudge === base, `隐藏时 nudge 零请求（got +${afterHiddenNudge - base}）`)
  ok(afterVisibleNudge > afterRestore, `回可见后 nudge 立即强取（got +${afterVisibleNudge - afterRestore}）`)
}

section('V4 stop 移除 visibilitychange 监听（全终态回收）')
{
  const doc = makeDocStub('visible')
  installDoc(doc)
  const f = countingFetch()
  const fb = freshFallback(f, { retryIntervalMs: 10_000 })
  await tick(30)
  const mounted = doc.listenerCount('visibilitychange')
  fb.stop()
  const afterStop = doc.listenerCount('visibilitychange')
  restoreDoc()
  ok(mounted === 1, `运行期恰好挂 1 个 visibilitychange 监听（got ${mounted}）`)
  ok(afterStop === 0, `stop 后监听清零（got ${afterStop}）`)
}

section('V5 document 未定义环境行为不变（node/smoke 裸跑=视为可见）')
{
  // 无桩环境（restoreDoc 后 originalDocument===undefined 时即裸跑）：取数照常。
  restoreDoc()
  const docAbsent = typeof globalThis.document === 'undefined'
  const f = countingFetch()
  const fb = freshFallback(f)
  fb.nudge()
  await tick(40)
  const calls = f.calls.length
  fb.stop()
  ok(docAbsent, '确认处于无 document 环境（桩已卸载）')
  ok(calls >= 2, `无 document 环境取数照常（projects+tickets，got ${calls}）`)
}

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
