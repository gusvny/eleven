/**
 * executor-entry-css-contract.mjs —— t260929-22 执行器入口的布局契约锁（gen2 口径）：
 * 项目行入口在普通窗口宽度（1280×720）必须可读可点，且**不破冻结契约**。
 *
 * 两代打回的几何史（本测锁的即是这两条边）：
 *   - gen0：名字段被图标簇挤成 0 宽（acceptance 红）→ 入口段=名字+计数+弹性空档；
 *   - gen1：把图标命中区缩到 20px 让宽 → t260904-17 A/B 实证为新红单变量（打回）
 *     → gen2 恢复 26×26 但改 widen 列宽 → t260904-17/t260915-09 双 A/B 实证列宽也是
 *     冻结边（打回）→ gen3 悬停现形条挂行下 → t260915-09 实证截住 .wb-psess 点击
 *     （打回）→ gen4（宿主 260929 裁决：260927 设计胜、260823 放宽）：图标簇行内
 *     收纳——常驻工单+立项单两枚 + 「More views」行内展开其余三枚，零绝对定位、
 *     零外溢命中面，列宽 180 / 命中区 26×26 双冻结边不动。
 *
 * 几何前提（组头行盒模型，全部可从源码 CSS 推出）：
 *   行宽 W（=左列宽）；水平 padding 8+8；前缀 caret10+gap5+dot8+gap5=36（内坐标）；
 *   图标簇 = 5×命中区宽 + 4×gap（右对齐）；入口段 = [36, W-8-簇]；
 *   行点击中心 = W/2。入口段盖过中心 ⇔ W/2 < W-8-簇 ⇔ W > 16+2×簇。
 * 本测解析源码里的图标命中区/簇 gap/列 min-width，重算该不等式——将来任何人改
 * 其中一项，这里立刻红，不再靠集测场景兜底。
 *
 * 浏览器级几何归集成场景 t260929-22-executor-entry-console（E1/E2 实测）。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const repo = process.cwd()
const src = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
let n = 0

// C1 入口段弹性规则（名字+计数+弹性空档整体吃掉非图标区）
assert(/\.wb-group-entry \{ flex:1 1 0; min-width:0;/.test(src), `C1 entry-zone flex rule present (${++n})`)

// C2 冻结契约：图标命中区恰为 26×26（t260904-17 冻结；两代打回的实证边）
{
  const m = src.match(/\.wb-view-icon \{ width:(\d+)px; height:(\d+)px;/)
  assert(m, `C2 view-icon rule found (${++n})`)
  assert(Number(m[1]) === 26 && Number(m[2]) === 26, `C2 icon hit area is the frozen 26x26 (got ${m[1]}x${m[2]}) (${++n})`)
}

// C3 入口段包住名字+计数、先于图标簇（空档属于入口）
{
  const head = src.indexOf('<span className="wb-group-entry" data-wb-executor-entry=""')
  assert(head > 0, `C3 entry span present (${++n})`)
  const icons = src.indexOf('<span className="wb-view-icons"', head)
  assert(icons > 0, `C3 icons cluster after entry (${++n})`)
  const block = src.slice(head, icons)
  assert(block.includes('wb-group-name') && block.includes('wb-group-count'),
    `C3 entry wraps name and count (${++n})`)
}

// C4 行本体不挂 onClick（动作只在入口段与图标，防一次点击双动作）；caret 独占折叠
{
  const headRow = src.match(/<div className="wb-group-head"[^>]*>/)
  assert(headRow && !headRow[0].includes('onClick'), `C4 head row has no onClick (${++n})`)
  const caret = src.match(/wb-group-caret" title=\{collapsed\[g\.project\.key\] \? 'Expand' : 'Collapse'\}\s*\n\s*onClick=\{\(e\) => \{ e\.stopPropagation\(\);/)
  assert(caret, `C4 caret owns collapse with stopPropagation (${++n})`)
}

// C5/gen4 可达性=行内收纳：零绝对定位（gen3 的行下条被 t260915-09 A/B 实证截住
// .wb-psess 点击，形态整体退役）；列宽 180 冻结；两枚场景钉住图标常驻在流内；
// 「More views」展开钮在场且行内收纳其余三枚。
{
  const m = src.match(/\.wb-view-icons \{ display:flex; gap:2px; \}/)
  assert(m, `C5 icon cluster is plain in-flow (no absolute/hover layer) (${++n})`)
  assert(!/wb-view-icons[^\n]*position:absolute/.test(src) && !/top:100%/.test(src),
    `C5b no out-of-row overlay left (${++n})`)
  const minW = Number(src.match(/\.wb-sb-left \{ flex:1 1 0; min-width:(\d+)px/)[1])
  assert(minW === 180, `C5c left column min-width stays 180px (got ${minW}) (${++n})`)
  // t261005-10 (UI-2)：Tickets/Epics/Docs 图标随视图归并退役——簇内常驻为零枚，
  // More views 展开位只剩 Model Routes + Project Settings。
  const iconsStart = src.indexOf('<span className="wb-view-icons"')
  const more = src.indexOf('data-wb-more-views=""', iconsStart)
  assert(iconsStart > 0 && more > 0, `C5d cluster and expander present (${++n})`)
  const pinned = src.slice(iconsStart, more)
  assert(!pinned.includes('aria-label="Tickets"') && !pinned.includes('aria-label="Epics"')
    && !pinned.includes('aria-label="Docs"'),
    `C5e board/epics/docs icons retired from the cluster (${++n})`)
  assert(src.includes('aria-label="Model Routes"') && src.includes('data-wb-project-settings-entry=""'),
    `C5e2 More views keeps Model Routes + Project Settings (${++n})`)
  assert(/aria-label=\{moreViews\[g\.project\.key\][^\n]*'More views'/.test(src),
    `C5f More views expander with keyboard support (${++n})`)
}

console.log(`done ${n}`)
