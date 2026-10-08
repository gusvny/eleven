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
import { panelFaceFromMessage, OPEN_FACE_MSG_TYPE, type PanelFace } from './face-overlay-model.ts'
// t261008-36: the two existing faces the panel's Settings tab now drives. They are
// mounted exactly as the retired More-views entry mounted them — one importer, one
// face; the panel gains no second read or write path for model routes.
import { ProvidersSection } from '../../../providers/src/client/index.tsx'
import { ProjectRemoveModal, ProjectSettingsModal } from './project-modals.tsx'
import type { ProjectEntryLike } from './project-modals-types.ts'

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
/** t261008-36: the panel Settings tab asks the host to open one of the two existing
 *  faces (Model routes / Project settings). Paired with OPEN_FACE_MSG_TYPE in
 *  panel-page.ts (declared once in face-overlay-model.ts, re-exported here to keep
 *  the existing constant surface). The payload carries the panel's own project key;
 *  the host accepts the message only when it equals this view's projectKey (identity
 *  comes from the panel's own context, never from the console's view registry). No
 *  result receipt: the face renders in this same document, so success is visible
 *  without an ack. */
export { OPEN_FACE_MSG_TYPE }

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
  // t261008-36: the face the panel Settings tab asked for. One face at a time,
  // rendered as a full-pane overlay covering the iframe (single layer: content
  // replacement, no second window, no navigation away). `null` = Settings face only.
  const [face, setFace] = useState<PanelFace | null>(null)
  // The project-settings chain mirrors the sidebar's modal state machine: the
  // settings modal's danger button steps into the remove flow; the remove flow's
  // close returns to settings (exactly the sidebar behavior). Back to Settings —
  // the overlay's own affordance — unmounts the whole face.
  const [settingsStep, setSettingsStep] = useState<'settings' | 'remove'>('settings')
  // Registry entry for the settings modal (key/name/primary). Fetched from the same
  // projects API the sidebar uses when the face opens; failure or a missing entry =
  // a named degraded face, never a blank pane.
  const [projectEntry, setProjectEntry] = useState<ProjectEntryLike | null>(null)
  const [entryError, setEntryError] = useState('')

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

  // t261008-36: a face never survives a project switch (no cross-project bleed;
  // the panel-side projectKey equality check also rejects stale frames). This is
  // the deliberate fix for the modal-state-survives-switch fault mode the sidebar
  // chain carries.
  useEffect(() => {
    setFace(null)
    setSettingsStep('settings')
    setProjectEntry(null)
    setEntryError('')
  }, [projectKey])

  // t261008-36: the settings face needs the registry entry (key/name/primary) for
  // its modal. One fetch per face-open, aborted on close/switch/unmount — same
  // all-terminal discipline as the reachability fetch above. Source = the same
  // projects API the sidebar reads; no second registry representation is kept.
  useEffect(() => {
    if (face !== 'project-settings') return
    const ac = new AbortController()
    setProjectEntry(null)
    setEntryError('')
    fetch('/sandbar-workbench/api/wf/projects', { signal: ac.signal })
      .then((r) => r.json())
      .then((pr) => {
        if (ac.signal.aborted) return
        const list: ProjectEntryLike[] = pr?.result?.projects ?? []
        const entry = list.find((p) => p && p.key === projectKey) ?? null
        if (entry) setProjectEntry(entry)
        else setEntryError(`Project ${projectKey} is not in the registry — the settings face cannot open.`)
      })
      .catch((e) => {
        if (ac.signal.aborted) return
        setEntryError(`The project registry could not be reached: ${e instanceof Error ? e.message : String(e)}`)
      })
    return () => ac.abort()
  }, [face, projectKey])

  // R4 precedence: the ticket-detail overlay wins. Opening a ticket (left-column
  // row, or a panel-tab row's open-ticket message) clears the face; it does not
  // auto-restore — a face silently reappearing would be a second layer resurrecting
  // itself. Reopening it is one click in the panel Settings tab.
  const openTicketWins = (ticketId: string) => {
    setFace(null)
    setSettingsStep('settings')
    if (openTicketOverlay) openTicketOverlay(ticketId)
  }

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
        if (typeof d.ticketId === 'string' && d.ticketId !== '' && openTicketOverlay) openTicketWins(d.ticketId)
        return
      }
      // t261008-36: open-face. Idempotent by replacement — opening the already-open
      // face sets the same value and mounts nothing new (it never stacks, never
      // toggles). Payload checks (face whitelist + projectKey equality) live in
      // panelFaceFromMessage (face-overlay-model.ts, unit-tested with malformed
      // shapes); a rejected message is ignored — the accepted surface does not grow.
      if (d.type === OPEN_FACE_MSG_TYPE) {
        const f = panelFaceFromMessage(d, projectKey)
        if (f) {
          setSettingsStep('settings')
          setFace(f)
        }
        return
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [openExecutorSession, openTicketOverlay, openTicketWins, projectKey])

  // t261008-18: the PANEL_GOTO_EVENT forward effect went with the strip button
  // that dispatched it. The panel-side wayfinding message contract (SHOW_TAB/_EPIC)
  // stays declared for the panel page itself; no parent-side sender remains.

  const theme = consoleThemeName()

  return (
    <div className="wb-executor-view" data-wb-executor-view="" data-project={projectKey} data-face={face ?? ''}>
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
      {/* t261008-36: the face overlay. Covers the iframe in this same column — the
          single layer the ticket demands (content replacement, no second window, no
          navigation away). The iframe never unmounts (t261005-10 contract); Back to
          Settings unmounts the face, and React unmount is the all-terminal cleanup
          for the face's own fetches. */}
      {face === 'routes' && (
        <div className="wb-face-overlay" data-wb-face-overlay="" data-face="routes">
          <div className="wb-face-head">
            <button type="button" className="wb-face-back" data-wb-face-back=""
              onClick={() => { setFace(null); setSettingsStep('settings') }}>Back to Settings</button>
            <span className="wb-face-title">Model routes</span>
          </div>
          <div className="wb-face-body" data-wb-face-body="routes">
            <ProvidersSection projectKey={projectKey} />
          </div>
        </div>
      )}
      {face === 'project-settings' && (
        <div className="wb-face-overlay" data-wb-face-overlay="" data-face="project-settings">
          <div className="wb-face-head">
            <button type="button" className="wb-face-back" data-wb-face-back=""
              onClick={() => { setFace(null); setSettingsStep('settings') }}>Back to Settings</button>
            <span className="wb-face-title">Project settings</span>
          </div>
          <div className="wb-face-body" data-wb-face-body="project-settings">
            {projectEntry ? (
              settingsStep === 'settings' ? (
                <ProjectSettingsModal
                  project={projectEntry}
                  onClose={() => { setFace(null); setSettingsStep('settings') }}
                  onRemove={() => setSettingsStep('remove')} />
              ) : (
                <ProjectRemoveModal
                  project={projectEntry}
                  onClose={() => setSettingsStep('settings')}
                  onRemoved={() => { setFace(null); setSettingsStep('settings') }} />
              )
            ) : (
              <div className="wb-executor-note" role="alert" data-wb-face-entry-error="">
                {entryError || 'Loading the project registry entry…'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const EXECUTOR_CSS = `
.wb-executor-view { display: flex; flex-direction: column; min-height: 0; height: 100%; position: relative; }
.wb-executor-frame { flex: 1; width: 100%; border: 0; background: transparent; }
.wb-executor-note { margin: 16px; padding: 12px 14px; border: 1px solid var(--dsw-derive-border, #444); border-radius: 8px;
  color: var(--dsw-derive-fg, #ccc); font-size: 13px; line-height: 1.5; max-width: 640px; }
.wb-face-overlay { position: absolute; inset: 0; z-index: 10; display: flex; flex-direction: column; min-height: 0;
  background: var(--dsw-alias-bg-base, #fff); }
.wb-face-head { display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  border-bottom: 1px solid var(--dsw-derive-border, #e8ebef); }
.wb-face-back { border: 1px solid var(--dsw-derive-border, #d0d7de); background: transparent; border-radius: 6px;
  padding: 3px 10px; font-size: 12px; cursor: pointer; color: inherit; }
.wb-face-title { font-size: 13px; font-weight: 600; color: inherit; }
.wb-face-body { flex: 1; min-height: 0; overflow: auto; }
.wb-face-body > .wb-pmod-overlay { position: static; background: transparent; padding: 12px; }
`
