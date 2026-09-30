// sc_grants_upstream_400_text.mjs — t260929-22 grants 上游生产者 + project 400 文案点名判据（灰盒 L2，节点半真实路由，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；工单 scope②③⑤）：
//   B1 生产者由构造保证：生产形态 console（未设 SANDBAR_WORKBENCH_BASE）下，grants
//      的降级理由**永远不得是「环境变量没接」类**——基址必须可由构造得出（同源请求
//      origin 即可）；真正不可达上游时降级理由=可达性类（HTTP 状态/网络错误）。
//      pre-fix 实况=reason 含 "SANDBAR_WORKBENCH_BASE unset"（本条红=anti-proof）。
//   B2 强形态（同源桩在场）：面板与 workbench 同一 console 服务——harness 同源挂
//      /sandbar-workbench/api/wf/workflows 夹具后，grants 必须 ok:true（degraded:false）
//      且出推导行，而非降级对象。**测试缝要求**（harness.mjs 向后兼容扩展）：
//      startHarness 新增可选项 `workbenchStub: true` 时在同一服务器上以
//      `http://<host>/sandbar-workbench/api/wf/workflows` 返回夹具模板拓扑
//      `{ ok:true, result:[{ id:'dev-lane', stages:[{id:'review_plan'},{id:'implement'}] }] }`
//      （同源=生产形态的结构前提；缝缺席=本条 FAIL 点名，TDD 红，arbitrate 期必须绿）。
//      缝实现=developer 侧 t260929-22 改动：startHarness 选项 `sameOriginWorkbench:true`
//      （清空 env 基址 + 同源伺服 workflows 桩，可注入 payload）。
//   C1–C4 畸形/缺失 project 的 400 文案必须**点名失败判据与要求**：提及参数名
//      project、写明要求（形状/白名单语义）、写明收到什么（缺失时不得以裸冒号收尾）。
//      逐面：GET settings（无参）、GET settings（非法键）、GET grants（空键）、
//      POST requests/answer（空键）。机器可判锚（不锚具体措辞，锚契约三要素）：
//      提及 project ∧ 非空超阈值 ∧ 不以冒号收尾 ∧ 含要求语义（形状/必须/must）。
//   C5 兄弟分支分级锚：未知 settings 操作 422 文案须含收到的 op 值与合法集合
//      （save|revoke|sleep）——「点名判据」家族的可接受先例，随票钉住防退化。
//
// intent 分工：R5（t260929-03-executor-panel-api）已锁「非法键=400 状态」契约刚性——
// 本场景只锁**文案内容**层；G1（同上）已锁 env base 显式指向桩时 ok:true——B2 锁的是
// **同源/无环境变量**生产形态，不同面。面板页内归 t260929-03-executor-panel-page。
//
// 三态纪律：node/harness 缺席=FAIL 点名（TDD 红属预期）；全部离线，无 ENV 面。
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t260929-03/lib_panel_harness.mjs'

const C = makeCase()

if (!existsSync(process.execPath)) { C.envFail('node-runtime', 'node 不在 PATH'); process.exit(2) }

let mod
try {
  mod = await loadPanelHarness()
} catch (e) {
  C.case('harness-load', false, String(e.message || e))
  C.exit()
}
if (!mod || typeof mod.startHarness !== 'function') {
  C.case('harness-present', false,
    '测试缝缺席 server/plugins/executor-panel/harness.mjs（协议见 t260929-03/lib_panel_harness.mjs 头注；TDD 期红属预期）')
  C.exit()
}

const GOOD = 'fixture-proj'
const BAD = 'BAD/KEY'

/** C 族契约谓词：文案点名判据与要求（不锚措辞）。 */
function namesCheck(msg, { received = '' } = {}) {
  if (typeof msg !== 'string' || !msg) return 'message empty'
  if (!/project/i.test(msg)) return 'does not name the project parameter'
  if (msg.trim().length < 25) return `too short to name check+requirement: ${JSON.stringify(msg)}`
  if (/[：:]\s*$/.test(msg)) return 'ends with a bare colon — nothing after it (content-free tail)'
  if (received && !msg.includes(received)) return `does not state what was received (${JSON.stringify(received)})`
  if (!/(\^|\[\s*a-z|lowercase|小写|[a-z0-9][a-z0-9-]|must|必须|形如|要求|match)/i.test(msg)) {
    return 'does not state the requirement (shape/whitelist semantics)'
  }
  return null
}

const iso = makeIsoDir('t260929-22-')

async function boot(opts = {}) {
  return mod.startHarness({ panelDir: iso.dir, watchdogDir: iso.dir, ...opts })
}

async function main() {
  // ---- B1：生产形态（无基址、无同源桩）→ 降级理由只能是可达性类
  let h1
  try {
    h1 = await boot()
  } catch (e) {
    C.case('boot-production-shaped', false, String(e.message || e).slice(0, 160))
    C.exit()
  }
  try {
    const r = await fetch(h1.base + '/sandbar-executor-panel/api/grants?project=' + GOOD)
    const j = await r.json()
    if (r.status !== 200) { C.case('B1 grants reachable status', false, `HTTP ${r.status}`) } else {
      C.case('B1 grants status 200', true)
    }
    const reason = String(j.reason ?? j.grants?.reason ?? '')
    if (j.degraded !== true || j.grants?.ok !== false) {
      C.case('B1 production-shaped grants', true, 'not degraded — upstream resolved by construction')
    } else if (/unset|not wired|SANDBAR_WORKBENCH_BASE/i.test(reason)) {
      C.case('B1 no missing-config degradation', false,
        `grants degraded with a missing-config reason in a production-shaped console (no producer by construction): ${JSON.stringify(reason)}`)
    } else {
      C.case('B1 no missing-config degradation', true,
        `degraded for a reachability-class reason (acceptable): ${JSON.stringify(reason.slice(0, 120))}`)
    }
  } finally {
    await h1.close()
  }

  // ---- B2 强形态：同源桩在场（developer 缝 sameOriginWorkbench）+ 夹具项目已声明
  //      守望者（声明=宿主动作，面板绝不自宣——out-of-scope 守卫）→ 绝不降级
  const { mkdirSync, writeFileSync } = await import('node:fs')
  mkdirSync(join(iso.dir, GOOD), { recursive: true })
  writeFileSync(join(iso.dir, GOOD, 'watchdog.json'), JSON.stringify({
    enabled: true, executor_session: 'sess-a', stall_minutes: 3, reconcile_seconds: 30,
    alerts: { enabled: true, sound: true, desktop: false, night: { start: '23:00', end: '07:00', policy: 'normal' }, redline: [], keep_days: 14 },
  }))
  const h2 = await boot({ sameOriginWorkbench: true })
  try {
    let stubUp = false
    try {
      const sr = await fetch(h2.base + '/sandbar-workbench/api/wf/workflows')
      stubUp = sr.ok && /ok|workflows/.test(await sr.text())
    } catch { /* stub not mounted */ }
    if (!stubUp) {
      C.case('B2 same-origin workbench stub seam', false,
        'harness ignored sameOriginWorkbench:true — same-origin /sandbar-workbench/api/wf/workflows not served (seam 扩展缺席；TDD 红，arbitrate 期必须绿)')
    } else {
      const r2 = await fetch(h2.base + '/sandbar-executor-panel/api/grants?project=' + GOOD)
      const j2 = await r2.json()
      const reason = String(j2.reason ?? j2.grants?.reason ?? '')
      const ok = r2.status === 200 && j2.degraded === false && j2.grants?.ok === true && Array.isArray(j2.grants?.rows)
      C.case('B2 grants resolve from same-origin upstream', ok,
        ok ? 'derived grant list served, no degradation notice'
          : `not a derived list (degraded=${j2.degraded}, ok=${j2.grants?.ok}, rows=${Array.isArray(j2.grants?.rows)}): ${JSON.stringify(reason.slice(0, 160))}`)
    }
  } finally {
    await h2.close()
  }

  // ---- C1–C5：400 文案点名判据
  const h3 = await boot()
  try {
    const get = async (p) => { const r = await fetch(h3.base + p); return { r, j: await r.json().catch(() => ({})) } }
    const post = async (p, body) => {
      const r = await fetch(h3.base + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
      return { r, j: await r.json().catch(() => ({})) }
    }
    const msgOf = (x) => String(x.j.error ?? x.j.reason ?? '')

    { const x = await get('/sandbar-executor-panel/api/settings')
      const why = x.r.status === 400 ? namesCheck(msgOf(x)) : `HTTP ${x.r.status} (expected 400)`
      C.case('C1 bare GET settings 400 text names check', why === null, why ?? 'names parameter, requirement and absence') }
    { const x = await get('/sandbar-executor-panel/api/settings?project=' + encodeURIComponent(BAD))
      const why = x.r.status === 400 ? namesCheck(msgOf(x), { received: BAD }) : `HTTP ${x.r.status} (expected 400)`
      C.case('C2 malformed project 400 text names check', why === null, why ?? 'names parameter, requirement and received value') }
    { const x = await get('/sandbar-executor-panel/api/grants?project=')
      const why = x.r.status === 400 ? namesCheck(msgOf(x)) : `HTTP ${x.r.status} (expected 400)`
      C.case('C3 empty grants project 400 text names check', why === null, why ?? 'names parameter, requirement and absence') }
    { const x = await post('/sandbar-executor-panel/api/requests/answer', {})
      const why = x.r.status === 400 ? namesCheck(msgOf(x)) : `HTTP ${x.r.status} (expected 400)`
      C.case('C4 answer with empty project 400 text names check', why === null, why ?? 'names parameter, requirement and absence') }
    { const x = await post('/sandbar-executor-panel/api/settings?project=' + GOOD, { op: 'weird-op' })
      const m = msgOf(x)
      const ok = x.r.status === 422 && m.includes('weird-op') && /save/.test(m) && /revoke/.test(m) && /sleep/.test(m)
      C.case('C5 unknown-op 422 names op + allowed set', ok,
        ok ? 'sibling branch acceptable (names what failed and the allowed set)' : `HTTP ${x.r.status}, msg=${JSON.stringify(m.slice(0, 120))}`) }
  } finally {
    await h3.close()
  }
  iso.clean()
  C.exit()
}

await main()
