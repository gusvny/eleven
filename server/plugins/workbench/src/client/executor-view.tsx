/**
 * executor-view.tsx —— 中列执行器视图（t260929-22 GAP A）：设计稿 260927 §界面与命名
 * 的落地——左栏项目行即入口点进来后，中列顶部一个 `Executor / Chat` 切换器在
 * 「面板」与「对话」两个视图之间翻（机制同知识库页签那套；没有单独的「打开对话」钮）。
 *
 * - Executor 分支：同源 iframe 嵌面板页（`?project=<key>` 深链——panel-page.ts 消费该参数）。
 *   面板路由不可达=显式降级横幅（点名状态码），绝不渲染空白冒充常态。
 * - Chat 分支：判定在 executor-view-model.ts（chatLegVerdict）；打开动作由侧栏传入
 *   （sessions.open），打开的会话落在**现有对话 UI**（260903-07 裁定：右栏恒全局单会话，
 *   中列不再开对话——与设计稿「面板与对话是同一会话的两个视图」的落点差异已在
 *   交接报告点名，非静默替代）。
 * - 全终态：settings/可达性两个 fetch 都带 AbortController，卸载/换项目即中止；
 *   本组件无常驻定时器（轮询在面板页自己内部）。
 *
 * 测试锚：data-wb-executor-view / data-wb-executor-seg / data-wb-chat-seg /
 * data-wb-executor-frame / data-wb-chat-note（集成场景按锚断言，不按文案）。
 */

import { useEffect, useState } from 'react'
import { chatLegVerdict, executorPanelUrl } from './executor-view-model.ts'

export interface ExecutorViewProps {
  projectKey: string
  /** 当前控制台会话列表里的会话 id 集（Chat 分支在册判定用；快照缺席=undefined）。 */
  listedSessionIds?: string[]
  /** 打开面板声明的 executor 会话（侧栏实现：sessions.open；返回是否无异常）。 */
  openExecutorSession: (sessionId: string) => boolean
}

export function ExecutorView({ projectKey, listedSessionIds, openExecutorSession }: ExecutorViewProps) {
  const [seg, setSeg] = useState<'executor' | 'chat'>('executor')
  const [panelState, setPanelState] = useState<{ ok: boolean; detail: string }>({ ok: false, detail: 'checking…' })
  const [settings, setSettings] = useState<unknown>(null)
  const [settingsState, setSettingsState] = useState<'idle' | 'loading' | 'loaded' | 'failed'>('idle')
  const [openedId, setOpenedId] = useState('')

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

  // Chat 分支数据（懒取：第一次切到 chat 时；换项目重取）。
  useEffect(() => {
    if (seg !== 'chat' || settingsState !== 'idle') return
    const ac = new AbortController()
    setSettingsState('loading')
    fetch('/sandbar-executor-panel/api/settings?project=' + encodeURIComponent(projectKey), { signal: ac.signal })
      .then(async (res) => {
        if (!res.ok) { setSettings({ ok: false, error: `HTTP ${res.status}` }); setSettingsState('loaded'); return }
        setSettings(await res.json().catch(() => ({ ok: false, error: 'response body is not JSON' })))
        setSettingsState('loaded')
      })
      .catch((e) => {
        if (ac.signal.aborted) return
        setSettings({ ok: false, error: e instanceof Error ? e.message : String(e) })
        setSettingsState('failed')
      })
    return () => ac.abort()
  }, [seg, settingsState, projectKey])

  // 切到 chat 且数据在、尚未打开 → 按裁决开一次（不重复投递）。
  useEffect(() => {
    if (seg !== 'chat' || settingsState === 'idle' || settingsState === 'loading' || openedId !== '') return
    const v = chatLegVerdict(settings, listedSessionIds)
    if (v.action === 'open' && openExecutorSession(v.sessionId)) setOpenedId(v.sessionId)
  }, [seg, settings, settingsState, listedSessionIds, openExecutorSession, openedId])

  const chatVerdict = settingsState === 'loaded' || settingsState === 'failed'
    ? chatLegVerdict(settings, listedSessionIds)
    : null

  return (
    <div className="wb-executor-view" data-wb-executor-view="" data-project={projectKey}>
      <style>{EXECUTOR_CSS}</style>
      {/* 顶部切换器（设计稿：`Executor / Chat`，在面板与对话两个视图之间翻） */}
      <div className="wb-executor-switch" role="tablist" aria-label="Executor panel / conversation">
        <button
          role="tab" aria-selected={seg === 'executor'}
          data-wb-executor-seg="" data-on={seg === 'executor'}
          onClick={() => setSeg('executor')}>Executor</button>
        <button
          role="tab" aria-selected={seg === 'chat'}
          data-wb-chat-seg="" data-on={seg === 'chat'}
          onClick={() => setSeg('chat')}>Chat</button>
        <span className="wb-executor-switch-project" title={projectKey}>{projectKey}</span>
      </div>
      {seg === 'executor' && (
        panelState.ok ? (
          <iframe
            data-wb-executor-frame=""
            className="wb-executor-frame"
            title={`Executor panel — ${projectKey}`}
            src={executorPanelUrl(projectKey)} />
        ) : (
          <div className="wb-executor-note" role="alert" data-wb-executor-note="">
            Executor panel unavailable for this project. {panelState.detail}
          </div>
        )
      )}
      {seg === 'chat' && (
        <div className="wb-executor-chat" data-wb-chat-pane="">
          {chatVerdict === null ? (
            <div className="wb-executor-note">Resolving the declared executor session…</div>
          ) : chatVerdict.action === 'note' ? (
            <div className="wb-executor-note" role="alert" data-wb-chat-note="">{chatVerdict.reason}</div>
          ) : openedId === chatVerdict.sessionId ? (
            <div className="wb-executor-note" data-wb-chat-note="">
              Conversation opened in the chat column (right) — session {openedId}.
              The conversation lives in the existing chat UI (per the 260903-07 single-global-chat ruling);
              this switcher stays here as the panel-side entry back.
            </div>
          ) : (
            <div className="wb-executor-note" role="alert" data-wb-chat-note="">
              Failed to open the declared session {chatVerdict.sessionId} (see the console for details).
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const EXECUTOR_CSS = `
.wb-executor-view { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.wb-executor-switch { display: flex; align-items: center; gap: 4px; padding: 6px 10px; border-bottom: 1px solid var(--dsw-derive-border, #333); }
.wb-executor-switch button { border: 1px solid var(--dsw-derive-border, #444); background: transparent; color: inherit;
  padding: 3px 12px; border-radius: 6px; cursor: pointer; font: inherit; }
.wb-executor-switch button[data-on="true"] { background: var(--dsw-derive-bg-accent, #2b2b2b); font-weight: 600; }
.wb-executor-switch-project { margin-left: auto; color: var(--dsw-derive-fg-dim, #888); font-size: 12px; }
.wb-executor-frame { flex: 1; width: 100%; border: 0; background: transparent; }
.wb-executor-chat { padding: 16px; }
.wb-executor-note { padding: 12px 14px; border: 1px solid var(--dsw-derive-border, #444); border-radius: 8px;
  color: var(--dsw-derive-fg, #ccc); font-size: 13px; line-height: 1.5; max-width: 640px; }
`
