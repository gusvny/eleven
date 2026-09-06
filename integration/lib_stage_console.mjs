// lib_stage_console.mjs —— 等台族统一控制台供给（t260904-19；t260906-01 仲裁改泳道限定台）。
//
// 唯一搭台纪律（integration/README.md 舞台纪律段）落地点：旧 compose 缺省固定口
// 3199 已不供给，本族场景经本助手拿控制台地址：
//   1. env SUYOU_TEST_CONSOLE 显式指台（人工通路，兼容既有用法）；
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
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, 'stage_docker.py');
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
  if (process.env.SUYOU_TEST_CONSOLE) {
    return { base: process.env.SUYOU_TEST_CONSOLE.replace(/\/$/, ''), project: '(external)', teardown: () => {} };
  }
  const env = {
    ...process.env,
    SANDBAR_STAGE_LOCK_DIR: process.env.SANDBAR_STAGE_LOCK_DIR || '/tmp/sandbar-test-stages',
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
    '--services', services, '--timeout', String(ensureBudget)],
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
    await fetch(`http://127.0.0.1:${st.ports.console}/suyou-workbench/api/wf/projects/add`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: SEED.key, name: SEED.name, dir, dry_run: false }),
    }).catch(() => {});
  } catch { /* seeding 失败不阻塞供给：场景行锚找不到时各自 env_fail 点名 */ }
  return {
    base: `http://127.0.0.1:${st.ports.console}`,
    project: st.project,
    seed: SEED,
    teardown: () => { /* 泳道常驻台：场景退出不拆（供给面/人工 down） */ },
  };
}

/** 夹具项目锚（gen6）：行选择器后缀，场景用
 *  `[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])` 精确锚 seed 行
 *  （注册表缺省 suyou 行在前，first-row 会错锚到不可写工作区行）。 */
export const STAGE_SEED_ROW_SEL = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])';
export const STAGE_SEED = { key: 'seedws', name: 'SeedWs' };
