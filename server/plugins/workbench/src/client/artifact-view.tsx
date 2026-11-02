/**
 * artifact-view.tsx — the six built-in artifact views (epic artifact-face, slice 3,
 * ticket t261030-36). One view draws ONE declared artifact. The frame owns the row list,
 * the order, the byte link and the machine verdict; a view never adds, hides or reorders
 * a row.
 *
 * Every decision lives in `artifact-view-model.ts`; this file is the React projection.
 * A text read starts only when the body is opened, and stops on close, on unmount and on a
 * ticket change (one AbortController per read). An image body uses the shared `Lightbox`
 * that the screenshot-evidence list also uses.
 */
import { useEffect, useState } from 'react'
import { renderMarkdown } from '../../../knowledge/src/client/markdown.ts'
import type { ArtifactViewRow } from './artifact-face-model.ts'
import { ARTIFACT_VIEW_CSS } from './artifact-view-css.ts'
import { Lightbox } from './lightbox.tsx'
import {
  buildDiffView, buildLedgerView, buildStructureView, buildTextView, planArtifactBody,
  readArtifactText, runBodyRead, textLooksBinary, VIEW_TITLE,
  type ArtifactBodyPlan, type ArtifactFetch, type DiffBody, type LedgerBody, type LedgerEntryView,
  type StructureBody, type TreeNode, type ViewKind,
} from './artifact-view-model.ts'


type ReadPhase = 'idle' | 'loading' | 'ready' | 'error'

interface ReadState {
  phase: ReadPhase
  text?: string
  message?: string
}

/**
 * Read one text row. The effect aborts on close, on unmount and on a link change; a retry
 * bumps a nonce so the same link is read again on demand.
 */
function useArtifactRead(plan: ArtifactBodyPlan, open: boolean): ReadState & { retry: () => void } {
  const [state, setState] = useState<ReadState>({ phase: 'idle' })
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let live = true
    setState({ phase: 'loading' })
    const fetchImpl = globalThis.fetch as unknown as ArtifactFetch
    runBodyRead(plan, (href, signal) => readArtifactText(href, fetchImpl, signal), controller.signal)
      .then((result) => {
        if (!live) return
        if (result === null) { setState({ phase: 'idle' }); return }
        if (result.ok) { setState({ phase: 'ready', text: result.text }); return }
        if (result.kind === 'aborted') return
        setState({ phase: 'error', message: result.message })
      })
      .catch((err) => {
        if (live) setState({ phase: 'error', message: err instanceof Error ? err.message : String(err) })
      })
    return () => { live = false; controller.abort() }
  }, [open, plan.href, plan.read, nonce])
  return { ...state, retry: () => setNonce(n => n + 1) }
}

export function ArtifactView({ row, ticketId, bytesHref }: {
  row: ArtifactViewRow
  ticketId: string
  bytesHref: string | null
}) {
  const plan = planArtifactBody(row, bytesHref)
  // Defensive: the frame's call site already gates on the same rule.
  if (!plan.body) return null
  const kind = plan.kind
  return (
    <div className="wb-av" data-view-kind={kind} data-view-state={plan.read === 'text' ? 'lazy' : 'ready'}
      data-testid={`artifact-view-${kind}`} data-ticket={ticketId}>
      <style>{ARTIFACT_VIEW_CSS}</style>
      {kind === 'image' && (plan.read === 'image'
        ? <ImageBody row={row} plan={plan} />
        : <ExternalBody row={row} plan={plan} reason={plan.why} />)}
      {kind === 'external' && <ExternalBody row={row} plan={plan} reason="" />}
      {plan.read === 'text' && <TextBody row={row} plan={plan} />}
    </div>
  )
}

function ImageBody({ row, plan }: { row: ArtifactViewRow; plan: ArtifactBodyPlan }) {
  const [open, setOpen] = useState(false)
  const [broken, setBroken] = useState(false)
  const items = [{ name: row.title, src: plan.href, alt: row.title }]
  return (
    <div className="wb-av-body">
      {broken
        ? <div className="wb-av-state">The image could not be loaded. Use the original link on the row.</div>
        : (
            <button type="button" className="wb-av-thumb" aria-label={`Zoom in ${row.title}`}
              onClick={() => setOpen(true)}>
              <img className="wb-av-img" loading="lazy" alt={row.title} src={plan.href}
                onError={() => setBroken(true)} />
            </button>
          )}
      {!broken && <div className="wb-av-note">Click the image to zoom.</div>}
      {open && !broken && (
        <Lightbox items={items} index={0} onClose={() => setOpen(false)}
          onNav={() => setOpen(true)} kindLabel="Image" />
      )}
    </div>
  )
}

function ExternalBody({ row, plan, reason }: {
  row: ArtifactViewRow
  plan: ArtifactBodyPlan
  reason: string
}) {
  return (
    <div className="wb-av-body">
      <div className="wb-av-strong">{row.title}</div>
      <div className="wb-av-source">{row.sourceLabel}</div>
      <div className="wb-av-meta">{[plan.sizeText, plan.timeText].filter(x => x !== '').join(' · ')}</div>
      {reason !== '' && <div className="wb-av-note">{reason}</div>}
      {row.openHint !== '' && <div className="wb-av-note">Open with: {row.openHint}</div>}
      {plan.href !== '' && (
        <a className="wb-av-action" href={plan.href} target="_blank" rel="noreferrer">Download original</a>
      )}
    </div>
  )
}

function TextBody({ row, plan }: { row: ArtifactViewRow; plan: ArtifactBodyPlan }) {
  const [open, setOpen] = useState(false)
  const read = useArtifactRead(plan, open)
  const title = VIEW_TITLE[plan.kind]
  return (
    <div className="wb-av-body">
      <button type="button" className="wb-av-toggle" aria-expanded={open}
        data-read-state={read.phase} onClick={() => setOpen(value => !value)}>
        {open ? `Hide ${title}` : `Show ${title}`}
      </button>
      {open && read.phase === 'loading' && <div className="wb-av-meta">Reading the artifact…</div>}
      {open && read.phase === 'error' && (
        <div className="wb-av-state">
          The artifact could not be read: {read.message}
          <button type="button" className="wb-av-retry" onClick={read.retry}>Retry</button>
        </div>
      )}
      {open && read.phase === 'ready' && (
        <TextReady row={row} plan={plan} text={read.text ?? ''} />
      )}
    </div>
  )
}

function TextReady({ row, plan, text }: { row: ArtifactViewRow; plan: ArtifactBodyPlan; text: string }) {
  if (textLooksBinary(text)) {
    return <ExternalBody row={row} plan={plan} reason="The file looks binary; the console shows its metadata only." />
  }
  if (plan.kind === 'text') {
    const view = buildTextView(text, row.source)
    if (view.mode === 'markdown') {
      return (
        <div>
          <div className="wb-md" data-view-body="markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(view.text) }} />
          {view.note !== '' && <div className="wb-av-note">{view.note}</div>}
        </div>
      )
    }
    return (
      <div>
        <pre className="wb-av-pre" data-view-body="text">{view.text}</pre>
        {view.note !== '' && <div className="wb-av-note">{view.note}</div>}
      </div>
    )
  }
  if (plan.kind === 'structure') return <StructureBodyView body={buildStructureView(text, row.source, row.shape)} />
  if (plan.kind === 'diff') return <DiffBodyView body={buildDiffView(text)} />
  return <LedgerBodyView body={buildLedgerView(text, row.shape)} />
}

function StructureBodyView({ body }: { body: StructureBody }) {
  if (body.mode === 'table') {
    return (
      <div>
        <table className="wb-av-table" data-view-body="table">
          <thead><tr>{body.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {body.rows.map((cells, i) => (
              <tr key={i}>{cells.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  if (body.mode === 'tree') {
    return (
      <div>
        <ul className="wb-av-tree" data-view-body="tree"><TreeNodes nodes={body.nodes} /></ul>
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  if (body.mode === 'lines') {
    return (
      <div>
        <pre className="wb-av-pre" data-view-body="lines">{body.lines.join('\n')}</pre>
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  return (
    <div>
      <pre className="wb-av-pre" data-view-body="text">{body.text}</pre>
      {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
    </div>
  )
}

function TreeNodes({ nodes }: { nodes: TreeNode[] }) {
  return (
    <>
      {nodes.map((node, i) => (
        <li key={`${node.label}-${i}`}>
          {node.kind === 'scalar'
            ? <span><span className="wb-av-key">{node.label}</span>: <span className="wb-av-val">{node.value}</span></span>
            : (
                <details>
                  <summary>
                    <span className="wb-av-key">{node.label}</span>
                    {node.value !== '' && <span className="wb-av-meta"> {node.value}</span>}
                  </summary>
                  <ul className="wb-av-tree"><TreeNodes nodes={node.children} /></ul>
                </details>
              )}
        </li>
      ))}
    </>
  )
}

function DiffBodyView({ body }: { body: DiffBody }) {
  if (body.mode === 'text') {
    return (
      <div>
        <pre className="wb-av-pre" data-view-body="text">{body.text}</pre>
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  return (
    <div>
      <div className="wb-av-counts">{body.note}{body.note === '' ? '' : ' '}+{body.added} -{body.removed}</div>
      {body.files.map(file => (
        <section className="wb-av-file" key={file.name}>
          <div className="wb-av-file-head">
            <span className="wb-av-key">{file.name}</span>
            <span className="wb-av-meta">+{file.added} -{file.removed}</span>
          </div>
          {file.note !== '' && <div className="wb-av-note">{file.note}</div>}
          {file.hunks.map(hunk => (
            <div className="wb-av-hunk" key={hunk.label}>
              <div className="wb-av-hunk-head">{hunk.label}</div>
              <div data-view-body="diff">
                {hunk.lines.map((line, i) => (
                  <div className="wb-av-dline" data-kind={line.kind} key={i}>
                    <span className="wb-av-ln">{line.oldLine === null ? '' : line.oldLine}</span>
                    <span className="wb-av-ln">{line.newLine === null ? '' : line.newLine}</span>
                    <span className="wb-av-mark">{line.kind === 'added' ? '+' : line.kind === 'removed' ? '-' : ' '}</span>
                    <span className="wb-av-dtext">{line.text}</span>
                  </div>
                ))}
              </div>
              {hunk.truncated && <div className="wb-av-note">Showing the first rows of this hunk; the original is one click away.</div>}
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}

function LedgerEntries({ entries }: { entries: LedgerEntryView[] }) {
  if (entries.length === 0) return <div className="wb-av-note">No entries in this run.</div>
  return (
    <>
      {entries.map((entry, i) => (
        <div className="wb-av-entry" data-color={entry.color} key={`${entry.name}-${i}`}>
          <span className="wb-av-dot" data-color={entry.color} />
          <span className="wb-av-meta">{entry.color}</span>
          <span className="wb-av-key">{entry.name}</span>
          {entry.detail !== '' && <span className="wb-av-meta">{entry.detail}</span>}
          {entry.note !== '' && <span className="wb-av-note">{entry.note}</span>}
          {entry.count !== '' && <span className="wb-av-tag">count {entry.count}</span>}
        </div>
      ))}
    </>
  )
}

function LedgerBodyView({ body }: { body: LedgerBody }) {
  if (body.mode === 'text') {
    return (
      <div>
        <pre className="wb-av-pre" data-view-body="text">{body.text}</pre>
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  if (body.mode === 'generic') {
    return (
      <div>
        <div className="wb-av-counts" data-view-body="ledger-generic">
          green {body.green} · red {body.red} · neutral {body.neutral}
        </div>
        <LedgerEntries entries={body.entries} />
        {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
      </div>
    )
  }
  return (
    <div>
      <div className="wb-av-counts" data-view-body="ledger-receipt">
        green {body.green} · red {body.red} · {body.runs.length} runs
      </div>
      {body.runs.map((run, i) => (
        <section className="wb-av-run" key={`${run.label}-${i}`}>
          <div className="wb-av-run-head">
            <span className="wb-av-key">{run.label}</span>
            <span className="wb-av-verdict" data-verdict={run.verdict}>
              {run.verdict === 'none' ? 'no written verdict' : run.verdict}
            </span>
            {run.disagreement && <span className="wb-av-note">The recorded verdict and its rows disagree; both are shown.</span>}
          </div>
          <LedgerEntries entries={run.entries} />
        </section>
      ))}
      {body.note !== '' && <div className="wb-av-note">{body.note}</div>}
    </div>
  )
}
