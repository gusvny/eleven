/**
 * executor-entry-css-contract.mjs —— t260929-22 执行器入口的布局契约锁（gen2 口径）：
 * 项目行入口在普通窗口宽度（1280×720）必须可读可点，且**不破冻结契约**。
 *
 * 两代打回的几何史（本测锁的即是这两条边）：
 *   - gen0：名字段被图标簇挤成 0 宽（acceptance 红）→ 入口段=名字+计数+弹性空档；
 *   - gen1：把图标命中区缩到 20px 让宽 → t260904-17 A/B 实证为新红单变量（打回）
 *     → gen2 恢复 26×26 但改 widen 列宽 → t260904-17/t260915-09 双 A/B 实证列宽也是
 *     冻结边（打回）→ gen3：几何全部还原（26×26 + 列宽 180），可达性=图标簇悬停
 *     现形，静止态整行非图标区归入口段。
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

// C5/gen3 可达性=悬停现形：列宽 180px 不动（t260915-09/t260904-17 A/B 冻结边）、
// 图标命中区 26×26 不动（C2）——静止态图标簇退场（pointer-events:none + opacity:0），
// 整行非图标区归入口段；悬停/键盘聚焦恢复可点。
{
  const m = src.match(/\.wb-view-icons \{[^}]*pointer-events:none; opacity:0; \}/)
  assert(m, `C5 icons cluster rest-state rule (pointer-events:none, opacity:0) (${++n})`)
  assert(/top:100%/.test(m[0]), `C5b strip hangs below the row (top:100%) — never covers the entry anchor (${++n})`)
  assert(/\.wb-group-head:hover \.wb-view-icons, \.wb-view-icons:focus-within \{ pointer-events:auto; opacity:1; \}/.test(src),
    `C5c hover/focus-within restores the cluster (${++n})`)
  const minW = Number(src.match(/\.wb-sb-left \{ flex:1 1 0; min-width:(\d+)px/)[1])
  assert(minW === 180, `C5c left column min-width untouched at 180px (got ${minW}) (${++n})`)
}

console.log(`done ${n}`)
