#!/usr/bin/env node
/**
 * t260921-03 场景：已结束工单的 UI 终态对账与异常收口呈现契约（灰盒 L2 组件契约层，
 * node 直 import 纯函数源 + 源级锚，零浏览器零 3099——镜 t260919-02
 * sc_failed_state_ui_model.mjs 同款手法，由 integration 在集成层独立钉契约）。
 *
 * 用户场景（工单正文，宿主 260921）：左栏工单列表里 t260920-02/t260921-01 显示
 * 「阻塞在 inspect」，但工作流早已 COMPLETED 且本期没有任何报告——用户扫一眼必须
 * 能认出「这张票已结束、且结束得不正常（无报告）」，而不是一张永远受阻的票。
 *
 * 覆盖面（票面验收五条之呈现面；引擎数据面归 sc_close_health_board.py）：
 *   U1 deriveTicketState 终态对账新判序：exec_status=COMPLETED → done **先于一切
 *      词面**（陈旧快照永不胜出）——blocked/running/failed 词面×COMPLETED 全组合
 *      暴力断言不得落 blocked/active/failed；CONTINUED_AS_NEW 转场态词面零扰动；
 *      失败族零回归 spot（全表归 t260919-02-failed-state-ui-model，不重复）；畸形
 *      exec（数字/对象/数组/布尔/空串/缺失）不 throw 落旧值。
 *   U2 closeHealthOf 部署窗镜像兜底：行带合法键→透传；键缺（老 bundle 行）→本地
 *      镜像只输出 {abnormal, failed, ''} 三值——绝不造 ok/unreadable（部署窗不许
 *      假正常）；已知偏差显式钉值（review 意见2）：降级闭合老行镜像给 abnormal 而非
 *      unreadable（同族不撒谎终态，措辞降级可接受）；非法值/null 行不 throw。
 *   U3 异常收口徽标词表：abnormal→「已结束·异常（无报告）」、unreadable→
 *      「已结束·待核」、ok/failed/''→不贴（正常收口与失败态不重复标注——反用例③）；
 *      徽标词与五态状态词互异可辨；不含瞬态占位语（KI-018①）。
 *   U4 排序：done×异常收口档位严格高于 done×正常收口（不沉底、不并入看起来正常的
 *      分组——要求③字面），失败档仍最顶（t260919-02 零回归）；sortMergedTickets
 *      端到端全序断言（时间戳反向构造，防「同档按时间巧合绿」）。
 *   U5 筛选：独立「异常收口」筛选（health='abnormal'，命中 abnormal+unreadable）
 *      与五态 chip AND 语义；异常收口仍归 done 桶（countByState 分母——要求⑤
 *      「归已结束桶」）。
 *   U6/U7 详情终态对账（review 意见1 契约化）：buildStatusCard 对 COMPLETED×abnormal
 *      出 amber 终态卡（headline 含「已结束」、无 retry-qc/rework 操作话术、原因
 *      可读）；正常收口不出异常措辞卡（反用例③）；源级锚（宽容 guard 词探针，不绑
 *      实现形状）：详情头 stage_state 徽标 / ⛔受阻横幅 / 基本信息状态行三处消费
 *      陈旧词面的站点必须被终态对账守卫——否则点开实案票详情仍见「受阻」=详情侧
 *      反向撒谎。
 *
 * 依据三支：①工单验收口径原文（五条要求+四组验收用例口径+交付即验收「点开可见原因」）；
 * ②KI（notes/debts/known-issues.md）：KI-018①（open——新增文案禁瞬态占位语）、
 * KI-055（台面绿×真机红——本场景 browser-free 离线钉词表契约，呈现面证据不依赖
 * 3099 bundle 窗）、KI-052（版本错窗——U2 部署窗镜像即该族的诚实性防御面）；
 * ③对外契约=t260921-03 方案 v1 承诺（close_health 五值词表/徽标两词/health 筛选
 * chip/tier 插层/amber 终态卡）。
 *
 * 分工（防 intent 级重复）：workbench/tests/t260904-17-ticket-list-model.mjs
 * （developer L1）钉判序真值表快照与缺省行；t260919-02-failed-state-ui-model 钉失败
 * 族全表与失败面视图（本条只做零回归 spot 不重复其任何断言）；t260919-02-terminal-
 * face-board 钉引擎失败行数据面。本条独立钉「COMPLETED 终态对账 + 异常收口可辨」
 * 端到端呈现契约，与彼三面零重叠。源级锚手法=t260919-02 源级锚先例（守调用点字面），
 * 但本票实现未落地，锚用宽容 guard 词探针（断契约不断形状）。
 * 纯离线无环境依赖（node 在场由登记 cmd 前置检查，缺=ENV_FAIL exit 2）。
 * 实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
 *
 * 跑法：node integration/t260921-03/sc_close_health_ui_model.mjs
 */

import { readFileSync } from 'node:fs'

let PASS = 0, FAIL = 0
function ok(cond, msg) {
  if (cond) { PASS++; console.log('  ok', msg) } else { FAIL++; console.log('  FAIL', msg) }
}

async function loadModule(url) {
  try { return { mod: await import(url) } } catch (e) { return { err: e } }
}

const MODEL_URL = '../../server/plugins/workbench/src/client/ticket-list-model.ts'
const CARD_URL = '../../server/plugins/workbench/src/host/status-card.ts'
const INDEX_URL = new URL('../../server/plugins/workbench/src/client/index.tsx', import.meta.url)

const model = await loadModule(MODEL_URL)
const cardMod = await loadModule(CARD_URL)
let idxSrc = ''
try { idxSrc = readFileSync(INDEX_URL, 'utf8') } catch { /* 源缺席=U7 各锚自会红 */ }

const dts = model.mod?.deriveTicketState
const closeHealthOf = model.mod?.closeHealthOf
const closeHealthBadgeOf = model.mod?.closeHealthBadgeOf
const sortMergedTickets = model.mod?.sortMergedTickets
const ticketMergeTierOf = model.mod?.ticketMergeTierOf
const filterRows = model.mod?.filterRows
const countByState = model.mod?.countByState
const STATE4_LABEL = model.mod?.STATE4_LABEL
const buildStatusCard = cardMod.mod?.buildStatusCard

function needFn(fn, name, group) {
  if (typeof fn !== 'function') {
    ok(false, `${group}：模型层导出 ${name} 在案（契约函数缺失——实现未落地或更名，red 预期）`)
    return false
  }
  return true
}

/* 实案形行（t260920-02 同构）：词面 blocked + 工作流 COMPLETED + 无报告 */
const ABN_ROW = {
  id: 'inspection-integration-tests-20260922', status: 'blocked', stage_state: 'blocked',
  exec_status: 'COMPLETED', engine: 'inspection', report_path: '',
  close_health: 'abnormal', close_health_reason: '本期无报告（report_path 缺失，发现 0 条）',
  updated_ts: 2000,
}
const OK_ROW = {
  id: 'inspection-integration-tests-20260923', status: 'closed', stage_state: 'awaiting-human',
  exec_status: 'COMPLETED', engine: 'inspection', report_path: 'out/inspection/x.json',
  close_health: 'ok', close_health_reason: '', updated_ts: 2500,   // ts 比 abnormal 新——防同档巧合绿
}
const UNREAD_ROW = { ...ABN_ROW, id: 'inspection-integration-tests-20260924', close_health: 'unreadable', updated_ts: 1500 }

/* ---------------- U1 终态对账新判序 ---------------- */
console.log('== U1 组：deriveTicketState——COMPLETED 先于一切词面（陈旧快照永不胜出）==')
if (needFn(dts, 'deriveTicketState', 'U1')) {
  const wordFaces = [
    ['blocked', 'blocked'], ['running', 'running'], ['open', 'awaiting'],
    ['dispatched', 'awaiting'], ['settled', 'awaiting-human'], ['verified', 'running'],
    ['rework', 'running'], ['closed', 'awaiting'], ['failed', 'failed'], ['', ''],
    [undefined, undefined],
  ]
  let bad = []
  for (const [s, ss] of wordFaces) {
    if (dts(s, ss, 'COMPLETED') !== 'done') bad.push(`(${JSON.stringify(s)},${JSON.stringify(ss)})`)
  }
  ok(bad.length === 0,
    `COMPLETED×全部词面组合→done（实案形 blocked×COMPLETED 必 done；违例=${bad.join(',') || '无'}）`)
  ok(dts('blocked', 'blocked', 'COMPLETED') !== 'blocked' && dts('blocked', 'blocked', 'COMPLETED') !== 'active',
    '实案形不再显示受阻/在飞（要求①「绝不再显示在跑/阻塞」字面）')
  // 转场态与在跑零扰动（spot——全表归 t260919-02 / L1）
  ok(dts('open', 'running', 'CONTINUED_AS_NEW') === 'active', 'CONTINUED_AS_NEW×running→active（转场词面零扰动）')
  ok(dts('open', 'blocked', 'CONTINUED_AS_NEW') === 'blocked', 'CONTINUED_AS_NEW×blocked→blocked（转场受阻照旧）')
  ok(dts('open', 'running', 'RUNNING') === 'active' && dts('open', 'blocked', 'RUNNING') === 'blocked',
    'RUNNING 词面沿用（存量在飞行零扰动）')
  // 失败族零回归 spot（全表归 t260919-02）
  ok(dts('open', 'running', 'FAILED') === 'failed' && dts('closed', 'awaiting', 'FAILED') === 'failed',
    '失败族→failed 零回归（t260919-02 锚 spot）')
  ok(dts('open', 'running') === 'active' && dts('closed', 'awaiting') === 'done',
    '缺 exec_status 落旧值（存量行零扰动）')
  // 畸形 exec 不 throw
  let threw = false
  try {
    for (const bad2 of [42, {}, [], true, 'COMPLETED ', '  ']) dts('blocked', 'blocked', bad2)
    dts('blocked', 'blocked', '')
    dts('blocked', 'blocked', undefined)
    dts('blocked', 'blocked', null)
  } catch { threw = true }
  ok(!threw, '畸形 exec（数字/对象/数组/布尔/带空白串/空/缺失）不 throw')
}

/* ---------------- U2 closeHealthOf 部署窗镜像 ---------------- */
console.log('== U2 组：closeHealthOf——行键透传 + 部署窗镜像三值（绝不造 ok）==')
if (needFn(closeHealthOf, 'closeHealthOf', 'U2')) {
  ok(closeHealthOf(ABN_ROW) === 'abnormal', '行带 close_health=abnormal → 透传')
  ok(closeHealthOf(UNREAD_ROW) === 'unreadable', '行带 close_health=unreadable → 透传')
  ok(closeHealthOf(OK_ROW) === 'ok', '行带 close_health=ok → 透传')
  // 部署窗老行（键缺）镜像：只输出 abnormal/failed/''——绝不造 ok/unreadable（KI-052 族诚实防御）
  const oldAbn = { ...ABN_ROW }; delete oldAbn.close_health; delete oldAbn.close_health_reason
  ok(closeHealthOf(oldAbn) === 'abnormal',
    '键缺×实案形（COMPLETED+inspection+report_path 缺）→镜像 abnormal（部署窗也要标出无报告）')
  const oldFail = { status: 'failed', stage_state: 'failed', exec_status: 'FAILED', engine: 'inspection' }
  ok(closeHealthOf(oldFail) === 'failed', '键缺×失败族→镜像 failed')
  const oldOk = { ...OK_ROW }; delete oldOk.close_health
  ok(closeHealthOf(oldOk) === '' || closeHealthOf(oldOk) === 'ok',
    '键缺×有报告行→镜像不造异常（\'\' 或 ok，绝不反向撒谎）')
  // 已知偏差（review 意见2 显式钉值）：降级闭合老行镜像给 abnormal 而非 unreadable——
  // 同在异常收口族、不撒谎终态，仅徽标措辞降级（待核→异常），部署窗内可接受
  const oldDegraded = { status: 'running', stage_state: 'running', exec_status: 'COMPLETED', engine: 'inspection', report_path: '' }
  ok(closeHealthOf(oldDegraded) === 'abnormal',
    '键缺×降级闭合老行（running 词面×COMPLETED×无报告）→镜像 abnormal（已知偏差：非 unreadable，钉值防漂移）')
  ok(closeHealthOf({ ...oldAbn, close_health: 'weird' }) !== 'weird',
    '非法 close_health 值不透传（降级镜像，绝不把脏值送上板）')
  ok(closeHealthOf(null) === '' && closeHealthOf(undefined) === '' && closeHealthOf({}) === '',
    'null/undefined/空对象行 → \'\' 不 throw（行=不可信外部输入）')
  const out = closeHealthOf({ ...oldAbn, report_path: 42 })
  ok(out === 'abnormal' || out === '', 'report_path 非串（数字）容忍不 throw，按缺失/无断言处置')
}

/* ---------------- U3 徽标词表 ---------------- */
console.log('== U3 组：异常收口徽标（可扫读 + 反用例：正常/失败不贴）==')
if (needFn(closeHealthBadgeOf, 'closeHealthBadgeOf', 'U3')) {
  ok(closeHealthBadgeOf(ABN_ROW) === 'Closed·Abnormal (no report)', // t260925-18 UI 英文化：词面改英文，契约=abnormal 可扫读+带无报告语义
    `abnormal→「已结束·异常（无报告）」（got ${JSON.stringify(closeHealthBadgeOf(ABN_ROW))}）`)
  ok(closeHealthBadgeOf(UNREAD_ROW) === 'Closed·Unverified', // 同上：unreadable 词面英文
    `unreadable→「已结束·待核」（got ${JSON.stringify(closeHealthBadgeOf(UNREAD_ROW))}）`)
  ok(closeHealthBadgeOf(OK_ROW) === '', '正常收口不贴徽标（反用例③：不得被标成异常/看起来正常即可）')
  const failRow = { status: 'failed', stage_state: 'failed', exec_status: 'FAILED', close_health: 'failed' }
  ok(closeHealthBadgeOf(failRow) === '', 'failed 行不重复贴异常收口徽标（已有「已失败」态字）')
  const badge = closeHealthBadgeOf(ABN_ROW)
  const stateWords = Object.values(STATE4_LABEL ?? {})
  ok(!stateWords.includes(badge), '徽标词与五态状态词互异可辨（异常收口是新维度，不撞车状态词表）')
  for (const bad3 of ['刷新重试', '查询超时', '瞬时']) {
    ok(!badge.includes(bad3), `徽标不含「${bad3}」瞬态占位语（KI-018①）`)
  }
}

/* ---------------- U4 排序（不沉底、不并组） ---------------- */
console.log('== U4 组：排序——异常收口档严格高于正常收口档（端到端全序）==')
if (needFn(sortMergedTickets, 'sortMergedTickets', 'U4') && needFn(ticketMergeTierOf, 'ticketMergeTierOf', 'U4')) {
  const w = { id: 'w-wait', status: 'open', stage_state: 'awaiting-human', updated_ts: 5000 }
  const f = { id: 'f-fail', status: 'failed', stage_state: 'failed', exec_status: 'FAILED', updated_ts: 4000 }
  const a = { id: 'a-run', status: 'open', stage_state: 'running', exec_status: 'RUNNING', updated_ts: 3000 }
  const abn = { ...ABN_ROW }
  const okd = { ...OK_ROW }   // okd.updated_ts=2500 > abn 2000：若同档按时间倒序会排在 abn 前=必红
  const sorted = sortMergedTickets([okd, abn, a, f, w]).map(r => r.id)
  ok(JSON.stringify(sorted) === JSON.stringify(['w-wait', 'f-fail', 'a-run', 'inspection-integration-tests-20260922', 'inspection-integration-tests-20260923']),
    `全序=等你/失败→在跑→异常收口→正常收口（got ${JSON.stringify(sorted)}；abnormal 不得沉底或被 ok 档时间戳压过）`)
  // 档位相对关系（宽容探针：4 参行参优先，回落 3 参——断契约不断签名）
  const tierOf = (row) => {
    try { return ticketMergeTierOf(row.status, row.stage_state, row.exec_status, row) } catch { /* 形状回落 */ }
    return ticketMergeTierOf(row.status, row.stage_state, row.exec_status)
  }
  const tAbn = tierOf(abn), tOk = tierOf(okd), tFail = tierOf(f), tRun = tierOf(a)
  ok(tAbn < tOk, `done×abnormal 档 < done×ok 档（${tAbn} < ${tOk}——不并入看起来正常的分组）`)
  ok(tFail < tAbn, `失败档仍最顶（${tFail} < ${tAbn}——t260919-02 零回归）`)
  ok(tRun < tAbn, `在跑档高于异常收口档（${tRun} < ${tAbn}——收口行不插队活跃票）`)
}

/* ---------------- U5 筛选与桶归属 ---------------- */
console.log('== U5 组：异常收口筛选 chip（AND 语义）+ done 桶归属不变 ==')
if (needFn(filterRows, 'filterRows', 'U5') && needFn(countByState, 'countByState', 'U5')) {
  const rows = [ABN_ROW, UNREAD_ROW, OK_ROW,
    { ...ABN_ROW, id: 'x-run', status: 'open', stage_state: 'running', exec_status: 'RUNNING', close_health: '' }]
  const hit = filterRows(rows, { state: 'done', health: 'abnormal' }).map(r => r.id)
  ok(JSON.stringify(hit.sort()) === JSON.stringify([ABN_ROW.id, UNREAD_ROW.id].sort()),
    `done×health=abnormal → 仅异常收口两张（abnormal+unreadable；AND 语义；got ${JSON.stringify(hit)}）`)
  ok(filterRows(rows, {}).length === rows.length, '不带筛选→全量（chip 是过滤非分组，零扰动）')
  const counts = countByState([ABN_ROW, OK_ROW])
  ok(counts.done === 2, `异常收口仍归 done 桶（countByState.done=${counts.done}——要求⑤「归已结束桶」，折叠分母口径不变）`)
}

/* ---------------- U6/U7 详情终态对账 ---------------- */
console.log('== U6 组：buildStatusCard 终态收口卡（amber，已结束+原因，零操作话术）==')
if (needFn(buildStatusCard, 'buildStatusCard', 'U6')) {
  const detail = {
    id: ABN_ROW.id, status: 'blocked', stage_state: 'blocked',
    blocked_reason: 'agent 退出码 1（未完成）；输出尾：unknown preset "read-only"',
    exec_status: 'COMPLETED', close_health: 'abnormal',
    close_health_reason: '本期无报告（report_path 缺失，发现 0 条）',
    findings: { high: 0, med: 0, low: 0, total: 0 }, report_path: '',
  }
  const card = buildStatusCard(detail)
  ok(card !== null && typeof card === 'object', 'COMPLETED×abnormal 详情出状态卡（不为 null——点开可见原因）')
  if (card) {
    ok(card.severity === 'amber', `终态收口卡 severity=amber（复用既有 warn 面；got ${card.severity}）`)
    ok(String(card.headline ?? '').includes('Closed'), `headline 含「已结束」（got ${JSON.stringify(card.headline)}——结束方式可表达）`)
    const all = JSON.stringify(card, (k, v) => typeof v === 'function' ? '<fn>' : v)
    ok(all.includes('无报告') || all.includes('report_path'), '卡面点名缺了什么（要求④「缺了什么」）')
    ok(all.includes('退出码 1') || all.includes('read-only'), '卡面携带异常原因事实（blocked_reason 链可达——不许无因异常）')
    ok(!/retry[- ]qc|rework|unblock|打回|重试/i.test(String(card.next ?? '')),
      `终态卡 next 零操作话术（got ${JSON.stringify(card.next)}——已结束票不给推进话术，票面边界）`)
    for (const bad4 of ['刷新重试', '查询超时']) {
      ok(!all.includes(bad4), `卡面不含「${bad4}」瞬态占位语（KI-018① 新增面）`)
    }
  }
  const okCard = buildStatusCard({ ...detail, status: 'closed', stage_state: 'awaiting-human', close_health: 'ok', close_health_reason: '', report_path: 'out/x.json', blocked_reason: '' })
  ok(okCard === null || !String(okCard?.headline ?? '').includes('异常'),
    '正常收口不出异常措辞卡（反用例③：对账不反向撒谎）')
  ok(buildStatusCard(null) === null && buildStatusCard(42) === null && buildStatusCard('x') === null,
    '畸形 detail（null/数字/串）→null 不 throw（既有契约 spot）')
  // gen1 修订（验收走查问题1）：落账镜像形态（abnormal×report_path 在场，live 实案
  // 真形）的「缺了什么」必须与引擎 reason 同口径——旧实现输出「报告已在（本卡不该
  // 出现…）」与异常原因行自相矛盾=异常收口看起来没问题（票义红线）。上面的主夹具
  // report_path=''，此子用例专钉该形态防回潮。
  // t261004-20：report_path 展示值从仓根推导（镜像本树产物的真实落点），不绑宿主机器路径。
  const mirrorCard = buildStatusCard({
    ...detail,
    report_path: new URL('../../server/engine/out/inspection/inspection-integration-tests-20260920.json', import.meta.url).pathname,
    close_health_reason: '面快照 blocked：agent 退出码 1（未完成）；发现 0 条（落账文件为受阻面镜像）',
  })
  const mirrorAll = JSON.stringify(mirrorCard ?? {})
  ok(mirrorCard !== null && !mirrorAll.includes('报告已在') && !mirrorAll.includes('不该出现'),
    '落账镜像形态「缺了什么」无「报告已在/不该出现」矛盾文案（gen1 问题1 防回潮）')
  ok(mirrorAll.includes('Missing: No report for this period'),
    `落账镜像形态缺了什么=引擎 reason 同口径（got ${JSON.stringify(mirrorCard?.closeFacts?.find(f => String(f).startsWith('Missing:')) ?? '')}）`)
}

console.log('== U7 组：详情头陈旧词面站点必须被终态对账守卫（review 意见1 源级锚，宽容 guard 探针）==')
{
  // 宽容锚：定位三处消费 detail.stage_state 的站点，断言其紧邻区域出现终态对账
  // guard 词（实现形状不限——deriveTicketState 单点/close_health/exec_status/COMPLETED
  // 任一在场即守卫在位）。实现落地前三处全红=TDD 信号。
  const GUARD = /deriveTicketState\s*\(|close_health|exec_status|COMPLETED|'done'/
  const sites = [
    { name: '详情头 stage_state 徽标', lit: 'data-state={detail.stage_state}' },
    { name: '⛔受阻原因横幅', lit: '⛔ Blocked:' }, // t260925-18 UI 英文化：横幅固定文案改英文，站点与守卫契约不变
    // t260925-18：基本信息区块整体从详情 UI 移除（数据面仍走 ticket CLI）——该站点
    // 不复存在，守卫对象随之消失（契约对已删站点空真）；两处存活站点继续钉。
  ]
  for (const { name, lit } of sites) {
    const at = idxSrc.indexOf(lit)
    if (at < 0) { ok(false, `${name}：站点字面在源（未找到 ${JSON.stringify(lit)}——源形状漂移，改锚勿改契约）`); continue }
    const windowSrc = idxSrc.slice(Math.max(0, at - 400), at + 400)
    ok(GUARD.test(windowSrc),
      `${name}：紧邻区域带终态对账守卫（陈旧词面不得对已结束票渲染受阻/在跑——要求①详情半边）`)
  }
}

console.log(`SUMMARY pass=${PASS} fail=${FAIL} env_fail=0 na=0`)
process.exit(FAIL > 0 ? 1 : 0)
