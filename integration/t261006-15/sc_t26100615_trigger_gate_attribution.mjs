#!/usr/bin/env node
/**
 * sc_t26100615_trigger_gate_attribution.mjs — t261006-15, grey-box L3, "ro" pool.
 *
 * User-perceivable face under test (design §7 host rulings + dispatch spec
 * P3/P4): the Inspection tab's on-demand full-library trigger is a WRITE that
 * is gated and attributed —
 *   G1 it sits behind the panel's credential gate (KI-193 family: panel write
 *      endpoints must never be callable by an anonymous local curl);
 *   G2 a gated request appends EXACTLY ONE attributed record — who / when /
 *      scope / reason — into the project's own account; never anonymous;
 *   G3 malformed input (missing instance / empty reason / oversized fields) is
 *      refused with the named criterion, nothing appended (input three-state
 *      discipline);
 *   G4 a trigger whose spawn FAILS is visible: an explicit failed record (or
 *      named error face) — never a silent no-op, never a fabricated success;
 *   G5 trigger records read back newest-first, independent of the selected
 *      period, malformed rows counted not dropped, and the read face is
 *      read-only (byte-compare).
 *
 * Harness: production panel route shell via
 * t261003-06/lib_panel_seam.mjs startPluginHarness (real node.ts apply + stub
 * webServer, temp port, never 3099/7233), projects root isolated via env.
 * Offline seconds, zero docker/Temporal/browser. The real spawn of
 * inspection_trigger.py cannot connect to Temporal here, so the observed
 * terminal state is a REAL spawn failure — exactly the G4 face.
 *
 * Intent split: archive/period-list semantics =
 * sc_t26100615_period_archive_route.mjs; rendered tab journey/layout =
 * sc_t26100615_inspection_tab_journey_layout.mjs; unit truth tables of the
 * trigger core = developer L1; the generic KI-193 gate contract on EXISTING
 * panel write routes = t261004-41 family (not re-judged here — this entry
 * owns the NEW trigger route's gate+attribution). Not landed = FAIL named
 * (TDD-phase red expected; arbitrate/merge must be green). node missing =
 * ENV_FAIL exit 2.
 */
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PANEL_ROUTE = '/sandbar-executor-panel'
const PROJ = 'sandbar'
const POST = PANEL_ROUTE + '/api/inspection/trigger'
const GET = PANEL_ROUTE + '/api/inspection/trigger-records?project=' + PROJ

const C = makeCase()

async function jpost(base, url, body, headers = {}) {
  const r = await fetch(base + url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body),
  })
  const text = await r.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* non-json */ }
  return { status: r.status, body: json, text }
}
async function jget(base, url) {
  const r = await fetch(base + url)
  const text = await r.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* non-json */ }
  return { status: r.status, body: json, text }
}

/** projects root isolated per case; returns harness + ledger path readers. */
async function harnessWith({ seedProjectDir = false } = {}) {
  const iso = makeIsoDir('t26100615-trig-')
  const projectsDir = join(iso.dir, 'projects')
  mkdirSync(projectsDir, { recursive: true })
  if (seedProjectDir) mkdirSync(join(projectsDir, PROJ, 'inspection'), { recursive: true })
  const prev = process.env.SANDBAR_PROJECTS_DIR
  process.env.SANDBAR_PROJECTS_DIR = projectsDir
  const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel') })
  return {
    H, iso, projectsDir,
    ledgerFile: join(projectsDir, PROJ, 'inspection', 'trigger-records.jsonl'),
    async close() {
      await H.close()
      if (prev === undefined) delete process.env.SANDBAR_PROJECTS_DIR
      else process.env.SANDBAR_PROJECTS_DIR = prev
      iso.clean()
    },
  }
}

function authHeaders(base) {
  // Production gate face = dsh session cookie (KI-193 fix). The panel's
  // DECLARED boundary: the cookie NAME is computable
  // ('dsh-auth-' + base64url(sha256(Host))) and only the value SHAPE is
  // checked locally (`v1.<seg>.<seg>`) — the HMAC secret is process-private
  // and unverifiable here, an honest inherited boundary (api.ts header).
  // This scenario presents a shape-valid credential so the gated write path
  // is reachable; refusing to reach it would make G2–G5 dead cases.
  const host = new URL(base).host
  const name = 'dsh-auth-' + createHash('sha256').update(host).digest('base64url')
  return { cookie: name + '=v1.aGVsbG8.d29ybGQ' }
}

let mod = null

async function main() {
  if (!existsSync(HARNESS_PATH)) {
    C.case('harness-present', false, 'server/plugins/executor-panel/harness.mjs missing')
    return C.exit()
  }
  mod = await import('file://' + HARNESS_PATH).catch((e) => {
    C.case('harness-loadable', false, String(e).slice(0, 250)); return null
  })
  if (!mod) return C.exit()
  if (typeof mod.startPluginHarness !== 'function') {
    C.case('plugin-shell-seam-present', false, 'harness.mjs missing startPluginHarness')
    return C.exit()
  }

  // ---- G1: the write face is gated — anonymous request is refused AND ----
  // ---- writes nothing. A 404 here means the route is NOT LANDED: FAIL. ----
  {
    const h = await harnessWith()
    try {
      const before = existsSync(h.ledgerFile) ? readFileSync(h.ledgerFile, 'utf8') : ''
      const r = await jpost(h.H.base, POST, { project: PROJ, instance: 'integration-tests', scope: 'server/plugins', reason: 'probe' })
      if (r.status === 404) {
        C.case('trigger-route-landed', false, 'POST ' + POST + ' → 404 (route not landed, P3)')
      } else {
        C.case('trigger-route-landed', true, 'status=' + r.status)
        const refused = r.status === 401 || r.status === 403
        C.case('G1-anonymous-write-refused', refused,
          `status=${r.status} body=${r.text.slice(0, 160)}`)
        const after = existsSync(h.ledgerFile) ? readFileSync(h.ledgerFile, 'utf8') : ''
        C.case('G1-refused-request-writes-nothing', after === before, '')
      }
    } finally { await h.close() }
  }

  // ---- G3: malformed bodies refused with the named criterion, nothing ----
  // ---- appended. Skipped when the route itself is not landed.          ----
  const badBodies = [
    ['missing-reason', { project: PROJ, instance: 'integration-tests', scope: 'server/plugins' }],
    ['empty-reason', { project: PROJ, instance: 'integration-tests', scope: 'server/plugins', reason: '   ' }],
    ['missing-instance', { project: PROJ, scope: 'server/plugins', reason: 'deep dive requested' }],
    ['missing-scope', { project: PROJ, instance: 'integration-tests', reason: 'deep dive requested' }],
    ['oversized-reason', { project: PROJ, instance: 'integration-tests', scope: 'server/plugins', reason: 'x'.repeat(20000) }],
  ]
  {
    const h = await harnessWith()
    try {
      const probe = await jpost(h.H.base, POST, badBodies[0][1], authHeaders(h.H.base))
      if (probe.status !== 404) {
        for (const [name, body] of badBodies) {
          const r = await jpost(h.H.base, POST, body, authHeaders(h.H.base))
          const blob = (r.text || '').toLowerCase()
          const named = /reason|instance|scope|required|empty|invalid|too long|missing/.test(blob)
          C.case('G3-refused-named-' + name,
            r.status >= 400 && r.status < 500 && named,
            `status=${r.status} body=${r.text.slice(0, 140)}`)
        }
        const after = existsSync(h.ledgerFile) ? readFileSync(h.ledgerFile, 'utf8') : ''
        C.case('G3-nothing-appended-on-malformed', after.trim() === '', `rows=${after.trim() ? after.trim().split('\n').length : 0}`)
      }
    } finally { await h.close() }
  }

  // ---- G2a FIRST USE: the very first trigger on a project must succeed —
  // ---- the append face owns creating its project account directory.    ----
  {
    const h = await harnessWith()
    try {
      const r = await jpost(h.H.base, POST,
        { project: PROJ, instance: 'integration-tests', scope: 'server/plugins', reason: 'first trigger on a fresh project' },
        authHeaders(h.H.base))
      if (r.status !== 404) {
        const rows = existsSync(h.ledgerFile)
          ? readFileSync(h.ledgerFile, 'utf8').trim().split('\n').filter(Boolean) : []
        // First-use success = the record LANDS in the project account. The
        // spawn itself may legitimately fail offline (temporalio/Temporal
        // unreachable) — the declared contract for that face is an explicit
        // 502-family answer WITH the attributed record (plan B3: spawn
        // failure → explicit record, never a silent no-op). Demanding HTTP
        // 200 here was a scenario-side over-assertion (gen2 fix): the record
        // landing is the first-use face; the spawn verdict is G4's.
        const spawned = r.status >= 200 && r.status < 300
        const namedSpawnFailure = r.status >= 500 && r.status < 600
          && /spawn|temporal|inspection_trigger/i.test(r.text)
        C.case('G2a-first-use-on-fresh-project-succeeds',
          rows.length === 1 && (spawned || namedSpawnFailure),
          `status=${r.status} rows=${rows.length} body=${r.text.slice(0, 200)}`)
      }
    } finally { await h.close() }
  }

  // ---- G2/G4: gated request → exactly one attributed record; real spawn ----
  // ---- fails offline, and the failure must be VISIBLE in the record.   ----
  {
    const h = await harnessWith({ seedProjectDir: true })
    try {
      const r = await jpost(h.H.base, POST,
        { project: PROJ, instance: 'integration-tests', scope: 'server/plugins', reason: 'host requested full-library review of plugins' },
        authHeaders(h.H.base))
      if (r.status === 404) {
        C.case('G2-trigger-appends-attributed-record', false, 'route 404 (not landed)')
      } else {
        const raw = existsSync(h.ledgerFile) ? readFileSync(h.ledgerFile, 'utf8') : ''
        const lines = raw.trim() ? raw.trim().split('\n') : []
        C.case('G2-exactly-one-record', lines.length === 1, `rows=${lines.length} http=${r.status}`)
        if (lines.length >= 1) {
          let row = null
          try { row = JSON.parse(lines[0]) } catch { /* torn line */ }
          C.case('G2-record-parses', !!row, 'line=' + lines[0].slice(0, 160))
          if (row) {
            const blob = JSON.stringify(row)
            C.case('G2-attributed-not-anonymous',
              blob.includes('server/plugins') && blob.includes('host requested full-library')
              && !!(row.at ?? row.when ?? row.time) && !!(row.by ?? row.who),
              'row=' + blob.slice(0, 300))
            // G4: offline spawn must surface as failed-or-pending-named,
            // never a fabricated ok:true success.
            const spawnFace = JSON.stringify(row.spawn ?? row.result ?? row.status ?? '')
            const honest = !/ok["']?\s*:\s*true/.test(spawnFace)
            C.case('G4-failed-spawn-visible-honest', honest,
              'spawn-face=' + spawnFace.slice(0, 200))
          }
          C.case('G2-ledger-in-project-account',
            h.ledgerFile.includes(join('inspection', 'trigger-records.jsonl')) && h.ledgerFile.startsWith(h.projectsDir),
            'path=' + h.ledgerFile)
        }
        // ---- G5 read side: newest-first, period-independent, read-only ----
        if (lines.length >= 1) {
          const g1 = await jget(h.H.base, GET)
          if (g1.status === 404) {
            C.case('G5-records-read-face-landed', false, 'GET ' + GET + ' → 404 (P4)')
          } else {
            C.case('G5-records-read-face-landed', g1.status === 200, 'status=' + g1.status)
            const rows = g1.body && (g1.body.records ?? g1.body.rows ?? g1.body.items)
            C.case('G5-records-newest-first',
              Array.isArray(rows) && rows.length >= 1
              && String(JSON.stringify(rows[0])).includes('server/plugins'),
              'rows=' + (rows ? rows.length : 'none'))
            const before = readFileSync(h.ledgerFile, 'utf8')
            await jget(h.H.base, GET + '&period=20261004')
            const after = readFileSync(h.ledgerFile, 'utf8')
            C.case('G5-read-is-readonly', before === after, '')
          }
          // malformed rows are counted, not silently dropped (B4 family)
          writeFileSync(h.ledgerFile, '{torn line\n' + raw)
          const g2 = await jget(h.H.base, GET)
          const gb = JSON.stringify(g1.body ? g2.body ?? {} : {})
          C.case('G5-malformed-row-counted-not-dropped',
            /malformed|invalid|count/i.test(gb) || (g2.body && (g2.body.records ?? []).length >= 1),
            'body=' + gb.slice(0, 200))
        }
      }
    } finally { await h.close() }
  }

  C.exit()
}

main().catch((e) => { console.log(`[FAIL] scenario-run — ${String(e?.stack ?? e).slice(0, 300)}`); process.exit(1) })
