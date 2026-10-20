/**
 * t261012-03-round-dialog-view.test.mjs — the round dialog's pure render core
 * and its page wiring UT (t261012-03, approved mock
 * notes/discussions/261011-line-round-ui-mock.html §2).
 *
 * Review conditions carried here:
 *  - the dialog render core is the page's OWN implementation (embedded via
 *    String(); the embed table is cross-checked statically);
 *  - the dialog's fetch target is EXACTLY a path PANEL_API_ROUTES carries
 *    (the t261009-44 dead-button lesson);
 *  - terminal vs running is a shape fact: a red round cannot render as a
 *    green one; a could-not-run round cannot look like it ran and passed;
 *  - absences are named: missing log, unknown run, refused answer.
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { PANEL_API_ROUTES } from '../src/host/api.ts'
import { buildRoundDialogCore, buildRoundsRows, countsCell, roundPill, ROUND_COPIES } from '../src/host/certification-view.ts'

let n = 0
const ROUTE = '/sandbar-executor-panel/api/certification/round'

const LIVE = {
  ok: true, project: 'proj-x', run: 'run-live',
  face: { run_id: 'run-live', line: 'develop-buffer', revision: { sandbar: '353b2479' }, started_at: '2026-10-11T22:13:09Z', state: 'running', counts: { ran: 4, pass: 4, fail: 0, env_fail: 0 }, last_scenario: { name: 'sc-a', verdict: 'PASS' }, outcome: null },
  face_reason: null,
  failures: { rows: [{ name: 't-bad', verdict: 'fail', duration: '1.0 s' }], more: 0, judged: 5, last: { name: 'sc-a', verdict: 'PASS', duration: '0.1 s' } },
  failures_absent: null,
  wrote: [], wrote_note: '',
  trigger: 'scheduled', trigger_note: '',
  log_path: '/data/rounds/run-live/suite.log', log_absent: null,
}
const RED = (over = {}) => ({
  ok: true, project: 'proj-x', run: 'run-a',
  face: { run_id: 'run-a', line: 'develop-buffer', revision: { sandbar: '6efc7b3e' }, started_at: '2026-10-11T16:49:00Z', state: 'done', counts: { ran: 10, pass: 8, fail: 70, env_fail: 227 }, outcome: { verdict: 'red', reason: '' } },
  face_reason: null,
  failures: { rows: [{ name: 't-f1', verdict: 'fail', duration: '1.0 s' }, { name: 't-f2', verdict: 'env_fail', duration: '0.2 s' }], more: 50, judged: 305, last: { name: 't-f2', verdict: 'ENV_FAIL', duration: '0.2 s' } },
  failures_absent: null,
  wrote: ['certification cert-1 (line develop-buffer)', 'freeze frz-1 opened (line develop-buffer)'],
  wrote_note: '',
  trigger: 'person', trigger_note: '',
  log_path: '/data/rounds/run-a/suite.log', log_absent: null,
  ...over,
})

// ---- the refused answer renders its named reason ----
{
  const html = buildRoundDialogCore({ ok: false, reason: 'no terminal face is retained for this run' })
  assert(html.includes('id="roundDegrade"') && html.includes('no terminal face is retained for this run'), 'a refused answer names the reason')
  n += 1
}

// ---- the running dialog: result so far, nothing-yet Wrote, log path ----
{
  const html = buildRoundDialogCore(LIVE)
  assert(html.includes('id="roundRunId"') && html.includes('run-live'), 'the run id leads the dialog')
  // t261019-23 (F5): the running pill claims its own last-write moment
  assert(html.includes('data-k="run"') && html.includes(`>${ROUND_COPIES.running} · ${ROUND_COPIES.lastWrite} `), 'a running round renders the run pill with its last write')
  assert(html.includes('353b2479') && html.includes('develop-buffer'), 'revision + line render')
  assert(html.includes(ROUND_COPIES.resultSoFar) && html.includes(countsCell(LIVE.face.counts, '')), 'result-so-far renders the live counts')
  assert(html.includes('sc-a') && html.includes('PASS'), 'the last judged case renders with its verdict')
  assert(html.includes(ROUND_COPIES.nothingYet), 'a running round writes nothing yet — named, never a guessed row')
  assert(html.includes('id="roundLogPath"') && html.includes('/data/rounds/run-live/suite.log'), 'the retained log path renders')
  assert(html.includes('auto'), 'the trigger word maps from the header source')
  n += 8
}

// ---- the red terminal dialog: verdict, honest cap, ONE Wrote line, N clauses ----
{
  const html = buildRoundDialogCore(RED())
  assert(html.includes('data-k="red"') && !html.includes('data-k="green"'), 'a red round renders the red pill and never a green marker')
  assert(html.includes('id="roundWrote"') && (html.match(/id="roundWrote"/g) ?? []).length === 1, 'exactly ONE Wrote line')
  assert(html.includes('certification cert-1') && html.includes('freeze frz-1 opened'), 'the Wrote line names EVERY fact (cert + the freeze it opened)')
  assert(html.includes('… 50 more'), 'the failures cap is an honest exact +N more')
  assert(html.includes('id="roundLastJudged"') && html.includes('ENV_FAIL'), 'the last judged line carries the log verdict token')
  n += 5
}

// ---- the could-not-run dialog: state=failed is distinguishable, reason named ----
{
  const d = RED({
    run: 'run-f',
    face: { run_id: 'run-f', state: 'failed', counts: { ran: 0, pass: 0, fail: 0, env_fail: 0 }, outcome: { verdict: null, reason: 'runner_timeout:3600s' } },
    failures: null, failures_absent: 'retained log not written',
    wrote: [], wrote_note: '',
  })
  const html = buildRoundDialogCore(d)
  assert(html.includes('data-k="none"') && html.includes(ROUND_COPIES.couldNotRun), 'a could-not-run round renders the none pill with its own words')
  assert(!html.includes('data-k="green"') && !html.includes('data-k="red"'), 'it never reads as a judged verdict')
  assert(html.includes('runner_timeout:3600s'), 'the could-not-run reason renders as the Wrote line')
  assert(html.includes(`id="roundFailuresAbsent">${ROUND_COPIES.logAbsent.split(' ').slice(0, 3).join(' ')}`) || html.includes('retained log not written'), 'a missing retained log is a named absence in the Failures block')
  n += 4
}

// ---- no_proof + unreadable outcomes never read green ----
{
  assert(roundPill({ state: 'done', outcome: { verdict: 'no_proof', reason: 'ran nothing' } }).k === 'none', 'no_proof renders the none pill')
  assert(roundPill({ state: 'done', outcome: { verdict: null, reason: '' } }).text === ROUND_COPIES.unreadableOutcome, 'a null verdict never reads green')
  assert(roundPill(null).k === 'none', 'a missing face never reads green')
  assert(roundPill({ state: 'done', outcome: { verdict: 'green', reason: '' } }).k === 'green', 'only an explicit green verdict reads green')
  assert(countsCell(null, 'counts unreadable: no recognizable lines') === 'counts unreadable: no recognizable lines', 'a counts_note renders verbatim instead of numbers')
  assert(countsCell(undefined, '') === ROUND_COPIES.countsUnreadable, 'a face without counts names the absence, never zeros')
  n += 6
}

// ---- the table: named rows and the older-rounds line ----
{
  const rows = buildRoundsRows({
    dir: '/r',
    live: { ok: true, face: LIVE.face },
    rounds: [
      { run_id: 'run-x', absent: 'terminal face not written' },
      { run_id: 'run-t', reason: 'face is not valid JSON: x' },
    ],
    older: 4,
  }, [{ id: 'run-live', source: 'scheduled' }])
  assert(rows.includes('data-round-link="run-live"'), 'the live row leads with its link')
  assert(rows.includes('terminal face not written') && rows.includes('face is not valid JSON'), 'per-row named states render verbatim')
  assert(rows.includes('4 older rounds not shown'), 'the render cap is declared, never a silent drop')
  const empty = buildRoundsRows({ dir: '/r', rounds: [] }, [])
  assert(empty.includes('colspan="6"'), 'no rounds on disk renders the em-dash empty row')
  n += 4
}

// ---- page wiring: the embed + the fetch target are real ----
{
  assert(PANEL_PAGE_HTML.includes('id="roundDlgWrap"') && PANEL_PAGE_HTML.includes('id="roundDlg"'), 'the dialog overlay mounts on the Certification pane')
  assert(PANEL_PAGE_HTML.includes('function buildRoundDialogCore('), 'the dialog core is page-embedded (one implementation)')
  assert(PANEL_PAGE_HTML.includes('function buildRoundsRows(') && PANEL_PAGE_HTML.includes('function countsCell('), 'the rounds helpers are page-embedded too')
  assert(PANEL_PAGE_HTML.includes("'/sandbar-executor-panel/api/certification/round?project='"), 'the page fetches the round route')
  const fetched = [...PANEL_PAGE_HTML.matchAll(/'(\/sandbar-executor-panel\/api\/[a-z/]+)\?/g)].map((m) => m[1])
  const table = new Set(PANEL_API_ROUTES.map((r) => r.path))
  for (const p of fetched) assert(table.has(p), 'page-fetched path registered: ' + p)
  assert(table.has(ROUTE), 'the round route is in PANEL_API_ROUTES')
  assert(PANEL_PAGE_HTML.includes('data-round-link'), 'the run id is wired as the entry link')
  assert(PANEL_PAGE_HTML.includes('closeRoundDialog'), 'the dialog close path is wired')
  n += 4 + fetched.length
}

done(n)
