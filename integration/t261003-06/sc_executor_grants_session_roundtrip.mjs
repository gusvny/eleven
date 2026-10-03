// sc_executor_grants_session_roundtrip.mjs — t261003-06 grants 读写缺陷回归（灰盒 L2，
// harness 缝驱动真实路由面，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；设计 note §5 三缺陷 + review_plan C1/C2/C3 附条件裁定）：
//   A1 宿主在 Grants 页点名执行器会话并保存 → 读出面报告该会话在场（点名不丢）。
//   A2 【缺陷①回归】此后任何一次保存（改一个权限再存）→ 点名仍在（改动前实况：
//      saveGrantsDecl 落盘文档从不带 executor_sessions，第二次保存静默抹掉点名，
//      回执却报成功；review_plan C1 纠偏：缺陷只在 Save 脸，settings op=revoke 是
//      「停守望者」的另一张脸，与此无关）。
//   A3 总开关关（POST /api/grants {op:'master', enabled:false}，C2 裁定的 grants-only
//      新脸）→ 授予清零、点名保留，读出面呈 named-zero-grants 态。
//   A4 【watchdog 照常运行红线】总开关关之后 Settings 读面的守望者 enabled 仍为
//      true——授权收回绝不连带停守望者（设计 note §3「收回授权只影响授权」）。
//   B1/B2 【缺陷②回归】授予 6 个操作 → granted_count 恰 6、读出句「6 of 6」口径
//      （改动前按 op×模板派生行数计，六操作会被报成 18）；部分授予 → 「2 of 6」。
//      workbench 模板拓扑桩在场（2 模板派生行）证明计数不随行数翻倍。
//   C1–C3 【缺陷③】读出面三态可区分：没点名（no-session）/ 点名了但零授予
//      （named-zero-grants）/ 已授予（granted）——三态 state 值互异，不靠人读文案猜。
//   C4 畸形授予输入照旧拒收：非布尔授予值 / 未知操作键 → saved:false + 人话原因。
//
// 三态：harness.mjs 缝缺席/新契约面未落地=FAIL exit 1 且点名（TDD 期红属预期）。
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from './lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const OPS = ['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup']

async function jfetch(base, url, opts) {
  const r = await fetch(base + url, opts)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startHarness（缝契约见 lib_panel_seam.mjs 头注；TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir()
  const H = await harness.startHarness({ panelDir: join(iso.dir, 'panel'), watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  try {
    const api = '/sandbar-executor-panel/api/grants?project=' + PROJ
    // 前置（用户旅程）：宿主先在 Settings 页声明守望者——授权推导面要求项目已声明
    // （未声明=授权面显式「未接入」，不是空表）。
    await jfetch(H.base, '/sandbar-executor-panel/api/settings?project=' + PROJ,
      { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ op: 'save', config: { enabled: true } }) })
    const save = (body) => jfetch(H.base, api, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ by: 'host-sc', ...body }) })
    const get = () => jfetch(H.base, api)
    const stateOf = (g) => (g.body && g.body.session_readout && g.body.session_readout.state) || (g.body && g.body.readout && g.body.readout.state) || null
    const sessionsOf = (g) => (g.body && g.body.session_readout && g.body.session_readout.sessions) || (g.body && g.body.executor_sessions) || []

    // A1 点名保存 → 读出可见
    const s1 = await save({ executor_sessions: ['exec-1'], grants: { sign: true, rerun: true } })
    const g1 = await get()
    C.case('A1-save-with-session-readable-back', s1.status < 300 && sessionsOf(g1).includes('exec-1'),
      `save=${s1.status} sessions=${JSON.stringify(sessionsOf(g1))}`)

    // A2 【缺陷①回归】第二次保存（改权限）点名仍在
    const s2 = await save({ executor_sessions: ['exec-1'], grants: { sign: true, rerun: false } })
    const g2 = await get()
    C.case('A2-resave-keeps-session-naming', s2.status < 300 && sessionsOf(g2).includes('exec-1'),
      `resave=${s2.status} sessions=${JSON.stringify(sessionsOf(g2))}`)

    // A3 总开关关：授予清零、点名保留、三态呈 named-zero-grants
    const off = await save({ op: 'master', enabled: false })
    const g3 = await get()
    C.case('A3-power-off-clears-grants-keeps-session',
      off.status < 300 && stateOf(g3) === 'named-zero-grants' && sessionsOf(g3).includes('exec-1'),
      `master-off=${off.status} state=${stateOf(g3)} sessions=${JSON.stringify(sessionsOf(g3))}`)

    // A4 watchdog 照常运行（授权收回绝不停守望者）
    const st = await jfetch(H.base, '/sandbar-executor-panel/api/settings?project=' + PROJ)
    const wd = st.body && (st.body.config || st.body.watchdog || st.body)
    const enabled = wd && wd.enabled !== undefined ? wd.enabled : null
    C.case('A4-power-off-watchdog-still-enabled', st.status < 300 && enabled === true,
      `settings=${st.status} enabled=${JSON.stringify(enabled)}`)

    // B1 【缺陷②回归】6 操作全授予=6 of 6（不随 workbench 桩模板的派生行数变 18/12）
    const allGrants = Object.fromEntries(OPS.map(o => [o, true]))
    await save({ executor_sessions: ['exec-1'], grants: allGrants })
    const gAll = await get()
    const face = (gAll.body && (gAll.body.grants || gAll.body)) || {}
    const cnt = face.granted_count
    const note = JSON.stringify(gAll.body || {})
    C.case('B1-readout-counts-distinct-ops-6-of-6', cnt === 6 && /6 of 6/i.test(note),
      `granted_count=${JSON.stringify(cnt)}（行数口径=缺陷②回潮）`)

    // B2 部分授予 → 2 of 6
    await save({ executor_sessions: ['exec-1'], grants: { sign: true, rerun: true } })
    const gP = await get()
    const pFace = (gP.body && (gP.body.grants || gP.body)) || {}
    C.case('B2-partial-readout-2-of-6', pFace.granted_count === 2 && /2 of 6/i.test(JSON.stringify(gP.body)),
      `granted_count=${JSON.stringify(pFace.granted_count)}`)

    // C1 没点名（另一项目：声明在、零点名）
    // C1 没点名（beta-2 项目：声明在、零点名）
    await jfetch(H.base, '/sandbar-executor-panel/api/grants?project=beta-2', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ by: 'host-sc', grants: { sign: true } }) })
    const gNS = await jfetch(H.base, '/sandbar-executor-panel/api/grants?project=beta-2')
    C.case('C1-no-session-named-state-explicit', stateOf(gNS) === 'no-session',
      `state=${stateOf(gNS)}`)

    // C2 点名零授予（A3 已达 named-zero-grants；此处复采一次作三态采点）
    await save({ op: 'master', enabled: false })
    const gNZ = await get()

    // C3 三态 state 值互异（granted / named-zero-grants / no-session）
    const states = new Set([stateOf(gAll), stateOf(gNZ), stateOf(gNS)])
    C.case('C3-readout-three-states-distinguishable', states.size === 3,
      `states=${JSON.stringify([...states])}（<3=缺陷③未修）`)

    // C4 畸形授予输入拒收（编辑面正常工作口径：saved:false + 人话原因）
    const bad = await save({ grants: { sign: 'yes' } })
    const unknown = await save({ grants: { teleport: true } })
    const rejected = (r) => r.body && (r.body.saved === false || r.body.ok === false) && !!(r.body.error || r.body.reason)
    C.case('C4-malformed-grants-still-rejected', rejected(bad) && rejected(unknown),
      `bad=${JSON.stringify(bad.body || {}).slice(0, 120)} unknown=${JSON.stringify(unknown.body || {}).slice(0, 120)}`)
  } finally {
    await H.close()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
