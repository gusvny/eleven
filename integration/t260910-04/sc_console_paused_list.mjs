// sc_console_paused_list.mjs —— t260910-04 console 接口面场景（R1(a) 真链腿）。
//
// 直跑：node integration/t260910-04/sc_console_paused_list.mjs（exit 0=过 / 1=红 / 2=ENV_FAIL）。
//
// intent（工单派发规格点名的「console 接口面」洞，KI-063 场景面偏科封堵）：
//   真引擎 pause 后，console 面 GET /wf/tickets?project= 列表行的 paused/paused_phase
//   与 client.py ticket-query snapshot **逐键一致**；resume 后回 false、工单续派到收口。
//   与 workbench UT（假引擎，锁 host 透传形状/错误契约）两层各管一段；与
//   sc_ticket_pause_gate.py（引擎面）intent 不同面：彼锁引擎暂停语义、本条锁
//   「引擎 snapshot → console API 行」的透传链（t260908-01 合并后实测断点正在这一跳）。
//
// 拓扑与护栏声明：
// - 台面（260910 gen2 仲裁改造）：**私有台**——stage_docker 直起（services=full，
//   docker/镜像缺席=ENV_FAIL exit 2 点名，绝不回落生产端口），逐跑唯一项目名、
//   现分空闲端口、退出钩子 stageDown 零残留（L7 有断言腿）。共享树台（lib_stage_console
//   ensureStageConsole）两大连坐退场：restart 掐断并发场景在飞流式请求（multi-tab
//   T7 ERR_INCOMPLETE_CHUNKED_ENCODING）、跨泳道 churn 吃 900s 执行器 SIGKILL。
// - 台面代码新鲜（附条件②，KI-058 同族「安装态≠代码态」）：私有台 fresh boot 挂当前
//   树 /repo——新鮮 by construction，无 restart 需求；就绪以 /wf/projects 200 探测。
// - 活 worker 腿（附条件①）：pause 生效/快照可查/恢复续派三者都要 worker 在场答题
//   （stage_docker services 全集无 worker 服务；lib 的 fixture_ticket_worker 是 drain
//   即退形态不作驻留）。形态照 sc_ticket_pause_gate.py 现成声明：夹具仓（本仓
//   --depth 1 clone，泳道/settle/merge 全在夹具仓内，真仓零接触）+ 真引擎 worker.py +
//   桩大脑 SANDBAR_AGENT_STUB=1；子进程 env 剥泳道三件套（SANDBAR_TASK_QUEUE/
//   SANDBAR_TASK_QUEUES/SANDBAR_WATCH_WORKFLOW）后钉死 SANDBAR_TASK_QUEUES=
//   sandbar-ticket-<本场景票id>、SANDBAR_TARGET_HOST=本台地址——递归按构造不可能
//   （一次性台+无泳道标记+专属队列），L0 写守卫断言 TARGET_HOST=127.0.0.1:台端口且
//   端口 ∉ stage_docker.FORBIDDEN_PORTS，绝不缺省回落生产 7233。
// - 灰盒：断言只落公开契约面——ticket-query snapshot 键、ticket-list 行键、console
//   HTTP JSON；不 import 引擎内部。
// - 进程/fd 终态回收：worker 子进程正常/报错/超时/取消每条路径都走 stopWorker 的
//   TERM→20s 帽→KILL 清理；场景进程退出前 finally 兜底。
//
// 预算注记：900s kill 帽偏紧（台 ensure 冷起 600s 帽+clone+全链），超帽被杀=空 stdout
// 丢原因（t260905-02 教训），故 ENV_FAIL 一律尽早 exit 2 点名。实现落地前红属预期
// （TDD 信号），arbitrate/merge 期必须绿。
import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, mkdtempSync, openSync, rmSync, symlinkSync, writeFileSync, writeSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const INTEG = path.dirname(HERE);
const REPO = path.dirname(INTEG);                       // 泳道树根（=台面 /repo 挂载源）
// 宿主引擎 python：泳道树 gitignored 无 venv——回落主仓（git common-dir 上两级推导，
// 与 L1 夹具链同源），再缺席则退 python3（_engine_py 口径）。
function resolveHostPy() {
  const laneVenv = path.join(REPO, 'server', 'engine', '.venv', 'bin', 'python');
  if (existsSync(laneVenv)) return laneVenv;
  const gd = spawnSync('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
    { encoding: 'utf8', timeout: 15_000 });
  const mainVenv = path.join(path.resolve(String(gd.stdout ?? '').trim(), '..'),
    'server', 'engine', '.venv', 'bin', 'python');
  if (gd.status === 0 && existsSync(mainVenv)) return mainVenv;
  return 'python3';
}
const PY = resolveHostPy();
const PROJECT_KEY = 'p91004c';
const RUN_TAG_SUFFIX = Date.now().toString(36);         // 每跑唯一（未知 key 400 腿用，避免撞历史注册）
const STUB_DELAY_SEC = 6;                               // 桩段时长（引擎旋钮，sc_ticket_pause_gate 同值）
const LANE_MARKERS = ['SANDBAR_TASK_QUEUE', 'SANDBAR_TASK_QUEUES', 'SANDBAR_WATCH_WORKFLOW'];

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`); return true; }
  fail++; console.error(`  FAIL ${label}`); return false;
}
function envFail(why) {
  console.error(`[ENV_FAIL] sc_console_paused_list — ${why}`);
  process.exit(2);
}

let worker = null;
function stopWorker(label) {
  if (!worker) return;
  const w = worker; worker = null;
  try { w.kill('SIGTERM'); } catch { /* 已退 */ }
  const t0 = Date.now();
  while (Date.now() - t0 < 20_000 && w.exitCode === null && w.signalCode === null) {
    spawnSync('sleep', ['0.5']);
  }
  if (w.exitCode === null && w.signalCode === null) {
    try { w.kill('SIGKILL'); } catch { /* 尽力兜底 */ }
    console.error(`  [warn] ${label}：TERM 20s 未退，KILL 兜底（资源回收路径在案）`);
  }
}
process.on('exit', () => { if (worker) { try { worker.kill('SIGKILL'); } catch { /* 兜底 */ } } });

function sh(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { encoding: 'utf8', timeout: opts.timeout ?? 180_000, ...opts });
}
function cli(sub, args, cwd, timeout = 180_000) {
  const env = { ...process.env };
  for (const m of LANE_MARKERS) delete env[m];          // 剥泳道三件套（防递归硬纪律）
  env.SANDBAR_TARGET_HOST = G.target;                   // 钉本台（L0 写守卫锚）
  if (G.namespace) env.SANDBAR_NAMESPACE = G.namespace;
  if (G.registry) env.SANDBAR_PROJECTS_YAML = G.registry;
  env.SANDBAR_FIXTURE_TEMPLATES = '1';   // fixture-two-step 注册环境门（开票侧）
  const p = sh(PY, [path.join(cwd, 'server', 'engine', 'client.py'), sub, JSON.stringify(args)],
    { cwd, env, timeout });
  try { return { rc: p.status, body: JSON.parse(String(p.stdout ?? '').trim()) }; }
  catch { return { rc: p.status, body: {}, stdout: String(p.stdout ?? ''), stderr: String(p.stderr ?? '') }; }
}

/** 遗留 stray 清理：崩跑遗留的无 worker RUNNING 票=本项目每张列表查询按张多付 8s
 * 快照超时（QUERY_TIMEOUT_S，lib_stage_console run L/M/O/Q/S 实案）。按 id terminate，
 * best-effort（历史 stray 已终止时报 not found 之类=正常跳过）。 */
function terminateTid(tidX) {
  const f = path.join(tmpdir(), `t26091004-term-${tidX}.py`);
  writeFileSync(f, [
    'import asyncio, sys',
    'from temporalio.client import Client',
    'async def m():',
    '    c = await Client.connect(sys.argv[1], namespace=sys.argv[2])',
    '    try:',
    "        await c.get_workflow_handle(sys.argv[3]).terminate('t260910-04 stray cleanup')",
    '        print("terminated")',
    '    except Exception as e:',
    '        print("ignored", type(e).__name__)',
    'asyncio.run(m())',
  ].join('\n'));
  const env = { ...process.env };
  env.SANDBAR_TARGET_HOST = G.target;
  if (G.namespace) env.SANDBAR_NAMESPACE = G.namespace;
  const p = sh(PY, [f, G.target, G.namespace, tidX], { env, timeout: 60_000 });
  try { rmSync(f, { force: true }) } catch { /* 临时文件尽力清 */ }
  return p.status === 0;
}

async function fetchJson(url, timeoutMs = 15_000) {
  const r = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  return { status: r.status, body: await r.json().catch(() => null) };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitSnap(tid, pred, label, deadlineS) {
  const t0 = Date.now();
  let snap = null;
  while ((Date.now() - t0) / 1000 < deadlineS) {
    const { body } = cli('ticket-query', { ticket_id: tid }, G.fixture);
    if (body?.ok) {
      snap = body.result?.snapshot ?? null;
      if (snap && pred(snap)) return snap;
    }
    await sleep(2000);
  }
  const tl = (snap?.timeline ?? []).slice(-4)
    .map((e) => `${e.stage}/${e.state}:${String(e.reason ?? '').slice(0, 120)}`).join(' | ');
  ok(false, `${label}：${deadlineS}s 超时（末态 stage=${snap?.stage}/${snap?.stage_state} status=${snap?.status} timeline尾=${tl}）`);
  return null;
}

/** console 列表轮询：直到行在场且 pred(行) 成立。 */
async function waitRow(tid, pred, label, deadlineS) {
  const t0 = Date.now();
  let row = null;
  while ((Date.now() - t0) / 1000 < deadlineS) {
    const r = await fetchJson(`${G.base}/sandbar-workbench/api/wf/tickets?project=${PROJECT_KEY}`).catch(() => null);
    row = (r?.body?.result?.tickets ?? []).find((t) => t?.id === tid) ?? null;
    if (row && pred(row)) return row;
    await sleep(2000);
  }
  ok(false, `${label}：console 行 ${deadlineS}s 内未达断言态（实得 ${JSON.stringify(row)?.slice(0, 200)}）`);
  return null;
}

const G = { target: '', namespace: '', registry: '', fixture: '', base: '' };

async function main() {
  console.log('== L0 环境门与写守卫');
  if (PY === 'python3') {
    envFail('宿主引擎 venv 缺席（泳道树与主仓皆无 server/engine/.venv，python3 回落无 temporalio 保障）');
  }
  if (spawnSync('docker', ['info'], { timeout: 30_000 }).status !== 0) {
    envFail('docker 守护不可达');
  }
  // 嵌套语义（260910 仲裁实锤修正）：套件执行器（run_integration_tests 段）本身就
  // 跑在泳道 env 里，env 必带泳道 worker 标记——「带标记=env_fail」会把本场景在
  // 套件里打成 0.1s 假红（实测 ENV_FAIL 0.1s）。防递归靠结构性隔离已足够（子进程
  // 剥泳道三件套+钉本票专属队列+TARGET_HOST 钉自建台∉FORBIDDEN_PORTS），不再做
  // 自护栏 env_fail；防呆判据应是「宿主台可达」而非「env 带标记」。
  // 台面拓扑（260910 gen2 仲裁实锤改造）：**私有台**（stage_docker 直起，逐跑唯一
  // 项目名，退出钩子 stageDown 零残留）。不再用共享树台（lib_stage_console）——共享
  // 台两大连坐实锤：①本场景新鲜守卫要 docker restart dsh，多池并行下掐断 browser
  // 池在飞流式请求（multi-tab T7 ERR_INCOMPLETE_CHUNKED_ENCODING×8）；②跨泳道
  // churn 让本场景吃 900s 执行器 SIGKILL（exit -9）+ ensure 挂死/端口冲突。私有台
  // fresh boot 挂当前树 /repo=代码新鲜 by construction，端口现分空闲段，谁也不踩谁。
  // 嵌套语义：套件执行器本就跑在泳道 env 里，防递归靠结构性隔离（子进程剥泳道
  // 三件套+钉本票专属队列+TARGET_HOST 钉自建台∉FORBIDDEN_PORTS）。
  const stMod = await import(path.join(INTEG, 'stage_docker.mjs'));
  const tmp = mkdtempSync(path.join(tmpdir(), 't26091004-sc-'));
  const fixturesDir = path.join(tmp, 'fixtures');
  mkdirSync(fixturesDir, { recursive: true });
  let STAGE_PROJECT = `t26091004-sc-${process.pid}`;
  const profileDir = stMod.buildStageProfile({
    repoProfileDir: path.join(REPO, 'server', 'profile'),
    laneWorkbenchDir: path.join(REPO, 'server', 'plugins', 'workbench'),
    tmpHome: tmp,
  });
  // stageUp 失败重试一次（260911 gen4 仲裁补强）：多泳道并发期端口 TOCTOU（bind
  // probe 探到空闲→compose 绑定时被别的泳道抢占，套件实锤「Bind failed: port is
  // already allocated」1.3s 速败）——换项目名重起=换新端口段再试；两次皆败才
  // env_fail 点名（三次态行为不变，纯健壮性，断言零变化）。失败台顺手 down 防残留。
  let stUp = null;
  let upErr = '';
  for (let attempt = 0; attempt < 2 && !stUp; attempt++) {
    if (attempt > 0) {
      STAGE_PROJECT = `${STAGE_PROJECT}-r1`;
      await sleep(10_000);
    }
    try {
      stUp = stMod.stageUp({
        project: STAGE_PROJECT,
        services: 'full',
        // namespace 不显式传：随台缺省（=compose 契约缺省，t260917-07 补完终切后为
        // sandbar-test），消费面一律用 stUp.namespace 回报值，绝不硬编码台名。
        fixturesDir,
        profileDir,
        projectsDir: '/fixtures/projects',
        timeoutSec: 300,
      });
    } catch (e) {
      upErr = String(e?.message ?? e);
      try { stMod.stageDown(STAGE_PROJECT); } catch { /* 尽力清残留 */ }
    }
  }
  if (!stUp) envFail(`私有台 stageUp 两次皆败（含并发端口争用面）：${upErr.slice(0, 200)}`);
  G.base = `http://127.0.0.1:${stUp.ports.console}`;
  // temporal 宿主端口：stageUp 返回体现分端口（不再 docker inspect 反解）。
  G.target = `127.0.0.1:${stUp.ports.temporal}`;         // L0 写守卫锚：恒钉本台，绝不缺省回落生产 7233
  G.namespace = stUp.namespace || 'sandbar-test';        // 台回报值优先；回落=契约缺省值（形状防御，t260917-07 对齐终切）
  // 禁区端口表（gen2 验收补缺）：真源在 stage_docker.py（.mjs 不导出该面）——
  // ESM 缺席时回落 python 模块读取；两路皆缺席=写守卫空转（断言恒真≠守卫），
  // 必须 env_fail 点名拒绝装饰性守卫。
  let forbidden = [...(stMod.FORBIDDEN_PORTS ?? [])];
  if (forbidden.length === 0) {
    const fp = sh('python3', ['-c', 'import sys; sys.path.insert(0,"' + INTEG + '"); import stage_docker as sd; print(sorted(sd.FORBIDDEN_PORTS))'], { timeout: 30_000 });
    try { forbidden = JSON.parse(String(fp.stdout ?? '[]').trim()); } catch { /* 落下统一 env_fail */ }
  }
  if (forbidden.length === 0) envFail('禁区端口表不可得（stage_docker.mjs/.py 均未产出 FORBIDDEN_PORTS）——L0 写守卫拒绝空转');
  const tPort = Number(G.target.split(':')[1] ?? 0);     // 守卫对象=temporal 端口（写守卫钉的地址）
  // 进程退出兜底回收（资源生命周期纪律）：任何出口（含各 process.exit 路径）都拆
  // 私有台——exit 钩子同步段可 spawnSync；正常流另有 L7 零残留断言腿。
  process.on('exit', () => { try { stMod.stageDown(STAGE_PROJECT); } catch { /* 尽力回收 */ } });

  // ---- 附条件②（私有台形态）：代码新鲜 by construction + 就绪探测 ----
  console.log('== L0b 私有台就绪与新鲜性（fresh boot 挂当前树 /repo，无 restart 需求）');
  ok(stUp?.project === STAGE_PROJECT && tPort > 0 && forbidden.includes(tPort) === false,
     `L0b 私有台就绪（${STAGE_PROJECT}，console=:${stUp.ports.console} temporal=:${tPort} ∉ FORBIDDEN_PORTS ns=${G.namespace}）`);
  {
    const t0 = Date.now();
    let ready = false;
    while (Date.now() - t0 < 120_000) {
      const r = await fetchJson(`${G.base}/sandbar-workbench/api/wf/projects`, 5000).catch(() => null);
      if (r?.status === 200) { ready = true; break; }
      await sleep(2000);
    }
    ok(ready, 'console 就绪（/wf/projects 200）——私有台 boot 即本树 node.ts，无陈旧代码面');
  }

  console.log('== L1 夹具仓 + 注册表 + 台面项目接线');
  const fixture = path.join(tmp, 'fixture');
  try {
    const clone = sh('git', ['clone', '--depth', '1', REPO, fixture], { timeout: 300_000 });
    if (clone.status !== 0) envFail(`夹具仓 clone 失败：${String(clone.stderr).slice(-200)}`);
    // 基线分支对齐（t260908-01 implement r5 实证教训）：--depth 1 clone 的默认分支名
    // 跟随源仓 HEAD 分支（泳道分支名），不是 main——dev-lane 旅程 merge_check 的写集
    // 白名单基线 merge-base main × lane/<tid> 会 rc=128 红灯。当前分支统一改名 main。
    {
      const br = sh('git', ['-C', fixture, 'rev-parse', '--abbrev-ref', 'HEAD'], { timeout: 15_000 });
      if (br.status === 0 && String(br.stdout ?? '').trim() !== 'main') {
        sh('git', ['-C', fixture, 'branch', '-m', 'main'], { timeout: 15_000 });
      }
    }
    sh('git', ['-C', fixture, 'config', 'user.email', 'e2e@pause.test']);
    sh('git', ['-C', fixture, 'config', 'user.name', 't26091004-e2e']);
    // 引擎 venv：必须链**主仓**真 venv（泳道树 gitignored 无 venv，链它=悬空——
    // _ensure_lane_deps 对悬空 src 跳过，lane 内 test 检查回落 python3 缺 pytest
    // → merge_check blocked，260910 实跑实锤）。主仓根=git common-dir 上两级
    // （verify.yaml supply 同款推导）。
    {
      const gd = sh('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'], { timeout: 15_000 });
      const mainRoot = path.resolve(String(gd.stdout ?? '').trim(), '..');
      const vsrc = path.join(mainRoot, 'server', 'engine', '.venv');
      if (!existsSync(vsrc)) envFail(`主仓引擎 venv 缺席：${vsrc}（lane 依赖引导/test 检查需要）`);
      symlinkSync(vsrc, path.join(fixture, 'server', 'engine', '.venv'));
    }
    G.fixture = fixture;
    // 宿主侧注册表（开票白名单；dirs→夹具仓自身，sc_ticket_pause_gate 先例形态）
    G.registry = path.join(tmp, 'projects.yaml');
    writeFileSync(G.registry,
      // legacy 单文件格式（SANDBAR_PROJECTS_YAML 通路，lib_stage_console legacyYaml 同款）
      `projects:\n  - key: ${PROJECT_KEY}\n    name: ConsolePausedList\n    dirs:\n      - ${fixture}\n`);
    // 台面（容器内）注册表：<fixturesDir>/projects/<key>/project.yaml（私有台把
    // fixturesDir 挂 /fixtures rw，projectsDir=/fixtures/projects）
    mkdirSync(path.join(fixturesDir, 'projects', PROJECT_KEY), { recursive: true });
    mkdirSync(path.join(fixturesDir, PROJECT_KEY), { recursive: true });
    writeFileSync(path.join(fixturesDir, 'projects', PROJECT_KEY, 'project.yaml'),
      `schema: v1\nproject:\n  - key: ${PROJECT_KEY}\n    name: ConsolePausedList\n    dirs:\n      - /fixtures/${PROJECT_KEY}\n`);

    // L0 写守卫：TARGET_HOST 恒=本台地址，端口 ∉ FORBIDDEN_PORTS
    ok(G.target.startsWith('127.0.0.1:') && !forbidden.includes(tPort),
       `L0 写守卫：TARGET_HOST 钉本台 127.0.0.1，端口 ${tPort} ∉ FORBIDDEN_PORTS（${forbidden.length} 项）`);

    console.log('== L2 开票 + 驻留桩脑 worker');
    // 开场 stray 清理：本项目历史崩跑遗留的 RUNNING/暂停票（无 worker 答题）让本项目
    // 每张列表查询按张付 8s 快照超时，直接拖穿 waitRow 预算——先清场再开票。
    {
      const { body } = cli('ticket-list', { project: PROJECT_KEY }, fixture);
      for (const r of (body?.result?.tickets ?? [])) {
        if (r?.stage_state === 'running' || r?.paused === true) terminateTid(r.id);
      }
    }
    const tid = `t260910-${String(40 + (Math.floor(Date.now() / 60_000) % 50)).padStart(2, '0')}`;
    // 模板必须=dev-lane：console（dsh 容器）的引擎进程不开 SANDBAR_FIXTURE_TEMPLATES，
    // ticket-list 的 WorkflowType 过滤器里没有 fixture-two-step 类 → 该票对 console
    // **恒不可见**（260910 实跑实锤：console 恒 0 行）。dev-lane 的 arbitrate blocked
    // 风险由两钉化解：①下面 L2b 查询锚最早 pause（门口停在链头，arbitrate 根本不跑）；
    // ②L3b 趁门口预置 stage_arbitrate verdict=pass（幂等缓存路径），resume 后照收口。
    const start = cli('ticket-start', {
      ticket_id: tid, template_id: 'dev-lane', project: PROJECT_KEY,
      title: '[e2e] t260910-04 console 腿暂停透传', user_request: 't260910-04 console paused list',
      write_set: [`integration/e2e-probe-${tid}.txt`],
    }, fixture);
    ok(start.body?.ok === true, `L2 dev-lane 开票 RUNNING（${tid}，实得 ok=${start.body?.ok} ${String(start.body?.error ?? '').slice(0, 120)}）`);
    if (start.body?.ok !== true) process.exit(1);

    // 驻留 worker：剥三件套+钉本票队列+桩大脑（cli 同款 env；存活覆盖 pause→断言→resume→收口）
    {
      const env = { ...process.env };
      for (const m of LANE_MARKERS) delete env[m];
      env.SANDBAR_TARGET_HOST = G.target;
      if (G.namespace) env.SANDBAR_NAMESPACE = G.namespace;
      env.SANDBAR_TASK_QUEUES = `sandbar-ticket-${tid}`;
      env.SANDBAR_AGENT_STUB = '1';
      env.SANDBAR_AGENT_STUB_DELAY_SEC = String(STUB_DELAY_SEC);
      // 桩链其余旋钮（sc_ticket_pause_gate 同款）：arbitrate 建议/验收走查照抄短路口径，
      // 缺了会卡 arbitrate/blocked（首跑实测）。
      env.SANDBAR_SUGGEST_STUB = 'ok';
      env.SANDBAR_UI_CAPTURE_STUB = '1';
      env.SANDBAR_FIXTURE_TEMPLATES = '1';   // worker 侧同门：fixture-two-step 类注册（sc start_worker extra 同款）
      // 归档落点钉进现场（ticket_data_dir = <SANDBAR_PROJECTS_DIR>/<key>/data/tickets/<id>）：
      // 不钉则回落 ~/.sandbar/projects——沙箱对 home 写拒（PermissionError 实锤），
      // 归档 fail-closed → merge/blocked 永不收口。
      env.SANDBAR_PROJECTS_DIR = path.join(tmp, 'projects-dir');
      worker = spawn(PY, [path.join(fixture, 'server', 'engine', 'worker.py')],
        { cwd: fixture, env, stdio: ['ignore', 'pipe', 'pipe'] });
      let wlog = '';
      const wlogFd = openSync(path.join(tmp, 'worker.log'), 'w');
      worker.stderr.on('data', (d) => { wlog += d; writeSync(wlogFd, d); });
      worker.stdout.on('data', (d) => { wlog += d; writeSync(wlogFd, d); });
      worker._logTail = () => wlog.slice(-400);
    }
    // pause 时机锚（260910 实跑教训①：ticket-list 的 SA 可见性传播滞后（秒级~分钟级）
    // ≫ 桩段时长（6s/段）——等「列表在场」再 pause 必然追不上门，票已跑到后续段；
    // 时机锚必须直接轮 ticket-query（真源查询，无传播滞后）。教训②：桩脑下 dev-lane
    // 会卡 arbitrate/blocked 永不收口（见上模板注）。锚 stage_state=running（不锚段名）
    // 时发 pause→当前段自然跑完→停在下一个段间门口（sc_ticket_pause_gate L3.2 纪律）。
    const inflight = await waitSnap(tid, (s) => s.stage_state === 'running',
      'L2b 首段在飞（pause 时机锚）', 240);
    if (!inflight) { stopWorker('main-worker'); process.exit(1); }
    // 列表在场核验（advanced-visibility 传播滞后本身是已知形态，只记腿不卡流程：
    // pause 已生效、票停在门口，列表何时可见由本腿观察，超时只计红不断链）。
    const seen = await (async () => {
      const t0 = Date.now();
      while (Date.now() - t0 < 90_000) {
        const { body } = cli('ticket-list', { project: PROJECT_KEY }, fixture);
        if ((body?.result?.tickets ?? []).some((r) => r?.id === tid)) return true;
        await sleep(2000);
      }
      return false;
    })();
    ok(seen, 'L2c 票在引擎 ticket-list 在场（传播核验，观察腿）');

    console.log('== L3 pause → console 行与 snapshot 逐键一致');
    const pause = cli('ticket', { op: 'pause', ticket_id: tid, input: { who: 'e2e-host', note: 'console 腿暂停' } }, fixture);
    ok(pause.body?.ok === true, 'L3 pause 信号回执 ok');
    const snapGate = await waitSnap(tid, (s) => s.paused === true && s.paused_phase === 'at_gate',
      'L3 引擎停段间门口（at_gate）', 240);
    if (!snapGate) { stopWorker('main-worker'); process.exit(1); }
    const rowGate = await waitRow(tid, (r) => r.paused === true && r.paused_phase === 'at_gate',
      'L3 console 行 paused/at_gate', 90);
    if (!rowGate) { stopWorker('main-worker'); process.exit(1); }
    ok(rowGate.paused === snapGate.paused && rowGate.paused_phase === snapGate.paused_phase,
       `L3 console 行与 snapshot 逐键一致（paused=${snapGate.paused} paused_phase=${snapGate.paused_phase}）`);
    ok(rowGate.stage === snapGate.stage && rowGate.stage_state === snapGate.stage_state,
       'L3 同步核验 stage/stage_state 一致（行=引擎投影非独立真源）');
    // 行形状不变量全行扫（设计段补腿）：任意行的 paused 缺席或布尔、paused_phase 缺席
    // 或字符串——KI-008 降级行/closed 超窗极简行不带 paused 键是合法形状，缺键不
    // throw、键形非法（null/字符串布尔等）=红。锁「引擎行逐键透传不清洗」的契约面。
    {
      const sweep = await fetchJson(`${G.base}/sandbar-workbench/api/wf/tickets?project=${PROJECT_KEY}`).catch(() => null);
      const rows = sweep?.body?.result?.tickets ?? [];
      ok(rows.every((r) => !('paused' in r) || typeof r.paused === 'boolean') &&
         rows.every((r) => !('paused_phase' in r) || typeof r.paused_phase === 'string'),
         `L3 行形状不变量全行扫：paused 缺席|布尔、paused_phase 缺席|字符串（${rows.length} 行）`);
    }

    console.log('== L3b 预置仲裁 verdict（幂等缓存路径，sc_ticket_pause_gate 先例）');
    // 暂停在段间门口= arbitrate 尚未跑；趁门口预置 stage_arbitrate_gen0.json
    // （verdict=pass），否则桩脑无 verdict 标记会走到 KI-061 超限 blocked（首跑实测）。
    // 点目录规则与引擎 resolve_dot_dir 同：新名 .sandbar 优先、旧名 .suyou 粘性回落（naming-compat：读侧回落兼容面）
    {
      const lane = snapGate?.meta?.workspace?.path ?? '';
      if (!lane) { ok(false, `L3b 泳道路径锚定（snapshot.meta.workspace.path 实得 ${JSON.stringify(lane)}）`); process.exit(1); }
      let sdir = path.join(lane, '.sandbar');
      if (!existsSync(sdir) && existsSync(path.join(lane, '.suyou'))) sdir = path.join(lane, '.suyou');  // naming-compat：旧名粘滞回落
      mkdirSync(sdir, { recursive: true });
      const fsMod = await import('node:fs');
      let gen = 0;
      for (const fn of fsMod.readdirSync(sdir)) {
        const m = fn.match(/^stage_arbitrate_gen(\d+)\.json$/);
        if (m) gen = Math.max(gen, Number(m[1]) + 1);
      }
      fsMod.writeFileSync(path.join(sdir, `stage_arbitrate_gen${gen}.json`), JSON.stringify({
        status: 'ok',
        summary: '集成测试三态判定：verdict=pass（e2e 预置，走幂等缓存路径）',
        report: '[e2e seeded by sc_console_paused_list] verdict=pass',
        deliverables: [], files_changed: [],
        evidence: 'seeded by sc_console_paused_list',
      }), 'utf8');
      ok(true, `L3b 仲裁 verdict 预置落盘（${sdir}/stage_arbitrate_gen${gen}.json）`);
      // lane 依赖软链（_ensure_lane_deps 幂等复刻）：worktree 不继承 gitignored 的
      // server/engine/.venv，缺了 verify.yaml test 检查回落 python3 缺 pytest →
      // merge_check blocked（260910 实跑实锤）。此刻链已在门口、merge_check 未跑，
      // 补链即可；目标=夹具根的 .venv（指向主仓真 venv，L1 已建）。
      {
        const laneVenv = path.join(lane, 'server', 'engine', '.venv');
        if (!existsSync(laneVenv)) {
          mkdirSync(path.dirname(laneVenv), { recursive: true });
          symlinkSync(path.join(fixture, 'server', 'engine', '.venv'), laneVenv);
        }
        ok(existsSync(laneVenv), 'L3b lane 依赖软链在位（server/engine/.venv→主仓 venv）');
      }
      // write_set 探针：票声明 write_set=[integration/e2e-probe-<tid>.txt]，merge_check
      // 精判写集覆盖（声明文件 0 落盘=blocked，260910 实跑实锤）——趁门口把探针写进泳道。
      const probe = path.join(lane, 'integration', `e2e-probe-${tid}.txt`);
      mkdirSync(path.dirname(probe), { recursive: true });
      writeFileSync(probe, 'probe by sc_console_paused_list\n', 'utf8');
      ok(true, `L3b write_set 探针落盘（${probe}）`);
    }

    console.log('== L4 resume → 行回 false → 续派到收口');
    const resume = cli('ticket', { op: 'resume', ticket_id: tid, input: { who: 'e2e-host', note: 'console 腿恢复' } }, fixture);
    ok(resume.body?.ok === true, 'L4 resume 信号回执 ok');
    const snapFin = await waitSnap(tid, (s) => s.paused === false, 'L4 引擎恢复（paused=false）', 240);
    if (!snapFin) { stopWorker('main-worker'); process.exit(1); }
    const rowFin = await waitRow(tid, (r) => r.paused === false, 'L4 console 行 paused 回 false', 90);
    if (rowFin) ok(rowFin.paused === false && (rowFin.paused_phase ?? '') === '', 'L4 console 行二态清干净');
    // merge 人门：预置 verdict 使链走到 merge awaiting-human，human sign approve 放行
    const snapMerge = await waitSnap(tid, (s) => s.stage === 'merge' && s.stage_state === 'awaiting-human',
      'L4 走到 merge 人门', 420);   // 含 run_integration_tests 相位（嵌套场景在夹具道 env_fail 秒过，sc 同款预算）
    if (snapMerge) {
      const sign = cli('ticket', { op: 'sign', ticket_id: tid,
        input: { who: 'e2e-human', gate: 'merge', decision: 'approve', note: 't260910-04 e2e 放行' } }, fixture);
      ok(sign.body?.ok === true, 'L4 merge sign approve 回执 ok');
    }
    // 收口：COMPLETED 后行仍健康（水合窗内 closed 行 paused=false 在场——closed 超窗极简行
    // 与 KI-008 降级行不带 paused 键，按行分支分别断言：在场键必布尔，缺键不 throw）
    const fin = await waitSnap(tid, (s) => s.status === 'closed' || s.stage_state === 'done',
      'L4 工单续派到收口', 300);
    if (fin) {
      // 180s 预算（gen2 验收修正）：列表行可见性走 SA 传播，本场景 L2c 自己实测
      // 「秒级~分钟级」——60s 旧预算与该文档矛盾，负载窗（run 260910-232102 同族
      // 时段）实测 60s 不现身=假红。行在场仍是真断言，只是预算对齐传播现实。
      const rowClosed = await waitRow(tid, (r) => true, 'L4 收口后 console 行在场', 180);
      if (rowClosed) {
        ok(typeof rowClosed.paused === 'boolean' || rowClosed.paused === undefined,
           'L4 收口行：paused 在场必布尔 / 缺键不 throw（行分支契约）');
        if (typeof rowClosed.paused === 'boolean') {
          ok(rowClosed.paused === false, 'L4 水合窗内收口行 paused===false');
        }
      }
    }
    stopWorker('main-worker');
    // host 白名单回归（设计段补腿）：列表主数据下放引擎后，缺 project/未知 key 的
    // 400 面必须原样保住（host 层 findProject 校验不随取数通路切换而丢）。
    console.log('== L5 host 白名单回归（400 面不丢）');
    {
      const r0 = await fetchJson(`${G.base}/sandbar-workbench/api/wf/tickets`).catch(() => null);
      ok(r0?.status === 400, `L5 缺 project → 400（实得 ${r0?.status}）`);
      const r1 = await fetchJson(`${G.base}/sandbar-workbench/api/wf/tickets?project=no-such-key-${RUN_TAG_SUFFIX}`).catch(() => null);
      ok(r1?.status === 400, `L5 未知 key → 400（实得 ${r1?.status}）`);
    }
    // 台面回收腿（资源生命周期纪律）：私有台 stageDown 零残留断言；异常出口由
    // exit 钩子兜底同款回收（见 L0b）。
    console.log('== L7 私有台回收（stageDown 零残留）');
    {
      const down = sh('python3', [path.join(INTEG, 'stage_docker.py'), 'down', '--project', STAGE_PROJECT], { timeout: 180_000 });
      let residue = null;
      try { residue = JSON.parse(String(down.stdout ?? '').trim().split('\n').at(-1) ?? '{}'); } catch { /* 解析失败按红处置 */ }
      const leftovers = Object.values(residue?.residue ?? {}).flat();
      ok(down.status === 0 && leftovers.length === 0,
         `L7 stageDown 零残留（residue=${JSON.stringify(residue?.residue ?? '解析失败').slice(0, 120)}）`);
    }
    console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
    process.exit(fail === 0 ? 0 : 1);
  } finally {
    stopWorker('finally-cleanup');
    if (fail > 0 && worker?._logTail) console.error(`[worker log tail]\n${worker._logTail()}`);
    if (fail > 0) {
      console.error(`[diag] fail>0：现场保留于 ${tmp}（SANDBAR_T91004_KEEP_TMP=1 语义常开）`);
    } else {
      try { rmSync(tmp, { recursive: true, force: true }); } catch { /* tmp 兜底 */ }
    }
  }
}

main().catch((e) => { console.error(String(e?.stack ?? e)); process.exit(2); });
