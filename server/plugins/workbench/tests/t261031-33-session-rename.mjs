#!/usr/bin/env node
/**
 * t261031-33-session-rename.mjs - L1 battery for the project-session tab rename.
 *
 * Scope (developer test face, white box allowed): the pure layer this ticket
 * adds, and nothing else.
 *   A. setEntryTitle sets, trims and clears the custom name (R3).
 *   B. setEntryTitle boundaries: unknown id, ticket id, duplicate id, no-op
 *      reference, input never mutated, order and sibling references kept.
 *   C. setEntryTitle malformed input: non-string name is refused (a malformed
 *      call never destroys a name), non-array ledger, non-string id, the
 *      TITLE_MAX_LEN clamp shared with the file schema, '' stored title
 *      normalized to an absent field.
 *   D. The identity rule (R2): a rename changes `title` only - id, project,
 *      cwd, lastOpenedAt, seq and handle stay byte-identical, so the handle
 *      stays reachable and the entry keeps its lifetime under the ledger cap.
 *   E. tabLabelOf: a set name wins over the handle short code (R5); with no
 *      name the label is today's handle label, byte-identical.
 *   F. pickProjectTabs exposes the trimmed name as customTitle and keeps the
 *      raw title for the tooltip.
 *   G. The click machine (src/client/psess-rename.ts, R1): one click produces
 *      exactly one switch and no editor; one double click produces zero
 *      switches and one editor; a stale timer after the pair never switches;
 *      the latest click wins; a click or a double click inside the open editor
 *      changes nothing; malformed events are no-ops; states are not mutated.
 *   H. The commit decision: an unchanged draft writes nothing (a bare double
 *      click plus blur cannot turn a handle label into a stored name); an
 *      empty or whitespace-only draft clears; Enter and Esc are the row's
 *      business, not this function's.
 *
 * Run: node tests/t261031-33-session-rename.mjs (node >= 22.18 native
 * type-stripping, .ts imported directly; cwd independent; no IO, no DOM).
 * Exit contract: last line SUMMARY pass=N skip=M fail=K; exit 1 iff fail > 0.
 */

import {
  setEntryTitle,
  tabLabelOf,
  pickProjectTabs,
  LEDGER_CAP,
  TITLE_MAX_LEN,
} from '../src/shared/sessions.ts'
import {
  RENAME_CLICK_WINDOW_MS,
  initialTabClickState,
  renameCommitOf,
  renameDraftOf,
  tabClickStep,
} from '../src/client/psess-rename.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** One ledger entry (lastOpenedAt is an ordinal: larger = registered later). */
function ent(id, extra = {}) {
  return { id, project: 'sandbar', cwd: '/repo/sandbar', lastOpenedAt: 10, ...extra }
}

/* A. Set, trim, clear */
section('A setEntryTitle: set / trim / clear (R3)')
{
  const base = [ent('s-1', { seq: 1 }), ent('s-2', { seq: 2 })]
  const snapshot = JSON.stringify(base)

  const set = setEntryTitle(base, 's-1', 'Fix the ledger cap')
  ok(set !== base, 'a set name returns a NEW array')
  ok(set.find(e => e.id === 's-1')?.title === 'Fix the ledger cap', 'the name is stored on the entry')
  ok(set.find(e => e.id === 's-2')?.title === undefined, 'the other entries get no name')
  ok(JSON.stringify(base) === snapshot, 'the input ledger is never mutated')

  const trimmed = setEntryTitle(base, 's-1', '   spaced name \n')
  ok(trimmed.find(e => e.id === 's-1')?.title === 'spaced name', 'the name is trimmed on both sides')

  const cleared = setEntryTitle(set, 's-1', '')
  ok(cleared.find(e => e.id === 's-1')?.title === undefined, 'an empty commit removes the name')
  ok(!('title' in (cleared.find(e => e.id === 's-1') ?? {})), 'the title FIELD is removed, never stored as an empty string')
  const blank = setEntryTitle(set, 's-1', '  \t ')
  ok(blank.find(e => e.id === 's-1')?.title === undefined, 'a whitespace-only commit clears too')

  // A clear on an entry that has no name is a no-op (same reference = no write)
  ok(setEntryTitle(base, 's-2', '   ') === base, 'clearing an absent name returns the input reference (no write)')
  // Stored '' (a file fetch can write it) normalizes to an absent field
  const storedEmpty = [ent('s-3', { title: '' })]
  const norm = setEntryTitle(storedEmpty, 's-3', '')
  ok(norm.find(e => e.id === 's-3')?.title === undefined, "a stored '' title is normalized to an absent field")
}

/* B. Boundaries */
section('B setEntryTitle: unknown id / ticket id / duplicate id / no-op reference')
{
  const base = [ent('s-1', { seq: 1 }), ent('s-2', { seq: 2 })]
  ok(setEntryTitle(base, 'ghost', 'nope') === base, 'an unknown id is a no-op (a rename never inserts an entry)')
  ok(setEntryTitle(base, 'ghost', 'nope').length === base.length, 'the ledger length is unchanged by an unknown id')
  ok(setEntryTitle(base, 'ticket-t9', 'nope') === base, 'a ticket id never matches (those are not in the ledger)')
  ok(setEntryTitle(base, '', 'nope') === base, 'an empty id is a no-op')

  const dup = [ent('s-1', { seq: 1 }), ent('s-1', { seq: 2 }), ent('s-9', { seq: 3 })]
  const dupOut = setEntryTitle(dup, 's-1', 'one name')
  ok(dupOut.filter(e => e.id === 's-1').every(e => e.title === 'one name'),
    'a duplicate id renames every copy (one id, one name, never a half state)')
  ok(dupOut.find(e => e.id === 's-9')?.title === undefined, 'the duplicate rename leaves other ids alone')

  const same = setEntryTitle(base, 's-1', 'same name')
  ok(setEntryTitle(same, 's-1', 'same name') === same, 'renaming to the current name returns the input reference (idempotent)')
  ok(setEntryTitle(same, 's-1', '  same name  ') === same, 'the trimmed name counts as unchanged (no write)')

  const set = setEntryTitle(base, 's-1', 'x')
  ok(set[0] !== base[0] && set[1] === base[1], 'only the renamed entry is copied; siblings keep their reference')
  ok(set.map(e => e.id).join(',') === base.map(e => e.id).join(','), 'the array order is kept (a rename never reorders)')
}

/* C. Malformed input */
section('C setEntryTitle: malformed input is refused, never obeyed')
{
  const base = [ent('s-1', { title: 'kept name' })]
  for (const bad of [null, undefined, 42, {}, [], true]) {
    ok(setEntryTitle(base, 's-1', bad) === base,
      `a non-string name (${JSON.stringify(bad)}) is refused - the stored name survives`)
  }
  ok(setEntryTitle(base, 's-1', null).find(e => e.id === 's-1')?.title === 'kept name', 'the stored name is unchanged after a refused call')
  ok(setEntryTitle(base, 42, 'x') === base, 'a non-string id is a no-op')
  ok(Array.isArray(setEntryTitle(null, 's-1', 'x')) && setEntryTitle(null, 's-1', 'x').length === 0,
    'a non-array ledger yields an empty ledger (no throw)')
  ok(Array.isArray(setEntryTitle(undefined, 's-1', 'x')), 'an undefined ledger does not throw')

  const long = 'n'.repeat(TITLE_MAX_LEN + 120)
  const clamped = setEntryTitle(base, 's-1', long).find(e => e.id === 's-1')
  ok(clamped?.title?.length === TITLE_MAX_LEN, `a very long name is clamped to ${TITLE_MAX_LEN} (the file schema slice)`)
  ok(clamped?.title === 'n'.repeat(TITLE_MAX_LEN), 'the clamp keeps the leading text, never a scrambled name')
  const exact = setEntryTitle(base, 's-1', 'n'.repeat(TITLE_MAX_LEN))
  ok(exact.find(e => e.id === 's-1')?.title?.length === TITLE_MAX_LEN, 'a name of exactly the limit is kept whole')
}

/* D. Identity untouched */
section('D a rename changes the display name only (R2/R4)')
{
  const base = [
    ent('s-1', { seq: 4, handle: '0eca', lastOpenedAt: 77, title: 'old' }),
    ent('s-2', { seq: 5 }),
  ]
  const out = setEntryTitle(base, 's-1', 'new name')
  const a = out.find(e => e.id === 's-1')
  const b0 = base.find(e => e.id === 's-1')
  ok(a?.id === b0.id, 'the ledger id is untouched')
  ok(a?.project === b0.project, 'the project is untouched')
  ok(a?.cwd === b0.cwd, 'the cwd is untouched')
  ok(a?.lastOpenedAt === b0.lastOpenedAt, 'lastOpenedAt is untouched (a rename never re-registers the entry)')
  ok(a?.seq === b0.seq, 'seq is untouched (the tab number is stable)')
  ok(a?.handle === b0.handle, 'the handle is untouched (it stays the identity)')
  ok(a?.title === 'new name', 'only the title changed')

  // Ledger cap: the rename leaves the array length and the tail entry alone, so
  // the name cannot be lost earlier than the entry itself (R4).
  let ledger = []
  for (let i = 1; i <= LEDGER_CAP + 3; i++) ledger = [{ ...ent(`c-${i}`, { seq: i, lastOpenedAt: i }), ...{} }, ...ledger].slice(0, LEDGER_CAP)
  const tail = ledger[ledger.length - 1]
  const capped = setEntryTitle(ledger, tail.id, 'kept')
  ok(capped.length === ledger.length, 'a rename never changes the ledger length (cap eviction is unchanged)')
  ok(capped[capped.length - 1].id === tail.id && capped[capped.length - 1].title === 'kept',
    'the oldest entry can carry a name and is still the entry the cap evicts')
}

/* E. Label rule */
section('E tabLabelOf: a set name wins, no name is today behaviour (R5)')
{
  ok(tabLabelOf('My name', '0eca') === 'My name', 'a set name wins over the handle short code')
  ok(tabLabelOf(undefined, '0eca') === '0eca', 'no name -> the handle short code (byte-identical to today)')
  ok(tabLabelOf('', '0eca') === '0eca', 'an empty name -> the handle short code')
  ok(tabLabelOf('   ', '0eca') === '0eca', 'a whitespace-only name -> the handle short code')
  ok(tabLabelOf('  My name  ', '0eca') === 'My name', 'the label is trimmed')
  ok(tabLabelOf(null, 'executor') === 'executor', 'the executor fixed name is an ordinary handle label here')
  ok(tabLabelOf(undefined, '') === '', 'a missing handle label yields an empty label (never a guess)')
  ok(tabLabelOf(undefined, undefined) === '', 'both sides missing -> empty label, no throw')
  ok(tabLabelOf('name', 3) === 'name', 'a set name never depends on the handle label')
}

/* F. Rendered tab data */
section('F pickProjectTabs exposes the name and keeps the raw title')
{
  const ledger = [
    ent('s-1', { seq: 1, title: '  named  ' }),
    ent('s-2', { seq: 2 }),
    ent('s-3', { seq: 3, title: '   ' }),
  ]
  const tabs = pickProjectTabs(ledger, { project: 'sandbar', byId: { 's-2': { displayTitle: 'display two' } } })
  ok(tabs.find(t => t.id === 's-1')?.customTitle === 'named', 'customTitle is the trimmed name')
  ok(tabs.find(t => t.id === 's-1')?.title === '  named  ', 'the raw title stays for the tooltip')
  ok(tabs.find(t => t.id === 's-2')?.customTitle === undefined, 'an entry with no name carries no customTitle')
  ok(tabs.find(t => t.id === 's-2')?.title === 'display two', 'the displayTitle fallback is unchanged')
  ok(tabs.find(t => t.id === 's-3')?.customTitle === undefined, 'a whitespace-only title counts as no name')
  ok(tabs.every(t => t.project === undefined), 'ProjectTab still carries render fields only')
}

/* G. Click machine */
section('G click machine: one click switches, a double click edits (R1)')
{
  // A single click: no switch at once, exactly one switch when the timer fires.
  let s = initialTabClickState()
  let r = tabClickStep(s, { type: 'click', id: 'a' })
  s = r.state
  ok(r.switchTo === null && r.openEditor === null, 'a click does not switch at once (it arms the switch)')
  ok(s.pending === 'a' && s.editing === null, 'the click arms exactly that tab')
  r = tabClickStep(s, { type: 'switch-due', id: 'a' })
  s = r.state
  ok(r.switchTo === 'a' && r.openEditor === null, 'the timer fires exactly one switch')
  ok(s.pending === null, 'the switch disarms the pending click')
  ok(tabClickStep(s, { type: 'switch-due', id: 'a' }).switchTo === null, 'the same timer twice never switches twice')

  // A double click: click, click, dblclick -> zero switches, one editor.
  s = initialTabClickState()
  s = tabClickStep(s, { type: 'click', id: 'a' }).state
  s = tabClickStep(s, { type: 'click', id: 'a' }).state
  r = tabClickStep(s, { type: 'dblclick', id: 'a' })
  s = r.state
  ok(r.switchTo === null && r.openEditor === 'a', 'a double click opens the editor and switches nothing')
  ok(s.pending === null && s.editing === 'a', 'the pair leaves no armed switch behind')
  ok(tabClickStep(s, { type: 'switch-due', id: 'a' }).switchTo === null,
    'a stale timer that was already queued never switches after the editor opened')

  // Two switches never happen for one pair, whatever the order of arrivals.
  s = tabClickStep(initialTabClickState(), { type: 'click', id: 'a' }).state
  s = tabClickStep(s, { type: 'dblclick', id: 'a' }).state
  ok(tabClickStep(s, { type: 'switch-due', id: 'a' }).switchTo === null, 'click -> dblclick -> timer: zero switches')

  // Latest click wins (rapid clicking through tabs switches once, to the last).
  s = tabClickStep(initialTabClickState(), { type: 'click', id: 'a' }).state
  r = tabClickStep(s, { type: 'click', id: 'b' })
  s = r.state
  ok(s.pending === 'b', 'the latest click wins')
  ok(tabClickStep(s, { type: 'switch-due', id: 'a' }).switchTo === null, 'the dropped tab never switches')
  ok(tabClickStep(s, { type: 'switch-due', id: 'b' }).switchTo === 'b', 'only the last clicked tab switches')

  // Inside the open editor: a click or a double click changes nothing.
  const editing = { pending: null, editing: 'a' }
  r = tabClickStep(editing, { type: 'click', id: 'a' })
  ok(r.switchTo === null && r.openEditor === null && r.state.editing === 'a',
    'a click inside the open editor arms nothing and keeps the editor')
  r = tabClickStep(editing, { type: 'dblclick', id: 'a' })
  ok(r.switchTo === null && r.openEditor === null && r.state.editing === 'a',
    'a double click in the editor is word selection, never a re-open (the draft survives)')
  r = tabClickStep(editing, { type: 'click', id: 'b' })
  ok(r.switchTo === null && r.state.pending === 'b' && r.state.editing === 'a',
    'a click on another tab arms that switch and leaves the editor open (blur commits it)')

  // Closing the editor.
  r = tabClickStep({ pending: 'b', editing: 'a' }, { type: 'close-editor' })
  ok(r.state.editing === null && r.state.pending === null, 'close-editor empties both fields')
  ok(r.switchTo === null && r.openEditor === null, 'close-editor asks for no side effect')

  // Malformed input.
  ok(tabClickStep(undefined, { type: 'click', id: 'a' }).state.pending === 'a', 'an undefined state starts from the initial state')
  ok(tabClickStep(initialTabClickState(), undefined).switchTo === null, 'an undefined event is a no-op')
  ok(tabClickStep(initialTabClickState(), { type: 'nonsense', id: 'a' }).switchTo === null, 'an unknown event type is a no-op')
  ok(tabClickStep(initialTabClickState(), { type: 'click', id: '' }).state.pending === null, 'an empty id never arms a switch')
  ok(tabClickStep(initialTabClickState(), { type: 'click' }).state.pending === null, 'a click without an id never arms a switch')
  ok(tabClickStep({ pending: 5, editing: 7 }, { type: 'click', id: 'a' }).state.editing === null,
    'a malformed state field is normalized, never trusted')

  // Input state is not mutated.
  const frozen = Object.freeze({ pending: 'a', editing: null })
  tabClickStep(frozen, { type: 'dblclick', id: 'a' })
  ok(frozen.pending === 'a' && frozen.editing === null, 'the input state object is never mutated')
  ok(RENAME_CLICK_WINDOW_MS > 0 && RENAME_CLICK_WINDOW_MS < 500,
    `the click window (${RENAME_CLICK_WINDOW_MS} ms) sits inside the browser double-click interval`)
}

/* H. Commit decision */
section('H commit decision: unchanged writes nothing, empty clears (R1/R3)')
{
  ok(renameCommitOf('same', 'same').kind === 'none', 'an unchanged draft writes nothing')
  ok(renameCommitOf('  same  ', 'same').kind === 'none', 'a trimmed-equal draft writes nothing')
  ok(renameCommitOf('same', '  same ').kind === 'none', 'the prefill is compared trimmed too')
  ok(renameCommitOf('', '0eca').kind === 'set' && renameCommitOf('', '0eca').name === '',
    'an empty draft is a CLEAR (name "")')
  ok(renameCommitOf('   ', '0eca').name === '', 'a whitespace-only draft clears')
  ok(renameCommitOf('  new name  ', '0eca').name === 'new name', 'a typed name is trimmed before the write')
  ok(renameCommitOf('0eca', '0eca').kind === 'none', 'committing the prefilled handle writes nothing (no accidental name)')
  ok(renameCommitOf(null, '0eca').kind === 'set' && renameCommitOf(null, '0eca').name === '',
    'a non-string draft degrades to empty (the clear path), never to a crash')
  ok(renameCommitOf(undefined, undefined).kind === 'none', 'an absent draft and prefill write nothing')

  // The prefill rule matches the rendered label, so the user edits what they see.
  ok(renameDraftOf('My name', '0eca') === 'My name', 'the editor opens with the set name')
  ok(renameDraftOf(undefined, '0eca') === '0eca', 'the editor opens with the handle when no name is set')
  ok(renameDraftOf('  ', 'executor') === 'executor', 'a whitespace-only name prefills the handle')
}

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
