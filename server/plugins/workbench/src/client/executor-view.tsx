/**
 * executor-view.tsx — the middle-column executor view (revised by t261003-09).
 *
 * t260929-22 put an `Executor / Chat` switch at the top. The host measured the Chat
 * branch stuck on "Resolving the declared executor session…": no timeout, no retry,
 * no failure face, while the endpoint it calls answers HTTP 200 in about 1 ms. So
 * t261003-09 retired the whole row per the ticket face (tab and project name both
 * gone, no fourth state on this branch). "Open the declared executor session" now
 * runs from one small button in the panel Overview, which asks the parent console to
 * open it over postMessage (same-origin iframe; this component is the host-side
 * handler: it checks the origin and the source frame, then takes the existing
 * sessions.open path and replies with one result line). No second entry point: this
 * file is the only session-opening handler and the panel button is the only entry.
 *
 * - The same-origin iframe embeds the panel page (`?project=<key>&theme=<light|dark>`
 *   deep link, consumed by panel-page.ts). An unreachable panel route = an explicit
 *   degraded banner naming the status code, never a blank page posing as normal.
 * - Theme (defect 2): the theme name the parent page resolved goes into the iframe
 *   URL. The platform exposes no theme-flip event, so the name is resolved once at
 *   mount and takes effect when the view reopens or the page reloads (declared in
 *   the handover report).
 * - Every terminal state: the reachability fetch carries an AbortController (project
 *   switch or unmount aborts it); the message listener is removed on unmount; this
 *   component keeps no timer (polling lives inside the panel page).
 *
 * Test anchors: data-wb-executor-view / data-wb-executor-frame / data-wb-executor-note
 * (t261003-06's seg/chat anchors retired with their row; the integration scenarios
 * assert on anchors, never on copy).
 */

import { useEffect, useRef, useState } from 'react'
import { consoleThemeName, executorPanelUrl } from './executor-view-model.ts'

/** 面板 → 宿主的代开请求（type 常量双向成对；改一处必须改另一处，单测锚定）。 */
export const OPEN_SESSION_MSG_TYPE = 'sandbar-executor-panel:open-session'
/** 宿主 → 面板的结果回执（面板只渲染一行 STE 文案，不做轮询/重试/状态条）。 */
export const OPEN_SESSION_RESULT_MSG_TYPE = 'sandbar-executor-panel:open-session-result'
/** t261005-10 (UI-2): a panel Epics/Inspection ticket row asks the host to open the
 *  existing ticket-detail overlay (the t261005-04 machinery; the panel builds no
 *  second detail face). */
export const OPEN_TICKET_MSG_TYPE = 'sandbar-executor-panel:open-ticket'
/** Panel wayfinding message contract (t261005-10, kept as the panel page's own
 * protocol surface). Since t261008-18 no parent-side sender ships in this client;
 * the panel accepts only these two, from the parent only. */
export const SHOW_TAB_MSG_TYPE = 'sandbar-executor-panel:show-tab'
export const SHOW_EPIC_MSG_TYPE = 'sandbar-executor-panel:show-epic'
/* t261008-18: PANEL_GOTO_EVENT ('wb-panel-goto') went with the machine-level head
 * button that dispatched it — the panel is reached by opening it, not by in-window
 * wayfinding from a strip that no longer exists. */

export interface ExecutorViewProps {
  projectKey: string
  /** 打开面板声明的 executor 会话（侧栏实现：sessions.open；返回是否无异常）。 */
  openExecutorSession: (sessionId: string) => boolean
  /** t261005-10 (UI-2): a panel ticket row requests the ticket-detail overlay (the
   *  sidebar handleTicketClick chain). Absent = a no-op — the overlay is not this
   *  surface's to build; no error is raised. */
  openTicketOverlay?: (ticketId: string) => void
}

export function ExecutorView({ projectKey, openExecutorSession, openTicketOverlay }: ExecutorViewProps) {
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
      const d = e.data as { type?: unknown; sessionId?: unknown; ticketId?: unknown } | null
      if (!d || typeof d !== 'object') return
      // t261005-10 (UI-2): the same listener also takes open-ticket — a ticket row
      // opens the existing overlay. Unknown types or unknown senders are ignored
      // (the accepted surface does not grow, review C3); a missing
      // openTicketOverlay callback is a no-op.
      if (d.type === OPEN_SESSION_MSG_TYPE) {
        const ok = typeof d.sessionId === 'string' && d.sessionId !== '' && openExecutorSession(d.sessionId)
        frame.contentWindow?.postMessage({ type: OPEN_SESSION_RESULT_MSG_TYPE, ok }, window.location.origin)
        return
      }
      if (d.type === OPEN_TICKET_MSG_TYPE) {
        if (typeof d.ticketId === 'string' && d.ticketId !== '' && openTicketOverlay) openTicketOverlay(d.ticketId)
        return
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [openExecutorSession, openTicketOverlay])

  // t261008-18: the PANEL_GOTO_EVENT forward effect went with the strip button
  // that dispatched it. The panel-side wayfinding message contract (SHOW_TAB/_EPIC)
  // stays declared for the panel page itself; no parent-side sender remains.

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
