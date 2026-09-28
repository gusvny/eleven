/**
 * 基线：verify-lane 配置驱动契约 + merge 闸 base 透传（票 t260901-08）。
 *
 * 意图：
 *   sandbar M0：dev-lane 代码道必须全配置驱动——项目把自己的写集白名单 /
 *   检查项（v2 list-command 形态）/ integration 命令声明在 verify.yaml（schema v1），
 *   引擎只运行并评判声明了的东西。
 *   历史上 verify_lane 写死 app/ 项目形状，merge_check 调 verify_lane 又不传
 *   `base`，写集检查被静默跳过，server-ticket 的 merge 闸对写集违规实际空转。
 *
 * 被测契约（docs/design/sandbar-project-onboarding-contract-v1.md，三态语义）：
 *   - verify.yaml 缺失 → 代码道关闭（green 项可见，非静默）；
 *   - verify.yaml 畸形 / 未知 schema → fail-closed（整条道红）；
 *   - 合法配置 → 白名单前缀取 write_allow，只跑声明的检查项；
 *   - merge 闸路径（require_base=true）base 为空/缺失 → 红（fail-closed），
 *     手动路径（无 require_base）保持 skip 但可见；
 *   - verify_lane.py 里 app/ 写死残留清零；
 *   - agent_activities.merge_check 把 base + require_base 传给 verify_lane
 *     （静态回归桩——这才是「闸不空转」的真正修复）。
 *
 * 完全密封：只要 git + python3（stdlib），fixture 全在平台 tmpdir。
 * 无 Docker、无真 Temporal、无网络。cwd = 仓根。
 */

import { spawnSync } from 'node:child_process'
import { mkdtemp, writeFile, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readFileSync } from 'node:fs'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const REPO = process.cwd()
const TOOLS = join(REPO, 'server', 'tools')
const LANE = join(REPO, 'server', 'tools', 'verify_lane.py')
const ACT = join(REPO, 'server', 'engine', 'agent_activities.py')

// ---- 环境探测（前置缺失时干净 SKIP） ----
function probe(cmd, args) {
  const p = spawnSync(cmd, args, { encoding: 'utf8' })
  return p.error ? null : p
}
const git = probe('git', ['--version'])
const py = probe('python3', ['--version'])
if (!git || !py) {
  console.log('SKIP git/python3 unavailable: verify-lane-config')
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

let root = null
try { root = await mkdtemp(join(tmpdir(), 'vlcfg-')) } catch (e) {
  console.log('SKIP cannot create tmpdir: ' + e.message)
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

/** fixture 仓内的 git 辅助。 */
function fx(repo, ...args) {
  const p = spawnSync('git', args, { cwd: repo, encoding: 'utf8' })
  if (p.status !== 0) throw new Error(`git ${args.join(' ')}: ${p.stderr}`)
  return p.stdout.trim()
}
import { mkdirSync, writeFileSync } from 'node:fs'
function put(repo, rel, content) {
  const abs = join(repo, rel)
  const dir = abs.slice(0, abs.lastIndexOf('/'))
  mkdirSync(dir, { recursive: true })
  writeFileSync(abs, content)
}
async function makeRepo(withVerifyYaml, yamlText) {
  const repo = await mkdtemp(join(root, 'fx-'))
  fx(repo, 'init', '-q', '-b', 'main')
  fx(repo, 'config', 'user.email', 't@example.com')
  fx(repo, 'config', 'user.name', 't')
  put(repo, 'src/base.ts', 'export const base = 1\n')
  if (withVerifyYaml) put(repo, 'verify.yaml', yamlText)
  fx(repo, 'add', '-A')
  fx(repo, 'commit', '-qm', 'base')
  return repo
}

/** 对 fixture 仓（path=repo）跑 verify_lane.run()，返回解析后的结果。 */
function runLane(repo, args) {
  const code = `
import json, sys
sys.path.insert(0, ${JSON.stringify(TOOLS)})
import verify_lane
print(json.dumps(verify_lane.run(json.loads(sys.argv[1]))))
`
  const p = spawnSync('python3', ['-c', code, JSON.stringify({ path: repo, ...args })], {
    cwd: repo, encoding: 'utf8', timeout: 120000,
  })
  if (p.error || p.status !== 0) {
    return { error: (p.stderr || p.stdout || String(p.error)).slice(-500) }
  }
  try { return JSON.parse(p.stdout) } catch (e) {
    return { error: 'unparseable output: ' + p.stdout.slice(-300) }
  }
}
function checksText(res) { return JSON.stringify(res.checks || []) }
function findCheck(res, substr) {
  return (res.checks || []).find(c => (c.check || '').includes(substr))
}

try {
  // ---------- A. missing verify.yaml -> lane closed, visible, green ----------
  section('A. verify.yaml 缺失 = code 道关闭（green 可见，非静默）')
  {
    const repo = await makeRepo(false)
    const res = runLane(repo, { lane: 'code', skip_slow: true })
    ok(!res.error, 'A0 verify_lane 不抛异常（缺失态走声明关闭）')
    if (!res.error) {
      ok(res.green === true, 'A1 缺失态整道 green')
      ok(/缺失|关闭/.test(checksText(res)), 'A2 green 项 detail 可见声明关闭（非静默）')
    }
  }

  // ---------- B. malformed verify.yaml -> fail-closed red ----------
  section('B. verify.yaml 畸形 = fail-closed 整道红')
  {
    const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["src/"]\n    这是一行不认识的垃圾\n')
    const res = runLane(repo, { lane: 'code', skip_slow: true })
    ok(!res.error, 'B0 不抛异常（畸形判红不 crash）')
    if (!res.error) {
      ok(res.green === false && res.red_count > 0, 'B1 畸形态整道红')
      ok(/畸形/.test(checksText(res)), 'B2 detail 写明畸形与证据')
    }
  }

  // ---------- C. unknown schema -> fail-closed red ----------
  section('C. schema 版本不支持 = fail-closed 红（不猜测解读）')
  {
    const repo = await makeRepo(true, 'schema: v9\nlanes:\n  code:\n    write_allow: ["src/"]\n')
    const res = runLane(repo, { lane: 'code', skip_slow: true })
    ok(!res.error, 'C0 不抛异常')
    if (!res.error) {
      ok(res.green === false, 'C1 版本不支持整道红')
      ok(/v9|版本/.test(checksText(res)), 'C2 detail 写明声明版本 v9 与支持区间')
    }
  }

  // ---------- D. 合法配置：白名单按 write_allow 判 ----------
  section('D. 合法配置：白名单按 write_allow 判（配置驱动，非 app/ 写死）')
  const YAML_OK = 'schema: v1\nlanes:\n  code:\n    write_allow: ["src/"]\n'
  {
    // D1: 干净 diff（只有 src/）→ 白名单 green
    const repo = await makeRepo(true, YAML_OK)
    put(repo, 'src/ok.ts', 'export const ok = 2\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', 'clean')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true })
    ok(!res.error, 'D1.0 干净 diff 不抛异常')
    if (!res.error) {
      const wl = findCheck(res, '白名单')
      ok(!!wl && wl.level === 'green', 'D1.1 白名单项 green 且真实 evaluated')
    }
  }
  {
    // D2: 越界文件 → 红，点名该文件
    const repo = await makeRepo(true, YAML_OK)
    put(repo, 'other/evil.ts', 'export const evil = 1\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', 'out')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true })
    ok(!res.error, 'D2.0 越界 diff 不抛异常')
    if (!res.error) {
      ok(res.green === false, 'D2.1 越界写整道红')
      ok(/other\/evil\.ts|越界/.test(checksText(res)), 'D2.2 红字点名越界文件')
    }
  }
  {
    // D3: 换一种项目形状——write_allow 完全不是 app/*（配置驱动证明）
    const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["lib/"]\n')
    put(repo, 'lib/a.py', 'x = 1\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', 'lib only')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true })
    ok(!res.error, 'D3.0 非 app/ 项目形态不抛异常')
    if (!res.error) ok(res.green === true, 'D3.1 lib/ 项目按自身声明绿（无 app/ 残留依赖）')
  }
  {
    // D4: 前缀内的非 ASCII 文件名 → 必须绿。
    // 验收 S2a 回归棒：`git diff --name-only` 默认 core.quotepath=true，
    // 输出带引号的八进制转义名，匹配不到任何前缀，曾被误判出集
    //（安全侧假红，挡住 merge 闸）。
    const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["docs/"]\n')
    put(repo, 'docs/设计/契约文档v1.md', '# 中文文件名\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', '中文文档')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true })
    const wl = findCheck(res, '白名单')
    ok(!res.error && res.green === true && !!wl && wl.level === 'green',
      'D4.1 前缀内中文名文件不误判越界（quotepath 修复回归棒）')
  }
  {
    // D5: 前缀外的非 ASCII 文件名 → 红，点名原样 UTF-8 名
    const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["docs/"]\n')
    put(repo, '其他/中文越界.md', 'x\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', '越界')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true })
    ok(!res.error && res.green === false, 'D5.1 前缀外中文名文件照判越界')
    ok(/中文越界|其他\//.test(checksText(res)), 'D5.2 红字点名原样 UTF-8 名（非八进制转义）')
  }
  {
    // D6: 精判题眼（t260901-08 收口轮）——工单 write_set 逐文件上限压过 write_allow：
    // 票声明 write_set=['docs/'] 却改了 server/ 下的文件 → 必红点名
    // （write_allow 若含 server/ 也救不了：精判优先，07/08 越界事故的漏网口被封死）。
    const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["docs/", "server/"]\n')
    put(repo, 'server/engine/越界.py', 'x = 1\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', '越界')
    const res = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true, write_set: ['docs/'] })
    ok(!res.error && res.green === false, 'D6.1 窄 write_set 压过宽松 write_allow：改 server/ 必红')
    ok(/server\/dsh\/engine\/越界\.py/.test(checksText(res)), 'D6.2 红字点名越界文件（精判口径）')
    // D6b: write_set 覆盖改动 → 全绿（精判放行正路径）
    put(repo, 'docs/ok.md', 'y\n')
    fx(repo, 'add', '-A'); fx(repo, 'commit', '-qm', '界内')
    const res2 = runLane(repo, { lane: 'code', base: 'HEAD~1', skip_slow: true, write_set: ['docs/'] })
    ok(!res2.error && res2.green === true, 'D6b.1 write_set 覆盖的改动全绿（精判放行）')
  }

  // ---------- E. require_base：空 base 时 merge 闸 fail-closed ----------
  section('E. require_base=true × 空 base = fail-closed 红（合并闸不再空转）')
  {
    const repo = await makeRepo(true, YAML_OK)
    const res = runLane(repo, { lane: 'code', base: '', require_base: true, skip_slow: true })
    ok(!res.error, 'E0 不抛异常')
    if (!res.error) {
      ok(res.green === false, 'E1 空 base 在合并闸口径下红（不许 falsy 静默跳过）')
      ok(/base|base_ref/.test(checksText(res)), 'E2 红字可仲裁（指明 base_ref 未登记）')
    }
    // E3: 手动路径保持 skip 但可见
    const res2 = runLane(repo, { lane: 'code', skip_slow: true })
    ok(!res2.error && res2.green === true, 'E3 手动路径（无 require_base）保持跳过不误伤')
    ok(/base/.test(checksText(res2)), 'E4 手动跳过分支 detail 可见「未验」')
  }

  // ---------- G. integ 道：三行输出契约 + 分道返回形状 ----------
  // 契约②b（t260903-01 入约）：三行协议（PASS/FAIL+缩进尾段/SCENARIOS 参考行）、
  // 红绿=rc==0 且 fail==0、零场景绿=integration 道唯一关闭惯用法、err 语义、
  // integ 返回形状 {lane,green,ran,pass,fail,scenarios,err}（无 red_count/checks）。
  section('G. integ 道：三行输出契约 + 分道返回形状（契约②b）')
  {
    // 引擎现行校验：write_allow 缺失=畸形（契约②a「声明 code 道即须声明写集边界」），
    // 故 integ fixture 一并声明最小 code 道——这是声明义务，不是引擎洞。
    const WL = 'schema: v1\nlanes:\n  code:\n    write_allow: ["src/"]\n'
    const mk = async (cmdLine) => {
      const repo = await makeRepo(true, WL + `integration:\n  cmd: ${cmdLine}\n`)
      return runLane(repo, { lane: 'integ' })
    }
    const INTEG_KEYS = ['lane', 'green', 'ran', 'pass', 'fail', 'scenarios', 'err']

    // G1: verify.yaml missing -> fail-closed err (NO silent close; 契约②a 缺失态勘误)
    {
      const repo = await makeRepo(false)
      const res = runLane(repo, { lane: 'integ' })
      ok(!res.error && res.green === false && !!res.err, 'G1 integ 道 verify.yaml 缺失 = fail-closed err（非空转）')
      ok(!res.error && res.red_count === undefined && res.checks === undefined,
        'G1b integ 道无 red_count/checks（不得按 content 形状读）')
    }
    // G2: 零场景绿惯用法（cmd: true）——键集全在且 err=null
    {
      const res = await mk('true')
      ok(!res.error && res.green === true && res.ran === 0 && res.err === null,
        'G2 恒成功空命令 = 零场景绿（integration 道唯一关闭惯用法，契约②b）')
      ok(INTEG_KEYS.every(k => k in res), 'G2b integ 返回键集齐全 {lane,green,ran,pass,fail,scenarios,err}')
    }
    // G3: 段在位而 cmd 为空 = 畸形 fail-closed（引擎无「空 cmd=关闭」路径）
    {
      const repo = await makeRepo(true, WL + 'integration:\n  cmd: ""\n')
      const res = runLane(repo, { lane: 'integ' })
      ok(!res.error && res.green === false && !!res.err, 'G3 cmd 为空 = 畸形 fail-closed（无幻影关闭路径）')
    }
    // G4: FAIL 行 + 四空格缩进尾段 + rc!=0 -> green=false, fail=1, tail 收进
    {
      const res = await mk('"printf \'FAIL [x场景] exit=3\\n    输出尾段样本\\nSCENARIOS ran=1 pass=0 fail=1\\n\'; exit 1"')
      ok(!res.error && res.green === false && res.fail === 1 && res.ran === 1, 'G4 FAIL 行判红且计数正确')
      ok(res.scenarios?.[0]?.exit === 3, 'G4b scenarios[].exit 透传')
      ok(/输出尾段样本/.test(res.scenarios?.[0]?.output_tail || ''), 'G4c 四空格缩进尾段收进 output_tail')
    }
    // G5: PASS 行 + rc=0 -> green=true
    {
      const res = await mk('"printf \'PASS [ok场景]\\nSCENARIOS ran=1 pass=1 fail=0\\n\'"')
      ok(!res.error && res.green === true && res.ran === 1 && res.pass === 1 && res.fail === 0,
        'G5 PASS 行 + rc=0 判绿')
    }
    // G5b: PASS 行带耗时尾注（260908 KI-060 备料②）-> name 取第一个 ]，报告附加行忽略
    {
      const res = await mk('"printf \'PASS [ok场景] (3.7s)\\nSCENARIOS ran=1 pass=1 fail=0\\n耗时分解（池内串行合计）：\\n  ro 12s\\n\'"')
      ok(res.green === true && res.scenarios[0].name === 'ok场景',
        'G5b PASS 耗时尾注 name 不污染 + 报告附加行被忽略')
    }
    // G6: 零结果且 rc!=0 -> err 态（非红非绿，测试道自身故障）
    {
      const res = await mk('exit 7')
      ok(!res.error && res.green === false && !!res.err && res.ran === undefined,
        'G6 无结果行且 rc!=0 = err 态（非红非绿，契约②b 边界②）')
    }
    // G7: 引擎不读 SCENARIOS 末行、不校验一致性（汇总与明细不一致不判红）
    {
      const res = await mk('"printf \'PASS [a]\\nSCENARIOS ran=9 pass=9 fail=9\\n\'"')
      ok(!res.error && res.green === true, 'G7 SCENARIOS 参考行不构成判据（不一致不判红，契约②b-1）')
    }
    // G8: code 道返回形状键集（content 形状）
    {
      const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["src/"]\n')
      const res = runLane(repo, { lane: 'code', skip_slow: true })
      const keys = Object.keys(res).sort().join(',')
      ok(!res.error && keys === 'checks,green,lane,red_count',
        'G8 code 道返回键集恰为 {lane,green,red_count,checks}（契约②b-2）')
    }
  }

  // ---------- H. 手写解析器语法子集 = 可写域（契约②c） ----------
  // 每个契约列举的语法形态至少一条正例真跑 _parse_verify_yaml；畸形反例端到端判红。
  section('H. 手写解析器语法子集 = 可写域（契约②c，逐形态钉死）')
  {
    const parse = (text) => {
      const code = `
import json, sys
sys.path.insert(0, ${JSON.stringify(TOOLS)})
import verify_lane
print(json.dumps(verify_lane._parse_verify_yaml(sys.argv[1]), ensure_ascii=False))
`
      const p = spawnSync('python3', ['-c', code, text], { encoding: 'utf8', timeout: 60000 })
      if (p.status !== 0) return { error: (p.stderr || '').slice(-300) }
      return JSON.parse(p.stdout)
    }
    // H1: 块列表（'- ' 字符串列表）
    {
      const r = parse('schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n      - docs/\n')
      ok(JSON.stringify(r.lanes?.code?.write_allow) === JSON.stringify(['src/', 'docs/']),
        'H1 块列表解析（- 字符串列表）')
    }
    // H2: '- k: v' 列表套映射（checks 条目，深缩进多键并入条目）
    {
      const r = parse('lanes:\n  code:\n    checks:\n      - id: t1\n        cmd: "true"\n        timeout: 60\n      - id: t2\n        cmd: "true"\n')
      const ck = r.lanes?.code?.checks
      ok(Array.isArray(ck) && ck.length === 2, 'H2 列表套映射：两条 checks 条目')
      ok(ck?.[0]?.id === 't1' && ck?.[0]?.cmd === 'true' && ck?.[0]?.timeout === '60' && ck?.[1]?.id === 't2',
        'H2b 深缩进多键并入条目（id/cmd/timeout 同条目，引号值剥离）')
    }
    // H3: 引号标量 + 值内 ' #' 截断（注释剥离不伤引号内/紧贴 #）
    {
      const r = parse('schema: v1   # 行尾注释\nid: 名字 # 尾注\ncmd: run#anchor\n')
      ok(r.schema === 'v1' && r.id === '名字' && r.cmd === 'run#anchor',
        'H3 裸 token+引号值、行尾 # 截断、url#anchor 不误伤')
    }
    // H4: tab 展开为两空格
    {
      const r = parse('lanes:\n\tcode:\n\t\twrite_allow: ["src/"]\n')
      ok(JSON.stringify(r.lanes?.code?.write_allow) === JSON.stringify(['src/']),
        'H4 tab 展开两空格（缩进等价）')
    }
    // H5: 行内流列表（既有形态保持）
    {
      const r = parse('lanes:\n  code:\n    write_allow: ["a/", "b"]\n')
      ok(JSON.stringify(r.lanes?.code?.write_allow) === JSON.stringify(['a/', 'b']), 'H5 行内流列表解析')
    }
    // H6/H7: 畸形反例端到端 fail-closed（未知顶层键 / checks 条目未知键）
    {
      const repo = await makeRepo(true, 'schema: v1\nfoo: bar\n')
      const res = runLane(repo, { lane: 'code', skip_slow: true })
      ok(!res.error && res.green === false && /未知顶层键/.test(checksText(res)),
        'H6 未知顶层键 = 畸形 fail-closed（不静默过滤）')
    }
    {
      const repo = await makeRepo(true, 'schema: v1\nlanes:\n  code:\n    write_allow: ["src/"]\n    checks:\n      - id: t\n        cmd: "true"\n        cwd: .\n        timeout: 5\n        file: src/\n')
      const res = runLane(repo, { lane: 'code' })
      ok(!res.error && res.green === false && /未知键/.test(checksText(res)),
        'H7 checks 条目未知键（旧五类型键式 file）= 畸形 fail-closed')
    }
  }

  // ---------- F. 静态回归棒 ----------
  section('F. 静态回归棒：合并闸补传 base；app/ 硬编码清零；声明与文档在位')
  {
    const act = readFileSync(ACT, 'utf8')
    const payloadMatch = act.match(/verify_lane",\s*\n?\s*json\.dumps\((\{[\s\S]*?\})\)\s*,/)
      ?? act.match(/verify_lane",\s*\n?\s*json\.dumps\((\{[\s\S]*?\})\)/)
    ok(payloadMatch !== null, 'F1 merge_check 仍调用 verify_lane（结构未漂移）')
    if (payloadMatch) {
      const payload = payloadMatch[1]
      // t260901-08 收口轮：扩写集已拍板、补丁已落盘——PENDING 有声跳过退役，转硬断言。
      // 这里不许再有任何 SKIP 分支：payload 回归（丢 base/require_base/write_set）必须
      // FAIL，跳过=合并闸空转回归被测试集静默掩盖，正是本票要治的病。
      ok(/["']base["']/.test(payload) && /require_base["']?\s*:\s*[Tt]rue/.test(payload),
        'F2/F3 merge_check payload 含 base + require_base:true（合并闸真判写集，fail-closed）')
      ok(/["']write_set["']\s*:\s*list\(args\.write_set\)/.test(payload),
        'F2b merge_check payload 接线工单 write_set（精判逐文件，write_allow 仅兜手动）')
    }
    const lane = readFileSync(LANE, 'utf8')
    ok(!/CODE_WHITELIST\s*=/.test(lane), 'F4 verify_lane 无 CODE_WHITELIST 硬编码白名单')
    ok(!/app\/src\//.test(lane), 'F5 verify_lane 无 app/src/ 路径残留')
    ok(/lane_cfg/.test(lane) && /write_allow/.test(lane), 'F6 检查项由 verify.yaml 声明装配（lane_cfg/write_allow 在位）')
    ok(/require_base/.test(lane), 'F7 verify_lane 暴露 require_base 参数')
    // 仓根 verify.yaml 在位且声明本仓自身形状
    try {
      const vy = readFileSync(join(REPO, 'verify.yaml'), 'utf8')
      ok(/schema:\s*v1/.test(vy), 'F8 仓库根 verify.yaml 在位且 schema: v1')
      // 260904 重构（宿主质疑「真实数据自测」）：原 F9 是 suyou 仓 verify.yaml 的
      // 快照断言（write_allow 含 app/src/）——sandbar 无 app/，红因是快照错仓。
      // 换成 sandbar 形态的性质断言：write_allow 按配置声明本仓真源面（server/ 与
      // integration/ 为引擎与场景真源，稳定不变量），且无 suyou 项目域 app/ 残留回流。
      const wl = vy.match(/write_allow:\s*\n((?:\s*-\s*\S+\n)+)/)?.[1] || ''
      ok(/-\s*server\/\s*\n/.test(wl) && /-\s*integration\/\s*\n/.test(wl),
        'F9 write_allow 声明本仓真源面 server/ 与 integration/（配置驱动，非硬编码）')
      ok(!/app\//.test(wl), "F9' write_allow 无 suyou 项目域 app/ 残留")
      ok(/integration\/run_scenarios\.py/.test(vy), 'F10 verify.yaml 声明 integration.cmd（v2 列表命令制）')
    } catch (e) { ok(false, 'F8 仓库根 verify.yaml 在位（缺失: ' + e.code + ')') }
    // 契约文档带字段级 schema 章节
    try {
      const contract = readFileSync(join(REPO, 'docs', 'design', 'sandbar-project-onboarding-contract-v1.md'), 'utf8')
      ok(/field-level definition/i.test(contract) && /write_allow/.test(contract), 'F11 契约文档含 verify.yaml 字段级定义')
      ok(/change (record|log)/i.test(contract) && /t260901-08/.test(contract), 'F12 契约变更记录落了本票条目')
      // t260903-01 声明制对齐锚点：②a 列表命令制 + ②b/②c/②d/②e 四新章在位
      const sec2a = contract.match(/^### ②a[\s\S]*?(?=^### )/m)?.[0] || ''
      ok(/id, cmd, cwd\?, timeout\?/.test(sec2a) && /integration\.cmd/.test(sec2a),
        'F13 ②a 载列表命令制键集 {id,cmd,cwd?,timeout?} 与 integration.cmd')
      ok(/schema stays v1 ruling|keep-schema-v1/i.test(sec2a), 'F14 ②a 载 schema 保 v1 裁定说明')
      for (const [kw, label] of [['Output contract', '②b'], ['grammar subset', '②c'], ['Thin-shell execution topology', '②d'], ['rule of three', '②e']]) {
        ok(new RegExp(kw, 'i').test(contract), `F15 契约新章锚点在位：${label}（${kw}）`)
      }
      // 五类型字样只允许出现在「退役/失真/勘误」注记行（含相邻行窗口——注记词
      // 可能落在跨行句子的后半句）——语义对齐防漂移。
      // 变更记录是 append 式历史（v1.1 当年条目原样保留），不在活口检查范围。
      const liveLines = contract.split(/^#{2,4}\s*change (record|log)/im)[0].split('\n')
      const hasNote = (l) => /retired|distort|erratum|obsolete|void/i.test(l)
      const fiveTypeBad = liveLines.filter((l, i) =>
        /shotdebug|deps_dir|red_green\.rule|integration\.entry/.test(l)
        && !hasNote(l)
        && !(i > 0 && hasNote(liveLines[i - 1]))
        && !(i < liveLines.length - 1 && hasNote(liveLines[i + 1])))
      ok(fiveTypeBad.length === 0, 'F16 五类型/旧 integration 键只现于退役注记（无活口失真）')
    } catch (e) { ok(false, 'F11 契约文档可读') }
  }
} finally {
  // 资源回收：fixture 树在所有终态路径上都被删除
  try { await rm(root, { recursive: true, force: true }) } catch { /* best effort */ }
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
