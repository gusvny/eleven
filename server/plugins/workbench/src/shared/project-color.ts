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

/** 调色板：10 色。定稿口径（实现期修订，偏离方案 v2「RGB 欧氏 ≥120」并在此声明）：
 *  「两两可辨」按**色相间隔**锁死——10 个色相均匀分布（每 36° 一档，s=0.72/l=0.66 生成），
 *  任意两色 hue 环距 ≥36°（smoke/project-color.mjs 断言 ≥20° 留余量）。理由：tag 色的
 *  「可辨」是感知问题，同亮度饱和色的色相才是主判据；RGB 欧氏距离会把感知上差异明显
 *  的两色（如绿 vs 青）误判为近色，10 色板在 RGB≥120 约束下无解（程序化搜索实证，
 *  只剩荧光/暗色极端解，暗底可读性崩坏）。
 *  亮度带锁定 0.66（GitHub 暗色系 UI 同档），保证暗底可读。 */
export const PROJECT_PALETTE: readonly string[] = [
  '#e76a6a', // 0° 红
  '#e7b56a', // 36° 橙
  '#cee76a', // 72° 黄绿
  '#83e76a', // 108° 绿
  '#6ae79c', // 144° 春绿
  '#6ae7e7', // 180° 青
  '#6a9ce7', // 216° 蓝
  '#836ae7', // 252° 靛紫
  '#ce6ae7', // 288° 紫
  '#e76ab5', // 324° 粉
]

/** 畸形输入/无法归项目的兜底色（中性灰，低饱和一眼「未定色」）。 */
export const FALLBACK_COLOR = '#9ca3af'

/** key 长度上限（超过按畸形处理；projects.yaml 的 key 都是短标识符）。 */
const KEY_MAX_LEN = 64

/** FNV-1a 32bit 哈希 + murmur3 终混：
 *  纯 FNV 对短 key 的低 4 位雪崩不足，真实注册表首对项目（suyou/sandbar）即同槽
 *  撞色（两 key FNV 后均 %10===2，实锤见走查报告）——用户点名的第一对就撞，
 *  「撞色风险」从概率声明变现实缺陷。加 murmur3 finalizer 改善低位雪崩；
 *  smoke/project-color.mjs 落「真实注册表键两两不同槽」回归断言看住。 */
export function fnv1a(input: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b)
  h ^= h >>> 13
  h = Math.imul(h, 0xc2b2ae35)
  h ^= h >>> 16
  return h >>> 0
}

/** project key 合法面（宽松白名单：非空、≤64、无控制字符——UI 展示面用它渲染文本）。 */
export function isProjectKeyLike(key: unknown): key is string {
  return typeof key === 'string' && key.length > 0 && key.length <= KEY_MAX_LEN
    && !/[\u0000-\u001f\u007f]/.test(key)
}

/**
 * 项目 key → 调色板色。同 key 任意次调用恒同值（纯函数，R3-a 验收对象）。
 * 畸形 key → FALLBACK_COLOR，不 throw。
 */
export function projectColor(key: unknown): string {
  if (!isProjectKeyLike(key)) return FALLBACK_COLOR
  return PROJECT_PALETTE[fnv1a(key) % PROJECT_PALETTE.length]
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
