/**
 * t261008-05-overlay-host-height-contract.mjs —— 中列 overlay 宿主高度链契约锁
 * （developer L1，纯 node 源码解析，秒级；浏览器 computed layout 归集成场景
 * t261008-05-executor-panel-height-chain，两层各管各的，本测不冒充像素层）。
 *
 * 缺陷史（本测锁的边）：t261005-10（UI-2）把 overlay + 机器状态头宿主放成中列里
 * 面板视图的**兄弟块**后，宿主仍吃到遗留全局 .wb-root 规则的 height:100% 与
 * min-height:100%（index.tsx）——对 flex:none 的 flex 项，二者都按中列的确定高度
 * 解析，宿主占满整列，.wb-executor-view（flex:1 1 0%; min-height:0）归零，iframe
 * 落回 150px 替换元素默认值并外溢。修复（t261008-05）=兄弟选择器上同时给
 * height:auto 与 min-height:0——只给 min-height:0 不够：flex-basis:auto 会先吃
 * height:100%。遗留全局规则**有意不改**（仍以 .wb-root 为全高根的视图依赖它）。
 *
 * 借用纪律（C-cond-1，review 条款）：本测沿用 executor-entry-css-contract.mjs 的
 * 源码字符串锁模式。该模式的故障面（不带过来当唯一保证）：
 *   (a) 声明重排 / 特异性变化 / 宿主不再是 .wb-right-content 直接子元素——正则
 *       全看不见，绿了 computed layout 仍可能塌；
 *   (b) 浏览器默认值（iframe 150px）不在源码里。
 *   带过来的：零浏览器、确定性、秒级（改坏规则的人当场红）。
 *   兜底：t261008-05-executor-panel-height-chain 场景在真浏览器实测 computed
 *   layout（G1–G4），**验收真源在那层**，本测是快的上游哨兵。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import assert from 'node:assert/strict'

const repo = process.cwd()
const sidebar = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
const index = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
let n = 0

// C1（核心判据）：兄弟选择器同时压住 height 与 min-height——只带其一，
// flex-basis:auto 仍会按另一条把宿主撑回整列（t261008-05 修复的 load-bearing 面）。
{
  const m = sidebar.match(/\.wb-right-content > \.wb-root \{([^}]*)\}/)
  assert(m, `C1 sibling host rule present (${++n})`)
  assert(/flex\s*:\s*none/.test(m[1]), `C1 host rule keeps flex:none (${++n})`)
  assert(/height\s*:\s*auto/.test(m[1]), `C1 host rule sets height:auto (${++n})`)
  assert(/min-height\s*:\s*0/.test(m[1]), `C1 host rule sets min-height:0 (${++n})`)
}

// C2 范围纪律：遗留全局 .wb-root 规则原样保留（票面明令不改；仍全高根的视图依赖它）。
{
  const m = index.match(/\.wb-root\{[^}]*\}/)
  assert(m, `C2 legacy global .wb-root rule found (${++n})`)
  assert(/min-height:100%/.test(m[0]) && /height:100%/.test(m[0]),
    `C2 legacy rule keeps its height:100%/min-height:100% untouched (${++n})`)
}

// C3 面板侧零高下限链完好：视图拿弹性余高、iframe 填满视图（缺任一=链塌的另一头）。
assert(/\.wb-right-content > \.wb-executor-view \{ flex:1; min-height:0; \}/.test(sidebar),
  `C3 executor view flex rule intact (${++n})`)
assert(/\.wb-executor-frame \{ flex: 1; width: 100%; border: 0/.test(readFileSync(
  join(repo, 'server/plugins/workbench/src/client/executor-view.tsx'), 'utf8')),
  `C3 executor frame fills its view (${++n})`)

// C4（仅注释，不计断言）：几何推理=flex:none → flex-basis:auto → 用 height；
// height:100% 对确定高度列=整列高。推理记录在 sidebar.tsx 兄弟规则上方的注释里，
// 不在此重复断言（review C-cond-3：注释不占测试覆盖）。

console.log(`t261008-05-overlay-host-height-contract: ${n} assertions passed`)
