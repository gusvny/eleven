/**
 * executor-entry-css-contract.mjs —— t260929-22 gen1 可达性修的布局契约锁：
 * 执行器入口（项目行）在普通窗口宽度（1280×720，sidebar ≈237px）必须可读可点。
 *
 * 背景（acceptance 打回实证）：入口段与五个视图图标共挤一行 237px——图标簇 138px
 * 把项目名挤成 0 宽、行中部点击落在图标上（图标 wrapper stopPropagation 吞掉）。
 * 修法：入口段=名字+计数+弹性空档（flex:1 1 0 吃掉非图标区）+ 图标命中区 26→20px。
 * 本测以源级契约锁住几何前提（源级锚=布局是 JSX+CSS 常量的单点；浏览器几何归
 * 集成场景 t260929-22-executor-entry-console 的 E1/E2 实测）：
 *   C1 入口段规则在场且弹性吃满非图标区（flex:1 1 0 + min-width:0）；
 *   C2 图标命中区 ≤20px（几何预算：簇 ≤110px，入口段在 237px 行内 ≥80px，
 *      行中部点击必落入口段）；
 *   C3 入口段包住名字与计数、且位于图标簇之前（空档属于入口）；
 *   C4 行本体与 caret 各司其职：行不挂 onClick（不双动作）、caret stopPropagation。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const repo = process.cwd()
const src = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
let n = 0

// C1 入口段弹性规则
assert(/\.wb-group-entry \{ flex:1 1 0; min-width:0;/.test(src), `C1 entry-zone flex rule present (${++n})`)

// C2 图标命中区几何预算（≤20px）
{
  const m = src.match(/\.wb-view-icon \{ width:(\d+)px; height:(\d+)px;/)
  assert(m, `C2 view-icon rule found (${++n})`)
  assert(Number(m[1]) <= 20 && Number(m[2]) <= 20, `C2 icon hit area <=20px (got ${m[1]}x${m[2]}) (${++n})`)
}

// C3 入口段包住名字+计数、先于图标簇（同一组头块内序）
{
  const head = src.indexOf('<span className="wb-group-entry" data-wb-executor-entry=""')
  assert(head > 0, `C3 entry span present (${++n})`)
  const icons = src.indexOf('<span className="wb-view-icons"', head)
  assert(icons > 0, `C3 icons cluster after entry (${++n})`)
  const block = src.slice(head, icons)
  assert(block.includes('wb-group-name') && block.includes('wb-group-count'),
    `C3 entry wraps name and count (${++n})`)
}

// C4 行本体不挂 onClick（动作只在入口段与图标，防一次点击双动作）
{
  const headRow = src.match(/<div className="wb-group-head"[^>]*>/)
  assert(headRow && !headRow[0].includes('onClick'), `C4 head row has no onClick (${++n})`)
  const caret = src.match(/wb-group-caret" title=\{collapsed\[g\.project\.key\] \? 'Expand' : 'Collapse'\}\s*\n\s*onClick=\{\(e\) => \{ e\.stopPropagation\(\);/)
  assert(caret, `C4 caret owns collapse with stopPropagation (${++n})`)
}

console.log(`done ${n}`)
