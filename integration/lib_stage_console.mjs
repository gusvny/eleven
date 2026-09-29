// lib_stage_console.mjs — shared console supply for stage-based scenarios (tickets t260904-19, t260906-01).
//
// Scenarios in this family get their test console here, via one of two paths:
//   1. env SANDBAR_TEST_CONSOLE points at a console explicitly (manual path);
//   2. a long-lived stage is started per tested tree (= lane), named
//      stage-console-<tree-hash-8>.
//
// Why one console per lane instead of one global console: the old global one
// was "first lane to ensure wins" — whichever lane ensured first had its /repo
// mounted forever, and every later lane tested someone else's code (six hours
// of browser legs ran against the wrong tree, t260906-01). Parallel lanes also
// trampled each other on the same compose project name (container conflicts,
// mount source being swapped, containers killed). With tree-derived names each
// lane gets its own console and lanes never fight.
//
// A failed boot (docker/image missing, unhealthy stage) = honest environment
// red: print the CLI's STAGE_ line and process.exit(2) — three-state contract
// holds, never a fake green.
//
// Supply budget (t260905-07): must stay strictly below the executor's per-
// scenario kill cap (900s). If the budget is >= the cap, "cannot supply" ends
// as an executor SIGKILL (exit -9), the scenario's ENV_FAIL never lands, and
// the reason is lost. Default 600s leaves 300s for the real legs. Slower
// first-time environments can raise SANDBAR_STAGE_ENSURE_TIMEOUT (raise the
// executor cap together with it).
//
// Long-lived stage lifecycle = permanent infra: scenarios do NOT tear the
// stage down on exit; teardown belongs to the supply side / humans
// (down --project stage-console-<tree-hash>).
//
// Fixture seeding (260908): stage-based scenarios (ticket-session-restore /
// the t260903-07 family / ticket-evidence-images) need real ticket rows and
// evidence images on the console. They used to be env_fail permanently, for
// two reasons:
// 1. the test image has no temporalio, so the in-container toolchain failed
//    silently with ok:false and the ticket list was always empty;
// 2. nobody seeded fixtures — it was all manual.
// This module self-heals after ensure:
//   - the python registry (per-key directory format) is seeded into
//     /fixtures/projects (lives and dies with the stage, zero host residue);
//   - 3 fixture tickets across 2 projects (seedws x2 + seedq x1 — the multi-row
//     click leg needs >=2 rows, the cross-project color leg needs >=2 projects
//     with tickets). Ticket ids use the t<yymmdd>-<NN> shape — the chat tag
//     reference whitelist only accepts that shape. Tickets are created from
//     the host-side engine venv against THIS stage's temporal (SA=ProjectKey
//     is what the in-container list reads); the old short ids integfix1/2 are
//     cleaned up per stage;
//   - one evidence PNG per ticket lands at
//     <tested-tree>/.suyou/evidence/<ticket-id>/  // naming-compat: archive path is an existing convention
//     (/repo is a read-only mount, so writing at the host repo root makes it
//     visible in the container — the data source for the drawer evidence leg).
// The whole chain is idempotent (count by ticket id, top up only what is
// missing); a seeding failure does not block supply — each scenario's fixture
// leg names it as env_fail (three-state contract, never fake green).
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isTransient } from './lib_transient_retry.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, 'stage_docker.py');
// 1x1 PNG (same bytes as sc_ticket_evidence_images) — fixture ticket drawer
// evidence image.
const PNG_1X1_HEX =
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
  '0000000d4944415478da63fcffff3f030005fe02fea72d1f240000000049454e44ae426082';
// The tested tree = the parent of integration/ (same rule as stage_docker.py's
// REPO=__file__.parent.parent — going up only one level from the directory;
// one more level up would be the lane's parent directory, which t260905-05
// proved mounts the wrong dir and makes the compose admin.log mount EROFS).
// This is also the "lane fingerprint" from the t260906-01 gen3 ruling: same
// tree = same lane = same stage name, different trees never collide.
const WANT_REPO = path.resolve(HERE, '..');
// One long-lived stage project name per tested tree (first 8 hex chars of the
// path hash; same tree = same name = reuse, different trees never collide).
const TREE_PROJECT = `stage-console-${createHash('sha256').update(WANT_REPO).digest('hex').slice(0, 8)}`;

/** The running stage's /repo mount source (host-side tested tree); null when
 * the container is absent or not inspectable. */
function repoMountSource(project, env) {
  const p = spawnSync('docker', ['inspect', `${project}-dsh`, '--format',
    '{{range .Mounts}}{{if eq .Destination "/repo"}}{{.Source}}{{end}}{{end}}'],
  { encoding: 'utf8', env, timeout: 15000 });
  if (p.status !== 0) return null;
  const s = String(p.stdout || '').trim();
  return s || null;
}

export async function ensureStageConsole({ services = 'full', project = TREE_PROJECT } = {}) {
  if (process.env.SANDBAR_TEST_CONSOLE) {
    return { base: process.env.SANDBAR_TEST_CONSOLE.replace(/\/$/, ''), project: '(external)', teardown: () => {} };
  }
  // daemon 预检（260916 仲裁归因修正，t260915-19）：容器运行时未起/ socket 激活挂死时
  // （OrbStack 装了 socket-activation，连 socket 会触发惰性拉起，起不来=CLI 无限等），
  // docker CLI 挂到自身超时——供给帽内烧满 600-900s 才落诚实环境红（run_scenarios 供给
  // 面 ran=0 超时的同族根因）。此处 5s 探针先行：daemon 无响应=立即环境红点名，
  // 判定语义零变化（仍是三态 env_fail），只把「烧帽等死」收敛为「秒级点名」。
  {
    const probe = spawnSync('docker', ['version', '--format', '{{.Server.Version}}'],
      { encoding: 'utf8', timeout: 5000 });
    if (probe.error || probe.status !== 0) {
      console.error('[ENV_FAIL] stage-console — docker 守护进程不可达（5s 预检无响应/失败：'
        + `${probe.error?.code ?? probe.status ?? 'rc=' + probe.status}）。`
        + '先起容器运行时（OrbStack/Docker Desktop）再重跑；宿主 3099 红线不碰。');
      process.exit(2);
    }
  }
  // Fixture host directory: one per stage (= per tree), lives and dies with
  // the stage; mounted into the container as /fixtures (rw).
  const FIXTURES_HOST = path.join('/tmp', `sandbar-fixtures-${TREE_PROJECT.slice(-8)}`);
  mkdirSync(FIXTURES_HOST, { recursive: true });
  const env = {
    ...process.env,
    // 锁根纪律（t260904-19 拓扑注释同款）：不设 SANDBAR_STAGE_LOCK_DIR，
    // 与所有生产调用方共享 stage_docker 缺省锁根（~/.sandbar/test-stages，
    // 不可写时自带降级）——flock 档位互斥只在共享根下成立。260909 提速战役③
    // 终验实锤：本行曾私指 /tmp，链台与 engine 族各拿各的档位锁，双命名空间
    // 互不可见→同档撞端口（run F/J 的 L1 红即此族）。用户显式 env 经
    // ...process.env 透传不受影响。
    // Registry root for the in-container python engine chain (an in-container
    // path inside the rw mount — see the "fixture seeding" section above;
    // before 260908 this was pinned to /nonexistent, so the toolchain always
    // saw an empty registry). stage_docker reads this knob from env (no CLI
    // flag): compose_env passes it into the container.
    SANDBAR_TEST_PROJECTS_DIR: '/fixtures/projects',
    // GUI session model is supplied by the stage (the compose step rewrites
    // agent-default-model): when deepseek is out of credit, the turn error
    // rolls back the user message line and chat tag scenarios go red
    // permanently; kimi-coding/k3 measured healthy (260908). The product
    // default (server/profile) stays untouched — this env only affects the
    // test stage.
    SANDBAR_TEST_GUI_MODEL: 'kimi-coding/k3',
  };
  // Before reuse, verify the /repo mount source is this tree. A wrong tree or
  // an empty shell (mount source directory was deleted — same wrong-tree
  // shape as KI-052) gets torn down and rebuilt (self-heal). The stage name
  // is tree-derived so a different tree never reuses this stage at all — this
  // check only covers drift/cleanup within this tree's own stage.
  const mounted = repoMountSource(project, env);
  if (mounted && (mounted !== WANT_REPO || !existsSync(mounted))) {
    spawnSync('python3', [CLI, 'down', '--project', project],
      { encoding: 'utf8', env, timeout: 180000 });
  }
  // Supply budget: default 600s, strictly below the executor's current 900s
  // per-scenario kill cap (see the header budget section; t260905-02 ruled:
  // being killed by the executor during ensure means empty stdout and a lost
  // reason). With the budget below the cap, "cannot supply" lands as an
  // honest env_fail exit 2 naming the stage. Healthy reuse returns in seconds.
  const ensureBudget = Number(process.env.SANDBAR_STAGE_ENSURE_TIMEOUT || 600);
  // 260912 仲裁第 10 次进段自查修正：本段各次 ensure 必须**共享同一个总预算**，
  // 不能每次各拿满 600s——否则「初试 + 瞬态重试 + 自愈(down + 重 ensure)」叠加可把
  // 单条场景的供给时间放大到 20~40 分钟：既破坏了本文件原有不变式「供给帽 600s
  // 严格低于执行器 900s/场景 kill 帽」，也是多泳道风暴下套件 wall 冲过机械步外层
  // 预算（主树 INTEG_RUN_TO=60min）的助推因素。改为按总预算衰减下发每次 --timeout，
  // 预算耗尽即不再重试、直接以诚实 env_fail 收口（判定语义与断言一律不变）。
  const ensureDeadline = Date.now() + ensureBudget * 1000 + 60_000;
  const remainingSec = () => Math.max(0, Math.ceil((ensureDeadline - Date.now()) / 1000));
  const ensureOnce = () => {
    const budget = Math.min(ensureBudget, remainingSec());
    if (budget <= 30) {
      return { status: 1, error: null,
        stderr: `STAGE_ENSURE: 供给总预算已耗尽（前置尝试/自愈已用尽 ${ensureBudget}s 帽）` };
    }
    return spawnSync('python3', [CLI, 'ensure', '--project', project, '--keep',
      '--repo-dir', WANT_REPO,
      '--services', services,
      '--fixtures-dir', FIXTURES_HOST,
      '--timeout', String(budget)],
      { encoding: 'utf8', env, timeout: budget * 1000 + 60_000 });
  };
  let p = ensureOnce();
  if ((p.error || p.status !== 0) && isTransient(String(p.stderr ?? ''))) {
    // 瞬态重试（t260910-12 目标④）：命中白名单（502/拒连/起台面繁忙）自动
    // 重试一次——判定走 lib_transient_retry 单源；仍红才按环境红收口。
    console.error('[stage-console] ensure 红命中瞬态白名单，2s 后自动重试一次');
    p = ensureOnce();
  }
  // FM-B 自愈（260911 仲裁多轮实锤）：`~/.sandbar` 可写性震荡→锁根降级后本根无租约
  // 而本台容器仍在跑→stage_docker 报「有无主容器在跑（租约已死/缺失）」拒起——18 条
  // 台面族场景连片环境红的唯一根因。判定式命中即视为**本泳道自己的孤儿台**（project
  // 名由本树路径哈希派生，不可能指向他泳道）；down 本台（幂等回收）+ 重 ensure 一次
  // =自愈。只动本项目，绝不触碰任何别的泳道容器；仍红才按环境红收口。
  if ((p.error || p.status !== 0) && /有无主容器在跑/.test(String(p.stderr ?? ''))) {
    console.error('[stage-console] 自愈：本台容器在跑而无主租约（锁根震荡假孤儿），down 本台后重 ensure 一次');
    spawnSync('python3', [CLI, 'down', '--project', project],
      { encoding: 'utf8', env, timeout: 180000 });
    p = ensureOnce();
    if ((p.error || p.status !== 0) && isTransient(String(p.stderr ?? ''))) p = ensureOnce();
  }
  if (p.error || p.status !== 0) {
    const named = String(p.stderr ?? '').split('\n').filter((l) => l.startsWith('STAGE_')).at(-1);
    const why = p.error
      ? `ensure 超时/不可执行（${ensureBudget}s 供给帽，${p.error.code ?? p.error.name ?? p.error}）`
      : `rc=${p.status} ${String(p.stderr ?? '').slice(0, 200)}`;
    // Precision: after the STAGE_ line, append the tail of the CLI stderr
    // (compose diagnostics) — never keep just a conclusion and drop evidence.
    console.error(`[ENV_FAIL] stage-console — ${named ?? why}\n${String(p.stderr ?? '').slice(-600)}`);
    process.exit(2);
  }
  let st = JSON.parse(String(p.stdout).trim().split('\n').at(-1));
  // 身份验证（260911 仲裁实锤，t260906-01 异树病还魂形态）：ensure 曾在租约/
  // 容器churn 窗口返回本项目的名字+端口，但该端口实际被另一棵树（他泳道）的
  // console 容器持有——本树场景连上别家台面，「产品卡缺失」假红。base 必须由
  // 本项目自己的 -dsh 容器持有；不持即拆重 ensure 一次，仍不持=诚实环境红。
  const portHeldByOwn = () => {
    const q = spawnSync('docker', ['port', `${st.project}-dsh`, '3199'],
      { encoding: 'utf8', timeout: 15000 });
    return q.status === 0 && String(q.stdout).includes(`:${st.ports.console}`);
  };
  if (!portHeldByOwn()) {
    console.error('[stage-console] base 未由本项目容器持有（端口改配/异树串连窗），down 后重 ensure 一次');
    spawnSync('python3', [CLI, 'down', '--project', st.project],
      { encoding: 'utf8', env, timeout: 180000 });
    p = ensureOnce();
    if ((p.error || p.status !== 0) && isTransient(String(p.stderr ?? ''))) p = ensureOnce();
    if (p.error || p.status !== 0) {
      const named = String(p.stderr ?? '').split('\n').filter((l) => l.startsWith('STAGE_')).at(-1);
      console.error(`[ENV_FAIL] stage-console — 重 ensure 仍失败：${named ?? `rc=${p.status}`}\n${String(p.stderr ?? '').slice(-600)}`);
      process.exit(2);
    }
    st = JSON.parse(String(p.stdout).trim().split('\n').at(-1));
    if (!portHeldByOwn()) {
      console.error('[ENV_FAIL] stage-console — 重 ensure 后 base 仍非本项目容器持有（跨树串连窗，稍后重跑）：'
        + `project=${st.project} port=${st.ports.console}`);
      process.exit(2);
    }
  }
  const SEED = { key: 'seedws', name: 'SeedWs' };
  // In-container fixture project seeding (gen6 ruling, option b): the default
  // registry's suyou entries point at host absolute paths that the container
  // cannot see → session/workspace creation honestly refuses (WorkspaceCreateError
  // in practice). The seed project is an in-container writable directory; add
  // is idempotent (409 on existing is tolerated).
  const dir = `/tmp/seed-${SEED.key}`;
  try {
    spawnSync('docker', ['exec', `${st.project}-dsh`, 'mkdir', '-p', dir],
      { env, timeout: 30000 });
    await fetch(`http://127.0.0.1:${st.ports.console}/sandbar-workbench/api/wf/projects/add`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: SEED.key, name: SEED.name, dir, dry_run: false }),
    }).catch(() => {});
  } catch { /* seeding failure does not block supply: each scenario names it as env_fail */ }
  // 260909 提速战役③终验 run K 实锤：冷台首跑时 seedFixtures 曾 fire-and-
  // forget——播种在途（未失败）而场景已开跑，先手的链头场景断言夹具票行
  // 必 env_fail（11 连ENV_FAIL即此族；热台被存量掩住，冷暴露随锁根归一
  // 首次现形）。语义不变（播种失败仍不阻断供给、由各场景 fixture 子用例点名
  // env_fail），只把「在途竞态」收敛为「完成才放行」。并发 ensure 下同票
  // 竞建由 create 后的重列兜底：对方建成=本方顶补成功（幂等口径不变）。
  try {
    await seedFixtures(st, FIXTURES_HOST);
  } catch (e) {
    console.warn(`[stage-console] fixture seeding failed (scenario fixture legs will name env_fail): ${e}`);
  }
  return {
    base: `http://127.0.0.1:${st.ports.console}`,
    project: st.project,
    seed: SEED,
    fixturesDir: FIXTURES_HOST,
    teardown: () => { /* lane-long-lived stage: scenarios do not tear it down */ },
  };
}

/** Fixture seeding (the design landing point of the header section). Idempotent;
 * failures throw to the caller's warning. */
async function seedFixtures(st, fixturesHost) {
  // 0. Per-stage seeding mutex（run S 实锤：播种曾多场景并发，listIds→create
  //    之间的 advanced-visibility 传播滞后让后到者把已收口（COMPLETED）的
  //    票同名重建——Temporal 允许 closed 后重用 workflow id——留下 RUNNING
  //    且无 worker 的残留票：此后每张列表查询为它付 8s 快照查询超时
  //    （QUERY_TIMEOUT_S），3 票 ≈25.5s，场景行渲染预算被击穿（run L/M/O/
  //    Q/S 的 fixture 行族 env_fail）。锁内单播种者 + 播种后全票 describe
  //    核验收口（2c），双保险。锁=目录原子建删；持锁者崩溃会留锁，等待
  //    有 4min 帽，超时按无锁顶补路径继续（幂等，不裸等）。
  const SEED_LOCK = path.join(fixturesHost, '.seeding-lock');
  let lockOwner = false;
  {
    const t0 = Date.now();
    for (;;) {
      try {
        mkdirSync(SEED_LOCK);
        lockOwner = true;
        break;
      } catch {
        if (Date.now() - t0 > 240_000) break;
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
  }
  try {
    await seedFixturesLocked(st, fixturesHost);
  } finally {
    if (lockOwner) {
      try { rmSync(SEED_LOCK, { recursive: true, force: true }); } catch { /* 留锁不阻断：下一场等满帽后走顶补 */ }
    }
  }
}

async function seedFixturesLocked(st, fixturesHost) {
  // 1. In-container python engine-chain registry (per-key directory format,
  //    schema v1): /fixtures/projects/<key>/project.yaml + in-container
  //    writable project root /fixtures/<key>. Two fixture projects: seedws
  //    (two tickets) + seedq (one ticket) — the cross-project color leg needs
  //    at least two projects with tickets.
  const regYamlFor = (key, name) =>
    'schema: v1\nproject:\n' +
    `  - key: ${key}\n    name: ${name}\n    dirs:\n` +
    `      - /fixtures/${key}\n`;
  const seedProjects = [
    { key: STAGE_SEED.key, name: STAGE_SEED.name, ids: FIXTURE_TICKET_IDS },
    { key: STAGE_SEED_B.key, name: STAGE_SEED_B.name, ids: FIXTURE_TICKET_IDS_B },
  ];
  for (const sp of seedProjects) {
    mkdirSync(path.join(fixturesHost, sp.key), { recursive: true });
    mkdirSync(path.join(fixturesHost, 'projects', sp.key), { recursive: true });
    writeFileSync(path.join(fixturesHost, 'projects', sp.key, 'project.yaml'), regYamlFor(sp.key, sp.name));
  }
  // 2. Host-side ticket creation environment: legacy single-file registry
  //    (create only uses the whitelist + lane path derivation; the paths land
  //    in host temp dirs, unrelated to the container side) + this stage's
  //    temporal address/namespace.
  const legacyYaml = path.join(fixturesHost, 'fixture-registry.yaml');
  writeFileSync(legacyYaml,
    'projects:\n' +
    seedProjects.map((sp) => {
      const hostDir = `/tmp/seed-${sp.key}-host`;
      mkdirSync(hostDir, { recursive: true });
      return `  - key: ${sp.key}\n    name: ${sp.name}\n    dirs:\n      - ${hostDir}\n`;
    }).join(''));
  const py = process.env.SANDBAR_ENGINE_PY
    || path.join(WANT_REPO, 'server', 'engine', '.venv', 'bin', 'python');
  if (!existsSync(py)) throw new Error(`host engine venv missing: ${py}`);
  // namespace fallback = the compose contract default (sandbar-test; t260917-07
  // finished the d342b46 rename). st.namespace from the stage JSON is authoritative.
  const toolEnv = {
    ...process.env,
    SANDBAR_PROJECTS_YAML: legacyYaml,
    SANDBAR_TARGET_HOST: `127.0.0.1:${st.ports.temporal}`,
    SANDBAR_NAMESPACE: st.namespace || 'sandbar-test',  // 台回报值优先；回落=契约缺省（t260917-07）
  };
  // 260928：工具调用允许**按项目覆盖身份**。为什么必须能覆盖：夹具票建在种子项目
  // （sp.key，如 seedws）里，而本进程的 env 带着运行票自己的身份
  // SANDBAR_CALLER_PROJECT=sandbar（引擎 spawn 链注入）——不改的话 ticket.py create
  // 会被跨项目闸 fail-closed 拒收（实案：`跨项目写操作拒收：调用方项目身份 sandbar 与
  // 目标票所属项目 seedws 不符`），播种失败 ⇒ 台面夹具缺席 ⇒ 所有依赖夹具的场景一起红
  // （t260928-13 的 merge 门就卡在这两条共享红上）。声明「调用方=该夹具项目自身」后，
  // 身份与目标一致，闸如实放行。
  const runTool = (argsJson, env = toolEnv) => spawnSync(py, ['-c',
    'import sys, json; sys.path.insert(0, "server/tools"); import ticket;'
    + ' print(json.dumps(ticket.run(json.loads(sys.argv[1])), ensure_ascii=False))',
    argsJson],
    { encoding: 'utf8', env, cwd: WANT_REPO, timeout: 180_000 });
  // Ticket ids use the t<yymmdd>-<NN> shape: the chat project tag's ticket
  // reference whitelist only accepts /t\d{6}-\d{2}/ — the old short ids
  // (integfix1/2) are never indexed, so the t02 chip leg was red permanently
  // (proven 260908). Idempotence anchor = the list's id (no worker query
  // needed; the title degrades when there is no worker).
  // SA 生效窗（t260914-01 arbitrate gen4 实测）：台冷启动时 namespace/SA 注册与
  // 首个消费者的 ticket-list 之间存在短窗（同刻多泳道起台时更明显）——客户端会拿到
  // `column name 'ProjectKey' is not a valid search attribute`。staged 工具自身对
  // namespace 未就绪窗就用「重试 3×2s」吸收（stage_docker.register_namespace），
  // 夹具这里同口径吸收同一窗；**重试后仍失败=照旧响亮红**（真缺 SA 绝不放过），
  // 且报错点名台身份（project/address/namespace）——旧文案只贴 stderr 尾巴，
  // 无从判断「查的是哪台哪个 namespace」（本次定位耗时即此）。
  const SA_NOT_READY = /is not a valid search attribute/i;
  const listIds = (project) => {
    let out;
    for (let attempt = 0; attempt < 3; attempt++) {
      out = runTool(JSON.stringify({ op: 'list', project }));
      if (out.status === 0) break;
      const tail = `${out.stderr || ''}${out.stdout || ''}`;
      if (attempt < 2 && SA_NOT_READY.test(tail)) {   // 只在 SA 生效窗上重试，其它错误立即红
        spawnSync('sleep', ['2']);
        continue;
      }
      break;
    }
    if (out.status !== 0) {
      throw new Error('fixture ticket count failed'
        + `（台 project=${project} address=127.0.0.1:${st.ports.temporal}`
        + ` namespace=${toolEnv.SANDBAR_NAMESPACE}）：${out.stderr?.slice(-200)}`);
    }
    return new Set((JSON.parse(out.stdout.trim())?.tickets ?? []).map((t) => t?.id));
  };
  for (const sp of seedProjects) {
    const have = listIds(sp.key);
    for (const fid of sp.ids) {
      if (have.has(fid)) continue;
      const projEnv = { ...toolEnv, SANDBAR_CALLER_PROJECT: sp.key };
      const createOut = runTool(JSON.stringify({
        op: 'create', project: sp.key, id: fid, workflow: 'dev-lane',
        title: `${FIXTURE_TITLE_PREFIX} ${fid}（勿动）`,
        body: '测试台夹具票：供集成场景行卡/抽屉/tag 断言使用，人手勿操作',
        allow_empty_write_set: true,
      }), projEnv);
      if (createOut.status !== 0) {
        // 并发 ensure 下同票竞建（run K 供给在途竞态修复后，多场景 t=0 齐
        // 调 ensure，播种不再 fire-and-forget）：本方 create 撞上「workflow
        // id 已存在」即对方刚建成——重列确认在场则视同本方顶补成功，幂等
        // 口径不变；真失败（对方也没建成）才抛。
        if (listIds(sp.key).has(fid)) continue;
        throw new Error(`fixture ticket ${fid} create failed: ${createOut.stderr?.slice(-200)}`);
      }
    }
  }
  // 2a. Clean up the old short-id fixtures: integfix1/2 are outside the tag
  //     whitelist shape, so they only pollute row order and the t02 list[0]
  //     sample. Idempotent (a deleted id comes back NotFound, swallowed per
  //     ticket). temporalio 1.18's Client has no delete method — go through
  //     workflow_service directly (proven 260908: handle.delete() does not
  //     exist, and the old version silently swallowed everything, so the
  //     cleanup never actually ran).
  const LEGACY_FIXTURE_IDS = ['integfix1', 'integfix2'];
  spawnSync(py, ['-c', [
    'import sys, asyncio',
    'from temporalio.client import Client',
    'from temporalio.api.common.v1 import WorkflowExecution',
    'from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest',
    'async def main():',
    '    c = await Client.connect(sys.argv[1], namespace=sys.argv[2])',
    '    for tid in sys.argv[3].split(","):',
    '        try:',
    '            h = c.get_workflow_handle(tid)',
    '            d = await h.describe()',
    '            if d.status.name == "RUNNING": await h.terminate("fixture stray cleanup")',
    '            await c.workflow_service.delete_workflow_execution(',
    '                DeleteWorkflowExecutionRequest(namespace=c.namespace,',
    '                    workflow_execution=WorkflowExecution(workflow_id=tid)))',
    '            print("deleted", tid)',
    '        except Exception as e:',
    '            print("skipped", tid, type(e).__name__)',
    'asyncio.run(main())',
  ].join('\n'), `127.0.0.1:${st.ports.temporal}`, st.namespace || 'sandbar-test', LEGACY_FIXTURE_IDS.join(',')],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 60_000 });
  // 2b. Closing drain: fixture tickets are driven to COMPLETED by a fake
  // DevLaneWorkflow (the no-worker direct-read precondition of
  // fixture_ticket_fake.py's header). When tickets are already closed, the
  // drain worker's first poll round exits — seconds.
  const allIds = seedProjects.flatMap((sp) => sp.ids);
  const drain = () => {
    const drainOut = spawnSync(py, [path.join(HERE, 'fixture_ticket_worker.py'),
      `127.0.0.1:${st.ports.temporal}`, st.namespace || 'sandbar-test',  // 台回报值优先；回落=契约缺省
      allIds.join(','), '120'],
      { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 150_000 });
    if (drainOut.status !== 0) {
      throw new Error(`fixture ticket drain failed: ${(drainOut.stderr || '').slice(-200)}`);
    }
  };
  drain();
  // 2c. Post-drain verify（run S 实锤）： visibility 滞后造成的同名重建可能
  // 发生在任何一次顶补路径里——全票 describe 核验收口，残留 RUNNING 重 drain，
  // 有界三轮；收口票直读无 worker（fake 头注），这一步把「无 worker 残留票
  // → 列表 8s/票 查询超时」的根掐死在播种侧。
  const describeOpen = () => {
    const out = spawnSync(py, ['-c', [
      'import sys, json, asyncio',
      'from temporalio.client import Client',
      'async def main():',
      '    c = await Client.connect(sys.argv[1], namespace=sys.argv[2])',
      '    open_ids = []',
      '    for tid in sys.argv[3].split(","):',
      '        try:',
      '            d = await c.get_workflow_handle(tid).describe()',
      '            if (d.status.name if d.status is not None else "") != "COMPLETED": open_ids.append(tid)',
      '        except Exception:',
      '            open_ids.append(tid)',
      '    print(json.dumps(open_ids))',
      'asyncio.run(main())',
    ].join('\n'), `127.0.0.1:${st.ports.temporal}`, st.namespace || 'sandbar-test', allIds.join(',')],  // 台回报值优先；回落=契约缺省（见 toolEnv 同款）
      { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 60_000 });
    if (out.status !== 0) throw new Error(`fixture post-drain describe failed: ${(out.stderr || '').slice(-200)}`);
    return JSON.parse(String(out.stdout).trim() || '[]');
  };
  for (let round = 0; round < 3; round++) {
    const open = describeOpen();
    if (open.length === 0) break;
    console.warn(`[stage-console] fixture drain re-round ${round + 1}: ${open.join(',')} 未收口，重 drain`);
    drain();
  }
  // 2d. Fixture-body stray sweep（run S 实锤）：撞号避让（_uniq_v2 序号递增）
  // 曾让并发播种者把夹具票建成清单外 id（fixture body 相同）——此类残留
  // 不在 allIds 内、drain 永不收口、无 worker 使每张列表查询付 8s 超时。
  // 按 fixture body 特征（集成夹具票前缀，播种专属）精确识别清单外流浪票
  // 并 terminate：不误伤场景经 UI 自建的票（body 不同）。有界 50 张。
  // 入参 JSON 的 ensure_ascii 形（\uXXXX），marker 需同形比对才能命中。
  const markerEsc = FIXTURE_TITLE_PREFIX.replace(/[-￿]/g,
    (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
  const sweepOut = spawnSync(py, ['-c', [
    'import sys, json, asyncio',
    'from temporalio.client import Client',
    'async def main():',
    '    c = await Client.connect(sys.argv[1], namespace=sys.argv[2])',
    '    keep = set(sys.argv[3].split(",")); marker = sys.argv[4]',
    '    marker_esc = sys.argv[5]; cap = 50',
    '    killed = []',
    '    async for w in c.list_workflows("WorkflowType = \'DevLaneWorkflow\'"):',
    '        if cap <= 0: break',
    '        cap -= 1',
    '        if w.id in keep: continue',
    '        try:',
    '            hist = await c.get_workflow_handle(w.id).fetch_history()',
    '            evs = list(hist.events)',
    '            if not evs: continue',
    '            attrs = evs[0].workflow_execution_started_event_attributes',
    '            body = ""',
    '            for p in (attrs.input.payloads or []):',
    '                try:',
    // run S 实锤：p.data 是 bytes，str() 会把 JSON ensure_ascii 形的反斜杠
    // 再翻一倍（\\u6d4b → repr 四层），marker/markerEsc 永远失配、清扫静默空转。
    // 按 utf-8 解码后比对：此时 ensure_ascii 形恰为单层 \uXXXX，与 markerEsc 同形。
    '                    body += p.data.decode("utf-8", "replace") if isinstance(p.data, bytes) else str(p.data)',
    '                except Exception: pass',
    '            if marker not in body and marker_esc not in body: continue',
    '            if w.status is not None and w.status.name == "RUNNING":',
    '                await c.get_workflow_handle(w.id).terminate("fixture stray sweep")',
    '                killed.append(w.id)',
    '        except Exception:',
    '            continue',
    '    print(json.dumps(killed))',
    'asyncio.run(main())',
  ].join('\n'), `127.0.0.1:${st.ports.temporal}`, st.namespace || 'sandbar-test',  // 台回报值优先；回落=契约缺省（见 toolEnv 同款）
    allIds.join(','), FIXTURE_TITLE_PREFIX, markerEsc],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 120_000 });
  if (sweepOut.status === 0) {
    const killed = JSON.parse(String(sweepOut.stdout).trim() || '[]');
    if (killed.length) console.warn(`[stage-console] fixture stray sweep terminated: ${killed.join(',')}`);
  }
  // 3. Evidence images (the drawer evidence leg's data source; idempotent =
  // omit files that already exist). The evidence route reads per ticket id
  // (<ticket-id>/.suyou/evidence/<file>), independent of whether a workflow  // naming-compat
  // has a worker. Give every fixture ticket an image: row order is not
  // guaranteed, and clicking the wrong row means that ticket has no evidence
  // → the drawer image leg times out.
  // Land in two places: the repo root (the default anchor / no-project API
  // surface) + each fixture project root (after KI-057 the drawer's apiGet
  // always carries ?project=, and evidence enumeration anchors at
  // <project-root>/.suyou/evidence — with only the repo root, the project  // naming-compat
  // surface is empty and the drawer evidence section does not render at all,
  // proven when the stage was rebuilt on 260908).
  for (const sp of seedProjects) {
    for (const fid of sp.ids) {
      const png = Buffer.from(PNG_1X1_HEX, 'hex');
      for (const base of [WANT_REPO, path.join(fixturesHost, sp.key)]) {
        const evFile = path.join(base, '.suyou', 'evidence', fid, 'shot-fixture.png');  // naming-compat: archive path is an existing convention
        mkdirSync(path.dirname(evFile), { recursive: true });
        if (!existsSync(evFile)) writeFileSync(evFile, png);
      }
    }
  }
}

/** Fixture project anchor (gen6): row selector suffix; scenarios pin the seed
 * row with STAGE_SEED_ROW_SEL below (the default registry's legacy row comes
 * first, so first-row would anchor the wrong, non-writable workspace row). */
export const STAGE_SEED_ROW_SEL = '[data-wb-psess-row]:has([aria-label="New SeedWs session"])';
export const STAGE_SEED = { key: 'seedws', name: 'SeedWs' };
// Fixture ticket contract (seedFixtures): ids use the t<yymmdd>-<NN> shape —
// the chat project tag's ticket reference whitelist only accepts
// /t\d{6}-\d{2}/ (the old short ids integfix1/2 are never indexed, which kept
// the t02 chip leg red). Idempotence anchor = the list's id (no worker query
// needed; the title degrades when there is no worker). Counts: seedws >=2
// (t01 T4 multi-row click), seedq >=1 (the cross-project color leg needs >=2
// projects with tickets).
export const FIXTURE_TITLE_PREFIX = '集成夹具票';
export const FIXTURE_TICKET_IDS = ['t260908-81', 't260908-82'];
export const FIXTURE_TICKET_IDS_B = ['t260908-91'];
export const STAGE_SEED_B = { key: 'seedq', name: 'SeedQ' };
