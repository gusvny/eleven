/**
 * smoke/stage-parts.mjs —— t260828-01「执行主体 parts 徽标」冒烟（observability 立项）。
 *
 * 直跑：node smoke/stage-parts.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. src/shared/parts.ts 纯函数：组合拼接（agent+script→🤖⚙️、human+script→👤⚙️）、
 *      undefined/空数组 →「—」软降级、未知枚举值 → ❓ 兜底且悬停行点名、不抛错。
 *   B. /suyou-workbench/api/wf/workflows 路由端到端（真实仓库 repo，无 stub）：
 *      五模版全部 stage 带非空 parts 透出（链路：STAGES→yaml→workflow.py
 *      _brief→路由），且 stage 链/parts 与 Python 侧 STAGES 代码真源逐条比对
 *      （独立基线，不与路由同源；加 stage 不会假红）。
 *   B2. workflow.py validate（真实代码拷进 tmp 仓读自制 yaml）：非法 parts → 非零
 *      退出+大声报错点名；无 parts 旧 yaml → 照常加载、_brief 透出 parts=[]
 *      （数据层软降级，「—」由前端补）。
 *   C. 防穿口径说明：本单零新增端点（徽标数据搭既有 workflows 列表），无新路径面；
 *      agent-live 既有 4XX 防穿用例由 smoke/agent-live.mjs 回归覆盖，本文件不重复。
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
const REPO = resolve(HERE, '..', '..', '..', '..')  // <repo>/server/dsh/workbench/smoke/

const tmp = await mkdtemp(join(tmpdir(), 'wb-parts-'))
try {
  /* ------------------------------------------------------------ A. 纯函数 */
  section('A parts.ts 纯函数（拼接/降级/未知值）')
  {
    ok(partsIcons(['agent']) === '🤖', 'agent → 🤖')
    ok(partsIcons(['agent', 'script']) === '🤖⚙️', 'implement 组合态 → 🤖⚙️ 直接拼接')
    ok(partsIcons(['human', 'script']) === '👤⚙️', 'merge 组合态 → 👤⚙️')
    ok(partsIcons(['script']) === '⚙️', 'merge_check 纯脚本 → ⚙️')
    ok(partsIcons(undefined) === '—', '无 parts 字段（旧数据）→ — 软降级')
    ok(partsIcons([]) === '—', '空数组 → — 软降级')
    ok(partsIcons(['agent', 'robot']) === '🤖❓', '未知枚举值 → ❓ 兜底不炸')

    ok(partsTitle(['agent', 'script']) === `执行主体：🤖 ${PART_LABEL.agent} + ⚙️ ${PART_LABEL.script}（静态声明；动态真源=Temporal history）`,
      '悬停一行说明（组合态）')
    ok(partsTitle(undefined).includes('旧数据无 parts'), '无 parts 悬停行说明降级口径')
    ok(partsTitle(['robot']).includes('未知执行主体 robot'), '未知值在悬停行点名')
    // 三枚图标/标签与枚举一一对应（防漏枚举分支）
    ok(PART_ICON.agent === '🤖' && PART_ICON.script === '⚙️' && PART_ICON.human === '👤',
      '图标表 agent🤖/script⚙️/human👤')
  }

  /* ------------------------------------------------------------ B. workflows 路由透出 */
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
    const route = routes.find(r => r.kind === 'exact' && r.path === '/suyou-workbench/api/wf/workflows')
    ok(route !== undefined, 'workflows exact 路由已挂')

    const res = {
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    }
    const req = { url: '/suyou-workbench/api/wf/workflows', method: 'GET', async *[Symbol.asyncIterator]() {} }
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

    // 与代码真源逐条比对（t260829-04）：基线=Python 侧 STAGES 类属性（真源=代码），
    // 与 API 路由不同源——不加硬编码 stage 总数，模版加段后本断言自动跟随，不会假红。
    // temporalio 只有主库/泳道 venv 装了：解释器候选探测（同 replay_check.py 口径）。
    const POC = join(REPO, 'server', 'dsh', 'temporal-poc')
    const pyCode = `
import json, sys
sys.path.insert(0, ${JSON.stringify(POC)})
from workflows_v2 import TEMPLATE_CLASSES
print(json.dumps({t: [{"id": s.id, "parts": list(s.parts)} for s in c.STAGES] for t, c in TEMPLATE_CLASSES.items()}))
`
    const pyCandidates = ['python3',
      join(REPO, 'server', 'dsh', 'temporal-poc', '.venv', 'bin', 'python'),
      resolve(REPO, '..', '..', 'server', 'dsh', 'temporal-poc', '.venv', 'bin', 'python'),
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

    // 负例：真实 workflow.py（拷进 tmp 仓）读非法 parts 的 yaml → 非零退出 + 大声报错；
    // 无 parts 的旧 yaml → 照常加载（数据层软降级，「—」由前端补）。
    section('B2 workflow.py validate：非法 parts 大声报错 / 无 parts 放行')
    await mkdir(join(tmp, 'repo', 'server', 'tools'), { recursive: true })
    await mkdir(join(tmp, 'repo', 'server', 'dsh', 'workflows'), { recursive: true })
    await writeFile(join(tmp, 'repo', 'server', 'tools', 'workflow.py'),
      await readFile(join(REPO, 'server', 'tools', 'workflow.py'), 'utf8'), 'utf8')
    await writeFile(join(tmp, 'repo', 'server', 'dsh', 'workflows', 'bad.yaml'), `id: bad
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
    await writeFile(join(tmp, 'repo', 'server', 'dsh', 'workflows', 'old.yaml'), `id: old
name: "旧模版（无 parts）"
lane: main
description: "smoke 旧数据形态"
stages:
  - id: a
    role: developer
    name: "甲"
`, 'utf8')
    // bad.yaml 必须在：非零退出且 stderr/stdout 点名非法值
    let r = await execFileP('python3', [join(tmp, 'repo', 'server', 'tools', 'workflow.py')])
      .then(() => ({ rc: 0, out: '' }), (e) => ({ rc: e.code ?? 1, out: String(e.stderr ?? '') + String(e.stdout ?? '') }))
    ok(r.rc !== 0 && r.out.includes('非法值') && r.out.includes('robot'),
      '非法 parts（robot）→ 非零退出 + 大声报错点名')
    // 只留 old.yaml：无 parts 旧数据照常 list，stages 带 parts: []（_brief 兜底）
    await rm(join(tmp, 'repo', 'server', 'dsh', 'workflows', 'bad.yaml'))
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
