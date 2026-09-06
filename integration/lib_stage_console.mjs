// lib_stage_console.mjs —— 等台族统一控制台供给（t260904-19）。
//
// 唯一搭台纪律（integration/README.md 舞台纪律段）落地点：旧 compose 缺省固定口
// 3199 已不供给，本族场景经本助手拿控制台地址：
//   1. env SUYOU_TEST_CONSOLE 显式指台（人工通路，兼容既有用法）；
//   2. 否则消费/自起共享常驻台 stage-console-shared（stage_docker ensure 幂等：
//      健康复用、并发经档位锁排队；全族场景复用一台，npm i/apt 只付一次）。
// 起台失败（docker 缺席/镜像缺席/起台不健康）=诚实环境红：打印 CLI 的 STAGE_ 行
// 后 process.exit(2)——三态语义不变，绝不假绿。
// 共享台生命周期=常驻基建（同 verify.yaml supply 的 sandbar-test-integ 例外口径）：
// 场景退出**不拆台**；拆台归供给面/人工（down --project stage-console-shared）。
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI = path.join(HERE, 'stage_docker.py');

export async function ensureStageConsole({ services = 'full', project = 'stage-console-shared' } = {}) {
  if (process.env.SUYOU_TEST_CONSOLE) {
    return { base: process.env.SUYOU_TEST_CONSOLE.replace(/\/$/, ''), project: '(external)', teardown: () => {} };
  }
  const env = {
    ...process.env,
    SANDBAR_STAGE_LOCK_DIR: process.env.SANDBAR_STAGE_LOCK_DIR || '/tmp/sandbar-test-stages',
  };
  const p = spawnSync('python3', [CLI, 'ensure', '--project', project, '--keep',
    '--services', services, '--timeout', '900'],
  { encoding: 'utf8', env, timeout: 960000 });
  if (p.status !== 0) {
    const named = String(p.stderr ?? '').split('\n').filter((l) => l.startsWith('STAGE_')).at(-1);
    console.error(`[ENV_FAIL] stage-console — ${named ?? `rc=${p.status} ${String(p.stderr ?? '').slice(0, 200)}`}`);
    process.exit(2);
  }
  const st = JSON.parse(String(p.stdout).trim().split('\n').at(-1));
  const SEED = { key: 'seedws', name: 'SeedWs' };
  // 容器侧夹具项目 seeding（gen6 拍板案 b）：共享台缺省注册表的 suyou 条目指向
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
    teardown: () => { /* 共享常驻台：场景退出不拆（供给面/人工 down） */ },
  };
}

/** 夹具项目锚（gen6）：行选择器后缀，场景用
 *  `[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])` 精确锚 seed 行
 *  （注册表缺省 suyou 行在前，first-row 会错锚到不可写工作区行）。 */
export const STAGE_SEED_ROW_SEL = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])';
export const STAGE_SEED = { key: 'seedws', name: 'SeedWs' };
