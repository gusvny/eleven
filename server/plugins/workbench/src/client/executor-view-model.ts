/**
 * executor-view-model.ts —— 执行器入口视图的纯决策层（t261003-09 修订）。
 *
 * t260929-22 曾在这里放「Chat 分支裁决」（chatLegVerdict）；宿主实测该分支恒挂在
 * 「Resolving the declared executor session…」（无超时/无重试/无失败面），t261003-09
 * 把整行切换器连同 Chat 分支一起退役——本模块只剩面板 URL 构造与主题名解析两个纯面。
 *
 * 主题（t261003-09 缺陷 2）：面板是同源 iframe，父页 CSS 自定义属性穿不过边界，
 * 由父页解析出主题名后经 `?theme=` 深链传给面板页（面板侧双调色板，见 panel-page.ts）。
 * 主题名全仓统一词表 = 'light' | 'dark'（一词一义，不混第二种拼写）。
 * 解析纯函数 resolveThemeName 在 node 可裸 import 直测（tests/executor-entry-model.mjs）。
 */

/**
 * 从控制台解析出的背景色推主题名（纯函数；畸形输入显式回落 'light'，不 throw、不猜暗色）。
 * 认 #rgb/#rrggbb 与 rgb()/rgba()；相对亮度 >= 0.5 判 light。解析失败（空串、截断值、
 * var() 链、'inherit' 等任何非字面色）一律 'light'——错误输入当浅色处理是显式降级，
 * 单测逐例锚定。
 */
export function resolveThemeName(bg: unknown): 'light' | 'dark' {
  const s = typeof bg === 'string' ? bg.trim().toLowerCase() : ''
  let r = NaN, g = NaN, b = NaN
  const hex = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/)
  if (hex) {
    const h = hex[1]
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
    r = parseInt(full.slice(0, 2), 16)
    g = parseInt(full.slice(2, 4), 16)
    b = parseInt(full.slice(4, 6), 16)
  } else {
    const fn = s.match(/^rgba?\(([^)]*)\)$/)
    if (fn) {
      const parts = fn[1].split(/[,\s/]+/).filter(Boolean)
      if (parts.length >= 3) {
        // 8bit 整数与百分比两种记法都收；alpha 位无视（透明底按不透明算）。
        const num = (v: string): number =>
          v.endsWith('%') ? Math.round(parseFloat(v) * 2.55) : parseFloat(v)
        r = num(parts[0])
        g = num(parts[1])
        b = num(parts[2])
      }
    }
  }
  if (![r, g, b].every((v) => Number.isFinite(v) && v >= 0 && v <= 255)) return 'light'
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
  return lum >= 0.5 ? 'light' : 'dark'
}

/**
 * 控制台当下主题名（组件侧薄壳读 computed 值，纯判定在 resolveThemeName）。
 * 平台外壳未暴露主题翻转事件：视图挂载时解析一次，翻主题后重开视图/刷新生效
 * （t261003-09 交接报告已声明的机制限制）。读不到/异常 → 显式 'light'。
 */
export function consoleThemeName(): 'light' | 'dark' {
  try {
    const cs = getComputedStyle(document.documentElement)
    const v = cs.getPropertyValue('--dsw-alias-bg-base') || cs.getPropertyValue('--dsw-alias-bg-primary')
    return resolveThemeName(v)
  } catch {
    return 'light'
  }
}

/** 面板页同源 URL（深链 ?project=；空键不带项目参数；theme 恒随父页解析结果拼接；
 *  运行时畸形 theme 实参归一 'light'——类型层外的防御，不产出第三种主题名）。 */
export function executorPanelUrl(projectKey: string, theme: 'light' | 'dark' = 'light'): string {
  const t = theme === 'dark' ? 'dark' : 'light'
  return projectKey === ''
    ? '/sandbar-executor-panel/?theme=' + t
    : '/sandbar-executor-panel/?project=' + encodeURIComponent(projectKey) + '&theme=' + t
}
