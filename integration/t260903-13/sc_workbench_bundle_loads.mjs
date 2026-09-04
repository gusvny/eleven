#!/usr/bin/env node
/**
 * sc_workbench_bundle_loads.mjs —— t260903-13：重建产物在 dsh 客户端模块契约下可加载。
 *
 * 用户故事：dsh 控制台经 window.__ModuleLoader__.load({id, factory}) 惰性加载
 * suyou-workbench/client（产物形态合同=tsdown.config.ts 头注 closure-factory 外衣：
 * react 与 @deepseek-ai/* 外部化走平台模块表）。tsdown 重建若破坏外衣形状、
 * 泄漏非外部化 bare require、或 client.cjs/client.js 半新不同体，用户可感形态
 * =台面模块加载失败。本场景在 vm 沙箱按契约真实加载产物，断言：
 *   1) lib/client.cjs 与 lib/client.js 同体（exports ./client 指向 client.js）；
 *   2) 外衣头尾字样在（id=suyou-workbench 的 load 头 + return module.exports 尾）；
 *   3) 工厂可执行、返回非空 exports、bare require 全部落在声明外部化面内；
 *   4) 加载器自证红绿：合法合成样本绿 / 外部依赖泄漏红 / 外衣破损红 /
 *      load 未被调用红——自证不过则真产物的绿不可信。
 *
 * 灰盒锚点：锚模块加载契约与外部化清单（config 头注声明的产物形态合同），
 * 不锚 bundle 内部实现。纯读仓+合成样本，零端口、零 3099、零网络。
 * Exit contract（三态，定稿 §7.3 闸内无 SKIP）：末行 SUMMARY pass=N fail=K
 * env_fail=E na=W；fail>0 或全 na→exit 1，env_fail>0→exit 2。
 */
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* 宽容桩：任何取值/调用/构造都返回自身——只垫浏览器全局的 define 期，
 * 不参与判定；判定只落在「工厂可执行 + exports 非空 + require 不越表」。 */
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
    window: windowProxy,
    self: windowProxy,
    document: LOOSE,
    navigator: LOOSE,
    localStorage: LOOSE,
    performance: LOOSE,
    location: LOOSE,
    history: LOOSE,
    requestAnimationFrame: LOOSE,
    setTimeout: LOOSE,
    clearTimeout: LOOSE,
    setInterval: LOOSE,
    clearInterval: LOOSE,
    getComputedStyle: LOOSE,
    addEventListener: LOOSE,
    removeEventListener: LOOSE,
    HTMLElement: LOOSE,
    MutationObserver: LOOSE,
    ResizeObserver: LOOSE,
    IntersectionObserver: LOOSE,
    CustomEvent: LOOSE,
    Event: LOOSE,
    Image: LOOSE,
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

/* ------------------------------------------------ 1. 加载器自证红绿（合成样本） */
section('1. 加载器自证（合成样本红绿，先证尺子再量布）')
const GOOD = `window.__ModuleLoader__.load({ id: "sample", factory: (require) => { const r = require("react"); void r; return { mount() {} }; } });`
const LEAK = `window.__ModuleLoader__.load({ id: "sample", factory: (require) => { require("lodash"); return {}; } });`
const BROKEN = `window.__ModuleLoader__.load({ id: "sample", factory: (require) => { return module.exports; } });`
const NOTLOADED = `void 0`

const g = tryLoadBundle(GOOD)
ok(!g.fail && g.id === 'sample' && g.exports, '合成合法样本：绿（工厂执行+exports 非空+外部化 require 放行）')
const l = tryLoadBundle(LEAK)
ok(!!l.fail && /泄漏/.test(l.fail), '合成泄漏样本（require lodash）：红')
const b = tryLoadBundle(BROKEN)
ok(!!b.fail, '合成外衣破损样本（缺 module 声明）：红')
const n = tryLoadBundle(NOTLOADED)
ok(!!n.fail && /未被调用/.test(n.fail), '合成未挂载样本（无 load 调用）：红')

/* ------------------------------------------------ 2. 真产物契约加载 */
section('2. 真产物：同体 + 外衣 + 契约加载')
const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const cjsPath = join(root, 'server/dsh/workbench/lib/client.cjs')
const jsPath = join(root, 'server/dsh/workbench/lib/client.js')
ok(existsSync(cjsPath), 'lib/client.cjs 在场（缺=未构建，红）')
ok(existsSync(jsPath), 'lib/client.js 在场（exports ./client 的指向）')
if (existsSync(cjsPath) && existsSync(jsPath)) {
  const cjs = readFileSync(cjsPath)
  const js = readFileSync(jsPath)
  ok(cjs.equals(js), 'client.cjs 与 client.js 同体（防 onSuccess 复制缺失的半新产物）')
  const code = js.toString('utf8')
  ok(code.startsWith('window.__ModuleLoader__.load({ id: "suyou-workbench", factory:'), '外衣头（id=suyou-workbench 的 load）')
  ok(code.trimEnd().endsWith('return module.exports; } });'), '外衣尾（return module.exports）')
  const res = tryLoadBundle(code)
  ok(!res.fail, `vm 沙箱按契约加载成功${res.fail ? '：' + res.fail : ''}`)
  if (!res.fail) {
    ok(res.id === 'suyou-workbench', 'load id=suyou-workbench')
    ok(res.exports != null, 'factory 返回非空 exports')
  }
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
process.exit(failed > 0 ? 1 : 0)
