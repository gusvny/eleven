/**
 * tests/t261028-23-diff-rows-model.mjs — the pure unified-diff row model of the
 * file reviewer (t261028-23), asserted directly with no DOM and no network:
 *   A. row numbering (old/new line numbers, kinds, dense indexes, unique keys);
 *   B. the hunk list a view needs (header label, counts, row range);
 *   C. the manifest forms the diff face actually ships: a modified file, an
 *      added file (all `+` lines, no hunk header), a removed-only file, a
 *      degraded (removed-then-added) view;
 *   D. the NAMED empty states — empty diff, malformed diff, no unified diff —
 *      never a crash and never a silently blank view;
 *   E. the anchor <-> row mapping (exact match, same-line/same-text under a
 *      moved hunk, and no match at all).
 *
 * Run: node server/plugins/workbench/tests/t261028-23-diff-rows-model.mjs
 * Pure/offline: no server, no Temporal, no browser, never touches 3099/7233.
 */
import {
  DIFF_EMPTY,
  DIFF_MALFORMED,
  DIFF_NO_UNIFIED,
  SYNTHETIC_HUNK_ID,
  anchorLabel,
  parseUnifiedDiff,
  rowAnchor,
  rowForAnchor,
  rowMatchesAnchor,
  rowMatchesAnchorLoosely,
} from '../src/client/diff-rows-model.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* A/B/C1: a real per-file git diff (headers + two hunks) */
const MODIFIED = [
  'diff --git a/server/plugins/workbench/src/client/index.tsx b/server/plugins/workbench/src/client/index.tsx',
  'index 1111111..2222222 100644',
  '--- a/server/plugins/workbench/src/client/index.tsx',
  '+++ b/server/plugins/workbench/src/client/index.tsx',
  '@@ -10,4 +10,5 @@ export function openChangedFile() {',
  ' const a = 1',
  '-const b = 2',
  '+const b = 3',
  '+const c = 4',
  ' return a',
  ' }',
  '@@ -40,3 +41,3 @@ export function other() {',
  ' unchanged here',
  '-gone',
  '+added',
].join('\n')

{
  const p = parseUnifiedDiff(MODIFIED)
  ok(p.ok === true, 'A1 a git-shaped diff parses')
  ok(p.ok && p.rows.length === 9, `A2 nine rows (${p.ok ? p.rows.length : 'n/a'})`)
  ok(p.ok && p.rows.every((r, i) => r.index === i), 'A3 row indexes are dense 0..n-1')
  ok(p.ok && new Set(p.rows.map((r) => r.key)).size === p.rows.length, 'A4 row keys are unique')
  ok(p.ok && p.rows[0].kind === 'context' && p.rows[0].oldLine === 10 && p.rows[0].newLine === 10,
    'A5 a context row carries both numbers')
  ok(p.ok && p.rows[1].kind === 'removed' && p.rows[1].oldLine === 11 && p.rows[1].newLine === null,
    'A6 a removed row has only the base number')
  ok(p.ok && p.rows[2].kind === 'added' && p.rows[2].oldLine === null && p.rows[2].newLine === 11,
    'A7 an added row has only the changed-side number')
  ok(p.ok && p.rows[5].oldLine === 13 && p.rows[5].newLine === 14, 'A8 numbering continues past an insertion')
  ok(p.ok && p.rows[0].text === 'const a = 1' && p.rows[0].hash.length === 8, 'A9 row text keeps the diff marker off, hash present')
  ok(p.ok && p.added === 3 && p.removed === 2, `A10 +/− counts from the rows (${p.ok ? `+${p.added} −${p.removed}` : 'n/a'})`)
  ok(p.ok && p.skipped === 0 && p.synthetic === false, 'A11 no skipped noise, not synthetic')

  ok(p.ok && p.hunks.length === 2, 'B1 two hunks')
  ok(p.ok && p.hunks[0].oldStart === 10 && p.hunks[0].oldCount === 4 && p.hunks[0].newStart === 10 && p.hunks[0].newCount === 5,
    'B2 first hunk carries its header numbers')
  ok(p.ok && p.hunks[0].firstRow === 0 && p.hunks[0].rowCount === 6, 'B3 first hunk spans rows 0..5')
  ok(p.ok && p.hunks[1].firstRow === 6 && p.hunks[1].rowCount === 3, 'B4 second hunk spans rows 6..8')
  ok(p.ok && p.hunks[0].label.includes('export function openChangedFile'), 'B5 the hunk label keeps the header')
  ok(p.ok && p.rows[6].hunk === p.hunks[1].id && p.rows[6].hunk !== p.hunks[0].id, 'B6 every row names its hunk')
}

/* C2: added file — the diff face synthesises all `+` lines with no hunk header */
{
  const p = parseUnifiedDiff(['+line one', '+line two', '+line three', ''].join('\n'))
  ok(p.ok === true && p.synthetic === true, 'C2 added-file form parses as one synthetic hunk')
  ok(p.ok && p.rows.length === 3 && p.rows.every((r) => r.kind === 'added'), 'C3 every synthetic row is added')
  ok(p.ok && p.rows[0].newLine === 1 && p.rows[2].newLine === 3 && p.rows.every((r) => r.oldLine === null),
    'C4 synthetic rows number the changed side from 1, no base side')
  ok(p.ok && p.hunks.length === 1 && p.hunks[0].id === SYNTHETIC_HUNK_ID, 'C5 the synthetic hunk has a stable id')
  ok(p.ok && p.added === 3 && p.removed === 0, 'C6 synthetic counts')
}

/* C3: removed-only file (deleted file) */
{
  const removedOnly = [
    'diff --git a/gone.txt b/gone.txt',
    'deleted file mode 100644',
    'index 1234567..0000000',
    '--- a/gone.txt',
    '+++ /dev/null',
    '@@ -1,2 +0,0 @@',
    '-alpha',
    '-beta',
  ].join('\n')
  const p = parseUnifiedDiff(removedOnly)
  ok(p.ok === true && p.rows.length === 2 && p.removed === 2 && p.added === 0, 'C7 removed-only file: two removed rows')
  ok(p.ok && p.rows.every((r) => r.newLine === null) && p.rows[0].oldLine === 1 && p.rows[1].oldLine === 2,
    'C8 removed-only rows keep base numbers only')
  ok(p.ok && p.hunks[0].oldCount === 2 && p.hunks[0].newCount === 0, 'C9 removed-only hunk header counts')
}

/* C4: degraded view the diff face emits when a JSON side fails to parse */
{
  const p = parseUnifiedDiff('(JSON parse failed, degraded to line-level view: bad JSON)\n-old line\n+new line')
  ok(p.ok === true && p.synthetic === true && p.rows.length === 2, 'C10 degraded form parses as a synthetic hunk')
  ok(p.ok && p.rows[0].kind === 'removed' && p.rows[0].oldLine === 1 && p.rows[1].kind === 'added' && p.rows[1].newLine === 1,
    'C11 degraded form numbers both sides from 1')
  ok(p.ok && p.skipped === 1, 'C12 the preamble line is counted as skipped, not shown as a row')
}

/* C5: a multi-file diff and the "\ No newline" marker */
{
  const two = [
    'diff --git a/a.txt b/a.txt',
    '--- a/a.txt',
    '+++ b/a.txt',
    '@@ -1 +1 @@',
    '-one',
    '+uno',
    '\\ No newline at end of file',
    'diff --git a/b.txt b/b.txt',
    '--- a/b.txt',
    '+++ b/b.txt',
    '@@ -1 +1 @@',
    '-two',
    '+dos',
  ].join('\n')
  const p = parseUnifiedDiff(two)
  ok(p.ok === true && p.rows.length === 4, `C13 two files in one diff parse (${p.ok ? p.rows.length : 'n/a'} rows)`)
  ok(p.ok && p.hunks.length === 2, 'C14 one hunk per file')
  ok(p.ok && p.rows.every((r) => r.text !== ''), 'C15 the "no newline" marker is not a row')
}

/* D: named empty states */
{
  const e1 = parseUnifiedDiff('')
  ok(e1.ok === false && e1.state === DIFF_EMPTY && e1.reason !== '', 'D1 empty string -> named empty-diff state')
  const e2 = parseUnifiedDiff('   \n\n ')
  ok(e2.ok === false && e2.state === DIFF_EMPTY, 'D2 whitespace-only -> named empty-diff state')
  const e3 = parseUnifiedDiff(undefined)
  ok(e3.ok === false && e3.state === DIFF_NO_UNIFIED && e3.reason.includes('no unified diff'), 'D3 missing unified field -> named no-unified-diff')
  for (const bad of [null, 42, {}, []]) {
    const r = parseUnifiedDiff(bad)
    ok(r.ok === false && r.state === DIFF_NO_UNIFIED, `D4 non-string input ${JSON.stringify(bad)} -> named state, no throw`)
  }
  const e4 = parseUnifiedDiff('(diff output over the cap, degraded to --stat summary)\nserver/x.ts | 5 +++--')
  ok(e4.ok === false && e4.state === DIFF_MALFORMED && e4.reason.includes('first unrecognised line'),
    'D5 a --stat summary (no rows) -> named malformed-diff naming the offending line')
  const e5 = parseUnifiedDiff('@@ this is not a hunk header @@\nwhatever')
  ok(e5.ok === false && e5.state === DIFF_MALFORMED, 'D6 a bogus @@ line -> named malformed-diff, no crash')
  const e6 = parseUnifiedDiff('\u0000\u0001 binary garbage')
  ok(e6.ok === false && e6.state === DIFF_MALFORMED, 'D7 binary garbage -> named malformed-diff')
}

/* E: anchor <-> row mapping */
{
  const p = parseUnifiedDiff(MODIFIED)
  const rows = p.ok ? p.rows : []
  const ctx = rows[0]
  const rem = rows[1]
  const add = rows[2]

  const ctxAnchor = rowAnchor(ctx)
  const remAnchor = rowAnchor(rem)
  const addAnchor = rowAnchor(add)
  ok(ctxAnchor !== null && ctxAnchor.side === 'new' && ctxAnchor.line === 10 && ctxAnchor.hunk === ctx.hunk
    && ctxAnchor.contextHash === ctx.hash, 'E1 a context row anchors to its changed-side line')
  ok(remAnchor !== null && remAnchor.side === 'old' && remAnchor.line === 11, 'E2 a removed row anchors to its base-side line')
  ok(addAnchor !== null && addAnchor.side === 'new' && addAnchor.line === 11, 'E3 an added row anchors to its changed-side line')

  ok(rowMatchesAnchor(ctx, ctxAnchor) === true, 'E4 the recorded anchor matches its own row')
  ok(rowMatchesAnchor(ctx, { ...ctxAnchor, line: 99 }) === false, 'E5 a different line does not match')
  ok(rowMatchesAnchor(ctx, { ...ctxAnchor, contextHash: 'deadbeef' }) === false, 'E6 different text does not match')
  ok(rowMatchesAnchor(ctx, { ...ctxAnchor, hunk: '@@ moved @@' }) === false, 'E7 exact match requires the same hunk')

  ok(rowMatchesAnchorLoosely(ctx, { ...ctxAnchor, hunk: '@@ moved @@' }) === true,
    'E8 same side+line+text under a moved hunk is a loose match (an insert above shifted the header)')
  ok(rowMatchesAnchorLoosely(ctx, { ...ctxAnchor, line: 99 }) === false, 'E9 a loose match still requires the same line')
  ok(anchorLabel(ctxAnchor).includes('new line 10') && anchorLabel(remAnchor).includes('old line 11'),
    'E10 anchor labels name the side and the line')

  ok(rowForAnchor(rows, { ...addAnchor, hunk: '@@ moved @@' }) === add, 'E11 rowForAnchor finds the row across a moved hunk')
  ok(rowForAnchor(rows, { ...ctxAnchor, contextHash: 'nope' }) === undefined, 'E12 rowForAnchor returns nothing when the line is gone')
}
console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
