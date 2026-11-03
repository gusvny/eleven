/**
 * doc-row.ts — the projection behind the docs list rows (t261029-49; no DOM, no IO,
 * importable from plain node for tests).
 *
 * A list row always draws five cells: title / category / tags / status / updated.
 * Those five keys are the knowledge-base frontmatter schema (the derived index carries
 * title/category/tags/status/updated). docs/epics/ is a different index category with
 * its own schema (code / retired / summary, see docs/design/epic-registry-v1.md): it
 * has no status, no updated and no tags key. Drawing such a row with the five-field
 * projection left those two cells EMPTY, and an empty cell reads as "the data is
 * missing" — that is the defect this module exists to close.
 *
 * This is the single projection for that table:
 *   - five-field row: values pass through; a missing field becomes an explicit 'n/a'
 *     (never a blank cell).
 *   - epic row (category === 'epics'): the epic's own fields fill the three cells the
 *     five-field rows fill — code into the title-cell badge, retired into the status
 *     cell (retired / active), summary into the updated cell. The epic schema has no
 *     tags, so the tags cell is an explicit 'n/a'.
 *
 * Malformed input discipline: an unknown entry, a non-string field or a non-array tags
 * value takes a defined branch — never throws, never fabricates. Every cell always
 * carries renderable text (`text` is a non-empty string).
 */

/** Explicit "this schema has no such field" placeholder (console copy is English). */
export const NOT_APPLICABLE = 'n/a'

/** The epic category name (one of the index categories; the path rule reads the same store). */
export const EPIC_CATEGORY = 'epics'

/** One renderable cell: `text` is non-empty; `na` marks the explicit placeholder;
 *  `field` names the index field the value came from (so the UI can label it). */
export interface DocCell {
  text: string
  na: boolean
  field: string
}

/** One row: the five-cell projection plus the epic code badge the title cell carries. */
export interface DocRow {
  path: string
  category: string
  isEpic: boolean
  /** Title cell. */
  title: DocCell
  /** Epic code ('' for a non-epic row; for an epic row it falls back to the file stem). */
  code: string
  /** Tag chips ([] for the epic schema). */
  tags: string[]
  /** Tags cell: the renderable placeholder when `tags` is empty. */
  tagsCell: DocCell
  /** Status cell. */
  status: DocCell
  /** Updated cell (for an epic row: the summary). */
  updated: DocCell
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function cell(text: string, field: string): DocCell {
  return { text, na: false, field }
}

function na(field: string): DocCell {
  return { text: NOT_APPLICABLE, na: true, field }
}

/** File stem (epics/<code>.md -> <code>; malformed input -> ''). */
function stemOf(path: string): string {
  const base = path.slice(path.lastIndexOf('/') + 1)
  return base.endsWith('.md') ? base.slice(0, -3) : base
}

/** The retired flag (booleans as they are; the strings 'true'/'false' too, because an
 *  index may carry either shape). Unrecognised -> null, so the caller shows n/a and
 *  never guesses. */
function retiredFlag(v: unknown): boolean | null {
  if (v === true || v === false) return v
  if (typeof v === 'string') {
    const s = v.trim().toLowerCase()
    if (s === 'true') return true
    if (s === 'false') return false
  }
  return null
}

/** Project any derived-index entry into the five cells the list draws. A malformed
 *  entry lands on defined values (n/a / the path name) and never throws. */
export function docRow(entry: unknown): DocRow {
  const e: Record<string, unknown> = entry && typeof entry === 'object' && !Array.isArray(entry)
    ? entry as Record<string, unknown>
    : {}
  const path = str(e.path)
  const category = str(e.category)
  const isEpic = category === EPIC_CATEGORY
  const titleText = str(e.title) || str(e.file) || path
  const tags = Array.isArray(e.tags)
    ? e.tags.filter((t): t is string => typeof t === 'string' && t.trim() !== '')
    : []
  const code = str(e.code) || (isEpic ? stemOf(path) : '')

  if (isEpic) {
    // Epic schema: code / retired / summary. No status, no updated, no tags.
    const retired = retiredFlag(e.retired)
    const summary = str(e.summary)
    return {
      path,
      category,
      isEpic: true,
      title: titleText !== '' ? cell(titleText, 'title') : na('title'),
      code,
      tags: [],
      tagsCell: na('tags'),
      status: retired === null ? na('retired') : cell(retired ? 'retired' : 'active', 'retired'),
      updated: summary !== '' ? cell(summary, 'summary') : na('summary'),
    }
  }

  const status = str(e.status)
  const updated = str(e.updated)
  return {
    path,
    category,
    isEpic: false,
    title: titleText !== '' ? cell(titleText, 'title') : na('title'),
    code: '',
    tags,
    tagsCell: tags.length > 0 ? cell(tags.join(', '), 'tags') : na('tags'),
    status: status !== '' ? cell(status, 'status') : na('status'),
    updated: updated !== '' ? cell(updated, 'updated') : na('updated'),
  }
}
