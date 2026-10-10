#!/usr/bin/env node
/**
 * sc_reconcile_scope_t261009-61.mjs — ticket t261009-61 scenario (grey-box L3,
 * real Watchdog class on injected in-memory io — the established core seam,
 * offline seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Intent (user-perceivable, KI-01M4J6926Z30WVQ0R18A5PP6NK): the alerts face the
 * host actually reads must NOT carry a permanent non-converging
 * `reconcile_mismatch` redline built out of harmless history. Two harmless classes
 * previously counted forever:
 *   Class A — terminal tickets (status closed/verified) whose board stage_state is
 *             the close-out default (`awaiting`) while the ledger's derived last
 *             stage is `merge` (279 rows on the real board);
 *   Class B — ledger-only history: ids the board no longer lists (archived/pruned
 *             workflows, `dispatcher-scan-*` scans) shown as `board=<absent>`
 *             (~416 rows).
 * A redline must be actionable and must be able to converge. A REAL divergence on
 * an in-flight ticket must still raise the redline, named, not buried.
 *
 * Steps (real Watchdog, per-heartbeat reconcile over board x ledger fixtures):
 *  R1 Class A shape: closed board rows (stage_state=awaiting) vs ledger last stage
 *     merge -> NO reconcile_mismatch alert; reconcile face not `mismatch`.
 *  R2 Class B shape: ledger-only dispatcher-scan-* and pruned ticket ids -> no
 *     `board=<absent>` mismatches, no alert.
 *  R3 real divergence: in-flight ticket (no terminal status) with genuinely
 *     differing board/ledger states -> reconcile_mismatch redline naming the
 *     ticket AND both state words (the error names what actually failed).
 *  R4 the 630 shape end to end: Class A rows + Class B rows + exactly one real
 *     in-flight divergence -> the redline fires ONCE and its count is 1 — the
 *     real divergence is not buried under history.
 *  R5 convergence: the diverging in-flight ticket reaches a terminal status on
 *     the board -> the next heartbeat carries no reconcile_mismatch (the redline
 *     CAN clear — a redline that cannot converge is noise).
 *  R6 malformed input: ledger rows missing stage/stage_state and board rows with
 *     no status label -> no crash, no fabricated mismatch; status-absent rows
 *     stay conservative (a real state-word divergence on a status-absent row is
 *     still counted — historical tickets must not become a silent blind spot).
 *
 * TDD note: R1/R2/R4/R5 red before the implement stage lands (expected signal);
 * must be green at arbitrate/merge. Watchdog tree missing = ENV_FAIL exit 2.
 */
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const WD = join(REPO, 'server/plugins/watchdog')

let Watchdog, memTailIo, memCoreIo, ledgerLine, fakeClock
try {
  ;({ Watchdog } = await import(pathToFileURL(join(WD, 'src/host/core.ts')).href))
  const lib = await import(pathToFileURL(join(WD, 'tests/lib.mjs')).href)
  ;({ memTailIo, memCoreIo, ledgerLine, fakeClock } = lib)
} catch (e) {
  console.error('ENV_FAIL: watchdog tree or its test lib unavailable: ' + (e && e.message))
  process.exit(2)
}

let fails = 0
const fail = (m) => { console.error('FAIL ' + m); fails += 1 }
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } } }

function boot({ boardRows = [], ledgerLines = [], clock = fakeClock() }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => ({
      ...CFG,
      config: {
        enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
        alerts: { enabled: true, sound: false, desktop: false, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: async (p) => core.listAlerts(p) },
    boardReader: async () => ({ ok: true, rows: boardRows }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome-sc61' },
  })
  return w
}

const mismatchAlerts = (st) => (st.alerts ?? []).filter((a) => a.rule === 'reconcile_mismatch')
const redlineAlerts = (st) => (st.alerts ?? []).filter((a) => a.rule === 'reconcile_mismatch' && a.level === 'redline')

// Closed board row in the real close-out shape: status=closed, stage_state=awaiting.
const closedRow = (id) => ({ id, status: 'closed', stage: 'closeout', stage_state: 'awaiting' })
// Ledger line whose derived last stage is merge (the closed ticket's real last stage).
const mergeLine = (ticket, seq) => ledgerLine({ seq, ticket, stage: 'merge', stage_state: 'merge' })
// Ledger-only historical id (archived/pruned workflow or scan).
const scanLine = (ticket, seq) => ledgerLine({ seq, ticket, stage: 'scan', stage_state: 'scan' })

try {
  // ── R1: Class A shape — terminal rows' state-word drift is not a mismatch ──
  {
    const rows = ['t260928-20', 't260928-28', 't260928-29'].map(closedRow)
    const lines = ['t260928-20', 't260928-28', 't260928-29'].map((t, i) => mergeLine(t, i + 1))
    const w = boot({ boardRows: rows, ledgerLines: lines })
    await w.start()
    const st = w.status()
    if (mismatchAlerts(st).length !== 0) fail(`R1 closed-ticket awaiting-vs-merge drift raised reconcile_mismatch (must not — terminal rows are not actionable): ${JSON.stringify(mismatchAlerts(st)).slice(0, 300)}`)
    if (st.reconcile?.state === 'mismatch') fail(`R1 reconcile face reads mismatch over terminal-only drift: ${JSON.stringify(st.reconcile).slice(0, 200)}`)
    w.dispose()
  }

  // ── R2: Class B shape — ledger-only history is not board=<absent> mismatch ──
  {
    const scans = Array.from({ length: 5 }, (_, i) => scanLine(`dispatcher-scan-2026-09-28T14:${String(10 + i).padStart(2, '0')}:16Z`, 10 + i))
    const pruned = ['t260901-77', 't260902-03'].map((t, i) => ledgerLine({ seq: 20 + i, ticket: t, stage_state: 'merge' }))
    const w = boot({ boardRows: [], ledgerLines: [...scans, ...pruned] })
    await w.start()
    const st = w.status()
    if (mismatchAlerts(st).length !== 0) fail(`R2 ledger-only history raised reconcile_mismatch (must not — historical ids are not someone's next action): ${JSON.stringify(mismatchAlerts(st)).slice(0, 300)}`)
    const text = JSON.stringify(st.reconcile ?? {})
    if (text.includes('<absent>')) fail(`R2 reconcile face still carries board=<absent> rows for history: ${text.slice(0, 300)}`)
    w.dispose()
  }

  // ── R3: a real in-flight divergence still redlines, named with both sides ──
  {
    const w = boot({
      boardRows: [{ id: 't-live-1', status: 'dispatched', stage: 'implement', stage_state: 'running' }],
      ledgerLines: [ledgerLine({ seq: 1, ticket: 't-live-1', stage: 'review', stage_state: 'review_plan' })],
    })
    await w.start()
    const st = w.status()
    const rl = redlineAlerts(st)
    if (rl.length === 0) fail(`R3 real in-flight divergence did NOT redline — the fix must not open a silence hole. reconcile=${JSON.stringify(st.reconcile).slice(0, 200)}`)
    else {
      const text = JSON.stringify(rl)
      for (const needle of ['t-live-1', 'running', 'review_plan']) {
        if (!text.includes(needle)) fail(`R3 redline does not name '${needle}' (an error must name what actually failed): ${text.slice(0, 300)}`)
      }
    }
    w.dispose()
  }

  // ── R4: the 630 shape end to end — one real divergence, count = 1, not buried ──
  {
    const closedIds = Array.from({ length: 12 }, (_, i) => `t2609xx-${String(100 + i)}`)
    const scans = Array.from({ length: 8 }, (_, i) => scanLine(`dispatcher-scan-2026-09-28T15:${String(10 + i).padStart(2, '0')}:00Z`, 100 + i))
    const lines = [
      ...closedIds.map((t, i) => mergeLine(t, i + 1)),
      ...scans,
      ledgerLine({ seq: 500, ticket: 't-live-2', stage: 'verify', stage_state: 'verify' }),
    ]
    const w = boot({
      boardRows: [...closedIds.map(closedRow), { id: 't-live-2', status: 'dispatched', stage: 'verify', stage_state: 'dispatched' }],
      ledgerLines: lines,
    })
    await w.start()
    const st = w.status()
    const rl = redlineAlerts(st)
    if (rl.length === 0) fail(`R4 the 630 shape produced NO redline even though a real in-flight divergence (t-live-2) exists — history suppression must not eat the real one`)
    else {
      const detail = rl.map((a) => JSON.stringify(a)).join('\n')
      if (!detail.includes('t-live-2')) fail(`R4 redline dropped the real diverging ticket t-live-2: ${detail.slice(0, 300)}`)
      if (/t2609xx-/.test(detail)) fail(`R4 redline still carries terminal-ticket rows inside the mixed fixture: ${detail.slice(0, 300)}`)
      if (/dispatcher-scan-/.test(detail)) fail(`R4 redline still carries ledger-only scan rows: ${detail.slice(0, 300)}`)
      const n = (st.reconcile?.mismatches ?? []).length
      if (n !== 1) fail(`R4 mismatch count over the 630-shaped fixture is ${n}, expected 1 (only the actionable in-flight divergence): ${JSON.stringify(st.reconcile?.mismatches).slice(0, 300)}`)
    }
    w.dispose()
  }

  // ── R5: convergence — once the diverging ticket goes terminal, the redline clears ──
  {
    const clock = fakeClock()
    const w = boot({
      clock,
      boardRows: [{ id: 't-live-3', status: 'dispatched', stage: 'review', stage_state: 'review_plan' }],
      ledgerLines: [ledgerLine({ seq: 1, ticket: 't-live-3', stage: 'review', stage_state: 'running' })],
    })
    await w.start()
    if (redlineAlerts(w.status()).length === 0) fail('R5 pre-state: expected a redline for the genuine divergence before close-out')
    // The ticket closes; the board row goes terminal (status + close-out default).
    w.boardReader = async () => ({ ok: true, rows: [{ id: 't-live-3', status: 'closed', stage: 'closeout', stage_state: 'awaiting' }] })
    await w.tickOnce()
    const st2 = w.status()
    const fresh = redlineAlerts(st2).length
    if (fresh > 1) fail(`R5 redline re-raised after the diverging ticket reached a terminal state (a terminal row is no longer actionable): ${JSON.stringify(redlineAlerts(st2)).slice(0, 300)}`)
    if (st2.reconcile?.state === 'mismatch') fail(`R5 reconcile face still mismatch after close-out: ${JSON.stringify(st2.reconcile).slice(0, 200)}`)
    w.dispose()
  }

  // ── R6: malformed / sparse input — no crash, no fabricated mismatch, conservative core ──
  {
    const lines = [
      '{{{not json at all', // malformed row: named skip, never a crash
      ledgerLine({ seq: 2, ticket: 't-sparse-1', __drop: ['stage', 'stage_state'] }), // row with no state words
      ledgerLine({ seq: 3, ticket: 't-sparse-2', stage_state: 'merge' }), // status-absent historical ticket, real drift
    ]
    const w = boot({
      boardRows: [
        { id: 't-sparse-1', stage: 'implement', stage_state: 'running' }, // board has state, ledger does not -> no fabricated mismatch
        { id: 't-sparse-2', stage_state: 'awaiting' }, // no status label: conservative = still compared
      ],
      ledgerLines: lines,
    })
    await w.start()
    const st = w.status()
    if (st.phase !== 'running') fail(`R6 malformed/sparse ledger row crashed the watchdog: phase=${st.phase}`)
    const mm = st.reconcile?.mismatches ?? []
    const sparse1 = mm.filter((m) => m.ticket === 't-sparse-1')
    if (sparse1.length !== 0) fail(`R6 fabricated a mismatch from a ledger row with no state words (missing side must not invent a comparison): ${JSON.stringify(sparse1)}`)
    const sparse2 = mm.filter((m) => m.ticket === 't-sparse-2')
    if (sparse2.length !== 1) fail(`R6 status-absent row with real state drift was silently dropped (historical rows stay conservative, not blind): ${JSON.stringify(mm)}`)
    w.dispose()
  }
} catch (e) {
  fail('R9 scenario crashed: ' + (e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : String(e)))
}

console.log(`SUMMARY pass=${6 - fails} fail=${fails} env_fail=0 na=0`)
process.exit(fails === 0 ? 0 : 1)
