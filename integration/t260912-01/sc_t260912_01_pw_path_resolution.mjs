#!/usr/bin/env node
// t260912-01 八条界面场景依赖解析统一守卫（集成 L2/L3，读源断言 + 位置无关真跑子用例）。
//
// 用户可感知契约（被钉面）：八条浏览器场景在**任意泳道布局**（含 /private/tmp/<任意>
// 这类不在 <主仓>/.lane/<票>/ 下的副本）都不得再把「布局算错」谎报成
// 「playwright-core unavailable / 本树+主树均无 / 沙箱外安装」——依赖解析统一走
// lib_pw_deps.mjs 单源（git-common-dir 口径，位置无关），探测失败只许**事实点名**
// （列出探过的候选路径），归因不得引向环境。
//
// 子用例面：
//   G0  前置：git 在场（缺席=ENV_FAIL，git-common-dir 口径无处落地）；
//   G1  读源断言：八文件逐个引用 lib_pw_deps + 禁主树位置算术/候选字面量 +
//       禁谎言文案（措辞级禁令；泳道根 `HERE/../..` 形态是位置无关合法面，豁免）；
//   G1b lib 契约在文：--git-common-dir 口径 + 双 env 名（新名 SANDBAR_PLAYWRIGHT_PATH
//       优先、旧名 SANDBAR_PLAYWRIGHT_MODULE 同语义兜底——旧名下游 capture.mjs/
//       capture-lane.mjs 仍在消费，单砍旧名=静默砍通路）；
//   G2  守卫自证防恒真：变异样本（主树算术/候选字面量/谎言文案）必咬、
//       合法泳道根样本与干净样本必过；
//   G3  双算互证：lib.mainRoot() === 直接 git rev-parse --git-common-dir 的 dirname；
//   G4  位置无关组合路径子用例（临时主仓 A + git worktree B + lib 副本）：副本的
//       mainRoot() 必指 A，loadPlaywright() 必真装载（A 软链真 playwright-core 包，
//       旧 `../..` 算术在此布局指错目录=负面对照打印）；终态回收零残留；
//   G5  本泳道子用例：mainRoot()==主树 且 loadPlaywright() 可装载（缺席=ENV_FAIL
//       点名真实路径——环境缺件归环境，不谎报布局）。
//
// 与既有 intent 分界：与 t260907-01-migration-path-hygiene（suyou 旧字面量卫生）、
// t260911-01-filter-contract-guard（跨语言真源契约）不同面——本条守**八条场景的
// 依赖解析口径统一与文案诚实**。lib 副本关系与故障模式取舍清单见 lib_pw_deps.mjs
// 头注（env 覆盖/git 缺席回落/存在性检查/逐候选降级/全失败返 null 五项照搬声明）。
// 实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, realpathSync, rmSync, symlinkSync, readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const INTEG = resolve(HERE, "..");
const REPO = resolve(INTEG, "..");            // 泳道仓根（本文件位置父二，位置无关合法面）
const LIB = join(INTEG, "lib_pw_deps.mjs");

// 单源消费方清单（原「八文件」）：261001 宿主令退休 sc_t01_click_no_chat_switch.mjs
// 与其 baselines 兄弟后，本清单同步收窄——**退休一个场景必须同时扫这类在场清单**
// （漏扫=本场景以「文件缺失」报红，2026-10-01 实案）。
const CONSUMERS = [
  "t260903-07/sc_t02_chat_project_tag.mjs",
  "t260904-07/sc_session_charter_injection_journey.mjs",
  "t260905-09/sc_platform_context_fold_stacked.mjs",
  "t260901-24/sc_t04_gate_interlock.mjs",
  "baselines/sc_ticket_session_restore.mjs",
  "baselines/sc_ticket_evidence_images.mjs",
  "baselines/sc_capture_chat_active.mjs",
];

let passed = 0, failed = 0, envFailed = 0;
function ok(cond, label, detail = "") {
  if (cond) { passed++; console.log(`  ok  ${label}`); }
  else { failed++; console.log(`  FAIL ${label} ${String(detail).slice(0, 300)}`); }
}
function envFail(label) {
  envFailed++; console.log(`  ENV_FAIL ${label}（环境缺件，没验成——原因归环境）`);
}
function info(label) { console.log(`  ..  ${label}`); }

// ---------------- 检测器（纯函数；G1 与 G2 共用同一实现，防两套口径漂移） ----------------
// 主树位置算术/候选字面量：只扫代码面（整行 // 注释剔除——注释里的路径叙述不算探测面）。
// 谎言文案：全文扫（注释里复述谎话同样误导后人，措辞级禁令）。
function stripFullLineComments(text) {
  return text.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
}
const ARITH_PATTERNS = [
  ["resolve(REPO,'..','..') 主树算术", /resolve\(\s*REPO\s*,\s*['"]\.\.['"]\s*,\s*['"]\.\.['"]\s*\)/],
  ["path.resolve(REPO_ROOT,\"..\",\"..\") 主树算术", /path\.resolve\(\s*REPO_ROOT\s*,\s*['"]\.\.['"]\s*,\s*['"]\.\.['"]\s*\)/],
  ["MAIN_TREE 标识符", /\bMAIN_TREE\b/],
  ["ui-check/node_modules/playwright-core 候选字面量", /ui-check\/node_modules\/playwright-core/],
];
const LYING_PATTERNS = [
  ["「playwright-core unavailable」孤立断言", /playwright-core unavailable/],
  ["「沙箱外安装」归因", /沙箱外安装/],
  ["「本树+主树均无」断言", /本树\+主树均无/],
];
function scanSource(text) {
  const code = stripFullLineComments(text);
  const hits = [];
  for (const [label, re] of ARITH_PATTERNS) if (re.test(code)) hits.push(label);
  for (const [label, re] of LYING_PATTERNS) if (re.test(text)) hits.push(label);
  return hits;
}

// ---------------- G0 前置 ----------------
const gitProbe = spawnSync("git", ["--version"], { encoding: "utf8" });
if (gitProbe.status !== 0) {
  envFail("git 缺席：git-common-dir 口径无处落地（git --version 失败）");
  console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=0`);
  process.exit(2);
}

// ---------------- G2 守卫自证（先于 G1，防检测器失明恒真） ----------------
{
  const samples = [
    [`const MAIN_TREE = path.resolve(REPO_ROOT, "..", "..");`, true, "变异样①主树算术(REPO_ROOT)必咬"],
    [`const MAIN = resolve(REPO, '..', '..');`, true, "变异样②主树算术(REPO)必咬"],
    [`const p = new URL('../../server/ui-check/node_modules/playwright-core/index.mjs', import.meta.url);`, true, "变异样③候选字面量必咬"],
    [`record('browser/deps', 'env_fail', 'playwright-core unavailable');`, true, "变异样④谎言文案必咬"],
    [`console.log('宿主沙箱外安装恢复后本链自动生效');`, true, "变异样⑤沙箱外归因必咬"],
    [`const REPO = resolve(HERE, '..', '..');   // 泳道根解析`, false, "合法样⑥泳道根 HERE 形态必须放行"],
    [`const x = 1;`, false, "干净样⑦必须放行"],
  ];
  for (const [sample, shouldFlag, label] of samples) {
    const hits = scanSource(sample);
    ok(shouldFlag ? hits.length > 0 : hits.length === 0, `G2 ${label}`, `hits=${JSON.stringify(hits)}`);
  }
}

// ---------------- G1 读源断言（单源消费方清单 + lib 契约） ----------------
for (const rel of CONSUMERS) {
  const f = join(INTEG, rel);
  if (!existsSync(f)) { ok(false, `G1 ${rel} 在场`, "文件缺失"); continue; }
  const text = readFileSync(f, "utf8");
  const hits = scanSource(text);
  ok(hits.length === 0, `G1 ${rel} 零主树算术/零候选字面量/零谎言文案`, `hits=${JSON.stringify(hits)}`);
  ok(/lib_pw_deps/.test(text), `G1 ${rel} 引用 lib_pw_deps 单源`, "无 lib_pw_deps 引用");
}
{
  const t04 = readFileSync(join(INTEG, "t260901-24/sc_t04_gate_interlock.mjs"), "utf8");
  ok(t04.includes("SANDBAR_PLAYWRIGHT_MODULE"),
    "G1 sc_t04 保留旧 env 名通路（子进程 fallback 名不静默砍）", "SANDBAR_PLAYWRIGHT_MODULE 缺席");
  if (!existsSync(LIB)) {
    ok(false, "G1b lib_pw_deps.mjs 在场（本票交付物）", "文件缺失");
  } else {
    const libText = readFileSync(LIB, "utf8");
    ok(libText.includes("--git-common-dir"), "G1b lib 走 git-common-dir 口径", "无 --git-common-dir");
    ok(libText.includes("SANDBAR_PLAYWRIGHT_PATH") && libText.includes("SANDBAR_PLAYWRIGHT_MODULE"),
      "G1b lib 双 env 名同认（新名优先/旧名兜底）", "双名缺一");
  }
}

// ---------------- git-common-dir 直算（G3/G4/G5 共用） ----------------
function gitCommonDir(cwd) {
  const r = spawnSync("git", ["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
    { encoding: "utf8" });
  const dir = (r.stdout || "").trim();
  return r.status === 0 && dir ? dir : null;
}
const MAIN_TREE = (() => {           // 仅守卫内部用（检测器只扫八文件与 lib，不扫本文件）
  const d = gitCommonDir(REPO);
  return d ? realpathSync(dirname(d)) : null;
})();

let lib = null;
try {
  lib = await import(pathToFileURL(LIB).href);
} catch (e) {
  ok(false, "G3 lib_pw_deps.mjs 可导入（本票交付物未落地即红）", String(e).slice(0, 160));
}

// ---------------- G3 双算互证 ----------------
if (lib && MAIN_TREE) {
  let got = null;
  try { got = realpathSync(lib.mainRoot()); } catch { /* 缺席即红 */ }
  ok(got === MAIN_TREE, "G3 lib.mainRoot() === git-common-dir 双算互证", `lib=${got} git=${MAIN_TREE}`);
}

// ---------------- G4 位置无关组合路径子用例（临时主仓 A + worktree B + lib 副本） ----------------
let tmp = null, A = "", B = "";   // 预置外层：finally 回收子用例在任何抛点都可达（终态纪律）
if (lib && MAIN_TREE) {
  tmp = mkdtempSync(join(tmpdir(), "t260912-01-pw-"));
  A = join(tmp, "A-main");
  B = join(tmp, "B-lane");
  try {
    const sh = (args, cwd) => spawnSync("git", args, { cwd, encoding: "utf8" });
    mkdirSync(A, { recursive: true });
    sh(["init", "-q"], A);
    (await import("node:fs")).writeFileSync(join(A, "seed.txt"), "seed\n");
    sh(["-c", "user.email=t@t.local", "-c", "user.name=t", "add", "-A"], A);
    sh(["-c", "user.email=t@t.local", "-c", "user.name=t", "commit", "-qm", "seed"], A);
    // 真包软链进临时主仓：组合路径子用例才有真依赖可装载（只读主树，不写主树）
    const realPw = join(MAIN_TREE, "server", "ui-check", "node_modules", "playwright-core");
    const havePw = existsSync(realPw);
    if (havePw) {
      mkdirSync(join(A, "server", "ui-check", "node_modules"), { recursive: true });
      symlinkSync(realPw, join(A, "server", "ui-check", "node_modules", "playwright-core"), "dir");
    }
    const w = sh(["worktree", "add", "--detach", B], A);
    ok(w.status === 0, "G4a 临时主仓+worktree 夹具建立", (w.stderr || "").slice(0, 160));
    if (w.status === 0) {
      // lib 副本：mainRoot() 锚定 lib 自身位置（副本在 B 内 → 解析面=B 的仓=A）
      mkdirSync(join(B, "integration"), { recursive: true });
      copyFileSync(LIB, join(B, "integration", "lib_pw_deps.mjs"));
      const probe = [
        "import { pathToFileURL } from 'node:url';",
        "import(pathToFileURL(process.argv[2]).href).then(async (m) => {",
        "  const root = m.mainRoot();",
        "  let pw = null; try { pw = await m.loadPlaywright(); } catch (e) { pw = null; }",
        "  const faces = typeof m.pwProbeFaces === 'function' ? m.pwProbeFaces() : null;",
        "  console.log('PROBE ' + JSON.stringify({ root, pwLoaded: !!pw, faces }));",
        "}).catch((e) => { console.log('PROBE-ERR ' + String(e).slice(0, 160)); process.exit(3); });",
      ].join("\n");
      writeFileSync(join(tmp, "probe.mjs"), probe);
      const p = spawnSync(process.execPath, [join(tmp, "probe.mjs"), join(B, "integration", "lib_pw_deps.mjs")],
        { cwd: B, encoding: "utf8" });
      const line = ((p.stdout || "").split("\n").find((l) => l.startsWith("PROBE")) || "");
      let payload = null;
      try { payload = JSON.parse(line.replace(/^PROBE /, "")); } catch { /* 解析失败即红 */ }
      ok(p.status === 0 && !!payload, "G4b 副本在 B 内可执行（node 子进程）",
        `status=${p.status} out=${((p.stdout || "") + (p.stderr || "")).slice(0, 200)}`);
      if (payload) {
        const rootEq = (() => { try { return realpathSync(payload.root) === realpathSync(A); } catch { return false; } })();
        ok(rootEq, "G4c 副本 mainRoot() 指临时主仓 A（位置无关）",
          `root=${payload.root} A=${A}`);
        const oldArith = resolve(B, "..", "..");
        info(`负面对照：旧 '../..' 算术在此布局指向 ${oldArith}（${realpathSync(oldArith) === realpathSync(A) ? "恰同=本布局不复发" : "≠A=恒假病灶复现形态"}）`);
        if (havePw) {
          ok(payload.pwLoaded === true,
            "G4d 组合路径真装载：loadPlaywright() 非 null（④路经 A 软链包）",
            `pwLoaded=${payload.pwLoaded} faces=${JSON.stringify(payload.faces)}`);
        } else {
          envFail(`主树 playwright-core 缺席：${realPw}（组合路径子用例无真包可链）`);
        }
      }
    }
  } finally {
    // 终态回收（资源生命周期纪律）：worktree remove --force 只删自建 B，再核零残留
    const created = !!A && existsSync(join(B, ".git"));
    let rmOk = true, residue = false, listOut = "";
    if (created) {
      const rmw = spawnSync("git", ["worktree", "remove", "--force", B], { cwd: A, encoding: "utf8" });
      rmOk = rmw.status === 0;
      const lst = spawnSync("git", ["worktree", "list"], { cwd: A, encoding: "utf8" });
      listOut = lst.stdout || "";
      residue = listOut.includes("B-lane");
    }
    try { if (tmp) rmSync(tmp, { recursive: true, force: true }); } catch { /* 已清 */ }
    ok(!created || (rmOk && !residue), "G4e 夹具终态回收零残留（worktree list 无 B）",
      `rm=${rmOk} list=${listOut.slice(0, 120)}`);
  }
}

// ---------------- G5 本泳道子用例 ----------------
if (lib && MAIN_TREE) {
  const mr = (() => { try { return lib.mainRoot(); } catch { return null; } })();
  ok(mr === MAIN_TREE, "G5a 本泳道 mainRoot()==主树", `mr=${mr}`);
  let pw = null;
  try { pw = await lib.loadPlaywright(); } catch { pw = null; }
  if (pw) {
    ok(true, "G5b 主树 playwright-core 可装载（事实路径在案）");
    info(`loadPlaywright() 装载成功（mainRoot=${mr}）`);
  } else {
    envFail(`主树 playwright-core 缺失：${join(MAIN_TREE, "server", "ui-check", "node_modules", "playwright-core")}（真实路径点名，不归因布局）`);
  }
  // G5c（review K2）：直接 import「mainRoot() 拼出的第④路候选路径」并断言暴露
  // chromium.launch——裸包 'playwright-core' 侥幸命中盖不住第④路缺陷（载荷面强断言）。
  const mainPwFile = join(mr, "server", "ui-check", "node_modules", "playwright-core", "index.mjs");
  if (!existsSync(mainPwFile)) {
    envFail(`G5c 主树候选不在：${mainPwFile}（真实路径点名）`);
  } else {
    let mod = null;
    try { mod = await import(pathToFileURL(mainPwFile).href); } catch { mod = null; }
    ok(mod && mod.chromium && typeof mod.chromium.launch === "function",
      "G5c mainRoot 拼出路径可 import 且暴露 chromium.launch（导入来源==第④路候选）",
      `path=${mainPwFile}`);
  }
  // G5d 事实文案面（lib 新增面 B）：点名双 env 名与主树候选，无归因话术。
  try {
    const det = lib.pwMissingDetail();
    ok(det.includes("SANDBAR_PLAYWRIGHT_PATH") && det.includes("SANDBAR_PLAYWRIGHT_MODULE")
      && det.includes("主树 "),
      "G5d 事实文案点名双 env 名与主树候选", det.slice(0, 160));
    ok(!/unavailable|沙箱|依赖缺失/.test(det), "G5d 文案无谎报归因词");
  } catch (e) {
    ok(false, "G5d 事实文案面可调用（pwMissingDetail 在场）", String(e).slice(0, 120));
  }
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=0`);
process.exit(failed > 0 ? 1 : envFailed > 0 ? 2 : 0);
