/**
 * inspection-exit — the human exit block for a mechanically-rejected (blocked)
 * inspection ticket, on the ticket detail face (t261008-22, host order 261008;
 * plan v2 Step 4, entry face = the workbench ticket detail, where the blocked row
 * the host complained about actually sits).
 *
 * Two named actions, both requiring a reason (a reason-less attempt is refused BY
 * NAME client-side before any fetch — zero side effects; the server refuses again):
 *   - "Re-run this period"  -> POST /sandbar-executor-panel/api/inspection/period/rerun
 *     (drives inspection_trigger.py trigger --reopen-reason; the engine's refusals —
 *     the in-flight refusal ("a live inspection for this period already exists ...
 *     named cancel first, then re-run") included — surface
 *     VERBATIM, never reworded or swallowed).
 *   - "Void with a reason"  -> POST /sandbar-executor-panel/api/inspection/period/void
 *     (drives inspection_trigger.py void — the engine's named void for terminal
 *     blocked-completed tickets; void never reads as success: the block says the
 *     rejected findings stay on the ticket).
 *
 * Population copy (review C6): a blocked-completed ticket's valid exit is re-run
 * alone; void is optional labeling (who/why), never a prerequisite — the copy never
 * tells the host to "void first" here. A voided ticket renders the recorded
 * disposition instead of the actions (who/reason verbatim; findings untouched).
 *
 * Same-origin cross-plugin fetch precedent: the requests band already reads
 * /sandbar-executor-panel/api/requests from this client (index.tsx).
 */

import { useState } from 'react'
import { inspectionExitVisible, buildExitPayload } from './inspection-exit-model.ts'

export { inspectionExitVisible, buildExitPayload }

export interface InspectionExitDetail {
  id?: string
  kind?: string
  status?: string
  instance_id?: string
  period?: string
  voided?: { at?: unknown; who?: unknown; reason?: unknown }
}

/** The block itself (client component; self-contained state). */
export function InspectionExitBlock({ detail, projectKey }: {
  detail: InspectionExitDetail
  projectKey?: string
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<'rerun' | 'void' | null>(null)
  const [msg, setMsg] = useState('')
  const [msgKind, setMsgKind] = useState<'info' | 'error' | 'ok'>('info')

  if (detail.voided) {
    const v = detail.voided
    const who = typeof v.who === 'string' && v.who.trim() !== '' ? v.who : 'unknown'
    const why = typeof v.reason === 'string' && v.reason.trim() !== '' ? v.reason : '(reason not recorded)'
    return (
      <div className="wb-insp-exit" data-testid="inspection-exit-voided">
        <div className="wb-insp-exit-ttl">Voided</div>
        <div className="wb-sub">Voided by {who}: {why}</div>
        <div className="wb-sub">This ticket stays on record as rejected — the findings above were not erased by the void.</div>
      </div>
    )
  }

  const run = async (action: 'rerun' | 'void') => {
    const check = buildExitPayload(action, detail, projectKey, reason)
    if (!check.ok) {
      setMsgKind('error')
      setMsg(check.error)
      return
    }
    setBusy(action)
    setMsg('')
    try {
      const res = await fetch(`/sandbar-executor-panel/api/inspection/period/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(check.payload),
      })
      const doc = await res.json().catch(() => null) as Record<string, unknown> | null
      const err = doc && typeof doc.error === 'string' ? doc.error : `HTTP ${res.status}`
      if (res.ok && doc && doc.ok === true) {
        setMsgKind('ok')
        setMsg(action === 'rerun'
          ? 'Re-run accepted — a NEW ticket for the same period was opened (the audit link old → new is in the reopen journal); this blocked row will leave the top tier.'
          : 'Void recorded — who and why are in the engine ledger; this row is no longer ranked as blocked.')
      } else {
        setMsgKind('error')
        setMsg(`Refused: ${err}`)
      }
    } catch (e) {
      setMsgKind('error')
      setMsg(`Exit call failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="wb-insp-exit" data-testid="inspection-exit">
      <div className="wb-insp-exit-ttl">Human exit for this rejected ticket</div>
      <div className="wb-sub">
        Re-run opens a NEW ticket for the same period (this blocked row stops being ranked
        as blocked). Void labels this rejected ticket with who and why — it does not
        un-reject the findings. Both need a reason.
      </div>
      <textarea
        className="wb-insp-exit-reason"
        data-testid="inspection-exit-reason"
        placeholder="Reason (required — who is signing: host; why now)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
      />
      <div className="wb-insp-exit-actions">
        <button className="wb-btn" data-testid="inspection-exit-rerun" disabled={busy !== null}
          onClick={() => { void run('rerun') }}>
          {busy === 'rerun' ? 'Re-running…' : 'Re-run this period'}
        </button>
        <button className="wb-btn" data-testid="inspection-exit-void" disabled={busy !== null}
          onClick={() => { void run('void') }}>
          {busy === 'void' ? 'Voiding…' : 'Void with a reason'}
        </button>
      </div>
      {msg !== '' && (
        <div className={msgKind === 'error' ? 'wb-sub' : 'wb-sub'}
          data-testid="inspection-exit-msg" data-kind={msgKind}>{msg}</div>
      )}
    </div>
  )
}
