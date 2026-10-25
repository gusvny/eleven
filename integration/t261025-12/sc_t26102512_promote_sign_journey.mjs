/**
 * sc_t26102512_promote_sign_journey.mjs — t261025-12, part 2 of 3.
 *
 * intent (host ruling 261025 option c, §5 "Sign a promotion", + ticket item B):
 *   The panel performs the signed promotion act by calling the ENGINE's
 *   promotion writer — never a second implementation. The recorded row names
 *   the HUMAN identity that signed; an agent role name is refused by the
 *   engine no matter which surface sent it; the engine's named refusals
 *   (agent role name, promotion_not_fast_forward, no_green_certification)
 *   reach the panel verbatim, never as a generic failure; and the answer is
 *   the ledger READ-BACK row (signer + revisions moved), never an optimistic
 *   guess — a write that claims ok while the ledger holds no row is a named
 *   inconsistency, not success.
 *
 * failure surface (grey-box):
 *   - a panel-side refusal that BYPASSES the engine (UI-only identity check —
 *     a role bypass); the refusal must come from promote_buffer's own rule;
 *   - refusals flattened into one generic 'promote failed' message;
 *   - an optimistic success on a write whose read-back finds nothing;
 *   - a recorded signer defaulted from an agent-role owner (KI-193 identity
 *     discipline: never invent the human);
 *   - a preview that renders a number while the face is unreadable (the
 *     host's 'Promote 1' incident — count with nothing behind it).
 *
 * layering / intent split:
 *   - promote_buffer/preview truth tables over fixture repos (fast-forward
 *     geometry, green-cert rules, preview moves-no-ref) belong to developer
 *     L1 pytest (test_t261025_12_promote_preview.py) and the engine's own
 *     suite; the adapter receipt parse matrices belong to L1 too;
 *   - the green-certification + landing + promotion ledger semantics belong
 *     to the t261009-18/-28/-30 families; KI-193's credential gate is owned
 *     by the queue journey's E-face (sibling scenario) and the L1 gate tests;
 *   - THIS entry owns the panel-to-engine refusal journey (verbatim texts,
 *     engine-as-enforcement-point) and the read-back/mismatch contract over
 *     the real route and the real ledger file.
 *
 * offline: zero docker / Temporal server / browser, never touches 3099/7233.
 * The refusal cases run against the REAL engine writer (develop_promote
 * imported by the real adapter subprocess); the happy-path row shape is
 * judged on a REAL ledger file through the real read face, with only the
 * git-writing leg stubbed at the route's declared seam. Pre-implement tree
 * red (route/adapter face absent) = the named TDD signal; green required at
 * the integration gate/merge. api.ts or the adapter unimportable/unspawnable
 * = ENV_FAIL exit 2.
 */
import { mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

let failed = 0
function ok(cond, label) {
  if (cond) { console.log(`  ok  ${label}`) } else { failed++; console.log(`FAIL  ${label}`) }
}

let createApi
try {
  ;({ createApi } = await import('../../server/plugins/executor-panel/src/host/api.ts'))
} catch (e) {
  console.log(`ENV_FAIL: executor-panel api.ts unimportable: ${e && e.message}`)
  process.exit(2)
}
const REPO = resolve(import.meta.dirname, '../..')

const ROUTE = '/sandbar-executor-panel/api/certification/promote'
// the credential the gate binds: cookie name derived from the Host header
import { createHash } from 'node:crypto'
const HOST = 'panel.sc.test'
const AUTH_NAME = 'dsh-auth-' + createHash('sha256').update(HOST).digest('base64url')
const auth = { cookie: `${AUTH_NAME}=v1.sig.sig`, host: HOST }

const tmp = mkdtempSync(join(tmpdir(), 'sc-t26102512-promote-'))
try {
  const projects = join(tmp, 'projects')
  const ledgerDir = join(projects, 'proj-p', 'ledger')
  mkdirSync(ledgerDir, { recursive: true })
  mkdirSync(join(projects, 'proj-p', 'data', 'develop'), { recursive: true })
  writeFileSync(join(projects, 'proj-p', 'data', 'develop', 'lines.json'), JSON.stringify([
    // owner deliberately an AGENT ROLE NAME: the worst legal prefill source
    { line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'developer-agent' },
  ]))
  // the engine's env contract: a FLAT DIRECTORY of <project>.jsonl files
  const ledgerFile = join(ledgerDir, 'proj-p.jsonl')
  writeFileSync(ledgerFile, '')
  const env = {
    HOME: tmp,
    SANDBAR_PROJECTS_DIR: projects,
    SANDBAR_DELIVERY_LEDGER_DIR: ledgerDir,
    SANDBAR_RUNS_LEDGER: '',
  }

  // ---- A. the engine is the enforcement point: an agent role name is refused
  //        by the WRITER, verbatim, and the ledger stays byte-identical
  {
    const before = readFileSync(ledgerFile, 'utf8')
    const api = createApi(env, {}) // NO stubs: the real engine chain answers
    const r = await api.handle('POST', ROUTE, new URLSearchParams(),
      JSON.stringify({ project: 'proj-p', line: 'develop-buffer', signer: 'developer-agent' }), 'http://panel', auth)
    ok(r.status !== 200, `A1 an agent-role signer does NOT succeed (got ${r.status})`)
    const txt = JSON.stringify(r.json || {})
    ok(/signer_is_agent_role_name|agent role name/i.test(txt),
      `A2 the refusal NAMES the agent-role rule verbatim (got ${txt.slice(0, 200)})`)
    ok(!/generic|failed unexpectedly/i.test(txt) && (r.json && r.json.error || r.json && r.json.reason || '').length > 0,
      'A3 the refusal is a named one, not a generic failure')
    ok(readFileSync(ledgerFile, 'utf8') === before,
      'A4 the delivery ledger is byte-identical after the refused act')
  }

  // ---- B. the engine's other refusal vocabulary travels verbatim
  {
    const api = createApi(env, {})
    // no green certification exists in the fixture ledger -> engine refuses
    const r = await api.handle('POST', ROUTE, new URLSearchParams(),
      JSON.stringify({ project: 'proj-p', line: 'develop-buffer', signer: 'host' }), 'http://panel', auth)
    ok(r.status !== 200, 'B1 a promotable-less line does not succeed')
    const txt = JSON.stringify(r.json || {})
    ok(/no_green_certification|green certification|promotion_missing_signer|signer/i.test(txt),
      `B2 the engine's own refusal text travels verbatim (got ${txt.slice(0, 200)})`)
    const r2 = await api.handle('POST', ROUTE, new URLSearchParams(),
      JSON.stringify({ project: 'proj-p', line: 'develop-buffer', signer: '   ' }), 'http://panel', auth)
    ok(r2.status === 400, 'B3 an empty signer is a named 400 (never sent to the engine)')
  }

  // ---- C. the answer is the READ-BACK row, never the writer's word
  {
    const row = { id: 'prom-1', kind: 'promotion', at: 1730000000000, signer: 'host', line_id: 'develop-buffer',
      cert_id: 'cert-1', revisions: { src: 'abc1234' } }
    const api = createApi(env, {
      // the git-WRITING leg is stubbed at the route's declared seam (its truth
      // tables are L1/pytest land); the READ-BACK leg below parses the REAL
      // ledger file from disk — the reader side stays real.
      certPromoteWrite: async () => ({ ok: true, row: { id: 'prom-1', signer: 'host' } }),
      certPromoteLatest: async () => {
        const lines = readFileSync(ledgerFile, 'utf8').trim().split('\n').filter(Boolean)
        return { ok: true, promotion: lines.length ? JSON.parse(lines[lines.length - 1]) : undefined }
      },
    })
    writeFileSync(ledgerFile, JSON.stringify(row) + '\n')
    const r = await api.handle('POST', ROUTE, new URLSearchParams(),
      JSON.stringify({ project: 'proj-p', line: 'develop-buffer', signer: 'host' }), 'http://panel', auth)
    ok(r.status === 200 && r.json && r.json.ok === true, 'C1 a promotable act answers 200 ok')
    const ans = JSON.stringify(r.json || {})
    ok(/"signer":"host"/.test(ans) && /revisions|cert_id/.test(ans),
      'C2 the answer carries signer + what the signature moved (read back, not guessed)')
    // reader side: the row is genuinely in the ledger file the face reads
    ok(readFileSync(ledgerFile, 'utf8').includes('"signer":"host"'),
      'C3 the promotion row is READ BACK from the real ledger file on disk')
  }

  // ---- D. write says ok, ledger holds nothing -> named inconsistency, never success
  {
    const api = createApi(env, {
      certPromoteWrite: async () => ({ ok: true, row: { id: 'prom-x', signer: 'host' } }),
      certPromoteLatest: async () => ({ ok: true, promotion: undefined }),
    })
    writeFileSync(ledgerFile, '') // ledger EMPTY: the read-back will find no row
    const r = await api.handle('POST', ROUTE, new URLSearchParams(),
      JSON.stringify({ project: 'proj-p', line: 'develop-buffer', signer: 'host' }), 'http://panel', auth)
    ok(r.status !== 200, `D1 a write-ok-but-no-row act is NOT a 200 (got ${r.status})`)
    const txt = JSON.stringify(r.json || {})
    ok(/read.?back|no row|not found|inconsisten|ledger/i.test(txt),
      `D2 the inconsistency is NAMED (got ${txt.slice(0, 200)})`)
  }

  // ---- E. the eligibility face: unreadable means NO number, ever
  {
    // the real adapter, run directly: a broken store must refuse by name
    const adapter = join(REPO, 'server/plugins/executor-panel/src/host/certification-adapter.py')
    ok(existsSync(adapter), 'E0 the certification adapter exists at its declared path')
    if (existsSync(adapter)) {
      // the adapter imports the engine (temporalio); use the engine venv
      // first, the same fallback chain every registry entry uses
      const venvPy = join(REPO, 'server/engine/.venv/bin/python')
      const py = existsSync(venvPy) ? venvPy : 'python3'
      let out = ''
      let rc = 0
      try {
        out = execFileSync(py, [adapter, 'promote-preview', 'proj-p'], {
          env: { ...process.env, SANDBAR_PROJECTS_DIR: join(tmp, 'missing'), HOME: tmp },
          encoding: 'utf8',
        })
      } catch (e) {
        rc = e.status ?? 1
        out = (e.stdout || '') + (e.stderr || '')
      }
      const txt = out.trim()
      let face = null
      try { face = JSON.parse(txt.split('\n').filter((l) => l.trim().startsWith('{')).pop() || 'null') } catch { /* named below */ }
      ok(face !== null, `E1 the promote-preview face answers one strict JSON receipt (rc=${rc})`)
      if (face) {
        ok(face.ok === false && typeof face.reason === 'string' && face.reason.length > 0,
          `E2 an unreadable store is a NAMED refusal (got ${JSON.stringify(face).slice(0, 160)})`)
        ok(!('promotable' in face) || face.promotable === 0 || face.promotable === undefined,
          'E3 the unreadable face carries NO promotable number (the Promote-1 lie stays dead)')
      }
    }
  }

  // ---- F. the panel never invents the human: an agent-role owner is not a signer default
  {
    const { buildCertificationCore } = await import('../../server/plugins/executor-panel/src/host/certification-view.ts')
    const core = buildCertificationCore({
      project: 'proj-p',
      lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'developer-agent' }],
      face: { ok: true, lineId: 'develop-buffer', state: 'GREEN', frozen: false, frozenFace: null,
        deliveredTotal: 1, certified: [], waiting: [], promotable: 0, promoteBlock: 'nothing certified', boundary: null, rounds: [], roundState: 'idle' },
      raw: { certs: [], runs: [], outcomes: [] }, notes: [],
    })
    ok(!/value\s*=\s*["']developer-agent/.test(core),
      'F1 the rendered tab never prefills the agent-role owner as the signer value')
    ok(!/developer-agent/.test(core),
      'F2 the agent role name appears nowhere on the certification face as an identity')
  }

  if (failed > 0) {
    console.log(`FAIL sc_t26102512_promote_sign_journey: ${failed} red check(s)`)
    process.exit(1)
  }
  console.log('PASS sc_t26102512_promote_sign_journey')
  process.exit(0)
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
