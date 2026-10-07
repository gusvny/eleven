// sc_request_thread_panel_view.mjs — t261007-02: the panel reads and shows the
// thread ledger's new fields and new states over the production API surface.
//
// Grey-box L3, offline seconds, zero docker/Temporal, never touches 3099/7233.
// Drives the production plugin harness (startPluginHarness: the real node.ts
// apply + createApi core, same shape as the credential gate in production)
// against a seeded thread ledger (rows written in the engine request_thread.py
// row shapes — the same rows the engine CLI lands).
//
// Faces:
//   P1 the five states round-trip: a seeded ledger with open / answered /
//      resolved / dismissed / superseded heads reads back with the right
//      `state` per head, and the waiting list keeps its meaning — open items
//      only (ticket item 10).
//   P2 the two ownership fields ride the read face: source ticket (fact) and
//      owning epic (judgement), with `none` + its reason intact; legacy rows
//      without the fields read back without becoming malformed.
//   P3 links ride the read face: a supersedes link (with from) and a duplicates
//      link from a re-file (WITHOUT from — the denied filing never became a row;
//      the panel must not resolve a dangling id) both surface on the target head.
//   P4 the delegated answer trio (by / via / anchor) arrives as separate fields
//      on the reply view — the columns the panel shows.
//   P5 the host state-change face (POST /api/requests/state) dismisses an open
//      item with a credential, refuses without one (401, ledger untouched),
//      refuses a non-dismissed state by name, and refuses a second dismissal of
//      a terminal head (409, never rewritten).
//   P6 the answer route also lands the answered state row (the write path never
//      skips the state row) and refuses to answer a dismissed head.
//
// intent 分工：引擎状态机/拒收/重复改投本体归
// sc_request_thread_states.py；本条只锁「面板读出与宿主状态面」。
// harness 缺场 = FAIL 点名（TDD 期红属预期，arbitrate/merge 期必须绿）；
// node 缺席 = ENV_FAIL exit 2；闸内无 SKIP。
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PROJ = 'threadalpha'

const FAILS = []
function check(name, cond, detail = '') {
  const tag = cond ? 'PASS' : 'FAIL'
  console.log(`[${tag}] ${name}` + (detail && !cond ? ` — ${detail}` : ''))
  if (!cond) FAILS.push(name)
}

const { startPluginHarness } = await import(HARNESS_PATH)

const panelDir = mkdtempSync(join(tmpdir(), 'threadpanel-'))
const ledgerFile = join(panelDir, PROJ, 'requests.jsonl')
mkdirSync(join(panelDir, PROJ), { recursive: true })

const head = (id, at, extra = {}) => JSON.stringify({ type: 'request', id, at,
  project: PROJ, kind: 'decision', question: 'q ' + id, detail: '',
  default_action: 'x', expires_at: null, raised_by: 'sess-exec-1', ...extra })
const rows = [
  head('req-open', 1000),
  head('req-ans', 1001),
  head('req-res', 1002, { subject: 'fam-a', epic: 'project-executor', source_ticket: 't261007-02', source_class: 'executor-session' }),
  head('req-dis', 1003),
  head('req-sup', 1004, { subject: 'fam-b', epic: 'none', epic_reason: 'no epic owns cross-project tooling yet' }),
  head('req-old', 1005), // legacy row: no thread fields — must not turn malformed
  JSON.stringify({ type: 'state', id: 'st-1', state_for: 'req-ans', state: 'answered', at: 2000, by: 'host' }),
  JSON.stringify({ type: 'state', id: 'st-2', state_for: 'req-res', state: 'resolved', at: 2001, by: 'sess-exec-1', evidence: 't261007-02' }),
  JSON.stringify({ type: 'state', id: 'st-3', state_for: 'req-dis', state: 'dismissed', at: 2002, by: 'host' }),
  JSON.stringify({ type: 'link', id: 'lnk-1', kind: 'supersedes', from: 'req-open', to: 'req-sup', at: 2003, by: 'sess-exec-1' }),
  JSON.stringify({ type: 'state', id: 'st-4', state_for: 'req-sup', state: 'superseded', at: 2004, by: 'sess-exec-1', note: 'set automatically by the supersedes link' }),
  JSON.stringify({ type: 'link', id: 'lnk-2', kind: 'duplicates', to: 'req-res', at: 2005, by: 'sess-exec-2', dup_subject: 'fam-a', dup_epic: 'project-executor', dup_source_ticket: 't261007-02' }),
  JSON.stringify({ type: 'reply', id: 'rpl-1', reply_for: 'req-res', at: 2006, text: 'host chose plan A', by: 'sess-exec-1', intent: 'answer', via: 'integration-agent', anchor: 'go with A' }),
]
writeFileSync(ledgerFile, rows.join('\n') + '\n', 'utf8')
const beforeBytes = readFileSync(ledgerFile, 'utf8')

const harness = await startPluginHarness({ panelDir })
// KI-193 test credential: same cookieName algorithm as defaultAuthFace (shape-only
// value; the repo does not verify HMAC) bound to the harness host.
const { createHash } = await import('node:crypto')
const hostPart = harness.base.replace('http://', '')
const cookieName = 'dsh-auth-' + createHash('sha256').update(hostPart).digest('base64url')
const cookie = cookieName + '=v1.cGFuZWwtdGVzdA.c2lnbmF0dXJlLXNoYXBlLW9ubHk'
const get = async (p) => {
  const r = await fetch(harness.base + p)
  return { status: r.status, json: await r.json() }
}
const post = async (p, body, withCredential = true) => {
  const r = await fetch(harness.base + p, {
    method: 'POST',
    headers: { 'content-type': 'application/json',
      ...(withCredential ? { cookie } : {}) },
    body: JSON.stringify(body),
  })
  return { status: r.status, json: await r.json() }
}

try {
  const read = await get(`/sandbar-executor-panel/api/requests?project=${PROJ}`)
  const byId = new Map((read.json.rows || []).map(r => [r.id, r]))

  // P1 five states; waiting list = open only
  check('P1 states round-trip per head',
    byId.get('req-open')?.state === 'open' && byId.get('req-ans')?.status === 'answered'
    && byId.get('req-res')?.state === 'resolved' && byId.get('req-dis')?.state === 'dismissed'
    && byId.get('req-sup')?.state === 'superseded',
    JSON.stringify([...byId].map(([k, v]) => [k, v.state])))
  const waitingRows = (read.json.rows || []).filter(r => r.status === 'waiting' || r.state === 'open')
  check('P1b the waiting list keeps its meaning: open items only',
    waitingRows.length === 2 && waitingRows.map(r => r.id).sort().join(',') === 'req-old,req-open',
    'waiting=' + waitingRows.map(r => r.id).join(','))

  // P2 ownership fields; legacy row tolerated
  const res = byId.get('req-res')
  check('P2a source ticket and owning epic ride the read face',
    res?.source_ticket === 't261007-02' && res?.epic === 'project-executor')
  const sup = byId.get('req-sup')
  check('P2b epic none carries its reason',
    sup?.epic === 'none' && sup?.epic_reason === 'no epic owns cross-project tooling yet')
  const legacy = byId.get('req-old')
  check('P2c a legacy row without the fields reads back unharmed (not malformed)',
    legacy && legacy.epic === undefined && legacy.source_ticket === undefined
      && read.json.malformed_rows === 0)

  // P3 links: supersedes with from, duplicates re-file without from (no dangling id)
  const supLinks = sup?.links || []
  const dupLinks = res?.links || []
  check('P3a the supersedes link surfaces on the target head (with from)',
    supLinks.length === 1 && supLinks[0].from === 'req-open' && supLinks[0].kind === 'supersedes')
  check('P3b the re-file duplicates link surfaces without from (no dangling id resolved)',
    dupLinks.length === 1 && dupLinks[0].from === undefined
      && dupLinks[0].dup_subject === 'fam-a' && read.json.malformed_rows === 0)

  // P4 delegated trio as separate fields
  const rp = (res?.replies || [])[0] || {}
  check('P4 by/via/anchor arrive as separate fields on the reply view',
    rp.by === 'sess-exec-1' && rp.via === 'integration-agent' && rp.anchor === 'go with A')

  // P5 host state face
  const noCred = await post('/sandbar-executor-panel/api/requests/state',
    { project: PROJ, id: 'req-open', state: 'dismissed' }, false)
  check('P5a a credential-less state write is refused 401 (KI-193 gate)',
    noCred.status === 401)
  check('P5b a refused write leaves the ledger byte-identical',
    readFileSync(ledgerFile, 'utf8') === beforeBytes)
  const badState = await post('/sandbar-executor-panel/api/requests/state',
    { project: PROJ, id: 'req-open', state: 'resolved' })
  check('P5c a non-dismissed state is refused by name (fixed setters)',
    badState.status === 400 && /dismissed/.test(badState.json.error || ''))
  const dismiss = await post('/sandbar-executor-panel/api/requests/state',
    { project: PROJ, id: 'req-open', state: 'dismissed' })
  check('P5d the host dismisses an open item (the void-question way out)',
    dismiss.status === 200 && dismiss.json.ok === true)
  const again = await post('/sandbar-executor-panel/api/requests/state',
    { project: PROJ, id: 'req-open', state: 'dismissed' })
  check('P5e a second dismissal is refused 409 (a row is never rewritten)',
    again.status === 409)
  const afterDismiss = await get(`/sandbar-executor-panel/api/requests?project=${PROJ}`)
  check('P5f the dismissed head left the waiting set',
    (afterDismiss.json.rows || []).every(r => r.id !== 'req-open' || r.state === 'dismissed'))

  // P6 answer face: state row lands; answering a dismissed head is refused
  const seedAns = join(panelDir, PROJ, 'second.jsonl')
  void seedAns
  const answer = await post('/sandbar-executor-panel/api/requests/answer',
    { project: PROJ, id: 'req-old', answer: 'do the thing' })
  const lines = readFileSync(ledgerFile, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l))
  const lastTwo = lines.slice(-2)
  check('P6a the answer lands with an answered state row right after it (never skips the state row)',
    answer.status === 200 && lastTwo[0].type === 'answer' && lastTwo[1].type === 'state'
      && lastTwo[1].state === 'answered')
  const ansDismissed = await post('/sandbar-executor-panel/api/requests/answer',
    { project: PROJ, id: 'req-dis', answer: 'too late' })
  // t261007-01 §9 (merged from main, host ruling): answer-after-dismiss WINS --
  // a dismiss is not a decision; the host may change their mind. The dismissed
  // head takes the answer and leaves dismissed for answered.
  const afterAnswerDismissed = await get('/sandbar-executor-panel/api/requests?project=' + PROJ)
  const reqDis = (afterAnswerDismissed.json.rows || []).find(r => r.id === 'req-dis')
  check('P6b answering a dismissed head wins (a dismiss is not a decision; head flips to answered)',
    ansDismissed.status === 200 && reqDis && reqDis.state === 'answered',
    'status=' + ansDismissed.status + ' state=' + (reqDis && reqDis.state))
} finally {
  await harness.close()
  // reclaim the fixture tree (L8 tmp-dir hygiene: every mkdtemp gets a verb)
  rmSync(panelDir, { recursive: true, force: true })
}

console.log()
if (FAILS.length) {
  console.log(`RESULT: FAIL (${FAILS.length}): ` + FAILS.join('; '))
  process.exit(1)
}
console.log('RESULT: PASS — panel thread view faces green (states, fields, links, delegated trio, host state face)')
