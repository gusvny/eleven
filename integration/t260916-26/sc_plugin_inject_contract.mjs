#!/usr/bin/env node
// sc_plugin_inject_contract.mjs —— t260916-26 场景①：客户端 entry 装机包的
// 「双版本可激活」注入契约（灰盒 L2，ro 池，纯读仓+vm 沙箱，零端口零 3099 零网络）。
//
// 用户故事（工单正文宿主实报）：stage 控制台（dsh 0.1.5）顶部「Failed to load plugins /
// web boot: 2 entries did not activate」——sandbar-knowledge 与 sandbar-providers 均
// pending（waiting for service: conversationViews）。宿主装载契约（dsh_seam）：entry 声明
// `inject` 服务清单，宿主逐项等注入，声明了已移除的服务=永久 pending=插件装不上。升级期
// 必然存在 0.1.1（生产）×0.1.5（stage）混版窗口，同一份装机包必须两版都能激活。
//
// 断言锚=插件宿主**公开注入契约**（装机包导出的 inject 清单），不锚 src 实现细节：
//   ① 可装载：装机包 lib/client.cjs 在 dsh 客户端模块契约（window.__ModuleLoader__.load
//      外衣+外部化 require 表）下真实加载，工厂可执行、返回非空 exports（装载失败=
//      用户可感的「Failed to load plugins」同族形态；加载器复制自 t260903-13 看守场景，
//      漂移责任=两侧头注对齐）；
//   ② 注入面收敛：inject 是字符串数组，且每一项都落在**双版本稳定服务集**
//      STABLE_SERVICES={slots,sessions,workspaces} 内——证据链：workbench 声明全部三项且
//      在 0.1.5 实测正常（工单对照），slots 在 0.1.5 在场还有宿主实报旁证（pending 只点名
//      conversationViews，slots 已注入成功）；
//   ③ 事故模式零残留（本票两个 entry）：装机包**字符串字面量形态**不含已移除服务名
//      （"conversationViews" 双引号形态出现=代码里重新声明/引用缺席服务键；注释散文
//      引用不算——装机包头注保留收窄史是既定纪律，开发者 L1 smoke 同款锚形+CJK 引号
//      纪律防注释散文误报；0.1.5 已移除 dsh-client-runtime 整包，活代码引用都是混版
//      窗口里的哑弹）；
//   ④ 全族排查（宿主纪律：实报即全族）：仓内四个客户端 entry（knowledge/providers/
//      workbench/admin-ui）装机包 inject 全部落②同一条收敛线——防下一家插件把脆弱服务名
//      写回 inject（对话页扩展面 0.1.5 起走 uiConversation.views 注册通道，不属于 inject
//      注入面）。
//
// 降级路径（工单验收③）在本场景的结构形态：inject 零声明脆弱服务 ⇒ 宿主无从等待 ⇒
// pending 结构性不可能 ⇒「两服务都不存在」时插件照常激活、UI 不报 Failed to load
// plugins。real-host 0.1.5 活体子用例不可本地机械复现（本机无 0.1.5 宿主、无 docker 台），
// 归宿主 stage 3199 走查（方案 S5）；本场景是它在闸内的机械等价锚。
//
// 边界与异常输入（自证红绿先行，先证尺子再量布）：inject 缺导出/非数组/非字符串元素/
// 空串服务名/集外服务名（=事故形态）五类坏样本必须全数判红；空数组 [] 是合法边界
// （零注入=最大降级仍可激活，admin-ui 现状即 []）。
//
// 维护契约（rot 说明，同 t260907-08 LEGACY_DARK_BG_BASE 机械升级模式）：STABLE_SERVICES
// 是「双版本稳定集」的当期证据值，锚在 workbench 0.1.5 激活这一单点活证上。未来宿主
// 再迁服务（如 slots 也被移除）时，本集合必须随新一轮双版本证据重推导并同步更新——
// 届时本场景红=提醒重取证，不是误报。
//
// 与既有场景 intent 分界：t260903-13-workbench-bundle-loads 锁 workbench 装机包的模块
// 加载契约（外衣/外部化/双产物同体），本场景对 workbench 只取 exports.inject 做全族
// 收敛线、不复锁其加载面；t260903-04-client-bundle-sync 锁 src↔lib 同步（特征词法），
// 本场景锁装机包对宿主的注入契约（语义面）；knowledge/providers 的开发者 smoke
// （inject-contract 契约 UT）无闸内执行点（SCENARIOS 无登记），本场景按 t260916-05
// 先例把它守的面升格闸内可见。
//
// 三态（t260904-12）：末行 SUMMARY pass/fail/env_fail/na；fail>0 或全 na=exit 1；
// env_fail>0=exit 2。本票实现落地前 ③子用例红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { readFileSync, existsSync } from 'node:fs'
import path from 'node:path'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const REPO = resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (typeof status === 'boolean') status = status ? 'pass' : 'fail' // 布尔调用形态：true=pass false=fail
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// 双版本稳定服务集（证据链见头注②；rot 维护契约见头注末节）
const STABLE_SERVICES = new Set(['slots', 'sessions', 'workspaces'])
// 事故形态服务名（0.1.5 已随 dsh-client-runtime 移除）
const REMOVED_SERVICE = 'conversationViews'
// 本票两个被测 entry（改动面）与其余家族 entry（全族排查面）
const TICKET_ENTRIES = [
  { id: 'sandbar-knowledge', dir: 'knowledge' },
  { id: 'sandbar-providers', dir: 'providers' },
]
const FAMILY_ENTRIES = [
  { id: 'sandbar-workbench', dir: 'workbench' },
  { id: 'sandbar-admin-ui', dir: 'ui' },
]

/* ---- 加载器（复制自 t260903-13/sc_workbench_bundle_loads.mjs，漂移责任两侧头注）---- */
const LOOSE = new Proxy(function () {}, {
  get(t, p) {
    if (p === Symbol.toPrimitive) return () => ''
    if (p === 'then') return undefined
    return LOOSE
  },
  apply() { return LOOSE },
  construct() { return LOOSE },
})
const EXTERNAL_OK = /^(@deepseek-ai\/|react(\/|$))/

function makeLoaderSandbox() {
  const loaded = {}
  const moduleLoader = { load(rec) { loaded.id = rec && rec.id; loaded.factory = rec && rec.factory } }
  const windowProxy = new Proxy({}, {
    get(t, p) {
      if (p === '__ModuleLoader__') return moduleLoader
      if (p === Symbol.toPrimitive) return () => ''
      return LOOSE
    },
    has() { return true },
  })
  const requireInTable = (spec) => {
    if (EXTERNAL_OK.test(spec)) return LOOSE
    throw new Error(`外部依赖泄漏：bare require 越过模块表：${spec}`)
  }
  const sandbox = {
    window: windowProxy, self: windowProxy, document: LOOSE, navigator: LOOSE,
    localStorage: LOOSE, performance: LOOSE, location: LOOSE, history: LOOSE,
    requestAnimationFrame: LOOSE, setTimeout: LOOSE, clearTimeout: LOOSE,
    setInterval: LOOSE, clearInterval: LOOSE, getComputedStyle: LOOSE,
    addEventListener: LOOSE, removeEventListener: LOOSE, HTMLElement: LOOSE,
    MutationObserver: LOOSE, ResizeObserver: LOOSE, IntersectionObserver: LOOSE,
    CustomEvent: LOOSE, Event: LOOSE, Image: LOOSE,
    console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
    process: { env: { NODE_ENV: 'production' } },
  }
  return { sandbox, loaded, requireInTable }
}

function tryLoadBundle(code) {
  const { sandbox, loaded, requireInTable } = makeLoaderSandbox()
  try {
    const script = new vm.Script(code, { filename: 'bundle-under-test.js' })
    script.runInNewContext(sandbox, { timeout: 30000 })
    if (typeof loaded.factory !== 'function') {
      return { fail: 'window.__ModuleLoader__.load 未被调用（外衣头缺失或形状不对）' }
    }
    const exports = loaded.factory(requireInTable)
    if (exports == null) return { fail: 'factory 返回空 exports' }
    return { id: loaded.id, exports }
  } catch (e) {
    return { fail: String((e && e.message) || e) }
  }
}

/* ---- 注入契约判定（被自证红绿校准的尺子）---- */
function judgeInject(inject) {
  const reasons = []
  if (inject === undefined) reasons.push('inject 导出缺席（entry 装载契约要求声明注入清单）')
  else if (!Array.isArray(inject)) reasons.push(`inject 非数组：${typeof inject}`)
  else {
    for (const s of inject) {
      if (typeof s !== 'string') reasons.push(`inject 含非字符串元素：${JSON.stringify(s)}`)
      else if (s === '') reasons.push('inject 含空串服务名')
      else if (!STABLE_SERVICES.has(s)) {
        reasons.push(`inject 声明了双版本稳定集之外的服务：${s}（0.1.5 缺席即永久 pending）`)
      }
    }
  }
  return { ok: reasons.length === 0, reasons }
}

/* ---- 1. 尺子自证（合成样本红绿）---- */
console.log('== 1. 尺子自证（合成样本：合法绿 / 坏样本红）==')
{
  const good = judgeInject(['slots'])
  record('自证：合法 inject=[slots] 判绿', good.ok === true, good.reasons.join('; '))
  const empty = judgeInject([])
  record('自证：边界空数组 inject=[] 判绿（零注入=最大降级仍可激活）', empty.ok === true, empty.reasons.join('; '))
  const bads = [
    ['缺导出', judgeInject(undefined)],
    ['非数组', judgeInject('slots')],
    ['非字符串元素', judgeInject(['slots', 42])],
    ['空串服务名', judgeInject([''])],
    ['集外服务名（事故形态）', judgeInject([REMOVED_SERVICE])],
  ]
  for (const [label, j] of bads) {
    record(`自证：坏样本「${label}」判红`, j.ok === false && j.reasons.length > 0,
      j.ok === true ? '坏样本被判绿=尺子失真' : j.reasons[0])
  }
}

/* ---- 2. 本票两 entry：装机包可装载 + 注入面收敛 + 事故模式零残留 ---- */
console.log('== 2. 本票 entry（knowledge/providers）装机包注入契约 ==')
for (const { id, dir } of TICKET_ENTRIES) {
  const cjsPath = join(REPO, 'server', 'plugins', dir, 'lib', 'client.cjs')
  const esmPath = join(REPO, 'server', 'plugins', dir, 'lib', 'client.js')
  if (!existsSync(cjsPath) || !existsSync(esmPath)) {
    record(`${id}: 装机双产物在场`, false, `缺 ${!existsSync(cjsPath) ? cjsPath : esmPath}`)
    continue
  }
  const loaded = tryLoadBundle(readFileSync(cjsPath, 'utf8'))
  record(`${id}: 装机包在 dsh 模块契约下可加载（工厂可执行+exports 非空）`,
    !loaded.fail, loaded.fail || `id=${loaded.id}`)
  if (loaded.fail) continue
  const j = judgeInject(loaded.exports.inject)
  record(`${id}: inject 清单全部落在双版本稳定集 ${[...STABLE_SERVICES].join('/')} 内`,
    j.ok, j.ok ? `inject=${JSON.stringify(loaded.exports.inject)}` : j.reasons.join('; '))
  const esmText = readFileSync(esmPath, 'utf8')
  const cjsText = readFileSync(cjsPath, 'utf8')
  const literal = `"${REMOVED_SERVICE}"` // 代码形态=服务键字符串字面量；注释散文/反引号/单引号形态不算（头注收窄史是既定纪律）
  const leaked = [cjsText, esmText]
    .map((t, i) => (t.includes(literal) ? (i === 0 ? 'client.cjs' : 'client.js') : null))
    .filter(Boolean)
  record(`${id}: 事故模式零残留（双产物零 ${literal} 字面量形态）`,
    leaked.length === 0, leaked.length ? `残留于 ${leaked.join(',')}` : '双产物零字面量残留')
}

/* ---- 3. 全族排查：其余 entry 同一条收敛线 ---- */
console.log('== 3. 全族排查（workbench/admin-ui 装机包注入面同线收敛）==')
for (const { id, dir } of FAMILY_ENTRIES) {
  const cjsPath = join(REPO, 'server', 'plugins', dir, 'lib', 'client.cjs')
  if (!existsSync(cjsPath)) {
    record(`${id}: 装机包在场（全族收敛前提）`, false, `缺 ${cjsPath}`)
    continue
  }
  const loaded = tryLoadBundle(readFileSync(cjsPath, 'utf8'))
  if (loaded.fail) {
    record(`${id}: 装机包可加载（取 inject 的前提）`, false, loaded.fail)
    continue
  }
  const j = judgeInject(loaded.exports.inject)
  record(`${id}: inject 清单落在双版本稳定集内（全族零脆弱注入）`,
    j.ok, j.ok ? `inject=${JSON.stringify(loaded.exports.inject)}` : j.reasons.join('; '))
}

summarize()
