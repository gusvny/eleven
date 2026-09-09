// stage_docker.mjs —— docker 测试舞台 mjs 薄壳（票 t260904-19）。
//
// 实现单点在 integration/stage_docker.py（CLI）；本文件只做 subprocess 调用 +
// JSON 解析 + 容器内路径的 profile 物化。分配/健康/回收逻辑零复制——双份必漂移
// 是本仓前科。场景夹具一律经本壳调用，勿手写 docker compose。
import { spawnSync } from 'node:child_process';
import { mkdirSync, cpSync, existsSync, symlinkSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const INTEG_DIR = path.dirname(fileURLToPath(import.meta.url));
export const STAGE_CLI = path.join(INTEG_DIR, 'stage_docker.py');

/** 起台：返回 stage_docker up 的 JSON（project/ports/namespace/...）。
 *  失败抛 Error（message=CLI stderr 的 STAGE_* 行，三态文案已在 CLI 侧点名）。
 *  opts: { project, services='dsh', namespace, fixturesDir, profileDir, profileName,
 *          repoDir, projectsDir, timeoutSec } */
export function stageUp(opts) {
  const args = [STAGE_CLI, 'up', '--project', opts.project,
    '--services', opts.services ?? 'dsh', '--timeout', String(opts.timeoutSec ?? 600)];
  if (opts.namespace) args.push('--namespace', opts.namespace);
  if (opts.fixturesDir) args.push('--fixtures-dir', opts.fixturesDir);
  if (opts.profileDir) args.push('--profile-dir', opts.profileDir);
  if (opts.profileName) args.push('--profile-name', opts.profileName);
  if (opts.repoDir) args.push('--repo-dir', opts.repoDir);
  const env = { ...process.env };
  if (opts.projectsDir) env.SANDBAR_TEST_PROJECTS_DIR = opts.projectsDir;
  const p = spawnSync('python3', args, { encoding: 'utf8', env, timeout: (opts.timeoutSec ?? 600) * 1000 + 15000 });
  if (p.error) throw new Error(`stage_docker up 无法执行：${p.error.message}`);
  if (p.status !== 0) {
    const named = String(p.stderr ?? '').split('\n').filter((l) => l.startsWith('STAGE_'));
    throw new Error(named.at(-1) ?? `stage_docker up rc=${p.status} ${String(p.stderr ?? '').slice(0, 300)}`);
  }
  return JSON.parse(p.stdout.trim().split('\n').at(-1));
}

/** 拆台（幂等）。返回 down 结果 JSON（residue 面供场景断言零残留）。 */
export function stageDown(project) {
  const p = spawnSync('python3', [STAGE_CLI, 'down', '--project', project],
    { encoding: 'utf8', timeout: 180000 });
  if (p.error) throw new Error(`stage_docker down 无法执行：${p.error.message}`);
  if (p.status !== 0) throw new Error((p.stderr ?? '').trim() || `down rc=${p.status}`);
  return JSON.parse(p.stdout.trim().split('\n').at(-1));
}

/** 容器内 profile 物化（docker 台版，克缝始终=测泳道/指定树代码）：
 *  - cordis 配置/sandbar-tools.ts 取 repoProfileDir（committed）；
 *  - node_modules 只放一个目录+被测 workbench 软链（→ /repo/server/plugins/workbench，
 *    /repo=被测树）；其余插件由 compose command 从依赖树 /repo-nm（缺省主树，
 *    stage_docker 自动回落）逐项并入——仓内插件不在全局 npm，「其余→全局
 *    node_modules」模型对它们是悬空链。
 *  宿主侧不可验证容器内软链解析——由 stage_docker 的 console 健康探针兜底
 *  （起不来=ENV_FAIL）。
 *  返回 profileDir（挂载为容器 /profile，SANDBAR_TEST_PROFILE_SRC=/profile）。 */
export function buildStageProfile({ repoProfileDir, laneWorkbenchDir, tmpHome }) {
  const profDir = path.join(tmpHome, 'profiles', 'suyou');
  mkdirSync(profDir, { recursive: true });
  for (const f of ['cordis.yml', 'cordis.patch.yml', 'package.json']) {
    const src = path.join(repoProfileDir, f);
    if (existsSync(src)) cpSync(src, path.join(profDir, f));
  }
  const tsTools = path.join(repoProfileDir, 'sandbar-tools.ts');
  if (existsSync(tsTools)) symlinkSync(tsTools, path.join(profDir, 'sandbar-tools.ts'));
  const nm = path.join(profDir, 'node_modules');
  mkdirSync(nm, { recursive: true });
  symlinkSync(laneWorkbenchDir ?? '/repo/server/plugins/workbench', path.join(nm, 'sandbar-workbench'), 'dir');
  return profDir;
}
