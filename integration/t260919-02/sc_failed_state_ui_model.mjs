#!/usr/bin/env node
/**
 * t260919-02 场景：终态失败票的 UI 状态词表契约（灰盒 L2 组件契约层，node 直 import
 * 纯函数源，零浏览器零 3099——镜 workbench/tests/t260904-17-ticket-list-model.mjs 同款
 * node 裸 import 黑盒单测手法，由 integration 在集成层独立钉契约）。
 *
 * 用户场景（工单正文验收①）：列表行的「已失败」必须与「在跑」可区分、与「收口」不混同
 * ——用户扫一眼 chips/行卡就能认出「这张票已经死 了，为什么失败」。引擎行形状契约由
 * sc_terminal_face_board.py 钉（数据面），本场景钉 UI 词表与失败面视图（呈现面）。
 *
 * 覆盖面（票面验收①「四态×文案对照」+验收②「绝不空面板/绝不编造」的 UI 半边）：
 *   S1 deriveTicketState 真值表：失败族（FAILED/CANCELED/TIMED_OUT/未知新终态）→ failed；
 *      现四态全保持（缺 exec_status 逐条旧值不变——存量行零扰动）；CONTINUED_AS_NEW
 *      沿用现四态（转场态不显失败）；畸形 exec_status（数字/对象）不 throw；
 *      断链防御子用例（review 附条件①）：exec_status 缺失但 status/stage_state 词面
 *      'failed' → failed（失败行不得因键断链回退显在跑）。
 *   S2 失败文案可辨：failed 态人话短名=「已失败」，五态文案互异（与 running/done 可区分）。
 *   S3 chips 接线：countByState 认 failed 键；filterRows 按 failed 过滤。
 *   S4 合并排序：failed 行置顶档（tier0，与等你/受阻同档——死票不沉底）。
 *   S5 terminalFaceView 失败面视图：全字段 face → 视图含执行状态/原因/无快照说明；
 *      原因不可得 face → 显式「原因不可得」；畸形 face（null/串/数字/缺键）全降级
 *      不抛不编造（验收②「绝不空面板、绝不编造」的纯函数半边）。
 *   S6 视图=纯数据对象（零函数值字段——渲染层才持有操作入口，失败面零操作入口的
 *      数据面前提）。
 *
 * 依据三支：①工单验收口径（四态×文案对照/失败标记可辨/原因不可得显式）；②KI：
 * KI-025 家族诚实口径（失败态不得伪装可重试——failed 态必须独立于 active 存在）；
 * ③契约=方案 v1（TicketState5 第五态 failed/「已失败」/补集口径/terminal-face.ts
 * terminalFaceView 纯函数）。
 *
 * 分工（防 intent 重复）：workbench/tests/t260904-17-ticket-list-model.mjs（developer
 * L1，随票扩）钉词表快照与缺省行；ki025_show_error_split.mjs 钉 410 分级纯函数；本场景
 * 在集成层独立钉「失败可辨」端到端词表契约+失败面视图降级面，不重复彼两面的任何断言。
 * 纯离线无环境依赖（node 在场由登记 cmd 前置检查，缺=ENV_FAIL exit 2）。
 * 实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
 *
 * 跑法：node integration/t260919-02/sc_failed_state_ui_model.mjs
 */

let PASS = 0, FAIL = 0
function ok(cond, msg) {
  if (cond) { PASS++; console.log('  ok', msg) } else { FAIL++; console.log('  FAIL', msg) }
}

async function loadModule(url, label) {
  try {
    return { mod: await import(url) }
  } catch (e) {
    return { err: e }
  }
}

const MODEL_URL = '../../server/plugins/workbench/src/client/ticket-list-model.ts'
const FACE_URL = '../../server/plugins/workbench/src/client/terminal-face.ts'

const model = await loadModule(MODEL_URL, 'ticket-list-model')
const STATES = ['active', 'done', 'waiting', 'blocked', 'failed']

console.log('== S1 组：deriveTicketState 真值表（失败族→failed；现四态零扰动）==')
if (model.err) {
  ok(false, `ticket-list-model.ts 加载失败：${model.err.message}`)
} else {
  const d = model.mod.deriveTicketState
  ok(typeof d === 'function', 'deriveTicketState 导出在位')
  if (typeof d === 'function') {
    // 失败族（exec_status 补集口径：终态非成功即失败，未知新终态宁显失败不显在跑）
    for (const es of ['FAILED', 'CANCELED', 'TIMED_OUT', 'ZOMBIE']) {
      let got, threw = false
      try { got = d('dispatched', 'running', es) } catch (e) { threw = true }
      ok(!threw && got === 'failed',
         `exec_status=${es} → failed（与在跑可辨；got=${got}）`)
    }
    // 现四态零扰动（缺 exec_status=存量行逐条旧值不变）
    const legacy = [
      [['closed', 'awaiting'], 'done'],
      [['x', 'blocked'], 'blocked'],
      [['x', 'awaiting-human'], 'waiting'],
      [['x', 'running'], 'active'],
      [['x', 'awaiting'], 'active'],
      [['x', 'mystery'], 'active'],   // 未知 stage_state 宁显活跃（既有缺省行）
    ]
    for (const [[st, ss], want] of legacy) {
      const got = d(st, ss)
      ok(got === want, `缺 exec_status 旧行为保持：(${st},${ss})→${want}（got=${got}）`)
      const gotEmpty = d(st, ss, '')
      ok(gotEmpty === want, `空串 exec_status 同缺省：(${st},${ss},'')→${want}（got=${gotEmpty}）`)
    }
    // 成功/转场态不被误判失败
    ok(d('closed', 'awaiting', 'COMPLETED') === 'done', 'COMPLETED+closed → done（收口零回归）')
    ok(d('dispatched', 'running', 'RUNNING') === 'active', 'RUNNING → active（在跑零回归）')
    ok(d('dispatched', 'running', 'CONTINUED_AS_NEW') === 'active',
       'CONTINUED_AS_NEW（转场）不显失败（got=%s）'.replace('%s', d('dispatched', 'running', 'CONTINUED_AS_NEW')))
    // 畸形 exec_status：不 throw，落缺省（沿用现四态）
    for (const bad of [42, {}, ['x'], true]) {
      let got, threw = false
      try { got = d('dispatched', 'running', bad) } catch (e) { threw = true }
      ok(!threw && STATES.includes(got),
         `畸形 exec_status=${JSON.stringify(bad)} 不 throw 且落五态内（got=${got}）`)
    }
    // 断链防御子用例（review 附条件①）：exec_status 缺失但行词面已是 failed → 不得回退在跑
    ok(d('failed', 'failed') === 'failed',
       `断链防御：exec_status 缺失+status/stage_state='failed' → failed（got=${d('failed', 'failed')}）`)
    ok(d(undefined, 'failed', undefined) === 'failed',
       `断链防御：仅 stage_state='failed' 词面 → failed（got=${d(undefined, 'failed')}）`)
  }
}

console.log('== S2 组：失败文案可辨（「已失败」与四态文案互异）==')
if (model.err) {
  ok(false, 'ticket-list-model.ts 未落地（S2 跳断言=FAIL，TDD 红）')
} else {
  const L = model.mod.STATE4_LABEL
  ok(L && typeof L === 'object', 'STATE4_LABEL 词表在位')
  if (L && typeof L === 'object') {
    ok(L.failed === '已失败', `failed 文案=「已失败」（got=${JSON.stringify(L.failed)}）`)
    const vals = Object.values(L)
    ok(new Set(vals).size === vals.length, `五态文案互异（${JSON.stringify(L)}）`)
    ok(STATES.every(s => s in L), `五键齐（缺=${STATES.filter(s => !(s in L))}）`)
  }
}

console.log('== S3 组：chips 接线（countByState/filterRows 认 failed）==')
if (model.err) {
  ok(false, 'ticket-list-model.ts 未落地（S3 FAIL，TDD 红）')
} else {
  const { countByState, filterRows } = model.mod
  const rows = [
    { id: 'a', status: 'dispatched', stage_state: 'running', exec_status: 'FAILED' },
    { id: 'b', status: 'dispatched', stage_state: 'running', exec_status: 'RUNNING' },
    { id: 'c', status: 'closed', stage_state: 'awaiting' },
  ]
  const counts = countByState(rows)
  ok(counts && counts.failed === 1, `countByState.failed==1（got=${counts && counts.failed}）`)
  ok(counts && counts.active === 1 && counts.done === 1,
     `active/done 计数零回归（${JSON.stringify(counts)}）`)
  const picked = filterRows(rows, { state: 'failed' })
  ok(Array.isArray(picked) && picked.length === 1 && picked[0].id === 'a',
     'filterRows(state=failed) 恰取失败行')
}

console.log('== S4 组：合并排序（failed 置顶档，死票不沉底）==')
if (model.err) {
  ok(false, 'ticket-list-model.ts 未落地（S4 FAIL，TDD 红）')
} else {
  const { ticketMergeTierOf } = model.mod
  ok(ticketMergeTierOf('dispatched', 'running', 'FAILED') === 0,
     `failed → tier0（置顶；got=${ticketMergeTierOf('dispatched', 'running', 'FAILED')}）`)
  ok(ticketMergeTierOf('dispatched', 'running', 'RUNNING') === 1,
     'RUNNING → tier1（在跑档零回归）')
  // t260921-03 有意更新（根因见该函数注释与 t260916-15 UT 同名块）：收口档拆二——
  // 正常收口 2→3，异常收口插层 tier2（不沉底不并入「看起来正常」组）；失败档 0
  // 与在跑档 1 零回归。三参形态（无行参）回落实正常收口=3。
  ok(ticketMergeTierOf('closed', 'awaiting', 'COMPLETED') === 3,
     'COMPLETED → tier3（正常收口档；t260921-03 拆档后）')
  ok(ticketMergeTierOf('closed', 'awaiting', 'COMPLETED', { exec_status: 'COMPLETED' }) === 3,
     'COMPLETED 健康行（四参）→ tier3')
  ok(ticketMergeTierOf('blocked', 'blocked', 'COMPLETED',
    { exec_status: 'COMPLETED', close_health: 'abnormal' }) === 2,
     'COMPLETED×异常收口（四参行参）→ tier2（不沉底不并入正常收口组）')
}

console.log('== S5/S6 组：terminalFaceView 失败面视图（降级不抛/原因不可得/纯数据）==')
const face = await loadModule(FACE_URL, 'terminal-face')
if (face.err) {
  ok(false, `terminal-face.ts 未落地（S5/S6 FAIL，TDD 红）：${face.err.message}`)
} else {
  const viewOf = face.mod.terminalFaceView
  ok(typeof viewOf === 'function',
     `terminalFaceView 导出在位（实际导出键=${Object.keys(face.mod)}）`)
  if (typeof viewOf === 'function') {
    const full = {
      exec_status: 'FAILED',
      reason: '套件 boom: step close failed',
      close_time: '2026-09-19 07:30',
      instance_id: 'integration-tests',
      period: '20260919',
      snapshot_available: false,
      snapshot_note: '终态票快照不可查询',
      last_stage: null,
    }
    let v = null, threw = false
    try { v = viewOf(full) } catch (e) { threw = true }
    ok(!threw && v && typeof v === 'object', '全字段 face 渲染不抛')
    const txt = JSON.stringify(v)
    ok(txt.includes('FAILED'), '视图含执行状态')
    ok(txt.includes('boom'), '视图含失败原因串')
    ok(txt.includes('integration-tests'), '视图含票身份（实例）')
    ok(!threw && v !== null && typeof v === 'object', '视图非空对象（绝不空面板）')
    // 原因不可得：显式文案+保留执行状态
    let v2 = null, threw2 = false
    try { v2 = viewOf({ exec_status: 'FAILED' }) } catch (e) { threw2 = true }
    const t2 = JSON.stringify(v2)
    ok(!threw2 && t2.includes('原因不可得'),
       `原因不可得 face → 显式「原因不可得」（got=${t2.slice(0, 120)}）`)
    ok(!threw2 && t2.includes('FAILED'), '原因不可得时执行状态保留（绝不编造绝不丢状态）')
    // 畸形 face：全降级不抛
    for (const bad of [null, 'x', 42, [], {}, undefined]) {
      let out = null, t = false
      try { out = viewOf(bad) } catch (e) { t = true }
      ok(!t, `畸形 face=${JSON.stringify(bad)} 不抛`)
    }
    // S6：纯数据视图（零函数值字段——操作入口只在渲染层，数据面不得携带）
    const hasFn = (() => {
      const seen = [viewOf(full), viewOf({})].filter(x => x && typeof x === 'object')
      const walk = (o, depth) => {
        if (depth > 3 || !o || typeof o !== 'object') return false
        for (const val of Object.values(o)) {
          if (typeof val === 'function') return true
          if (walk(val, depth + 1)) return true
        }
        return false
      }
      return seen.some(o => walk(o, 0))
    })()
    ok(!hasFn, '视图为纯数据（零函数值字段——失败面零操作入口的数据面前提）')
  }
}

console.log(`SUMMARY pass=${PASS} fail=${FAIL} env_fail=0 na=0`)
process.exit(FAIL > 0 ? 1 : 0)
