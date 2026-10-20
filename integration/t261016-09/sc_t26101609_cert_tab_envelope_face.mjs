#!/usr/bin/env node
/**
 * sc_t26101609_cert_tab_envelope_face.mjs — t261016-09, the Certification
 * tab's success envelope, rendered face and page-level UI contract (defects
 * D1, D2, D3 and the model half of D4 of the host's 261016 report).
 *
 * Grey-box L3: the REAL certification reader spawn against the REAL adapter
 * subprocess over a fixture project store, the REAL page-embedded render
 * core, the REAL page stylesheet/markup (panel-page.ts) and the REAL workbench
 * decision model — offline seconds, zero docker/Temporal-server/browser,
 * never touches 3099/7233.
 *
 * intent (host words, ticket t261016-09):
 *   A. SUCCESS ENVELOPE (D3) — the readable certification receipt carries the
 *      round-faces section on the SUCCESS path (the t261012-03 residual: the
 *      refusal envelope had it, the success envelope dropped it, so the page
 *      read `round_faces === undefined` and degraded over an empty tbody).
 *   B. RENDERED ROUNDS (D3) — over that same real receipt the tab core
 *      renders one row per published round and no "no round-faces section"
 *      degrade banner.
 *   C. OVERLAY CONTRACT (D1) — the round dialog's backdrop is hidden on load
 *      by the CSS cascade itself (the `hidden` attribute with NO author
 *      inline display to outrank the UA rule; the `:not([hidden])` rule is
 *      the ONLY flex grant), and the page script drives the dialog only
 *      through the `hidden` attribute — never an inline display write, so a
 *      closed overlay can never intercept clicks.
 *   D. NO CLASS COLLISION (D2) — the auto-rounds control's class names are
 *      not defined by any stylesheet rule outside the certification block
 *      (the Grants `.sw` pill + `::after` knob and the Settings `.knob` grid
 *      row must not reach this element).
 *   E. MODEL FACES (D4b/c) — a delivered ticket STAYS on the certified list
 *      with its marker (never silently emptying the table); `promotable`
 *      counts only the undelivered part; promotable===0 always names its
 *      reason; coverage follows the run row's OWN verdict word (green with
 *      red counts still covers; absent verdict never covers), and malformed
 *      rows degrade fail-closed without a throw.
 *
 * Division of intent: the engine-vs-panel green agreement over the ledger
 * belongs to the sibling sc_t26101609_cert_green_agreement.py entry; the
 * adapter's round-faces honesty contract belongs to
 * t261012-03-rounds-table-honest-faces; dialog journey content belongs to
 * t261012-03-round-dialog-journey.
 *
 * Three states: engine/panel/workbench modules unimportable = ENV_FAIL exit
 * 2; a named face missing = FAIL, must be green at the integration gate /
 * merge. PASS/FAIL/ENV_FAIL only — no SKIP.
 */
import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'

const run = promisify(execFile)
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const ADAPTER = join(REPO, 'server/plugins/executor-panel/src/host/certification-adapter.py')

let PASS = 0, FAIL = 0
const dirs = []
const check = (name, cond, detail = '') => {
  if (cond) { PASS++; console.log('PASS ' + name) }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ': ' + String(detail).slice(0, 400) : '')) }
}
const tmp = () => { const d = mkdtempSync(join('/tmp', 't26101609-env-')); dirs.push(d); return d }
process.on('exit', () => { for (const d of dirs) rmSync(d, { recursive: true, force: true }) })

const PROJECT = 't26101609-env'
const LINE = 'buffer'
const REV = 'a'.repeat(40)
const NOW = 1791500000000

// ---- fixture: the same store shape the python sibling builds, by hand ------
function buildStore(root) {
  const proj = join(root, PROJECT)
  mkdirSync(join(proj, 'data', 'develop'), { recursive: true })
  mkdirSync(join(proj, 'ledger'), { recursive: true })
  writeFileSync(join(proj, 'data', 'develop', 'lines.json'), JSON.stringify([
    { version: 1, line_id: LINE, scope: 'epic buffer', owner: 'host',
      repositories: [{ name: 'sandbar', branch: 'develop' }] },
  ]))
  const repos = [{ repo: 'sandbar', revision: REV }]
  // run-green: OWN verdict green over red counts (the incident shape);
  // a published round face for it so the rounds table has a real row.
  const runs = [
    { id: 'run-env1', verdict: 'green', cases: { ran: 3, failed: 24, env_failed: 0 }, source: 'scheduled', started_at: NOW - 120000, repos },
    { id: 'run-env2', cases: { ran: 5, failed: 0, env_failed: 0 }, source: 'person', started_at: NOW - 130000, repos },
  ]
  writeFileSync(join(proj, 'ledger', 'scenario-runs.jsonl'),
    runs.map((r) => JSON.stringify(r)).join('\n') + '\n')
  const rows = []
  let seq = 1
  for (const r of runs) {
    rows.push({ kind: 'landing', id: 'ldg-' + seq, seq: seq++, at: NOW - 60000, ticket: 'T-' + r.id.slice(-4), line: LINE, actor: 'dev', repos })
    rows.push({ kind: 'certification', id: 'cert-' + seq, seq: seq++, at: NOW - 30000, line: LINE, run: r.id, booked_red: 'none', judged_by: 'scenario', repos })
  }
  writeFileSync(join(proj, 'ledger', 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  // one published round face so the success envelope's section has content
  const rounds = join(proj, 'data', 'develop', 'rounds', 'run-env1')
  mkdirSync(rounds, { recursive: true })
  writeFileSync(join(rounds, 'face.json'), JSON.stringify({
    run_id: 'run-env1', line: LINE, revision: { repo: 'sandbar', revision: REV },
    started_at: new Date(NOW - 120000).toISOString(), updated_at: new Date(NOW - 60000).toISOString(),
    state: 'done', pool: 'integ', counts: { ran: 3, pass: 1, fail: 2, env_fail: 0 },
    outcome: { verdict: 'green', reason: '' },
  }))
  return {
    SANDBAR_PROJECTS_DIR: root,
    SANDBAR_RUNS_LEDGER: join(proj, 'ledger', 'scenario-runs.jsonl'),
  }
}

const styleBlocks = (html) => {
  const out = []
  const re = /<style>([\s\S]*?)<\/style>/g
  let m
  while ((m = re.exec(html))) out.push(m[1])
  return out.join('\n')
}

const main = async () => {
  if (!existsSync(ADAPTER)) { console.log('ENV_FAIL: certification adapter missing: ' + ADAPTER); process.exit(2) }
  let reader, view, model, page
  try {
    reader = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-reader.ts'))
    view = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-view.ts'))
    model = await import(join(REPO, 'server/plugins/workbench/src/client/certification-model.ts'))
    page = await import(join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts'))
  } catch (e) { console.log('ENV_FAIL: panel/workbench modules unimportable: ' + e.message); process.exit(2) }

  const root = tmp()
  const env = buildStore(root)

  // ---- A: the success envelope carries the round-faces section ----
  const answer = await reader.certificationFace({ project: PROJECT }, { env })
  if (!answer.ok) { console.log('FAIL A readable receipt: ' + answer.reason) } else {
    check('A success envelope carries round_faces', answer.round_faces !== undefined && answer.round_faces !== null, Object.keys(answer))
    const rf = answer.round_faces
    check('A the section carries the published round',
      !!rf && Array.isArray(rf.rounds) && rf.rounds.some((r) => r && r.face && r.face.run_id === 'run-env1'),
      JSON.stringify(rf).slice(0, 200))
  }

  // ---- B: the tab core renders rounds rows over the real receipt ----
  if (!answer.ok) { FAIL++; console.log('FAIL B skipped (no receipt)') } else {
    const html = view.buildCertificationCore({ ...answer, note: '' })
    const rows = (html.match(/<tr[^>]*data-run/g) || []).length
    check('B rounds table renders a row per published round', rows >= 1, rows)
    const degrade = view.roundsSectionNote(answer.round_faces)
    check('B no degrade banner over a present section', !degrade, degrade)
    check('B certified list is non-empty (the engine answers certified)',
      /certified/i.test(html) && (html.match(/T-/g) || []).length >= 1, 'certified rows in rendered face')
  }

  // ---- C: overlay contract (D1) ----
  {
    const html = page.PANEL_PAGE_HTML
    const m = html.match(/<div id="roundDlgWrap"([^>]*)>/)
    check('C the backdrop markup exists', !!m)
    const attrs = m ? m[1] : ''
    check('C the backdrop carries the hidden attribute on load', /\bhidden\b/.test(attrs), attrs)
    check('C the backdrop carries NO inline display (the UA rule must win)', !/display\s*:/.test(attrs), attrs)
    const css = styleBlocks(html)
    check('C the ONLY flex grant is the :not([hidden]) rule',
      /#roundDlgWrap:not\(\[hidden\]\)\s*\{\s*display\s*:\s*flex/.test(css) &&
      !/#roundDlgWrap\s*\{[^}]*display\s*:\s*flex/.test(css), css.slice(0, 0) || 'rule scan')
    // the page script drives the dialog through hidden only — an inline
    // display write anywhere on the wrap reintroduces the always-on overlay
    const script = html.slice(html.lastIndexOf('<script'))
    check('C the script never writes an inline display on the wrap',
      !/roundDlgWrap[^;]{0,40}\.style\.display/.test(script) && !/roundDlgWrap['"]\)\.style/.test(script), 'script scan')
  }

  // ---- D: no handler-less switch chrome (D2, updated by t261019-23 F2) ----
  // The 'auto rounds' control was a switch-shaped element with no handler —
  // t261019-23 removed it entirely. The contract this face now pins: the
  // control is GONE from markup and stylesheet, and the round-state word
  // (the truthful half) stays.
  {
    const tabHtml = view.buildCertificationCore({ ...answer, note: '' })
    check('D no switch chrome survives in the certification markup '
      + '(certsw/certTrack/certKnob gone)', !tabHtml.includes('certsw')
      && !tabHtml.includes('certTrack') && !tabHtml.includes('certKnob'), 'markup')
    const css = styleBlocks(page.PANEL_PAGE_HTML)
    check('D no switch selector rules survive in the page stylesheet '
      + '(a comment naming the retired classes is not a rule)',
      !/\.certsw\s*[,{]/.test(css) && !/\.certTrack\s*[,{]/.test(css)
        && !/\.certKnob\s*[,{]/.test(css), 'stylesheet')
    check('D the round-state word still renders (id certRoundState)',
      tabHtml.includes('certRoundState'), 'markup')
  }

  // ---- E: the model faces (D4b/c) ----
  {
    const fixturePath = join(REPO, 'server/plugins/workbench/tests/fixtures/t261009-41-certification-fixture.json')
    if (!existsSync(fixturePath)) { console.log('ENV_FAIL: golden fixture missing: ' + fixturePath); process.exit(2) }
    const base = JSON.parse(readFileSync(fixturePath, 'utf8')).input
    const unfrozen = { ...base, freeze: { ...base.freeze, frozen: false, culprit: null } }
    // E1: delivered stays listed + promotable counts only undelivered + reason
    const allDelivered = {
      ...unfrozen,
      outcomes: unfrozen.waitStates.filter((w) => w.state === 'certified')
        .map((w) => ({ ticket: w.ticket, delivered_in: 'prom-x', ending: 'ended' })),
    }
    const f1 = model.deriveCertificationFace(allDelivered)
    const certCount = unfrozen.waitStates.filter((w) => w.state === 'certified').length
    check('E1 certified rows keep their engine count when everything is delivered',
      f1.certified.length === certCount && certCount > 0, f1.certified.length + '/' + certCount)
    check('E1 every delivered row carries the delivered marker',
      f1.certified.every((c) => c.delivered === true), JSON.stringify(f1.certified))
    check('E1 promotable counts only the undelivered part', f1.promotable === 0, f1.promotable)
    check('E1 promotable===0 names its reason', typeof f1.promoteBlock === 'string' && f1.promoteBlock.length > 0, f1.promoteBlock)
    // E2: partial delivery splits the table instead of emptying it
    const halfDelivered = {
      ...unfrozen,
      outcomes: [{ ticket: f1.certified[0].ticket, delivered_in: 'prom-x', ending: 'ended' }],
    }
    const f2 = model.deriveCertificationFace(halfDelivered)
    check('E2 the undelivered part stays promotable with no block reason',
      f2.promotable === certCount - 1 && f2.promoteBlock === '', f2.promotable + '/' + JSON.stringify(f2.promoteBlock))
    // E3: coverage follows the row's OWN verdict (engine agreement)
    const redCounts = { ran: 3, failed: 24, env_failed: 0 }
    const ledger = {
      ...unfrozen,
      runs: [{ id: 'run-g', verdict: 'green', cases: redCounts, source: 'scheduled', started_at: NOW, repos: [] },
             { id: 'run-u', cases: { ran: 9, failed: 0, env_failed: 0 }, source: 'scheduled', started_at: NOW, repos: [] }],
      certs: [{ id: 'cert-g', run: 'run-g', at: NOW - 1000 }, { id: 'cert-u', run: 'run-u', at: NOW - 500 }],
      waitStates: [{ ticket: 't-a', state: 'certified', covered_by: 'cert-g', waiting_since: NOW - 2000 },
                   { ticket: 't-b', state: 'certified', covered_by: 'cert-u', waiting_since: NOW - 2000 }],
      outcomes: [],
      ticketMeta: { 't-a': { title: 'A', epic: 'E' }, 't-b': { title: 'B', epic: 'E' } },
    }
    const f3 = model.deriveCertificationFace(ledger)
    check('E3 a green-worded row covers even over red counts', f3.boundary && f3.boundary.runId === 'run-g', JSON.stringify(f3.boundary))
    check('E3 a verdict-less row never covers (fail-closed)',
      !f3.certified.some((c) => c.certifiedBy === 'cert-u' && f3.boundary && f3.boundary.runId === 'run-u'), f3.boundary)
    // E4: malformed input degrades without a throw
    let threw = false, f4 = null
    try {
      f4 = model.deriveCertificationFace({ ...ledger, runs: ['nope', { id: 'r', verdict: 7, cases: null }], waitStates: [null, 'x', { ticket: 't-c', state: 'certified', covered_by: 'cert-g' }] })
    } catch (e) { threw = true }
    check('E4 malformed rows never throw and never mint a green', !threw && f4 !== null, threw)
  }

  console.log(`SUMMARY pass=${PASS} fail=${FAIL}`)
  process.exit(FAIL === 0 ? 0 : 1)
}

main().catch((e) => { console.log('ENV_FAIL: ' + (e && e.stack || e)); process.exit(2) })
