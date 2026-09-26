/**
 * smoke/stage-parts.mjs — smoke for t260828-01 「actor parts badges」 (observability kickoff).
 *
 * Run: node smoke/stage-parts.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. src/shared/parts.ts pure functions: combination concatenation (agent+script -> 🤖⚙️,
 *      human+script -> 👤⚙️), undefined/empty array -> 「—」 soft fallback, unknown enum value
 *      -> ❓ fallback plus a hover line naming it, never throws.
 *   B. /sandbar-workbench/api/wf/workflows route end-to-end (real repo, no stub): all five
 *      templates expose every stage with a non-empty parts list (chain: STAGES -> yaml ->
 *      workflow.py _brief -> route), and the stage chain / parts are compared item by item
 *      against the Python-side STAGES code source of truth (an independent baseline, not
 *      derived from the route, so adding a stage cannot turn this falsely red).
 *   B2. workflow.py validate (real code copied into a tmp repo reading a hand-made yaml):
 *      illegal parts -> non-zero exit + loud error naming the value; legacy yaml without
 *      parts -> loads as usual and _brief exposes parts=[] (data-layer soft fallback,
 *      the frontend renders 「—」).
 *   C. Traversal-guard scope note: this ticket adds zero new endpoints (badge data rides the
 *      existing workflows list), so there is no new path surface; agent-live's existing 4XX
 *      traversal-guard cases are regression-covered by smoke/agent-live.mjs, not repeated here.
 */

import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { PART_ICON, PART_LABEL, partsIcons, partsTitle } from '../src/shared/parts.ts'
import { apply } from '../node.ts'

const execFileP = promisify(execFile)

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')  // <repo>/server/plugins/workbench/smoke/

const tmp = await mkdtemp(join(tmpdir(), 'wb-parts-'))
try {
  /* ------------------------------------------------------------ A. pure functions */
  section('A parts.ts 纯函数（拼接/降级/未知值）')
  {
    ok(partsIcons(['agent']) === '🤖', 'agent → 🤖')
    ok(partsIcons(['agent', 'script']) === '🤖⚙️', 'implement 组合态 → 🤖⚙️ 直接拼接')
    ok(partsIcons(['human', 'script']) === '👤⚙️', 'merge 组合态 → 👤⚙️')
    ok(partsIcons(['script']) === '⚙️', 'merge_check 纯脚本 → ⚙️')
    ok(partsIcons(undefined) === '—', '无 parts 字段（旧数据）→ — 软降级')
    ok(partsIcons([]) === '—', '空数组 → — 软降级')
    ok(partsIcons(['agent', 'robot']) === '🤖❓', '未知枚举值 → ❓ 兜底不炸')

    ok(partsTitle(['agent', 'script']) === `Executed by: 🤖 ${PART_LABEL.agent} + ⚙️ ${PART_LABEL.script} (static declaration; dynamic source of truth = Temporal history)`,
      '悬停一行说明（组合态）')
    ok(partsTitle(undefined).includes('no static parts declaration'), '无 parts 悬停行说明降级口径')
    ok(partsTitle(['robot']).includes('unknown executor robot'), '未知值在悬停行点名')
    // the three icons/labels map 1:1 onto the enum (guards against a missed enum branch)
    ok(PART_ICON.agent === '🤖' && PART_ICON.script === '⚙️' && PART_ICON.human === '👤',
      '图标表 agent🤖/script⚙️/human👤')
  }

  /* ------------------------------------------------------------ B. workflows route exposure */
  section('B /api/wf/workflows 透出 parts（真实链路，无 stub）')
  {
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo: REPO })
    const route = routes.find(r => r.kind === 'exact' && r.path === '/sandbar-workbench/api/wf/workflows')
    ok(route !== undefined, 'workflows exact 路由已挂')

    const res = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    const req = { url: '/sandbar-workbench/api/wf/workflows', method: 'GET', async *[Symbol.asyncIterator]() {} }
    await route.handler(req, res)
    ok(res.status === 200 && res.body.ok === true, 'GET 200')
    const wfs = res.body.result
    ok(Array.isArray(wfs) && wfs.length === 5, '五模版（dev-lane/content-pipeline/proofread/regression/cleanup）')
    let total = 0
    let missing = []
    const byId = Object.fromEntries(wfs.map(w => [w.id, w]))
    for (const w of wfs) {
      for (const s of w.stages) {
        total++
        if (!Array.isArray(s.parts) || s.parts.length === 0) missing.push(`${w.id}.${s.id}`)
      }
    }
    ok(missing.length === 0, `全部 ${total} 个 stage parts 非空透出${missing.length ? '，缺：' + missing.join('、') : ''}`)

    // Item-by-item comparison against the code source of truth (t260829-04): the baseline is
    // the Python-side STAGES class attributes (source of truth = code), independent of the API
    // route — no hardcoded stage total, so the assertion follows automatically when a template
    // gains a stage and cannot turn falsely red.
    // temporalio is only installed in the main-repo/worklane venvs: probe interpreter
    // candidates (same rule as replay_check.py).
    const POC = join(REPO, 'server', 'engine')
    const pyCode = `
import json, sys
sys.path.insert(0, ${JSON.stringify(POC)})
from workflows_v2 import TEMPLATE_CLASSES
print(json.dumps({t: [{"id": s.id, "parts": list(s.parts)} for s in c.STAGES] for t, c in TEMPLATE_CLASSES.items()}))
`
    const pyCandidates = ['python3',
      join(REPO, 'server', 'engine', '.venv', 'bin', 'python'),
      resolve(REPO, '..', '..', 'server', 'engine', '.venv', 'bin', 'python'),
    ]
    let baseline = null
    for (const py of pyCandidates) {
      baseline = await execFileP(py, ['-c', pyCode]).then(o => JSON.parse(o.stdout), () => null)
      if (baseline) break
    }
    ok(baseline !== null, 'Python 侧 STAGES 基线可取（真源=代码，独立于路由）')
    if (baseline) {
      const diffs = []
      for (const w of wfs) {
        const base = baseline[w.id]
        if (!Array.isArray(base)) { diffs.push(`${w.id}: 基线缺失`); continue }
        if (JSON.stringify(w.stages.map(s => s.id)) !== JSON.stringify(base.map(s => s.id)))
          diffs.push(`${w.id}: stage 链不一致（api=[${w.stages.map(s => s.id)}] 基线=[${base.map(s => s.id)}]）`)
        for (let i = 0; i < Math.min(w.stages.length, base.length); i++) {
          if (JSON.stringify(w.stages[i].parts ?? []) !== JSON.stringify(base[i].parts))
            diffs.push(`${w.id}.${base[i].id}: parts 不一致（api=${JSON.stringify(w.stages[i].parts)} 基线=${JSON.stringify(base[i].parts)}）`)
        }
      }
      ok(diffs.length === 0, `五模版 stage 链与 parts 全部与 STAGES 代码真源一致${diffs.length ? '；差异：' + diffs.join('；') : ''}`)
    }
    const dl = byId['dev-lane']
    const impl = dl?.stages.find(s => s.id === 'implement')
    const merge = dl?.stages.find(s => s.id === 'merge')
    ok(impl && impl.parts.join('+') === 'agent+script', 'implement=agent+script（验收口径）')
    ok(merge && merge.parts.join('+') === 'human+script', 'merge=human+script（验收口径）')
    ok(dl?.stages.find(s => s.id === 'merge_check')?.parts.join('') === 'script', 'merge_check=script')

    // Negative case: the real workflow.py (copied into the tmp repo) reading a yaml with
    // illegal parts -> non-zero exit + loud error; legacy yaml without parts -> loads as
    // usual (data-layer soft fallback, the frontend renders 「—」).
    section('B2 workflow.py validate：非法 parts 大声报错 / 无 parts 放行')
    await mkdir(join(tmp, 'repo', 'server', 'tools'), { recursive: true })
    await mkdir(join(tmp, 'repo', 'server', 'workflows'), { recursive: true })
    await writeFile(join(tmp, 'repo', 'server', 'tools', 'workflow.py'),
      await readFile(join(REPO, 'server', 'tools', 'workflow.py'), 'utf8'), 'utf8')
    await writeFile(join(tmp, 'repo', 'server', 'workflows', 'bad.yaml'), `id: bad
name: "坏模版"
lane: main
description: "smoke 负例"
stages:
  - id: a
    role: developer
    name: "甲"
    parts:
      - agent
      - robot
`, 'utf8')
    await writeFile(join(tmp, 'repo', 'server', 'workflows', 'old.yaml'), `id: old
name: "旧模版（无 parts）"
lane: main
description: "smoke 旧数据形态"
stages:
  - id: a
    role: developer
    name: "甲"
`, 'utf8')
    // bad.yaml must still be present: non-zero exit plus stderr/stdout naming the illegal value
    let r = await execFileP('python3', [join(tmp, 'repo', 'server', 'tools', 'workflow.py')])
      .then(() => ({ rc: 0, out: '' }), (e) => ({ rc: e.code ?? 1, out: String(e.stderr ?? '') + String(e.stdout ?? '') }))
    ok(r.rc !== 0 && r.out.includes('非法值') && r.out.includes('robot'),
      '非法 parts（robot）→ 非零退出 + 大声报错点名')
    // only old.yaml left: legacy data without parts still lists, stages carry parts: [] (_brief fallback)
    await rm(join(tmp, 'repo', 'server', 'workflows', 'bad.yaml'))
    r = await execFileP('python3', [join(tmp, 'repo', 'server', 'tools', 'workflow.py')])
      .then((o) => ({ rc: 0, out: o.stdout }), (e) => ({ rc: e.code ?? 1, out: String(e.stderr ?? '') }))
    ok(r.rc === 0, '无 parts 旧模版 → 正常加载')
    const listed = JSON.parse(r.out)
    ok(listed.workflows?.[0]?.stages?.[0]?.parts?.length === 0, '旧数据 _brief 透出 parts=[]（前端显 —）')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
