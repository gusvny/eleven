#!/usr/bin/env node
// t261005-16 场景②：新家采集全旅程——注册表与机器现实脱钩（灰盒 L3；
// 缺省走生产 docker 舞台通路——merge_check 的 ui_evidence 正是这条路，
// t261005-16 验收走查打回：只测 --boot-local 降级通路=回归盲区）。
//
// intent（登记于 run_scenarios.py）——KI-204 的用户可感知旅程钉子：采集台在
// 新家起台后，「新建会话」绝不能落在注册表里某个目录已不存在的项目上
// （实证形态：新建会话失败：工作区创建失败 <已删除的历史仓绝对路径> …
// ENOENT，capture exit 1，UI 证据永落不进泳道；字面路径不在测试内硬编码——
// 敌意探针目录由本场景自造）。断言只落公开可感知行为：
//
// - J1（主修，决定性红前面）：宿主侧注入一个「敌意注册表」（SANDBAR_PROJECTS_DIR
//   指向只含 suyou/死目录 条目的目录）跑真采集——台**不得**消费宿主注册表：
//   exit 0、console.log 无「工作区创建失败」、敌意探针路径零出现、PNG 落 --out
//   顶层（平铺契约顺带守卫，字面见 t261005-13-evidence-layout-named，不重复展开）。
//   修前此面必红（台继承 env → 控制台装载敌意条目 → 会话创建 ENOENT）；
//   修后台自建注册表覆盖 env，宿主现实无关（同时覆盖工单 OUTCOME 3：
//   「宿主目录存在」的机器=本面无害通过的特例）。
// - J2（全旅程面）：env 干净跑真采集，exit 0 且证据平铺（工单 OUTCOME 2 的
//   原始复现命令口径）。重负载；SANDBAR_T26100516_FULL=1 时才跑（闸内缺省
//   只跑 J1，把条目墙钟控制在引擎 900s 预算内；巡检/人工开满两面）。
// - J3（资源终态面）：两次跑结束后 tmpdir 无 suyou-capture-lane-* 残留
//   （台的五路终态回收矩阵的旁观断言，既有 capture 家族先例同款）。
//
// intent 分工：capture-chat-e2e/-active 守视图内容与 chat 态链路（7/9 视图、
// data-phase）；本条只守「新家注册表独立于宿主/机器现实」这一面，不重复视图断言。
// ENV_FAIL（exit 2）：node/playwright/凭据/preset 源缺席、采集台自身环境拒跑
// （rc=2）——环境红不假红不假绿。实现落地前 J1/J2 红属预期（TDD 信号）；
// arbitrate/merge 期必须绿。不碰 3099（台自选空闲端口）。
import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { mkdtemp, rm, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { emitCase } from "../lib_result.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const CAPTURE_LANE = path.join(REPO, "server", "ui-check", "capture-lane.mjs");
const SUITE = "t261005-16-capture-fresh-home-journey";
const PROBE = "/nonexistent/t26100516-hostile-probe/dead";
const FAIL_TEXT = "工作区创建失败";
const results = [];

function check(name, ok, reason = "", evidence = "") {
  emitCase({ name, suite: SUITE, status: ok ? "pass" : "fail", cause: "self",
             reason, evidence: String(evidence).slice(0, 400) });
  results.push({ name, ok });
}

function preflight() {
  const missing = [];
  if (!existsSync(CAPTURE_LANE)) missing.push(CAPTURE_LANE);
  const laneClient = path.join(REPO, "server", "plugins", "workbench", "lib", "client.js");
  if (!existsSync(laneClient)) missing.push(`lane build missing: ${laneClient} (run the build first)`);
  const pw = path.join(REPO, "server", "ui-check", "node_modules", "playwright-core");
  if (!existsSync(pw)) missing.push(`playwright-core unresolvable: ${pw}`);
  if (missing.length) {
    emitCase({ name: "t261005-16-journey-preflight", suite: SUITE, status: "not-checked",
               cause: "external", reason: "environment pieces missing",
               evidence: missing.join(" | ").slice(0, 400) });
    process.exit(2);
  }
}

function judge(run, opts) {
  const { tag, code, stdout, out } = run;
  if (code === 2) {
    emitCase({ name: `J-${tag}`, suite: SUITE, status: "not-checked", cause: "external",
               reason: "capture-lane refused to run (env face, rc=2)",
               evidence: stdout.slice(-300) });
    return false;
  }
  const haystack = stdout;
  check(`J1-${tag}-exit0-no-workspace-failure`, code === 0 && !haystack.includes(FAIL_TEXT),
        "a fresh-home capture must not fail at session creation over a retired/dead "
        + "registry project — the exit-0 journey is the user-visible contract",
        `rc=${code} tail=${stdout.slice(-160)}`);
  const pngs = existsSync(out) ? readdirSync(out).filter((f) => f.endsWith(".png")) : [];
  check(`J1-${tag}-pngs-flat-in-out`, pngs.length >= 1,
        "evidence must land in --out read TOP-LEVEL non-recursively (the gate reads only the "
        + "top level — t261005-13 contract); HOW MANY views succeed is the capture family's "
        + "face (capture-chat-e2e/-active), not this entry's",
        `count=${pngs.length} sample=${pngs.slice(0, 3).join(",")}`);
  // 尾部镜像用例：闸的 FAIL 窗口只露出最后几条规范行，首用例（exit0）的证据会被
  // 挤出窗口——补一条尾部发射的同信息用例（纯观测面，不改判定）。
  emitCase({ name: `Z-${tag}-bench-rc-mirror`, suite: SUITE,
             status: code === 0 ? "pass" : "fail", cause: "self",
             reason: "bench exit code mirror (observability; mirrors J1 exit0 face)",
             evidence: `rc=${code} tail=${stdout.slice(-1500)}` });
  results.push({ name: `Z-${tag}-bench-rc-mirror`, ok: code === 0 });
  check(`J1-${tag}-hostile-registry-not-consumed`,
        !(opts && opts.probe) || !haystack.includes(PROBE),
        "the bench must not consume the host registry (probe path must never appear)",
        `probe seen=${haystack.includes(PROBE)}`);
  return code === 0;
}

let preResidue = new Set();

async function main() {
  preflight();
  preResidue = new Set(readdirSync(tmpdir()).filter((f) => f.startsWith("suyou-capture-lane-")));
  const full = process.env.SANDBAR_T26100516_FULL === "1";

  // ---- J1: hostile host registry must not leak into the bench ----
  const hostileHome = await mkdtemp(path.join(tmpdir(), "t26100516-hostile-"));
  const hostileRoot = path.join(hostileHome, "projects");
  await mkdir(path.join(hostileRoot, "suyou"), { recursive: true });
  await writeFile(path.join(hostileRoot, "suyou", "project.yaml"),
                  `schema: v1\nkey: suyou\nname: hostile probe\ndirs:\n  - ${PROBE}\n`,
                  "utf8");
  const env1 = { ...process.env, SANDBAR_PROJECTS_DIR: hostileRoot };
  const r1 = await runCaptureWithEnv(env1, "hostile-registry");
  judge(r1, { probe: true });

  // ---- J2: clean fresh home (opt-in full) ----
  if (full) {
    const env2 = { ...process.env };
    delete env2.SANDBAR_PROJECTS_DIR;
    const r2 = await runCaptureWithEnv(env2, "fresh-home");
    judge(r2, {});
  } else {
    emitCase({ name: "J2-fresh-home-default", suite: SUITE, status: "not-checked",
               cause: "self",
               reason: "opt-in face: set SANDBAR_T26100516_FULL=1 to run the clean "
                     + "fresh-home journey (wall-clock budget; J1 already carries the "
                     + "deterministic red-before face)",
               evidence: "SANDBAR_T26100516_FULL unset" });
  }

  // ---- J3: teardown residue bystander, bounded to THIS run ----
  //（共享 tmpdir 里有历史残骸（早前被杀的台），全局清零断言会把别人的欠账记到本次头上；
  //  只断「本次跑新增为零」——回收矩阵自身的契约面。）
  const before = new Set(readdirSync(tmpdir()).filter((f) => f.startsWith("suyou-capture-lane-")));
  // snapshot was taken before the runs above via preResidue (see main flow)
  const residue = readdirSync(tmpdir())
    .filter((f) => f.startsWith("suyou-capture-lane-") && !preResidue.has(f));
  check("J3-no-new-bench-tmp-residue", residue.length === 0,
        "the bench teardown matrix must leave no NEW temp home behind (bounded bystander)",
        ("foreign pre-existing=" + before.size + " new=") + residue.slice(0, 5).join(","));

  await rm(r1.home, { recursive: true, force: true });
  await rm(hostileHome, { recursive: true, force: true });
  process.exit(results.some((r) => !r.ok) ? 1 : 0);
}

async function runCaptureWithEnv(env, tag) {
  const home = await mkdtemp(path.join(tmpdir(), "t26100516-journey-"));
  const out = path.join(home, "shots");
  await mkdir(out, { recursive: true });
  // 通路口径（t261005-16 验收走查打回面）：**缺省跑生产 docker 舞台通路**——
  // merge_check 的 ui_evidence 走的正是缺省模式，回归必须守生产通路本身；
  // --boot-local（docker 缺席宿主的人工降级通路）仅在
  // SANDBAR_T26100516_BOOT_LOCAL=1 显式选择时使用（docker 缺席=台 rc=2 →
  // judge 记 not-checked 环境红，不假绿）。
  const bootLocal = process.env.SANDBAR_T26100516_BOOT_LOCAL === "1";
  const laneArgs = [CAPTURE_LANE, "--lane", REPO, "--out", out];
  if (bootLocal) laneArgs.push("--boot-local");
  const p = await new Promise((resolve) => {
    const child = spawn("node", laneArgs,
                        { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stdout += d; });
    const t = setTimeout(() => child.kill("SIGTERM"), 780000);
    child.on("exit", (code) => { clearTimeout(t); resolve({ code, stdout }); });
  });
  return { ...p, out, home, tag };
}

main().catch((e) => {
  emitCase({ name: "t261005-16-journey-crash", suite: SUITE, status: "not-checked",
             cause: "unknown", reason: "scenario crashed",
             evidence: String(e && e.stack || e).slice(0, 400) });
  process.exit(2);
});
