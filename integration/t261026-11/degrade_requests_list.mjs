/**
 * degrade_requests_list.mjs — the degrade matrix on the requests ledger
 * read face (t261026-11). Face under judgement: readRequests, the reader the
 * requests list renders from.
 *
 * The real payload is produced by the REAL writer: appendRequest (the ledger
 * producer) writes a real ledger through the face's own LedgerIo seam, and
 * the matrix feeds that ledger's bytes as the fifth shape — plus missing /
 * unreadable / empty / garbage ledgers as the four broken shapes. No
 * hand-written view model.
 *
 * Registered in run_scenarios.py only while green (green-before-register).
 * Run: node integration/t261026-11/degrade_requests_list.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, rmSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { runDegradeMatrix } from '../lib_degrade_matrix.mjs'

const REQ = new URL('../../server/plugins/executor-panel/src/host/requests.ts', import.meta.url).pathname
const req = await import(REQ)

const dir = mkdtempSync(join(tmpdir(), 't11-req-'))
process.on('exit', () => { try { rmSync(dir, { recursive: true, force: true }) } catch { /* best effort */ } })

const key = 't261026-11'
const env = { SANDBAR_PANEL_DIR: dir }
const LEDGER = req.requestsLedgerFile(key, env) // <dir>/<key>/requests.jsonl
mkdirSync(join(dir, key), { recursive: true })

// The face's own LedgerIo seam over that one file.
const io = {
  existsSync: (f) => f === LEDGER,
  readFileSync: (f) => readFileSync(f, 'utf8'),
  appendFileSync: (f, line) => writeFileSync(f, line, { flag: 'a' }),
  mkdirSync: (d, o) => mkdirSync(d, o),
}

// REAL payload: the producer writes its own rows.
const wrote = req.appendRequest(io, env, key,
  { kind: 'decision', question: 'merge the funnel into main?', raised_by: 'integration' },
  Date.parse('2026-10-26T09:00:00Z'))
if (!wrote?.ok) { console.log(`ENV_FAIL: the producer refused its own write: ${wrote?.error}`); process.exit(2) }
const REAL_TEXT = readFileSync(LEDGER, 'utf8')

const r = runDegradeMatrix({
  face: 'requests-list',
  // Faithful adapter: the shape IS the ledger file's bytes, exactly what the
  // reader's io hands it. UNREADABLE maps to the reader's own read-throw
  // branch; missing maps to existsSync=false — the same seams the runtime
  // hits. No reinterpreting of the reader's answer.
  call: (payload) => {
    if (payload === 'UNREADABLE') {
      const throwing = { ...io, readFileSync: () => { throw new Error('EACCES: ledger unreadable') } }
      return req.readRequests(throwing, env, key)
    }
    if (payload === null || payload === undefined) {
      const absent = { ...io, existsSync: () => false }
      return req.readRequests(absent, env, key)
    }
    const bytes = typeof payload === 'string' ? payload : JSON.stringify(payload)
    writeFileSync(LEDGER, bytes)
    return req.readRequests(io, env, key)
  },
  real: REAL_TEXT,
  expect: (out) => ({
    row_read: Array.isArray(out?.rows) && out.rows.length >= 1,
    question_wording: String(out?.rows?.[0]?.question ?? '').includes('merge the funnel'),
  }),
})

process.exit(r.ok ? 0 : 1)
