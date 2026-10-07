// sc_dismiss_status_and_reopen_guard.mjs — t261007-01: a dismissed request leaves the
// waiting count, cannot be re-filed verbatim, and loses to a later answer (grey-box L3,
// harness seam over the production route surface, offline zero docker zero browser,
// never touches 3099/7233).
//
// Intent (ticket scope 2/3/6 + design note §9 change-of-mind rule):
//   A host who dismisses a void request (KI-212: the asked-about work was superseded)
//   gets it out of "Needs your answer" — the read view reports the third status
//   `dismissed` and it no longer counts as waiting. The executor must not re-file the
//   same request verbatim: the append is refused and names the prior dismiss; a
//   re-raise that carries new evidence (a different question line) passes. A host may
//   change their mind: an answer after a dismiss wins — the status returns to
//   `answered`, and the dismiss row stays in the ledger trace. Dismissing an
//   already-answered request is refused (a decision exists; declared developer
//   decision, plan fault-mode item 4, not a §9 ruling).
//
// Assertions anchor the public read view and HTTP statuses, not implementation.
//
// Three states: harness seam missing or the dismiss/status faces not landed = FAIL
// exit 1 named (TDD-phase red expected; arbitrate/merge must be green); node missing
// = ENV_FAIL exit 2.
import { join } from 'node:path'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
// Console-shaped credential (same cookie name/shape the dsh console browser session
// sets; grey-box mechanism understanding — the assertion is behavioral: with it the
// write is accepted, without it refused, as pinned by sc_dismiss_unauth_refusal.mjs).
function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return name + '=v1.AAAA.BBBB'
}
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, text: (await r.text()).slice(0, 300) }))
const getRows = async (base) => fetch(base + `/sandbar-executor-panel/api/requests?project=${PROJ}`)
  .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))

const reqRow = (id, q) => JSON.stringify({ type: 'request', id, project: PROJ, kind: 'question', question: q, detail: 'd', default_action: 'wait', expires_at: null, raised_by: '', at: 1 }) + '\n'

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs missing startHarness (TDD-phase red expected)')
    return C.exit()
  }
  const iso = makeIsoDir('t261007-01-')
  const panelDir = join(iso.dir, 'panel')
  const H = await harness.startHarness({ panelDir, watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  const cookie = { cookie: consoleCookie(H.base) }
  try {
    const ledgerPath = join(panelDir, PROJ, 'requests.jsonl')
    mkdirSync(join(panelDir, PROJ), { recursive: true })
    writeFileSync(ledgerPath,
      reqRow('r1', 'should we redo the migrated importer?') +
      reqRow('r2', 'please approve the temp cleanup') + '\n')
    // r1 is dismissed below; r2 stays waiting so the waiting count has something left.
    writeFileSync(ledgerPath, readFileSync(ledgerPath, 'utf8').replace(/\n$/, ''))

    // S1: dismiss the superseded request with a valid credential → accepted.
    const d = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r1' }, cookie)
    C.case('S1-dismiss-with-credential-accepted', d.status >= 200 && d.status < 300, `status=${d.status} body=${d.text}`)

    // S2: read view — r1 is `dismissed`, r2 still `waiting`; waiting no longer counts r1.
    const v = await getRows(H.base)
    const r1 = v.body?.rows?.find((x) => x.id === 'r1')
    const r2 = v.body?.rows?.find((x) => x.id === 'r2')
    C.case('S2-dismissed-status-in-read-view', r1?.status === 'dismissed', `r1.status=${r1?.status}`)
    C.case('S3-other-request-still-waiting', r2?.status === 'waiting', `r2.status=${r2?.status}`)
    const waitingCount = (v.body?.rows ?? []).filter((x) => x.status === 'waiting').length
    C.case('S4-waiting-count-excludes-dismissed', waitingCount === 1, `waiting=${waitingCount} (r1 dismissed, r2 waiting)`)

    // S5: verbatim re-file of the dismissed question is refused and names the prior dismiss.
    const ref = await jpost(H.base, '/sandbar-executor-panel/api/requests', { project: PROJ, kind: 'question', question: 'should we redo the migrated importer?', detail: 'd', default_action: 'wait' }, cookie)
    C.case('S5-verbatim-refile-refused', ref.status >= 400 && ref.status < 500 && /dismiss/i.test(ref.text), `status=${ref.status} body=${ref.text}`)

    // S6: a re-raise carrying new evidence (different question line) passes.
    const re = await jpost(H.base, '/sandbar-executor-panel/api/requests', { project: PROJ, kind: 'question', question: 'prior request was dismissed; NEW EVIDENCE: importer corrupted 3 ledgers — redo it?', detail: 'd', default_action: 'wait' }, cookie)
    C.case('S6-refile-with-new-evidence-accepted', re.status >= 200 && re.status < 300, `status=${re.status} body=${re.text}`)

    // S7: change of mind — an answer after the dismiss wins; status returns to answered.
    const a = await jpost(H.base, '/sandbar-executor-panel/api/requests/answer', { project: PROJ, id: 'r1', answer: 'redo it with the new importer' }, cookie)
    C.case('S7-answer-after-dismiss-accepted', a.status >= 200 && a.status < 300, `status=${a.status} body=${a.text}`)
    const v2 = await getRows(H.base)
    const r1b = v2.body?.rows?.find((x) => x.id === 'r1')
    C.case('S8-answer-after-dismiss-wins', r1b?.status === 'answered', `r1.status=${r1b?.status} (§9 change-of-mind rule)`)
    const trace = readFileSync(ledgerPath, 'utf8')
    C.case('S9-both-rows-stay-in-trace', trace.includes('"dismiss"') && trace.includes('"answer"'), 'ledger trace keeps both the dismiss and the answer rows')

    // S10: dismissing an already-answered request is refused (developer decision — a
    // decision exists; a dismiss adds nothing).
    const dd = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r1' }, cookie)
    C.case('S10-dismiss-on-answered-refused', dd.status === 409, `status=${dd.status}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
