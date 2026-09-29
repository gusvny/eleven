/**
 * executor-view-model.ts —— 执行器入口视图的纯决策层（t260929-22 GAP A）。
 *
 * 组件（executor-view.tsx）只做渲染；判定全在本模块，node 可裸 import 直测
 * （tests/executor-entry-model.mjs 看守）。判定「Chat 分支」怎么走：读面板 settings
 * 回执里的 executor_session 声明——**面板/入口绝不自declare**（票面 out-of-scope），
 * 未声明=显式提示去面板 Settings 声明，不静默、不造缺省。
 */

/** 面板 settings 回执的最小消费面（只取本判定用的三键；多余键无视）。 */
export interface PanelSettingsLike {
  ok?: unknown
  declared?: unknown
  executor_session?: unknown
  error?: unknown
}

export type ChatLegVerdict =
  | { action: 'open'; sessionId: string }
  | { action: 'note'; reason: string }

/**
 * Chat 分支裁决：声明了且在当前会话列表里 → 打开；否则给**点名原因**的提示
 * （未声明 / 声明的会话不在册 / 回执读不了）。列表缺席（快照无 byId）按不在册
 * 处理——畸形输入显式降级，不 throw、不猜。
 */
export function chatLegVerdict(settings: unknown, listedSessionIds?: string[]): ChatLegVerdict {
  if (typeof settings !== 'object' || settings === null ||
      (settings as PanelSettingsLike).ok !== true) {
    return { action: 'note', reason: 'Executor session unreadable: the panel settings endpoint did not return a usable payload (it may be degraded — see the panel Settings tab for the reason).' }
  }
  const s = settings as PanelSettingsLike
  const declared = s.executor_session
  if (s.declared !== true || typeof declared !== 'string' || declared === '') {
    return { action: 'note', reason: 'No executor session declared for this project (declaring one is the host\'s call, in the panel\'s Settings tab — this entry never self-declares).' }
  }
  const listed = Array.isArray(listedSessionIds) ? listedSessionIds : []
  if (!listed.includes(declared)) {
    return { action: 'note', reason: `Declared executor session '${declared}' is not in this console's session list (it may have been settled). Re-declare it in the panel's Settings tab if needed.` }
  }
  return { action: 'open', sessionId: declared }
}

/** 面板页同源 URL（深链 ?project=；空键不带参数=面板自己的选择器）。 */
export function executorPanelUrl(projectKey: string): string {
  return projectKey === ''
    ? '/sandbar-executor-panel/'
    : '/sandbar-executor-panel/?project=' + encodeURIComponent(projectKey)
}
