// sc_concurrency_save_gate.mjs — t261006-17 (CL-2) scenario 2: the Save face.
//
// intent: saving the limit goes THROUGH the engine entry (never a local
// declaration write by the panel), lands in the engine audit with who=host and
// when, and the read face reflects the new limit afterwards (KI-198 family:
// "writer says saved, reader unchanged" must not come back here). The write
// endpoint sits behind the console credential gate (KI-193) with the writer
// identity fixed to host — a claimed identity in the body is never authority.
//
// Sub-cases:
//  S1 no credential on POST → 401, before any parse or disk touch (KI-193).
//  S2 credential + a body by:'someone-else' → named writer-mismatch refusal
//     (by_claimed surfaced), nothing written.
//  S3 CL-2b entry ABSENT (system state, probed, never guessed) → the POST
//     returns the named `engine entry absent` refusal and the declaration file
//     on disk is byte-identical (no fallback local write, KI-193 wording).
//  S4 CL-2b entry PRESENT (same probe, N/A-eligible system-state sub-case) →
//     the full chain: POST limit 5 → reader = `tail -n 1
//     <abs-projects-root>/<key>/concurrency-limit-audit.jsonl` carries
//     by=host/from/to/ts; declaration file reads {"version":1,"limit":5};
//     GET face then reports limit 5 (post-save reload, KI-198 read-back);
//     unlimited boundary save (limit:'unlimited') also lands and reads back.
//
// intent split: route/ledger read faces = sc_concurrency_face_ledger_route;
// Overview DOM = sc_concurrency_overview_ui; grants-path fault table (timeout,
// malformed receipt, non-zero exit shapes) is pinned at L1 by the developer
// battery on the same spawn helper; the engine-side set_limit truth table
// belongs to CL-2b's own ticket.
//
// Three states: node missing = ENV_FAIL exit 2; panel harness/route not landed
// = FAIL naming the missing face (TDD-phase red expected); S4 sub-cases are
// N/A only when the probed engine state says CL-2b is absent (N/A is a
// system-state verdict, never an environment one); green at gate.
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t260929-03/lib_panel_harness.mjs'
import { REPO, enginePython, engineWriteEntryPresent, seedProject } from './lib_t26100617.mjs'

const C = makeCase()
if (!existsSync(process.execPath)) { C.envFail('node-runtime', 'node not on PATH'); process.exit(2) }

let mod
try { mod = await loadPanelHarness() } catch (e) { C.case('harness-load', false, String(e.message || e)); C.exit() }
if (!mod || typeof mod.startHarness !== 'function') {
  C.case('harness-present', false,
    'panel test seam absent: server/plugins/executor-panel/harness.mjs (TDD-phase red expected)')
  C.exit()
}

const iso = makeIsoDir('t26100617-save-')
const root = iso.dir
process.env.SANDBAR_PROJECTS_DIR = root
const KEY = 'alpha'
seedProject(root, KEY, { version: 1, limit: 2 },
  { version: 1, limit: 2, unlimited: false, holders: [], queue: [] })
const DECL = join(root, KEY, 'concurrency-limit.json')
const AUDIT = join(root, KEY, 'concurrency-limit-audit.jsonl')
const declBefore = readFileSync(DECL, 'utf8')

let H
try {
  H = await mod.startHarness({ port: 0, panelDir: join(root, '_panel'), watchdogDir: join(root, '_panel') })
} catch (e) { C.case('harness-boot', false, String(e).slice(0, 300)); C.exit() }

// Same-shaped cookie the console browser carries (t261004-18 fixture face).
const cookie = 'dsh-auth-' +
  Buffer.from(createHash('sha256').update(new URL(H.base).host).digest()).toString('base64url') +
  '=v1.AAAA.BBBB'

async function post(payload, withCookie = true) {
  const key = payload.project || ''
  const r = await fetch(H.base + '/sandbar-executor-panel/api/concurrency?project=' +
    encodeURIComponent(key), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(withCookie ? { cookie } : {}),
    },
    body: JSON.stringify(payload),
  })
  let body = null
  try { body = await r.json() } catch { /* caller judges */ }
  return { status: r.status, body }
}

// The face refusal carries the engine text either as `reason` or `error`.
const refusalOf = (body) => String((body && (body.reason ?? body.error)) || JSON.stringify(body || {}))

// ---------- S1 credential gate ----------
{
  const { status } = await post({ project: KEY, limit: 5 }, false)
  C.case('S1.401-without-credential', status === 401, 'status=' + status)
  C.case('S1.decl-untouched-before-auth', readFileSync(DECL, 'utf8') === declBefore,
    'a 401 must happen before any parse or disk touch')
}

// ---------- S2 writer identity ----------
{
  const { status, body } = await post({ project: KEY, limit: 5, by: 'someone-else' })
  const reason = refusalOf(body)
  C.case('S2.writer-mismatch-refused', status !== 200 || (body && body.ok === false),
    'a body by-claim is never authority: ' + reason.slice(0, 250))
  // System-state conditional: while CL-2b is absent the entry-absent refusal
  // may legitimately fire before identity is judged; once the entry exists the
  // refusal must NAME the claimed identity face.
  C.case('S2.claim-surfaced', /engine entry absent/i.test(reason) ||
    /writer_mismatch|by_claimed/.test(reason),
    'refusal names the claimed identity face (or the CL-2b-absent state): ' + reason.slice(0, 250))
  C.case('S2.decl-untouched', readFileSync(DECL, 'utf8') === declBefore, 'nothing written on mismatch')
}

// ---------- S3 / S4 CL-2b system-state split ----------
const probe = engineWriteEntryPresent(root)
console.log('  [probe] CL-2b engine write entry present=' + probe.present +
  ' rc=' + probe.rc + ' :: ' + probe.probe.replace(/\n/g, ' | ').slice(0, 200))

{
  const { status, body } = await post({ project: KEY, limit: 5 })
  const reason = refusalOf(body)
  if (!probe.present) {
    C.case('S3.named-refusal-entry-absent', body && body.ok === false &&
      /engine entry absent/i.test(reason),
      'until CL-2b lands the POST refuses by name: ' + reason.slice(0, 250))
    C.case('S3.decl-byte-identical', readFileSync(DECL, 'utf8') === declBefore,
      'no silent local declaration write — bytes unchanged')
    C.case('S3.not-crash', status < 500, 'a named refusal is contract-shaped, status=' + status)
  } else {
    C.case('S4.save-accepted', status === 200 && body && body.ok !== false && body.saved !== false,
      'save through the engine entry: ' + JSON.stringify(body).slice(0, 250))
    // Reader-side: the audit line is read from the audit FILE, not from the
    // POST receipt (writer stdout is not evidence).
    let last = ''
    try { last = readFileSync(AUDIT, 'utf8').trim().split('\n').pop() } catch { /* absent */ }
    let row = {}
    try { row = JSON.parse(last || '{}') } catch { /* torn line = red below */ }
    C.case('S4.audit-row-reader-side', row.by === 'host' && row.from === 2 && row.to === 5 && !!row.ts,
      'observer: tail -n 1 ' + AUDIT + ' -> ' + last.slice(0, 200))
    let declAfter = {}
    try { declAfter = JSON.parse(readFileSync(DECL, 'utf8')) } catch { /* red below */ }
    C.case('S4.decl-on-disk', declAfter.version === 1 && declAfter.limit === 5,
      'observer: cat ' + DECL + ' -> ' + readFileSync(DECL, 'utf8').slice(0, 120))
    const gr = await fetch(H.base + '/sandbar-executor-panel/api/concurrency?project=' + KEY)
    const gb = await gr.json().catch(() => null)
    C.case('S4.face-reflects-new-limit', gb && gb.limit === 5,
      'KI-198 family: the read face must reflect the saved limit, got ' + JSON.stringify(gb && gb.limit))

    // Unlimited boundary save (knob arithmetic lands on the word, not 11/0).
    const u = await post({ project: KEY, limit: 'unlimited' })
    C.case('S4.unlimited-save', u.status === 200 && u.body && u.body.ok !== false,
      JSON.stringify(u.body).slice(0, 200))
    if (u.body && u.body.ok !== false) {
      const lastU = readFileSync(AUDIT, 'utf8').trim().split('\n').pop()
      C.case('S4.unlimited-audit-to', /"to":\s*(null|"unlimited")/.test(lastU),
        'observer: tail -n 1 ' + AUDIT + ' -> ' + lastU.slice(0, 200))
    }
  }
}

await H.close()
iso.clean()
C.exit()
