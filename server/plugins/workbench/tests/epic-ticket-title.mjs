/**
 * Epics tab row name contract (t261028-17).
 *
 * Host report 261028: old tickets showed the sentence "workflow COMPLETED; snapshot past
 * the hydrate window; ..." as their NAME in the Epics tab. The engine wrote that
 * diagnostic into the row's `title`, and this tab renders `title` verbatim — so the
 * sentence reached the operator as the ticket's name.
 *
 * Contract pinned here (the engine now sends the real archived title, and a diagnostic
 * only in `identity_note`):
 *   A. a row carrying the real title shows the real title;
 *   B. a row whose title is empty (name unresolved) shows the ticket id — never a
 *      sentence, never blank;
 *   C. an absent / non-string / blank title is ABSENT (id stands in): the mapper does
 *      not turn junk into text;
 *   D. no message matching: every non-empty title is the row's name verbatim (the
 *      mapper cannot know which strings are diagnostics, so it must not guess);
 *   E. the diagnostic never leaks from identity_note into the name slot;
 *   F. the t261021-12 time field is unchanged (updated_ts seconds → milliseconds).
 *
 * Run: node server/plugins/workbench/tests/epic-ticket-title.mjs
 */
import { epicTicketRow, titleOrTicketId } from './../src/host/epic-tickets.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// The exact sentence the old engine put into `title` (fixture text — the mapper never
// matches on it; it is here so a future "strip the message" regression shows up green
// instead of hiding).
const HYDRATE_SENTENCE = 'workflow COMPLETED; snapshot past the hydrate window; '
  + 'stage_state reconciled: awaiting -> closed'

section('A. real title from the archived row wins')
{
  const row = epicTicketRow({
    id: 't260903-11',
    title: 'T1 fpv-core 抽库设计（分仓设计票：库边界+依赖发布形态）',
    status: 'closed', stage: '', stage_state: 'closed', updated_ts: 1793136231,
    identity_note: 'workflow COMPLETED; snapshot past the hydrate window; stage_state '
      + 'reconciled: awaiting -> closed; archive manifest missing (no archived '
      + 'identity to read): /x/archive.json',
  })
  ok(row.title === 'T1 fpv-core 抽库设计（分仓设计票：库边界+依赖发布形态）',
    `title is the archived real title (title=${JSON.stringify(row.title)})`)
  ok(row.title !== row.id && !row.title.includes('hydrate window'),
    'a diagnostic never becomes the name')
}

section('B. an unresolved name falls back to the ticket id')
{
  const row = epicTicketRow({
    id: 't260903-12', title: '', status: 'closed', stage_state: 'closed',
    identity_note: HYDRATE_SENTENCE,
  })
  ok(row.title === 't260903-12', `empty title falls back to the id (title=${JSON.stringify(row.title)})`)
  ok(row.title.trim() !== '', 'the row is never blank')
}

section('C. absent / non-string / blank titles are absent (id stands in)')
{
  for (const [label, src] of [
    ['no title key', { id: 't-a' }],
    ['null title', { id: 't-b', title: null }],
    ['numeric title', { id: 't-c', title: 42 }],
    ['whitespace title', { id: 't-d', title: '   \n\t ' }],
  ]) {
    const row = epicTicketRow(src)
    ok(row.title === src.id, `${label} → id (title=${JSON.stringify(row.title)})`)
  }
  ok(titleOrTicketId('  padded  ', 't-e') === 'padded', 'a real title is trimmed, not replaced')
}

section('D. no message matching: any non-empty title is the name verbatim')
{
  // The mapper cannot tell a diagnostic from a name, so it must not try: whatever the
  // engine sends as a non-empty title is shown (the engine owns the rule that a title
  // is a name — server/engine/tests/test_t261028_06_closed_row_title_from_archive.py).
  ok(titleOrTicketId(HYDRATE_SENTENCE, 't-f') === HYDRATE_SENTENCE,
    'the mapper does not special-case a known message text')
  ok(titleOrTicketId('title with ; semicolons and (parens)', 't-g')
    === 'title with ; semicolons and (parens)', 'no transformation of a real name')
}

section('E. the diagnostic never leaks from identity_note into the name slot')
{
  const diag = 'ticket query timed out: queue sandbar-ticket-t9 has 0 live pollers '
    + '(dedicated worker stopped polling or absent); wait for the ensure replacement '
    + 'before refreshing'
  const row = epicTicketRow({ id: 't260903-13', title: '', identity_note: diag })
  ok(row.title === 't260903-13', 'id, not the note')
  ok(!Object.values(row).includes(diag), 'the note text appears in no rendered field')
}

section('F. t261021-12 time field unchanged')
{
  const ms = epicTicketRow({ id: 't-h', title: 'x', updated_ts: 1793136231 }).updated_ts
  ok(ms === 1793136231000, `updated_ts seconds → milliseconds (got ${ms})`)
  ok(!('updated_ts' in epicTicketRow({ id: 't-i', title: 'x', updated_ts: 0 })),
    'a <= 0 timestamp is ABSENT, never zero')
  ok(!('updated_ts' in epicTicketRow({ id: 't-j', title: 'x', updated_ts: 'nope' })),
    'a non-numeric timestamp is ABSENT, never now')
}

console.log(`\nepic-ticket-title 结果：pass=${pass} fail=${fail}`)
process.exitCode = fail === 0 ? 0 : 1
