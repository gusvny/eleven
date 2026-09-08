// Integration baseline for ticket t260901-03 —— capture chat 态视图造得出
// （根因#2 修复的端到端回归基线）。
//
// Intent（黑盒，用户视角）：
//   t260901-02 验收走查实证：隔离台端到端实跑 chat 视图 25s 内未出现
//   data-phase=active，capture 退出码 1，6/7 视图产出。根因#2 = 造数的种子会话
//   是 blank（平台语义「hero ⟺ 会话 blank」），点开恒停 hero。修复 = 种子升级
//   为「有内容会话」（造数期经真实 composer 发种子消息）。本基线锁这个修复：
//     U1-U3 纯函数防呆（不起浏览器/控制台，任何环境可跑）：
//       U1 validateSeedText 畸形输入（空/超长/控制字符）拒因精确；
//       U3 parseLedgerIds 坏账册（坏 JSON/非数组/脏条目）容错剔脏。
//     C1 全链：capture-lane 隔离台一条命令 → 断言退出码 0、7/7 视图、
//       console-chat.png 与 console-default.png sha256 不同（active 视图≠hero）、
//       capture 输出含 active 锚日志与「健全性断言绿」。
//     C2 门旗红线：直连语义不变——不带 --allow-seed 的 capture.mjs 对无账册
//       环境必须明确报错且零写操作（静态断言：报错文案含「--allow-seed」，
//       直连路径默认不带旗）。
//
// 环境：SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL=1 使 C1 记 ENV_FAIL 退 2（无 dsh/playwright 环境）；
//   SANDBAR_CAPTURE_MAIN_UI_CHECK 指主树 server/ui-check（泳道无 node_modules，
//   playwright-core 从主树加载）；captured 输出目录用 mkdtemp，跑完即删。
// 硬守卫：本基线拒绝以任何方式指向生产控制台端口 3099（SANDBAR_TEST_CONSOLE 若
//   含 3099 直接退出）；C1 的隔离台端口由 capture-lane 自己挑空闲端口。

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readdir, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { ensureLaneBuild } from "./capture-ensure-build.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");            // 泳道 worktree 根
const MAIN_TREE = path.resolve(REPO_ROOT, "..", "..");       // 主树（playwright/dsh 供给）
const MAIN_UI_CHECK = path.join(MAIN_TREE, "server", "ui-check");
const CAPTURE_LANE = path.join(REPO_ROOT, "server", "ui-check", "capture-lane.mjs");

// 7 张必备视图清单（与 sc_capture_chat_e2e.mjs 同口径）：
// --boot-local 自搭台会比 docker 台多产外观/文档/模型路由等尽力视图，
// 断言只看这 7 张在不在，多产不退化、缺张才算红。
const SEVEN_VIEWS = [
  "console-default.png", "console-board.png", "console-epics.png",
  "console-new-ticket.png", "console-sessions.png", "console-chat.png",
  "console-refresh.png",
];

const results = [];
function record(name, status, detail = "") {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ""}`);
}

// 3099 硬守卫（照抄 session-top-entry 口径）。
if ((process.env.SANDBAR_TEST_CONSOLE ?? "").includes(":3099")) {
  console.error("refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)");
  process.exit(1);
}

// ── U1-U3：纯函数防呆（import capture.mjs 的导出；模块有调用守卫，零副作用）──
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

  // U2（classifyHeroDegradation 三态判别）随 gen3 对齐移除：main 版（t260901-02
  // 根治版）走「+ 新建会话」路径，泳道版判据不适用，判别器不进交付面（gen3 B②）。

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

// ── C1：全链 capture-lane → 7/7 视图 + chat active 证据 ──

async function fullChain() {
  // 泳道 worker 机械跑护栏（t260901-09 arbitrate 补，与 ticket-lifecycle.mjs 同款）：
  // C1 要 boot 隔离台 + 走真模型种子链路 + capture-lane 只拍本次重建的 bundle（陈旧
  // build 拒跑是防证据造假的设计行为；非 UI 票的泳道不重建 bundle，此前提天然不满足）。
  // _run_manifest 继承 worker 环境（SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW）——泳道
  // 机械跑记 ENV_FAIL 退 2（三态契约闸内无放行），真实覆盖属顶层人工/隔离台跑；U1-U3/C2 纯函数半不受影响，照跑。
  if (process.env.SANDBAR_TASK_QUEUE || process.env.SANDBAR_WATCH_WORKFLOW) {
    return record("C1 capture-lane 全链", "env_fail",
      "nested inside a lane integration step (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present): recursive guard, top-level runs carry the coverage");
  }
  // build 前提自愈（t260901-10 arbitrate gen2，收编本票 gen6 的 mtime 归一化——
  // 字节幂等重建 + 同一性护栏，比刷时间戳更强且不弱化防造假守卫语义）：
  // fresh checkout 的 mtime 倒挂会让 capture-lane 的防造假守卫拒跑；自动执行守卫
  // 文档化的补救（重建 bundle，限字节幂等），不满足则按 C1 失败上报。
  const buildErr = ensureLaneBuild(REPO_ROOT);
  if (buildErr) return record("C1 capture-lane 全链", "fail", `build 前提：${buildErr}`);
  const out = await mkdtemp(path.join(tmpdir(), "suyou-capture-chat-active-"));
  let combined = "";
  try {
    const code = await new Promise((resolve) => {
      // --boot-local：chat 种子要真凭据真模型往返——docker 台模式容器内无凭据，
      // 会话恒 inert、composer 恒 readOnly，种子写不进去（capture-lane 明示的人工通路）。
      // 自搭台用空闲端口，不碰用户的 3099 控制台。
      const p = spawn(process.execPath, [CAPTURE_LANE, "--lane", REPO_ROOT, "--out", out, "--boot-local"], {
        cwd: REPO_ROOT,
        env: {
          ...process.env,
          // 凭据拷贝源：capture-lane 从 $DSH_HOME 拷 .credentials.yaml——运行环境
          // 的 DSH_HOME 可能指 worktree 内空目录，指向用户真 home 才有真凭据。
          DSH_HOME: process.env.HOME ? path.join(process.env.HOME, ".dsh") : process.env.DSH_HOME,
          SANDBAR_CAPTURE_MAIN_UI_CHECK: process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK || MAIN_UI_CHECK,
          // 种子消息等 active 的窗口放宽（真模型链路延迟，CI 上更稳）。
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
    // 视图清单断言从「恰 7 张」放宽为「7 张必备视图在场」：--boot-local 的自搭台
    // 比 docker 台多产外观/文档/模型路由等尽力视图（多不退化，缺才算红）
    const missing = SEVEN_VIEWS.filter((v) => !files.includes(v));
    if (missing.length) return record("C1 capture-lane 全链", "fail", `必备视图缺失 ${missing.length} 张: ${missing.join(",")}（实得 ${files.length}）`);
    const sha = async (f) => createHash("sha256").update(await readFile(path.join(out, f))).digest("hex");
    const chatSha = await sha("console-chat.png");
    const defaultSha = await sha("console-default.png");
    if (chatSha === defaultSha) return record("C1 capture-lane 全链", "fail", "console-chat ≡ console-default（字节相同=chat 视图未切换，同帧假验收）");
    // chat 视图成功锚：navigateToChat 成功路径的专属日志行（25s active 断言通过的
    // 唯一出口；断言失败时该视图记失败、无此行——比 grep data-phase 字面量可靠）。
    // gen3 对齐后隔离台路径锚：点「+ 新建会话」+ 种子消息驱动 active（main 版语义）。
    if (!/锚=隔离台(?:项目行)?「\+ (?:新建会话|钮)」\+ 种子消息/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无 chat 成功锚日志（+ 新建会话+种子消息）——active 断言未过");
    if (/准入模态遮挡/.test(combined)) return record("C1 capture-lane 全链", "fail", "chat 证据被准入模态遮挡（截后断言触发）");
    if (!/健全性断言绿/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无「健全性断言绿」");
    // 消息上屏锚（t260901-03 验收走查打回修复）：种子消息词必须进会话转录，
    // 机械绿 = 口径 2「chat 视图含用户消息气泡」真绿，不是靠模型占位行反推。
    if (!/种子消息已上屏/.test(combined)) return record("C1 capture-lane 全链", "fail", "capture 输出无「种子消息已上屏」锚——chat 证据缺用户消息气泡");
    const chatSize = (await stat(path.join(out, "console-chat.png"))).size;
    record("C1 capture-lane 全链", "pass", `7/7 视图，chat ${chatSize}B，chat≠default，active 锚+消息上屏+健全性断言俱在`);
  } catch (e) {
    record("C1 capture-lane 全链", "fail", String(e).slice(0, 160));
  } finally {
    await rm(out, { recursive: true, force: true }).catch(() => {});
  }
}

// ── C2：门旗红线静态断言（直连路径不带旗；缺旗报错文案含 --allow-seed）──
async function gateRedLine() {
  let fail = 0;
  const capSrc = await readFile(path.join(REPO_ROOT, "server", "ui-check", "capture.mjs"), "utf8");
  // 直连路径不带旗：capture-lane 的 spawn 调用里必须显式传 --allow-seed（隔离台），
  // 而 capture.mjs 的 url 缺省指向 3099 时要求不带旗也能安全报错。
  if (!/--allow-seed/.test(capSrc)) { fail++; record("C2 门旗存在性", "fail", "capture.mjs 无 --allow-seed 门旗"); }
  else record("C2 门旗存在性", "pass", "--allow-seed 文案在案");
  if (!/SANDBAR_UI_CAPTURE_ALLOW_SEED/.test(capSrc)) { fail++; record("C2 env 门旗", "fail", "无 SANDBAR_UI_CAPTURE_ALLOW_SEED"); }
  else record("C2 env 门旗", "pass", "env 门旗在案");
  // 缺旗报错交人：navigateToChat 的 throw 文案必须含门旗指引。
  if (!/未带 --allow-seed/.test(capSrc)) { fail++; record("C2 缺旗报错文案", "fail", "navigateToChat 缺旗报错文案缺失"); }
  else record("C2 缺旗报错文案", "pass", "无 MRU 行且缺旗=明确报错交人");
  return fail;
}

let fail = await unitGuards();
fail += await gateRedLine();
// 260904 回迁守卫（KI-036）：本树与主树 ui-check 均缺 playwright-core（安装=宿主
// 沙箱外 npm install）→ C1 全链记 ENV_FAIL 退 2 不假红；依赖恢复后自动生效，断言面不变。
import { existsSync as _existsSync } from "node:fs";
const _pwMissing = !_existsSync(path.join(REPO_ROOT, "server", "ui-check",
                                         "node_modules", "playwright-core"))
  && !_existsSync(path.join(MAIN_UI_CHECK, "node_modules", "playwright-core"));
if (process.env.SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL === "1") {
  record("C1 capture-lane 全链", "env_fail", "SANDBAR_CAPTURE_CHAT_ACTIVE_FORCE_ENV_FAIL=1");
} else if (_pwMissing) {
  record("C1 capture-lane 全链", "env_fail",
    "KI-036：ui-check 缺 playwright-core（本树+主树均无），宿主沙箱外安装后本链自动恢复");
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
