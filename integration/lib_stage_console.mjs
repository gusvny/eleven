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
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
  // Fixture host directory: one per stage (= per tree), lives and dies with
  // the stage; mounted into the container as /fixtures (rw).
  const FIXTURES_HOST = path.join('/tmp', `sandbar-fixtures-${TREE_PROJECT.slice(-8)}`);
  mkdirSync(FIXTURES_HOST, { recursive: true });
  const env = {
    ...process.env,
    SANDBAR_STAGE_LOCK_DIR: process.env.SANDBAR_STAGE_LOCK_DIR || '/tmp/sandbar-test-stages',
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
    // Precision: after the STAGE_ line, append the tail of the CLI stderr
    // (compose diagnostics) — never keep just a conclusion and drop evidence.
    console.error(`[ENV_FAIL] stage-console — ${named ?? why}\n${String(p.stderr ?? '').slice(-600)}`);
    process.exit(2);
  }
  const st = JSON.parse(String(p.stdout).trim().split('\n').at(-1));
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
  seedFixtures(st, FIXTURES_HOST).catch((e) =>
    console.warn(`[stage-console] fixture seeding failed (scenario fixture legs will name env_fail): ${e}`));
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
  // naming-compat: suyou-test is the existing test-stage namespace name
  // (same as the compose default); this repo does not change it.
  const toolEnv = {
    ...process.env,
    SANDBAR_PROJECTS_YAML: legacyYaml,
    SANDBAR_TARGET_HOST: `127.0.0.1:${st.ports.temporal}`,
    SANDBAR_NAMESPACE: st.namespace || 'suyou-test',  // naming-compat: namespace name stays with the stage
  };
  const runTool = (argsJson) => spawnSync(py, ['-c',
    'import sys, json; sys.path.insert(0, "server/tools"); import ticket;'
    + ' print(json.dumps(ticket.run(json.loads(sys.argv[1])), ensure_ascii=False))',
    argsJson],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 180_000 });
  // Ticket ids use the t<yymmdd>-<NN> shape: the chat project tag's ticket
  // reference whitelist only accepts /t\d{6}-\d{2}/ — the old short ids
  // (integfix1/2) are never indexed, so the t02 chip leg was red permanently
  // (proven 260908). Idempotence anchor = the list's id (no worker query
  // needed; the title degrades when there is no worker).
  const listIds = (project) => {
    const out = runTool(JSON.stringify({ op: 'list', project }));
    if (out.status !== 0) throw new Error(`fixture ticket count failed: ${out.stderr?.slice(-200)}`);
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
      if (createOut.status !== 0) throw new Error(`fixture ticket ${fid} create failed: ${createOut.stderr?.slice(-200)}`);
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
  ].join('\n'), `127.0.0.1:${st.ports.temporal}`, st.namespace || 'suyou-test', LEGACY_FIXTURE_IDS.join(',')],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 60_000 });
  // 2b. Closing drain: fixture tickets are driven to COMPLETED by a fake
  // DevLaneWorkflow (the no-worker direct-read precondition of
  // fixture_ticket_fake.py's header). When tickets are already closed, the
  // drain worker's first poll round exits — seconds.
  const allIds = seedProjects.flatMap((sp) => sp.ids);
  const drainOut = spawnSync(py, [path.join(HERE, 'fixture_ticket_worker.py'),
    `127.0.0.1:${st.ports.temporal}`, st.namespace || 'suyou-test',  // naming-compat: namespace name stays with the stage
    allIds.join(','), '120'],
    { encoding: 'utf8', env: toolEnv, cwd: WANT_REPO, timeout: 150_000 });
  if (drainOut.status !== 0) {
    throw new Error(`fixture ticket drain failed: ${(drainOut.stderr || '').slice(-200)}`);
  }
  // 3. Evidence images (the drawer evidence leg's data source; idempotent =
  // skip files that already exist). The evidence route reads per ticket id
  // (<ticket-id>/.suyou/evidence/<file>), independent of whether a workflow
  // has a worker. Give every fixture ticket an image: row order is not
  // guaranteed, and clicking the wrong row means that ticket has no evidence
  // → the drawer image leg times out.
  // Land in two places: the repo root (the default anchor / no-project API
  // surface) + each fixture project root (after KI-057 the drawer's apiGet
  // always carries ?project=, and evidence enumeration anchors at
  // <project-root>/.suyou/evidence — with only the repo root, the project
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
export const STAGE_SEED_ROW_SEL = '[data-wb-psess-row]:has([aria-label="新建 SeedWs 会话"])';
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
