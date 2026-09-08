// lib_stage_console.mjs —— 等台族统一控制台供给（t260904-19；t260906-01 仲裁改泳道限定台）。
//
// 唯一搭台纪律（integration/README.md 舞台纪律段）落地点：旧 compose 缺省固定口
// 3199 已不供给，本族场景经本助手拿控制台地址：
//   1. env SANDBAR_TEST_CONSOLE 显式指台（人工通路，兼容既有用法）；
//   2. 否则消费/自起常驻台，工程名按被测树（=泳道）派生：stage-console-<树哈希8位>。
//      演进脉络（t260906-01 仲裁 gen3 泳道限定 与 t260905-05 树哈希 两边同义合并）：
//      原全局单名 stage-console-shared 是「先到先得挂树」：先起泳道 ensure 把它的树
//      挂上 /repo，后续泳道健康复用=全在测别人家的 client（本票六小时浏览器腿全跑在
//      t260905-04 树上=错树假红/假绿）；并发泳道各自 up 还在同一工程名上互踩（容器名
//      冲突 compose rc=1 / 挂载源来回翻、容器被对家 kill 137 实录）。按树派生后每泳道
//      （worktree/主树）各得一台：bindings 与注册表种子只归本泳道写，根除「共享台绑定
//      创建泳道 /repo + ensure 健康复用永不换血」的跨泳道陈旧态（t260906-01 机械跑
//      实录：浏览器面在别泳道台上红绿失真 + 瞬态败）；确定性拿自己的树，npm i/apt
//      每台只付一次，泳道间零对抗。
// 起台失败（docker 缺席/镜像缺席/起台不健康）=诚实环境红：打印 CLI 的 STAGE_ 行
// 后 process.exit(2)——三态语义不变，绝不假绿。
// 供给预算纪律（t260905-07 仲裁）：起台预算必须严格低于套件执行器的单场景杀帽
// （现役 900s）——预算≥杀帽时「供给不了」永远以执行器 SIGKILL（exit -9）收场，
// 场景自己的 ENV_FAIL（exit 2+STAGE_ 名点）永无落地机会，归因信息全灭。默认 600s
// 留 300s 给场景真腿；首建特慢的环境用 SANDBAR_STAGE_ENSURE_TIMEOUT 调高（同时把
// 执行器帽调到预算之上）。
// 常驻台生命周期=常驻基建（同 verify.yaml supply 的 sandbar-test-integ 例外口径）：
// 场景退出**不拆台**；拆台归供给面/人工（down --project stage-console-<树哈希>）。
//
// 夹具自种（260908）：等台族场景（ticket-session-restore / t260903-07 族 /
// ticket-evidence-images）需要台上有真工单行 + 证据图，此前恒 env_fail——病根两层：
// ① 测试镜像无 temporalio，容器内 admin.py 工具链静默 ok:false，工单列表恒空；
// ② 没有自种机制，「环境无 fixture」靠人工。本模块在 ensure 后自愈供给：
//   - python 注册表（per-key 目录模式）种进 fixtures 挂载体（/fixtures/projects，
//     随台生灭、零宿主残留）；容器内引擎工具链白名单由此过；
//   - 夹具工单 ×3 跨两项目（seedws×2 + seedq×1；t01 多行点击 ≥2 行、t02 跨项目
//     配色 ≥2 个有票项目）：票号 t<yymmdd>-<NN> 形（chat tag 引用白名单只认此形），
//     ticket list 是纯 Temporal 读，建票从宿主侧 engine venv 打**本台** temporal
//     （SA=ProjectKey 即被容器内 list 读到）；旧短号 integfix1/2 逐台清场；
//   - 每票证据 PNG 落 <被测树>/.suyou/evidence/<票号>/（/repo 只读挂载下宿主仓根  // naming-compat：归档路径是存量约定
//     直写即容器可见；抽屉证据腿的数据源）。
//   全链幂等（按票号 id 清点，缺几张补几张）；种票失败不阻塞供给
//   ——各场景 fixture 腿自行 env_fail 点名（三态语义不变，绝不假绿）。
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, 'stage_docker.py');
// 1x1 PNG（与 sc_ticket_evidence_images 同款字节）——夹具票抽屉证据图。
const PNG_1X1_HEX =
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
  '0000000d4944415478da63fcffff3f030005fe02fea72d1f240000000049454e44ae426082';
// 被测树=执行本助手的树（integration/ 的上一级；对齐 stage_docker.py 的
// REPO=__file__.parent.parent——从目录出发只上跳一级，多跳一级=泳道父目录，
// t260905-05 仲裁实锤：错挂 .lane 目录导致 compose admin.log 挂载点 EROFS）。
// 即 t260906-01 仲裁 gen3 的「泳道指纹」：同树=同泳道恒同名复用，异树恒异名零对抗。
const WANT_REPO = path.resolve(HERE, '..');
// 每棵被测树一个常驻台工程名（路径哈希前 8 位；同树恒同名=复用，异树恒异名=零对抗）。
const TREE_PROJECT = `stage-console-${createHash('sha256').update(WANT_REPO).digest('hex').slice(0, 8)}`;

/** 在跑台 /repo 挂载源（宿主侧被测树）；容器不在/不可查=null。 */
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
  // 夹具宿主目录：每台（=每树）独立，随台生灭；挂进容器 /fixtures（rw）。
  const FIXTURES_HOST = path.join('/tmp', `sandbar-fixtures-${TREE_PROJECT.slice(-8)}`);
  mkdirSync(FIXTURES_HOST, { recursive: true });
  const env = {
    ...process.env,
    SANDBAR_STAGE_LOCK_DIR: process.env.SANDBAR_STAGE_LOCK_DIR || '/tmp/sandbar-test-stages',
    // 容器内 python 引擎链的注册表根（容器内路径，位于 rw 挂载体里；
    // 见文件头「夹具自种」段——260908 前钉 /nonexistent=工具链恒空表）。
    // stage_docker 从 env 读此旋钮（无 CLI 旗标）：compose_env 透传进容器。
    SANDBAR_TEST_PROJECTS_DIR: '/fixtures/projects',
    // GUI 会话模型=台内供给（compose 拷贝后改 agent-default-model）：deepseek 欠费时
    // turn error 回滚用户消息行，chat tag 场景恒红；kimi-coding/k3 实测健康（260908）。
    // 产品默认（server/profile）不动——本 env 只作用于测试台。
    SANDBAR_TEST_GUI_MODEL: 'kimi-coding/k3',
  };
  // 复用前核对 /repo 挂载源=本树；错树/空壳（挂载源目录已被清理，KI-052 同族
  // 错树形态）=拆了重起（self-heal）。本台工程名按树派生，异树永不复用——此核对
  // 只兜本树台面的目录清理/漂移，不再承担跨泳道仲裁。
  const mounted = repoMountSource(project, env);
  if (mounted && (mounted !== WANT_REPO || !existsSync(mounted))) {
    spawnSync('python3', [CLI, 'down', '--project', project],
      { encoding: 'utf8', env, timeout: 180000 });
  }
  // 供给预算：默认 600s（严格低于现役执行器 900s 单场景杀帽，见文件头纪律段；
  // t260905-02 仲裁实锤：ensure 重建期被执行器杀=stdout 空、归因全灭——预算压帽
  // 之下，供给拿不下=诚实 env_fail exit 2 点名）。首建特慢的环境用
  // SANDBAR_STAGE_ENSURE_TIMEOUT 调高（执行器帽须同步在其上）；健康复用秒级返回。
  const ensureBudget = Number(process.env.SANDBAR_STAGE_ENSURE_TIMEOUT || 600);
  const p = spawnSync('python3', [CLI, 'ensure', '--project', project, '--keep',
    '--repo-dir', WANT_REPO,
    '--services', services,
    '--fixtures-dir', FIXTURES_HOST,
    '--timeout', String(ensureBudget)],
  { encoding: 'utf8', env, timeout: ensureBudget * 1000 + 60_000 });
  if (p.error || p.status !== 0) {
    const named = String(p.stderr ?? '').split('\n').filter((l) => l.startsWith('STAGE_')).at(-1);
    const why = p.error
      ? `ensure 超时/不可执行（${ensureBudget}s 供给帽，${p.error.code ?? p.error.name ?? p.error}）`
      : `rc=${p.status} ${String(p.stderr ?? '').slice(0, 200)}`;
    // 报错精确性：STAGE_ 行后附 CLI stderr 尾（compose 诊断面），不做只留结论丢证据。
    console.error(`[ENV_FAIL] stage-console — ${named ?? why}\n${String(p.stderr ?? '').slice(-600)}`);
    process.exit(2);
  }
  const st = JSON.parse(String(p.stdout).trim().split('\n').at(-1));
  const SEED = { key: 'seedws', name: 'SeedWs' };
  // 容器侧夹具项目 seeding（gen6 拍板案 b）：缺省注册表的 suyou 条目指向
  // 宿主绝对路径，容器内不可见 → 会话/工作区创建诚实拒收（WorkspaceCreateError
  // 实录）。seed 项目=容器侧可写目录，add 幂等（已存在=409 容忍）。
  const dir = `/tmp/seed-${SEED.key}`;
  try {
    spawnSync('docker', ['exec', `${st.project}-dsh`, 'mkdir', '-p', dir],
      { env, timeout: 30000 });
    await fetch(`http://127.0.0.1:${st.ports.console}/sandbar-workbench/api/wf/projects/add`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: SEED.key, name: SEED.name, dir, dry_run: false }),
    }).catch(() => {});
  } catch { /* seeding 失败不阻塞供给：场景行锚找不到时各自 env_fail 点名 */ }
  seedFixtures(st, FIXTURES_HOST).catch((e) =>
    console.warn(`[stage-console] 夹具自种失败（场景 fixture 腿将 env_fail 点名）：${e}`));
  return {
    base: `http://127.0.0.1:${st.ports.console}`,
    project: st.project,
    seed: SEED,
    fixturesDir: FIXTURES_HOST,
    teardown: () => { /* 泳道常驻台：场景退出不拆（供给面/人工 down） */ },
  };
}

/** 夹具自种（文件头部「夹具自种」段的设计落点）。幂等；失败抛给调用方 warn。 */
async function seedFixtures(st, fixturesHost) {
  // ① 容器内 python 引擎链注册表（per-key 目录模式，schema v1）：
  //    /fixtures/projects/<key>/project.yaml + 容器内可写项目根 /fixtures/<key>。
  //    两个夹具项目：seedws（两票）+ seedq（一票）——t02 跨项目配色腿要 ≥2 个
  //    有票项目才凑得齐切换面。
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
  // ② 宿主侧建票环境：legacy 单文件注册表（建票只用过白名单+lane 路径推导，
  //    路径落在宿主临时目录，与容器面无关）+ 本台 temporal 地址/namespace。
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
  if (!existsSync(py)) throw new Error(`宿主 engine venv 缺席：${py}`);
  // naming-compat：suyou-test 是测试台 namespace 存量名（compose 缺省同），本仓侧不改。
  const toolEnv = {
    ...process.env,
    SANDBAR_PROJECTS_YAML: legacyYaml,
    SANDBAR_TARGET_HOST: `127.0.0.1:${st.ports.temporal}`,
    SANDBAR_NAMESPACE: st.namespace || 'suyou-test',  // naming-compat：ns 存量名随台
  };
  const runTool = (argsJson) => spawnSync(py, ['-c',
    'import sys, json; sys.path.insert(0, "server/tools"); import ticket;'
    + ' print(json.dumps(ticket.run(json.loads(sys.argv[1])), ensure_ascii=False))',
    argsJson],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 180_000 });
  // 票号=t<yymmdd>-<NN> 形：chat 项目 tag 的工单引用白名单（/t\d{6}-\d{2}/）只认
  // 这个形状——旧短号 integfix1/2 永远不会被 tag 索引收录，t02 chip 腿恒红（260908
  // 实锤）。幂等锚=list 的 id（不依赖 worker 查询；title 无 worker 时退化）。
  const listIds = (project) => {
    const out = runTool(JSON.stringify({ op: 'list', project }));
    if (out.status !== 0) throw new Error(`夹具票清点失败：${out.stderr?.slice(-200)}`);
    return new Set((JSON.parse(out.stdout.trim())?.tickets ?? []).map((t) => t?.id));
  };
  for (const sp of seedProjects) {
    const have = listIds(sp.key);
    for (const fid of sp.ids) {
      if (have.has(fid)) continue;
      const createOut = runTool(JSON.stringify({
        op: 'create', project: sp.key, id: fid, workflow: 'dev-lane',
        title: `${FIXTURE_TITLE_PREFIX} ${fid}（勿动）`,
        body: '测试台夹具票：供集成场景行卡/抽屉/tag 断言使用，人手勿操作',
        allow_empty_write_set: true,
      }));
      if (createOut.status !== 0) throw new Error(`夹具票 ${fid} 建票失败：${createOut.stderr?.slice(-200)}`);
    }
  }
  // ②a 旧短号夹具清场：integfix1/2 是 tag 白名单外形状，留在台上只会污染行序与
  //     t02 的 list[0] 取样。幂等（删过即 NotFound，逐票吞）。temporalio 1.18
  //     的 Client 无 delete 方法——直走 workflow_service（260908 实锤：handle
  //     .delete() 不存在，旧版静默全吞=清场从未生效）。
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
  ].join('\n'), `127.0.0.1:${st.ports.temporal}`, st.namespace || 'suyou-test', LEGACY_FIXTURE_IDS.join(',')],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 60_000 });
  // ②b 收口排水：夹具票由假 DevLaneWorkflow 跑到 COMPLETED（fixture_ticket_fake.py
  // 头注的免 worker 直读前提）。已收口的常态下排水 worker 首轮轮询即退，秒级。
  const allIds = seedProjects.flatMap((sp) => sp.ids);
  const drainOut = spawnSync(py, [path.join(HERE, 'fixture_ticket_worker.py'),
    `127.0.0.1:${st.ports.temporal}`, st.namespace || 'suyou-test',  // naming-compat：ns 存量名随台
    allIds.join(','), '120'],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 150_000 });
  if (drainOut.status !== 0) {
    throw new Error(`夹具票收口失败：${(drainOut.stderr || '').slice(-200)}`);
  }
  // ③ 证据图（抽屉证据腿数据源；幂等=文件在就不再写）。证据路由按票号文件
  //    直读（.suyou/evidence/<票号>/），与 workflow 是否有 worker 无关。  // naming-compat：归档路径是存量约定
  //    每张夹具票都给：行序不保证，点错行=该票无证据→抽屉图腿超时。
  //    落两处：仓根（默认锚/no-project API 面）+ 各夹具项目根（KI-057 之后抽屉
  //    的 apiGet 统一带 ?project=，证据枚举按项目锚=<项目根>/.suyou/evidence——  // naming-compat：归档路径是存量约定
  //    只落仓根时项目面带全空，抽屉证据段整体不渲染，260908 重建台实锤）。
  for (const sp of seedProjects) {
    for (const fid of sp.ids) {
      const png = Buffer.from(PNG_1X1_HEX, 'hex');
      for (const base of [WANT_REPO, path.join(fixturesHost, sp.key)]) {
        const evFile = path.join(base, '.suyou', 'evidence', fid, 'shot-fixture.png');  // naming-compat：归档路径是存量约定
        mkdirSync(path.dirname(evFile), { recursive: true });
        if (!existsSync(evFile)) writeFileSync(evFile, png);
      }
    }
  }
}

/** 夹具项目锚（gen6）：行选择器后缀，场景用
 *  `[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])` 精确锚 seed 行
 *  （注册表缺省 suyou 行在前，first-row 会错锚到不可写工作区行）。 */
export const STAGE_SEED_ROW_SEL = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])';
export const STAGE_SEED = { key: 'seedws', name: 'SeedWs' };
// 夹具票口径（seedFixtures）：t<yymmdd>-<NN> 形——chat 项目 tag 的工单引用白名单
// 只认 /t\d{6}-\d{2}/（旧短号 integfix1/2 永不被 tag 索引收录，t02 chip 腿恒红的
// 病根）；幂等锚=list 的 id（不依赖 worker 查询；title 无 worker 时退化）。张数：
// seedws ≥2（t01 T4 多行点击），seedq ≥1（t02 跨项目配色腿要 ≥2 个有票项目）。
export const FIXTURE_TITLE_PREFIX = '集成夹具票';
export const FIXTURE_TICKET_IDS = ['t260908-81', 't260908-82'];
export const FIXTURE_TICKET_IDS_B = ['t260908-91'];
export const STAGE_SEED_B = { key: 'seedq', name: 'SeedQ' };
