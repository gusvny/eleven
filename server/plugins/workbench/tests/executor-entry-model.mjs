/**
 * executor-entry-model.mjs —— 执行器入口视图纯决策层 UT（t261003-09 修订）：
 *  - executorPanelUrl：?project= 深链 + theme 恒随父页解析结果拼接（缺陷 2 的缝）；
 *  - resolveThemeName：从控制台背景色推主题名——字面色两族 + **畸形输入逐例**
 *    （空/截断/var() 链/非字符串 → 显式 'light'，不 throw 不猜暗色）。
 * chatLegVerdict 与 Chat 分支随 t261003-09 退役（宿主实测恒挂 resolving——行已删，
 * 无第四态），其旧用例一并退役。
 */
import assert from 'node:assert/strict'
import { executorPanelUrl, resolveThemeName } from '../src/client/executor-view-model.ts'

let n = 0

// ---- 面板 URL：带 ?project= 与 theme=，键 encodeURIComponent ----
{
  assert(executorPanelUrl('alpha') === '/sandbar-executor-panel/?project=alpha&theme=light', `url plain key (${++n})`)
  assert(executorPanelUrl('alpha', 'dark') === '/sandbar-executor-panel/?project=alpha&theme=dark', `url dark theme (${++n})`)
  assert(executorPanelUrl('a b/c') === '/sandbar-executor-panel/?project=' + encodeURIComponent('a b/c') + '&theme=light', `url encodes odd key (${++n})`)
  assert(executorPanelUrl('') === '/sandbar-executor-panel/?theme=light', `empty key -> project param omitted (${++n})`)
  // 畸形 theme 实参（类型层外的运行时防御）→ 归一 light，不产出第三种主题名。
  assert(executorPanelUrl('alpha', 'midnight') === '/sandbar-executor-panel/?project=alpha&theme=light', `malformed theme arg -> light (${++n})`)
}

// ---- resolveThemeName：字面深色 → dark ----
for (const v of ['#141a24', '#141A24', '#000', '#182b3a', 'rgb(20, 26, 36)', 'rgba(20,26,36,0.4)']) {
  assert(resolveThemeName(v) === 'dark', `dark literal ${JSON.stringify(v)} (${++n})`)
}
// ---- 字面浅色 → light ----
for (const v of ['#ffffff', '#fff', '#f6f8fa', 'rgb(246, 248, 250)', 'rgb(100%, 100%, 100%)']) {
  assert(resolveThemeName(v) === 'light', `light literal ${JSON.stringify(v)} (${++n})`)
}
// ---- 畸形/非字面输入（消费 computed 值的失败面）→ 显式 'light'，绝不 throw ----
for (const bad of ['', '   ', 'inherit', 'var(--dsw-alias-bg-base, #fff)', '#12', '#12345', 'rgb(1,2)', 'rgb()', 'transparent', 'midnight', null, undefined, 42, {}]) {
  assert(resolveThemeName(bad) === 'light', `malformed input ${JSON.stringify(bad)} -> light (${++n})`)
}

console.log(`done ${n}`)
