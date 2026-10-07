// t261008-07 — unit layer for the single-column ticket detail model
// (ticket-detail-column-model.ts). Independent-node style per run_tests.mjs.
// Covers: decision card per-state wording, receipts last-round summary,
// stage notes, changes kv rows, requests filter (incl. malformed input),
// timeline rows, and the mock section order.
import assert from 'node:assert/strict';
import {
  SECTION_ORDER, decisionCard, receiptRows, stageNoteRows,
  changeRows, requestsForTicket, timelineRows,
} from '../src/client/ticket-detail-column-model.ts';

let n = 0;
function ok(name, fn) { fn(); n += 1; console.log(`PASS ${name}`); }

// ---- SECTION_ORDER: the acceptance baseline order -------------------------
ok('section order equals the mock single column', () => {
  assert.deepEqual([...SECTION_ORDER], [
    'crumb', 'head', 'actions', 'decision', 'spec', 'lane-map', 'columns', 'collapsed',
  ]);
});

// ---- decisionCard ----------------------------------------------------------
ok('decision card: awaiting-human names what is signed', () => {
  const c = decisionCard({ status: 'settled', stage_state: 'awaiting-human', stage: 'arbitrate', stage_name: 'arbitrate' }, null);
  assert.equal(c.title, 'Waiting for you: sign the merge');
  assert.match(c.body, /Sign the arbitrate handoff/);
  assert.match(c.body, /Send it back instead if the diff is wrong/);
});

ok('decision card: at work uses the stage', () => {
  const c = decisionCard({ status: 'running', stage_state: 'running', stage: 'implement' }, null);
  assert.equal(c.title, 'At work: implement');
  assert.match(c.body, /Nothing to decide yet/);
});

ok('decision card: at work falls back to stage id then a neutral phrase', () => {
  assert.equal(decisionCard({ status: 'running', stage_state: 'running', stage: 'ui_evidence' }, null).title, 'At work: ui_evidence');
  assert.equal(decisionCard({ status: 'running', stage_state: 'running' }, null).title, 'At work: the current stage');
});

ok('decision card: queued with and without a position (never fabricated)', () => {
  const c = decisionCard({ status: 'queued', stage_state: 'queued' }, 3);
  assert.equal(c.title, 'Queued, position 3');
  assert.match(c.body, /It starts when a slot frees/);
  assert.equal(decisionCard({ status: 'queued', stage_state: 'queued' }, null).title, 'Queued');
  assert.equal(decisionCard({ status: 'queued', stage_state: 'queued' }, 0).title, 'Queued'); // not a position
});

ok('decision card: paused', () => {
  const c = decisionCard({ status: 'running', stage_state: 'running', paused: true, stage: 'implement' }, null);
  assert.equal(c.title, 'Paused by you');
  assert.match(c.body, /It stops after the current stage ends/);
});

ok('decision card: awaiting-human wins over a stale paused flag at the gate', () => {
  const c = decisionCard({ status: 'settled', stage_state: 'awaiting-human', paused: true, stage: 'arbitrate' }, null);
  assert.equal(c.title, 'Waiting for you: sign the merge');
});

ok('decision card: null faces render nothing', () => {
  assert.equal(decisionCard({ status: 'closed', stage_state: 'done' }, null), null);
  assert.equal(decisionCard({ status: 'done', stage_state: 'done' }, null), null);
  assert.equal(decisionCard({ kind: 'inspection', status: 'running', stage_state: 'awaiting-human' }, null), null);
  assert.equal(decisionCard({ engine: 'inspection', status: 'settled', stage_state: 'awaiting-human' }, null), null);
  assert.equal(decisionCard({}, null), null);
  assert.equal(decisionCard(null, null), null);
  assert.equal(decisionCard('nope', null), null);
});

// ---- receiptRows -----------------------------------------------------------
const RUN = { stage: 'merge_check', label: 'merge_check', green: true, red_count: 0, checks: [{ item: 'a', green: true }, { item: 'b', green: true }, { item: 'c', green: false }] };

ok('receipts: last round only, green of total', () => {
  const rows = receiptRows([{ stage: 'old', checks: [{ green: false }] }, RUN]);
  assert.deepEqual(rows, [{ k: 'merge_check', v: '2 of 3 green' }]);
});

ok('receipts: suite counts and env red only when carried', () => {
  const rows = receiptRows([{ ...RUN, suite: { ran: 224, passed: 220, known: 4 }, red_count: 1 }]);
  assert.deepEqual(rows, [
    { k: 'merge_check', v: '2 of 3 green' },
    { k: 'suite', v: '224 ran / 220 passed / 4 known' },
    { k: 'env red', v: '1' },
  ]);
  // suite present but without numeric counts → no suite row
  const partial = receiptRows([{ ...RUN, suite: { ran: 'many' } }]);
  assert.equal(partial.length, 1);
});

ok('receipts: absent/empty/malformed face → null', () => {
  assert.equal(receiptRows(undefined), null);
  assert.equal(receiptRows([]), null);
  assert.equal(receiptRows([{ stage: 'x' }, null, 'junk']), null); // no checks array anywhere
  assert.equal(receiptRows('nope'), null);
  // zero-check run still renders an honest line (face exists, checks absent)
  assert.deepEqual(receiptRows([{ stage: 'gate', checks: [] }]), [{ k: 'gate', v: 'no checks recorded' }]);
});

// ---- stageNoteRows ---------------------------------------------------------
ok('stage notes: gens face rounds, timeline fallback counts', () => {
  assert.deepEqual(
    stageNoteRows({ gens: { implement: 2 }, timeline: [{ stage: 'implement', state: 'running' }, { stage: 'implement', state: 'running' }, { stage: 'review', state: 'running' }] }),
    [{ stage: 'implement', note: 'round 2 · entered 2 times' }, { stage: 'review', note: 'ran once' }],
  );
  assert.deepEqual(
    stageNoteRows({ timeline: [{ stage: 'arbitrate', state: 'running' }, { stage: 'arbitrate', state: 'running' }, { stage: 'arbitrate', state: 'blocked' }] }),
    [{ stage: 'arbitrate', note: 'ran 2 times' }],
  );
});

ok('stage notes: absent faces → null', () => {
  assert.equal(stageNoteRows({}), null);
  assert.equal(stageNoteRows({ timeline: [{ stage: 'x', state: 'blocked' }] }), null); // no running entries, no gens
  assert.equal(stageNoteRows({ gens: {} }), null);
  assert.equal(stageNoteRows(null), null);
  assert.equal(stageNoteRows({ gens: { implement: 'two' } }), null); // non-numeric gen, no runs
});

// ---- changeRows ------------------------------------------------------------
const DIFF = { files: [{ unified: '+a\n+b\n-c\n' }, { unified: 'ctx\n+++\n---\n+d\n' }, { path: 'x' }] };
ok('changes: file count and plus/minus line, lane row when carried', () => {
  assert.deepEqual(changeRows(DIFF, { worktree: '/lane/t1', branch: 'lane/t1' }), [
    { k: 'files', v: '3 · +3 −1' },
    { k: 'lane', v: '/lane/t1 · lane/t1' },
  ]);
  assert.deepEqual(changeRows(DIFF, {}), [{ k: 'files', v: '3 · +3 −1' }]);
});

ok('changes: no/unreadable diff face → null', () => {
  assert.equal(changeRows(undefined, {}), null);
  assert.equal(changeRows({}, {}), null);
  assert.equal(changeRows({ files: 'nope' }, {}), null);
  assert.equal(changeRows(null, {}), null);
});

// ---- requestsForTicket -----------------------------------------------------
const REQ = (id, ticket, question = 'ask you something') => ({ type: 'request', id, at: 1, source_ticket: ticket, question });

ok('requests: filters by source_ticket', () => {
  const rows = [REQ('a', 't1'), REQ('b', 't2'), REQ('c', 't1')];
  const got = requestsForTicket(rows, 't1');
  assert.equal(got.length, 2);
  assert.deepEqual(got.map(r => r.id), ['a', 'c']);
});

ok('requests: legacy rows without the field never match', () => {
  assert.equal(requestsForTicket([{ id: 'x', question: 'q' }, REQ('y', '')], 't1'), null);
});

ok('requests: malformed rows skipped, never thrown', () => {
  const rows = [null, 'junk', 42, { id: 'z', source_ticket: 't1' }, REQ('ok', 't1', ''), REQ('fine', 't1')];
  const got = requestsForTicket(rows, 't1');
  assert.deepEqual(got.map(r => r.id), ['fine']);
});

ok('requests: no rows / bad input → null', () => {
  assert.equal(requestsForTicket([], 't1'), null);
  assert.equal(requestsForTicket(undefined, 't1'), null);
  assert.equal(requestsForTicket([REQ('a', 't2')], 't1'), null);
  assert.equal(requestsForTicket([REQ('a', 't1')], ''), null);
});

// ---- timelineRows ----------------------------------------------------------
ok('timeline: normalized rows, malformed skipped, empty → null', () => {
  const rows = timelineRows([{ at: '2026-10-08T01:00:00Z', stage: 'implement', state: 'running', reason: '' }, null, {}, 'x']);
  assert.deepEqual(rows, [{ at: '2026-10-08T01:00:00Z', stage: 'implement', state: 'running', reason: '' }]);
  assert.equal(timelineRows([]), null);
  assert.equal(timelineRows(undefined), null);
  assert.equal(timelineRows([{}, null]), null);
});

console.log(`\n${n} checks passed`);
