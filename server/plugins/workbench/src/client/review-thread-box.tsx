/**
 * review-thread-box.tsx — the ONE thread face of the changed-files reviewer
 * (t261028-23 extracted it out of review-panel.tsx so the markdown block mode
 * and the code line mode share it instead of growing a second look).
 *
 * The markup, class names and test anchors are the markdown reviewer's own
 * (t261022-14); the line mode only passes a different thread object. Reply
 * draft state stays with the caller (one open composer at a time, as before).
 */

import type { ReactElement } from 'react'

/** The fields this face needs — satisfied by both the block and line thread models. */
export interface ThreadFace {
  id: string
  author: string
  at: number
  text: string
  resolved: boolean
  replies: { author: string; at: number; text: string }[]
}

export interface ThreadBoxProps {
  thread: ThreadFace
  /** Non-null marks an outdated thread and carries the tag text (English). */
  outdated?: string | null
  replying: boolean
  replyDraft: string
  onReplyDraft: (v: string) => void
  onStartReply: () => void
  onCancelReply: () => void
  /** Called with the trimmed reply text when the reply composer is submitted. */
  onSubmitReply: (text: string) => void
  onSetResolved: (v: boolean) => void
}

export function ThreadBox({
  thread, outdated = null, replying, replyDraft,
  onReplyDraft, onStartReply, onCancelReply, onSubmitReply, onSetResolved,
}: ThreadBoxProps): ReactElement {
  const tag = outdated ?? null
  return (
    <div className={`wb-rv-threadbox${thread.resolved ? ' resolved' : ''}${tag !== null ? ' outdated' : ''}`}
      data-testid={tag !== null ? 'outdated-thread' : 'thread'} data-thread-id={thread.id}>
      <div className="wb-rv-threadhead">
        <b>{thread.author}</b> <span className="wb-rv-time">{new Date(thread.at).toLocaleString()}</span>
        {tag !== null && <span className="wb-rv-outdated-tag">{tag}</span>}
        <span className="wb-rv-spacer" />
        {thread.resolved
          ? <button data-testid="reopen" onClick={() => onSetResolved(false)}>Reopen</button>
          : <button data-testid="resolve" onClick={() => onSetResolved(true)}>Resolve</button>}
      </div>
      <div className="wb-rv-threadtext">{thread.text}</div>
      {thread.replies.map((rep, i) => (
        <div key={i} className="wb-rv-reply">↩ <b>{rep.author}</b> {rep.text}</div>
      ))}
      {replying ? (
        <div className="wb-rv-compose">
          <textarea value={replyDraft} autoFocus onChange={(e) => onReplyDraft(e.target.value)} />
          <div className="wb-rv-cbtns">
            <button className="wb-rv-primary" onClick={() => onSubmitReply(replyDraft.trim())}>Reply</button>
            <button onClick={onCancelReply}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="wb-rv-addc" data-testid="reply-btn" onClick={onStartReply}>Reply</button>
      )}
    </div>
  )
}
