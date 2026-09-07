/**
 * sandbar-workbench · 中列当前项目 key 的模块单态（session-entry t260828-06 从
 * src/client/index.tsx 迁出为共享模块）。
 *
 * 为什么共享：hero 接管组件（client/hero.tsx → HeroSessionEntry）挂在
 * `conversation.hero.*` 槽上，scope=root——不在中列组件树内，拿不到 WorkbenchSection
 * 的 projectKey prop；只能读这份单态。index.tsx 的 apiGet/apiPost 拼 ?project=
 * 也走它（原语义不变：WorkbenchSection 挂载/切换时 setViewProject）。
 *
 * 空串 = 尚无中列视图激活过（首屏直落 hero 的场景）——hero 侧用
 * 「单项目注册表兜底」解析（见 HeroSessionEntry 的 projectKey 推导），多项目
 * 未选则新建禁用并提示，与侧栏「会话」区同口径（不造隐形缺省）。
 */

let viewProject = ''

/** 当前中列视图的项目 key（空串=未选/未激活）。 */
export function getViewProject(): string {
  return viewProject
}

/** WorkbenchSection 挂载/切换项目时写入（index.tsx 唯一写入点）。 */
export function setViewProject(project: string): void {
  viewProject = typeof project === 'string' ? project : ''
}
