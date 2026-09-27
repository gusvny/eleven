// t260926-05 巡检报告面纯函数层 UT（src/client/inspection-report-model.ts 真值表）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
// 覆盖：asText 安全文本 / suiteSectionView 真值表（全量/老形态/畸形/null）/
// faceRows（curated+未知键透传+畸形）/ reportDigest（嵌套/数组/环引用/截断）/
// findingView（畸形发现项/非对象证据）——外加全输出零 `[object Object]` 全局断言
// （工单验收②③的机械执行点）。
import assert from 'node:assert/strict'
import {
  asText, suiteSectionView, faceRows, reportDigest, findingView,
} from '../src/client/inspection-report-model.ts'

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

// 收集一切产出的文本，末尾全局断言零 `[object Object]`（任何一条漏防=红）。
const allText = []
const collect = (v) => { allText.push(typeof v === 'string' ? v : JSON.stringify(v)) }

// ---- asText：安全文本契约 ----
ok(asText('abc') === 'abc', '字符串原样')
ok(asText(42) === '42' && asText(true) === 'true', '数字/布尔 String')
ok(asText(null) === '' && asText(undefined) === '', 'null/undefined 空串')
ok(asText({ a: 1 }) === '{"a":1}', '对象走紧凑 JSON')
ok(asText(['x', 1]) === '["x",1]', '数组走紧凑 JSON')
ok(asText('x'.repeat(500)).length === 401 && asText('x'.repeat(500)).endsWith('…'), '超长截断带省略号')
const cyc = {}; cyc.self = cyc
ok(asText(cyc) !== '' && !asText(cyc).includes('[object Object]'), '环引用不炸不产出 [object Object]')

// ---- suiteSectionView：全量形状 ----
const full = {
  ok: true, error: '', ran: 319, passed: 300, failed: 15, env_fail: 4,
  wall_seconds: 2630.5, supply_used_sec: 800.25, runner_used_sec: 3000.75,
  run_budget_sec: 6600, supply_timeout_sec: 3600,
  worktree: '.lane/t260927', base_ref: 'abc123', report_path: '/r/out/inspection/x-suite.json',
  blockers: ['budget exhausted'], cases: [{ name: 'sc_a', exit: 0 }, { name: 'sc_b', exit: 1 }],
}
const svFull = suiteSectionView(full)
collect(svFull)
const flat = svFull.rows.map(r => `${r.label}=${r.value}`)
ok(flat.some(x => x.startsWith('Suite ok=yes')), '全量形态 ok 行')
ok(flat.some(x => x.startsWith('Ran=319')), 'ran 计数行')
ok(flat.some(x => x.startsWith('Supply phase wall clock (supply_used_sec)=800.25')), '供给段分相墙钟行')
ok(flat.some(x => x.startsWith('Runner phase wall clock (runner_used_sec)=3000.75')), '跑者段分相墙钟行')
ok(flat.some(x => x.startsWith('Runner budget (run_budget_sec)=6600')), '跑者预算行')
ok(flat.some(x => x.startsWith('Base ref=abc123')), 'base_ref 行')
ok(!flat.some(x => x.startsWith('Suite timeout')), '非超时形态无超时行')
ok(svFull.blockers.length === 1 && svFull.blockers[0] === 'budget exhausted', 'blockers 透传')
ok(svFull.cases.length === 2 && svFull.cases[0].name === 'sc_a' && svFull.cases[0].exit === '0', '逐场景红绿透传')

// ---- suiteSectionView：260927 三态（超时+迟到） ----
const svLate = suiteSectionView({ ok: false, ran: 0, passed: 0, failed: 0, env_fail: 0, suite_timeout: true, suite_timeout_sec: 10800, late: true, late_error: 'orphan wrote -suite-late.json' })
collect(svLate)
const lateFlat = svLate.rows.map(r => `${r.label}=${r.value}`)
ok(lateFlat.some(x => x.startsWith('Suite timeout=YES')), '超时行 warn 形态')
ok(lateFlat.some(x => x.startsWith('Late receipt=YES')), '迟到回执行')
ok(svLate.rows.find(r => r.label === 'Suite timeout')?.warn === true, '超时行带 warn 标记')
ok(svLate.rows.find(r => r.label === 'Late receipt')?.warn === true, '迟到行带 warn 标记')
ok(lateFlat.some(x => x.includes('-suite-late.json')), '迟到 error 细节透传')

// ---- suiteSectionView：老形态缺新键 / 计数缺键给 '—' ----
const svOld = suiteSectionView({ ok: true, ran: 5, passed: 5, failed: 0, env_fail: 0 })
collect(svOld)
ok(svOld.rows.some(r => r.label === 'Ran' && r.value === '5'), '老形态计数在')
ok(!svOld.rows.some(r => r.label === 'Wall clock (supply phase)'), '老形态缺分相墙钟=不加空行')
const svGap = suiteSectionView({ ok: true })
ok(svGap.rows.find(r => r.label === 'Ran')?.value === '—', '计数键缺=显式 — 不静默')

// ---- suiteSectionView：畸形 / null ----
collect(suiteSectionView('garbage'))
collect(suiteSectionView(123))
collect(suiteSectionView([{ name: 'x' }]))
ok(suiteSectionView('garbage').rows.length === 1 && suiteSectionView('garbage').rows[0].value === 'garbage', '非 dict 形状=单行安全文本')
ok(suiteSectionView(null).rows.length === 0, 'null=零行（段整体隐藏）')
const svMad = suiteSectionView({ ok: false, ran: 1, failed: 0, env_fail: 0, blockers: [null, { deep: true }], cases: ['raw-string', { name: { nested: 1 }, exit: null }] })
collect(svMad)
ok(svMad.blockers.every(b => typeof b === 'string' && b.length > 0), 'blockers 畸形项安全文本化')
ok(svMad.cases.every(c => typeof c.name === 'string'), 'cases 畸形项安全文本化')

// ---- faceRows：curated + 未知键透传 + 专属性键不重复 ----
const detail = {
  id: 't26092801', kind: 'inspection', instance_id: 'i', period: 'p',
  findings: [], timeline: [], red_line: 'rl', report_path: '/x.json', suite: {},
  budget_note: 'used 95% of inspect budget', heartbeat_note: '全绿期',
  scan_meta: { files: 12 }, redirect: null, future_engine_key: { deep: { deeper: 1 } },
  engine: 'inspection', stage: 'report',
}
const fr = faceRows(detail)
collect(fr)
const frLabels = fr.map(r => r.label)
ok(frLabels.includes('Budget note') && frLabels.includes('Heartbeat note') && frLabels.includes('Scan meta'), 'curated 三键在')
ok(!frLabels.includes('Redirect'), 'redirect 空=不出空行')
ok(frLabels.includes('future_engine_key'), '未知键透传（引擎未来加键自动可读）')
ok(!frLabels.includes('findings') && !frLabels.includes('red_line') && !frLabels.includes('engine'), '专属性键不出泛化行')
ok(fr.find(r => r.label === 'Scan meta').value === '{"files":12}', '对象值走紧凑 JSON')
ok(fr.find(r => r.label === 'future_engine_key').value === '{"deep":{"deeper":1}}', '深嵌值走紧凑 JSON 不丢')
ok(faceRows(null).length === 0 && faceRows('x').length === 0 && faceRows([1]).length === 0, '畸形 detail=空表不炸')
ok(faceRows({ redirect: { from: 'a', to: 'b' } }).some(r => r.label === 'Redirect' && r.value.includes('"to":"b"')), 'redirect 非空时出对象行')

// ---- reportDigest：嵌套/数组/标量根/环引用/行数封顶 ----
const dg = reportDigest({ kind: 'inspection', period: 'p', findings: [{ severity: 'high', evidence: [{ path: 'a.ts', line: 3 }] }], empty: {}, nul: null })
collect(dg)
ok(dg[0].depth === 0 && dg[0].text === 'kind: inspection', '根层平铺 label: value')
ok(dg.some(l => l.text === 'severity: high'), '嵌套键平铺')
ok(dg.some(l => l.text === '[0]: {2 keys}' || l.text.includes('entries')), '数组/对象计数行')
ok(dg.some(l => l.text === 'path: a.ts') && dg.some(l => l.text === 'line: 3'), '证据字段平铺')
ok(dg.some(l => l.text.includes('(empty)')), '空对象显式点名')
const dgArr = reportDigest([1, 'two'])
ok(dgArr.some(l => l.text.includes('2 entries')) && dgArr.some(l => l.text === '[1]: two'), '数组根可读')
collect(reportDigest('plain'))
ok(reportDigest('plain').length === 1 && reportDigest('plain')[0].text === 'report: plain', '标量根兜底')
const digCyc = { a: 1 }; digCyc.me = digCyc
const dgCycLines = reportDigest(digCyc)
collect(dgCycLines)
ok(dgCycLines.some(l => l.text.includes('circular')), '环引用显式点名不炸')
const dgBig = reportDigest({ a: 1, b: 2, c: 3, d: 4, e: 5 }, 3)
collect(dgBig)
ok(dgBig.length <= 4 && dgBig.some(l => l.text.includes('truncated')), '行数封顶显式截断点名')

// ---- findingView：正常/畸形/非对象证据 ----
const fvOk = findingView({ severity: 'high', scan: 'deadman', confidence: 0.9, verified: 'yes', subject: 'S', why: 'W', suggestion: 'Fix', evidence: [{ path: 'a.ts', line: 3, quote: 'q' }, 'raw-entry', { line: 7 }] }, 0)
collect(fvOk)
ok(fvOk.fallback === undefined, '对象发现项无 fallback')
ok(fvOk.sev === 'high' && fvOk.scan === 'deadman' && fvOk.subject === 'S', '核心字段透传')
ok(fvOk.confidence === '0.9' && fvOk.verified === 'yes', 'confidence/verified 文本化')
ok(fvOk.evidence[0].loc === 'a.ts:3' && fvOk.evidence[0].quote === 'q', '证据 path:line + quote')
ok(fvOk.evidence[1].loc === 'raw-entry' && fvOk.evidence[1].quote === '', '非对象证据条目安全文本')
ok(fvOk.evidence[2].loc === ':7', '缺 path 的证据条目只给 line（可读不炸）')
const fvStr = findingView('just-a-string', 2)
ok(fvStr.fallback === 'Finding 2: just-a-string', '字符串发现项回退行')
collect(findingView(['arr', 'finding'], 3))
ok(findingView(['arr', 'finding'], 3).fallback.includes('arr'), '数组发现项回退行')
const fvNull = findingView(null, 4)
ok(fvNull.fallback === 'Finding 4: (empty entry)', 'null 发现项回退行')
const fvEv = findingView({ severity: 'low', evidence: { not: 'an array' } }, 5)
ok(fvEv.evidenceFallback === '{"not":"an array"}', '非数组 evidence 走 evidenceFallback')
collect(findingView({ evidence: [[1], null, 5] }, 6))
ok(findingView({ evidence: [[1], null, 5] }, 6).evidence.length === 3, '畸形证据条目逐条可读')

// ---- 全局：任何产出零 `[object Object]` ----
ok(!allText.some(t => t && t.includes('[object Object]')), `全输出零 [object Object]（收集 ${allText.length} 条）`)

console.log(`t260926-05-inspection-report-model: ${n} checks pass`)
