/**
 * docs-index-view.ts — the docs face's derived-index state (t261103-19; design
 * docs/design/project-docs-roots-v1.md goal 6).
 *
 * WHAT THIS IS NOT: a copy source. The banner text is written ONCE — by the shared
 * index face (`server/plugins/knowledge/src/shared/docs-roots.ts` -> `indexBanner`) —
 * and the workbench host face hands it to this page as `result.index.banner`. This
 * model only decides HOW that state is presented (which tone) and refuses to invent a
 * state or a wording when the face is missing or malformed. One wording, not two.
 *
 * READ-ONLY: nothing here starts a rebuild, and the page that calls it starts none
 * either. The documentation inspection is the only automatic writer of the index; an
 * operator rebuild is a separate, explicit act.
 *
 * WHY THE TONES DIFFER: a stale or failed index must never look like a current one.
 * `current` is quiet/green; `absent` and `stale` are warn-amber; `failed` is red. The
 * four states therefore stay distinguishable at a glance, and the sentence a reader
 * sees is the host's own sentence for that state.
 */

export type DocsIndexTone = 'ok' | 'warn' | 'red'

export interface DocsIndexStateView {
  /** The host's state string, verbatim (`absent` | `current` | `stale` | `failed` ...). */
  state: string
  /** The host's banner, verbatim — the ONE wording for this state. */
  banner: string
  /** Presentation only; never changes the sentence. */
  tone: DocsIndexTone
  /** True for every state that must never read as current (stale, failed, unknown). */
  notCurrent: boolean
}

/**
 * The index face of one docs-tree payload, or null when there is none.
 *
 * Null is an answer, not a failure: the notes scope carries no derived index, and a
 * payload without an index face gets no banner. An unknown state string is shown as
 * itself with the warn tone — it is never mapped onto one of the four invented
 * states. The page renders the returned banner verbatim, so a stale or failed index
 * can never be re-labelled as current here.
 */
export function docsIndexStateView(payload: unknown): DocsIndexStateView | null {
  if (payload === null || typeof payload !== 'object') return null
  const face = (payload as { index?: unknown }).index
  if (face === null || typeof face !== 'object') return null
  const state = (face as { state?: unknown }).state
  const banner = (face as { banner?: unknown }).banner
  // Malformed face: show nothing rather than a fabricated state or an empty banner.
  // Types are checked before the string test on purpose — coercing a number into a
  // sentence would invent wording this page does not own.
  if (typeof state !== 'string' || typeof banner !== 'string') return null
  if (state === '' || banner === '') return null
  const tone: DocsIndexTone = state === 'current' ? 'ok' : (state === 'failed' ? 'red' : 'warn')
  return { state, banner, tone, notCurrent: state !== 'current' }
}

/** The element escaper the page already owns (`esc`); passed in so this module stays
 *  closure-free and can be embedded into the served page via String(fn). */
export type HtmlEscape = (text: unknown) => string

/**
 * One banner line for the docs face, or '' when there is no index face to show.
 *
 * The sentence is escaped and printed exactly as the host wrote it — this function adds
 * no words of its own. Only the tone class differs per state, so the four states stay
 * visibly distinct and a stale or failed index never takes the current look.
 */
export function docsIndexBannerHtml(payload: unknown, esc: HtmlEscape): string {
  const face = docsIndexStateView(payload)
  if (face === null) return ''
  const tone = face.tone === 'red' ? ' red' : (face.tone === 'ok' ? ' ok' : '')
  return '<div class="banner' + tone + '" data-docs-index-state="' + esc(face.state) + '">'
    + esc(face.banner) + '</div>'
}
