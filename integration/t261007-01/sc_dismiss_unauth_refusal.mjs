// sc_dismiss_unauth_refusal.mjs — t261007-01: the dismiss write refuses a credential-less
// caller and writes nothing (grey-box L3, harness seam over the production route surface,
// offline zero docker zero browser, never touches 3099/7233).
//
// Intent (ticket scope 7 + KI-193 stance + plan fault-mode item 1):
//   The dismiss write is a host-side write and must pass the same console-session
//   credential gate as the answer write — the dismiss path must not open a second
//   door. A request without any credential must be refused (401/403) and the ledger
//   must be byte-identical afterwards. A malformed body without a credential is
//   refused by the identity gate, never answered by the syntax gate (400) with the
//   write path reachable. The read face stays open so the page keeps loading.
//
// Assertions anchor public contract (HTTP status + on-disk bytes), not implementation:
//   refused = 401/403; nothing written = sha256 of the ledger file identical before/after.
//
// Three states: harness seam missing or the dismiss endpoint not landed = FAIL exit 1
// with the name (TDD-phase red expected; arbitrate/merge must be green); node missing
// or harness load error of environment kind = ENV_FAIL exit 2.
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const sha = (p) => existsSync(p) ? createHash('sha256').update(readFileSync(p)).digest('hex') : 'absent'
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, text: (await r.text()).slice(0, 200) }))

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs missing startHarness (seam contract in lib_panel_seam.mjs header; TDD-phase red expected)')
    return C.exit()
  }
  const iso = makeIsoDir('t261007-01-')
  const panelDir = join(iso.dir, 'panel')
  const H = await harness.startHarness({ panelDir, watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  try {
    // Precondition (user journey): a waiting request exists so a refused dismiss has
    // state to leave untouched.
    const ledgerPath = join(panelDir, PROJ, 'requests.jsonl')
    mkdirSync(join(panelDir, PROJ), { recursive: true })
    writeFileSync(ledgerPath, JSON.stringify({ type: 'request', id: 'r1', project: PROJ, kind: 'question', question: 'seed question?', detail: 'seed', default_action: 'wait', expires_at: null, raised_by: '', at: 1 }) + '\n')
    const before = sha(ledgerPath)

    // D1: no credential on the dismiss endpoint → 401/403, never 2xx.
    const d1 = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r1' })
    C.case('D1-dismiss-no-credential-refused', d1.status === 401 || d1.status === 403, `status=${d1.status} (a second door would answer 2xx)`)

    // D2: forged identity without a credential is refused the same way.
    const d2 = await jpost(H.base, '/sandbar-executor-panel/api/requests/dismiss', { project: PROJ, id: 'r1', by: 'host' })
    C.case('D2-dismiss-forged-by-no-credential-refused', d2.status === 401 || d2.status === 403, `status=${d2.status}`)

    // D3: malformed body, no credential → the identity gate answers (401/403), the
    // syntax gate (400) must not be the first door.
    const d3 = await fetch(H.base + '/sandbar-executor-panel/api/requests/dismiss', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{not-json',
    })
    C.case('D3-malformed-body-no-credential-identity-gate', d3.status === 401 || d3.status === 403, `status=${d3.status}`)

    // D4: after every refusal the ledger is byte-identical — nothing was written.
    const after = sha(ledgerPath)
    C.case('D4-zero-bytes-written-on-refusal', before === after, `ledger ${before === after ? 'unchanged' : 'CHANGED'}`)

    // D5: the read face stays open (the host page keeps loading while writes refuse).
    const g1 = await fetch(H.base + `/sandbar-executor-panel/api/requests?project=${PROJ}`)
    C.case('D5-read-face-still-open', g1.status === 200, `status=${g1.status}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
