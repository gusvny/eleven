// sc_recent_actions_failure_face.mjs — t261005-12: a recording failure is
// visible to the READER, not only to the caller's stderr (ticket req. 2).
//
// Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
// 3099/7233. Drives the production panel harness (seam reused from
// t261003-06/lib_panel_seam, executorActionsDir injection per t261004-11)
// against the project's own executor-actions ledger + the engine-written
// last-failure marker (executor-actions.last-failure.json, see
// sc_gate_recording_engine_route.py for the writer side).
//
// User-perceivable faces:
//   R1 an empty ledger WITH a last-failure marker must NOT be presented as
//      mere "no recorded executor action" (the ticket's headline defect: the
//      pane stayed empty and silent) — the read face must surface the marker
//      (the injected why/error tokens readable somewhere in the body).
//   R2 the marker's why/error text reaches the reader verbatim enough to
//      name the failure (at least the injected why token + the error class).
//   R3 a MALFORMED marker (bad JSON / array / scalar) is treated as absent:
//      no crash, no fabricated failure claim, and the empty-state copy stays
//      honest (external-input discipline, t261003-10 A3 family).
//   R4 rows still present + marker present: the rows are served unchanged
//      AND the failure state is still visible (a past failure does not hide
//      current rows, and current rows do not hide the failure).
//   R5 read-only red line: reading never writes the ledger or the marker
//      (byte-compare before/after).
//
// intent 分工：writer 侧（引擎落 marker、caller 零写、路由契约）归
// sc_gate_recording_engine_route.py；空态/坏行/降级读源契约归
// t261003-10-recent-actions-real-source；本条只锁「失败对面板读者可见」。
// 三态：node 缺席=ENV_FAIL exit 2；闸内无 SKIP。harness 缺场=FAIL 点名
// （TDD 期红属预期，arbitrate/merge 期必须绿）。
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PANEL_ROUTE = '/sandbar-executor-panel'
const PROJ = 'sandbar'
const MARKER = 'executor-actions.last-failure.json'
const WHY = 'append to executor-actions.jsonl failed'
const ERR = 'PermissionError'

const C = makeCase()
const api = PANEL_ROUTE + '/api/actions?project=' + PROJ

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function harnessWith(ledgerContent, markerContent) {
  const iso = makeIsoDir()
  const dir = join(iso.dir, 'ledger')
  mkdirSync(dir, { recursive: true })
  const ledger = join(dir, PROJ + '.jsonl')
  if (ledgerContent !== null && ledgerContent !== undefined) writeFileSync(ledger, ledgerContent)
  if (markerContent !== null && markerContent !== undefined) writeFileSync(join(dir, MARKER), markerContent)
  const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), executorActionsDir: dir })
  return { H, dir, ledger, markerPath: join(dir, MARKER) }
}

let mod = null

async function main() {
  if (!existsSync(HARNESS_PATH)) {
    C.case('harness-present', false, 'server/plugins/executor-panel/harness.mjs 缺场')
    return C.exit()
  }
  mod = await import('file://' + HARNESS_PATH).catch((e) => {
    C.case('harness-loadable', false, String(e).slice(0, 300)); return null
  })
  if (!mod) return C.exit()
  if (typeof mod.startPluginHarness !== 'function') {
    C.case('plugin-shell-seam-present', false, 'harness.mjs 缺 startPluginHarness（缝契约见头注）')
    return C.exit()
  }

  // ---- R1 + R2: empty ledger + marker => failure surfaced, not silent ----
  {
    const marker = JSON.stringify({ at: '2026-10-05T00:00:00Z', why: WHY, error: ERR })
    const { H } = await harnessWith(null, marker)
    try {
      const r = await jfetch(H.base, api)
      const s = JSON.stringify(r.body || {})
      // Surfacing = the marker's own tokens appear in the body. The honest
      // empty copy alone ("no recorded executor action") is NOT surfacing —
      // that exact copy is the ticket's headline silence.
      const surfaced = s.includes(ERR) && s.includes(WHY.slice(0, 24))
      C.case('R1-failure-not-silent-on-empty', surfaced,
        'status=' + r.status + ' body=' + s.slice(0, 260))
      C.case('R2-why-and-error-reach-reader',
        s.includes(WHY.slice(0, 24)) && s.includes(ERR),
        'body=' + s.slice(0, 500))
    } finally { await H.close() }
  }

  // ---- R3: malformed marker treated as absent, empty copy stays honest ----
  for (const [name, bad] of [['not-json', '{oops'], ['array', '[]'], ['scalar', '42']]) {
    const { H } = await harnessWith(null, bad)
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const s = JSON.stringify(b)
      const honest = b.ok === false && String(b.reason || b.error || '').includes('no recorded executor action')
      const crashed = r.status >= 500 || s.includes('SyntaxError')
      C.case('R3-malformed-' + name, honest && !crashed,
        'status=' + r.status + ' body=' + s.slice(0, 200))
    } finally { await H.close() }
  }

  // ---- R4: rows + marker => both visible ----
  {
    const marker = JSON.stringify({ at: '2026-10-05T00:00:00Z', why: WHY, error: ERR })
    const row = JSON.stringify({
      idem: 't26100512-a', at: '2026-10-05T01:00:00Z', op: 'sign',
      ticket: 't261005-12', decision: 'allowed', session: 'sess-x', channel: 'exec',
    })
    const { H, dir } = await harnessWith(row + '\n', marker)
    try {
      const r = await jfetch(H.base, api)
      const s = JSON.stringify(r.body || {})
      C.case('R4-rows-and-failure-both-visible',
        s.includes('t261005-12') && s.includes(ERR),
        'marker_on_disk=' + existsSync(join(dir, MARKER))
        + ' body=' + s.slice(0, 700))
    } finally { await H.close() }
  }

  // ---- R5: read-only red line ----
  {
    const marker = JSON.stringify({ at: '2026-10-05T00:00:00Z', why: WHY, error: ERR })
    const { H, ledger, markerPath } = await harnessWith(null, marker)
    try {
      const beforeL = existsSync(ledger) ? readFileSync(ledger, 'utf8') : null
      const beforeM = readFileSync(markerPath, 'utf8')
      await jfetch(H.base, api)
      const afterL = existsSync(ledger) ? readFileSync(ledger, 'utf8') : null
      const afterM = readFileSync(markerPath, 'utf8')
      C.case('R5-readonly-untouched',
        (beforeL === null && afterL === null) || beforeL === afterL,
        'ledger mutated by a READ')
      C.case('R5b-marker-untouched', beforeM === afterM, 'marker mutated by a READ')
    } finally { await H.close() }
  }

  C.exit()
}

main().catch((e) => { C.case('runner', false, String(e).slice(0, 300)); C.exit() })
