// sc_t26100975_writer_e2e_panel_split.mjs — t261009-75, grey-box L3, the
// production route shell (startPluginHarness) + an isolated projects root,
// offline seconds, zero docker/Temporal/browser, never touches 3099.
//
// Ticket acceptance item (4): the clearing path is proven END TO END — the
// answer lands through the SANCTIONED writer (the panel's own answer POST
// route, KI-193's credential gate in front of it), and the item leaves
// "waiting" on the panel's OWN split — not only in the engine's account.
// That is the exact hole of 261010: the steward verified through one face
// while the host read another.
//
// Intent (user-perceivable):
//   E1 the panel's read face shows the seeded request waiting before anything
//      happens (fixture sanity + the "before" half of the journey).
//   E2 the sanctioned answer write succeeds through the production route
//      (200 ok:true) with the panel's credential gate armed — a
//      credential-less POST is refused and the ledger stays untouched.
//   E3 the row the writer landed on disk carries the canonical shape
//      (`at` is a JSON number, `answer` a string) — read back from the FILE,
//      not from the writer's receipt (reader-side evidence).
//   E4 after the write, the panel's OWN read split shows the item out of
//      "waiting" (answered), and the engine's read face agrees on the same
//      file — one ledger, one verdict, both faces.
//
// Three states: route/harness not behaving as declared = FAIL named (TDD red
// expected pre-implement where the fix is pending; E1-E4 must be green at the
// integration gate/merge); harness/node missing = ENV_FAIL exit 2.

import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { loadPanelHarness, makeIsoDir, makeCase, REPO } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const KEY = 'e2e-proj'
const HEAD = 'req-e2e-1'

const headRow = () => ({
  type: 'request', id: HEAD, at: 1000, project: KEY, kind: 'decision',
  question: 'rotate the token?', detail: '', default_action: 'no',
  expires_at: null, raised_by: 'session-exec', subject: 'token rotation',
  epic: 'executor-reliability', source_ticket: 't261009-75',
  source_class: 'executor-session',
})

const jget = (base, url, headers = {}) =>
  fetch(base + url, { headers }).then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))
const jpost = (base, url, body, headers = {}) =>
  fetch(base + url, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) })
    .then(async (r) => { const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch { /* named below */ } return { status: r.status, body: j, text: t.slice(0, 200) } })

/** The panel write gate's credential (same derivation the t261007-02 entry
 *  pins: dsh-auth-<sha256(host)>-shaped console cookie). */
function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return { cookie: name + '=v1.AAAA.BBBB' }
}

const ledgerFile = (root) => join(root, KEY, 'requests.jsonl')

function engineStates(file) {
  const script = `
import sys, json
sys.path.insert(0, ${JSON.stringify(join(REPO, 'server/engine'))})
import request_thread as rt
rows = [json.loads(l) for l in open(${JSON.stringify(file)}, encoding='utf-8') if l.strip()]
print(json.dumps(rt.head_states(rows)))
`
  return JSON.parse(execFileSync('python3', ['-B', '-c', script], {
    cwd: REPO, encoding: 'utf8', timeout: 30000,
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', HOME: '/nonexistent-t261009-75' },
  }))
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.envFail('harness-loadable', String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startPluginHarness !== 'function') {
    C.envFail('harness-loadable', 'executor-panel harness startPluginHarness missing (env seam absent = ENV_FAIL)')
    return C.exit()
  }
  const iso = makeIsoDir('t26100975-e2e-')
  // The harness mounts SANDBAR_PANEL_DIR at panelDir and no outer
  // SANDBAR_PROJECTS_DIR is set, so the panel's ledger root IS the panel dir:
  // seed the head exactly where the production path resolver will read it.
  const root = join(iso.dir, 'panel')
  mkdirSync(join(root, KEY), { recursive: true })
  writeFileSync(ledgerFile(root), JSON.stringify(headRow()) + '\n', 'utf8')
  const GET = '/sandbar-executor-panel/api/requests?project=' + KEY
  const POST = '/sandbar-executor-panel/api/requests/answer'
  try {
    const H = await harness.startPluginHarness({ panelDir: join(iso.dir, 'panel') })
    try {
      const cookie = consoleCookie(H.base)

      // E1 the "before" half: the panel's own split shows the head waiting.
      const before = await jget(H.base, GET)
      const beforeRow = (before.body?.rows ?? []).find((r) => r.id === HEAD)
      C.case('E1-panel-shows-waiting-before', before.status === 200 && beforeRow && beforeRow.status === 'waiting',
        `status=${before.status} row=${JSON.stringify(beforeRow ? { id: beforeRow.id, status: beforeRow.status } : null)}`)

      // E2 the sanctioned write through the production route; credential gate armed.
      const noAuth = await jpost(H.base, POST, { project: KEY, id: HEAD, answer: 'sneaky' })
      const afterNoAuth = readFileSync(ledgerFile(root), 'utf8')
      C.case('E2-credentialless-refused-and-ledger-untouched',
        noAuth.status >= 400 && !afterNoAuth.includes('sneaky') && afterNoAuth.trim().split('\n').length === 1,
        `status=${noAuth.status} lines=${afterNoAuth.trim().split('\n').length}`)
      const ok = await jpost(H.base, POST, { project: KEY, id: HEAD, answer: 'rotate it' }, cookie)
      C.case('E2-sanctioned-answer-lands', ok.status === 200 && ok.body && ok.body.ok === true,
        `status=${ok.status} body=${JSON.stringify(ok.body).slice(0, 200)}`)

      // E3 the landed row's shape, read back from the FILE (reader-side).
      const lines = readFileSync(ledgerFile(root), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
      const ans = lines.find((r) => r.type === 'answer' && r.answer_for === HEAD)
      C.case('E3-writer-row-canonical-shape',
        !!ans && typeof ans.at === 'number' && typeof ans.answer === 'string',
        `answer row=${JSON.stringify(ans ?? null).slice(0, 200)}`)

      // E4 the panel's OWN split after the write + engine agreement on the file.
      const after = await jget(H.base, GET)
      const afterRow = (after.body?.rows ?? []).find((r) => r.id === HEAD)
      C.case('E4-panel-split-out-of-waiting', after.status === 200 && afterRow && afterRow.status === 'answered',
        `status=${afterRow ? afterRow.status : 'absent'} (the host's face must move with the writer's row)`)
      let eng = null
      try { eng = engineStates(ledgerFile(root)) } catch (e) {
        C.envFail('engine-read-runs', String(e).slice(0, 200))
      }
      if (eng) {
        C.case('E4-engine-agrees-answered', eng[HEAD] === 'answered',
          `engine head_states=${JSON.stringify(eng)}`)
      }
    } finally {
      await H.close().catch(() => {})
    }
  } finally {
    iso.clean()
  }
  C.exit()
}

main()
