/**
 * file-pane.tsx — the middle-column file sheet (t261102-09).
 *
 * What it is: a layer over the middle column that shows one file the chat handed
 * over. It is a SIBLING of `.wb-right-content` inside `.wb-sb-right`, not a
 * replacement for it, so the ticket detail and the executor panel stay mounted
 * underneath and Back needs no restore stack — it closes the sheet and the view
 * that was there is exactly as it was.
 *
 * Layer rule: the UI-3 "one layer deep" invariant governs the overlay host's
 * CONTENT (ticket and epic swap in one entry). This sheet is a second, separate
 * surface and there is exactly one of it: z-index 91 sits above the ticket
 * drawer (90) and below every modal (99) and the lightbox (120).
 *
 * Honest naming: every failure renders a banner that carries the path and the
 * reason. A read that never answers (a console that runs old code does not serve
 * this route) is named as such, never as a generic network error.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import {
  describeReadFailure,
  fileTitleOf,
  initialViewKind,
  lineNoteOf,
  planSourceRows,
  textKindOf,
} from './file-pane-model.ts'
import { closeFileOpen, readFileOpenRequest, subscribeFileOpen } from './file-open-request.ts'
import { FILE_READ_PATH } from './file-route.ts'

type LoadView =
  | { phase: 'loading' }
  | { phase: 'ok'; content: string }
  | { phase: 'failed'; reason: string; message: string }

/**
 * The sheet itself.
 * @returns the sheet, or null when no request is open (the mount is conditional
 *   too; the guard keeps a stale render harmless).
 */
export function FilePane() {
  const request = useSyncExternalStore(subscribeFileOpen, readFileOpenRequest, readFileOpenRequest)
  const [load, setLoad] = useState<LoadView>({ phase: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [override, setOverride] = useState<{ key: string; view: 'rendered' | 'source' } | null>(null)
  const [copied, setCopied] = useState(false)
  const hitRef = useRef<HTMLDivElement | null>(null)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const path = request?.path ?? ''
  const kind = textKindOf(path)
  const requestKey = request === null ? '' : `${request.address}#${request.revision}`
  const autoView = request === null ? 'source' : initialViewKind(kind, request.line)
  const view = override !== null && override.key === requestKey ? override.view : autoView
  // The clip decision belongs to the model (one rule, unit-tested): the note states rows
  // were dropped, never a difference between two unrelated line counts.
  const plan = load.phase === 'ok' ? planSourceRows(load.content) : { rows: [], total: 0, clipped: false }
  const rows = plan.rows
  const lineNote = lineNoteOf(request?.line, rows.length)
  const line = lineNote === null ? 0 : lineNote.row

  // The read: one abortable request per address/revision/retry. The controller is
  // aborted on unmount, on a new request and on Retry, so no answer outlives it.
  useEffect(() => {
    if (request === null) return
    const controller = new AbortController()
    const query = new URLSearchParams({ path: request.path })
    if (request.scope === 'session' && request.sessionId !== '') query.set('session', request.sessionId)
    setLoad({ phase: 'loading' })
    fetch(`${FILE_READ_PATH}?${query.toString()}`, { signal: controller.signal })
      .then(async (res) => ({ status: res.status, text: await res.text() }))
      .then(({ status, text }) => {
        if (controller.signal.aborted) return
        let body: unknown = null
        try {
          body = JSON.parse(text)
        } catch {
          body = null
        }
        const answer = typeof body === 'object' && body !== null ? body as Record<string, unknown> : null
        const result = answer !== null && typeof answer.result === 'object' && answer.result !== null
          ? answer.result as Record<string, unknown>
          : null
        if (answer !== null && answer.ok === true && result !== null && typeof result.content === 'string') {
          setLoad({ phase: 'ok', content: result.content })
          return
        }
        const failure = describeReadFailure(status, text, request.path)
        setLoad({ phase: 'failed', reason: failure.reason, message: failure.message })
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        const detail = err instanceof Error ? err.message : String(err)
        setLoad({ phase: 'failed', reason: 'network', message: `Cannot open ${request.path}: the read did not complete (${detail}).` })
      })
    return () => { controller.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, attempt])

  // Keyboard: the sheet owns Escape while it is open, and keeps the ticket walk
  // (the drawer's window listener) from moving tickets underneath it. The arrows
  // are stopped but NOT defaulted away, so the file body still scrolls.
  useEffect(() => {
    if (request === null) return
    const onKey = (ev: KeyboardEvent): void => {
      if (ev.key === 'Escape') {
        ev.preventDefault()
        ev.stopPropagation()
        closeFileOpen()
        return
      }
      if (ev.key === 'ArrowUp' || ev.key === 'ArrowDown') ev.stopPropagation()
    }
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('keydown', onKey, true) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request === null])

  // Line navigation: reveal the requested row after it has rendered.
  useEffect(() => {
    if (load.phase !== 'ok' || view !== 'source' || line < 1) return
    const node = hitRef.current
    if (node !== null && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'center' })
  }, [load, view, line])

  // The copy label resets on a timer; the timer is cleared on unmount.
  useEffect(() => () => {
    if (copyTimer.current !== null) clearTimeout(copyTimer.current)
  }, [])

  const copyPath = useCallback(() => {
    try {
      void navigator.clipboard?.writeText(path)
      setCopied(true)
      if (copyTimer.current !== null) clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => { setCopied(false) }, 1200)
    } catch {
      // A clipboard the page may not use is not an error worth a banner.
      setCopied(false)
    }
  }, [path])

  if (request === null) return null

  const title = fileTitleOf(request.address)
  return (
    <div className="wb-file-pane" data-file-pane="" data-file-pane-address={request.address} role="region"
      aria-label={`File ${path === '' ? title : path}`}>
      <div className="wb-file-pane-head" data-file-pane-head="">
        <button type="button" className="wb-file-pane-btn" data-file-pane-back=""
          title="Back to the view underneath" onClick={closeFileOpen}>← Back</button>
        <span className="wb-file-pane-title" data-file-pane-path="" title={path}>{path === '' ? title : path}</span>
        {kind === 'markdown' && (
          <span className="wb-file-pane-toggle" data-file-pane-view={view}>
            <button type="button" className="wb-file-pane-btn" data-file-pane-rendered=""
              data-active={view === 'rendered'}
              onClick={() => setOverride({ key: requestKey, view: 'rendered' })}>Rendered</button>
            <button type="button" className="wb-file-pane-btn" data-file-pane-source=""
              data-active={view === 'source'}
              onClick={() => setOverride({ key: requestKey, view: 'source' })}>Source</button>
          </span>
        )}
        <button type="button" className="wb-file-pane-btn" data-file-pane-copy="" onClick={copyPath}>
          {copied ? 'Copied' : 'Copy path'}
        </button>
      </div>
      {lineNote !== null && (
        <div className="wb-file-pane-line-note" data-file-pane-line={lineNote.row}>{lineNote.text}</div>
      )}
      {load.phase === 'loading' && (
        <div className="wb-file-pane-status" data-file-pane-loading="">Loading file…</div>
      )}
      {load.phase === 'failed' && (
        <div className="wb-file-pane-banner" data-file-pane-refused={load.reason} role="alert">
          <div>{load.message}</div>
          <button type="button" className="wb-file-pane-btn" data-file-pane-retry=""
            onClick={() => setAttempt((n) => n + 1)}>Retry</button>
        </div>
      )}
      {load.phase === 'ok' && view === 'rendered' && (
        <div className="wb-file-md wb-md" data-file-pane-md=""
          dangerouslySetInnerHTML={{ __html: renderMarkdown(load.content) }} />
      )}
      {load.phase === 'ok' && view === 'source' && plan.clipped && (
        <div className="wb-file-pane-line-note" data-file-pane-row-clip={rows.length}>
          showing the first {rows.length} of {plan.total} lines
        </div>
      )}
      {load.phase === 'ok' && view === 'source' && (
        <div className="wb-file-pane-src" data-file-pane-src="">
          {rows.map((text, index) => {
            const number = index + 1
            const hit = number === line
            return (
              <div key={number} className="wb-file-pane-row" data-file-line={number}
                data-file-line-hit={hit ? '' : undefined}
                ref={hit ? hitRef : undefined}>
                <span className="wb-file-pane-ln" aria-hidden="true">{number}</span>
                <span className="wb-file-pane-lc">{text === '' ? ' ' : text}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
