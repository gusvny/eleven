/**
 * review-panel.tsx — the changed-files reviewer panel (t261022-14 markdown
 * blocks; t261028-23 line-based diffs for every other file).
 *
 * ONE panel, two render modes, one comment machinery:
 *   - block mode (`.md`/`.markdown`, unchanged from t261022-14): rendered
 *     markdown split into blocks, block diff marks, per-block threads;
 *   - line mode (any other changed file, t261028-23): the unified diff parsed
 *     into rows with old/new line numbers and +/- markers, threads rendered
 *     inline under the row they anchor to.
 * Both modes share the rail (changed files → navigation → comments with the
 * Open/All/Resolved filter → where this lives), the ThreadBox face, the
 * composer / reply / resolve affordances, the back-to-changes behaviour
 * (onClose) and the lane-file persistence seam.
 *
 * Persistence (requirement 6): every thread lives in the ticket's lane file
 * `<lane>/.sandbar/review-comments.json` via the host's GET/PUT
 * `/wf/tickets/<id>/review-comments` route — this component holds the threads
 * in memory, PUTs the full list on every change, and reads it back on mount
 * (survives a panel reload). Threads carry their owning file path, so one
 * document serves every reviewed file of the lane without mixing them.
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
  scopeThreads,
  threadsForBlock,
  toStoreThread,
  type CommentFilter,
  type PanelBlock,
  type Thread,
} from './review-panel-model.ts'
import { parseUnifiedDiff, rowAnchor, type DiffParse, type DiffRow } from './diff-rows-model.ts'
import {
  buildLineRender,
  filterLineThreads,
  hasOnlyResolvedForRow,
  hunkToc,
  normalizeLineThreads,
  openCountForRow,
  placeLineThreads,
  toStoreLineThread,
  type LineThread,
} from './review-line-model.ts'
import { ThreadBox } from './review-thread-box.tsx'

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
  unified?: unknown
  unifiedTruncated?: unknown
  note?: unknown
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

export interface ReviewerProps {
  target: ReviewerTarget
  onClose: () => void
  /**
   * Called when the clicked file is not part of the ticket's changed set (a
   * status-card or reference file). The caller opens its read-only viewer —
   * the reviewer never pretends to review a file it has no diff for.
   */
  onFallback?: (ticketId: string, path: string) => void
}

export function MarkdownReviewer({ target, onClose, onFallback }: ReviewerProps) {
  const { ticketId } = target
  const [path, setPath] = useState(target.path)
  const [files, setFiles] = useState<DiffFileEntry[]>([])
  const [entry, setEntry] = useState<DiffFileEntry | undefined>(undefined)
  const [rawBlocks, setRawBlocks] = useState<unknown>([])
  const [parse, setParse] = useState<DiffParse | undefined>(undefined)
  const [lane, setLane] = useState('')
  const [loadErr, setLoadErr] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [threads, setThreads] = useState<Thread[]>([])
  const [dropped, setDropped] = useState(0)
  const [lineThreads, setLineThreads] = useState<LineThread[]>([])
  const [lineDropped, setLineDropped] = useState(0)
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

  const lineMode = !isDocPath(path)
  const blocks: PanelBlock[] = useMemo(() => buildBlocks(rawBlocks), [rawBlocks])
  const commentsEndpoint = `${API}/tickets/${encodeURIComponent(ticketId)}/review-comments?path=${encodeURIComponent(path)}`

  // Load: diff face (blocks / unified diff + lane worktree) + the persisted
  // comment document. A missing file entry is named, never silently blank.
  useEffect(() => {
    let dead = false
    void (async () => {
      setLoadErr('')
      setLoaded(false)
      setRawBlocks([])
      setParse(undefined)
      setEntry(undefined)
      setThreads([])
      setDropped(0)
      setLineThreads([])
      setLineDropped(0)
      setComposing(null)
      setOpenThread(null)
      try {
        const d = await fetch(withProject(`${API}/tickets/${encodeURIComponent(ticketId)}/diff`)).then((r) => r.json())
        if (dead) return
        if (d?.ok !== true) throw new Error(d?.error ?? 'diff read failed')
        const face = d.result as DiffFace
        setLane(typeof face.worktree === 'string' ? face.worktree : '')
        const list = (Array.isArray(face.files) ? face.files : []) as DiffFileEntry[]
        setFiles(list)
        const file = list.find((f) => typeof f?.path === 'string' && f.path === path)
        if (file === undefined) throw new Error(`file not in the ticket's changed set: ${path}`)
        setEntry(file)
        if (isDocPath(path)) setRawBlocks(file.blocks ?? [])
        else setParse(parseUnifiedDiff(file.unified))
        setLoaded(true)
        const c = await fetch(withProject(commentsEndpoint)).then((r) => r.json())
        if (dead) return
        if (c?.ok === true && c.result?.ok === true && c.result.doc !== null) {
          // One lane document holds every reviewed file's threads: keep this
          // file's own (a thread without `path` belongs to the document path).
          const own = scopeThreads(c.result.doc.threads, path, typeof c.result.doc.path === 'string' ? c.result.doc.path : '')
          if (isDocPath(path)) {
            const n = normalizeThreads(own)
            setThreads(n.threads)
            setDropped(n.dropped)
          } else {
            const n = normalizeLineThreads(own)
            setLineThreads(n.threads)
            setLineDropped(n.dropped)
          }
        } else if (c?.ok === true && c.result?.ok === false) {
          setLoadErr(`lane comments unreadable: ${String(c.result.reason ?? '')}`)
        } // missing file = no comments yet (normal)
      } catch (err) {
        if (!dead) setLoadErr(String(err instanceof Error ? err.message : err))
      }
    })()
    return () => { dead = true }
  }, [ticketId, path, commentsEndpoint])

  /** PUT the given thread records; true when the lane file took them. */
  async function putThreads(payload: Record<string, unknown>[]): Promise<boolean> {
    setSaveState('saving…')
    try {
      const res = await fetch(withProject(commentsEndpoint), {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ threads: payload }),
      })
      const r = await res.json()
      if (r?.ok !== true) throw new Error(r?.error ?? 'save failed')
      setSaveState('')
      return true
    } catch (err) {
      setSaveState(`save failed: ${String(err instanceof Error ? err.message : err)}`)
      return false
    }
  }

  /**
   * Persist the full block-thread list through toStoreThread (arbitrate gen0
   * CF2): the wire shape is the STORE record shape (anchor:{index,hash,neighbour}),
   * not the model's internal flat shape. The owning path is stamped on.
   * Local state follows the store (a failed save keeps the old list, as before).
   */
  async function persist(next: Thread[]): Promise<void> {
    if (await putThreads(next.map((t) => toStoreThread(t, path)))) setThreads(next)
  }

  /** Same seam for line threads (anchor:{kind:'line',side,line,hunk,contextHash}). */
  async function persistLines(next: LineThread[]): Promise<void> {
    if (await putThreads(next.map((t) => toStoreLineThread(t, path)))) setLineThreads(next)
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

  function addLineComment(row: DiffRow): void {
    if (draft.trim() === '') return
    const anchor = rowAnchor(row)
    if (anchor === null) return
    const thread: LineThread = {
      id: `ln-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      parentId: null,
      anchor,
      author: 'human',
      at: Date.now(),
      text: draft.trim(),
      resolved: false,
      replies: [],
    }
    setDraft('')
    setComposing(null)
    void persistLines([...lineThreads, thread])
  }

  function addReply(threadId: string): void {
    if (replyDraft.trim() === '') return
    const text = replyDraft.trim()
    setReplyDraft('')
    setReplying(null)
    if (lineMode) {
      void persistLines(lineThreads.map((t) => t.id === threadId
        ? { ...t, replies: [...t.replies, { author: 'human', at: Date.now(), text }] }
        : t))
      return
    }
    void persist(threads.map((t) => t.id === threadId
      ? { ...t, replies: [...t.replies, { author: 'human', at: Date.now(), text }] }
      : t))
  }

  function setResolved(threadId: string, resolved: boolean): void {
    if (lineMode) {
      void persistLines(lineThreads.map((t) => (t.id === threadId ? { ...t, resolved } : t)))
      return
    }
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

  function jumpToRow(index: number): void {
    const node = docRef.current?.querySelector(`[data-row-index="${index}"]`)
    if (node !== null && node !== undefined) node.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  const toc = useMemo(() => buildToc(blocks), [blocks])
  const minimap = useMemo(() => buildMinimap(blocks, threads), [blocks, threads])
  const visible = useMemo(() => blocks.filter((b) => !(hideRemoved && b.status === 'removed')), [blocks, hideRemoved])
  const placed = useMemo(() => placeThreads(blocks, threads), [blocks, threads])
  const listed = useMemo(() => filterThreads(placed.map((p) => p.thread), filter), [placed, filter])

  const lineRows = parse !== undefined && parse.ok ? parse.rows : []
  const lineHunks = parse !== undefined && parse.ok ? parse.hunks : []
  const lineAdded = parse !== undefined && parse.ok ? parse.added : 0
  const lineRemoved = parse !== undefined && parse.ok ? parse.removed : 0
  const placedLines = useMemo(() => placeLineThreads(lineRows, lineThreads), [parse, lineThreads])
  const lineRender = useMemo(() => buildLineRender(lineRows, lineHunks, lineThreads), [parse, lineThreads])
  const lineListed = useMemo(() => filterLineThreads(placedLines.map((p) => p.thread), filter), [placedLines, filter])
  const lineToc = useMemo(() => hunkToc(lineHunks), [parse])

  // Files the rail offers: every changed file in line mode, the doc files only
  // in block mode (unchanged t261022-14 behaviour).
  const railFiles = useMemo(() => (lineMode
    ? files.filter((f) => typeof f.path === 'string').map((f) => f.path as string)
    : files.filter((f) => f.kind === 'doc' && typeof f.path === 'string').map((f) => f.path as string)),
  [files, lineMode])

  if (!loaded && loadErr !== '') {
    return (
      <div className="wb-rv-wrap" data-testid="reviewer-panel">
        <div className="wb-rv-head">
          <span className="wb-rv-title">{lineMode ? 'Line review' : 'Markdown review'} — {path}</span>
          <button className="wb-rv-close" onClick={onClose} aria-label="Close reviewer">×</button>
        </div>
        <div className="wb-rv-err">{loadErr}</div>
        {onFallback !== undefined && (
          <div className="wb-rv-note">
            This file is not in the ticket's changed set.
            {' '}
            <button className="wb-rv-railtoggle" data-testid="open-read-only"
              onClick={() => onFallback(ticketId, path)}>Open read-only view</button>
          </div>
        )}
      </div>
    )
  }

  const lastReplyOf = (t: { replies: { text: string }[] }) => (t.replies.length > 0 ? t.replies[t.replies.length - 1] : undefined)

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
        <span className="wb-rv-title">{lineMode ? 'Line review' : 'Markdown review'} — {path}</span>
        {lineMode ? (
          <>
            <span className="wb-rv-stat" data-testid="diff-stat">
              <span className="add">+{lineAdded}</span>{' '}<span className="del">−{lineRemoved}</span>
            </span>
            <span className="wb-rv-ticket" data-testid="review-ticket-id" title="Ticket">{ticketId}</span>
          </>
        ) : (
          <label className="wb-rv-hideremoved">
            <input type="checkbox" checked={hideRemoved} data-testid="hide-removed"
              onChange={(e) => setHideRemoved(e.target.checked)} /> hide removed
          </label>
        )}
        <button className="wb-rv-close" onClick={onClose} aria-label="Close reviewer">×</button>
      </div>
      {loadErr !== '' && <div className="wb-rv-err">{loadErr}</div>}
      {!lineMode && dropped > 0 && (
        <div className="wb-rv-note" data-testid="dropped-note">
          {dropped} unreadable comment entr{dropped === 1 ? 'y was' : 'ies were'} skipped (named here, never silent).
        </div>
      )}
      {lineMode && lineDropped > 0 && (
        <div className="wb-rv-note" data-testid="dropped-note">
          {lineDropped} unreadable comment entr{lineDropped === 1 ? 'y was' : 'ies were'} skipped (named here, never silent).
        </div>
      )}
      {lineMode && entry !== undefined && entry.unifiedTruncated === true && (
        <div className="wb-rv-note" data-testid="diff-truncated">
          Diff truncated by the diff face{typeof entry.note === 'string' && entry.note !== '' ? `: ${entry.note}` : ''}.
        </div>
      )}
      <div className={`wb-rv-body${railOpen ? '' : ' rail-closed'}`}>
        {/* left rail — never overlays the document (flex sibling, not absolute) */}
        {railOpen && (
          <div className="wb-rv-rail" data-testid="reviewer-rail">
            <div className="wb-rv-sec">
              <div className="wb-rv-secttl">{lineMode ? 'Changed files' : 'Changed markdown files'}</div>
              {railFiles.map((f) => (
                <button key={f} className={`wb-rv-toc l1${f === path ? ' on' : ''}`} data-testid="rail-file"
                  title="Open in the reviewer"
                  onClick={() => { setPath(f); setComposing(null); setOpenThread(null) }}>
                  {f === path ? '▸ ' : ''}{f}
                </button>
              ))}
            </div>
            {lineMode ? (
              <div className="wb-rv-sec">
                <div className="wb-rv-secttl">Diff hunks</div>
                {lineToc.length === 0 && <div className="wb-rv-empty">No hunks to show.</div>}
                {lineToc.map((h) => (
                  <button key={h.id} className="wb-rv-toc l1" data-testid="toc-entry"
                    title={h.label} onClick={() => jumpToRow(h.row)}>{h.label}</button>
                ))}
              </div>
            ) : (
              <div className="wb-rv-sec">
                <div className="wb-rv-secttl">Table of contents</div>
                {toc.length === 0 && <div className="wb-rv-empty">No h1/h2 headings.</div>}
                {toc.map((e) => (
                  <button key={e.index} className={`wb-rv-toc l${e.level}`} data-testid="toc-entry"
                    onClick={() => jumpTo(e.index)}>{e.text}</button>
                ))}
              </div>
            )}
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
              {lineMode ? (
                <>
                  {lineListed.length === 0 && <div className="wb-rv-empty">No {filter === 'all' ? '' : `${filter} `}comments.</div>}
                  {lineListed.map((t) => {
                    const at = placedLines.find((p) => p.thread.id === t.id)
                    const last = lastReplyOf(t)
                    return (
                      <div key={t.id} className={`wb-rv-thread${t.resolved ? ' resolved' : ''}`} data-testid="rail-thread"
                        onClick={() => {
                          setOpenThread(t.id)
                          if (at !== undefined && at.resolution.row !== null) jumpToRow(at.resolution.row)
                        }}>
                        <span className="wb-d-badge" data-s={t.resolved ? 'unchanged' : 'added'}>
                          {at !== undefined && at.resolution.row !== null ? `line ${t.anchor.line}` : 'outdated'}
                        </span>
                        <span className="wb-rv-snippet">{t.text.slice(0, 80)}</span>
                        {last !== undefined && <span className="wb-rv-lastreply">↩ {last.text.slice(0, 60)}</span>}
                      </div>
                    )
                  })}
                </>
              ) : (
                <>
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
                </>
              )}
            </div>
            <div className="wb-rv-sec wb-rv-laneinfo" data-testid="lane-info">
              <div className="wb-rv-secttl">Where this lives</div>
              <code className="wb-rv-lanepath">{lane !== '' ? `${lane}/.sandbar/review-comments.json` : 'lane file'}</code>
              <div className="wb-rv-lanenote">The lane's developer and integration agents read this file at their next turn and act on open threads. Resolving is yours; they leave thread state as they find it.</div>
            </div>
          </div>
        )}
        {/* minimap — a thin rail beside the document (block mode) */}
        {!lineMode && (
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
        )}
        {lineMode ? (
          /* the diff, one node per hunk header / row / outdated thread */
          <div className="wb-rv-doc wb-rv-diffdoc" ref={docRef} data-testid="reviewer-doc">
            {parse !== undefined && !parse.ok && (
              <div className="wb-rv-empty" data-testid="diff-empty" data-state={parse.state}>
                No line diff to show: {parse.reason}
              </div>
            )}
            {lineRender.map((item) => {
              if (item.kind === 'hunk') {
                return (
                  <div className="wb-rv-hunk" data-testid="diff-hunk" key={`h-${item.hunk.id}`}>
                    {item.hunk.label}
                  </div>
                )
              }
              if (item.kind === 'outdated') {
                const t = item.thread
                return (
                  <ThreadBox key={t.id} thread={t} outdated="outdated — the commented line has changed (line text or hunk no longer match)"
                    replying={replying === t.id} replyDraft={replyDraft}
                    onReplyDraft={setReplyDraft}
                    onStartReply={() => { setReplying(t.id); setReplyDraft('') }}
                    onCancelReply={() => { setReplying(null); setReplyDraft('') }}
                    onSubmitReply={() => addReply(t.id)}
                    onSetResolved={(v) => setResolved(t.id, v)} />
                )
              }
              const row = item.row
              const open = openCountForRow(placedLines, row.index)
              const grey = hasOnlyResolvedForRow(placedLines, row.index)
              return (
                <div key={row.key} className={`wb-rv-line s-${row.kind}`}
                  data-testid="diff-line" data-row-index={row.index} data-kind={row.kind}
                  data-old-line={row.oldLine ?? undefined} data-new-line={row.newLine ?? undefined}
                  data-hunk={row.hunk}>
                  <div className="wb-rv-linerow">
                    <span className="wb-rv-ln wb-rv-ln-old">{row.oldLine ?? ''}</span>
                    <span className="wb-rv-ln wb-rv-ln-new">{row.newLine ?? ''}</span>
                    <span className="wb-rv-mark">{row.kind === 'added' ? '+' : row.kind === 'removed' ? '−' : ' '}</span>
                    <span className="wb-rv-code">{row.text === '' ? '\u00a0' : row.text}</span>
                    <span className="wb-rv-lineactions">
                      {(open > 0 || grey) && (
                        <button className={`wb-rv-badge${grey ? ' grey' : ''}`} data-testid="line-badge"
                          onClick={() => { const ts = item.threads; if (ts.length > 0) setOpenThread(ts[0].id) }}>
                          {grey ? '✓ resolved' : `${open} open`}
                        </button>
                      )}
                      <button className="wb-rv-addc" title="Comment on this line" data-testid="line-comment-btn"
                        onClick={() => { setComposing(composing === row.index ? null : row.index); setDraft('') }}>+ comment</button>
                    </span>
                  </div>
                  {composing === row.index && (
                    <div className="wb-rv-compose" data-testid="composer">
                      <textarea value={draft} autoFocus
                        placeholder="Comment on this line — saved to the lane file for the lane agents"
                        onChange={(e) => setDraft(e.target.value)} />
                      <div className="wb-rv-cbtns">
                        <button className="wb-rv-primary" onClick={() => addLineComment(row)}>Comment</button>
                        <button onClick={() => { setComposing(null); setDraft('') }}>Cancel</button>
                      </div>
                    </div>
                  )}
                  {item.threads.map((t) => (
                    (openThread === t.id || t.resolved === false) && (
                      <ThreadBox key={t.id} thread={t}
                        replying={replying === t.id} replyDraft={replyDraft}
                        onReplyDraft={setReplyDraft}
                        onStartReply={() => { setReplying(t.id); setReplyDraft('') }}
                        onCancelReply={() => { setReplying(null); setReplyDraft('') }}
                        onSubmitReply={() => addReply(t.id)}
                        onSetResolved={(v) => setResolved(t.id, v)} />
                    )
                  ))}
                </div>
              )
            })}
          </div>
        ) : (
          /* the document, one node per block */
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
                      <ThreadBox key={t.id} thread={t}
                        replying={replying === t.id} replyDraft={replyDraft}
                        onReplyDraft={setReplyDraft}
                        onStartReply={() => { setReplying(t.id); setReplyDraft('') }}
                        onCancelReply={() => { setReplying(null); setReplyDraft('') }}
                        onSubmitReply={() => addReply(t.id)}
                        onSetResolved={(v) => setResolved(t.id, v)} />
                    )
                  ))}
                </div>
              )
            })}
            {/* outdated threads render at the end of the document, never dropped */}
            {placed.filter((p) => p.resolution.kind === 'outdated').map(({ thread }) => (
              <ThreadBox key={thread.id} thread={thread}
                outdated="outdated — the commented block has changed (hash and neighbour no longer match)"
                replying={replying === thread.id} replyDraft={replyDraft}
                onReplyDraft={setReplyDraft}
                onStartReply={() => { setReplying(thread.id); setReplyDraft('') }}
                onCancelReply={() => { setReplying(null); setReplyDraft('') }}
                onSubmitReply={() => addReply(thread.id)}
                onSetResolved={(v) => setResolved(thread.id, v)} />
            ))}
          </div>
        )}
      </div>
      {saveState !== '' && <div className="wb-rv-savestate" data-testid="save-state">{saveState}</div>}
    </div>
  )
}
