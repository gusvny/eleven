// sc_dismiss_writer_identity.mjs — t261007-01: the dismiss ledger row records the
// server-derived console identity, never the caller's claim (grey-box L3, harness seam
// over the production route surface, offline zero docker zero browser, never touches
// 3099/7233).
//
// Intent (ticket acceptance "a ledger read-back that shows the dismiss row carrying the
// console session identity" + scope 7 "by must not be caller-asserted" + KI-193 stance):
//   With a valid console-shaped credential, a dismiss whose body forges
//   by:<someone-else> records the writer as the identity the credential proves
//   (`host`), not the caller's claim; the mismatch is visible in the row
//   (by_claimed + writer_mismatch), never silently rewritten. Reader-side evidence:
//   the row is read back from the ledger FILE on disk, not from the write response.
//
// Three states: harness seam missing or the identity faces not landed = FAIL exit 1
// named (TDD-phase red expected; arbitrate/merge must be green); node missing =
// ENV_FAIL exit 2.
import { join } from 'node:path'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return name + '=v1.AAAA.BBBB'
}
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, text: (await r.text()).slice(0, 200) }))

const dismissRows = (ledgerPath) => readFileSync(ledgerPath, 'utf8')
  .split('\n').filter((l) => l.trim())
  .map((l) => { try { return JSON.parse(l) } catch { return null } })
  .filter((r) => r && r.type === 'dismiss')

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
    writeFileSync(ledgerPath, JSON.stringify({ type: 'request', id: 'r1', project: PROJ, kind: 'question', question: 'q1?', detail: 'd', default_action: 'wait', expires_at: null, raised_by: '', at: 1 }) + '\n')

    // I1: honest body (no by) — accepted.
    const h = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r1' }, cookie)
    C.case('I1-dismiss-honest-body-accepted', h.status >= 200 && h.status < 300, `status=${h.status} body=${h.text}`)

    // Reader-side evidence: read the row back from the ledger FILE.
    const rows = dismissRows(ledgerPath)
    C.case('I2-dismiss-row-on-disk', existsSync(ledgerPath) && rows.length === 1, `dismiss rows on disk=${rows.length}`)
    const row = rows[0] ?? {}

    // I3: the row shape carries the ticket fields.
    C.case('I3-row-shape-dismiss-for-at-by', row.dismiss_for === 'r1' && typeof row.at === 'number' && typeof row.by === 'string' && row.by.length > 0,
      `dismiss_for=${row.dismiss_for} at=${typeof row.at} by=${JSON.stringify(row.by)}`)

    // I4: the recorded writer is the fixed identity the credential proves.
    C.case('I4-writer-is-host', row.by === 'host', `by=${JSON.stringify(row.by)} (credential proves host; caller claim must not win)`)

    // I5: a forged body by is visible, not silently accepted or stripped.
    writeFileSync(ledgerPath, readFileSync(ledgerPath, 'utf8') + JSON.stringify({ type: 'request', id: 'r2', project: PROJ, kind: 'question', question: 'q2?', detail: 'd', default_action: 'wait', expires_at: null, raised_by: '', at: 2 }) + '\n')
    const f = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r2', by: 'executor-7' }, cookie)
    C.case('I5-forged-by-dismiss-accepted', f.status >= 200 && f.status < 300, `status=${f.status}`)
    const forged = dismissRows(ledgerPath).find((r) => r.dismiss_for === 'r2') ?? {}
    C.case('I6-forged-by-recorded-as-host', forged.by === 'host', `by=${JSON.stringify(forged.by)}`)
    C.case('I7-mismatch-visible', forged.by_claimed === 'executor-7' && forged.writer_mismatch === true,
      `by_claimed=${JSON.stringify(forged.by_claimed)} writer_mismatch=${forged.writer_mismatch}`)

    // I8: read view reports the forged-by dismissal as `dismissed` (the exact
    // provenance field name is implementation; the contract is the third status).
    const v = await fetch(H.base + `/sandbar-executor-panel/api/requests?project=${PROJ}`).then((r) => r.json()).catch(() => null)
    const r2v = v?.rows?.find((x) => x.id === 'r2')
    C.case('I8-read-view-dismissed', r2v?.status === 'dismissed', `status=${r2v?.status}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
