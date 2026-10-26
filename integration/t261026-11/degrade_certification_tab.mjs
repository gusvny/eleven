/**
 * degrade_certification_tab.mjs — the degrade matrix on the panel
 * Certification tab (t261026-11). Face under judgement: buildCertificationCore
 * over the real certification receipt.
 *
 * The real payload (shape 5) is the engine adapter's own receipt —
 * certification-adapter.py emits one JSON line read from the project store.
 * A hand-written stub receipt proves nothing (it was written by the same mind
 * that wrote the reader), so the fixture MUST be a captured receipt. This
 * lane's sandbox has no reachable project store, so the fixture is not yet
 * captured: the scenario is ENV_FAIL (exit 2, honest) until
 * fixtures/cert-receipt.json exists — see fixtures/README.md for the capture
 * command. Registration happens only after a green run.
 *
 * The four broken shapes run unconditionally: the reader's degrade contract
 * ("nothing is invented") must speak a named reason for each.
 *
 * Run: node integration/t261026-11/degrade_certification_tab.mjs
 */
import { existsSync, readFileSync } from 'node:fs'
import { runDegradeMatrix } from '../lib_degrade_matrix.mjs'

const FIXTURE = new URL('./fixtures/cert-receipt.json', import.meta.url).pathname
const VIEW = new URL('../../server/plugins/executor-panel/src/host/certification-view.ts', import.meta.url).pathname
const view = await import(VIEW)

if (!existsSync(FIXTURE)) {
  console.log('ENV_FAIL: fixtures/cert-receipt.json not captured yet — the real receipt must come from the producer (see fixtures/README.md), never a stub')
  process.exit(2)
}

let real
try {
  real = JSON.parse(readFileSync(FIXTURE, 'utf8'))
} catch (e) {
  console.log(`ENV_FAIL: captured receipt unparseable: ${e.message}`)
  process.exit(2)
}

const r = runDegradeMatrix({
  face: 'certification-tab',
  // Faithful adapter: the face's entry is buildCertificationCore(data).
  call: (payload) => view.buildCertificationCore(
    payload === null || payload === undefined || typeof payload !== 'object' ? (payload === undefined ? {} : payload) : payload,
  ),
  real,
  copiesKey: 'reason',
  expect: (out) => ({
    rounds_table: typeof out === 'string' && out.includes('certRoundRows'),
    no_red_banner_on_healthy: typeof out === 'string' && !out.includes('certDegrade'),
  }),
})

process.exit(r.ok ? 0 : 1)
