#!/usr/bin/env node
// t260919-02 终态失败票两面可见 UT：详情失败面视图模型真值表 + host 装配行为 +
// 接线源级锚（渲染断言归属纪律同 t260916-15：纯函数/纯装配在此，真浏览器渲染归场景）。
//
// 覆盖（对应票面验收②③与 review 意见①②④）：
//   A. terminalFaceView 全字段装配（face 全键 → 面板字段逐一可渲染）。
//   B. 畸形 face（null/非对象/数组）全降级：不 throw、显式「原因不可得」、绝不编造。
//   C. 反用例：终态但原因不可得（reason_available=false / reason=''）→ 显式
//      「原因不可得」文案 + 执行状态原文保留（绝不把「查不到原因」渲染成没失败）。
//   D. 诚实口径：回执错误原文（含「刷新无效」）随视图可达；快照/阶段说明缺省兜底。
//   E. host 装配（ticketShowErrorReply）：terminal+face → 410 且附 face；
//      直读失败/超时/畸形（face 缺失/null/数组/标量）→ 仍 410 且**无 face 键**
//      （review② 降级分支，UI 降纯错误提示不渲染失败面板）；非 terminal kind 不附带；
//      transient 仍 503+retryable（KI-025 分级零回归）。
//   F. 源级锚：TerminalFailurePanel 零操作入口；抽屉接线（terminalFace 渲染/清态）；
//      openDetail 捕获 face；node.ts 直读桥（terminal → 直读 ticket-query、超时小于
//      UI 体验阈值）；chips/CSS failed 接线在源。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  terminalFaceView, TERMINAL_FACE_FALLBACKS,
} from '../src/client/terminal-face.ts'
import {
  ticketShowErrorReply, ticketShowHttpVerdict,
} from '../src/host/ticket-error.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
  console.log(`  ok ${msg}`)
}

/* ---- 引擎 face 正例夹具（与 client.py _terminal_failure_face 键面同形） ---- */
const GOOD_FACE = {
  exec_status: 'FAILED',
  ticket_id: 't260919-01',
  project: 'sandbar',
  epic: 'engine-hardening',
  instance_id: 'integration-tests',
  period: '20260919',
  reason: '套件 boom：integration-tests 第 3 阶段失败',
  reason_available: true,
  reason_source: '来源：Temporal 工作流执行失败信息（终态执行历史回放异常链）',
  snapshot_available: false,
  snapshot_note: '无快照：终态工作流不再运行，snapshot 查询没有执行方承接（终态的确定性结论，不是瞬时故障，刷新无效）',
  last_stage: null,
  last_stage_note: '最后已知阶段不可得：宁缺不猜',
  start_ts: 1758240000,
  close_ts: 1758243600,
  start_time_txt: '09-19 07:30:00',
  close_time_txt: '09-19 08:30:00',
}

console.log('\n== A 全字段装配 ==')
{
  const v = terminalFaceView(GOOD_FACE, '工单已终态（FAILED），快照不可得——终态票不再推进，刷新无效')
  ok(v.execStatus === 'FAILED', '执行状态原文透传')
  ok(v.reasonAvailable === true && v.reason.includes('套件 boom'), '失败原因摘要可得且含引擎串')
  ok(v.reasonNote.includes('Temporal'), '原因来源说明在（正源=Temporal 工作流执行失败信息）')
  ok(v.receiptError.includes('刷新无效'), '回执错误原文随视图（诚实口径锚，不只闪提示条）')
  ok(v.snapshotNote.includes('无快照'), '无快照及为何无说明在')
  ok(v.lastStage === '' && v.lastStageNote !== '', '最后已知阶段不可得显式说明')
  ok(v.ticketId === 't260919-01' && v.instanceId === 'integration-tests' && v.period === '20260919',
    '票身份（票号/巡检实例/期号）在')
  ok(v.startTimeTxt !== '' && v.closeTimeTxt !== '', '起跑/终态时刻在')
}

console.log('\n== B 畸形 face 全降级（不 throw 不编造） ==')
{
  for (const bad of [undefined, null, 42, 'x', [], true]) {
    const v = terminalFaceView(bad, '工单已终态（FAILED）')
    ok(v.reasonAvailable === false && v.reason === '', `face=${JSON.stringify(bad) ?? 'undefined'} → 原因不可得`)
    ok(v.reasonNote.includes('原因不可得'), `face=${JSON.stringify(bad) ?? 'undefined'} → 显式不可得说明`)
    ok(v.snapshotNote === TERMINAL_FACE_FALLBACKS.snapshotNote, `face=${JSON.stringify(bad) ?? 'undefined'} → 快照说明兜底`)
    ok(v.execStatus === '未知', `face=${JSON.stringify(bad) ?? 'undefined'} → 执行状态显未知（不编造）`)
  }
}

console.log('\n== C 反用例：终态但原因不可得（显式文案 + 执行状态保留） ==')
{
  const noReason = { ...GOOD_FACE, reason: '', reason_available: false, reason_source: '原因不可得：失败异常链（WorkflowFailureError）未携带可读消息——不编造原因' }
  const v = terminalFaceView(noReason, '')
  ok(v.reasonAvailable === false && v.reason === '', '反用例：原因空')
  ok(v.reasonNote.includes('原因不可得') && v.reasonNote.includes('不编造'), '反用例：显式「原因不可得」+ 为何')
  ok(v.execStatus === 'FAILED', '反用例：执行状态原文保留（绝不当成没失败）')
  // 半残 face（缺键逐个）→ 逐键兜底不抛
  const v2 = terminalFaceView({ exec_status: 'CANCELED' }, '')
  ok(v2.execStatus === 'CANCELED' && v2.reasonAvailable === false && v2.ticketId === '', '半残 face：有键用键、缺键兜底')
  // 布尔/数字型畸形键值 → 按缺失降级不抛
  const v3 = terminalFaceView({ exec_status: 42, reason: true, reason_available: 'yes', close_time_txt: 7 }, '')
  ok(v3.execStatus === '未知' && v3.reason === '' && v3.reasonAvailable === false && v3.closeTimeTxt === '',
    '畸形键值（数字/布尔/字符串布尔）→ 全按缺失降级')
}

/* ---- E. host 装配（review② 降级分支行为断言） ---- */
console.log('\n== E ticketShowErrorReply：410 分级零回归 + face 只加键不改级 ==')
{
  const good = ticketShowErrorReply({ ok: false, error: '工单已终态（FAILED），快照不可得——终态票不再推进，刷新无效', kind: 'terminal' }, 't-1', GOOD_FACE)
  ok(good.status === 410 && good.body.retryable === undefined, 'terminal + face → 仍 410 不可重试（分级零退化）')
  ok(good.body.face !== undefined && good.body.face.reason.includes('套件 boom'), 'face 附带进 body（UI 有面可渲染）')
  ok(good.body.error.includes('刷新无效'), '「刷新无效」原文在 body（诚实口径零退化）')
  ok(good.body.ok === false && good.body.kind === 'terminal', 'body 骨架不变（ok/kind 原样）')

  for (const bad of [undefined, null, 42, 'x', [], true]) {
    const r = ticketShowErrorReply({ ok: false, error: '工单已终态（FAILED）…刷新无效', kind: 'terminal' }, 't-1', bad)
    ok(r.status === 410, `直读降级 face=${JSON.stringify(bad) ?? 'undefined'} → 仍 410（绝不变 503/不诱导刷新）`)
    ok(!('face' in r.body), `直读降级 face=${JSON.stringify(bad) ?? 'undefined'} → body 无 face 键（UI 降纯错误提示）`)
  }

  const nonTerm = ticketShowErrorReply({ ok: false, error: '查询失败，请刷新重试', kind: 'transient' }, 't-1', GOOD_FACE)
  ok(nonTerm.status === 503 && nonTerm.body.retryable === true, 'transient → 仍 503+retryable（KI-025 零回归）')
  ok(!('face' in nonTerm.body), '非终态 kind 不附带失败面（终态专属语义不扩散）')
  const nf = ticketShowErrorReply({ ok: false, error: '工单不存在：t-1', kind: 'not_found' }, 't-1', GOOD_FACE)
  ok(nf.status === 404 && !('face' in nf.body), 'not_found → 仍 404 无 face')
  const unknown = ticketShowErrorReply({ ok: false, error: '读取失败' }, 't-1', GOOD_FACE)
  ok(unknown.status === 500 && unknown.body.kind === 'internal' && !('face' in unknown.body), 'kind 断链 → 仍 500 internal')
  // verdict 纯函数本体回归（ki025 UT 之外再钉一眼）
  ok(ticketShowHttpVerdict('terminal').status === 410 && ticketShowHttpVerdict('terminal').retryable === false, 'verdict(terminal)=410 不可重试')
}

/* ---- F. 源级锚（防接线被静默拆除/复发） ---- */
console.log('\n== F 源级锚 ==')
const idxSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
const tfSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/terminal-face.ts'), 'utf8')
const nodeSrc = readFileSync(join(repo, 'server/plugins/workbench/node.ts'), 'utf8')

// TerminalFailurePanel 组件体：定位到组件定义→下一个顶层块之间，断言零操作入口。
const panelStart = idxSrc.indexOf('export function TerminalFailurePanel')
ok(panelStart > 0, 'TerminalFailurePanel 组件在源')
const panelEnd = idxSrc.indexOf('/** 编号 section 标题', panelStart)
const panelSrc = idxSrc.slice(panelStart, panelEnd)
ok(panelSrc.includes('data-testid="terminal-failure-panel"'), '面板带渲染断言锚 data-testid')
ok(!panelSrc.includes('onClick'), '面板零 onClick（终态票零操作入口，票面边界）')
ok(!panelSrc.includes('apiPost') && !panelSrc.includes('doOp') && !panelSrc.includes('onAdvance'),
  '面板零写操作/推进入口语义（set-stage/force/resume 一概不给）')
ok(panelSrc.includes('原因不可得') && panelSrc.includes('刷新无效'), '面板显式承载「原因不可得/刷新无效」诚实口径')
ok(panelSrc.includes('view.instanceId'), '巡检实例/期号进面板（票身份验收②）')
ok(!/#[0-9a-fA-F]{3,8}\b/.test(panelSrc.replace(/var\(--[a-z0-9-]+,\s*#?[0-9a-fA-F]*/g, 'var(')),
  '面板 JSX 消费位零裸 hex（色全走令牌 var()）')

ok(idxSrc.includes('{!detailLoading && terminalFace !== null && (\n            <TerminalFailurePanel view={terminalFace} />'),
  '抽屉接线：terminalFace 非空渲染失败面板（绝不空面板）')
ok(idxSrc.includes('setTerminalFace(terminalFaceView('), 'openDetail 捕获 face 装配视图')
ok(idxSrc.includes("e.face = data?.face"), '错误对象挂 face（apiGet 410 返回 body 通路）')
ok((idxSrc.match(/setTerminalFace\(null\)/g) || []).length >= 2, '切单/重开/关抽屉清态（≥2 处，不串票）')
ok(idxSrc.includes("'waiting', 'blocked', 'active', 'failed', 'done'"), 'chips 数组含 failed（五态过滤接线）')
ok(idxSrc.includes(".wb-chip-btn[data-state=failed]") && idxSrc.includes('.wb-root .wb-card[data-state=failed]')
  && idxSrc.includes('.wb-card-dot[data-state=failed]') && idxSrc.includes('.wb-card-state[data-state=failed]'),
  'failed 红系 CSS（chip/行底/点/状态字）在源')
ok(idxSrc.includes('deriveTicketState(t.status, t.stage_state, t.exec_status)'), 'deriveTicketState 调用点传 exec_status')
ok(idxSrc.includes("if (deriveTicketState(t.status, t.stage_state, t.exec_status) === 'failed') return []"),
  'availableOps：失败行零管理操作（终态票零推进入口，行卡面）')

ok(tfSrc.includes('不抛、不编造'), 'terminal-face.ts 纪律声明在源（畸形输入全降级的口径锚）')
ok(tfSrc.includes('reasonAvailable') && tfSrc.includes('TERMINAL_FACE_FALLBACKS'), '视图模型兜底词表单点')

ok(nodeSrc.includes("if ((r as any)?.kind === 'terminal') {"), 'node.ts：terminal 回执才走直读桥')
ok(nodeSrc.includes('fetchTerminalFace(parts[0])'), 'node.ts：直读引擎 ticket-query 取 face')
ok(nodeSrc.includes('sendTicketShowError(res, r, parts[0], face)'), 'node.ts：face 进 410 body')
const tmo = nodeSrc.match(/TERMINAL_FACE_TIMEOUT_MS = ([0-9_]+)/)
ok(tmo !== null && Number(tmo[1].replace(/_/g, '')) <= 8000,
  `直读超时有界（${tmo ? tmo[1] : '?'}ms ≤ 8s，显著小于 UI 详情体验阈值，review④）`)
ok(nodeSrc.includes("['ticket-query', JSON.stringify({ ticket_id: id })]"), '直读走引擎 ticket-query 子命令')
ok(!/console\.log/.test(nodeSrc.slice(nodeSrc.indexOf('function fetchTerminalFace'), nodeSrc.indexOf('function fetchTerminalFace') + 800)), '直读桥零调试残留')

const rowCardSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
ok(rowCardSrc.includes('deriveTicketState(t.status, t.stage_state, t.exec_status)'), '行卡五态推导传 exec_status')
ok(rowCardSrc.includes('exec_status?: string'), '行卡类型补 exec_status')
ok(rowCardSrc.includes('执行状态：'), '行卡悬停 title 带执行状态原文')

console.log(`\nt260919-02-terminal-face ok=${n}`)
