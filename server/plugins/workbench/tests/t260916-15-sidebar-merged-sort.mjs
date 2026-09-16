// t260916-15 左栏合并排序 UT：ticket-list-model 排序纯函数真值表 + 畸形输入 + 源级锚。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
//
// 口径（派发规格验收① + review 意见①③钉死项）：
//   tier 投影复用 deriveTicketState 四态单点：waiting|blocked→0（在等你/受阻）、
//   active→1（在跑）、done→2（已完成）；级内 updated_ts 倒序（引擎行=秒级，两数据
//   源同单位，直接比原始值——见 ticketSortTsOf 注释）；同 ts 保输入序（显式 index
//   兜底）。缺省行显式钉死：未知/未来 stage_state→tier1（「宁显活跃」缺省继承）、
//   'awaiting'→tier1——防未来被当意外行为或悄悄改口径。
// 渲染断言归属（KI-055/t260915-17 纪律）：本文件只锁纯函数真值表 + 源级锚；
//   真浏览器渲染断言（徽标可命中/可见/行序）归 integration/t260916-15 场景 S1。
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ticketMergeTierOf, ticketSortTsOf, sortMergedTickets,
} from '../src/client/ticket-list-model.ts'

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
}

/* ---- ticketMergeTierOf 真值表（四态 + review 意见①两缺省行） ---- */
ok(ticketMergeTierOf('dispatched', 'awaiting-human') === 0, '等你（awaiting-human）→tier0')
ok(ticketMergeTierOf('dispatched', 'blocked') === 0, '受阻（blocked）→tier0')
ok(ticketMergeTierOf('dispatched', 'running') === 1, '在跑（running）→tier1')
ok(ticketMergeTierOf('dispatched', 'awaiting') === 1, '缺省钉死：awaiting（等段间推进）→tier1')
ok(ticketMergeTierOf('dispatched', 'some-future-state') === 1, '缺省钉死：未知/未来 stage_state→tier1（宁显活跃）')
ok(ticketMergeTierOf('dispatched', undefined) === 1 && ticketMergeTierOf('dispatched', '') === 1, '缺省钉死：stage_state 缺/空→tier1')
ok(ticketMergeTierOf('closed', 'awaiting') === 2 && ticketMergeTierOf('closed', 'running') === 2, 'closed 优先→tier2（收口层，stage_state 不翻案）')
ok(ticketMergeTierOf('running', 'running') === 1, '降级闭合行（引擎钉 status=running）→tier1 不进收口层（08 UT 同口径）')
ok(ticketMergeTierOf(123, null) === 1 && ticketMergeTierOf(undefined, undefined) === 1, '畸形/缺参→tier1 缺省不抛')

/* ---- ticketSortTsOf（防御链 + 秒级单位直接比） ---- */
const T = 1789354800
ok(ticketSortTsOf({ updated_ts: T, created: 1, close_ts: 2 }) === T, 'updated_ts 优先')
ok(ticketSortTsOf({ created: T + 1, close_ts: T + 2 }) === T + 1, 'updated_ts 缺→created')
ok(ticketSortTsOf({ close_ts: T + 2 }) === T + 2, '仅 close_ts→close_ts')
ok(ticketSortTsOf({ updated_ts: 'x', created: NaN, close_ts: T }) === T, '非有限数逐级回落不产 NaN')
ok(ticketSortTsOf({ updated_ts: 0, created: -5, close_ts: null }) === 0, '≤0/null 视畸形，全缺→0')
ok(ticketSortTsOf({}) === 0 && ticketSortTsOf(null) === 0 && ticketSortTsOf(undefined) === 0, '空对象/null/undefined→0 不抛')
ok(ticketSortTsOf('x') === 0 && ticketSortTsOf(42) === 0, '行非对象→0 不抛')

/* ---- sortMergedTickets：混排真值表（验收①主断言面） ---- */
// 输入=旧拼接序（dev 行在前、巡检行在后，各组内乱序）——改前巡检恒尾、改后按口径混排。
const dev = (id, status, stageState, ts, over = {}) => ({ id, status, stage_state: stageState, updated_ts: ts, kind: 'dev', ...over })
const ins = (id, status, stageState, ts, over = {}) => ({ id, status, stage_state: stageState, updated_ts: ts, kind: 'inspection', ...over })
const mixed = [
  dev('dev-run', 'dispatched', 'running', T),            // 在跑（ts 中）
  dev('dev-wait', 'dispatched', 'awaiting-human', T + 7200), // 等你（ts 较新）
  ins('ins-wait', 'dispatched', 'awaiting-human', T + 14400), // 巡检等你（等你层最新 → 应组首=反沉底主角）
  dev('dev-done', 'closed', 'awaiting', T + 999_999),    // 已收口（updated_ts 全场最新 → 仍须沉底）
  ins('ins-run', 'dispatched', 'running', T - 3600),     // 巡检在跑（在跑层最老 → 层内垫底）
]
const sorted = sortMergedTickets(mixed)
ok(sorted.map(r => r.id).join(',') === 'ins-wait,dev-wait,dev-run,ins-run,dev-done',
  `混排全序=等你层(级内倒序)→在跑层(级内倒序)→收口层，实得 ${sorted.map(r => r.id).join(',')}`)
ok(sorted.findIndex(r => r.id === 'ins-wait') < sorted.findIndex(r => r.id === 'dev-run'),
  '反沉底核心面：巡检等你行排在 dev 在跑行之前（数据来源不决定位置）')
ok(sorted.findIndex(r => r.id === 'dev-done') === sorted.length - 1,
  '收口行 updated_ts 全场最新仍沉底（tier 优先于时间）')
ok(mixed[0].id === 'dev-run' && mixed[4].id === 'ins-run', '输入数组不被 mutate（浅拷贝排序）')

// 同 ts 平级=输入序（显式 index 兜底；输入序=dev 前、巡检后）
const tie = sortMergedTickets([
  dev('a-dev', 'dispatched', 'awaiting-human', T),
  ins('a-ins', 'dispatched', 'awaiting-human', T),
  ins('b-ins', 'dispatched', 'awaiting-human', T),
])
ok(tie.map(r => r.id).join(',') === 'a-dev,a-ins,b-ins', '同层同 ts 保输入序（确定性兜底）')

// 时间源回落：updated_ts 缺 → created 递补
const fallback = sortMergedTickets([
  dev('old', 'dispatched', 'running', undefined, { created: T }),
  dev('new', 'dispatched', 'running', undefined, { created: T + 60 }),
])
ok(fallback.map(r => r.id).join(',') === 'new,old', 'updated_ts 缺→created 递补倒序')

// 畸形输入不抛不崩：null/非对象元素沉底，全畸形数组返回等长数组
const malformed = sortMergedTickets([null, 'x', 42, ins('ok-ins', 'dispatched', 'awaiting-human', T)])
ok(malformed.length === 4 && malformed[0].id === 'ok-ins', 'null/非对象元素不抛、正常行仍居首')
ok(JSON.stringify(sortMergedTickets([])) === '[]', '空数组→空数组')
const one = sortMergedTickets([ins('solo', 'dispatched', 'running', T)])
ok(one.length === 1 && one[0].id === 'solo', '单行→原样')

/* ---- 源级锚（KI-051：语义锚；防接线被静默拆除） ---- */
const sbSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
ok(/tickets:\s*sortMergedTickets\(/.test(sbSrc), 'groups memo 拼接后过 sortMergedTickets（合并排序接线在源）')
ok(sbSrc.includes('sortMergedTickets(inspectionSplit.unowned)'), '兜底组同口径排序接线在源')
ok(sbSrc.includes('kindBadge={insp ? { text: INSPECTION_ROW_BADGE } : undefined}'), '项目组巡检行传类别徽标')
ok(sbSrc.includes("kindBadge={{ text: INSPECTION_ROW_BADGE }}"), '兜底组行传类别徽标')
ok(sbSrc.includes('.wb-sb .wb-card-kind'), '徽标 chip 样式作用域 .wb-sb（中列零影响）在源')
ok(sbSrc.includes('驻留窗分工'), '巡检行不经 inSandbar 窗的两窗分工声明保留（t260915-19 UT 锚不丢）')
ok(!sbSrc.includes('并进对应组尾部'), '旧「组尾部」契约措辞已随行为变更清除（防死注释）')

const cardSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
ok(cardSrc.includes('data-kind-badge={kindBadge.text}'), '行卡发射 data-kind-badge（渲染断言选择器锚）')
ok(cardSrc.includes('kindBadge?: { text: string }'), 'kindBadge=通用 prop（文本由父层给）')
ok(!cardSrc.includes('inspection'), 'ticket-row-card 仍零 inspection 专属词（t260915-08 守卫边界保持）')

const faceSrc = readFileSync(join(repo, 'server/plugins/workbench/src/host/inspection-face.ts'), 'utf8')
ok(faceSrc.includes("export const INSPECTION_ROW_BADGE = '巡检'"), '徽标词表单点在 host 层')
ok(!/const INSPECTION_ROW_BADGE\s*=/.test(sbSrc), '侧栏不本地定义徽标词（走单点 import）')

const modelSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-list-model.ts'), 'utf8')
ok(modelSrc.includes('全是**秒**'), '排序时间源单位口径（秒）钉在 doc 注释（review 意见③）')
ok(/index 兜底/.test(modelSrc), '同 ts 显式 index 兜底声明在源')

console.log(`t260916-15-sidebar-merged-sort ok=${n}`)
