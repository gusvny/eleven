/**
 * project-icons.tsx —— 左栏项目组头图标族（project-lifecycle 票③，验收 11b）。
 *
 * 宿主令 260904「四个 icon 太小、不统一，顺便做一套」：emoji（📋📖🔀🗂️）→
 * SVG 线性图标五枚（工单列表/文档/模型路由/立项单/项目设置）。第五枚=项目
 * 设置入口（面D：设置弹层，含摘除 danger 区）。
 *
 * 统一规格（mock v5 规格卡逐字）：
 *   viewBox 20×20 · stroke=currentColor · stroke-width 1.6 · 圆帽圆角 · fill none
 *   显形 18px · 命中区 26×26（radius 6，由消费方 CSS 承担）
 *   三态（idle/hover/active）由消费方容器类承担（sidebar .wb-view-icon 既有三态）；
 *   path 语义与配色卡（idle #57606a / hover #0969da+#f0f6ff / active #0969da）为
 *   mock 浅色语境定稿，侧栏深色语境沿用其既有三态色板——图标本体只吃
 *   currentColor，几何规格统一是本模块的契约。
 *
 * 设置=滑杆（三轨偏置旋钮）、路由=带箭头分流（宿主修订11 两枚重绘：轮辐齿轮
 * 像太阳、节点连线像 share——均已避开）。path 逐字取
 * notes/discussions/260904-project-ui-mock.html（冻结底稿，勿手改漂移）。
 *
 * 语义锚（tests/project-icons.mjs 断言面）：PROJECT_ICON_SPECS 五键齐备、
 * 每枚 title/aria-label 同值、viewBox/stroke-width 常量单源。
 */

import type { ReactElement } from 'react'

/** 图标名（消费方 switch 用，五枚全集）。 */
export type ProjectIconName = 'board' | 'docs' | 'routes' | 'epics' | 'settings'

/** 图标语义元数据：title 与 aria-label 恒同值（可辨识纪律，验收 11b）。 */
export const PROJECT_ICON_SPECS: Record<ProjectIconName, { title: string; ariaLabel: string }> = {
  board: { title: '工单列表', ariaLabel: '工单列表' },
  docs: { title: '文档', ariaLabel: '文档' },
  routes: { title: '模型路由', ariaLabel: '模型路由' },
  epics: { title: '立项单', ariaLabel: '立项单' },
  settings: { title: '项目设置', ariaLabel: '项目设置' },
}

/** 统一规格常量（单源；显形尺寸由消费方 CSS 定，几何常量在此）。 */
export const PROJECT_ICON_VIEWBOX = '0 0 20 20'
export const PROJECT_ICON_STROKE_WIDTH = 1.6

function iconPaths(name: ProjectIconName): ReactElement {
  switch (name) {
    // 工单列表（原 📋 · 保留 t260825-05 联动语义）
    case 'board':
      return (
        <>
          <rect x="4.2" y="4.6" width="11.6" height="11.8" rx="2" />
          <path d="M7.2 4.6V3.4a1.2 1.2 0 0 1 1.2-1.2h3.2a1.2 1.2 0 0 1 1.2 1.2v1.2" />
          <path d="M7.2 9h5.6M7.2 12.4h3.6" />
        </>
      )
    // 文档（t260905-06 旧提法退役，📖 书本形制沿用）
    case 'docs':
      return (
        <>
          <path d="M10 5.4C8.8 4.2 7 3.8 4.6 4a.8.8 0 0 0-.7.8v9c0 .4.3.8.8.8 2.1-.2 3.9.2 5.3 1.4 1.4-1.2 3.2-1.6 5.3-1.4.5 0 .8-.4.8-.8v-9a.8.8 0 0 0-.7-.8C13 3.8 11.2 4.2 10 5.4z" />
          <path d="M10 5.4v10.6" />
        </>
      )
    // 模型路由（原 🔀 · 带箭头分流=路由方向）
    case 'routes':
      return (
        <>
          <circle cx="4.2" cy="10" r="1.8" />
          <path d="M5.8 8.6l5.9-5.9M9.4 2.7h2.3v2.3M5.8 11.4l5.9 5.9M9.4 17.3h2.3v-2.3" />
        </>
      )
    // 立项单（原 🗂️ · 叠卡=立项+关联票）
    case 'epics':
      return (
        <>
          <rect x="6.6" y="3.4" width="10" height="10" rx="1.8" />
          <path d="M6.6 6.6h-2a1.8 1.8 0 0 0-1.8 1.8v7a1.8 1.8 0 0 0 1.8 1.8h7a1.8 1.8 0 0 0 1.8-1.8v-2" />
        </>
      )
    // 项目设置（新增 · 滑杆=设置 · 本立项面D入口）
    case 'settings':
      return (
        <>
          <path d="M3 5.6h8.2M15.4 5.6H17M3 10h1.9M9.1 10h7.9M3 14.4h9.4" />
          <circle cx="13.3" cy="5.6" r="1.9" />
          <circle cx="7" cy="10" r="1.9" />
          <circle cx="14.5" cy="14.4" r="1.9" />
        </>
      )
  }
}

/** 图标组件：纯 svg（currentColor），容器态样式归消费方。 */
export function ProjectIcon(props: { name: ProjectIconName; className?: string }) {
  const spec = PROJECT_ICON_SPECS[props.name]
  return (
    <svg
      className={props.className}
      viewBox={PROJECT_ICON_VIEWBOX}
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth={PROJECT_ICON_STROKE_WIDTH}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={spec.ariaLabel}
    >
      {iconPaths(props.name)}
    </svg>
  )
}
