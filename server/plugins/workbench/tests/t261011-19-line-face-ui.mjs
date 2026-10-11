// t261011-19 — the LineOn pill unit layer:
//   1. lineFaceOf / linePillText truth tables (pure mapping; malformed-input
//      cases mandatory — the row is untrusted external input);
//   2. the engine adapter fixture run (line-face-adapter.py against a synthetic
//      project store — engine-derived faces, named refusals, fail-closed run
//      headers; no real external source);
//   3. source locks (pill anchors, no state row background, untouched rank
//      marker, ten cells, dim-same-hue todo cells, frozen notice in the header).
// Standalone executable (node >=22 type-stripping, cwd=repo root; exit 0 = pass).
// Zero network / zero console.
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { lineFaceOf, linePillText } from '../src/client/ticket-list-model.ts'

const repo = resolveRepo()
function resolveRepo() {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
}
let n = 0, fail = 0
function ok(name, fn) {
  try { fn(); n += 1; console.log(`  ok ${name}`) } catch (e) { fail += 1; console.log(`  FAIL ${name}: ${e.message}`) }
}

/* ---------------------------------------------- lineFaceOf truth table */

ok('lineFaceOf：六个引擎词 → 六种 pill 面（映射，非推导）', () => {
  assert.deepEqual(lineFaceOf({ line_face: 'on_line' }), { kind: 'muted-outline', overdue: false })
  assert.deepEqual(lineFaceOf({ line_face: 'waiting' }), { kind: 'warn', overdue: false })
  assert.deepEqual(lineFaceOf({ line_face: 'red_implicated' }), { kind: 'danger', overdue: false })
  assert.deepEqual(lineFaceOf({ line_face: 'certified' }), { kind: 'success-outline', overdue: false })
  assert.deepEqual(lineFaceOf({ line_face: 'delivered' }), { kind: 'success-solid', overdue: false })
  assert.deepEqual(lineFaceOf({ line_face: 'withdrawn' }), { kind: 'muted-solid', overdue: false })
})

ok('lineFaceOf：overdue 布尔透传（引擎旗标，! 只是 UI 后缀）', () => {
  assert.equal(lineFaceOf({ line_face: 'waiting', line_face_overdue: true }).overdue, true)
  assert.equal(lineFaceOf({ line_face: 'waiting', line_face_overdue: false }).overdue, false)
  assert.equal(lineFaceOf({ line_face: 'waiting', line_face_overdue: 'yes' }).overdue, false)
  assert.equal(lineFaceOf({ line_face: 'waiting', line_face_overdue: 1 }).overdue, false)
})

ok('lineFaceOf：畸形输入全兜 null（不猜状态、不 throw）', () => {
  for (const row of [{}, { line_face: undefined }, { line_face: null }, { line_face: 7 },
    { line_face: ['waiting'] }, { line_face: { s: 'waiting' } }, { line_face: '' },
    { line_face: 'not_an_engine_word' }, { line_face: 'GREEN' }, null, undefined]) {
    assert.equal(lineFaceOf(row), null, String(JSON.stringify(row)))
  }
})

ok('linePillText：文字恒 LineOn；! 只跟引擎 overdue 旗标', () => {
  assert.equal(linePillText({ kind: 'warn', overdue: false }), 'LineOn')
  assert.equal(linePillText({ kind: 'muted-outline', overdue: true }), 'LineOn!')
})

/* ---------------------------------------------- adapter fixture run */

const ADAPTER = join(repo, 'server/plugins/workbench/src/host/line-face-adapter.py')

function runAdapter(env, project) {
  // Same interpreter resolution chain as node.ts runPocCli: the engine venv
  // when present (engine modules import temporalio), else python3.
  const fs = { readFileSync }
  void fs
  let python = 'python3'
  try { readFileSync(join(repo, 'server/engine/.venv/bin/python')); python = join(repo, 'server/engine/.venv/bin/python') } catch { /* fall back */ }
  const r = execFileSync(python, [ADAPTER, project], {
    cwd: repo, env: { ...process.env, ...env }, encoding: 'utf8',
  })
  return JSON.parse(r)
}

function writeFixture(dir) {
  const key = 'ut19proj'
  const projects = join(dir, 'projects')
  const ledger = join(dir, 'ledger')
  mkdirSync(join(projects, key, 'data', 'develop'), { recursive: true })
  mkdirSync(ledger, { recursive: true })
  writeFileSync(join(projects, key, 'data', 'develop', 'lines.json'), JSON.stringify([
    { version: 1, line_id: 'dev-buffer', scope: 'ut', owner: 'ut',
      repositories: [{ name: 'sandbar', branch: 'develop-buffer-v1' }] },
  ]))
  const landing = (id, ticket, at, extra = {}) => JSON.stringify({
    kind: 'landing', id, ticket, line: 'dev-buffer', actor: 'ut', at, seq: at,
    repos: [{ repo: 'sandbar', revision: 'r' + at }], ...extra,
  })
  const rows = [
    // waiting ticket (landing, no cert yet)
    landing('ldg-1', 't-wait', 1000),
    // certified ticket (landing + cert citing a green run in the headers)
    landing('ldg-2', 't-cert', 1001),
    JSON.stringify({ kind: 'certification', id: 'cert-1', line: 'dev-buffer', at: 2000, seq: 2000,
      run: 'run-1', booked_red: 'no', judged_by: 'ut',
      repos: [{ repo: 'sandbar', revision: 'r1001' }] }),
    // delivered ticket (landing + promotion carrying it, seq space shared)
    landing('ldg-3', 't-deliv', 1002),
    JSON.stringify({ kind: 'promotion', id: 'promo-1', at: 3000, seq: 5, tickets: ['t-deliv'] }),
    // withdrawn ticket (landing + a current withdraws relation)
    landing('ldg-4', 't-wd', 1003),
    JSON.stringify({ kind: 'withdraws', id: 'rel-1', at: 3001, seq: 6,
      from: 't-other', to: 't-wd' }),
    // on the line via opt-in but no landing row: NO entry at all
  ]
  writeFileSync(join(ledger, `${key}.jsonl`), rows.join('\n') + '\n')
  writeFileSync(join(ledger, 'promotion.jsonl'), '')
  writeFileSync(join(ledger, 'runs.jsonl'), JSON.stringify({
    id: 'run-1', cases: { ran: 2, failed: 0, env_failed: 0 }, source: 'manual', started_at: 1500,
  }) + '\n')
  const env = {
    SANDBAR_PROJECTS_DIR: projects,
    SANDBAR_DELIVERY_LEDGER_DIR: ledger,
    SANDBAR_RUNS_LEDGER: join(ledger, 'runs.jsonl'),
  }
  return { env, key, ledger, projects }
}

const tmp = mkdtempSync(join(tmpdir(), 'wb-lineface-'))
const fx = writeFixture(tmp)
let cleaned = false
function cleanup() { if (!cleaned) { cleaned = true; try { rmSync(tmp, { recursive: true, force: true }) } catch { /* tmp */ } } }
process.on('exit', cleanup)

ok('adapter：parents[4] 锚到 server/engine（导入成功即证；显式再核一次）', () => {
  const out = execFileSync('python3', ['-c',
    `from pathlib import Path; import sys; sys.path.insert(0, ".")
p = Path("${ADAPTER}")
print((p.resolve().parents[4] / "engine").is_dir())`], { cwd: repo, encoding: 'utf8' })
  assert.equal(out.trim(), 'True', 'parents[4] 必须落在 server/（engine 可达）')
})

ok('adapter：waiting/certified/delivered/withdrawn 四态由引擎投影词铸出', () => {
  const doc = runAdapter(fx.env, fx.key)
  assert.equal(doc.ok, true, doc.ok ? '' : String(doc.reason))
  const by = Object.fromEntries(doc.faces.map(f => [f.ticket, f]))
  assert.equal(by['t-wait']?.face, 'waiting')
  assert.equal(by['t-cert']?.face, 'certified')
  assert.equal(by['t-deliv']?.face, 'delivered')
  assert.equal(by['t-wd']?.face, 'withdrawn')
  // no landing row => no face entry (the host layer assembles on_line from the
  // engine's own membership keys, never this adapter)
  assert.ok(!('t-nolanding' in by))
  for (const f of doc.faces) {
    assert.ok(['waiting', 'red_implicated', 'certified', 'delivered', 'withdrawn'].includes(f.face),
      `face word is an engine word: ${f.face}`)
  }
})

ok('adapter：红轮判词 fail-closed——证书在场而 run headers 缺席位=具名拒收', () => {
  // empty runs ledger: the certification cites run-1, absent -> named refusal
  const doc = runAdapter({ ...fx.env, SANDBAR_RUNS_LEDGER: join(fx.ledger, 'absent.jsonl') }, fx.key)
  assert.equal(doc.ok, true, 'adapter itself ran')
  assert.ok(doc.notes.length > 0
    && (/run headers absent/.test(doc.notes[0]) || /run headers ledger is missing/.test(doc.notes[0])),
    `named refusal: ${JSON.stringify(doc.notes)}`)
  assert.ok(!doc.faces.some(f => f.ticket === 't-cert'), '缺席位不得铸 certified（绝不默认绿）')
})

ok('adapter：SANDBAR_RUNS_LEDGER 未设=不是空账默认（同名拒收面）', () => {
  const doc = runAdapter({ ...fx.env, SANDBAR_RUNS_LEDGER: '' }, fx.key)
  assert.ok(doc.notes.some(s => /SANDBAR_RUNS_LEDGER is not set/.test(s)),
    JSON.stringify(doc.notes))
})

ok('adapter：账本畸形行=具名拒收，零 face 冒出', () => {
  writeFileSync(join(fx.ledger, `${fx.key}.jsonl`), 'not-json-at-all\n')
  const doc = runAdapter(fx.env, fx.key)
  assert.equal(doc.ok, false)
  assert.ok(/malformed/.test(String(doc.reason)), String(doc.reason))
})

ok('adapter：声明缺失=具名拒收（LineDeclarationError 面透传）', () => {
  const doc = runAdapter({ ...fx.env, SANDBAR_PROJECTS_DIR: join(tmp, 'nope') }, fx.key)
  assert.equal(doc.ok, false)
  assert.ok(/line declaration missing/.test(String(doc.reason)), String(doc.reason))
})

ok('adapter：畸形 project key=具名拒收；词表=引擎词非编造', () => {
  const doc = runAdapter(fx.env, 'BAD_KEY!')
  assert.equal(doc.ok, false)
  assert.ok(/malformed project key/.test(String(doc.reason)), String(doc.reason))
})

/* ---------------------------------------------- source locks */

ok('行卡源码锁：pill 具名锚点 + 常量文字 + 三行结构 + 十格与 data-visual', () => {
  const card = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
  assert.ok(card.includes('data-line-face={t.line_face}'), 'pill 具名锚点 data-line-face')
  assert.ok(card.includes("data-line-overdue="), 'overdue 锚点')
  assert.ok(card.includes('className="wb-line-pill"'), 'pill 类名（样式作用域）')
  assert.ok(card.includes('linePillText(lineFace)'), '文字走 linePillText 单点（LineOn 常量）')
  assert.ok(card.includes('Array.from({ length: 10 }'), '十格数量锁=10')
  assert.ok(card.includes("data-visual={lit ? 'lit' : 'todo'}"), '格子携带 lit/todo 视觉态')
  assert.ok(card.includes('data-state={state4}')
    && card.includes('className="wb-stage-dots" data-lit={ordering.dotsLit} data-state={state4}'),
    '容器携带票状态（整阵同色相的数据源）')
  // three-line compact card: L2 is the title alone, L3 carries the matrix
  assert.ok(card.includes('wb-card-l3'), '第三行容器在场')
  const l1 = card.slice(card.indexOf('{compact ? ('), card.indexOf(' Board column'))
  const idFirst = l1.indexOf('idSpan')
  const posAt = l1.indexOf('posSpan')
  const pillAt = l1.indexOf('pillSpan')
  assert.ok(idFirst !== -1 && idFirst < posAt && posAt < pillAt, 'L1 顺序：票号 → 位次 → LineOn')
  // the old leading state dot leaves the compact row (board keeps it)
  const compactBranch = card.slice(card.indexOf('{compact ? ('), card.indexOf('// Board column'))
  const compactOnly = compactBranch.slice(0, compactBranch.indexOf(') : ('))
  assert.ok(!compactOnly.includes('wb-card-dot'), 'compact 行首状态点退役')
  assert.ok(card.includes('<span className="wb-card-dot" data-state={state4} />'), '板面状态点保留')
})

ok('模型层源码锁：lineFaceOf 只映射引擎词；未知词不铸面', () => {
  const model = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-list-model.ts'), 'utf8')
  for (const w of ['on_line', 'waiting', 'red_implicated', 'certified', 'delivered', 'withdrawn']) {
    assert.ok(model.includes(`  ${w}: '`), `映射表含引擎词 ${w}`)
  }
  assert.ok(!model.includes("'waiting_overdue'"), 'overdue 是布尔不是状态词')
})

ok('板面源码锁：状态行底退役（.wb-root .wb-card[data-state=*]{background 不复存在）', () => {
  const idx = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  for (const st of ['waiting', 'blocked', 'failed']) {
    assert.ok(!idx.includes(`.wb-root .wb-card[data-state=${st}]{background`),
      `行底规则退役：${st}`)
  }
  // the dim-shade todo cells never fall back to grey on the board either
  assert.ok(idx.includes('.wb-card-lane-dot[data-visual=todo][data-state=waiting]{background:var(--dsw-derive-warn-bg'),
    '板面 todo 格=同色淡档')
})

ok('左栏源码锁：位次标记原样保留（宿主令：不改样式）；冻结横幅在头部不在行上', () => {
  const sb = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
  assert.ok(sb.includes(`.wb-order-pos { flex:none; min-width:14px; text-align:center; font-size:10px; font-weight:600;
  color:var(--dsw-derive-accent,#0969da); background:color-mix(in srgb,var(--dsw-derive-accent,#0969da) 12%,transparent);
  border-radius:4px; padding:0 3px; line-height:14px; }`), '.wb-order-pos CSS 逐字节未动')
  assert.ok(sb.includes('.wb-line-frozen'), '冻结横幅样式在场')
  assert.ok(sb.includes('data-line-frozen="1"'), '冻结横幅具名锚点')
  assert.ok(!sb.includes('{t.line_face'), '行上不渲染线旗标（pill 只在行卡内）')
  // dim todo cells use the -bg token family, never the grey border token
  assert.ok(!/\.wb-stage-dots\[data-state=(active|waiting|blocked|failed)\] \.wb-stage-dot \{ background:var\(--dsw-derive-border/.test(sb),
    'todo 格永不回灰')
})

ok('node.ts 源码锁（仲裁第 1 轮 code-fault 修）：命名错误在场时行一律不富集', () => {
  const host = readFileSync(join(repo, 'server/plugins/workbench/node.ts'), 'utf8')
  const body = host.slice(host.indexOf('function applyLineFace'), host.indexOf('台面：ticket list'))
  // both the engine-face branch and the on_line membership branch sit behind
  // the clean-read guard — a stuck adapter never presents a line state
  assert.ok(body.includes("face.error === '' ? face.faces.get"), '引擎 face 命中分支带 clean-read 守卫')
  assert.ok(body.includes("face.error === '' && tk.lane_version"), 'on_line 成员分支带 clean-read 守卫')
  assert.ok(host.includes('line_face_error: lf.error'), '命名错误原样透传（绝不吞）')
})

console.log(`LINE_FACE_UI ran=${n} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
