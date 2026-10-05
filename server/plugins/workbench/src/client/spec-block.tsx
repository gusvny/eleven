/**
 * spec-block.tsx — the ticket-detail Spec block (console-ui epic UI-3, t261005-04).
 *
 * Caliber (261004 concurrency design §7.5, final block order): the Spec is read
 * before any decision — what you sign is this, nothing else. Four pieces, each
 * rendered only when its key exists (missing keys render nothing; never an
 * empty shell):
 *   - the Execution spec card (existing .wb-d2-spec markup reused as-is, t260904-06);
 *   - the verbatim original request (collapsed "Original request (verbatim)",
 *     data = detail.body — moved in here from the old always-expanded pinned
 *     card, matching the v11 mock);
 *   - the acceptance checklist (detail.acceptance, one readable line each;
 *     non-interactive, no faked state);
 *   - write-set chips (detail.write_set, the paths this ticket may change).
 * Also: when detail.red_line (the engine's single-string red line) exists, one
 * fact line renders — the STRUCTURED red-line face belongs to the prerequisite
 * ticket (plan-detail data face); this ticket renders the existing single key
 * only and fabricates no placeholder.
 *
 * Malformed-input discipline: each array field is filtered by typeof/Array with
 * empty strings dropped; all missing → the whole block returns null (old
 * tickets untouched). Body text is always a React text node (engine/agent
 * output is never raw-injected).
 */

export interface SpecBlockProps {
  body?: unknown
  spec?: unknown
  acceptance?: unknown
  writeSet?: unknown
  redLine?: unknown
  /** The spec's markdown HTML (the caller prepares it with the existing specMarkdownHtml — escape first). */
  specHtml?: string
}

function strList(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  const out: string[] = []
  for (const x of v) {
    if (typeof x === 'string' && x.trim() !== '') out.push(x)
  }
  return out
}

export function SpecBlock({ body, spec, acceptance, writeSet, redLine, specHtml }: SpecBlockProps) {
  const specText = typeof spec === 'string' && spec.trim() !== '' ? spec : ''
  const bodyText = typeof body === 'string' && body.trim() !== '' ? body : ''
  const acc = strList(acceptance)
  const ws = strList(writeSet)
  const rl = typeof redLine === 'string' && redLine.trim() !== '' ? redLine : ''

  if (specText === '' && bodyText === '' && acc.length === 0 && ws.length === 0 && rl === '') return null

  return (
    <div className="wb-spec-block" data-testid="spec-block">
      {specText !== '' && (
        <div className="wb-d2-spec" data-v="B">
          <div className="ttl">Execution spec<span className="cnt">{specText.length} chars</span></div>
          <div className="txt wb-md" dangerouslySetInnerHTML={{ __html: specHtml ?? '' }} />
        </div>
      )}
      {acc.length > 0 && (
        <div className="wb-spec-acc" data-testid="spec-acceptance">
          <div className="ttl">Acceptance ({acc.length})</div>
          <ul>
            {acc.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}
      {ws.length > 0 && (
        <div className="wb-spec-ws" data-testid="spec-write-set">
          <div className="ttl">Write set ({ws.length})</div>
          <div className="chips">
            {ws.map((w) => <code className="ws-chip" key={w}>{w}</code>)}
          </div>
        </div>
      )}
      {rl !== '' && (
        <div className="wb-spec-redline" data-testid="spec-red-line">Red line: {rl}</div>
      )}
      {bodyText !== '' && (
        <details className="wb-spec-orig" data-testid="spec-original">
          <summary>Original request (verbatim)</summary>
          <pre>{bodyText}</pre>
        </details>
      )}
    </div>
  )
}
