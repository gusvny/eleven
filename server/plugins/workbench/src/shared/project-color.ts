/**
 * sandbar-workbench · 项目 key → tag 色 纯函数（t260903-07 工单②：全局 chat 消息
 * 项目 tag 按项目着色，为多项目同屏区分做准备）。
 *
 * 借鉴模式取舍（格式对齐 session-ledger-store.ts 头注）：
 * - ✅ 确定性哈希取色（FNV-1a 32bit → 调色板下标）：同 key 恒同色，无配置面也稳定。
 * - ❌ 不带运行时随机/持久化记忆：纯函数无状态，刷新/重启不漂移（验收 R3-a）。
 * - ❌ 不读 projects.yaml 配置：色映射零配置面；未来注册表声明色升级 =
 *   在本模块加「yaml 可选 color 字段优先于哈希值」一层，函数签名不变（见下）。
 * - ✅ 畸形输入兜底（外部输入纪律）：空/非字符串/超长 key → 中性灰，不 throw。
 *
 * 撞色风险（已声明，验收 R3-c 不作通过/失败断言）：10 色板下两项目撞色概率
 * 约 1/10（生日悖论在项目数个位数时更高些）。升级路径一：扩色板；升级路径二
 * （优先）：projects.yaml 增加可选 `color` 字段，registry 声明色覆盖哈希值。
 */

/** Palette: since t261005-05 (UI-4 project identity) this re-exports the DECLARED
 *  12 colours from shared/project-identity.ts (verbatim mock v11 `PALETTE12`;
 *  declaration truth in that module's header). Single-source rule: the palette is
 *  declared once, in the identity module; the old export name stays so existing
 *  consumers need no change. Old 10-colour palette (36-degree steps) is history:
 *  superseded by the declared 12 (minimum hue-ring gap 19.2 degrees; the smoke
 *  criterion re-anchored to 18, reason in its header). */
export { PROJECT_PALETTE_12 as PROJECT_PALETTE } from './project-identity.ts'
import { PROJECT_PALETTE_12 } from './project-identity.ts'

/** Fallback colour for malformed input (neutral grey, plainly "unset").
 *  t261005-05: true source moved to shared/project-identity.ts (which uses it for
 *  the fallback identity); re-exported here to keep the old import path. */
export { FALLBACK_COLOR } from './project-identity.ts'
import { FALLBACK_COLOR } from './project-identity.ts'

/** Key cap / FNV-1a+murmur3 hash / key whitelist: since t261005-05 the true source
 *  lives in shared/project-identity.ts (the badge single source needs them
 *  self-contained; the panel page embeds the same functions via String(fn));
 *  re-exported here to keep the old import paths. Tradeoffs and known vectors in
 *  that module's header. */
export { fnv1a, isProjectKeyLike } from './project-identity.ts'
import { fnv1a, isProjectKeyLike } from './project-identity.ts'

/**
 * 项目 key → 调色板色。同 key 任意次调用恒同值（纯函数，R3-a 验收对象）。
 * 畸形 key → FALLBACK_COLOR，不 throw。
 */
export function projectColor(key: unknown): string {
  if (!isProjectKeyLike(key)) return FALLBACK_COLOR
  return PROJECT_PALETTE_12[fnv1a(key) % PROJECT_PALETTE_12.length]
}

/**
 * 生成 tag 样式 CSS 规则文本（注入 head 的自有 style 用；机制=属性锚 +
 * CSS ::before/attr()，对 React 托管容器零 childList 侵入——t260903-07 方案 v2 R1）。
 *
 * @param keys 已知项目 key 集合（重复自动去重；畸形 key 跳过不产规则）。
 * @returns 一段完整可注入的 CSS 文本（含基础规则 + 每项目着色规则）。
 *          key 只出现在属性选择器与 content 文本里，含 `"`/`\` 的 key 已在
 *          isProjectKeyLike 之外的这里再拦一层（双保险，防选择器注入）。
 */
export function projectTagCssRules(keys: readonly unknown[]): string {
  const seen = new Set<string>()
  for (const k of keys) {
    if (isProjectKeyLike(k) && !k.includes('"') && !k.includes('\\')) seen.add(k)
  }
  const base = [
    `[data-wb-projtag]::before{`,
    `content:attr(data-wb-projtag);`,
    `display:inline-block;`,
    `font-size:10px;line-height:1;padding:2px 6px;margin-right:6px;`,
    `border-radius:8px;border:1px solid transparent;`,
    `vertical-align:1px;`,
    `font-family:var(--ds-font-family-code,monospace);`,
    `white-space:nowrap;`,
    `}`,
  ].join('')
  const rules: string[] = [base]
  for (const k of seen) {
    const c = projectColor(k)
    // 半透明底=主色 22% 混入（rgba 由 hex 展开，避免 color-mix 兼容性赌注）
    const r = parseInt(c.slice(1, 3), 16)
    const g = parseInt(c.slice(3, 5), 16)
    const b = parseInt(c.slice(5, 7), 16)
    rules.push(
      `[data-wb-projtag="${k}"]::before{color:${c};border-color:${c}55;background:rgba(${r},${g},${b},0.16)}`,
    )
  }
  return rules.join('\n')
}
