// stage_docker.mjs — thin mjs wrapper around the docker test stage CLI (ticket t260904-19).
//
// The real logic lives in integration/stage_docker.py (the CLI). This file only
// does subprocess calls + JSON parsing + in-container profile materialization.
// Nothing is duplicated — two copies of allocation/health/teardown logic would
// drift, and drift has happened here before. Scenario fixtures must go through
// this wrapper; never hand-write docker compose commands.
import { spawnSync } from 'node:child_process';
import { mkdirSync, cpSync, existsSync, symlinkSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const INTEG_DIR = path.dirname(fileURLToPath(import.meta.url));
export const STAGE_CLI = path.join(INTEG_DIR, 'stage_docker.py');

/** Start a stage: returns the JSON from `stage_docker up` (project/ports/namespace/...).
 *  Throws Error on failure (message = the STAGE_* line from CLI stderr; the
 *  three-state wording is named in the CLI already).
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

/** Tear down a stage (idempotent). Returns the down-result JSON (the residue
 * field lets scenarios assert zero leftovers). */
export function stageDown(project) {
  const p = spawnSync('python3', [STAGE_CLI, 'down', '--project', project],
    { encoding: 'utf8', timeout: 180000 });
  if (p.error) throw new Error(`stage_docker down 无法执行：${p.error.message}`);
  if (p.status !== 0) throw new Error((p.stderr ?? '').trim() || `down rc=${p.status}`);
  return JSON.parse(p.stdout.trim().split('\n').at(-1));
}

/** Materialize the in-container profile (docker stage flavor; the lane under
 * test always runs its own tree's code):
 *  - cordis config / sandbar-tools.ts come from repoProfileDir (committed);
 *  - node_modules holds exactly one entry: a symlink to the workbench under
 *    test (→ /repo/server/plugins/workbench, where /repo is the tree under
 *    test). The compose command merges every other plugin from the dependency
 *    tree /repo-nm (defaults to the main tree, stage_docker falls back
 *    automatically) — in-repo plugins are not on global npm, so a
 *    "everything else → global node_modules" model would leave dangling links.
 *  The host cannot verify how in-container symlinks resolve — the stage's
 *  console health probe is the backstop (a stage that cannot boot = ENV_FAIL).
 *  Returns profileDir (mounted as /profile in the container, with
 *  SANDBAR_TEST_PROFILE_SRC=/profile). */
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
