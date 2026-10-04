#!/usr/bin/env node
/**
 * sc_panel_engine_row_old_door — the panel shows an engine-filed request with its
 * source, and the old door tells the executor where to go (t261004-23, gray-box
 * L2, offline seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * User-perceivable contract (host decision 261004, option 1):
 *  P1 an engine-filed row (surface: "engine", raised_by = executor session) that
 *     lands in the project's requests.jsonl shows up in the panel's read payload
 *     as a waiting request with both fields visible — the panel reads the same
 *     ledger the engine writes.
 *  P2 when the panel write gate (t261004-18) is present, an unauthenticated write
 *     is refused and the refusal copy names the engine entry path, so the
 *     executor that tries the old door is told where to go instead of guessing.
 *     Gate not landed yet = ENV_FAIL exit 2 naming the dependency (the ticket
 *     keeps the gate untouched; no relaxation is asserted here).
 *  P3 the refusal copy does not hand over a credential (no cookie/token minting
 *     recipe) — it points at the engine path, nothing else.
 *
 * Gray-box anchoring: the panel's public reader output and the 401 refusal copy
 * face only. No internal function names, no execution order.
 */
import { readFileSync, mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readRequests, fsLedgerIo } from '../../server/plugins/executor-panel/src/host/requests.ts'

let PASS = 0, FAIL = 0
const ok = (c, label) => { if (c) { PASS++; console.log('  ✓ ' + label) } else { FAIL++; console.log('  ✗ ' + label) } }
const section = (t) => console.log('\n' + t)
const die = (why) => { console.error('ENV_FAIL: ' + why); process.exit(2) }

const API_SRC = new URL('../../server/plugins/executor-panel/src/host/api.ts', import.meta.url)
let apiSrc = ''
try { apiSrc = readFileSync(API_SRC, 'utf8') } catch { die('executor-panel api.ts unreadable: ' + API_SRC.pathname) }

// ---------- P1 engine-filed row visible in the panel payload ----------
section('P1 engine 行进面板读出：waiting + raised_by + surface 可见')
const tmp = mkdtempSync(join(tmpdir(), 'sc-t261004-23-'))
try {
  const root = join(tmp, 'projects')
  const key = 't26100423fixture'
  const session = 't261004-23-executor-session'
  mkdirSync(join(root, key), { recursive: true })
  // One engine-filed row, exactly the shape the engine entry appends, plus one
  // panel-filed row (no surface) as the contrast face.
  const now = Date.now()
  const engineRow = { type: 'request', id: 'req-' + now + '-1', at: now, project: key,
    kind: 'approval', question: 'Can ticket T-9 merge now?', detail: '', default_action: 'hold',
    options: ['merge now', 'hold one round'], expires_at: null, raised_by: session, surface: 'engine' }
  const panelRow = { type: 'request', id: 'req-' + now + '-2', at: now + 1, project: key,
    kind: 'approval', question: 'Panel-filed contrast row?', detail: '', default_action: 'wait',
    options: undefined, expires_at: null, raised_by: 'host-session' }
  writeFileSync(join(root, key, 'requests.jsonl'),
    JSON.stringify(engineRow) + '\n' + JSON.stringify(panelRow) + '\n')

  const read = readRequests(fsLedgerIo, { SANDBAR_PANEL_DIR: root }, key)
  const rows = (read && read.rows) || []
  const eng = rows.find((r) => r.id === engineRow.id)
  const pnl = rows.find((r) => r.id === panelRow.id)
  ok(rows.length === 2, 'both rows read back (got ' + rows.length + ')')
  ok(Boolean(eng), 'engine-filed row appears in the panel read payload')
  if (eng) {
    ok(eng.status === 'waiting', 'engine-filed row shows as waiting (status=' + eng.status + ')')
    ok(eng.raised_by === session, 'raised_by = executor session visible in payload (' + eng.raised_by + ')')
    ok(eng.surface === 'engine', 'source marker surface=engine visible in payload (' + eng.surface + ')')
  }
  ok(Boolean(pnl) && pnl.surface === undefined, 'panel-filed contrast row carries no engine marker (source is truthful both ways)')
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

// ---------- P2/P3 old door copy (gate = t261004-18, may not be landed) ----------
section('P2/P3 旧门 401 文案点名 engine 去处（闸未落地=ENV_FAIL 点名依赖）')
const gateMarkers = ['401', 'cookie']
const hasGate = gateMarkers.every((m) => apiSrc.includes(m))
if (!hasGate) {
  console.log('  ~ panel write gate (t261004-18) not in this tree — P2/P3 cannot run yet')
  console.error('ENV_FAIL: panel write gate t261004-18 not landed in this tree; 401-copy checks pending that merge')
  // A real red on the runnable half takes precedence over the environment red.
  console.log('\nPASS ' + PASS + ' FAIL ' + FAIL)
  process.exit(FAIL ? 1 : 2)
}
// The 401 refusal face must name the engine entry path. Anchor: the engine entry
// path substring, searched near a 401/unauthorized refusal, wording-tolerant.
const namesEnginePath = /401[\s\S]{0,400}?server\/engine\/executor_requests|server\/engine\/executor_requests[\s\S]{0,400}?401/.test(apiSrc)
ok(namesEnginePath, 'refused-write (401) copy names the engine entry path server/engine/executor_requests')
const mintRecipe = /(cookie[^`\n]{0,80}=|sign(ed)?\s+(with|key)|HMAC[\s\S]{0,40}secret)/i.test(apiSrc.split('401').slice(1).join('401').slice(0, 2000))
ok(!mintRecipe, 'refusal copy hands over no credential recipe (points at the engine path only)')

console.log('\nPASS ' + PASS + ' FAIL ' + FAIL)
process.exit(FAIL ? 1 : 0)
