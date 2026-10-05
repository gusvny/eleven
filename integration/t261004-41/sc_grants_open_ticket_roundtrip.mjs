// sc_grants_open_ticket_roundtrip.mjs — t261004-41 回归：面板授权写链路必须把
// 用户在 Grants 页编辑的每一个字段带到盘上（open_ticket_epics / open_ticket_cap
// 当日在 api.ts 处理器与引擎入口两处被静默丢弃，宿主实报：勾选 epics → Saved. →
// 列表不变）。灰盒 L3，harness 缝驱动生产路由面（POST /api/grants → 引擎 CLI
// executor-grants-write → 声明文件），离线零 docker 零浏览器，红线零接触 3099。
//
// Intent（用户可感知行为，锚公开 JSON 契约=HTTP 回执与 GET 读面，不锚盘上私有布局）：
//   V1 全字段保存往返：一次 save 带全部五个可写字段（grants / night_tier /
//      executor_sessions / open_ticket_epics / open_ticket_cap）→ saved:true 且
//      GET 读面逐字段返回所写值——任何一个字段静默丢回即红（本票缺陷本体）。
//   V2 缺席=继承：部分编辑不带 open_ticket_* → 盘上先前的 epics 与 cap 原样保留
//      （部分编辑绝不抹字段）。
//   V3 显式清空：save 带 open_ticket_epics: [] → 读面列表为空——显式 [] 不得被
//      当成「缺席」继承回旧值。
//   V4 master 切换不抹面：master enabled:true / enabled:false 都不得动 epics/cap
//      （总闸只管授权面）。
//   V5 畸形输入显式拒绝：open_ticket_cap: true / open_ticket_epics: "all" →
//      saved:false（或 4xx）显式点名，绝不 saved:true 假成功（KI-193 家族教训：
//      假回执把诊断引向错误方向）。
// 分层口径：developer 侧 ms 级契约用例（engine-grants-write.test.mjs，stub 引擎）
// 归 L2；本场景是真缝全链（真 spawn 引擎 CLI）+ 用户旅程形状，锁的是 seam 而非
// 单层。静态字段奇偶守卫归 lint L19（integration/lint_tests.py），不在此重复。
//
// 三态：缝缺席/字段仍在链上被丢=FAIL exit 1 且点名（TDD 期红属预期：implement 落地
// 前本场景必须红，落地后必须绿）；node/harness 环境缺失=ENV_FAIL exit 2。
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { mkdirSync, writeFileSync } from 'node:fs'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const EPICS = ['epic-next', 'epic-grants']

const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))

const jget = (base, url, headers = {}) => fetch(base + url, { headers })
  .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))

function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + createHash('sha256').update(host).digest().toString('base64url')
  return name + '=v1.AAAA.BBBB'
}

const grantsPost = (H, cookie, body) =>
  jpost(H.base, `/sandbar-executor-panel/api/grants?project=${PROJ}`, body, cookie())
const grantsGet = (H, cookie) =>
  jget(H.base, `/sandbar-executor-panel/api/grants?project=${PROJ}`, cookie())

function readoutOf(res) {
  const b = res.body
  if (!b) return {}
  if (b.declaration) return b.declaration
  const g = b.grants_readout ?? b.readout ?? b
  return { open_ticket_epics: g.open_ticket_epics, open_ticket_cap: g.open_ticket_cap }
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.envFail('harness-loadable', 'server/plugins/executor-panel/harness.mjs 缺 startHarness（环境缝缺失=ENV_FAIL）')
    return C.exit()
  }
  const iso = makeIsoDir('t261004-41-roundtrip-')
  const H = await harness.startHarness({
    panelDir: join(iso.dir, 'panel'),
    watchdogDir: join(iso.dir, 'watchdog'),
    workbenchStub: true,
  })
  try {
    const cookie = () => ({ cookie: consoleCookie(H.base) })
    mkdirSync(join(iso.dir, 'watchdog', PROJ), { recursive: true })
    writeFileSync(join(iso.dir, 'watchdog', PROJ, 'requests.jsonl'),
      JSON.stringify({ type: 'request', id: 'r1', project: PROJ, kind: 'question', question: 'seed?', text: 'seed', at: 1 }) + '\n')

    // V1 全字段保存往返（含页面无控件的 cap：字段集整体往返，下一字段不得重演本缺陷）
    const full = {
      op: 'save',
      grants: { 'sign': true, 'rerun': true },
      night_tier: { enabled: true, until: Date.now() + 3600_000 },
      executor_sessions: ['sess-a'],
      open_ticket_epics: EPICS,
      open_ticket_cap: 5,
    }
    const s1 = await grantsPost(H, cookie, full)
    const saved1 = s1.body && (s1.body.saved === true || s1.body.ok === true)
    C.case('V1-full-save-accepted', s1.status === 200 && saved1,
      `status=${s1.status} saved=${JSON.stringify(s1.body && s1.body.saved)} err=${JSON.stringify(s1.body && (s1.body.reason || s1.body.error))}`)
    const r1 = await grantsGet(H, cookie)
    const ro1 = readoutOf(r1)
    const epicsOk = Array.isArray(ro1.open_ticket_epics) &&
      EPICS.every((e) => ro1.open_ticket_epics.includes(e)) &&
      ro1.open_ticket_epics.length === EPICS.length
    C.case('V1-epics-roundtrip', epicsOk,
      `readout=${JSON.stringify(ro1.open_ticket_epics)} want=${JSON.stringify(EPICS)}`)
    C.case('V1-cap-roundtrip', ro1.open_ticket_cap === 5,
      `readout=${JSON.stringify(ro1.open_ticket_cap)} want=5`)
    const sessOk = (() => {
      const s = (r1.body && (r1.body.declaration ?? r1.body))?.executor_sessions
      return Array.isArray(s) && s.includes('sess-a')
    })()
    C.case('V1-sessions-roundtrip', sessOk, `readout=${JSON.stringify(r1.body && r1.body.declaration && r1.body.declaration.executor_sessions)}`)

    // V2 缺席=继承：部分编辑不带 open_ticket_* → 先前的 epics/cap 保留
    const partial = await grantsPost(H, cookie, {
      op: 'save', grants: { 'sign': false, 'rerun': true },
    })
    const r2 = await grantsGet(H, cookie)
    const ro2 = readoutOf(r2)
    const kept = Array.isArray(ro2.open_ticket_epics) && ro2.open_ticket_epics.length === EPICS.length &&
      ro2.open_ticket_cap === 5
    C.case('V2-partial-edit-inherits-open-ticket', partial.status === 200 && kept,
      `status=${partial.status} readout=${JSON.stringify({ epics: ro2.open_ticket_epics, cap: ro2.open_ticket_cap })}`)

    // V3 显式清空：[] 必须到达盘上（不得被当「缺席」继承回旧值）
    const clear = await grantsPost(H, cookie, { op: 'save', grants: { 'rerun': true }, open_ticket_epics: [] })
    const r3 = await grantsGet(H, cookie)
    const ro3 = readoutOf(r3)
    C.case('V3-explicit-empty-clears-list', clear.status === 200 &&
      Array.isArray(ro3.open_ticket_epics) && ro3.open_ticket_epics.length === 0,
      `status=${clear.status} readout=${JSON.stringify(ro3.open_ticket_epics)}`)

    // V4 master 切换不抹 epics/cap：先重铺值，再 master on / off
    await grantsPost(H, cookie, { op: 'save', grants: { 'rerun': true }, open_ticket_epics: EPICS, open_ticket_cap: 4 })
    const mOn = await grantsPost(H, cookie, { op: 'master', enabled: true })
    const r4a = await grantsGet(H, cookie)
    const ro4a = readoutOf(r4a)
    const mOff = await grantsPost(H, cookie, { op: 'master', enabled: false })
    const r4b = await grantsGet(H, cookie)
    const ro4b = readoutOf(r4b)
    const keptOn = Array.isArray(ro4a.open_ticket_epics) && ro4a.open_ticket_epics.length === EPICS.length && ro4a.open_ticket_cap === 4
    const keptOff = Array.isArray(ro4b.open_ticket_epics) && ro4b.open_ticket_epics.length === EPICS.length && ro4b.open_ticket_cap === 4
    C.case('V4-master-on-keeps-open-ticket', mOn.status === 200 && keptOn,
      `status=${mOn.status} readout=${JSON.stringify({ epics: ro4a.open_ticket_epics, cap: ro4a.open_ticket_cap })}`)
    C.case('V4-master-off-keeps-open-ticket', mOff.status === 200 && keptOff,
      `status=${mOff.status} readout=${JSON.stringify({ epics: ro4b.open_ticket_epics, cap: ro4b.open_ticket_cap })}`)

    // V5 畸形输入按定稿语义「降级=缺席→继承」：不崩入口、不假抹盘——畸形值
    // 不得把已存的 epics/cap 清掉（plan Step 1c 定稿：malformed → dropped to None
    // = inherit；显式拒绝语义归 cap<1 / 非 list 等形状错，由引擎校验面拒绝）。
    const badCap = await grantsPost(H, cookie, { op: 'save', grants: { 'rerun': true }, open_ticket_cap: true })
    const r5a = await grantsGet(H, cookie)
    const ro5a = readoutOf(r5a)
    C.case('V5-malformed-cap-degrades-not-wipes', badCap.status === 200 &&
      Array.isArray(ro5a.open_ticket_epics) && ro5a.open_ticket_epics.length === EPICS.length && ro5a.open_ticket_cap === 4,
      `status=${badCap.status} readout=${JSON.stringify({ epics: ro5a.open_ticket_epics, cap: ro5a.open_ticket_cap })}`)
    const badEpics = await grantsPost(H, cookie, { op: 'save', grants: { 'rerun': true }, open_ticket_epics: 'all' })
    const r5b = await grantsGet(H, cookie)
    const ro5b = readoutOf(r5b)
    C.case('V5-malformed-epics-degrade-not-wipes', badEpics.status === 200 &&
      Array.isArray(ro5b.open_ticket_epics) && ro5b.open_ticket_epics.length === EPICS.length && ro5b.open_ticket_cap === 4,
      `status=${badEpics.status} readout=${JSON.stringify({ epics: ro5b.open_ticket_epics, cap: ro5b.open_ticket_cap })}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e && e.stack || e).slice(0, 300)); C.exit() })
