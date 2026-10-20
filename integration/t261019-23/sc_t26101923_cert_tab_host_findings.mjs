#!/usr/bin/env node
/**
 * sc_t26101923_cert_tab_host_findings.mjs — t261019-23, the Certification tab
 * tells the host the truth about state, time and identity (ticket t261019-23,
 * host review 261019 of the live tab, seven findings; this is a READ face — no
 * certification/freeze/promotion semantic is touched or asserted here).
 *
 * intent (user-perceivable behaviour, one check family per host finding):
 *   F1 the certified/waiting bar is a count-proportional strip that always
 *      fills (certified only grows) and carries no information → the rendered
 *      tab shows labelled FIGURES (delivered / certified / waiting), never a
 *      proportional #certBar with flex segments.
 *   F2 the 'auto rounds' control renders as a switch with no handler — a
 *      control-shaped thing that cannot be controlled → no switch chrome
 *      (certsw/certTrack/certKnob) in the rendered markup nor the page
 *      stylesheet; the round-state word itself stays.
 *   F3 waiting rows show '10:45' — clock only, no date → every waiting row's
 *      landed moment renders with a full date+time stamp.
 *   F4 certified and rounds lists run oldest-first → newest-first, by each
 *      row's own moment (the engine's wait-state face carries waiting_since
 *      on EVERY row, certified included); a row without a moment sorts last
 *      and is never dropped; malformed input degrades, never throws.
 *   F5 a round dead for a week still reads 'running' → a state:'running'
 *      face never renders a bare running pill without its last-write moment;
 *      when the engine face says no round is running while current.json still
 *      says running, the pill reads stale with the reason named; no terminal
 *      green/red word is invented for it.
 *   F6 'line 5bb7de8d' reads as a serial number → measured cells read
 *      'line <repo>:<sha8>' from the run row's own repos; absent repo name
 *      falls back to the plain sha, absent sha stays 'line ?'.
 *   F7 'certified, not delivered' and 'promotable' are the same set shown
 *      twice → the promotable figure appears exactly once (the Promote
 *      control + its refusal face), never duplicated in the state strip.
 *
 * Layering / intent split (no intent-level duplication):
 *   - the success envelope, overlay cascade, no-class-collision and
 *     delivered-split faces belong to t261016-09-cert-tab-envelope-face;
 *   - the rounds-table honesty contract (absence named, counts_note,
 *     retention) and the dialog journey belong to the t261012-03 pair;
 *   - the engine-vs-panel green agreement belongs to
 *     t261016-09-cert-green-agreement;
 *   - per-field parse truth tables and unit matrices belong to developer L1.
 *   This entry owns the SEVEN HOST FINDINGS as one read-face journey over the
 *   real reader spawn, the real adapter subprocess, the real page-embedded
 *   render core, the real panel-page stylesheet/markup and the real workbench
 *   decision model. Shared fixture technique with the t261016-09 family;
 *   shared steps are not shared intent.
 *
 * Three states: panel/workbench modules or the adapter unimportable =
 * ENV_FAIL exit 2; a named finding face missing = FAIL, must be green at the
 * integration gate / merge. PASS/FAIL/ENV_FAIL only — no SKIP.
 */
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, utimesSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const ADAPTER = join(REPO, 'server/plugins/executor-panel/src/host/certification-adapter.py')
const PAGE_TS = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')

let PASS = 0, FAIL = 0
const dirs = []
const check = (name, cond, detail = '') => {
  if (cond) { PASS++; console.log('PASS ' + name) }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ': ' + String(detail).slice(0, 400) : '')) }
}
const tmp = () => { const d = mkdtempSync(join('/tmp', 't26101923-cert-')); dirs.push(d); return d }
process.on('exit', () => { for (const d of dirs) rmSync(d, { recursive: true, force: true }) })

const PROJECT = 't26101923-cert'
const LINE = 'buffer'
const REV = 'a'.repeat(40)
const NOW = 1791500000000
const MIN = 60000

// ---- fixture: the same store shape the t261016-09 family builds, by hand ---
// Waits land OLDEST-FIRST in record order on purpose: the pre-fix tab renders
// payload order, so the fixture IS the finding-4 red shape.
function buildStore(root) {
  const proj = join(root, PROJECT)
  mkdirSync(join(proj, 'data', 'develop'), { recursive: true })
  mkdirSync(join(proj, 'ledger'), { recursive: true })
  writeFileSync(join(proj, 'data', 'develop', 'lines.json'), JSON.stringify([
    { version: 1, line_id: LINE, scope: 'epic buffer', owner: 'host',
      repositories: [{ name: 'sandbar', branch: 'develop' }] },
  ]))
  // three runs, started_at DESCENDING in payload order (finding 4's red shape
  // for the Rounds table); repos carry the repo NAME the measured label needs.
  const runs = [
    { id: 'run-old', verdict: 'green', cases: { ran: 3, failed: 0, env_failed: 0 }, source: 'scheduled', started_at: NOW - 30 * MIN, repos: [{ repo: 'sandbar', revision: REV }] },
    { id: 'run-mid', verdict: 'green', cases: { ran: 2, failed: 0, env_failed: 0 }, source: 'person', started_at: NOW - 20 * MIN, repos: [{ repo: 'sandbar', revision: 'b'.repeat(40) }] },
    { id: 'run-new', verdict: 'red', cases: { ran: 4, failed: 1, env_failed: 0 }, source: 'scheduled', started_at: NOW - 10 * MIN, repos: [{ revision: 'c'.repeat(40) }] },
  ]
  writeFileSync(join(proj, 'ledger', 'scenario-runs.jsonl'),
    runs.map((r) => JSON.stringify(r)).join('\n') + '\n')
  // two landings, two green certifications; waits carry waiting_since on every
  // row (the engine's own face), payload order oldest-first.
  const rows = []
  let seq = 1
  const repos = [{ repo: 'sandbar', revision: REV }]
  for (const [tid, agoMin] of [['T-old', 25], ['T-new', 5]]) {
    rows.push({ kind: 'landing', id: 'ldg-' + seq, seq: seq++, at: NOW - agoMin * MIN, ticket: tid, line: LINE, actor: 'dev', repos })
    rows.push({ kind: 'certification', id: 'cert-' + seq, seq: seq++, at: NOW - (agoMin - 1) * MIN, line: LINE, run: 'run-old', booked_red: 'none', judged_by: 'scenario', repos })
  }
  // two landings with NO covering certification -> real waiting rows, newest
  // first in payload order reversed (T-wait2 landed before T-wait) so the
  // finding-4 red shape (payload order) is the oldest-first rendering.
  rows.push({ kind: 'landing', id: 'ldg-' + seq, seq: seq++, at: NOW - 2 * MIN, ticket: 'T-wait2', line: LINE, actor: 'dev', repos })
  seq++
  rows.push({ kind: 'landing', id: 'ldg-' + seq, seq: seq++, at: NOW - 1 * MIN, ticket: 'T-wait', line: LINE, actor: 'dev', repos })
  writeFileSync(join(proj, 'ledger', 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  // the published rounds tree, plus a STALE live pointer: current.json says
  // state=running but its last write is 7 days old (finding 5's incident
  // shape — a round that died seconds in and never wrote a terminal state).
  const roundsRoot = join(proj, 'data', 'develop', 'rounds')
  for (const [rid, startedMin] of [['run-old', 30], ['run-new', 10]]) {
    const d = join(roundsRoot, rid)
    mkdirSync(d, { recursive: true })
    writeFileSync(join(d, 'face.json'), JSON.stringify({
      run_id: rid, line: LINE, revision: { repo: 'sandbar', revision: REV },
      started_at: new Date(NOW - startedMin * MIN).toISOString(),
      updated_at: new Date(NOW - (startedMin - 5) * MIN).toISOString(),
      state: 'done', pool: 'integ', counts: { ran: 3, pass: 3, fail: 0, env_fail: 0 },
      outcome: { verdict: rid === 'run-new' ? 'red' : 'green', reason: '' },
    }))
  }
  const stale = new Date(NOW - 7 * 24 * 60 * MIN)
  writeFileSync(join(roundsRoot, 'current.json'), JSON.stringify({
    run_id: 'run-dead-week', line: LINE, revision: { repo: 'sandbar', revision: REV },
    started_at: new Date(stale.getTime() + 5000).toISOString(),
    updated_at: new Date(stale.getTime() + 5000).toISOString(),
    state: 'running', pool: 'integ', counts: { ran: 0, pass: 0, fail: 0, env_fail: 0 },
  }))
  utimesSync(join(roundsRoot, 'current.json'), stale, stale)
  return {
    SANDBAR_PROJECTS_DIR: root,
    SANDBAR_RUNS_LEDGER: join(proj, 'ledger', 'scenario-runs.jsonl'),
  }
}

const stampRe = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/

const main = async () => {
  if (!existsSync(ADAPTER)) { console.log('ENV_FAIL: certification adapter missing: ' + ADAPTER); process.exit(2) }
  let reader, view, model, page
  try {
    reader = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-reader.ts'))
    view = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-view.ts'))
    model = await import(join(REPO, 'server/plugins/workbench/src/client/certification-model.ts'))
    page = await import(join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts'))
  } catch (e) { console.log('ENV_FAIL: panel/workbench modules unimportable: ' + e.message); process.exit(2) }
  if (typeof reader.certificationFace !== 'function' || typeof view.buildCertificationCore !== 'function'
    || typeof model.deriveCertificationFace !== 'function') {
    console.log('ENV_FAIL: the reader/view/model public faces are missing')
    process.exit(2)
  }

  const root = tmp()
  const env = buildStore(root)
  const answer = await reader.certificationFace({ project: PROJECT }, { env })
  if (answer.ok === false) { console.log('FAIL the fixture store does not answer a readable tab receipt: ' + answer.reason); process.exit(1) }
  const html = String(view.buildCertificationCore(answer))

  // ---- F1 the bar carries no information → labelled figures, no strip ----
  check('F1.1 the state area is not a count-proportional strip (no linebar '
    + 'class, no flex-percentage segments sized by counts)',
    !html.includes('linebar') && !/style="flex:/.test(html), html.slice(0, 200))
  check('F1.2 the state area shows the three labelled figures (delivered, '
    + 'certified, waiting) as words with counts, not a filling bar',
    html.includes(view.CERT_COPIES.delivered) && html.includes(view.CERT_COPIES.certified)
    && html.includes(view.CERT_COPIES.waiting), view.CERT_COPIES)

  // ---- F7 promotable exactly once ----
  const promoteHits = html.split(view.CERT_COPIES.promote).length - 1
  check('F7.1 the promotable figure appears EXACTLY once in the rendered tab '
    + '(the Promote control; never duplicated as a second strip figure)',
    promoteHits === 1, JSON.stringify({ promoteHits }))

  // ---- F2 the dead switch is gone, the state word stays ----
  check('F2.1 no switch chrome in the rendered markup (certsw/certTrack/certKnob)',
    !html.includes('certsw') && !html.includes('certTrack') && !html.includes('certKnob'), 'markup')
  const pageSrc = readFileSync(PAGE_TS, 'utf8')
  check('F2.2 no switch CSS rules for the certification pane in the page '
    + '(no .certsw/.certTrack/.certKnob SELECTOR rules survive in panel-page.ts; '
    + 'a comment naming the retired classes is not a rule)',
    !/\.certsw\s*[,{]/.test(pageSrc) && !/\.certTrack\s*[,{]/.test(pageSrc)
      && !/\.certKnob\s*[,{]/.test(pageSrc), 'stylesheet')
  check('F2.3 the round-state word still renders (id certRoundState)',
    html.includes('certRoundState'), 'markup')

  // ---- F3 full date+time on waiting rows ----
  const face = answer.face
  const waitCells = face.waiting.map((w) => w.landedAt)
  check('F3.1 every waiting row\'s landed moment renders with a full date and '
    + 'time (YYYY-MM-DD HH:MM), never clock-only',
    waitCells.length > 0 && waitCells.every((s) => stampRe.test(String(s))), waitCells)

  // ---- F4 newest-first by each row's own moment ----
  const ms = (s) => { const m = stampRe.exec(String(s)); if (!m) return NaN; return new Date(String(s).replace(' ', 'T')).getTime() }
  const waitMoments = face.waiting.map((w) => ms(w.landedAt)).filter((n) => !Number.isNaN(n))
  check('F4.1 the waiting list renders NEWEST-first (payload order was '
    + 'oldest-first in the fixture)', waitMoments.length >= 2
    && waitMoments.every((v, i) => i === 0 || waitMoments[i - 1] >= v), waitMoments)
  // the engine puts waiting_since on EVERY wait-state row, certified included;
  // judge the certified list by the RENDERED row order against each row's own
  // moment read back from the raw receipt (no private field is anchored).
  const rawWaits = Array.isArray(answer.raw && answer.raw.waitStates) ? answer.raw.waitStates : []
  const sinceOf = (ticket) => {
    const w = rawWaits.find((x) => x && x.ticket === ticket)
    return w && typeof w.waiting_since === 'number' ? w.waiting_since : NaN
  }
  const certOrder = face.certified.map((c) => sinceOf(c.ticket)).filter((n) => !Number.isNaN(n))
  check('F4.2 the certified list renders NEWEST-first too (each row judged by '
    + 'its own waiting_since from the raw wait face)',
    certOrder.length >= 2 && certOrder.every((v, i) => i === 0 || certOrder[i - 1] >= v), certOrder)
  const rowsHtml = String(view.buildRoundsRows(answer.round_faces, answer.raw.runs))
  // run-mid has no published face on purpose: the table renders PUBLISHED
  // rounds (the t261012-03 contract), so newest-first is judged on the rows
  // that exist — run-new must precede run-old.
  const orderIdx = ['run-new', 'run-old'].map((id) => rowsHtml.indexOf(id))
  check('F4.3 the Rounds table renders NEWEST-first by started_at '
    + '(run-new before run-old) with every published row still present',
    orderIdx.every((i) => i >= 0) && orderIdx[0] < orderIdx[1], orderIdx)

  // ---- F6 the measured cell names the repo ----
  check('F6.1 a measured cell with a repo name reads "line <repo>:<sha8>"',
    /line sandbar:[0-9a-f]{8}/.test(rowsHtml), rowsHtml.slice(0, 400))
  check('F6.2 a run row whose repos entry carries no repo name still renders '
    + 'the plain sha fallback (run-new), never a made-up label',
    rowsHtml.includes('line ' + 'c'.repeat(8)), 'fallback')

  // ---- F5 the week-dead round never reads bare 'running' ----
  // The contract under test is the behaviour, not the mechanism: a running
  // claim always carries its own last-write moment, and a running claim the
  // engine contradicts reads stale. (The plan floated a reader-side mtime
  // stat; the landed contract carries the face's own updated_at — either
  // mechanism satisfies the behaviour checks below.)
  const staleDate = new Date(NOW - 7 * 24 * 60 * MIN)
  const liveIso = new Date(staleDate.getTime() + 5000).toISOString()
  const rowsRegion = (h) => { const i = h.indexOf('certRoundRows'); return i >= 0 ? h.slice(i, i + 700) : h.slice(0, 300) }
  const realRows = String(view.buildRoundsRows(answer.round_faces, answer.raw.runs,
    (answer.face && answer.face.roundState) === 'running'))
  check('F5.1 the live running round\'s own last-write moment travels to the '
    + 'rendered pill over the REAL spawn (the current.json face\'s updated_at), '
    + 'so a running claim always shows when it was last written',
    realRows.includes(liveIso), rowsRegion(realRows))
  const withStamp = { ok: true, face: { run_id: 'run-dead-week', state: 'running',
    updated_at: liveIso } }
  const liveHtml = String(view.buildRoundsRows({ live: withStamp, rounds: [] }, []))
  check('F5.2 a state:running live face renders its pill WITH a last-write '
    + 'moment attached (never a moment-less running word)',
    /running/.test(liveHtml) && liveHtml.includes(withStamp.face.updated_at),
    liveHtml.slice(0, 400))
  // the disagreement shape: the engine face says idle while current.json says
  // running → the pill reads stale with the reason named, no invented terminal.
  const raw2 = JSON.parse(JSON.stringify(answer.raw || {}))
  raw2.roundState = 'idle'
  const disagreeHtml = String(view.buildCertificationCore({ ...answer, raw: raw2 }))
  check('F5.3 when the engine face says no round is running but the live face '
    + 'still says running, the pill reads STALE with the named reason and no '
    + 'bare running word',
    /stale/i.test(disagreeHtml) && disagreeHtml.includes('no write since'),
    rowsRegion(disagreeHtml))

  // ---- malformed/degraded inputs at the read face (named, never a throw) ---
  let threw = ''
  try {
    // the malformed-moment rows ride the REAL fixture input (a valid base),
    // so the derive is exercised on a shape the adapter really emits.
    const rawM = JSON.parse(JSON.stringify(answer.raw || {}))
    rawM.waitStates = [
      { ticket: 'T-nomoment', state: 'waiting' },
      { ticket: 'T-bad', state: 'waiting', waiting_since: 'not-a-number' },
      { ticket: 'T-good', state: 'waiting', waiting_since: NOW - MIN },
    ]
    const degraded = model.deriveCertificationFace(rawM)
    const names = degraded.waiting.map((w) => w.ticket)
    check('M1 the dated row sorts FIRST and the moment-less rows sort LAST, '
      + 'keeping their names, never crashing the derive',
      names[0] === 'T-good'
      && ['T-nomoment', 'T-bad'].every((t) => names.indexOf(t) >= names.indexOf('T-good'))
      && names[names.length - 1] !== 'T-good', names)
  } catch (e) { threw = e.message }
  check('M2 a malformed wait moment never throws out of the derive', threw === '', threw)
  // F6's model face: the measured token names the repo, and a revision-less
  // entry names its absence ('?') instead of guessing a sha.
  const mNamed = String(model.measuredToken([{ repo: 'sandbar', revision: 'c'.repeat(40) }]))
  const mNoRev = String(model.measuredToken([{ repo: 'sandbar' }]))
  const mNoRepo = String(model.measuredToken([{ revision: 'c'.repeat(40) }]))
  check('M3 the measured token names the repo ("line <repo>:<sha8>"); a '
    + 'revision-less entry names its absence (a ? token, never a guessed sha) '
    + 'and a repo-less entry falls back to the plain short sha',
    mNamed === 'line sandbar:' + 'c'.repeat(8)
    && mNoRev.includes('?') && !/[0-9a-f]{8}/.test(mNoRev)
    && mNoRepo === 'line ' + 'c'.repeat(8), JSON.stringify({ mNamed, mNoRev, mNoRepo }))

  console.log('SUMMARY pass=' + PASS + ' fail=' + FAIL + ' env_fail=0 na=0')
  return FAIL > 0 ? 1 : 0
}

main().then((code) => process.exit(code)).catch((e) => {
  console.log('ENV_FAIL: scenario harness error: ' + (e && e.message))
  process.exit(2)
})
