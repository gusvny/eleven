/**
 * smoke/epic-next.mjs — host half-smoke for the epic "continue" button (t260827-02).
 *
 * Run: node smoke/epic-next.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers:
 *   A. src/host/epic-next.ts pure functions:
 *      parseMiniYaml (nested mappings / whole-line and trailing comments / bare tokens);
 *      modelRouteFromYaml (role hit / falls to default / all missing -> null; a role with
 *      tasks does not mistakenly read the task-split layer); buildSuggestPrompt (must
 *      contain the full epic text / ticket summary / template list / result file path);
 *      validateSuggestion (compliant passes / status!=ok passes reason through / hallucinated
 *      template id rejected / empty title rejected / non-object rejected).
 *   B. Route (node.ts apply + mock webServer/req/res + stub admin.py, same pattern as epics.mjs):
 *      B1 STUB mode (SANDBAR_EPIC_NEXT_STUB=1) full chain: POST starts -> job_id+running;
 *      poll -> done with a compliant suggestion shape; prompt.md on disk containing the epic
 *      text / template list / ticket summary; POST again for an already-done code -> new
 *      job_id; after 6 concurrent jobs the directory keeps at most 5.
 *      B2 fake agent with real spawn (SANDBAR_AGENT_CMD=node <fixture>): POST -> running;
 *      a second POST while running -> reuses the same job_id; poll to done gets the
 *      suggestion the fake agent wrote.
 *      B3 fake agent writes a non-compliant result (hallucinated template id) -> poll ->
 *      failed with a human-readable reason.
 *      B4 error paths: malformed code 400 / unknown code 404 / unknown jobId 404 /
 *      jobId-code mismatch 404 / GET on the start path 405 / PUT 405 /
 *      workflow list failure -> POST 502 retryable.
 *      B5 workflow list failure -> 502 retryable.
 *      B6 STUB failure variants (t260828-03, direct import of startSuggestJob/pollSuggestJob):
 *      B6a invalid_json: file exists but the JSON is illegal (reproduces the LLM illegal
 *      \- escape) -> first poll still running (records the file fingerprint) -> second
 *      poll fails fast with a reason that says "not valid JSON" + parse summary, does not
 *      say "no output", and the dummy process is reaped;
 *      B6b never_write + SANDBAR_EPIC_NEXT_TIMEOUT_MS=500: no file -> not misjudged ->
 *      timeout failed "terminated", dummy process reaped.
 *      B7 real spawn process lifecycle (t260828-03): B7a fake agent writes illegal JSON then
 *      exits -> poll fails fast immediately (process already gone, no two-round stability
 *      wait); B7b fake agent writes a compliant result then hangs (known stock-headless
 *      behavior) -> done and the process is killed (no leak on the done path).
 *   C. src/client/epics-model.ts pure functions: composeSuggestedBody (attribution line
 *      injection / empty body tolerance).
 */

import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  buildSuggestPrompt, modelRouteFromYaml, parseMiniYaml, pollSuggestJob, resolveEpicNextDir,
  startSuggestJob, validateSuggestion,
} from '../src/host/epic-next.ts'
import { composeSuggestedBody, epicCreateNote } from '../src/client/epics-model.ts'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
const sleep = (ms) => new Promise(r => setTimeout(r, ms))

const EPIC_MD = `# 立项单：demo-epic

| 字段 | 值 |
| --- | --- |
| 代号 | \`demo-epic\` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-08-27 |

## 目标

做个示范。
`

/** stub admin.py: ticket list --epic returns 2 rows; workflow list returns 2 templates. */
const ADMIN_STUB = `import json, sys
args = json.loads(sys.argv[3]) if len(sys.argv) >= 4 else {}
tool = sys.argv[2] if len(sys.argv) >= 3 else ''
if tool == 'ticket' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"count": 1, "tickets": [
        {"id": "t260827-01", "title": "前置工单", "status": "closed",
         "stage": "settled", "stage_state": "done", "epic": "demo-epic"}
    ]}}))
    sys.exit(0)
if tool == 'workflow' and args.get('op') == 'list':
    print(json.dumps({"ok": True, "result": {"workflows": [
        {"id": "dev-lane", "name": "开发泳道"},
        {"id": "regression", "name": "回归验证"}
    ]}}))
    sys.exit(0)
print(json.dumps({"ok": False, "error": "stub unsupported"}))
sys.exit(1)
`

/** stub with workflow list failing (POST should return 502 retryable). */
const ADMIN_STUB_NO_WF = `import json, sys
print(json.dumps({"ok": False, "error": "temporal unreachable: connection refused"}))
sys.exit(1)
`

/**
 * Fake agent (for the real-spawn path): parses the result file path out of the last argv
 * (the assignment instruction), waits 600ms, writes the given payload, exits.
 * Usage: node fake-agent.mjs '<payload JSON>' <prompt>
 */
const FAKE_AGENT = `import { writeFileSync } from 'node:fs'
const payload = process.argv[2]
const prompt = process.argv[process.argv.length - 1]
const m = /结论写入结果文件：(\\S+)/.exec(prompt)
if (!m) { console.error('no result path in prompt'); process.exit(2) }
setTimeout(() => {
  writeFileSync(m[1], payload + '\\n', 'utf8')
}, 600)
`

/**
 * Fake agent variant (t260828-03): writes the result file then hangs without exiting —
 * simulates the known stock-headless "finishes work but never exits" behavior, verifying
 * the done terminal kills the process (process-leak regression).
 * Usage: same as above.
 */
const FAKE_AGENT_LINGER = `import { writeFileSync } from 'node:fs'
const payload = process.argv[2]
const prompt = process.argv[process.argv.length - 1]
const m = /结论写入结果文件：(\\S+)/.exec(prompt)
if (!m) { console.error('no result path in prompt'); process.exit(2) }
setTimeout(() => {
  writeFileSync(m[1], payload + '\\n', 'utf8')
}, 300)
setTimeout(() => {}, 600000)
`

const tmp = await mkdtemp(join(tmpdir(), 'wb-epic-next-'))
const ENV_KEYS = ['SANDBAR_EPIC_NEXT_DIR', 'SANDBAR_EPIC_NEXT_STUB', 'SANDBAR_EPIC_NEXT_TIMEOUT_MS', 'SANDBAR_AGENT_CMD', 'DSH_HOME']
const savedEnv = Object.fromEntries(ENV_KEYS.map(k => [k, process.env[k]]))
try {
  /* ------------------------------------------------------------ A. Pure functions */
  section('A epic-next 纯函数')

  {
    const table = parseMiniYaml(`# 注释行
default:   # 行尾注释
  provider: zai
  model: glm-5.2

roles:
  integration:
    provider: zai
    model: glm-5.3
  product-operation:
    provider: kimi-coding
    model: k3
    tasks:
      proofread:
        provider: zai
        model: glm-5.2
`)
    ok(table.default?.provider === 'zai' && table.roles?.integration?.model === 'glm-5.3',
      'parseMiniYaml：嵌套映射 + 注释剥除')
    ok(table.roles?.['product-operation']?.tasks?.proofread?.provider === 'zai',
      'parseMiniYaml：三层嵌套（tasks 分工层）')
    ok(modelRouteFromYaml(`default:\n  provider: zai\n  model: glm-5.2\nroles:\n  integration:\n    provider: zai\n    model: glm-5.3\n`, 'integration')?.model === 'glm-5.3',
      'modelRouteFromYaml：角色级命中')
    const fb = modelRouteFromYaml(`default:\n  provider: zai\n  model: glm-5.2\nroles:\n  developer:\n    provider: kimi-coding\n    model: k3\n`, 'integration')
    ok(fb?.provider === 'zai' && fb?.model === 'glm-5.2', 'modelRouteFromYaml：角色缺条目 → 落 default')
    ok(modelRouteFromYaml('roles:\n  developer:\n    provider: kimi-coding\n    model: k3\n', 'integration') === null,
      'modelRouteFromYaml：角色与 default 全缺 → null（不硬失败）')
    const notTasks = modelRouteFromYaml(`default:\n  provider: zai\n  model: glm-5.2\nroles:\n  product-operation:\n    tasks:\n      proofread:\n        provider: zai\n        model: glm-5.2\n`, 'product-operation')
    ok(notTasks?.provider === 'zai' && notTasks?.model === 'glm-5.2',
      'modelRouteFromYaml：角色只有 tasks 层时不误取分工值（provider/model 非标量则跳过）')
  }

  {
    const prompt = buildSuggestPrompt({
      code: 'demo-epic', epicTitle: 'demo', epicMarkdown: EPIC_MD,
      ticketsSummary: '[{"id":"t260827-01"}]',
      workflows: [{ id: 'dev-lane', name: '开发泳道' }],
      resultPath: '/tmp/x/result.json',
    })
    ok(prompt.includes('做个示范。') && prompt.includes('t260827-01')
      && prompt.includes('dev-lane：开发泳道') && prompt.includes('结论写入结果文件：/tmp/x/result.json'),
      'buildSuggestPrompt：立项全文/工单汇总/模板清单/结果路径全内联')
    ok(prompt.includes('不得发明') && prompt.includes('不创建、不修改任何文件'),
      'buildSuggestPrompt：只读与防幻觉模板约束写进指令')
  }

  {
    const ids = ['dev-lane', 'regression']
    const good = validateSuggestion({ status: 'ok', workflow: 'dev-lane', title: '下一步', body: 'b', rationale: 'r' }, ids)
    ok(good.ok === true && good.suggestion.workflow === 'dev-lane' && good.suggestion.title === '下一步',
      'validateSuggestion：合规建议放行')
    ok(validateSuggestion({ status: 'failed', reason: '立项已收尾' }, ids).error?.includes('立项已收尾'),
      'validateSuggestion：agent 自报 failed → 透传 reason')
    ok(validateSuggestion({ status: 'ok', workflow: 'made-up', title: 'x' }, ids).error?.includes('不在可用清单内'),
      'validateSuggestion：幻觉模板 id 拒收')
    ok(validateSuggestion({ status: 'ok', workflow: 'dev-lane', title: '  ' }, ids).error?.includes('缺工单标题'),
      'validateSuggestion：空 title 拒收')
    ok(validateSuggestion('not-an-object', ids).ok === false
      && validateSuggestion(null, ids).ok === false,
      'validateSuggestion：非对象/空值拒收不抛')
  }

  /* ------------------------------------------------------------ B. Route */
  section('B /sandbar-workbench/api/epics/<code>/suggest-next 路由')
  {
    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET', body = '') => ({
      url, method,
      async *[Symbol.asyncIterator]() { if (body) yield Buffer.from(body) },
    })
    const setup = (repo) => {
      const routes = []
      const ws = { register: (r) => { routes.push(r); return () => {} } }
      const ctx = {
        effect: (fn) => { fn() },
        logger: { info() {}, warn() {} },
        get: (k) => (k === 'webServer' ? ws : undefined),
        on: () => () => {},
      }
      apply(ctx, { repo })
      return routes.find(r => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/epics')
    }
    const call = async (handler, url, method = 'GET') => {
      const res = mockRes()
      await handler.handler(mockReq(url, method), res)
      return res
    }
    const mkRepo = async (name, adminSrc, epicNames = ['demo-epic']) => {
      const repo = join(tmp, name)
      await mkdir(join(repo, 'notes', 'epics'), { recursive: true })
      for (const n of epicNames) {
        await writeFile(join(repo, 'notes', 'epics', `${n}.md`), EPIC_MD.replaceAll('demo-epic', n), 'utf8')
      }
      await mkdir(join(repo, 'server'), { recursive: true })
      await writeFile(join(repo, 'server', 'admin.py'), adminSrc, 'utf8')
      return repo
    }

    process.env.SANDBAR_EPIC_NEXT_DIR = join(tmp, 'jobs')
    process.env.DSH_HOME = join(tmp, 'dsh-home')  // empty dir: the profile/creds/settings copies are all no-ops
    await mkdir(process.env.DSH_HOME, { recursive: true })

    /* --- B1 STUB mode full chain --- */
    process.env.SANDBAR_EPIC_NEXT_STUB = '1'
    const repoB = await mkRepo('repo-b', ADMIN_STUB, ['demo-epic', 'demo-epic-2'])
    const hB = setup(repoB)
    ok(hB !== undefined, 'epics prefix 路由已挂')

    let r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
    ok(r.status === 200 && r.body.ok === true && typeof r.body.result.job_id === 'string'
      && r.body.result.state === 'running' && r.body.result.reused === false,
      'POST 启动 → 200 job_id + running')
    const jobId = r.body.result.job_id

    r = await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${jobId}`)
    ok(r.status === 200 && r.body.result.state === 'done'
      && r.body.result.suggestion?.workflow === 'dev-lane'
      && typeof r.body.result.suggestion?.title === 'string',
      'STUB 轮询 → done，建议形状合规（模板=清单第一个）')

    // t260828-03: the done terminal must reap the process (the dummy process hung by the stub should already be killed — process-leak regression assertion)
    const doneJob = await pollSuggestJob(jobId)
    ok(doneJob?.proc?.killed === true, 'STUB done 终态回收 agent 进程（proc.killed）')

    const promptMd = await readFile(join(process.env.SANDBAR_EPIC_NEXT_DIR, jobId, 'prompt.md'), 'utf8')
    ok(promptMd.includes('做个示范。') && promptMd.includes('dev-lane：开发泳道')
      && promptMd.includes('t260827-01') && promptMd.includes('result.json'),
      'prompt.md 落盘：立项全文/模板清单/工单汇总/结果路径齐备（可审计）')

    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
    ok(r.status === 200 && r.body.result.job_id !== jobId && r.body.result.reused === false,
      '已完成的 code 再 POST → 起新 job（复用只限进行中）')
    const jobIdB = r.body.result.job_id

    // A STUB job only counts as done after a poll (the registry state flips only when a
    // poll happens) — posting again without polling hits "reuse while running"; that is a
    // feature, not a bug.
    r = await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${jobIdB}`)
    ok(r.body.result.state === 'done', 'STUB job 轮询后状态翻转为 done')

    // Start 4 more jobs (each polled to done; 6 total with the above) -> directory keeps at most 5
    for (let i = 0; i < 4; i++) {
      const p = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
      await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${p.body.result.job_id}`)
    }
    const shape = /^demo-epic-[0-9a-z]+-[0-9a-f]{6}$/
    const dirs = (await readdir(process.env.SANDBAR_EPIC_NEXT_DIR, { withFileTypes: true }))
      .filter(e => e.isDirectory() && shape.test(e.name))
    ok(dirs.length === 5, `job 目录每 code 保留 5 份（实际 ${dirs.length}；demo-epic-2 的不误清）`)

    /* --- B2 fake agent, real spawn: running reuse + poll to done --- */
    delete process.env.SANDBAR_EPIC_NEXT_STUB
    const fakeScript = join(tmp, 'fake-agent.mjs')
    await writeFile(fakeScript, FAKE_AGENT, 'utf8')
    const payload = JSON.stringify({ status: 'ok', workflow: 'regression', title: 'fake 建议标题', body: 'b', rationale: 'r' })
    process.env.SANDBAR_AGENT_CMD = `${process.execPath} ${fakeScript} '${payload}'`

    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic-2/suggest-next', 'POST')
    ok(r.status === 200 && r.body.result.state === 'running', '假 agent：POST → running（真 spawn）')
    const jobId2 = r.body.result.job_id
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic-2/suggest-next', 'POST')
    ok(r.status === 200 && r.body.result.job_id === jobId2 && r.body.result.reused === true,
      '进行中重复 POST → 复用同一 job（不重复起 agent）')

    let final = null
    for (let i = 0; i < 20; i++) {
      await sleep(300)
      const p = await call(hB, `/sandbar-workbench/api/epics/demo-epic-2/suggest-next/${jobId2}`)
      if (p.body?.result?.state !== 'running') { final = p; break }
    }
    ok(final !== null && final.status === 200 && final.body.result.state === 'done'
      && final.body.result.suggestion?.workflow === 'regression'
      && final.body.result.suggestion?.title === 'fake 建议标题',
      '假 agent 轮询 → done 拿到它写的建议（spawn/轮询/校验全链路）')

    /* --- B3 fake agent writes a non-compliant result -> failed --- */
    const badPayload = JSON.stringify({ status: 'ok', workflow: 'made-up-template', title: 'x' })
    process.env.SANDBAR_AGENT_CMD = `${process.execPath} ${fakeScript} '${badPayload}'`
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
    const jobId3 = r.body.result.job_id
    let final3 = null
    for (let i = 0; i < 20; i++) {
      await sleep(300)
      const p = await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${jobId3}`)
      if (p.body?.result?.state !== 'running') { final3 = p; break }
    }
    ok(final3 !== null && final3.body.result.state === 'failed'
      && String(final3.body.result.reason).includes('不在可用清单内'),
      '幻觉模板 id → failed + 人话 reason（validateSuggestion 闸生效）')

    /* --- B4 error paths --- */
    delete process.env.SANDBAR_AGENT_CMD
    process.env.SANDBAR_EPIC_NEXT_STUB = '1'
    r = await call(hB, '/sandbar-workbench/api/epics/Bad-Code/suggest-next', 'POST')
    ok(r.status === 400, 'POST 坏形状 code → 400')
    r = await call(hB, '/sandbar-workbench/api/epics/no-such-epic/suggest-next', 'POST')
    ok(r.status === 404, 'POST 不存在 code → 404')
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next/j00000000')
    ok(r.status === 404, '未知 jobId → 404 人话')
    r = await call(hB, `/sandbar-workbench/api/epics/demo-epic-2/suggest-next/${jobId}`)
    ok(r.status === 404, 'jobId 与 code 不匹配 → 404（防跨立项串读）')
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next/not!valid')
    ok(r.status === 400, 'jobId 形状非法 → 400')
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'GET')
    ok(r.status === 405, 'GET 启动路径 → 405')
    r = await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${jobId}`, 'PUT')
    ok(r.status === 405, 'PUT 轮询路径 → 405')
    r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/bogus-op', 'POST')
    ok(r.status === 405, '既有未知子路径 POST → 405 回归不变')

    /* --- B5 workflow list failure -> 502 retryable --- */
    const repoC = await mkRepo('repo-c', ADMIN_STUB_NO_WF)
    const hC = setup(repoC)
    r = await call(hC, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
    ok(r.status === 502 && String(r.body.error).includes('模板清单查询失败'),
      '模板清单拿不到 → 502 人话（不放行无校验的建议）')

    /* --- B6 STUB failure variants (t260828-03; direct import, strongest determinism) --- */
    section('B6 STUB 失败变体：invalid_json / never_write')
    const directInput = {
      repo: repoB, code: 'demo-epic', epicTitle: 'demo', epicMarkdown: EPIC_MD,
      ticketsSummary: '[]', workflows: [{ id: 'dev-lane', name: '开发泳道' }],
    }
    {
      // B6a invalid_json: file exists but the JSON is illegal -> fail-fast within two polls (no 10-minute timeout wait)
      delete process.env.SANDBAR_AGENT_CMD
      process.env.SANDBAR_EPIC_NEXT_STUB = 'invalid_json'
      const j1 = await startSuggestJob(directInput)
      const p1 = await pollSuggestJob(j1.jobId)
      ok(p1?.state === 'running',
        'invalid_json 第 1 轮 poll：仍 running（记录文件指纹，不误判仍在写）')
      const p2 = await pollSuggestJob(j1.jobId)
      ok(p2?.state === 'failed' && String(p2.reason).includes('不是合法 JSON'),
        'invalid_json 第 2 轮 poll：文件连续两轮未变 → fail-fast failed，reason 明说不是合法 JSON')
      ok(String(p2?.reason).length > 0 && !String(p2?.reason).includes('未产出'),
        'invalid_json reason 不再误说「未产出」（260828 文案写反修复）')
      ok(p2?.proc?.killed === true, 'invalid_json fail-fast 终态回收哑进程')
    }
    {
      // B6b never_write: file never appears -> no fail-fast misjudgment, timeout backstop + reap
      process.env.SANDBAR_EPIC_NEXT_STUB = 'never_write'
      process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS = '500'
      const j2 = await startSuggestJob(directInput)
      const q1 = await pollSuggestJob(j2.jobId)
      ok(q1?.state === 'running', 'never_write 无文件：仍 running（不误判为非法 JSON）')
      await sleep(600)
      const q2 = await pollSuggestJob(j2.jobId)
      ok(q2?.state === 'failed' && String(q2.reason).includes('已终止'),
        'never_write 超时 → failed「已终止」（时限 env 覆盖生效）')
      ok(q2?.proc?.killed === true, 'never_write 超时终态回收哑进程')
      delete process.env.SANDBAR_EPIC_NEXT_TIMEOUT_MS
    }

    /* --- B7 real spawn process lifecycle (t260828-03) --- */
    section('B7 真 spawn：invalid-JSON 自退 fail-fast / 合规结果长挂回收')
    delete process.env.SANDBAR_EPIC_NEXT_STUB
    {
      // B7a reproduces the 260828 incident: writes illegal JSON (\- escape) then exits -> poll fails fast immediately
      const badJsonPayload = '{"status":"ok","workflow":"dev-lane","title":"bad\\-dash","body":"b"}'
      process.env.SANDBAR_AGENT_CMD = `${process.execPath} ${fakeScript} '${badJsonPayload}'`
      r = await call(hB, '/sandbar-workbench/api/epics/demo-epic-2/suggest-next', 'POST')
      const jobId4 = r.body.result.job_id
      let final4 = null
      for (let i = 0; i < 25; i++) {
        await sleep(200)
        const p = await call(hB, `/sandbar-workbench/api/epics/demo-epic-2/suggest-next/${jobId4}`)
        if (p.body?.result?.state !== 'running') { final4 = p; break }
      }
      ok(final4 !== null && final4.body.result.state === 'failed'
        && String(final4.body.result.reason).includes('不是合法 JSON')
        && !String(final4.body.result.reason).includes('未产出'),
        '假 agent 写非法 JSON 后自退 → 立即 fail-fast（进程已退出不等两轮；reason 明说不是合法 JSON）')
    }
    {
      // B7b fake agent writes a compliant result then hangs -> done and the process is killed (done-path leak fix)
      const lingerScript = join(tmp, 'fake-agent-linger.mjs')
      await writeFile(lingerScript, FAKE_AGENT_LINGER, 'utf8')
      const okPayload = JSON.stringify({ status: 'ok', workflow: 'regression', title: 'linger 建议', body: 'b', rationale: 'r' })
      process.env.SANDBAR_AGENT_CMD = `${process.execPath} ${lingerScript} '${okPayload}'`
      r = await call(hB, '/sandbar-workbench/api/epics/demo-epic/suggest-next', 'POST')
      const jobId5 = r.body.result.job_id
      let final5 = null
      for (let i = 0; i < 25; i++) {
        await sleep(200)
        const p = await call(hB, `/sandbar-workbench/api/epics/demo-epic/suggest-next/${jobId5}`)
        if (p.body?.result?.state !== 'running') { final5 = p; break }
      }
      ok(final5 !== null && final5.body.result.state === 'done'
        && final5.body.result.suggestion?.title === 'linger 建议',
        '长挂假 agent 轮询 → done 拿到建议')
      const lingerJob = await pollSuggestJob(jobId5)
      ok(lingerJob?.proc?.killed === true || lingerJob?.proc?.exitCode !== null,
        'done 终态回收长挂 agent 进程（进程泄露修复，对齐 agent_activities.py finally-terminate）')
      delete process.env.SANDBAR_AGENT_CMD
    }
  }

  /* ------------------------------------------------------------ C. client pure functions */
  section('C epics-model composeSuggestedBody')
  {
    const body = composeSuggestedBody('demo-epic', '  做下一件事。\n')
    ok(body.startsWith(epicCreateNote('demo-epic')) && body.includes('\n\n做下一件事。'),
      'composeSuggestedBody：归属行首行注入 + 建议正文续接（首尾空白剥除）')
    ok(composeSuggestedBody('demo-epic', '   ') === epicCreateNote('demo-epic') + '\n',
      'composeSuggestedBody：空建议正文 → 只留归属行（与手动新建同形态）')
  }
} finally {
  for (const k of ENV_KEYS) {
    if (savedEnv[k] === undefined) delete process.env[k]
    else process.env[k] = savedEnv[k]
  }
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
