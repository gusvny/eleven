/**
 * sandbar-workbench · 「新建会话」启动面的双版兼容解析（260923 事故修复）。
 *
 * 为什么存在：dsh 0.1.5 把「UI 工作区服务」与「工作区控制器」拆成了两个服务——
 *   - `dsh-client-ui-workspace`：`super(ctx, "uiWorkspace")`，`startSession(workspaceId)`
 *     是这个类的方法（0.1.5 平台自己的 sidebar / agent-preset 都经 `ctx.uiWorkspace`
 *     调它，见 dsh-client-ui-sidebar:339 / dsh-client-ui-agent-preset:1467）；
 *   - `dsh-api-workspace-controller`：`super(ctx, "workspaces")`，**纯控制器，整包无
 *     startSession**。
 * 0.1.1 时代 `startSession` 在 `ctx.workspaces` 上（本插件的 WorkspacesFace 即照它写的），
 * 升级后同一句调用变成 `TypeError: workspaces.startSession is not a function`——用户侧
 * 表现为「新建会话失败：请求异常（详情见控制台）」，且**所有项目一起坏**（260923 实报：
 * nusuyou/sandbar 都炸）。
 *
 * 解析口径（与 t260916-26 的 inject 纪律一致）：
 *   - **不得**把 `uiWorkspace` 写进插件 inject——声明某版不存在的服务 = 该 entry 永久
 *     pending、整个插件激活不了（t260916-26 教训），故只能在调用点运行时解析；
 *   - 解析顺序＝调用方给的候选面顺序，命中即用，回调 `this` 绑回原宿主；
 *   - 全部候选都没有 → **响亮且精确**地报错（说清是哪一版哪个面的事），不甩裸 TypeError。
 *
 * 本模块零 npm 依赖、零 DOM（node 原生 type-stripping 可直测）。
 */

/** 提供 startSession 的服务面（结构类型；两版方法名一致）。 */
export interface StartSessionFace {
  startSession?: (workspaceId?: string) => void
}

/** 解析出的启动函数（`this` 已绑回宿主）。 */
export type StartSessionFn = (workspaceId?: string) => void

/** 不可用时的精确报错文案（点名两版各自的所在面，避免诊断被引向错误方向）。 */
export const START_SESSION_MISSING =
  'startSession 不可用：dsh 0.1.5 起该 API 在 uiWorkspace 上（dsh-client-ui-workspace），'
  + 'ctx.workspaces 现为纯控制器（dsh-api-workspace-controller，无此方法）；'
  + '0.1.1 时代它在 ctx.workspaces 上。候选服务面均未提供 startSession。'

/**
 * 从候选面里挑出可用的 startSession。
 * @param candidates - 按优先级排列的服务面（如 `[ctx.uiWorkspace, ctx.workspaces]`）。
 * @throws 所有候选都没有 startSession 时抛错（消息＝START_SESSION_MISSING）。
 */
export function resolveStartSession(candidates: readonly unknown[]): StartSessionFn {
  for (const face of candidates) {
    const fn = (face as StartSessionFace | null | undefined)?.startSession
    if (typeof fn === 'function') return (workspaceId?: string) => fn.call(face, workspaceId)
  }
  throw new Error(START_SESSION_MISSING)
}
