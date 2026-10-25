/**
 * review-panel.tsx — the changed-files markdown reviewer panel (t261022-14).
 *
 * Layout (ticket requirement 1): a left rail (changed doc files → per-file TOC,
 * the comment list in document order with an Open/All/Resolved filter, the rail
 * collapses from its own control and never overlays the document) and the
 * rendered markdown on the right, split into blocks (requirement 2) with diff
 * marks (requirement 3), a minimap rail (requirement 4) and per-block comment
 * threads (requirement 5).
 *
 * Persistence (requirement 6): every thread lives in the ticket's lane file
 * `<lane>/.sandbar/review-comments.json` via the host's GET/PUT
 * `/wf/tickets/<id>/review-comments` route — this component holds the threads
 * in memory, PUTs the full list on every change, and reads it back on mount
 * (survives a panel reload). The header shows the lane file path and states
 * plainly that the lane agents read it (requirement 9).
 *
 * The visual baseline is the host-approved mock (~/Documents/markdown-reviewer-mock.html);
 * behaviour is reproduced, none of its code is copied. Product sources only —
 * no external code. All UI copy is English (host order 260925).
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import { getViewProject } from '../shared/view-project.ts'
import {
  buildBlocks,
  buildMinimap,
  buildToc,
  filterThreads,
  hasOnlyResolved,
  normalizeThreads,
  openCount,
  placeThreads,
  threadsForBlock,
  toStoreThread,
  type CommentFilter,
  type PanelBlock,
  type Thread,
} from './review-panel-model.ts'

const API = '/sandbar-workbench/api/wf'

/** Status badge text (same words the diff fold already uses). */
const STATUS_LABEL: Record<string, string> = {
  added: 'added', removed: 'removed', modified: 'modified', unchanged: '',
}
const KIND_LABEL: Record<string, string> = {
  heading: 'heading', paragraph: 'para', 'list-item': 'list', 'table-cell': 'cell',
  code: 'code', quote: 'quote', image: 'image', hr: 'hr', frontmatter: 'meta',
  'table-head': 'table', 'table-row': 'row',
}

function withProject(path: string): string {
  const viewProject = getViewProject()
  if (!viewProject) return path
  return path + (path.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(viewProject)
}

interface DiffFileEntry {
  path?: unknown
  kind?: unknown
  status?: unknown
  blocks?: unknown
}

interface DiffFace {
  files?: unknown
  worktree?: unknown
}

function isDocPath(p: string): boolean {
  return /\.(md|markdown)$/i.test(p)
}

/* ------------------------------------------------------------------ panel */

export interface ReviewerTarget { ticketId: string; path: string }

export function MarkdownReviewer({ target, onClose }: { target: ReviewerTarget; onClose: () => void }) {
  const { ticketId } = target
  const [path, setPath] = useState(target.path)
  const [docFiles, setDocFiles] = useState<string[]>([])
  const [rawBlocks, setRawBlocks] = useState<unknown>([])
  const [lane, setLane] = useState('')
  const [loadErr, setLoadErr] = useState('')
  const [threads, setThreads] = useState<Thread[]>([])
  const [dropped, setDropped] = useState(0)
  const [filter, setFilter] = useState<CommentFilter>('open')
  const [hideRemoved, setHideRemoved] = useState(false)
  const [railOpen, setRailOpen] = useState(true)
  const [composing, setComposing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [replying, setReplying] = useState<string | null>(null)
  const [replyDraft, setReplyDraft] = useState('')
  const [openThread, setOpenThread] = useState<string | null>(null)
  const [viewportIndex, setViewportIndex] = useState(0)
  const [saveState, setSaveState] = useState('')
  const docRef = useRef<HTMLDivElement | null>(null)

  const blocks: PanelBlock[] = useMemo(() => buildBlocks(rawBlocks), [rawBlocks])
  const commentsEndpoint = `${API}/tickets/${encodeURIComponent(ticketId)}/review-comments?path=${encodeURIComponent(path)}`

  // Load: diff face (blocks + lane worktree) + the persisted comment document.
  useEffect(() => {
    let dead = false
    void (async () => {
      try {
        const d = await fetch(withProject(`${API}/tickets/${encodeURIComponent(ticketId)}/diff`)).then((r) => r.json())
        if (dead) return
        if (d?.ok !== true) throw new Error(d?.error ?? 'diff read failed')
        const face = d.result as DiffFace
        setLane(typeof face.worktree === 'string' ? face.worktree : '')
        const files = (Array.isArray(face.files) ? face.files : []) as DiffFileEntry[]
        setDocFiles(files.filter((f) => f.kind === 'doc' && typeof f.path === 'string').map((f) => f.path as string))
        const file = files.find((f) => typeof f?.path === 'string' && f.path === path)
        if (file === undefined) throw new Error(`file not in the ticket's changed set: ${path}`)
        setRawBlocks(file.blocks ?? [])
        const c = await fetch(withProject(commentsEndpoint)).then((r) => r.json())
        if (dead) return
        if (c?.ok === true && c.result?.ok === true && c.result.doc !== null) {
          const n = normalizeThreads(c.result.doc.threads)
          setThreads(n.threads)
          setDropped(n.dropped)
        } else if (c?.ok === true && c.result?.ok === false) {
          setLoadErr(`lane comments unreadable: ${String(c.result.reason ?? '')}`)
        } // missing file = no comments yet (normal)
      } catch (err) {
        if (!dead) setLoadErr(String(err instanceof Error ? err.message : err))
      }
    })()
    return () => { dead = true }
  }, [ticketId, path, commentsEndpoint])

  /**
   * PUT the full thread list; the host merges by id (last write wins per
   * thread). Serialized through toStoreThread (arbitrate gen0 CF2): the wire
   * shape is the STORE record shape (anchor:{index,hash,neighbour}), not the
   * model's internal flat shape — a raw model thread is dropped by the store's
   * sanitizer, which is the exact defect this seam now prevents.
   */
  async function persist(next: Thread[]): Promise<void> {
    setSaveState('saving…')
    try {
      const res = await fetch(withProject(commentsEndpoint), {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ threads: next.map(toStoreThread) }),
      })
      const r = await res.json()
      if (r?.ok !== true) throw new Error(r?.error ?? 'save failed')
      setThreads(next)
      setSaveState('')
    } catch (err) {
      setSaveState(`save failed: ${String(err instanceof Error ? err.message : err)}`)
    }
  }

  function addComment(blockIndex: number): void {
    if (draft.trim() === '') return
    const b = blocks[blockIndex]
    if (b === undefined) return
    const thread: Thread = {
      id: `th-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      parentId: null,
      blockIndex,
      hash: b.hash,
      neighbour: b.neighbour,
      author: 'human',
      at: Date.now(),
      text: draft.trim(),
      resolved: false,
      replies: [],
    }
    setDraft('')
    setComposing(null)
    void persist([...threads, thread])
  }

  function addReply(threadId: string): void {
    if (replyDraft.trim() === '') return
    void persist(threads.map((t) => t.id === threadId
      ? { ...t, replies: [...t.replies, { author: 'human', at: Date.now(), text: replyDraft.trim() }] }
      : t))
    setReplyDraft('')
    setReplying(null)
  }

  function setResolved(threadId: string, resolved: boolean): void {
    void persist(threads.map((t) => (t.id === threadId ? { ...t, resolved } : t)))
  }

  // Viewport marker for the minimap: first block whose node is at/under the fold top.
  function onScroll(): void {
    const root = docRef.current
    if (root === null) return
    const top = root.getBoundingClientRect().top + 40
    const nodes = root.querySelectorAll('[data-block-index]')
    for (const n of nodes) {
      if ((n as HTMLElement).getBoundingClientRect().bottom >= top) {
        setViewportIndex(Number((n as HTMLElement).dataset.blockIndex))
        return
      }
    }
  }

  function jumpTo(index: number): void {
    const node = docRef.current?.querySelector(`[data-block-index="${index}"]`)
    if (node !== null && node !== undefined) node.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  const toc = useMemo(() => buildToc(blocks), [blocks])
  const minimap = useMemo(() => buildMinimap(blocks, threads), [blocks, threads])
  const visible = useMemo(() => blocks.filter((b) => !(hideRemoved && b.status === 'removed')), [blocks, hideRemoved])
  const placed = useMemo(() => placeThreads(blocks, threads), [blocks, threads])
  const listed = useMemo(() => filterThreads(placed.map((p) => p.thread), filter), [placed, filter])

  if (loadErr !== '' && blocks.length === 0) {
    return (
      <div className="wb-rv-wrap" data-testid="reviewer-panel">
        <div className="wb-rv-head">
          <span className="wb-rv-title">Markdown review — {path}</span>
          <button className="wb-rv-close" onClick={onClose} aria-label="Close reviewer">×</button>
        </div>
        <div className="wb-rv-err">{loadErr}</div>
      </div>
    )
  }

  const lastReplyOf = (t: Thread) => (t.replies.length > 0 ? t.replies[t.replies.length - 1] : undefined)

  return (
    <div className="wb-rv-wrap" data-testid="reviewer-panel">
      <div className="wb-rv-head">
        {railOpen ? (
          <button className="wb-rv-railtoggle" data-testid="rail-toggle" title="Collapse the rail"
            onClick={() => setRailOpen(false)}>◀ rail</button>
        ) : (
          <button className="wb-rv-railtoggle" data-testid="rail-toggle" title="Expand the rail"
            onClick={() => setRailOpen(true)}>▶ rail</button>
        )}
        <span className="wb-rv-title">Markdown review — {path}</span>
        <label className="wb-rv-hideremoved">
          <input type="checkbox" checked={hideRemoved} data-testid="hide-removed"
            onChange={(e) => setHideRemoved(e.target.checked)} /> hide removed
        </label>
        <button className="wb-rv-close" onClick={onClose} aria-label="Close reviewer">×</button>
      </div>
      {loadErr !== '' && <div className="wb-rv-err">{loadErr}</div>}
      {dropped > 0 && (
        <div className="wb-rv-note" data-testid="dropped-note">
          {dropped} unreadable comment entr{dropped === 1 ? 'y was' : 'ies were'} skipped (named here, never silent).
        </div>
      )}
      <div className={`wb-rv-body${railOpen ? '' : ' rail-closed'}`}>
        {/* left rail — never overlays the document (flex sibling, not absolute) */}
        {railOpen && (
          <div className="wb-rv-rail" data-testid="reviewer-rail">
            <div className="wb-rv-sec">
              <div className="wb-rv-secttl">Changed markdown files</div>
              {docFiles.map((f) => (
                <button key={f} className={`wb-rv-toc l1${f === path ? ' on' : ''}`} data-testid="rail-file"
                  title="Open in the reviewer"
                  onClick={() => { setPath(f); setComposing(null); setOpenThread(null) }}>
                  {f === path ? '▸ ' : ''}{f}
                </button>
              ))}
            </div>
            <div className="wb-rv-sec">
              <div className="wb-rv-secttl">Table of contents</div>
              {toc.length === 0 && <div className="wb-rv-empty">No h1/h2 headings.</div>}
              {toc.map((e) => (
                <button key={e.index} className={`wb-rv-toc l${e.level}`} data-testid="toc-entry"
                  onClick={() => jumpTo(e.index)}>{e.text}</button>
              ))}
            </div>
            <div className="wb-rv-sec">
              <div className="wb-rv-secttl">
                Comments
                <span className="wb-rv-filters" data-testid="comment-filter">
                  {(['open', 'all', 'resolved'] as const).map((f) => (
                    <button key={f} className={`wb-rv-filter${filter === f ? ' on' : ''}`}
                      onClick={() => setFilter(f)}>{f}</button>
                  ))}
                </span>
              </div>
              {listed.length === 0 && <div className="wb-rv-empty">No {filter === 'all' ? '' : `${filter} `}comments.</div>}
              {listed.map((t) => {
                const b = blocks[t.blockIndex]
                const last = lastReplyOf(t)
                return (
                  <div key={t.id} className={`wb-rv-thread${t.resolved ? ' resolved' : ''}`} data-testid="rail-thread"
                    onClick={() => { setOpenThread(t.id); if (t.blockIndex < blocks.length) jumpTo(t.blockIndex) }}>
                    <span className={`wb-d-badge${t.resolved ? '' : ''}`} data-s={t.resolved ? 'unchanged' : 'added'}>
                      {b !== undefined ? KIND_LABEL[b.type] ?? b.type : 'outdated'}
                    </span>
                    <span className="wb-rv-snippet">{t.text.slice(0, 80)}</span>
                    {last !== undefined && <span className="wb-rv-lastreply">↩ {last.text.slice(0, 60)}</span>}
                  </div>
                )
              })}
            </div>
            <div className="wb-rv-sec wb-rv-laneinfo" data-testid="lane-info">
              <div className="wb-rv-secttl">Where this lives</div>
              <code className="wb-rv-lanepath">{lane !== '' ? `${lane}/.sandbar/review-comments.json` : 'lane file'}</code>
              <div className="wb-rv-lanenote">The lane's developer and integration agents read this file at their next turn and act on open threads. Resolving is yours; they leave thread state as they find it.</div>
            </div>
          </div>
        )}
        {/* minimap — a thin rail beside the document */}
        <div className="wb-rv-minimap" data-testid="minimap"
          onScroll={undefined}>
          {minimap.map((m) => (
            <button key={m.index} className="wb-rv-mmark" data-s={m.status}
              data-current={m.index === viewportIndex || undefined}
              data-testid="minimap-mark"
              title={`${STATUS_LABEL[m.status] || 'block'} #${m.index}${m.open > 0 ? ` · ${m.open} open` : ''}${m.onlyResolved ? ' · resolved' : ''}`}
              onClick={() => {
                jumpTo(m.index)
                const ts = threadsForBlock(threads, m.index)
                if (ts.length > 0) setOpenThread(ts[0].id)
              }}>
              {m.open > 0 && <span className="wb-rv-mcount">{m.open}</span>}
              {m.open === 0 && m.onlyResolved && <span className="wb-rv-mcount grey">✓</span>}
            </button>
          ))}
        </div>
        {/* the document, one node per block */}
        <div className="wb-rv-doc wb-md" ref={docRef} onScroll={onScroll} data-testid="reviewer-doc">
          {visible.map((b) => {
            const open = openCount(threads, b.index)
            const grey = hasOnlyResolved(threads, b.index)
            return (
              <div key={b.index} data-block-index={b.index}
                className={`wb-rv-block s-${b.status}${b.type === 'table-cell' ? ' cell' : ''}`}
                data-testid="reviewer-block" data-status={b.status}>
                <div className="wb-rv-bhead">
                  <span className="wb-d-badge" data-s={b.status}>{STATUS_LABEL[b.status]}</span>
                  <span className="wb-rv-btype">{KIND_LABEL[b.type] ?? b.type}</span>
                  {(open > 0 || grey) && (
                    <button className={`wb-rv-badge${grey ? ' grey' : ''}`} data-testid="block-badge"
                      onClick={() => { const ts = threadsForBlock(threads, b.index); if (ts.length > 0) setOpenThread(ts[0].id) }}>
                      {grey ? '✓ resolved' : `${open} open`}
                    </button>
                  )}
                  <button className="wb-rv-addc" title="Comment on this block"
                    onClick={() => { setComposing(composing === b.index ? null : b.index); setDraft('') }}>+ comment</button>
                </div>
                <div className="wb-rv-btext">
                  {b.inlineOps !== undefined ? (
                    // word-level marks: struck-out red deletions, green insertions
                    <span data-testid="inline-marks">
                      {b.inlineOps.map((op, i) => (
                        <span key={i}>
                          {op.del !== undefined && <del className="wb-rv-del">{op.del}</del>}
                          {op.add !== undefined && <ins className="wb-rv-ins">{op.add}</ins>}
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span dangerouslySetInnerHTML={{ __html: renderMarkdown(b.text) }} />
                  )}
                </div>
                {composing === b.index && (
                  <div className="wb-rv-compose" data-testid="composer">
                    <textarea value={draft} autoFocus
                      placeholder="Comment on this block — saved to the lane file for the lane agents"
                      onChange={(e) => setDraft(e.target.value)} />
                    <div className="wb-rv-cbtns">
                      <button className="wb-rv-primary" onClick={() => addComment(b.index)}>Comment</button>
                      <button onClick={() => { setComposing(null); setDraft('') }}>Cancel</button>
                    </div>
                  </div>
                )}
                {threadsForBlock(threads, b.index).map((t) => (
                  (openThread === t.id || t.resolved === false) && (
                    <div key={t.id} className={`wb-rv-threadbox${t.resolved ? ' resolved' : ''}`} data-testid="thread">
                      <div className="wb-rv-threadhead">
                        <b>{t.author}</b> <span className="wb-rv-time">{new Date(t.at).toLocaleString()}</span>
                        <span className="wb-rv-spacer" />
                        {t.resolved
                          ? <button data-testid="reopen" onClick={() => setResolved(t.id, false)}>Reopen</button>
                          : <button data-testid="resolve" onClick={() => setResolved(t.id, true)}>Resolve</button>}
                      </div>
                      <div className="wb-rv-threadtext">{t.text}</div>
                      {t.replies.map((rep, i) => (
                        <div key={i} className="wb-rv-reply">↩ <b>{rep.author}</b> {rep.text}</div>
                      ))}
                      {replying === t.id ? (
                        <div className="wb-rv-compose">
                          <textarea value={replyDraft} autoFocus onChange={(e) => setReplyDraft(e.target.value)} />
                          <div className="wb-rv-cbtns">
                            <button className="wb-rv-primary" onClick={() => addReply(t.id)}>Reply</button>
                            <button onClick={() => { setReplying(null); setReplyDraft('') }}>Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <button className="wb-rv-addc" data-testid="reply-btn" onClick={() => { setReplying(t.id); setReplyDraft('') }}>Reply</button>
                      )}
                    </div>
                  )
                ))}
              </div>
            )
          })}
          {/* outdated threads render at the end of the file, never dropped */}
          {placed.filter((p) => p.resolution.kind === 'outdated').map(({ thread }) => (
            <div key={thread.id} className="wb-rv-threadbox outdated" data-testid="outdated-thread">
              <div className="wb-rv-threadhead"><b>{thread.author}</b>
                <span className="wb-rv-outdated-tag">outdated — the commented block has changed (hash and neighbour no longer match)</span>
                <span className="wb-rv-spacer" />
                {thread.resolved
                  ? <button data-testid="reopen" onClick={() => setResolved(thread.id, false)}>Reopen</button>
                  : <button data-testid="resolve" onClick={() => setResolved(thread.id, true)}>Resolve</button>}
              </div>
              <div className="wb-rv-threadtext">{thread.text}</div>
              {thread.replies.map((rep, i) => <div key={i} className="wb-rv-reply">↩ <b>{rep.author}</b> {rep.text}</div>)}
            </div>
          ))}
        </div>
      </div>
      {saveState !== '' && <div className="wb-rv-savestate" data-testid="save-state">{saveState}</div>}
    </div>
  )
}
