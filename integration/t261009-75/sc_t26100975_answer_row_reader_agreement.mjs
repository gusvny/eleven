// sc_t26100975_answer_row_reader_agreement.mjs — t261009-75, grey-box L3,
// offline (real temp ledger file on disk, both real readers over the SAME
// bytes), zero docker/Temporal/browser, never touches 3099.
//
// KI-01M4HPGHVWAKB62TXYV4G7ENEB: one append-only ledger (requests.jsonl), two
// readers that disagreed on what a valid answer row is. On 261010 six
// hand-written answer rows with `at` as a STRING cleared the engine's account
// while the host's panel kept showing them waiting — "the ledger is clear"
// was true in one tool and false in the one the host reads.
//
// Intent (user-perceivable; ticket acceptance items 1-3):
//   A1 KI replay, panel half: the exact defect row (type=answer, answer_for
//      string, at STRING, answer string) does NOT clear a head on the panel's
//      read and is counted as malformed, never silently dropped. (Already the
//      panel's stance; pinned so the fix cannot loosen it.)
//   A2 reader agreement on the defect row: the engine's read face, over the
//      SAME file bytes, reaches the SAME verdict — head NOT answered. (The
//      fix; pre-implement the engine says answered and this is red — TDD red
//      expected, green required at the integration gate/merge.)
//   A3 the engine NAMES the shape-off answer row on a machine-readable face
//      (the steward can see WHY a head is still open without diffing two
//      tools). Pre-implement red expected.
//   A4 mutation guard: a canonical answer row (as the sanctioned writer
//      produces: at number, answer string) DOES clear the head on BOTH
//      readers — guards against over-tightening (a fix that answers nothing).
//   A5 the rest of the shape-off family: answer row missing `answer`, and
//      non-boolean-wrong `at` variants — head stays open on BOTH readers,
//      row counted on the panel face. Same KI family, one sweep, not just the
//      reported sample (incident-regression discipline).
//   A6 bad bytes in the same file (non-JSON line, non-dict JSON line) are
//      counted by both readers, never dropped silently.
//
// Anchors: the two readers' public verdicts over the same on-disk file
// (panel: readRequests rows/malformed_rows; engine: request_thread.head_states
// — the module's declared read view — plus whatever naming face the module
// exposes). No internal call ordering, no private row internals beyond the
// row contract both readers declare.
//
// Three states: engine still lenient = FAIL named (TDD red, expected
// pre-implement); python3 or the engine tree missing = ENV_FAIL exit 2.

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const REQUESTS_TS = join(REPO, 'server/plugins/executor-panel/src/host/requests.ts')
const ENGINE_DIR = join(REPO, 'server/engine')
const KEY = 'agree-proj'
const HEAD = 'req-agree-1'

const headRow = (id = HEAD) => ({
  type: 'request', id, at: 1000, project: KEY, kind: 'decision',
  question: 'restart the stage?', detail: '', default_action: 'no',
  expires_at: null, raised_by: 'session-exec', subject: 'stage restart',
  epic: 'executor-reliability', source_ticket: 't261009-75',
  source_class: 'executor-session',
})
// The 261010 defect, row-shape verbatim: `at` landed as a STRING.
const defectAnswer = (id = HEAD) => ({
  type: 'answer', answer_for: id, at: '1728500000000', answer: 'cleared by hand',
})
const canonicalAnswer = (id = HEAD) => ({
  type: 'answer', answer_for: id, at: 1728500000001, answer: 'cleared by the panel',
})

let LEDGER_FILE = null
function writeLedger(rows) {
  const f = LEDGER_FILE()
  mkdirSync(f.slice(0, f.lastIndexOf('/')), { recursive: true })
  writeFileSync(f, rows.map((r) => typeof r === 'string' ? r : JSON.stringify(r)).join('\n') + '\n', 'utf8')
  return f
}

/** Engine verdict over the same file: head_states (the module's declared read
 *  view) + any module-level naming face for malformed rows. Runs in a fresh
 *  python process so the engine's own import discipline stays untouched. */
function engineRead(file) {
  const script = `
import sys, json
sys.path.insert(0, ${JSON.stringify(ENGINE_DIR)})
import request_thread as rt
rows, malformed = [], 0
for line in open(${JSON.stringify(file)}, encoding='utf-8'):
    line = line.strip()
    if not line:
        continue
    try:
        doc = json.loads(line)
    except ValueError:
        malformed += 1
        continue
    if isinstance(doc, dict):
        rows.append(doc)
    else:
        malformed += 1
states = rt.head_states(rows)
named = ''
for n in dir(rt):
    ln = n.lower()
    if ('report' in ln or 'malformed' in ln) and callable(getattr(rt, n)) and n != 'head_states':
        try:
            named = str(getattr(rt, n)(rows))[:2000]
        except Exception as e:
            named = 'call-failed:' + str(e)[:120]
        break
print(json.dumps({'states': states, 'engine_malformed': malformed, 'named': named}))
`
  const out = execFileSync('python3', ['-B', '-c', script], {
    cwd: REPO, encoding: 'utf8', timeout: 30000,
    env: { PATH: process.env.PATH ?? '/usr/bin:/bin', HOME: '/nonexistent-t261009-75' },
  })
  return JSON.parse(out.trim().split('\n').pop())
}

async function main() {
  if (!existsSync(REQUESTS_TS)) {
    C.case('requests-module-present', false, 'panel requests.ts missing')
    return C.exit()
  }
  const req = await import(pathToFileURL(REQUESTS_TS).href).catch((e) => {
    C.envFail('requests-module-loadable', String(e).slice(0, 200))
    return null
  })
  if (!req || typeof req.readRequests !== 'function' || !req.fsLedgerIo) {
    C.envFail('requests-module-loadable', 'requests.ts must export readRequests and fsLedgerIo')
    return C.exit()
  }
  let python
  try {
    execFileSync('python3', ['--version'], { encoding: 'utf8', timeout: 10000 })
    python = true
  } catch {
    python = false
  }
  if (!python) {
    C.envFail('python3-present', 'python3 not runnable — engine read face cannot be driven')
    return C.exit()
  }
  if (!existsSync(join(ENGINE_DIR, 'request_thread.py'))) {
    C.envFail('engine-module-present', 'server/engine/request_thread.py missing')
    return C.exit()
  }

  const iso = mkdtempSync(join(tmpdir(), 't26100975-agree-'))
  const clean = () => rmSync(iso, { recursive: true, force: true })
  process.on('exit', clean)
  process.on('SIGINT', () => { clean(); process.exit(130) })
  const env = { HOME: iso, SANDBAR_PANEL_DIR: join(iso, 'ledger') }
  const io = req.fsLedgerIo
  LEDGER_FILE = () => req.requestsLedgerFile(KEY, env)
  const panelRead = () => req.readRequests(io, env, KEY)
  const statusOf = (read, id) => { const r = read.rows.find((x) => x.id === id); return r ? r.status : null }

  // ---- A1 KI replay on the panel's own read (same bytes on disk) ----
  writeLedger([headRow(), defectAnswer()])
  let read = panelRead()
  C.case('A1-fixture-head-visible', read.rows.some((r) => r.id === HEAD),
    `rows=${JSON.stringify(read.rows.map((r) => r.id))} file=${LEDGER_FILE()}`)
  C.case('A1-defect-row-panel-still-waiting', statusOf(read, HEAD) === 'waiting',
    `panel status=${statusOf(read, HEAD)} (string-at answer must NOT clear the panel's head)`)
  C.case('A1-defect-row-counted-malformed', read.malformed_rows >= 1,
    `malformed_rows=${read.malformed_rows} (named in the count, never silently dropped)`)

  // ---- A2 reader agreement on the same bytes ----
  let eng
  try {
    eng = engineRead(writeLedger([headRow(), defectAnswer()]))
  } catch (e) {
    C.envFail('engine-read-runs', String(e).slice(0, 240))
    return C.exit()
  }
  C.case('A2-engine-agrees-head-not-answered', eng.states[HEAD] === 'open',
    `engine head_states=${JSON.stringify(eng.states)} (KI-01M4HPGHVWAKB62TXYV4G7ENEB: pre-fix this reads answered — TDD red expected)`)
  C.case('A3-engine-names-defect-row', typeof eng.named === 'string' && eng.named.includes(HEAD),
    `engine naming face=${eng.named ? eng.named.slice(0, 200) : '(no report/malformed face found on request_thread)'}`)

  // ---- A4 mutation guard: the writer's row answers BOTH readers ----
  writeLedger([headRow(), canonicalAnswer()])
  read = panelRead()
  eng = engineRead(LEDGER_FILE())
  C.case('A4-writer-row-clears-panel', statusOf(read, HEAD) === 'answered' && read.malformed_rows === 0,
    `panel status=${statusOf(read, HEAD)} malformed=${read.malformed_rows}`)
  C.case('A4-writer-row-clears-engine', eng.states[HEAD] === 'answered',
    `engine head_states=${JSON.stringify(eng.states)}`)

  // ---- A5 the shape-off family, one sweep ----
  const variants = [
    ['missing-answer', { type: 'answer', answer_for: HEAD, at: 1728500000002 }],
    ['at-boolean', { type: 'answer', answer_for: HEAD, at: true, answer: 'x' }],
    ['answer-non-string', { type: 'answer', answer_for: HEAD, at: 1728500000003, answer: 7 }],
  ]
  for (const [tag, row] of variants) {
    writeLedger([headRow(), row])
    read = panelRead()
    eng = engineRead(LEDGER_FILE())
    C.case(`A5-${tag}-both-readers-keep-open`,
      statusOf(read, HEAD) === 'waiting' && read.malformed_rows >= 1 && eng.states[HEAD] === 'open',
      `panel=${statusOf(read, HEAD)}/malformed=${read.malformed_rows} engine=${eng.states[HEAD]}`)
  }

  // ---- A6 bad bytes counted by both readers ----
  writeLedger([headRow(), '{not json at all', '[1,2,3]', canonicalAnswer()])
  read = panelRead()
  eng = engineRead(LEDGER_FILE())
  C.case('A6-bad-lines-counted-both-readers',
    read.malformed_rows >= 2 && eng.engine_malformed >= 2 && eng.states[HEAD] === 'answered'
    && statusOf(read, HEAD) === 'answered',
    `panel malformed=${read.malformed_rows} engine malformed=${eng.engine_malformed} (counted, never dropped)`)

  C.exit()
}

main()
