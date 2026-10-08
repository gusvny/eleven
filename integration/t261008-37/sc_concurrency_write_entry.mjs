// sc_concurrency_write_entry.mjs — t261008-37 (CL-2b) scenario 1: the engine write entry.
//
// intent: the panel knob's engine half — spawning the REAL entry the panel
// spawns (`client.py concurrency-limit-write '<payload>'`, the exact
// spawnConcurrencyLimitWrite argv) against an isolated projects root lands a
// limit the reader side can prove: the declaration file bytes, the audit FILE
// tail, and the engine read face all agree, and the receipt passes the panel's
// own parser (KI-198 family: writer-says == reader-sees). Every refused write
// leaves BOTH files byte-identical (the panel's 'nothing written' promise),
// the first Save creates the project (where the default 3 lives), and an
// unknown subcommand still yields the panel's named `engine entry absent`
// refusal — no local fallback write (KI-193).
//
// Sub-cases:
//  W1 legal integer save through the real spawn: rc 0, raw-JSON receipt
//     saved:true, declaration bytes exactly {"version":1,"limit":5}, audit
//     tail carries by=host/from/to/ts, receipt.audit_row deep-equals the FILE
//     tail line, read face reports limit 5 (no restart), and the receipt
//     parses through the panel's own parseConcurrencySaveReceipt.
//  W2 the 'unlimited' boundary save lands and reads back (parser limit null,
//     read face unlimited).
//  W3 the refusal truth table through the real spawn: each illegal payload
//     (limit 0/11/"3"/5.5/true/null/missing; by missing/empty; project
//     missing/empty/whitelist-fail; non-dict source; JSON-array payload;
//     malformed-JSON argv; missing argv) exits NON-ZERO with a NAMED
//     saved:false reason that is NOT the engine-entry-absent sentence, and
//     leaves declaration + audit byte-identical (sha256, proven not asserted).
//  W4 first-Save on a project with no directory: the save creates the key
//     dir, the declaration, and the audit row with from=null — the probe-key
//     semantics the absent-entry check depends on.
//  W5 unknown subcommand: the engine output still matches the absent-entry
//     sentence and the panel's parseConcurrencySaveReceiptOrAbsent turns it
//     into the named `engine entry absent` refusal (no silent local write).
//
// intent split (declared, per the registry's no-duplicate-intents rule):
//  the POST/credential/writer-identity chain and the GET read-back belong to
//  t261006-17-concurrency-save-gate; the declaration fail-closed matrix and
//  read-face shape belong to t261004-32-decl-fail-closed; slot-ledger
//  semantics (lowering never interrupts holders, promotion on release)
//  belong to t261004-32-slot-ledger — NONE re-asserted here; this entry owns
//  the engine write entry's spawn contract, the three-face agreement
//  (decl bytes / audit file / read face), the entry-level zero-side-effect
//  proof, and the entry-absent negative.
//
// Three states: node missing = ENV_FAIL exit 2; engine venv missing falls
// back to python3 (lib convention); the entry being absent pre-implement =
// FAIL named (TDD-phase red expected); green at arbitrate/merge.
import { existsSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { makeIsoDir, makeCase } from '../t260929-03/lib_panel_harness.mjs'
import { REPO, enginePython, engineRead, seedProject } from '../t261006-17/lib_t26100617.mjs'
import { parseConcurrencySaveReceipt, parseConcurrencySaveReceiptOrAbsent } from
  '../../server/plugins/executor-panel/src/host/concurrency.ts'

const C = makeCase()
if (!existsSync(process.execPath)) { C.envFail('node-runtime', 'node not on PATH'); process.exit(2) }

const iso = makeIsoDir('t26100837-write-')
const root = iso.dir
process.env.SANDBAR_PROJECTS_DIR = root
const KEY = 'alpha'
seedProject(root, KEY, { version: 1, limit: 2 }, null)
const DIR = join(root, KEY)
const DECL = join(DIR, 'concurrency-limit.json')
const AUDIT = join(DIR, 'concurrency-limit-audit.jsonl')

const sha = (p) => existsSync(p) ? createHash('sha256').update(readFileSync(p)).digest('hex') : '<absent>'
const ABSENT_RE = /未知子命令|unknown (subcommand|op|command)|unrecognized|invalid choice/i

/** The REAL spawn the panel makes (same argv shape as spawnConcurrencyLimitWrite). */
function engineWrite(payloadRaw, sub = 'concurrency-limit-write') {
  const argv = [enginePython(), '-B', join(REPO, 'server', 'engine', 'client.py'), sub]
  if (payloadRaw !== undefined) argv.push(payloadRaw)
  const p = spawnSync(argv[0], argv.slice(1), {
    cwd: REPO, encoding: 'utf8', timeout: 60 * 1000,
    env: { ...process.env, SANDBAR_PROJECTS_DIR: root },
  })
  return { rc: p.status, stdout: p.stdout || '', stderr: p.stderr || '' }
}

const payload = (over) => JSON.stringify({ project: KEY, limit: 5, by: 'host', source: {}, ...over })

function tailRow() {
  const lines = readFileSync(AUDIT, 'utf8').trim().split('\n')
  return JSON.parse(lines[lines.length - 1])
}

// ---------- W1 legal integer save: three faces agree ----------
{
  const r = engineWrite(payload())
  let doc = null
  try { doc = JSON.parse(r.stdout.trim()) } catch { /* judged below */ }
  C.case('W1.rc0-and-raw-saved-receipt', r.rc === 0 && doc && doc.saved === true,
    'rc=' + r.rc + ' stdout=' + r.stdout.slice(0, 200))
  if (doc && doc.saved === true) {
    const declRaw = readFileSync(DECL, 'utf8')
    C.case('W1.decl-bytes', JSON.parse(declRaw).version === 1 && JSON.parse(declRaw).limit === 5,
      'observer: cat ' + DECL + ' -> ' + declRaw.slice(0, 120))
    const row = tailRow()
    C.case('W1.audit-tail-shape', row.by === 'host' && row.from === 2 && row.to === 5 &&
      typeof row.ts === 'number',
      'observer: tail -n 1 ' + AUDIT + ' -> ' + JSON.stringify(row))
    const rowKeysOk = Object.keys(doc.audit_row).every((k) =>
      JSON.stringify(doc.audit_row[k]) === JSON.stringify(row[k]))
    C.case('W1.receipt-row-equals-file-row', rowKeysOk && row.project === KEY,
      'KI-198: every receipt audit_row field must equal the file tail (values, not a parallel truth); the file row may carry the extra project key (contract fields ts/by/from/to)')
    C.case('W1.audit-row-no-value-drift', doc.audit_row.ts === row.ts &&
      doc.audit_row.by === row.by && JSON.stringify(doc.audit_row.from) === JSON.stringify(row.from) &&
      JSON.stringify(doc.audit_row.to) === JSON.stringify(row.to),
      'writer-says == reader-sees on all four contract fields')
    const read = engineRead(root, KEY)
    let face = null
    try { face = JSON.parse(read.stdout.trim()) } catch { /* judged below */ }
    C.case('W1.read-face-reflects-new-limit', read.rc === 0 && face && face.result &&
      face.result.limit === 5 && face.result.unlimited === false,
      'no restart, no cache: rc=' + read.rc + ' ' + read.stdout.slice(0, 200))
    const pr = parseConcurrencySaveReceipt(r.stdout)
    C.case('W1.panel-parser-accepts', pr.saved === true && pr.audit_row && pr.audit_row.by === 'host',
      'the panel side of the contract accepts this receipt: ' + JSON.stringify(pr).slice(0, 200))
  } else {
    C.case('W1.chain-skipped-receipt-missing', false, 'receipt absent — chain not asserted')
  }
}

// ---------- W2 unlimited boundary save ----------
{
  const r = engineWrite(payload({ limit: 'unlimited' }))
  let doc = null
  try { doc = JSON.parse(r.stdout.trim()) } catch { /* judged below */ }
  C.case('W2.unlimited-lands', r.rc === 0 && doc && doc.saved === true,
    'rc=' + r.rc + ' ' + r.stdout.slice(0, 160))
  if (doc && doc.saved === true) {
    const d = JSON.parse(readFileSync(DECL, 'utf8'))
    C.case('W2.decl-unlimited', d.limit === 'unlimited',
      'observer: ' + readFileSync(DECL, 'utf8').slice(0, 120))
    C.case('W2.parser-limit-null', parseConcurrencySaveReceipt(r.stdout).limit === null,
      'the panel reads unlimited back as null, never a number')
    const read = engineRead(root, KEY)
    let face = null
    try { face = JSON.parse(read.stdout.trim()) } catch { /* judged below */ }
    C.case('W2.read-face-unlimited', read.rc === 0 && face && face.result &&
      face.result.unlimited === true, read.stdout.slice(0, 200))
    const row = tailRow()
    C.case('W2.audit-to-unlimited', row.to === 'unlimited' || row.to === null, JSON.stringify(row))
  } else {
    C.case('W2.chain-skipped-receipt-missing', false, 'unlimited receipt absent — chain not asserted')
  }
}

// ---------- W3 refusal truth table: named, non-zero, byte-identical ----------
{
  const badCases = [
    ['limit-zero', payload({ limit: 0 })],
    ['limit-eleven', payload({ limit: 11 })],
    ['limit-string', payload({ limit: '3' })],
    ['limit-float', payload({ limit: 5.5 })],
    ['limit-bool', payload({ limit: true })],
    ['limit-null', payload({ limit: null })],
    ['limit-missing', JSON.stringify({ project: KEY, by: 'host', source: {} })],
    ['by-missing', JSON.stringify({ project: KEY, limit: 5, source: {} })],
    ['by-empty', payload({ limit: 5, by: '  ' })],
    ['project-missing', JSON.stringify({ limit: 5, by: 'host', source: {} })],
    ['project-empty', payload({ project: '', limit: 5 })],
    ['project-whitelist-fail', payload({ project: 'bad key!', limit: 5 })],
    ['source-not-dict', JSON.stringify({ project: KEY, limit: 5, by: 'host', source: 'x' })],
    ['payload-array', JSON.stringify([KEY, 5])],
    ['argv-malformed-json', '{project:'],
    ['argv-missing', undefined],
  ]
  for (const [name, raw] of badCases) {
    const before = [sha(DECL), sha(AUDIT)]
    const r = engineWrite(raw)
    let doc = null
    try { doc = JSON.parse(r.stdout.trim()) } catch { /* judged below */ }
    const refused = r.rc !== 0 && doc && doc.saved === false &&
      typeof doc.reason === 'string' && doc.reason.length > 0
    const after = [sha(DECL), sha(AUDIT)]
    C.case('W3.' + name + '-named-nonzero', refused,
      'rc=' + r.rc + ' reason=' + String(doc && doc.reason).slice(0, 160))
    C.case('W3.' + name + '-both-files-byte-identical',
      before[0] === after[0] && before[1] === after[1],
      'sha256 decl ' + before[0].slice(0, 12) + '->' + after[0].slice(0, 12) +
      ' audit ' + before[1].slice(0, 12) + '->' + after[1].slice(0, 12))
    C.case('W3.' + name + '-not-entry-absent', !(doc && doc.reason && ABSENT_RE.test(doc.reason)),
      'a validation refusal must name the failed check, not the entry-absent sentence')
  }
}

// ---------- W4 first Save creates the project ----------
{
  const KEY2 = 'bravo-fresh'
  const before = sha(join(root, KEY2, 'concurrency-limit.json'))
  const r = engineWrite(JSON.stringify({ project: KEY2, limit: 3, by: 'host', source: {} }))
  let doc = null
  try { doc = JSON.parse(r.stdout.trim()) } catch { /* judged below */ }
  C.case('W4.first-save-lands', r.rc === 0 && doc && doc.saved === true,
    'rc=' + r.rc + ' ' + r.stdout.slice(0, 160))
  if (doc && doc.saved === true) {
    const d = JSON.parse(readFileSync(join(root, KEY2, 'concurrency-limit.json'), 'utf8'))
    C.case('W4.decl-created', d.version === 1 && d.limit === 3, JSON.stringify(d))
    const row = JSON.parse(readFileSync(join(root, KEY2, 'concurrency-limit-audit.jsonl'),
      'utf8').trim().split('\n').pop())
    C.case('W4.audit-from-null', row.from === null && row.to === 3 && row.by === 'host',
      JSON.stringify(row))
  } else {
    C.case('W4.chain-skipped-receipt-missing', false,
      'first-save receipt absent (sha before=' + before.slice(0, 12) + ') — chain not asserted')
  }
}

// ---------- W5 unknown subcommand: entry-absent refusal preserved ----------
{
  const before = sha(DECL)
  const r = engineWrite(payload(), 'bogus-op')
  const out = r.stdout + r.stderr
  C.case('W5.absent-sentence-present', ABSENT_RE.test(out),
    'rc=' + r.rc + ' out=' + out.slice(0, 200))
  const parsed = parseConcurrencySaveReceiptOrAbsent(out.trim() || '{"saved":false,"reason":"empty"}')
  C.case('W5.panel-names-entry-absent',
    parsed.saved === false && /engine entry absent/i.test(parsed.reason),
    JSON.stringify(parsed).slice(0, 220))
  C.case('W5.no-local-write', sha(DECL) === before, 'no fallback write, bytes unchanged')
}

C.exit()
