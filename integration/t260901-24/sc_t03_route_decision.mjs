/**
 * t03-route-decision —— t260901-24「capture-lane 状态注入」注入决策面基线。
 *
 * 直跑：node integration/t260901-24/t03-route-decision.mjs（cwd=泳道根）。
 *
 * 黑盒契约（第 2 稿方案 R3/R4 + review C3）：capture.mjs 导出纯函数
 * routeDecision(method, url, fixtures)，只读红线在浏览器注入层的落点：
 *   - GET 命中 wf 读端点（tickets list/show/diff、workflows）→ fulfill，
 *     contentType 恒 'application/json'（缺失=客户端 res.json() 静默空态）；
 *   - 带 ?project= 查询串必须只比 path 照样命中（整串匹配=静默放行=空列表假象）；
 *   - POST 写端点（accept/advance/dispatch-next/rework/update/review）一律放行——
 *     写操作绝不被假数据吞掉；
 *   - 其余 GET 端点（projects/temporal-health/book）放行走真响应。
 *
 * 纯函数黑盒，不起浏览器。
 */

import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const CAPTURE = join(REPO, 'server', 'ui-check', 'capture.mjs')
const FIXTURES = join(REPO, 'server', 'ui-check', 'fixtures')

let passed = 0, failed = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('被测模块解析：capture.mjs 导出 routeDecision 与 loadFixtures')
let routeDecision = null, loadFixtures = null
try {
  const mod = await import(pathToFileURL(CAPTURE).href + '?t=' + Date.now())
  routeDecision = mod.routeDecision
  loadFixtures = mod.loadFixtures
} catch { /* 未实现则下方 loud 失败 */ }
if (typeof routeDecision !== 'function' || typeof loadFixtures !== 'function') {
  console.log('  FAIL capture.mjs 未导出 routeDecision/loadFixtures（t260901-24 implement 段应导出）')
  console.log(`\nSUMMARY pass=0 fail=1 env_fail=0 na=0`)
  process.exit(1)
}
ok(true, 'routeDecision / loadFixtures 已导出')

section('fixture 数据准备（随包真 fixture；缺则本测试无法进行）')
let fixtures = null
try { fixtures = await loadFixtures(FIXTURES) } catch (e) {
  console.log(`  FAIL 随包 fixture 加载失败：${String(e?.message || e).split('\n')[0]}`)
  console.log(`\nSUMMARY pass=1 fail=1 env_fail=0 na=0`)
  process.exit(1)
}
ok(fixtures != null, 'loadFixtures(随包目录) 通过')

const BASE = 'http://127.0.0.1:41001'
const GET_HIT = [
  ['/sandbar-workbench/api/wf/tickets', 'tickets list'],
  ['/sandbar-workbench/api/wf/tickets?project=suyou', 'tickets list 带查询串（C3）'],
  ['/sandbar-workbench/api/wf/tickets/T-FIX-A', 'ticket show'],
  ['/sandbar-workbench/api/wf/tickets/T-FIX-A/diff', 'ticket diff'],
  ['/sandbar-workbench/api/wf/workflows', 'workflows'],
  ['/sandbar-workbench/api/wf/workflows?project=suyou', 'workflows 带查询串'],
]
section('GET 命中 → fulfill 且 content-type 恒 application/json（R4/C3）')
for (const [p, label] of GET_HIT) {
  const d = callDecide('GET', BASE + p)
  ok(!!d?.fulfill, `GET ${label} → fulfill`)
  if (d?.fulfill) {
    ok(d.fulfill.contentType === 'application/json',
      `GET ${label} contentType=application/json（实际：${d.fulfill.contentType}）`)
    ok(d.fulfill.body != null, `GET ${label} 返回体非空`)
  }
}

section('POST 写端点 → 一律放行（只读红线，写操作绝不被假数据吞）')
const POSTS = ['accept', 'advance', 'dispatch-next', 'rework', 'update', 'review']
for (const op of POSTS) {
  const d = callDecide('POST', `${BASE}/sandbar-workbench/api/wf/tickets/T-FIX-A/${op}`)
  ok(!!d?.passthrough, `POST tickets/${op} → passthrough`)
}

section('其余 GET 端点 → 放行走真响应')
for (const p of ['/sandbar-workbench/api/wf/projects', '/sandbar-workbench/api/wf/temporal-health',
  '/sandbar-workbench/api/wf/book?path=x', '/sandbar-workbench/api/wf/tickets/T-FIX-A/agent-logs',
  '/sandbar-workbench/api/wf/no-such-endpoint']) {
  const d = callDecide('GET', BASE + p)
  ok(!!d?.passthrough, `GET ${p.replace('/sandbar-workbench/api/wf', '…wf')} → passthrough`)
}

section('方法变体边界')
ok(!!callDecide('HEAD', BASE + '/sandbar-workbench/api/wf/tickets')?.passthrough,
  'HEAD /tickets → passthrough（只放 GET）')
ok(!!callDecide('PUT', BASE + '/sandbar-workbench/api/wf/tickets/T-FIX-A')?.passthrough,
  'PUT /tickets/<id> → passthrough')
// 路径相近但非 wf 端点不误吞
ok(!!callDecide('GET', BASE + '/sandbar-workbench/other/tickets')?.passthrough,
  '非 wf 前缀路径 → passthrough')

function callDecide(method, url) {
  try {
    const d = routeDecision(method, url, fixtures)
    // 容 async 返回：Promise 归一由调用侧 await 不可行（本函数同步）——
    // routeDecision 契约为纯同步；若实现返回 Promise，此处判 Promise 也算 fulfill/passthrough 缺失，
    // 由上放断言失败指路。防御：把 Promise 计为无效。
    if (d && typeof d.then === 'function') return null
    return d
  } catch { return null }
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
if (failed > 0) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); process.exit(1) }
