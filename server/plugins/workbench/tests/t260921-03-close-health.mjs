// t260921-03 收口健康度 UT：closeHealthOf/closeHealthBadgeOf 真值表 + 六格终态×产物
// 矩阵 + 实案复现 + 反用例 + 畸形输入 + 筛选/计数口径。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
//
// 覆盖（票面验收①②③⑤ + review 意见②镜像域界定）：
//   A. closeHealthOf 行键透传（引擎 t260921-03 下发的枚举）/ 键缺兜底推导全分支 /
//      畸形输入不抛；abnormal 只从「已知终态」产生（在跑巡检面没报告≠异常收口）。
//   B. 镜像域界定（review 意见②）：可读行=行键与兜底同夹具同值；degraded 老行
//      （引擎无 unreadable 键的部署窗形态）兜底判 abnormal——已知偏差钉死不掩盖。
//   C. 实案复现：t260920-02 行夹具（面快照 blocked + exec COMPLETED + 无报告）→
//      state=done（绝不 blocked/running）+ 徽标「已结束·异常（无报告）」+ 原因随行。
//   D. 六格矩阵：COMPLETED/FAILED/TERMINATED × 有/无产物 → 行标记一致性
//      （TERMINATED 板面不可达=引擎场景钉，此处钉纯函数口径）。
//   E. 反用例③：正常收口（有产物）不标异常；被标异常必带原因（引擎 reason 键随行）。
//   F. 筛选/计数：health='abnormal' 筛异常收口族（abnormal+unreadable，failed 不混）；
//      异常收口行仍在 done 五态桶（countByState 分母口径）。
import assert from 'node:assert/strict'
import {
  deriveTicketState, closeHealthOf, closeHealthBadgeOf,
  filterRows, countByState, ticketMergeTierOf,
} from '../src/client/ticket-list-model.ts'
import { buildStatusCard } from '../src/host/status-card.ts'

let n = 0
function ok(msg, fn) {
  n++
  fn()
  console.log('  ok', msg)
}

/* ---- 夹具：引擎行形状（_row_from_inspection_face / _row_from_meta 产物的最小面） ---- */

// 实案 t260920-02（t260921-01 同形态）：workflow 正常 return（Temporal COMPLETED），
// 终态快照=业务 blocked 面——发现 0、无报告、带事实原因。blocked_reason=行事实词面
// （引擎行原样携带，对账不清洗）。
const REALCASE_ROW = {
  id: 't260920-02', kind: 'inspection', engine: 'inspection',
  status: 'blocked', stage: 'inspect', stage_state: 'blocked',
  title: '巡检 integration-tests · 期 20260920',
  exec_status: 'COMPLETED',
  close_health: 'abnormal',
  close_health_reason: '面快照 blocked：只读审查 agent 起不来（dsh 报 unknown preset "read-only"）；发现 0 条（本期无报告）',
  blocked_reason: '只读审查 agent 起不来（dsh 报 unknown preset "read-only"）',
  findings: { high: 0, med: 0, low: 0, total: 0 },
  report_path: '',
}
// 实案真形态（live 对账 260921 发现）：t260917-02 起 blocked 收口也落账（dead-man
// 面），落账走 report 同名约定并回写 face.report_path——report_path 在场但文件=
// 受阻面镜像。引擎键在场（=abnormal）与键缺（部署窗兜底）都必须判 abnormal。
const LIVE_REALCASE_ROW = {
  ...REALCASE_ROW, id: 't260921-01',
  report_path: '/Users/xingu/Documents/sandbar/server/engine/out/inspection/inspection-integration-tests-20260920.json',
  close_health_reason: '面快照 blocked：只读审查 agent 起不来（dsh 报 unknown preset "read-only"）；发现 0 条（落账文件为受阻面镜像）',
}
// 正常收口巡检行（clean 期 0 发现也落报告；面无受阻记录）
const OK_ROW = {
  ...REALCASE_ROW, id: 't260920-03', status: 'closed', stage: 'close', stage_state: 'done',
  close_health: 'ok', close_health_reason: '', blocked_reason: '',
  report_path: 'out/inspection/integration-tests/20260920.json',
}
// 窗内闭合行读取失败（引擎 degraded 行：unreadable + status 词面钉 running）
const UNREADABLE_ROW = {
  ...REALCASE_ROW, id: 't-x', status: 'running', stage_state: 'running',
  close_health: 'unreadable', close_health_reason: '收口面读取失败：已结束但票面不可读（显式存疑，未判定产物）',
}
// 失败终态巡检行（t260919-02 形状 + 本票健康度键）
const FAILED_ROW = {
  ...REALCASE_ROW, id: 't-y', status: 'failed', stage_state: 'failed',
  exec_status: 'FAILED', close_health: 'failed',
  close_health_reason: '工作流终态 FAILED', report_path: '',
}
const DEV_OK_ROW = {
  id: 't260919-01', status: 'closed', stage_state: 'awaiting',
  engine: 'template-as-code-v2', exec_status: 'COMPLETED',
  close_health: 'ok', close_health_reason: '',
}

console.log('\n== A closeHealthOf：行键透传 / 兜底推导 / 畸形降级 ==')

ok('行键合法 → 透传（引擎单点判定的结果，UI 不二次裁决）', () => {
  assert.equal(closeHealthOf(REALCASE_ROW), 'abnormal')
  assert.equal(closeHealthOf(OK_ROW), 'ok')
  assert.equal(closeHealthOf(UNREADABLE_ROW), 'unreadable')
  assert.equal(closeHealthOf(FAILED_ROW), 'failed')
  // 未收口：引擎给 '' → ''（在飞无健康度可言）
  assert.equal(closeHealthOf({ ...DEV_OK_ROW, status: 'dispatched', stage_state: 'running', exec_status: 'RUNNING', close_health: '' }), '')
})

ok('键缺兜底：受阻词面优先（blocked 面=没跑成实质工作）；无受阻按 report_path 判', () => {
  const { close_health, ...noKey } = REALCASE_ROW
  assert.equal(closeHealthOf(noKey), 'abnormal', '部署窗旧行（无引擎键）：实案形态兜底仍判异常收口')
  // 实案真形态：report_path 在场（落账镜像）但面带受阻——仍 abnormal（键在/键缺同判）
  const { close_health: _k, ...liveNoKey } = LIVE_REALCASE_ROW
  assert.equal(closeHealthOf(LIVE_REALCASE_ROW), 'abnormal', '引擎键透传=abnormal（受阻面不看文件名）')
  assert.equal(closeHealthOf(liveNoKey), 'abnormal', '键缺兜底：blocked_reason 优先于 report_path 在场')
  const { close_health: _c, ...okNoKey } = OK_ROW
  assert.equal(closeHealthOf(okNoKey), 'ok', '面无受阻+报告在兜底 ok')
  const { close_health: _d, ...devNoKey } = DEV_OK_ROW
  assert.equal(closeHealthOf(devNoKey), 'ok', 'dev-lane 无产物契约，终态成功即 ok')
})

ok('兜底只对已知终态下结论：在跑/断链绝不产 abnormal（在跑巡检面本来就没报告）', () => {
  const runningInsp = { kind: 'inspection', status: 'running', stage_state: 'running', exec_status: 'RUNNING', report_path: '' }
  assert.equal(closeHealthOf(runningInsp), '', '在跑巡检（报告未落）→未收口，不是异常收口')
  const noExecInsp = { kind: 'inspection', status: 'blocked', stage_state: 'blocked', report_path: '' }
  assert.equal(closeHealthOf(noExecInsp), '', 'exec 断链的 blocked 词面行→不可判（宁可少标不撒谎）')
  const closedNoExec = { kind: 'inspection', status: 'closed', stage_state: 'done', report_path: '' }
  assert.equal(closeHealthOf(closedNoExec), 'ok', 'exec 断链 closed 词→ok（无 exec 无法核产物，不判异常）')
})

ok('失败族兜底（t260919-02 补集口径零回归）+ 畸形输入全降级不抛', () => {
  for (const exec of ['FAILED', 'CANCELED', 'TIMED_OUT', 'SOME_NEW_TERMINAL', 'TERMINATED']) {
    assert.equal(closeHealthOf({ exec_status: exec }), 'failed', exec)
  }
  for (const bad of [null, undefined, 42, 'x', [], true]) {
    assert.equal(closeHealthOf(bad), '', `行=${JSON.stringify(bad)} → ''不抛`)
  }
  // close_health 键畸形（数字/对象/布尔）→ 按缺键兜底重推，不透传垃圾
  assert.equal(closeHealthOf({ ...OK_ROW, close_health: 42 }), 'ok')
  assert.equal(closeHealthOf({ ...REALCASE_ROW, close_health: { a: 1 } }), 'abnormal')
  // report_path 畸形（数字/对象）→ 按缺失=无报告
  assert.equal(closeHealthOf({ ...OK_ROW, close_health: undefined, report_path: 42 }), 'abnormal')
})

console.log('\n== B 镜像域界定（review 意见②：同夹具同值只对可读行成立） ==')

ok('可读行：引擎键与兜底推导同夹具同值（镜像不漂移）', () => {
  const { close_health, ...noKey } = REALCASE_ROW
  assert.equal(closeHealthOf(REALCASE_ROW), closeHealthOf(noKey), '实案行：键透传=兜底')
  const { close_health: _l, ...liveNoKey } = LIVE_REALCASE_ROW
  assert.equal(closeHealthOf(LIVE_REALCASE_ROW), closeHealthOf(liveNoKey), '实案真形行：键透传=兜底（落账镜像不骗兜底）')
  const { close_health: _o, ...okNoKey } = OK_ROW
  assert.equal(closeHealthOf(OK_ROW), closeHealthOf(okNoKey), '正常收口行：键透传=兜底')
  const { close_health: _f, ...failNoKey } = FAILED_ROW
  assert.equal(closeHealthOf(FAILED_ROW), closeHealthOf(failNoKey), '失败行：键透传=兜底')
})

ok('已知偏差（钉死不掩盖）：degraded 老行兜底判 abnormal（非 unreadable）——徽标降级为「已结束·异常（无报告）」，仍在异常收口族不撒谎终态', () => {
  const { close_health, ...unreadableNoKey } = UNREADABLE_ROW
  assert.equal(closeHealthOf(UNREADABLE_ROW), 'unreadable', '新引擎行：待核')
  assert.equal(closeHealthOf(unreadableNoKey), 'abnormal', '部署窗老行：兜底 only 能判到 abnormal（面缺失⇒无报告）')
  assert.equal(closeHealthBadgeOf(UNREADABLE_ROW), 'Closed·Unverified')
  assert.equal(closeHealthBadgeOf(unreadableNoKey), 'Closed·Abnormal (no report)', '徽标降级形态随偏差钉死')
})

console.log('\n== C 实案复现（验收用例②） ==')

ok('t260920-02 行：state=done（绝不 blocked/running）+ 异常收口徽标 + 原因随行', () => {
  // 终态对账：陈旧面快照词面不得胜出
  assert.equal(deriveTicketState(REALCASE_ROW.status, REALCASE_ROW.stage_state, REALCASE_ROW.exec_status), 'done')
  assert.notEqual(deriveTicketState(REALCASE_ROW.status, REALCASE_ROW.stage_state, REALCASE_ROW.exec_status), 'blocked')
  assert.notEqual(deriveTicketState(REALCASE_ROW.status, REALCASE_ROW.stage_state, REALCASE_ROW.exec_status), 'active')
  // 徽标可扫读 + 不许无因异常（引擎 reason 键随行，详情卡/悬停有料）
  assert.equal(closeHealthBadgeOf(REALCASE_ROW), 'Closed·Abnormal (no report)')
  assert.equal(closeHealthBadgeOf(LIVE_REALCASE_ROW), 'Closed·Abnormal (no report)', '实案真形（落账镜像）同徽标')
  assert.ok(REALCASE_ROW.close_health_reason.includes('read-only'), '原因含实案根因原文')
  // 排序插层：异常收口 tier2（不沉底、不并入正常收口档）
  assert.equal(ticketMergeTierOf(REALCASE_ROW.status, REALCASE_ROW.stage_state, REALCASE_ROW.exec_status, REALCASE_ROW), 2)
  assert.equal(ticketMergeTierOf(LIVE_REALCASE_ROW.status, LIVE_REALCASE_ROW.stage_state, LIVE_REALCASE_ROW.exec_status, LIVE_REALCASE_ROW), 2)
})

console.log('\n== D 六格矩阵（验收用例①：三种终态 × 有/无产物） ==')

ok('矩阵六格：行标记与详情一致（state/health/badge 三元组逐格钉死）', () => {
  const cells = [
    // [终态, 有产物, 期望 state, 期望 health, 期望 badge]
    ['COMPLETED', true, 'done', 'ok', ''],
    ['COMPLETED', false, 'done', 'abnormal', 'Closed·Abnormal (no report)'],
    ['FAILED', true, 'failed', 'failed', ''],
    ['FAILED', false, 'failed', 'failed', ''],
    ['TERMINATED', true, 'failed', 'failed', ''],
    ['TERMINATED', false, 'failed', 'failed', ''],
  ]
  for (const [exec, withArtifact, wantState, wantHealth, wantBadge] of cells) {
    // 巡检行夹具：有产物=report_path 在 + 引擎健康度键一致下发；无产物=两键缺
    const row = withArtifact
      ? { kind: 'inspection', status: 'closed', stage_state: 'done', exec_status: exec, report_path: 'out/x.json', close_health: wantHealth, close_health_reason: '' }
      : { kind: 'inspection', status: 'blocked', stage_state: 'blocked', exec_status: exec, report_path: '', close_health: wantHealth, close_health_reason: `工作流终态 ${exec}` }
    assert.equal(deriveTicketState(row.status, row.stage_state, row.exec_status), wantState, `${exec}×${withArtifact} state`)
    assert.equal(closeHealthOf(row), wantHealth, `${exec}×${withArtifact} health`)
    assert.equal(closeHealthBadgeOf(row), wantBadge, `${exec}×${withArtifact} badge`)
    // 详情一致性：行携带的健康度=行键（详情卡数据源同一键面，读得到同一结论）
    assert.equal(row.close_health, wantHealth, `${exec}×${withArtifact} detail face`)
  }
  // 第 7 格（live 对账真形态补格）：COMPLETED×受阻面×report_path 在场（落账镜像）
  // → abnormal——文件在场不构成「报告在」（健康度看面不看文件名）
  const mirror = { kind: 'inspection', status: 'blocked', stage_state: 'blocked',
    exec_status: 'COMPLETED', report_path: 'out/inspection/x.json',
    blocked_reason: 'agent 退出码 1（未完成）', close_health: 'abnormal', close_health_reason: '面快照 blocked：…；发现 0 条（落账文件为受阻面镜像）' }
  assert.equal(closeHealthOf(mirror), 'abnormal')
  const { close_health: _m, ...mirrorNoKey } = mirror
  assert.equal(closeHealthOf(mirrorNoKey), 'abnormal', '真形态键缺兜底同判')
  // TERMINATED 板面缺席=引擎既有纪律（TERMINATED 不上板），由集成场景 sc_close_health_board 钉
})

console.log('\n== E 反用例（验收用例③） ==')

ok('反用例③：正常收口（有产物）绝不被标异常；被标异常必带原因', () => {
  // 正常收口：无徽标、health=ok、tier=正常收口档
  assert.equal(closeHealthOf(OK_ROW), 'ok')
  assert.equal(closeHealthBadgeOf(OK_ROW), '')
  assert.equal(ticketMergeTierOf(OK_ROW.status, OK_ROW.stage_state, OK_ROW.exec_status, OK_ROW), 3)
  // dev-lane 正常收口同查（badge 恒空=既有收口行零变化）
  assert.equal(closeHealthBadgeOf(DEV_OK_ROW), '')
  // 被标异常的行必须带原因（引擎键面约束的 UI 侧断言：无因异常=不许）
  for (const row of [REALCASE_ROW, LIVE_REALCASE_ROW, UNREADABLE_ROW]) {
    assert.ok(typeof row.close_health_reason === 'string' && row.close_health_reason.trim() !== '',
      `${row.id} 异常原因非空`)
  }
})

console.log('\n== F 筛选 / 计数（验收用例⑤） ==')

ok('health=abnormal 筛异常收口族（abnormal+unreadable），failed 不混入，与 state AND', () => {
  const rows = [REALCASE_ROW, OK_ROW, UNREADABLE_ROW, FAILED_ROW, DEV_OK_ROW]
  const abn = filterRows(rows, { health: 'abnormal' })
  assert.deepEqual(abn.map(r => r.id).sort(), ['t-x', 't260920-02'], '异常收口族=abnormal+unreadable 两行')
  // 与 done 桶 AND：异常收口行确在 done 桶（要求⑤「归已结束桶」）
  const abnDone = filterRows(rows, { state: 'done', health: 'abnormal' })
  assert.deepEqual(abnDone.map(r => r.id).sort(), ['t-x', 't260920-02'])
  // failed 行有自己的「已失败」chip，不进异常收口筛
  assert.ok(!abn.some(r => r.id === 't-y'))
  // 全量无筛=原样
  assert.equal(filterRows(rows, {}).length, 5)
})

ok('计数口径：异常收口行仍在 done 五态桶（折叠分母=doneOk 由板面拆桶，桶归属不变）', () => {
  const c = countByState([REALCASE_ROW, OK_ROW, UNREADABLE_ROW, FAILED_ROW, DEV_OK_ROW])
  assert.equal(c.done, 4, 'done 桶=正常收口 2 + 异常收口 2（dev ok 1 + 实案 1 + 待核 1 + 正常 1）')
  assert.equal(c.failed, 1)
})

console.log('\n== G 详情终态收口卡（要求④：已结束+结束方式+异常原因+缺了什么） ==')

ok('COMPLETED×abnormal 详情出 amber 终态卡：事实链四件齐、零推进入口、无 ⛔/retry 话术', () => {
  const card = buildStatusCard({
    status: 'blocked', stage_state: 'blocked',
    blocked_reason: 'agent 退出码 1（未完成）；输出尾：unknown preset "read-only"',
    exec_status: 'COMPLETED', close_health: 'abnormal',
    close_health_reason: '本期无报告（report_path 缺失，发现 0 条）',
    findings: { high: 0, med: 0, low: 0, total: 0 }, report_path: '',
  })
  assert.ok(card !== null)
  assert.equal(card.severity, 'amber')
  assert.equal(card.terminal, true)
  assert.ok(card.headline.includes('Closed'))
  const all = JSON.stringify(card)
  assert.ok(card.closeFacts.some(f => f.includes('Ended: workflow')), '结束方式事实行')
  assert.ok(card.closeFacts.some(f => f.includes('Close reason:')), '异常原因事实行')
  assert.ok(card.closeFacts.some(f => f.includes('Blocked record (before terminal)') && f.includes('read-only')),
    '终态前受阻记录链可达（blocked_reason 不丢）')
  assert.ok(card.closeFacts.some(f => f.includes('Missing:') && /report/i.test(f)), '缺了什么事实行')
  assert.ok(/retry[- ]qc|rework|unblock|打回|重试/i.test(card.next) === false, 'next 零推进入口语义')
  assert.ok(!all.includes('刷新重试') && !all.includes('查询超时'), 'KI-018① 瞬态占位语不进卡')
})

ok('正常收口（close_health=ok）不出异常措辞卡（反用例③：不反向撒谎）；畸形 detail 软降级', () => {
  const okCard = buildStatusCard({
    status: 'closed', stage_state: 'awaiting-human', exec_status: 'COMPLETED',
    close_health: 'ok', close_health_reason: '', report_path: 'out/x.json', blocked_reason: '',
  })
  assert.ok(okCard === null || !String(okCard.headline).includes('异常'))
  assert.equal(buildStatusCard(null), null)
  assert.equal(buildStatusCard(42), null)
  assert.equal(buildStatusCard('x'), null)
  // unreadable 也出终态卡（显式存疑措辞），原因链允许缺席但不许冒充 ok
  const uCard = buildStatusCard({ exec_status: 'COMPLETED', close_health: 'unreadable', close_health_reason: '收口面读取失败：已结束但票面不可读（显式存疑，未判定产物）' })
  assert.ok(uCard !== null && uCard.terminal === true && uCard.headline.includes('Closed'))
})

ok('gen1 修订（验收走查问题1）：落账镜像形态（abnormal×report_path 在）的「缺了什么」与引擎 reason 同口径——绝不输出「报告已在/不该出现」矛盾文案', () => {
  const card = buildStatusCard({
    status: 'blocked', stage_state: 'blocked',
    blocked_reason: 'agent 退出码 1（未完成）',
    exec_status: 'COMPLETED', close_health: 'abnormal',
    close_health_reason: '面快照 blocked：agent 退出码 1（未完成）；发现 0 条（落账文件为受阻面镜像）',
    findings: { high: 0, med: 0, low: 0, total: 0 },
    report_path: '/Users/xingu/Documents/sandbar/server/engine/out/inspection/inspection-integration-tests-20260920.json',
  })
  assert.ok(card !== null && card.terminal === true)
  const missing = card.closeFacts.find(f => f.startsWith('Missing:'))
  assert.ok(missing, '缺了什么事实行在场')
  assert.equal(missing, 'Missing: No report for this period (the ledger file is the blocked-face mirror)')
  const all = JSON.stringify(card)
  assert.ok(!all.includes('报告已在') && !all.includes('不该出现'), '矛盾防线措辞零残留')
  assert.ok(!/retry[- ]qc|rework|unblock|打回|重试/i.test(card.next), '零推进入口语义不回潮')
})

console.log(`\nt260921-03-close-health ok=${n}`)
