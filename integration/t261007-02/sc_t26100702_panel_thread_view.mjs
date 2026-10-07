// sc_t26100702_panel_thread_view.mjs — the panel reads and shows the thread:
// five states, waiting = open only, the two ownership fields, the delegated
// answer trio, and the host-only state route (t261007-02, grey-box L2/L3,
// harness seam + in-memory ledgers, offline zero docker zero browser,
// red-line zero-touch 3099).
//
// Intent (user-perceivable; ticket items 2, 7, 10):
//   V1 the read view turns reply/state/link rows into a thread view: a head's
//      status is one of the five states (open/answered/resolved/dismissed/
//      superseded) derived from its state rows — the host can see WHERE an
//      item stands, not just whether it was answered.
//   V2 the waiting list keeps its meaning: open items only. An answered,
//      resolved, dismissed or superseded head leaves it; an EXPIRED open head
//      stays in it (expiry drives display and reminder level only, ticket
//      item 8 — it never closes and never silences).
//   V3 the two fields and the trio are visible as separate view fields:
//      source_ticket (fact, may be empty), epic (+ "none" + its reason),
//      and by / via / anchor on a delegated answer — three columns, not one
//      blob (ticket item 7).
//   V4 unknown/new row kinds are counted as malformed, never silently dropped
//      (the ledger read contract the panel already declares).
//   W  the host-only state route: a credential-less POST is refused (401/403,
//      KI-193 face) and the ledger stays byte-identical; a credentialed host
//      call sets answered/dismissed; the host cannot resolved-without-evidence
//      (refusal names the field) and cannot set superseded by hand.
//
// Anchors: public HTTP contract (status codes) + the panel read view fields +
// ledger bytes. Module/export missing = FAIL named (TDD-phase red expected;
// arbitrate/merge must be green).
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const REQUESTS = join(REPO, 'server/plugins/executor-panel/src/host/requests.ts')
const PROJ = 't26100702fixture'
const sha = (p) => existsSync(p) ? createHash('sha256').update(readFileSync(p)).digest('hex') : 'absent'
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST', headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, text: (await r.text()).slice(0, 200) }))

function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return name + '=v1.AAAA.BBBB'
}

// One head + the row shapes the ledger now carries (append-only, per plan v2).
function seedRows() {
  const head = (id, subject, epic, ticket, expires_at = null) => ({
    type: 'request', id, project: PROJ, subject, epic, source_ticket: ticket,
    source_class: 'executor-session', raised_by: 'session-exec', kind: 'finding',
    question: 'Q: ' + subject, text: 'Q: ' + subject, at: 1, expires_at,
  })
  return [
    head('h-open', 'flock window', 'executor-reliability', 't261007-02', 1), // expires in the past: expiry must not close it
    head('h-answered', 'stale copy', 'localization', ''),
    head('h-resolved', 'torn line', 'executor-reliability', 't261006-05'),
    { type: 'state', state_for: 'h-answered', state: 'answered', by: 'host', at: 2 },
    { type: 'state', state_for: 'h-resolved', state: 'answered', by: 'host', at: 2 },
    { type: 'state', state_for: 'h-resolved', state: 'resolved', by: 'session-exec', evidence: 't261006-11', at: 3 },
    head('h-dismissed', 'dup alarm', 'executor-reliability', ''),
    { type: 'state', state_for: 'h-dismissed', state: 'dismissed', by: 'host', at: 2 },
    head('h-superseded', 'old shape', 'localization', 't261005-01'),
    { type: 'link', from_id: 'h-open', to_id: 'h-superseded', kind: 'supersedes', at: 4 },
    { type: 'state', state_for: 'h-superseded', state: 'superseded', by: 'machine', at: 5 },
    head('h-delegated', 'delegated probe', 'localization', ''),
    { type: 'reply', reply_for: 'h-delegated', text: 'Granted for tonight only.', by: 'host', via: 'integration', anchor: 'give it the stage restart, one night only', at: 6 },
    { type: 'row-kind-from-the-future', id: 'x1', at: 7 },
  ]
}

function memIo(rows) {
  const files = {}
  if (rows) files[join('root', PROJ, 'requests.jsonl')] = rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
  return {
    files,
    existsSync: (f) => f in files,
    readFileSync: (f) => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f] },
    appendFileSync: (f, line) => { files[f] = (files[f] || '') + line },
    mkdirSync: () => {},
  }
}
const env = { HOME: '/nonexistent-t261007-02', SANDBAR_PROJECTS_DIR: 'root', SANDBAR_PANEL_DIR: 'root' }

async function main() {
  // ---- V: the read view (requests.ts), offline, in-memory io ----
  if (!existsSync(REQUESTS)) {
    C.case('requests-module-present', false, 'requests.ts 缺席')
    return C.exit()
  }
  const req = await import(pathToFileURL(REQUESTS).href).catch(() => null)
  if (!req || typeof req.readRequests !== 'function') {
    C.case('readRequests-export', false, 'requests.ts 缺 readRequests 导出')
    return C.exit()
  }
  const view = req.readRequests(memIo(seedRows()), env, PROJ)
  const rows = view.rows || []
  // Five-state truth = the view's `state`; legacy `status` names open 'waiting'.
  const stateOf = (id) => { const r = rows.find((x) => x.id === id); return r ? r.state : null }
  C.case('V1-five-states-visible',
    stateOf('h-open') === 'open' && stateOf('h-answered') === 'answered'
    && stateOf('h-resolved') === 'resolved' && stateOf('h-dismissed') === 'dismissed'
    && stateOf('h-superseded') === 'superseded',
    `states=${JSON.stringify(['h-open', 'h-answered', 'h-resolved', 'h-dismissed', 'h-superseded'].map(stateOf))}`)
  const waiting = rows.filter((r) => r.status === 'waiting').map((r) => r.id)
  C.case('V2-waiting-list-open-only',
    waiting.includes('h-open') && waiting.includes('h-delegated')
    && !waiting.includes('h-answered') && !waiting.includes('h-resolved')
    && !waiting.includes('h-dismissed') && !waiting.includes('h-superseded'),
    `waiting=${JSON.stringify(waiting)}`)
  const openExpired = rows.find((r) => r.id === 'h-open')
  C.case('V2b-expired-open-stays-waiting',
    openExpired && openExpired.state === 'open' && openExpired.status === 'waiting'
    && openExpired.expires_at === 1,
    `expired-open state=${openExpired && openExpired.state} expires_at=${openExpired && openExpired.expires_at}`)
  const del = rows.find((r) => r.id === 'h-delegated') || {}
  const drep = (del.replies || [])[0] || {}
  C.case('V3-two-fields-and-trio-as-separate-view-fields',
    del.source_ticket === '' && del.epic === 'localization'
    && drep.by === 'host' && drep.via === 'integration'
    && drep.anchor === 'give it the stage restart, one night only',
    `fields=${JSON.stringify({ t: del.source_ticket, e: del.epic, by: drep.by, via: drep.via, anchor: drep.anchor })}`)
  C.case('V4-unknown-row-kind-counted-not-dropped',
    typeof view.malformed_rows === 'number' && view.malformed_rows >= 1,
    `malformed_rows=${JSON.stringify(view.malformed_rows)}`)

  // ---- W: the host-only state route through the panel harness ----
  const harness = await loadPanelHarness().catch(() => null)
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'executor-panel harness 缺 startHarness（缝契约见 lib_panel_seam.mjs；TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir('t261007-02-')
  const panelDir = join(iso.dir, 'panel')
  const H = await harness.startHarness({ panelDir, watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  try {
    const ledgerPath = join(panelDir, PROJ, 'requests.jsonl')
    mkdirSync(join(panelDir, PROJ), { recursive: true })
    writeFileSync(ledgerPath, seedRows().map((r) => JSON.stringify(r)).join('\n') + '\n')
    const cookie = { cookie: consoleCookie(H.base) }
    const before = sha(ledgerPath)

    const anon = await jpost(H.base, `/sandbar-executor-panel/api/requests/state?project=${PROJ}`,
      { project: PROJ, id: 'h-open', state: 'dismissed' })
    C.case('W1-credential-less-state-post-refused',
      anon.status === 401 || anon.status === 403,
      `anon status=${anon.status}`)
    C.case('W1b-anon-refusal-wrote-nothing', sha(ledgerPath) === before, 'ledger byte-identical')

    const hostResolved = await jpost(H.base, `/sandbar-executor-panel/api/requests/state?project=${PROJ}`,
      { project: PROJ, id: 'h-open', state: 'resolved' }, cookie)
    C.case('W2-host-cannot-resolve-without-evidence',
      hostResolved.status >= 400 && /resolved|证据/i.test(hostResolved.text),
      `status=${hostResolved.status} text=${hostResolved.text.slice(0, 120)}`)

    const hostSuper = await jpost(H.base, `/sandbar-executor-panel/api/requests/state?project=${PROJ}`,
      { project: PROJ, id: 'h-open', state: 'superseded' }, cookie)
    C.case('W3-host-cannot-set-superseded', hostSuper.status >= 400,
      `status=${hostSuper.status}`)

    const hostDismiss = await jpost(H.base, `/sandbar-executor-panel/api/requests/state?project=${PROJ}`,
      { project: PROJ, id: 'h-open', state: 'dismissed' }, cookie)
    const lines = readFileSync(ledgerPath, 'utf8').trim().split('\n').map((l) => { try { return JSON.parse(l) } catch { return {} } })
    const st = lines.filter((r) => r.type === 'state' && r.state_for === 'h-open' && r.state === 'dismissed')
    C.case('W4-host-dismiss-lands-state-row',
      hostDismiss.status < 300 && st.length === 1,
      `status=${hostDismiss.status} dismissed rows=${st.length}`)
  } finally {
    if (typeof harness.stopHarness === 'function') await harness.stopHarness().catch(() => {})
  }
}

main().then(() => C.exit()).catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 200)); C.exit() })
