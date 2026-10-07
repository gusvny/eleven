#!/usr/bin/env node
// t261008-08 左栏工单行对齐 mock v11（notes/discussions/261004-concurrency-limit-mock.html
// 的 .tk 行，renderSide）UT：源级锚 + 模型层真值表。
//
// 纪律（同 t260919-02）：渲染断言归集成场景（integration/t261006-18 等）；本文件做
// ①源级锚（改动点逐条锁线，防回归漂移）②消费的 .ts 模型函数畸形输入真值表。
// .tsx 内含 JSX，node 直接 import 不可行（strip-types 不转 JSX），故组件逻辑以源锚
// 承载；悬停组合的畸形输入（progress 缺失/空文本、时间全缺）以 cardTitle 源锚 +
// 相对时间模型畸形输入双重看住。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { relativeTime, stageShortOf } from '../src/client/ticket-list-model.ts'

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
  console.log(`ok ${n} ${msg}`)
}

const card = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
const sidebar = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')

// ---- A. 行面构成（ticket-row-card.tsx 源锚） ----
// A1 彩条：borderLeftColor 行内色只在 !compact 写（mock 的 .tk 无左边条）。
ok(card.includes('style={compact ? undefined : { borderLeftColor: epicColor }}'),
  'A1 borderLeftColor inline colour guarded by !compact (compact rows carry no epic bar)')
ok(!card.includes('style={{ borderLeftColor: epicColor }}'),
  'A1b no unconditional borderLeftColor inline style remains')
// A2 状态英文词：compact 行不再渲染 wb-card-state（状态语义由彩点承载）。
ok(card.includes('!compact && (\n          <span className="wb-card-state"'),
  'A2 the English state word renders only on non-compact rows')
// A3 compact 二行 = 阶段小字 + epic chip；epic chip 一行位仅 !compact。
ok(card.includes('{compact && stageLabel !== \'\' && (\n          <span className="wb-card-stage"'),
  'A3 compact line 2 leads with the small stage label')
ok(card.includes('{compact && t.epic && (\n          <span className="wb-card-epic"'),
  'A3b the epic chip renders on compact line 2 (mock: l2 = stage · epic + dots)')
ok(card.includes('{!compact && t.epic && (\n          <span className="wb-card-epic"'),
  'A3c the board (non-compact) keeps the epic chip on line 1')
// A4 compact 一句进展：默认收进悬停；但父层给了合成进展句的 compact 行（t260915-19
// 巡检行分诊面）保持行面可见（arbitrate gen3 打回项：行面分诊事实不许只活在悬停）。
ok(card.includes('{(!compact || progress) && (\n          <span className="wb-card-progress"'),
  'A4 the progress sentence renders on the board rows and on compact rows carrying a synthesized progress face')
ok(card.includes('{!compact && <span className="wb-card-time">'),
  'A4b the relative time renders only on non-compact rows')
// A5 箭头到行尾：wb-order-ctl 块必须位于标题块之后（DOM 序=视觉序）。
const titleIdx = card.indexOf('data-wb-row-title=')
const ctlIdx = card.indexOf('data-order-ctl=')
ok(titleIdx !== -1 && ctlIdx !== -1 && titleIdx < ctlIdx,
  'A5 ordering controls (grip + arrows) render after the title = at the row end')
const posIdx = card.indexOf('data-order-pos=')
const gripIdx = card.indexOf('data-order-grip=')
ok(posIdx !== -1 && gripIdx !== -1 && posIdx < gripIdx,
  'A5b position number stays first, handgrip right after it')
// A6 悬停收编：cardTitle 带 compact/progress/rel 参数；compact 时收进展句与时间。
ok(/export function cardTitle\(t: CardTicket, wf\?: WfLike \| null, compact = false,\n  progress\?: CardProgress, rel\?: string \| null\)/.test(card),
  'A6 cardTitle takes compact/progress/rel (tooltip absorbs the moved facts)')
ok(card.includes('if (compact && progress?.text) parts.push(progress.text)'),
  'A6b the tooltip absorbs the progress sentence on compact rows (truthy-guarded)')
ok(card.includes('if (t.updated) parts.push(`Updated ${t.updated}`)\n  else if (compact && rel) parts.push(`Updated ${rel}`)'),
  'A6c the tooltip absorbs the updated time on compact rows (absolute first, relative fallback)')

// ---- B. 色条移除（sidebar.tsx 源锚） ----
ok(sidebar.includes('.wb-project-block { border-bottom:1px solid'),
  'B1 the project block carries only a bottom border (mock .proj)')
ok(!sidebar.includes('border-left:3px solid var(--wb-proj-color'),
  'B1b the project block 3px left bar is gone')
ok(/\.wb-sb \.wb-card \{[^}]*border-left-width:0/.test(sidebar),
  'B2 compact rows drop the inherited 4px epic bar (border-left-width:0 override)')
ok(sidebar.includes('.wb-sb .wb-card-stage'),
  'B3 the compact stage small-text rule exists in the sidebar stylesheet')
ok(sidebar.includes('flex:none; margin-left:auto; }') && sidebar.includes('t261008-08 (mock v11)'),
  'B4 the ordering controls push to the row end (margin-left:auto)')

// ---- C. 畸形输入真值表（模型层，卡片悬停的数据源） ----
// relativeTime：畸形/缺省输入绝不 throw、绝不编造时间（悬停兜底路径依赖此纪律）。
for (const bad of [undefined, null, NaN, 0, -1, 'not-a-number', Number.MAX_SAFE_INTEGER + 1]) {
  const out = relativeTime(bad)
  ok(out === null || typeof out === 'string',
    `C relativeTime(${String(bad)}) degrades to null/string, never throws (got ${JSON.stringify(out)})`)
}
// stageShortOf：畸形拓扑输入降级短名，不 throw（compact 二行小字与悬停同源）。
for (const bad of [undefined, null, {}, { short: 42 }, { short: '' }]) {
  const out = stageShortOf(bad)
  ok(typeof out === 'string' || out === undefined,
    `C stageShortOf(${JSON.stringify(bad)}) degrades to string/undefined, never throws`)
}

console.log(`T261008-08 left-column-row-mock UT: ${n} assertions green`)
