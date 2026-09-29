// theme.ts — 工单台主题令牌基建（t260905-08）。
//
// 机制（宿主令 260906 22:1X）：跟随 dsh 平台外观机制——全面消费平台
// `--dsw-alias-*` 令牌（外观翻转由平台壳负责），不另造主题状态、不监听
// prefers-color-scheme。平台没有的语义角色（危险/成功/警告/信息/分层表面）
// 用 color-mix 从既有 alias 派生（--dsw-derive-*，本文件 DERIVE_TOKENS_CSS
// 在 :root 定义一次）；混入 var(--dsw-alias-label-primary) 使文字色深浅两档
// 自动成立（浅档混向近黑、深档混向近白）。
//
// 纪律（review 条件1/R2）：**每个 var() 引用一律自带 fallback**——挂载点在
// 定义作用域外（宿主 slot/portal）时引用处未定义会整体 invalid→unset 静默
// 退化，fallback 保证任何挂载路径恒有值。fallback 取浅档原值（=改造前色）。
//
// 固定暗面板（--dsw-derive-dark-*）：终端/代码块等**自备深底**的表面，其
// 前后景是一对固定搭配，不随平台翻转（翻转反而破坏与固定底的对偶）。
//
// 已知机制限制（方案 C6 声明）：平台 alias 值为非法色时 CSS invalid at
// computed-value time → 属性 unset（不走 fallback），JS 层无从防御；
// 看守场景按 computed 值断言，unset 落继承链仍会被对比度断言网住。

/**
 * 平台 alias 消费词汇（6 个；定义侧在平台壳，不在本仓）。
 *
 * bgBase 收录依据（t260907-03 补评审门正名）：宿主平台 0.1.1-rc.2 的平台壳**没有**
 * `--dsw-alias-bg-primary` 名、只有 `--dsw-alias-bg-base`；bgPrimary 的兜底链
 * `var(--dsw-alias-bg-primary, var(--dsw-alias-bg-base, #fff))` = 兼容旧版平台——
 * 属**平台版本契约扩容**（多认一个旧平台令牌名），本票过门收录入账。
 */
export const ALIAS = {
  bgPrimary: 'var(--dsw-alias-bg-primary, var(--dsw-alias-bg-base, #fff))',
  bgBase: 'var(--dsw-alias-bg-base, #fff)',
  border: 'var(--dsw-alias-border-l, #d0d7de)',
  brand: 'var(--dsw-alias-brand-primary, #0969da)',
  labelPrimary: 'var(--dsw-alias-label-primary, #1f2328)',
  labelSecondary: 'var(--dsw-alias-label-secondary, #57606a)',
} as const

/** 派生语义令牌（TSX 行内 style 用；与 DERIVE_TOKENS_CSS 同名同 fallback）。 */
export const TOKEN = {
  fg: 'var(--dsw-derive-fg, #1f2328)',
  muted: 'var(--dsw-derive-muted, #57606a)',
  border: 'var(--dsw-derive-border, #d0d7de)',
  canvas: 'var(--dsw-derive-canvas, #fff)',
  surface: 'var(--dsw-derive-surface, #f6f8fa)',
  surface2: 'var(--dsw-derive-surface-2, #e8ebef)',
  accent: 'var(--dsw-derive-accent, #0969da)',
  accentSolid: 'var(--dsw-derive-accent-solid, #1f6feb)',
  onSolid: 'var(--dsw-derive-on-solid, #fff)',
  active: 'var(--dsw-derive-active, #7c3aed)',
  accentDeep: 'var(--dsw-derive-accent-deep, #0550ae)',
  accentBg: 'var(--dsw-derive-accent-bg, #ddf4ff)',
  accentBorder: 'var(--dsw-derive-accent-border, #96c8f2)',
  danger: 'var(--dsw-derive-danger, #cf222e)',
  dangerSolid: 'var(--dsw-derive-danger-solid, #d1242f)',
  dangerBg: 'var(--dsw-derive-danger-bg, #ffebe9)',
  dangerBorder: 'var(--dsw-derive-danger-border, #ff9b9b)',
  success: 'var(--dsw-derive-success, #1a7f37)',
  successDeep: 'var(--dsw-derive-success-deep, #116329)',
  successSolid: 'var(--dsw-derive-success-solid, #2da44e)',
  successBg: 'var(--dsw-derive-success-bg, #dafbe1)',
  successBorder: 'var(--dsw-derive-success-border, #7dd9a0)',
  warn: 'var(--dsw-derive-warn, #9a6700)',
  warnDeep: 'var(--dsw-derive-warn-deep, #7d4e00)',
  warnBg: 'var(--dsw-derive-warn-bg, #fff8c5)',
  warnBorder: 'var(--dsw-derive-warn-border, #d4a72c)',
} as const

/**
 * epic 徽标文字色：哈希装饰色向主题前景色方向调和（45%——acceptance 实测 65% 在 fallback 分支半透底链 4.21 压线、忠实深态最低槽 4.43 压线；45% 后全档两分支 ≥4.5），深浅两档下
 * EPIC_PALETTE 全 10 档对比度达标（看守场景逐档断言）。`--epic-c` 由消费点
 * 行内注入（epicColorOf 结果，纯函数不动）。
 */
export function epicChipColor(): string {
  /* t260929-22 gen5/gen8（对比度红 4.18<4.5）：epic 色只出 30%，其余沉到强墨令牌
     --dsw-derive-ink-strong（声明位=#24292f）——任何 epic 色（含最浅黄族）白底 ≥4.5；
     裸 hex 全部收进令牌声明/var fallback 位（hex-clean 纪律）。 */
  return 'color-mix(in srgb, var(--epic-c, var(--dsw-derive-ink-strong, #9ca3af)) 30%, var(--dsw-derive-ink-strong, #24292f))'
}

/** 弱化文字（审批区 epicLine 等此前恒走 --wb-muted fallback 的点位，t260905-08 收编）。 */
export function epicChipMuted(): string {
  return 'var(--dsw-derive-muted, #888)'
}

/**
 * :root 级派生令牌定义（注入各组件 CSS 常量头部；多组件各注入一份同值块，
 * 重复定义无害，保证任一组件独立挂载时令牌都在场）。
 */
export const DERIVE_TOKENS_CSS = `:root{
/* 文字系：45% 语义基色 × 55% 平台前景——浅档基色微加深（对比度↑），深档自动提亮 */
/* t260929-22 gen9（对比度行级打回：平台 label 在浅底实测 rgb(122,122,133)≈4.24，
   一切继承 fg 的正文都在线下）——fg 锁固定深墨；深壳主题启用时须连本块一起重订
   （同 --dsw-derive-warn/muted 等 gen8 深墨家族口径，UT contrast-palette 看守）。 */
--dsw-derive-fg:#24292f;
--dsw-derive-ink-blue:#0550ae;
/* t260929-22 gen8（对比度打回：平台 label 极性/取值不定，混不出保证对比度——
   文字语义令牌改为浅档深墨声明位裸值；深壳主题若启用须连本块一起重订）。 */
--dsw-derive-muted:#57606a;
--dsw-derive-border:var(--dsw-alias-border-l,#d0d7de);
--dsw-derive-canvas:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff));
--dsw-derive-surface:color-mix(in srgb,var(--dsw-alias-border-l,#d0d7de) 13%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-surface-2:color-mix(in srgb,var(--dsw-alias-border-l,#d0d7de) 26%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-accent:#0969da;
--dsw-derive-accent-solid:#1f6feb;
--dsw-derive-on-solid:#ffffff;
--dsw-derive-active:#7c3aed;
--dsw-derive-accent-deep:color-mix(in srgb,#0550ae 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-accent-bg:color-mix(in srgb,#0969da 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-accent-border:color-mix(in srgb,#0969da 42%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-danger:#cf222e;
--dsw-derive-danger-solid:#d1242f;
--dsw-derive-danger-bg:color-mix(in srgb,#cf222e 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-danger-border:color-mix(in srgb,#cf222e 40%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-success:color-mix(in srgb,#1a7f37 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-success-deep:color-mix(in srgb,#116329 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-success-solid:#2da44e;
--dsw-derive-success-bg:color-mix(in srgb,#1a7f37 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-success-border:color-mix(in srgb,#1a7f37 42%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
/* t260929-22 gen5（对比度红 4.24<4.5）：warn 文字加深——基色换 warn-deep 家族的
   #7d4e00、alias 只作 30% 少数项（极性不定时混不出保证对比度，见 UT contrast-palette）。 */
--dsw-derive-warn:#7d4e00;
--dsw-derive-ink-strong:#24292f;
--dsw-derive-warn-deep:color-mix(in srgb,#7d4e00 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-warn-bg:color-mix(in srgb,#eac54f 16%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-warn-border:color-mix(in srgb,#d4a72c 45%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
/* 固定暗面板：自备深底的表面（终端/代码块），前后景固定搭配不随平台翻转 */
--dsw-derive-dark-bg:#1e1e24;
--dsw-derive-dark-fg:#f0f3f6;
--dsw-derive-dark-muted:#b8b8c8;
--dsw-derive-dark-green:#7ee787;
--dsw-derive-dark-red:#f87171;
--dsw-derive-dark-amber:#ffd166;
--dsw-derive-dark-accent:#7ab8ff;
--dsw-derive-dark-warn-bg:#7a4a06;
--dsw-derive-dark-warn-fg:#ffe9c4;
/* 暗面板面位扩展（t260907-08）：docs 视图代码块（pre/.md-code/.md-cl/.md-copy）需要
 * 与 dark-bg 成对的边框/浮起面/悬停面三个面位——值取 GitHub Dark 系（与改造前
 * docs.tsx 写死值同源），搭配固定不翻转。登记理由：docs.tsx 令牌化时按消费点驱动
 * 盘点，既有 9 个 dark 令牌覆盖不了「面板内边框/浮起 chip」语义，缺才增（方案 §3）。 */
--dsw-derive-dark-border:#2a2f3a;
--dsw-derive-dark-surface:#21262d;
--dsw-derive-dark-surface-2:#30363d;
}
/* 老浏览器静态回退（t260915-08 仲裁修复，方向①）：warn/danger 底色令牌值为
 * color-mix(...)——不支持的浏览器（Chrome<111）上 var 替换 IACVT=底色透明，
 * 「等你=黄调行」在该类浏览器瞎掉。@supports not 分档在**令牌声明位**直接覆盖
 * 为静态色（hex-clean 看守 allowlist C 合法位），消费位 var() 零改动即两档自适应：
 * 新浏览器吃上方 color-mix 令牌，老浏览器吃本块静态色。探针用 currentcolor（无 hex）。
 * 本块随 DERIVE_TOKENS_CSS 多组件各注入一份，同值重复定义无害。 */
@supports not (background: color-mix(in srgb, currentcolor, currentcolor)) {
  :root{
  --dsw-derive-warn-bg:#fff8c5;
  --dsw-derive-danger-bg:#ffebe9;
  }
}`
