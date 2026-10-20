// Integration baseline for ticket t260901-03 — the capture chat "active" view
// can be produced (end-to-end regression baseline for the root-cause #2 fix).
//
// Intent (black-box, user perspective):
//   The t260901-02 acceptance walkthrough proved the gap: an isolated
//   workbench end-to-end run showed no data-phase=active within 25s, capture
//   exited 1, and only 6/7 views were produced. Root cause #2 = the session
//   seeded for evidence was blank (platform semantics "hero ⟺ the session is
//   blank"), so opening it always stayed on hero. The fix = upgrade the seed
//   to a "session with content" (a real composer round-trip sends the seed
//   message while the evidence is being faked up). This baseline locks that
//   fix:
//     U1-U3 pure-function guards (no browser/console; runnable anywhere):
//       U1 validateSeedText rejects malformed input (empty / too long /
//       control chars) with a precise reason;
//       U3 parseLedgerIds tolerates a corrupt ledger (bad JSON / not an array
//       / dirty entries) and drops the dirt.
//     C1 full chain: one command runs capture-lane on an isolated workbench →
//       assert exit code 0, 7/7 views, console-chat.png and
//       console-default.png with different sha256 (active view ≠ hero), and
//       capture output carrying the active anchor log plus 「健全性断言绿」.
//     C2 gate-flag red line: direct-connect semantics unchanged — capture.mjs
//       without --allow-seed against an un-ledgered environment must fail
//       loudly with zero writes (static assertion: the error text names
//       「--allow-seed」, and the direct path defaults to no flag).
//
// Environment: SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL=1 makes C1 record
//   ENV_FAIL exit 2 (no dsh/playwright environment);
//   SANDBAR_CAPTURE_MAIN_UI_CHECK points at the main tree's server/ui-check
//   (the lane has no node_modules; playwright-core loads from the main tree);
//   the captured output dir uses mkdtemp and is deleted afterwards.
// Hard guard: this baseline refuses in any way to target the production
//   console port 3099 (SANDBAR_TEST_CONSOLE containing 3099 exits directly);
//   C1's isolated workbench port is a free port picked by capture-lane itself.

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readdir, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { ensureLaneBuild } from "./capture-ensure-build.mjs";
// playwright-core 依赖解析唯一真源（t260912-01 缺陷③：位置无关四路口径）。
import { mainRoot } from "../lib_pw_deps.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");            // lane worktree root
// 主树解析位置无关化（t260912-01 缺陷③）：旧 `path.resolve(REPO_ROOT, "..", "..")`
// 位置算术在非 <主仓>/.lane/<票> 布局（如宿主 260912 副本开在 /private/tmp）指错
// 目录 → 依赖恒假缺。git-common-dir 口径=worktree 布局无关（lib_pw_deps 同款语义）。
// SANDBAR_MAIN_ROOT 可显式覆盖主树根（lib_pw_deps 取舍清单 #1）。
const MAIN_UI_CHECK = path.join(mainRoot(), "server", "ui-check");
const CAPTURE_LANE = path.join(REPO_ROOT, "server", "ui-check", "capture-lane.mjs");

// The 7 required views (same list as sc_capture_chat_e2e.mjs):
// a --boot-local self-hosted workbench produces extra best-effort views
// (appearance / docs / model routes, etc.) beyond what the docker workbench
// makes; the assertion only checks these 7 exist — extras never regress, a
// missing one is the red.
// t261012-05: same live-view realignment as sc_capture_chat_e2e (capture.mjs
// default VIEWS; epics/new-ticket/default retired with their icons;
// ticket-detail is data-optional and stays out of the required set).
const SEVEN_VIEWS = [
  "console-board.png", "console-board-dark.png", "console-board-light.png",
  "console-sessions.png", "console-settings-routes.png", "console-chat.png",
  "console-refresh.png",
];

const results = [];
function record(name, status, detail = "") {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ""}`);
}

// Hard 3099 guard (same policy as session-top-entry).
if ((process.env.SANDBAR_TEST_CONSOLE ?? "").includes(":3099")) {
  console.error("refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)");
  process.exit(1);
}

// ── U1-U3: pure-function guards (imports capture.mjs's exports; the module has a call guard, zero side effects) ──
async function unitGuards() {
  let m;
  try {
    m = await import(path.join(REPO_ROOT, "server", "ui-check", "capture.mjs"));
  } catch (e) {
    record("U0 capture.mjs 可导入", "fail", String(e).slice(0, 160));
    return 1;
  }
  record("U0 capture.mjs 可导入", "pass", "导出=" + Object.keys(m).sort().join(","));

  let fail = 0;
  const validateCases = [
    [null, "非字符串"],
    ["", "空串"],
    ["a".repeat(2001), "超长"],
    ["ok\x07bad", "控制字符"],
    ["ok\x1fbad", "控制字符"],
    ["（截图台造数）请只回复两个字：收到", "正常（main 版缺省词）"],
  ];
  for (const [v, label] of validateCases) {
    const r = m.validateSeedText(v);
    const ok = label.startsWith("正常") ? r === null : typeof r === "string" && r.length > 0;
    if (!ok) fail++;
    record(`U1 validateSeedText/${label}`, ok ? "pass" : "fail", String(r));
  }

  // U2 (the classifyHeroDegradation three-way discriminator) was dropped in
  // the gen3 alignment: the main-tree version (the t260901-02 real fix) goes
  // through the 「+ 新建会话」 path, so the lane version's criteria do not apply
  // and the discriminator never became deliverable (gen3 B②).

  const ledgerCases = [
    ["{bad json", [], "坏 JSON"],
    ['{"a":1}', [], "非数组"],
    ['[1,"x",null,{"id":"ok-1"},{"id":""}]', ["ok-1"], "脏条目剔脏"],
    ['[{"id":"a"},{"id":"b"}]', ["a", "b"], "正常"],
  ];
  for (const [raw, want, label] of ledgerCases) {
    const r = m.parseLedgerIds(raw);
    const ok = JSON.stringify(r) === JSON.stringify(want);
    if (!ok) fail++;
    record(`U3 parseLedgerIds/${label}`, ok ? "pass" : "fail", JSON.stringify(r));
  }
  return fail;
}

// ── C1: full chain capture-lane → 7/7 views + chat active evidence ──

async function fullChain() {
  // Lane worker mechanical-run guard (added by t260901-09 arbitrate, same as
  // ticket-lifecycle.mjs): C1 needs to boot an isolated workbench + drive the
  // real-model seed path + have capture-lane shoot only the bundle rebuilt on
  // this run (refusing a stale build is deliberate anti-fraud behavior; a
  // non-UI ticket's lane never rebuilds the bundle, so the precondition cannot
  // hold there). _run_manifest inherits the worker env
  // (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW) — a mechanical lane run
  // records ENV_FAIL exit 2 (the three-state contract has no pass-through
  // inside the gate); real coverage belongs to a top-level human/isolated
  // run; the U1-U3/C2 pure half is unaffected and still runs.
  if (process.env.SANDBAR_TASK_QUEUE || process.env.SANDBAR_WATCH_WORKFLOW) {
    return record("C1 capture-lane 全链", "env_fail",
      "nested inside a lane integration step (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present): recursive guard, top-level runs carry the coverage");
  }
  // Build-precondition self-heal (t260901-10 arbitrate gen2, absorbing this
  // ticket's gen6 mtime normalization — a byte-identical rebuild plus an
  // identity guardrail, stronger than touching timestamps and without
  // weakening the anti-fraud guard): an inverted-mtime fresh checkout makes
  // capture-lane's anti-fraud guard refuse to run; we perform the guard's own
  // documented remedy (rebuild the bundle, restricted to byte identity).
  //
  // t260913-01 仲裁修正（三态归属）：前提**无法满足**时（工具链不可得/重建失败/
  // 真实字节漂移）记 env_fail=not-checked 并点名缺什么——prepare 型原因记 FAIL
  // 是协议违约（README 已明文：本基线在泳道机械跑下「一律 ENV_FAIL」）。
  // 绝不改判 0；前提成立后真跑 capture-lane 的断言面照旧判 FAIL（下方链不动）。
  const buildErr = ensureLaneBuild(REPO_ROOT);
  if (buildErr) {
    return record("C1 capture-lane 全链", "env_fail", `build 前提未满足（not-checked）：${buildErr}`);
  }
  const out = await mkdtemp(path.join(tmpdir(), "suyou-capture-chat-active-"));
  let combined = "";
  try {
    const code = await new Promise((resolve) => {
      // --boot-local: chat seeding needs a real-credential, real-model round
      // trip — in docker workbench mode the container has no credentials, the
      // session stays inert and the composer stays readOnly, so the seed
      // cannot be written (the manual path capture-lane documents). The
      // self-hosted workbench uses a free port and never touches the user's
      // 3099 console.
      const p = spawn(process.execPath, [CAPTURE_LANE, "--lane", REPO_ROOT, "--out", out, "--boot-local"], {
        cwd: REPO_ROOT,
        env: {
          ...process.env,
          // Credential copy source: capture-lane copies .credentials.yaml from
          // $DSH_HOME — the runtime DSH_HOME may point at an empty dir inside
          // the worktree; only the user's real home has real credentials.
          DSH_HOME: process.env.HOME ? path.join(process.env.HOME, ".dsh") : process.env.DSH_HOME,
          SANDBAR_CAPTURE_MAIN_UI_CHECK: process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK || MAIN_UI_CHECK,
          // Widen the window for waiting on active after the seed message
          // (real-model latency; more stable on CI).
          SANDBAR_UI_CAPTURE_SEED_ACTIVE_MS: process.env.SANDBAR_UI_CAPTURE_SEED_ACTIVE_MS || "90000",
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
      p.stdout.on("data", (d) => { combined += d; process.stdout.write(d); });
      p.stderr.on("data", (d) => { combined += d; process.stderr.write(d); });
      p.on("close", resolve);
    });
    if (code !== 0) return record("C1 capture-lane 全链", "fail", `退出码 ${code}`);
    const files = (await readdir(out)).filter((f) => f.endsWith(".png"));
    // The view-list assertion is relaxed from "exactly 7" to "the 7 required
    // views are present": a --boot-local self-hosted workbench produces extra
    // best-effort views (appearance / docs / model routes) beyond the docker
    // workbench (extras never regress, only a missing one is red)
    const missing = SEVEN_VIEWS.filter((v) => !files.includes(v));
    if (missing.length) return record("C1 capture-lane 全链", "fail", `必备视图缺失 ${missing.length} 张: ${missing.join(",")}（实得 ${files.length}）`);
    const sha = async (f) => createHash("sha256").update(await readFile(path.join(out, f))).digest("hex");
    const chatSha = await sha("console-chat.png");
    // t261012-05: chat-vs-board (console-default.png retired; board is the
    // live non-chat landing face).
    const defaultSha = await sha("console-board.png");
    if (chatSha === defaultSha) return record("C1 capture-lane 全链", "fail", "console-chat ≡ console-board（字节相同=chat 视图未切换，同帧假验收）");
    // chat view success anchor: the log line unique to navigateToChat's
    // success path (the only way the 25s active assertion passes; when the
    // assertion fails the view is recorded failed and this line is absent —
    // more reliable than grepping the data-phase literal).
    // Post-gen3-alignment isolated-workbench path anchor: clicking 「+ 新建会话」
    // plus the seed message drives active (main-tree semantics).
    if (!/锚=隔离台(?:项目行)?「\+ (?:新建会话|钮)」\+ 种子消息/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无 chat 成功锚日志（+ 新建会话+种子消息）——active 断言未过");
    if (/准入模态遮挡/.test(combined)) return record("C1 capture-lane 全链", "fail", "chat 证据被准入模态遮挡（截后断言触发）");
    if (!/健全性断言绿/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无「健全性断言绿」");
    // Message-on-screen anchor (the fix for the t260901-03 acceptance
    // walkthrough rework): the seed message's words must land in the session
    // transcript, so the mechanical green = criterion 2 "the chat view
    // contains the user message bubble" being truly green, not inferred from
    // a model placeholder line.
    if (!/种子消息已上屏/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无「种子消息已上屏」锚——chat 证据缺用户消息气泡");
    const chatSize = (await stat(path.join(out, "console-chat.png"))).size;
    record("C1 capture-lane 全链", "pass", `7/7 视图，chat ${chatSize}B，chat≠default，active 锚+消息上屏+健全性断言俱在`);
  } catch (e) {
    record("C1 capture-lane 全链", "fail", String(e).slice(0, 160));
  } finally {
    await rm(out, { recursive: true, force: true }).catch(() => {});
  }
}

// ── C2: gate-flag red line, static assertions (the direct path passes no flag; the missing-flag error text names --allow-seed) ──
async function gateRedLine() {
  let fail = 0;
  const capSrc = await readFile(path.join(REPO_ROOT, "server", "ui-check", "capture.mjs"), "utf8");
  // The direct path passes no flag: capture-lane's spawn call must pass
  // --allow-seed explicitly (isolated workbench), while capture.mjs's default
  // url pointing at 3099 must fail safely even with no flag.
  if (!/--allow-seed/.test(capSrc)) { fail++; record("C2 门旗存在性", "fail", "capture.mjs 无 --allow-seed 门旗"); }
  else record("C2 门旗存在性", "pass", "--allow-seed 文案在案");
  if (!/SANDBAR_UI_CAPTURE_ALLOW_SEED/.test(capSrc)) { fail++; record("C2 env 门旗", "fail", "无 SANDBAR_UI_CAPTURE_ALLOW_SEED"); }
  else record("C2 env 门旗", "pass", "env 门旗在案");
  // A missing flag hands the error to a human: navigateToChat's throw text
  // must name the gate flag.
  if (!/未带 --allow-seed/.test(capSrc)) { fail++; record("C2 缺旗报错文案", "fail", "navigateToChat 缺旗报错文案缺失"); }
  else record("C2 缺旗报错文案", "pass", "无 MRU 行且缺旗=明确报错交人");
  return fail;
}

let fail = await unitGuards();
fail += await gateRedLine();
// 260904 migration-back guard (KI-036; t260912-01 位置无关化): the two candidates
// (this tree's and the main tree's ui-check, the latter resolved via
// lib_pw_deps.mainRoot() = git-common-dir) both lack playwright-core → the C1
// full chain records ENV_FAIL exit 2 instead of a fake red. Copy states facts
// only (candidate paths) — no "dependency missing / sandbox" attribution that
// would point at the environment while the real defect is layout arithmetic.
// It re-arms by itself once the dependency is back, assertions unchanged.
import { existsSync as _existsSync } from "node:fs";
const _pwMissing = !_existsSync(path.join(REPO_ROOT, "server", "ui-check",
                                         "node_modules", "playwright-core"))
  && !_existsSync(path.join(MAIN_UI_CHECK, "node_modules", "playwright-core"));
if (process.env.SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL === "1") {
  record("C1 capture-lane 全链", "env_fail", "SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL=1");
} else if (_pwMissing) {
  record("C1 capture-lane 全链", "env_fail",
    `KI-036：两侧候选均未探得 playwright-core（本树 ${path.join(REPO_ROOT, "server", "ui-check")}`
    + `；主树 ${MAIN_UI_CHECK}）——依赖就位后本链自动恢复，断言面不变`);
} else {
  await fullChain();
  fail += results.filter((r) => r.name.startsWith("C1") && r.status === "fail").length;
}

const pass = results.filter((r) => r.status === "pass").length;
const envFail = results.filter((r) => r.status === "env_fail").length;
const na = results.filter((r) => r.status === "na").length;
console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`);
const allNa = na > 0 && pass + fail + envFail === 0;
process.exit(fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0);
