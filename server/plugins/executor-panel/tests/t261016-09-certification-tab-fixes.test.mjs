/**
 * t261016-09-certification-tab-fixes.test.mjs — the Certification tab's four
 * live defects (host report 261016), pinned behaviourally at the seams that
 * broke:
 *
 *   D1  the round dialog's grey overlay was always on (inline display:flex
 *       outranked the UA [hidden] rule). Proof: the stylesheet owns the
 *       layout, the markup carries no inline display, and the page JS toggles
 *       ONLY the hidden attribute.
 *   D2  the auto-rounds control inherited the Grants toggle (.sw + ::after)
 *       and the Settings grid row (.knob) styles. Proof: the tab's control
 *       uses the namespaced .certsw/.certTrack/.certKnob names, they exist
 *       only in the certification block, and the Grants/Settings rules are
 *       byte-unchanged.
 *   D3  the reader's SUCCESS envelope dropped round_faces, so the Rounds
 *       table never had rows. Proof: certificationFace passes the section
 *       through, and the real captured live receipt drives a regression.
 *   D4  the panel recomputed an absolute green roll-up where the engine reads
 *       the ledger row's own verdict, and subtracted delivered tickets into
 *       an empty table. Proof: over a seeded real-engine run, the adapter's
 *       wait-state answers `certified` for a verdict-green-but-counts-red
 *       round — the same answer develop_certify.ticket_wait_state gives when
 *       driven with develop_promote._is_green_reader (the oracle), because
 *       the adapter now mirrors that reader exactly; and over the REAL
 *       captured receipt the certified list is non-empty (the engine answers
 *       certified there) with the delivered split stated.
 *
 * Review conditions carried here: the live-capture fixture must fail loudly
 * if it degrades to synthetic data (it does not — the captured file is
 * asserted to be the live envelope); every green-agreement check names its
 * engine oracle.
 */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { buildCertificationCore, CERT_COPIES } from '../src/host/certification-view.ts'
import { spawnCertificationRead, certificationFace, parseCertReceipt } from '../src/host/certification-reader.ts'
import { deriveCertificationFace } from '../../workbench/src/client/certification-model.ts'

let n = 0

// ---- D1: the overlay is closed until hidden is removed --------------------
{
  // the stylesheet owns the layout: closed by default, flex only when open
  assert(PANEL_PAGE_HTML.includes('#roundDlgWrap{position:fixed;inset:0;background:rgba(0,0,0,.45)')
    && PANEL_PAGE_HTML.includes('display:none}')
    && PANEL_PAGE_HTML.includes('#roundDlgWrap:not([hidden]){display:flex}'),
    'the backdrop layout lives in the stylesheet pair (D1)')
  // the markup carries the hidden attribute and NO inline display
  const m = PANEL_PAGE_HTML.match(/<div id="roundDlgWrap"[^>]*>/)
  assert(m && m[0].includes(' hidden') && !/style="[^"]*display/.test(m[0]),
    'the round dialog markup carries hidden and no inline display (D1)')
  // the JS toggles ONLY the hidden attribute — no style writes on the wrap
  assert(PANEL_PAGE_HTML.includes('wrap.hidden = true') && PANEL_PAGE_HTML.includes('wrap.hidden = false'),
    'the page JS opens/closes through the hidden attribute (D1)')
  assert(!/roundDlgWrap[\s\S]{0,200}?\.style\s*\./.test(PANEL_PAGE_HTML),
    'no inline style write ever touches roundDlgWrap (D1)')
  // the close paths stay wired: backdrop click + the ✕ button
  assert(PANEL_PAGE_HTML.includes("if(ev.target === wrap) closeRoundDialog()")
    && PANEL_PAGE_HTML.includes("closest('[data-round-close]')"),
    'backdrop and ✕ both close the dialog (D1)')
  n += 5
}

// ---- D2, re-ruled by t261019-23 (F2): the dead auto-rounds switch is GONE --
{
  const style = PANEL_PAGE_HTML.slice(PANEL_PAGE_HTML.indexOf('<style>'), PANEL_PAGE_HTML.indexOf('</style>'))
  const certSource = readFileSync(fileURLToPath(new URL('../src/host/certification-view.ts', import.meta.url)), 'utf8')
  // a control-shaped element with no handler must not render at all
  assert(!certSource.includes('certsw') && !certSource.includes('certTrack') && !certSource.includes('certKnob'),
    'no switch markup exists in the certification view (F2)')
  assert(!certSource.includes('autoRounds'), 'the auto-rounds copy entry is gone with the switch (F2)')
  for (const sel of ['#paneCert .certsw{', '#paneCert .certTrack{', '#paneCert .certKnob{']) {
    assert(style.split(sel).length === 1, `selector ${sel} removed from the served stylesheet (F2)`)
  }
  // the round-state word survives as plain text
  assert(certSource.includes('id="certRoundState"'), 'the round-state word still renders (F2)')
  // the collision partners are untouched: the Grants toggle and Settings grid
  assert(style.includes('.sw{width:38px;height:21px;border-radius:11px;background:var(--sw-off)')
    && style.includes('.sw::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px'),
    'the Grants toggle rules stay byte-identical (D2)')
  assert(style.includes('.knob{display:grid;grid-template-columns:200px 1fr 240px'),
    'the Settings grid row rule stays byte-identical (D2)')
  n += 7
}

// ---- D3 + D4: the REAL captured live receipt drives the regression --------
// Captured from the live console (read-only GET) before the fix; the file is
// the bug's own evidence (success envelope WITHOUT round_faces). If it ever
// degrades (missing / not the live shape) the test FAILS by name — it never
// silently falls back to synthetic data.
const receiptPath = fileURLToPath(new URL('./fixtures/certification-receipt-real.json', import.meta.url))
let receipt
try {
  receipt = JSON.parse(readFileSync(receiptPath, 'utf8'))
} catch (e) {
  throw new Error('FAIL: the live certification receipt fixture is missing or unreadable ('
    + receiptPath + '): ' + (e instanceof Error ? e.message : String(e))
    + ' — recapture with: curl http://127.0.0.1:3099/sandbar-executor-panel/api/certification?project=sandbar')
}
{
  assert(receipt.ok === true && receipt.project === 'sandbar' && isObj(receipt.raw)
    && Array.isArray(receipt.lines),
    'the captured receipt is the live success envelope (D3 regression input)')
  // The live-ledger oracle: develop_certify.ticket_wait_state driven with
  // develop_promote._is_green_reader over the SAME delivery ledger (captured
  // read-only into the oracle fixture). The captured receipt's own
  // waitStates are the OLD-caliber answers (everything red_implicated) —
  // that gap IS the defect. The face derived over the oracle's words must
  // show a NON-EMPTY certified list: the engine certifies those landings.
  const oracle = JSON.parse(readFileSync(
    fileURLToPath(new URL('./fixtures/certification-receipt-real.oracle.json', import.meta.url)), 'utf8'))
  assert(oracle.note.includes('_is_green_reader') && Array.isArray(oracle.waitStates)
    && oracle.waitStates.some((w) => w.state === 'certified'),
    'the oracle fixture carries the engine green reader\'s answers over the live ledger')
  const face = deriveCertificationFace({ ...receipt.raw, waitStates: oracle.waitStates })
  assert(face.ok === true, 'the live input derives a face')
  const oracleCertified = oracle.waitStates.filter((w) => w.state === 'certified')
  assert(face.certified.length === oracleCertified.length && face.certified.length > 0,
    `the certified list matches the engine oracle and is non-empty (${face.certified.length} rows) (D4)`)
  const deliveredRows = face.certified.filter((r) => r.delivered === true)
  assert(deliveredRows.length > 0,
    `delivered rows stay on the list with their marker (${deliveredRows.length}/${face.certified.length} delivered) (D4)`)
  assert(face.promotable === face.certified.length - deliveredRows.length,
    `promotable counts only the undelivered part (${face.promotable}) (D4)`)
  assert(face.promotable === 0 && face.promoteBlock !== ''
    && /already delivered/.test(face.promoteBlock),
    'the refusal face names its reason when nothing is promotable (D4)')
  // the same face through the page's own render core: certified rows exist
  // (the answer carries the RECOMPUTED face — the captured envelope's own
  // face field is the old caliber's output)
  const html = buildCertificationCore({ ...receipt, face, raw: { ...receipt.raw, waitStates: oracle.waitStates }, round_faces: { dir: '/x', rounds: [] } })
  const certTableHtml = html.slice(html.indexOf('id="certRows"'), html.indexOf('</tbody>', html.indexOf('id="certRows"')))
  assert((certTableHtml.match(/<tr>/g) ?? []).length === face.certified.length,
    `the certified table renders ${face.certified.length} rows over the live data (D4)`)
  assert(html.includes(CERT_COPIES.deliveredMark),
    'delivered rows are marked, not hidden (D4)')
  n += 8
}
function isObj(v) { return typeof v === 'object' && v !== null && !Array.isArray(v) }

// ---- D3: the reader's success envelope carries round_faces ----------------
{
  // An adapter receipt in the engine's own shape (the section the adapter
  // emits; shape pinned by t261012-03-round-faces.test.mjs).
  const adapterReceipt = JSON.stringify({
    ok: true,
    project: 'p',
    lines: [{ line_id: 'develop-buffer', scope: 's', owner: 'host' }],
    per_line: { 'develop-buffer': { ok: true, input: { line: { line_id: 'develop-buffer' } } } },
    meta_notes: [],
    runs_note: '',
    round_faces: {
      dir: '/tmp/rounds',
      live: { ok: true, face: { run_id: 'run-live', state: 'running', started_at: 't', counts: { ran: 1, pass: 1, fail: 0, env_fail: 0 }, revision: { sandbar: 'a' } } },
      rounds: [{ run_id: 'run-a', face: { run_id: 'run-a', state: 'done', started_at: 't', counts: { ran: 2, pass: 2, fail: 0, env_fail: 0 }, outcome: { verdict: 'green', reason: '' }, revision: { sandbar: 'a' } } }],
    },
  })
  const stub = (cmd, args, opts, cb) => cb(null, adapterReceipt)
  const answer = await certificationFace({ project: 'p' }, { execFileFn: stub })
  assert(answer.ok === true && answer.round_faces
    && answer.round_faces.rounds.length === 1 && answer.round_faces.rounds[0].run_id === 'run-a',
    'the success envelope carries the round-faces section (D3)')
  const html = buildCertificationCore(answer)
  assert(html.includes('data-round-link="run-live"') && html.includes('data-round-link="run-a"'),
    'the Rounds table renders rows from the success envelope (D3)')
  assert(!html.includes('carries no round-faces section'),
    'no no-section degrade banner on the success path (D3)')
  // malformed section shapes degrade by name, never throw
  for (const bad of [null, undefined, 7, 'x', []]) {
    const r = parseCertReceipt(JSON.stringify({ ok: true, project: 'p', lines: [], per_line: {}, round_faces: bad }))
    assert(r.ok === true && typeof r.round_faces.error === 'string',
      `round_faces ${JSON.stringify(bad)} degrades to a named section error (D3)`)
  }
  n += 6
}

// ---- D4: the adapter's green caliber is the engine's own reader -----------
// Oracle: develop_certify.ticket_wait_state driven with
// develop_promote._is_green_reader semantics (the ledger row's OWN verdict;
// absent/unknown -> not green). The adapter mirrors that reader exactly, so
// over a seeded real-engine run the panel's wait-states must answer the same
// word the oracle answers — including the host-measured disagreement shape:
// a round whose LEDGER row says green while its counts roll up red.
{
  const home = freshDir('t261016-09-')
  try {
    const dev = join(home, 'sandbar', 'data', 'develop')
    const ledger = join(home, 'sandbar', 'ledger')
    mkdirSync(dev, { recursive: true }); mkdirSync(ledger, { recursive: true })
    writeFileSync(join(dev, 'lines.json'), JSON.stringify([
      { line_id: 'develop-buffer', scope: 's', owner: 'host', repositories: [{ name: 'sandbar', branch: 'develop-buffer' }] },
    ]))
    // One landing covered by one certification whose run's LEDGER ROW says
    // green but whose counts say red (fail+env) — the row the panel used to
    // paint red while the engine certified through it.
    const rows = [
      { kind: 'landing', id: 'ldg-1', ticket: 't1', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: 'r1' }], actor: 'dev', at: 1000, seq: 1 },
      { kind: 'certification', id: 'cert-A', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: 'r1' }], run: 'run-x', judged_by: 'pytest', at: 2000, seq: 2 },
    ]
    writeFileSync(join(ledger, 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
    const headers = [
      // the disagreement row: ledger verdict green, absolute roll-up red
      { v: 'run-ledger-v1', id: 'run-x', repos: [{ repo: 'sandbar', revision: 'r1' }], suite: 'full', source: 'scheduled', env_fp: 'x', conc_width: 1, pool: '', started_at: 900, duration_s: 1.0, cases: { ran: 10, passed: 2, failed: 5, env_failed: 3 }, verdict: 'green' },
      // a second round with NO verdict word: never green, whatever its counts
      { v: 'run-ledger-v1', id: 'run-y', repos: [{ repo: 'sandbar', revision: 'r1' }], suite: 'full', source: 'person', env_fp: 'x', conc_width: 1, pool: '', started_at: 800, duration_s: 1.0, cases: { ran: 4, passed: 4, failed: 0, env_failed: 0 } },
    ]
    const runsPath = join(home, 'runs.jsonl')
    writeFileSync(runsPath, headers.map((h) => JSON.stringify(h)).join('\n') + '\n')
    const env = { ...process.env, SANDBAR_PROJECTS_DIR: home, SANDBAR_RUNS_LEDGER: runsPath }
    const read = await spawnCertificationRead('sandbar', { env })
    assert(read.ok === true && read.per_line['develop-buffer'].ok === true,
      'the seeded store reads through the real adapter + engine')
    const inp = read.per_line['develop-buffer'].input
    const ws = inp.waitStates.find((w) => w.ticket === 't1')
    // The oracle's answer for this ledger (ticket_wait_state + the engine's
    // green reader) is `certified` — the panel must say exactly that.
    assert(ws && ws.state === 'certified' && ws.covered_by === 'cert-A',
      'verdict-green-but-counts-red round CERTIFIES (engine oracle agreement) (D4)')
    // The emitted runs rows carry the row's own verdict verbatim: 'green'
    // stays green, and the verdict-less row does NOT invent one.
    const vx = inp.runs.find((r) => r.id === 'run-x')
    const vy = inp.runs.find((r) => r.id === 'run-y')
    assert(vx && vx.verdict === 'green', 'the disagreement row reads green (D4)')
    assert(vy && vy.verdict == null, 'a verdict-less row invents no verdict (D4)')
    // The model over the same input: covering filter uses the ledger caliber.
    const face = deriveCertificationFace(inp)
    assert(face.boundary && face.boundary.runId === 'run-x',
      'the boundary rests on the ledger-green round (D4)')
    n += 5
  } finally {
    cleanup([home])
  }
}

done(n)
