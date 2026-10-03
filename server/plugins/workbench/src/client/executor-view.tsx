/**
 * executor-view.tsx —— 中列执行器视图（t261003-09 修订）。
 *
 * t260929-22 曾在顶部放 `Executor / Chat` 切换器：宿主实测 Chat 分支恒挂在
 * 「Resolving the declared executor session…」（无超时/无重试/无失败面，而它打的
 * 端点实测 HTTP 200 ≈1ms），t261003-09 按票面把**整行退役**（页签+项目名一起删，
 * 不给这条腿加第四态）——「打开声明的 executor 会话」改由面板 Overview 里的一枚
 * 小按钮经 postMessage 请父控制台代开（同源 iframe；本组件即宿主侧 handler，
 * 校验 origin 与来源 frame 后走既有 sessions.open 通路，回复一行 STE 结果）。
 * 不再引入第二个入口：本文件是唯一的会话代开 handler，面板按钮是唯一的入口。
 *
 * - 同源 iframe 嵌面板页（`?project=<key>&theme=<light|dark>` 深链——panel-page.ts 消费）。
 *   面板路由不可达 = 显式降级横幅（点名状态码），绝不渲染空白冒充常态。
 * - 主题（缺陷 2）：父页解析出的主题名拼进 iframe URL；主题翻转事件平台不暴露，
 *   挂载时解析一次，翻转后重开视图/刷新生效（交接报告已声明）。
 * - 全终态：可达性 fetch 带 AbortController（换项目/卸载即中止）；message 监听
 *   随组件卸载 removeEventListener；本组件无常驻定时器（轮询在面板页内部）。
 *
 * 测试锚：data-wb-executor-view / data-wb-executor-frame / data-wb-executor-note
 * （t261003-06 的 seg/chat 锚随行退役；集成场景按锚断言，不按文案）。
 */

import { useEffect, useRef, useState } from 'react'
import { consoleThemeName, executorPanelUrl } from './executor-view-model.ts'

/** 面板 → 宿主的代开请求（type 常量双向成对；改一处必须改另一处，单测锚定）。 */
export const OPEN_SESSION_MSG_TYPE = 'sandbar-executor-panel:open-session'
/** 宿主 → 面板的结果回执（面板只渲染一行 STE 文案，不做轮询/重试/状态条）。 */
export const OPEN_SESSION_RESULT_MSG_TYPE = 'sandbar-executor-panel:open-session-result'

export interface ExecutorViewProps {
  projectKey: string
  /** 打开面板声明的 executor 会话（侧栏实现：sessions.open；返回是否无异常）。 */
  openExecutorSession: (sessionId: string) => boolean
}

export function ExecutorView({ projectKey, openExecutorSession }: ExecutorViewProps) {
  const [panelState, setPanelState] = useState<{ ok: boolean; detail: string }>({ ok: false, detail: 'checking…' })
  const frameRef = useRef<HTMLIFrameElement | null>(null)

  // 面板页可达性（每项目一次；换项目/卸载即中止——全终态）。
  useEffect(() => {
    const ac = new AbortController()
    setPanelState({ ok: false, detail: 'checking…' })
    fetch(executorPanelUrl(projectKey), { signal: ac.signal })
      .then((res) => {
        if (res.ok) setPanelState({ ok: true, detail: '' })
        else setPanelState({ ok: false, detail: `panel route answered HTTP ${res.status} — the executor-panel plugin may not be loaded; reload the console after (re)starting it.` })
      })
      .catch((e) => {
        if (ac.signal.aborted) return
        setPanelState({ ok: false, detail: `panel route unreachable: ${e instanceof Error ? e.message : String(e)}` })
      })
    return () => ac.abort()
  }, [projectKey])

  // 宿主侧代开 handler：面板按钮 postMessage 过来，这里校验（同源 origin + 请求
  // 恰来自本视图的 iframe + sessionId 是非空字符串）后走既有 sessions.open 通路，
  // 并把结果回执给面板（面板渲染一行文案；失败不是静默——false 也是显式回执）。
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return
      const frame = frameRef.current
      if (!frame || e.source !== frame.contentWindow) return
      const d = e.data as { type?: unknown; sessionId?: unknown } | null
      if (!d || d.type !== OPEN_SESSION_MSG_TYPE) return
      const ok = typeof d.sessionId === 'string' && d.sessionId !== '' && openExecutorSession(d.sessionId)
      frame.contentWindow?.postMessage({ type: OPEN_SESSION_RESULT_MSG_TYPE, ok }, window.location.origin)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [openExecutorSession])

  const theme = consoleThemeName()

  return (
    <div className="wb-executor-view" data-wb-executor-view="" data-project={projectKey}>
      <style>{EXECUTOR_CSS}</style>
      {panelState.ok ? (
        <iframe
          ref={frameRef}
          data-wb-executor-frame=""
          className="wb-executor-frame"
          title={`Executor panel — ${projectKey}`}
          src={executorPanelUrl(projectKey, theme)} />
      ) : (
        <div className="wb-executor-note" role="alert" data-wb-executor-note="">
          Executor panel unavailable for this project. {panelState.detail}
        </div>
      )}
    </div>
  )
}

const EXECUTOR_CSS = `
.wb-executor-view { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.wb-executor-frame { flex: 1; width: 100%; border: 0; background: transparent; }
.wb-executor-note { margin: 16px; padding: 12px 14px; border: 1px solid var(--dsw-derive-border, #444); border-radius: 8px;
  color: var(--dsw-derive-fg, #ccc); font-size: 13px; line-height: 1.5; max-width: 640px; }
`
