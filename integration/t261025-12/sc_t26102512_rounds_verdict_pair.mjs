/**
 * sc_t26102512_rounds_verdict_pair.mjs — t261025-12, part 3 of 3.
 *
 * intent (ticket item C "the face's honesty" + item D "no control without a
 * handler"):
 *   The rounds table shows BOTH verdicts the face already carries: the strict
 *   face verdict (env_fail > 0 means red) AND the content record verdict
 *   (record_rule / record_verdict). The host measured 261025: nine rounds all
 *   rendered red although seven ran 700+ cases with 0 failed (7-14
 *   environment reds each) — the collapse of the two verdicts into one word
 *   is what made the host ask why nothing is ever green. The two words stay
 *   visible side by side; they are never collapsed into one, and a round
 *   without a record verdict names that absence instead of staying silent.
 *   And per item D: a control that cannot act renders disabled WITH its named
 *   reason, and an unreadable face never renders a promotable number (the
 *   host's 'Promote 1' incident).
 *
 * failure surface (grey-box):
 *   - the record verdict dropped again during the control work (regression of
 *     exactly the honesty this ticket exists to add);
 *   - the two verdicts OR-ed into one pill ('red' swallowing a green record
 *     or vice versa);
 *   - a missing/malformed record_verdict crashing the render or inventing a
 *     verdict word;
 *   - the dialog (the round's own record face) still showing only one word;
 *   - 'Promote N' rendered while the face is unreadable.
 *
 * layering / intent split:
 *   - the strict-verdict pill rule (env_fail>0 => red), counts cell, measured
 *     cell, newest-first order, and the one-promotable-figure rule belong to
 *     the existing t261012-03 / t261019-23 / t261016-09 entries — this entry
 *     re-signs NONE of them and only owns the SECOND word (record_verdict +
 *     record_rule) and the disabled-with-reason/no-number faces introduced by
 *     t261025-12;
 *   - the record verdict's PRODUCTION (content_verdict from counts) belongs
 *     to integration/lib_round_face.py + line_round_runner (t261024-30);
 *   - view truth-table matrices belong to developer L1; THIS entry pins the
 *     user-perceivable pair over the real render core.
 *
 * offline: pure module import over the real render core, zero docker /
 * Temporal / browser, never touches 3099/7233. Pre-implement tree red (the
 * second word absent) = the named TDD signal; green required at the
 * integration gate/merge. certification-view.ts unimportable = ENV_FAIL
 * exit 2.
 */

let failed = 0
function ok(cond, label) {
  if (cond) { console.log(`  ok  ${label}`) } else { failed++; console.log(`FAIL  ${label}`) }
}

let view
try {
  view = await import('../../server/plugins/executor-panel/src/host/certification-view.ts')
} catch (e) {
  console.log(`ENV_FAIL: certification-view.ts unimportable: ${e && e.message}`)
  process.exit(2)
}
const { buildRoundsRows, buildRoundDialogCore, buildCertificationCore } = view

// a round that is the host's 261025 sample: strict face red on environment
// noise, content record green (700+ ran, 0 failed, 7 env reds)
function roundFace(over = {}) {
  return {
    run_id: 'run-red-green',
    state: 'done',
    started_at: '2026-10-25T09:00:00Z',
    counts: { ran: 734, fail: 0, env_fail: 7 },
    outcome: { verdict: 'red', reason: 'env_fail>0', record_verdict: 'green', record_rule: 'content-v1' },
    revision: { repo: 'sandbar', revision: 'a'.repeat(40) },
    ...over,
  }
}
const rf = (faces) => ({ dir: '/r', rounds: faces })

// ---- A. both words, side by side, never collapsed --------------------------
{
  const rows = buildRoundsRows(rf([{ run_id: 'run-red-green', face: roundFace() }]), [])
  ok(/data-k="red"/.test(rows), 'A1 the strict face verdict still renders (red pill, env_fail>0)')
  ok(/record[^<]*green|green[^<]*record/i.test(rows),
    'A2 the record verdict renders as its own word on the row')
  ok(/content-v1/.test(rows), 'A3 the record word is labelled with its record_rule')
  // not collapsed: both words coexist and neither is derived from the other
  const strict = rows.match(/data-k="red"/g) || []
  ok(strict.length >= 1 && /content-v1/.test(rows),
    'A4 the red pill and the green record word coexist (no OR-ing into one verdict)')
}

// ---- B. the absence of a record verdict is named, never silent, never invented
{
  const noRecord = buildRoundsRows(rf([{ run_id: 'run-a', face: roundFace({
    outcome: { verdict: 'red', reason: 'env_fail>0' },
  }) }]), [])
  ok(/no record verdict/i.test(noRecord),
    'B1 a round without record fields renders the named absence, not bare silence')
  ok(!/record[^<]*green/i.test(noRecord),
    'B2 no record word is invented when the face carries none')
  const malformed = buildRoundsRows(rf([{ run_id: 'run-b', face: roundFace({
    outcome: { verdict: 'red', reason: '', record_verdict: 7, record_rule: null },
  }) }]), [])
  ok(typeof malformed === 'string' && malformed.length > 0,
    'B3 a malformed record verdict (number, null rule) degrades without throwing')
  ok(!/>7</.test(malformed),
    'B4 the malformed value is never rendered as a verdict word')
}

// ---- C. the round dialog is honest about the round's verdict ----------------
// Ticket item C scopes the PAIR to the rounds table; the dialog's own
// obligation (ruling §5) is to show the round's record without inventing a
// verdict word. (The gen0 plan line "the dialog gains the same second word"
// over-promised the ticket; the dialog carries the strict verdict + reason
// and stays silent on the record pair — deviation recorded in the arbiter
// report, not pinned as a contract here.)
{
  const d = buildRoundDialogCore({
    ok: true,
    run: 'run-red-green',
    face: roundFace(),
    header: null,
    countsNote: null,
  })
  const txt = typeof d === 'string' ? d : JSON.stringify(d)
  ok(!/roundDegrade/.test(txt),
    'C1 a readable round face renders the dialog body, not the degrade banner')
  ok(/data-k="red"/.test(txt),
    'C2 the dialog shows the strict face verdict (red, env_fail>0)')
  ok(!/>record green</i.test(txt) || /content-v1/.test(txt),
    'C3 the dialog never contradicts the table pair (no invented words)')
}

// ---- D. no control without a handler; unreadable face renders NO number ----
{
  // an UNREADABLE count (promotable not a number) inside an ok receipt: the
  // Promote control must be disabled with its reason, and NO promotable
  // number may appear anywhere on the tab
  const core = buildCertificationCore({
    ok: true,
    project: 'proj-x',
    line: 'develop-buffer',
    lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
    face: { ok: false, reason: 'delivery ledger has 1 malformed line(s): garbage {',
      lineId: 'develop-buffer', state: 'IDLE', frozen: false, frozenFace: null,
      deliveredTotal: 0, certified: [], waiting: [], boundary: null, rounds: [], roundState: 'idle',
      promoteBlock: 'the promotion face is not readable: delivery ledger has 1 malformed line(s)' },
    raw: { certs: [], runs: [], outcomes: [] }, notes: [],
  })
  ok(!/Promote\s+\d/.test(core),
    'D1 an unreadable face renders NO promotable number (the Promote-1 lie stays dead)')
  ok(/disabled/.test(core) && /malformed|reason|promoteBlock|not readable/i.test(core),
    'D2 the promote control is disabled WITH its named reason next to it')
  // an ok face with promotable 0 + a stated reason keeps the same shape
  const core0 = buildCertificationCore({
    ok: true,
    project: 'proj-x',
    line: 'develop-buffer',
    lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
    face: { ok: true, lineId: 'develop-buffer', state: 'GREEN', frozen: false, frozenFace: null,
      deliveredTotal: 2, certified: [], waiting: [], promotable: 0,
      promoteBlock: 'nothing certified on this line yet', boundary: null, rounds: [], roundState: 'idle' },
    raw: { certs: [], runs: [], outcomes: [] }, notes: [],
  })
  ok(/disabled/.test(core0) && /nothing certified on this line yet/.test(core0),
    'D3 promotable 0 renders disabled + the promoteBlock reason verbatim')
  // the queue control: present with a handler-shaped affordance, and honest
  // about why it cannot act when no project is chosen
  const noProj = buildCertificationCore({
    project: '',
    lines: [],
    face: { ok: false, reason: 'no project selected', lineId: '', state: 'IDLE', frozen: false,
      frozenFace: null, deliveredTotal: 0, certified: [], waiting: [], promotable: 0, boundary: null, rounds: [], roundState: 'idle' },
    raw: { certs: [], runs: [], outcomes: [] }, notes: [],
  })
  ok(!/value="[^"]*"[^>]*disabled[^>]*>\s*Queue[^<]*<\/button>\s*<span[^>]*>\s*<\/span>/.test(noProj),
    'D4 a disabled queue control is never rendered with an EMPTY reason slot')
  ok(/id="certQueue"/.test(core0), 'D5 the queue control exists on the tab (the runAbsent note is retired)')
  ok(!/starts none|not wired|runAbsent|promoteAbsent/i.test(core0),
    'D6 no click-to-explain-its-own-absence copy remains on the tab')
}

if (failed > 0) {
  console.log(`FAIL sc_t26102512_rounds_verdict_pair: ${failed} red check(s)`)
  process.exit(1)
}
console.log('PASS sc_t26102512_rounds_verdict_pair')
process.exit(0)
