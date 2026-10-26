#!/usr/bin/env node
// capture-lane.mjs —— 泳道 UI 证据一键隔离台（t260829-07）。
//
// 用途：替代「人肉搭隔离台拍泳道截图」（t260829-01 审读、t260829-02/-06 补证据
// 全是手工）。一条命令完成：挑空闲端口 → 临时 DSH_HOME → 临时 profile（workbench
// 软链指向 --lane 泳道 build，其余插件仍指主树）→ boot dsh 控制台等就绪 →
// 调 capture.mjs 多视图截图 → finally 拆台。不碰 3099（一切用临时端口）。
//
// 用法：
//   node capture-lane.mjs --lane <worktree> --out <dir>   # 隔离台截图
//   node capture-lane.mjs --selftest                      # 干跑：不起控制台/浏览器
//
// 输出契约（t261005-13，与 ui_evidence 证据闸同契）：全部 PNG 落 --out **顶层
// （TOP LEVEL）**，非递归——证据闸只吃 <lane>/.sandbar/screenshots/ 顶层的
// *.png，before/、after/ 等子目录里的截图一律算缺证据（host ruling 261005-B）。
// 认证面回执（t261006-02，KI-205 第六层）：--out 顶层另落 auth-surface.json
// （auth_mode / probed_status / token_source_observed / 与舞台回执 token_source 的
// 一致性 / dsh 指纹）——钉住「capture 依赖的 dsh 认证面」，升级漂移可读可审计。
//
// 前置（拒跑语义，t260829-07 方案 0.4）：
//   - 泳道 lib/client.js 缺失 → 拒跑非零退出（指路先 build）；
//   - build 陈旧（lib/client.js mtime 早于 src/client|src/host 最新 mtime）→ 拒跑。
//     拍陈旧 build 的截图=证据造假，宁可没证据。mtime 误报（checkout 刷新 mtime）
//     是安全侧失败：人工重跑即可。
//   - 隔离台 preset 源缺失/畸形（t260901-02）：$HOME/.dsh/.agent-presets/sandbar-integration
//     不存在或缺 preset.yml/agent.cordis.yml → 拒跑（chat 态建会话必须该 preset，
//     仓库外人工工件；不自造假 preset 造假证据）。
//
// 终态回收矩阵（对照 capture.mjs 先例 + 本台新增责任，方案 0.1）：
//   正常完成 / 截图失败 / boot 不就绪超时 / SIGINT / SIGTERM —— 五条路径全部：
//   kill boot 进程组（detached+kill(-pid)，防控制台自己 spawn 的子进程残留）
//   + 关日志 fd + 删临时目录（DSH_HOME+软链）。process exit 钩子兜底（tornDown 防
//   重复拆）。

import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  closeSync, copyFileSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync,
  realpathSync, rmSync, statSync,
} from "node:fs";
import {
  copyFile as copyFileP, cp, mkdir, mkdtemp, readdir, rm, symlink, utimes,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";
import { perkeyIsHit, resolveCredentialsSource } from "./creds-source.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");  // server/ui-check → 仓根（t260907-10 摊平后两层）

function parseArgs(argv) {
  const args = { lane: null, out: null, selftest: false, stageJson: null, bootLocal: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--lane") args.lane = argv[++i] ?? "";
    else if (a === "--out") args.out = argv[++i] ?? "";
    else if (a === "--selftest") args.selftest = true;
    else if (a === "--stage-json") args.stageJson = argv[++i] ?? "";
    else if (a === "--boot-local") args.bootLocal = true;
    else throw new Error(`未知参数：${a}`);
  }
  return args;
}

/** 挑一个空闲 TCP 端口：listen 0 让内核分配，拿到后立即关闭（有竞态窗口，可接受——
 * 只用于临时隔离台，端口被抢的概率远小于人肉挑端口撞车）。 */
async function pickFreePort() {
  const net = await import("node:net");
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function listFilesRecursive(dir) {
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...listFilesRecursive(p));
    else out.push(p);
  }
  return out;
}

// 泳道 build 前置校验盯的源码集（与 build-client.sh 落 stamp 的集合必须一致：
// 集合漂移=恒 mismatch 恒拒跑，改任一侧都要同步另一侧）。
const WATCHED_SRC_DIRS = ["src/client", "src/host", "src/shared"];
// stamp 落点=workbench 包根（.build-stamp.json），不放 lib/：lib 是 git 观测目录，
// ensureLaneBuild 的字节一致守卫用 git status --porcelain 判「重建漂移」，未跟踪
// 文件也会被当漂移（t261026-23 arbitrate gen2 实锤）。包根文件不进守卫观测面。
const STAMP_RELPATH = path.join(".build-stamp.json");
const ARTIFACT_RELPATHS = ["lib/client.cjs", "lib/client.js"];
const HEX64 = /^[0-9a-f]{64}$/;

function sha256File(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

/** 内容 stamp（t261026-23）：freshness 按内容判，不按时钟。checkout 按树序写文件，
 * 同批检出的 src mtime 晚于 lib（t261026 实雷：byte 级零 diff 仍被 mtime 规则误判
 * 陈旧→拒跑）。stamp 由 build-client.sh 成功路径落 .build-stamp.json（workbench 包根）：sources=
 * 盯防源码集逐文件 sha256，artifacts=产物逐字节 sha256（手改 lib 不重建也拦）。
 * 这里重算同一集合与 stamp 逐项比对。返回 null=fresh，否则为 {rule, detail} 拒因。 */
function stampCheckReason(laneWbDir) {
  const stampPath = path.join(laneWbDir, STAMP_RELPATH);
  let stamp;
  try {
    stamp = JSON.parse(readFileSync(stampPath, "utf8"));
  } catch {
    return { rule: "stamp-malformed", detail: `${STAMP_RELPATH} 缺失字段/不可读/非 JSON` };
  }
  if (!stamp || typeof stamp !== "object" || Array.isArray(stamp) ||
      stamp.version !== 1 || stamp.algorithm !== "sha256" ||
      !stamp.sources || typeof stamp.sources !== "object" || Array.isArray(stamp.sources) ||
      !stamp.artifacts || typeof stamp.artifacts !== "object" || Array.isArray(stamp.artifacts)) {
    return { rule: "stamp-malformed", detail: `${STAMP_RELPATH} 结构不符（version/algorithm/sources/artifacts）` };
  }
  for (const [k, v] of Object.entries({ ...stamp.sources, ...stamp.artifacts })) {
    if (typeof v !== "string" || !HEX64.test(v)) {
      return { rule: "stamp-malformed", detail: `${STAMP_RELPATH} 哈希值非 sha256 hex：${k}` };
    }
  }
  // 产物逐字节比对：手改 lib 冒充现场=证据造假，内容不匹配即拦（mtime 规则追不到）。
  for (const rel of ARTIFACT_RELPATHS) {
    const p = path.join(laneWbDir, rel);
    if (!existsSync(p)) {
      return { rule: "stamp-mismatch", detail: `${rel} 不在树上（stamp 声明其存在）` };
    }
    const actual = sha256File(p);
    if (stamp.artifacts[rel] !== actual) {
      return { rule: "stamp-mismatch", detail: `${rel} 内容与 stamp 不符（期望 ${stamp.artifacts[rel]?.slice(0, 12)}…，实际 ${actual.slice(0, 12)}…）` };
    }
  }
  // 源码集重算比对：键集必须完全一致（树里多的/少的都是漂移），值不同=真陈旧。
  const actualSources = {};
  for (const sub of WATCHED_SRC_DIRS) {
    const dir = path.join(laneWbDir, sub);
    if (!existsSync(dir)) continue; // 泳道没有的子目录不算陈旧证据
    for (const f of listFilesRecursive(dir)) {
      actualSources[path.relative(laneWbDir, f).split(path.sep).join("/")] = sha256File(f);
    }
  }
  for (const rel of Object.keys(stamp.sources)) {
    if (!(rel in actualSources)) {
      return { rule: "stamp-mismatch", detail: `盯防源码 ${rel} 不在树上（stamp 声明其存在）` };
    }
    if (stamp.sources[rel] !== actualSources[rel]) {
      return { rule: "stamp-mismatch", detail: `盯防源码 ${rel} 内容与 stamp 不符（真陈旧，重建 bundle）` };
    }
  }
  for (const rel of Object.keys(actualSources)) {
    if (!(rel in stamp.sources)) {
      return { rule: "stamp-mismatch", detail: `盯防源码 ${rel} 在树上有而 stamp 没有（stamp 旧于源码，重建）` };
    }
  }
  return null;
}

/** 泳道 build 前置校验（方案 0.4 拒跑语义）。返回 null=可跑，否则为人话拒因。
 * 规则序（t261026-23）：先内容 stamp（有 stamp 的树按内容判，不看时钟），
 * 无 stamp 才回落 2s mtime 规则（老树兜底）。拒因一律点名命中哪条规则。 */
export function laneBuildRejectReason(laneWbDir) {
  const lib = path.join(laneWbDir, "lib", "client.js");
  if (!existsSync(lib)) {
    return `泳道 build 缺失：${lib} 不存在。先在泳道构建：` +
      `cd <lane>/server/plugins/workbench && bash server/plugins/workbench/build-client.sh`;
  }
  if (existsSync(path.join(laneWbDir, STAMP_RELPATH))) {
    const reason = stampCheckReason(laneWbDir);
    if (reason) {
      return `泳道 build 陈旧（rule=${reason.rule}）：${reason.detail}。` +
        `拍陈旧/被改 build 的截图=证据造假，先在泳道重建 bundle 再跑：` +
        `cd <lane>/server/plugins/workbench && bash build-client.sh`;
    }
    return null;
  }
  const buildM = statSync(lib).mtimeMs;
  let newestSrc = 0;
  let newestPath = "";
  for (const sub of WATCHED_SRC_DIRS) {
    const dir = path.join(laneWbDir, sub);
    if (!existsSync(dir)) continue; // 泳道没有的子目录不算陈旧证据
    for (const f of listFilesRecursive(dir)) {
      const m = statSync(f).mtimeMs;
      if (m > newestSrc) { newestSrc = m; newestPath = path.relative(laneWbDir, f); }
    }
  }
  // 容差 2s：git checkout 按树序写文件，同批检出的 lib/src mtime 相差毫秒级
  // （t260903-12 两建实雷：18ms 写序差被误判陈旧→拒跑）。分钟级陈旧仍必拦
  // （防伪语义不变：拍陈旧 build 截图=证据造假）。仅无 stamp 的树走本规则。
  const MTIME_TOL_MS = 2000;
  if (newestSrc > buildM + MTIME_TOL_MS) {
    return `泳道 build 陈旧（rule=mtime-fallback，树无内容 stamp）：lib/client.js` +
      `（${new Date(buildM).toISOString()}）早于源码 ` +
      `${newestPath}（${new Date(newestSrc).toISOString()}，容差 ${MTIME_TOL_MS}ms）。` +
      `拍陈旧 build 的截图=证据造假，先在泳道重建 bundle 再跑：` +
      `cd <lane>/server/plugins/workbench && bash build-client.sh`;
  }
  return null;
}

/** 隔离台 preset 物化拒因（t260901-02，镜像 laneBuildRejectReason 的拒跑模式：
 * 人话拒因 + 纯函数可单测 + 安全侧失败——缺源=拒跑指路，不自造假 preset 造假证据）。
 * 返回 null=可物化，否则为人话拒因。源=仓库外实体 $HOME/.dsh/.agent-presets/sandbar-integration/
 * （cordis.patch.yml：用户 preset 唯一入口、软链不被扫描；agent.cordis.yml 是 dsh 出厂
 * standard 组合现役版原样拷贝 + persona 内联，仓库内无真源，不现拼）。 */
export function presetMaterializeRejectReason(srcDir) {
  if (!existsSync(srcDir)) {
    return `隔离台 preset 源缺失：${srcDir} 不存在。chat 态建会话需控制台默认 preset ` +
      `sandbar-integration（仓库外人工工件）。按 server/profile/cordis.patch.yml 的 ` +
      `agent-presets 注释在主 checkout 用户家重建该实体目录（preset.yml + agent.cordis.yml，` +
      `实体复制，软链不被扫描），或用 SANDBAR_CAPTURE_PRESET_SOURCE 指向替代源。`;
  }
  for (const f of ["preset.yml", "agent.cordis.yml"]) {
    const p = path.join(srcDir, f);
    if (!existsSync(p)) return `隔离台 preset 源畸形：${srcDir} 缺 ${f}（人工工件不完整，拒绝物化出假 preset）`;
  }
  return null;
}

/** 把 preset 源实体复制进临时 DSH_HOME（t260901-02 根治项）。必须实体复制：
 * roster 只扫 $DSH_HOME/.agent-presets/ 实体目录，软链不被扫描（cordis.patch.yml 实证）。
 * 复制后自校验关键文件落地为实体——校验不过即抛（boot 前拒跑）。 */
export async function materializePresets(tmpHome, srcDir) {
  const dstDir = path.join(tmpHome, ".agent-presets", "sandbar-integration");
  await mkdir(path.dirname(dstDir), { recursive: true });
  await cp(srcDir, dstDir, { recursive: true });
  for (const f of ["preset.yml", "agent.cordis.yml"]) {
    const p = path.join(dstDir, f);
    if (!existsSync(p) || statSync(p).isSymbolicLink()) {
      throw new Error(`preset 物化自校验失败：${p} 未落地为实体文件（源 ${srcDir}）`);
    }
  }
  return dstDir;
}

/** 组临时 profile：复制 cordis 配置；node_modules 逐项 realpath 后软链，
 * 仅 sandbar-workbench 改指泳道 workbench 目录（泳道 lib/client.js 生效，其余插件不动）。 */
export async function buildTempProfile(tmpHome, laneWorkbenchDir) {
  const repoProfile = path.join(REPO_ROOT, "server", "profile");
  const profDir = path.join(tmpHome, "profiles", "sandbar");
  await mkdir(profDir, { recursive: true });
  for (const f of ["cordis.yml", "cordis.patch.yml", "package.json"]) {
    const src = path.join(repoProfile, f);
    if (existsSync(src)) await copyFileP(src, path.join(profDir, f));
  }
  const tsTools = path.join(repoProfile, "sandbar-tools.ts");
  if (existsSync(tsTools)) await symlink(tsTools, path.join(profDir, "sandbar-tools.ts"));
  const repoNm = path.join(repoProfile, "node_modules");
  const nm = path.join(profDir, "node_modules");
  await mkdir(nm, { recursive: true });
  let overridden = false;
  if (existsSync(repoNm)) {
    for (const name of readdirSync(repoNm)) {
      const dest = name === "sandbar-workbench" ? laneWorkbenchDir
        : (() => { try { return realpathSync(path.join(repoNm, name)); } catch { return null; } })();
      if (!dest) continue;
      await symlink(dest, path.join(nm, name));
      if (name === "sandbar-workbench") overridden = true;
    }
  }
  if (!overridden) {
    throw new Error(`主树 profile/node_modules 缺 sandbar-workbench 软链，无法改指泳道 build（查 ${repoNm}）`);
  }
  // headless profile 也软链一份（同构 docker-compose 测试控制台；截图台不 spawn，兜底）
  const profHeadless = path.join(tmpHome, "profiles", "sandbar-headless");
  const repoHeadless = path.join(REPO_ROOT, "server", "profile-headless");
  if (existsSync(repoHeadless)) await symlink(repoHeadless, profHeadless);
  return profDir;
}

// 台内注册表的项目 key（t261005-16，KI-204 ③）：隔离台不再绑定历史 suyou 项目，
// 自建一个工作区必然存在的台内项目（key 过 PROJECT_KEY_RE 白名单）。
export const BENCH_PROJECT_KEY = "capture-bench";

/**
 * 组台内注册表（t261005-16，KI-204 ③）：临时 DSH_HOME 是一个新家，注册表装载器
 * （TS project-registry.ts / Python engine/shared.py 两侧同构）在根无 `.migrated`
 * 标记时会从仓内历史种子 server/projects.yaml 重播迁移——把已退役的 suyou 项目
 * （dirs 指向本机已不存在的路径）种回注册表 ⇒ 新建会话按 dirs[0] 建工作区 → ENOENT。
 * 修法：给临时控制台预置一个**自带 `.migrated` 标记**的 per-key 注册表根（装载器
 * 见标记即跳过迁移，两侧判据一致），内含台内项目 capture-bench，其工作区目录
 * 预先 mkdir 必然存在——台在任何机器上都不再依赖机器现实的注册表。
 * 格式按 docs/design/sandbar-project-onboarding-contract-v1.md ①a schema v1，
 * 与装载器 serializeProjectYaml（project-registry.ts）逐字节同形：顶层
 * `schema: v1` + `project:` 列表——顶层平铺 key:/name:/dirs: 会被两侧解析器
 * 隔离进 quarantined（t261005-16 第一轮仲裁实测抓出，勿回退）。
 * key 必须等于所在目录名。
 * 返回注册表根绝对路径（调用方把它设进控制台 env 的 SANDBAR_PROJECTS_DIR）。
 * 舞台通路口径（t261005-16 仲裁第三轮）：opts.workspaceDir（宿主侧真实 mkdir 的
 * 工作区目录）与 opts.declaredWorkspacePath（写进 project.yaml 的路径）可分离——
 * docker 舞台把注册表 bind mount 进容器后，容器只能看见挂载树内的路径，写宿主
 * 临时绝对路径（/var/folders/...）＝把 KI-204 的死目录病灶换个路径重演（仲裁第
 * 三轮实锤：容器内 workspace-invalid-path）。缺省两者同值＝boot-local 行为不变。
 */
export async function buildBenchRegistry(tmpHome, opts = {}) {
  const root = path.join(tmpHome, "bench-registry", "projects");
  const projDir = path.join(root, BENCH_PROJECT_KEY);
  const wsDir = opts.workspaceDir || path.join(tmpHome, "bench-workspace");
  const declaredWs = opts.declaredWorkspacePath || wsDir;
  await mkdir(projDir, { recursive: true });
  await mkdir(wsDir, { recursive: true });
  const projectYaml = [
    "schema: v1",
    "project:",
    `  - key: ${BENCH_PROJECT_KEY}`,
    "    name: Capture Bench",
    "    dirs:",
    `      - ${declaredWs}`,
    "",
  ].join("\n");
  // `wx` 独占写（t261005-16 畸形输入纪律）：落点位已有同名文件（崩溃残留/人工改动）
  // → fail-loud 具名拒因，绝不静默覆盖。
  const fsp = await import("node:fs/promises");
  try {
    await fsp.writeFile(path.join(projDir, "project.yaml"), projectYaml,
      { encoding: "utf8", flag: "wx" });
  } catch (e) {
    throw new Error(`台内注册表构建失败：${path.join(projDir, "project.yaml")} 落点位被占（${e.code || e.message}）——拒绝静默覆盖，人工处置后重试`);
  }
  // `.migrated` 标记：装载器的跳过判据只认它（两侧同构）；内容照迁移器自己的
  // 格式落一行来源，便于隔离台现场人工判读。
  await fsp.writeFile(
    path.join(root, ".migrated"),
    "source: capture-lane bench registry (t261005-16)\n", "utf8");
  return root;
}

/**
 * dsh 认证面指纹（t261006-02，KI-205 第六层钉面）：跑一次 `<bin> --profile web --help`
 * （15s 超时；缺席/失败容忍 → source:"unavailable"，绝不因此拒跑），记录两个事实：
 *   fence       —— 帮助文本含 --trusted-host（本代「浏览器信任栅」的标记面）；
 *   tokenOption —— 帮助文本含 token 选项（上一代 token 面的标记；本代恒 false）。
 * 指纹随 <out>/auth-surface.json 落盘：dsh 升级让认证面漂移时，「哪一代的哪个面」
 * 可读可审计，而不是让所有 UI 票静默不可过（ticket required outcome 3）。
 * 已知盲区（review 条件 3，有意不钉）：本钉面只覆盖「有栅无 token」→「回 token 门」
 * 这一漂移方向；反向（token 门代带 token 回归）走 legacy 兑换路径照常绿——回执不是
 * 完备漂移检测器，只是方向性钉子。
 */
export function dshAuthFingerprint({ bin = "dsh", helpArgs = ["--profile", "web", "--help"] } = {}) {
  try {
    const p = spawnSync(bin, helpArgs, { encoding: "utf8", timeout: 15000 });
    const text = `${p.stdout ?? ""}${p.stderr ?? ""}`;
    if (p.error || (p.status !== 0 && text.trim() === "")) {
      return { fence: null, tokenOption: null, source: `unavailable (${bin})` };
    }
    return {
      fence: text.includes("--trusted-host"),
      tokenOption: /(^|\s)--[a-z-]*token/i.test(text),
      source: `${bin} --profile web --help`,
    };
  } catch {
    return { fence: null, tokenOption: null, source: "unavailable" };
  }
}

/**
 * 认证面裁决（t261006-02 纯函数；selftest 8/8 与 UT 直测同一张表）：给「探测到的
 * 首页 HTTP 状态 + 日志里提出的 token」，裁出 capture 的导航入口。
 *   200                 → 本代浏览器信任栅：裸 URL 即入口（authMode=browser-trust）。
 *   401/303 且有 token   → 上一代 token 门：带 token 地址首次跳转兑换 cookie
 *                        （authMode=token-gate，legacy 路径原样保留）。
 *   401/303 且无 token   → 拒绝（代际漂移）：点名「缺的是上一代 token 门的面，而这一代
 *                        构建只宣布浏览器信任栅（--trusted-host；token_source=none）」。
 *   其它状态             → 拒绝：不认识的面不猜。
 * review 条件 2（303 语义未实证）：303 可能是登录跳转，只在**真 200** 上走裸 URL
 * 分支；303 落谨慎路径（有 token 走兑换，无 token 拒绝）。
 * 拒绝不是时序问题：提高 SANDBAR_CAPTURE_LANE_BOOT_MS 无济于事（KI-205 02:5x，
 * 120000 阈值实测同败）。
 */
export function resolveAuthEntry({ port, status, token = "", fingerprint = null }) {
  const fp = fingerprint
    ? `（dsh 指纹：fence=${fingerprint.fence} tokenOption=${fingerprint.tokenOption} source=${fingerprint.source}）`
    : "";
  if (status === 200) {
    return { ok: true, entryUrl: `http://127.0.0.1:${port}/`, authMode: "browser-trust", status };
  }
  if (status === 401 || status === 303) {
    if (token) {
      return { ok: true, entryUrl: `http://127.0.0.1:${port}/?token=${token}`, authMode: "token-gate", status };
    }
    return { ok: false, authMode: "token-gate-no-token", status, refusal:
      `dsh 控制台要求认证（HTTP ${status}＝上一代 token 门面：/?token= 兑换 cookie）但本台取不到任何 token`
      + `——这是 dsh 代际漂移（KI-205 第六层）：缺的是「上一代 dsh 的 token 门面」，而安装的这一代构建只宣布`
      + `浏览器信任栅（--trusted-host；舞台回执 token_source=none，CLI 与启动行均无 token）。不是时序问题：提高 `
      + `SANDBAR_CAPTURE_LANE_BOOT_MS 无济于事（120000 实测同败）。${fp} `
      + `出路：确认目标台确实是这一代 dsh（token_source=none）后重跑；确要拍旧代 token 门台，须在该台日志可读处提供 token。` };
  }
  return { ok: false, authMode: `http-${status}`, status, refusal:
    `dsh 控制台首页返回未认识的状态 HTTP ${status}（既非 200 浏览器信任栅、也非 401/303 token 门）——不猜测，拒绝拍摄${fp}` };
}

/**
 * producer/gate 一致性比对（t261006-02，review 条件 1）：gate 观测面（authMode）vs
 * 舞台回执 token_source（producer 读点，integration/stage_docker.py 2306/2355 落的
 * none|docker-logs|cli）。不一致=漂移信号（scenario 断言红），返回值进
 * auth-surface.json 的 producer_agreement 字段。
 */
export function compareTokenSource(authMode, producerTokenSource) {
  if (producerTokenSource == null) return "receipt-without-token_source";
  const gateSaysNone = authMode === "browser-trust";
  return gateSaysNone === (producerTokenSource === "none") ? "agree" : "mismatch";
}

/**
 * 本地 console.log 的 token 提取（260928 引入，t261006-02 改语义）：上一代 dsh 0.1.5
 * 会话门在 console.log 打 `dsh web: http://…/?token=…`；取**最后一个** token 值
 * （多次启动取最近）。本代（浏览器信任栅）日志根本没有该行 → 返回 ""，交
 * resolveAuthEntry 裁决，不再把「取不到 token」当独立失败面。畸形输入（二进制垃圾、
 * 超长单行、文件不可读）一律安全返回 ""，不炸栈（selftest 8/8 覆盖）。
 */
function tokenFromLocalLog(logPath) {
  try {
    const log = readFileSync(logPath, "utf8");
    const m = log.match(/[?&]token=([A-Za-z0-9._~-]+)/g);
    if (!m) return "";
    const last = m[m.length - 1];
    return last.slice(last.indexOf("=") + 1);
  } catch { return ""; }
}

/** 舞台通路 token 提取（t261005-16 引入；t261006-02 起仅服务 token 门代）：docker
 * 舞台的 dsh 跑在容器里，日志经 `docker logs <project>-dsh` 提 token（先例
 * stage_docker._plugins_token_from_logs 同款正则）。取不到返回空串交
 * resolveAuthEntry 裁决——本代（token_source=none）本就无 token，空串是合法事实
 * 而非失败面。 */
function tokenFromDockerLogs(project) {
  try {
    const p = spawnSync("docker", ["logs", "--tail", "200", `${project}-dsh`],
      { encoding: "utf8", timeout: 15000 });
    const m = ((p.stdout ?? "") + (p.stderr ?? "")).match(/[?&]token=([A-Za-z0-9_-]{20,})/);
    return m ? m[1] : "";
  } catch { return ""; }
}

/** 舞台通路等台就绪（t261006-02 认证面裁决版）：轮询首页，首个可达响应交
 * resolveAuthEntry 裁决——200（本代浏览器信任栅）立即出裸 URL 入口；401/303
 * （上一代 token 门）等 docker logs 里的 token 现身（token 可能晚于端口可达）。
 * 超时=ENV_FAIL 语义的 Error：拒绝文案由 resolveAuthEntry 生成（点名哪一代的
 * 哪个面），不静默回落裸 URL。 */
export async function waitReadyStage(port, timeoutMs, project, fingerprint, tickMs = 500) {
  const t0 = Date.now();
  let reachable = false;
  let lastStatus = 0;
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`);
      lastStatus = res.status;
      // 200=浏览器信任栅在场；401/303=token 门在场。只有连不上才继续等。
      if (res.ok || res.status === 401 || res.status === 303) {
        reachable = true;
        const verdict = resolveAuthEntry({ port, status: res.status, token: tokenFromDockerLogs(project), fingerprint });
        if (verdict.ok) return verdict;
        // !ok（token 门但 token 未现）→ 继续轮询
      }
    } catch { /* 未就绪，继续轮询 */ }
    await new Promise(r => setTimeout(r, tickMs));
  }
  if (reachable) {
    const verdict = resolveAuthEntry({ port, status: lastStatus, token: "", fingerprint });
    throw new Error(`docker 舞台 ${timeoutMs}ms 内已可达但拿不到可用导航入口（127.0.0.1:${port}，project=${project}-dsh；`
      + `手动验证：docker logs ${project}-dsh 2>&1 | grep -o 'token=[A-Za-z0-9._~-]*'；若多个舞台并起请串行化后重跑）`
      + `——${verdict.refusal}`);
  }
  throw new Error(`docker 舞台 ${timeoutMs}ms 内未就绪（127.0.0.1:${port}）`
    + `——ENV_FAIL 可行动出路（KI-205 / t261006-01）：①提高等待阈值后重跑同一命令`
    + `（本台读 env SANDBAR_CAPTURE_LANE_BOOT_MS，默认 45000，可设如 120000）；`
    + `②确认舞台容器在跑（docker ps | grep ${project}-dsh）与 docker logs ${project}-dsh 可读；`
    + `③多个舞台并起时串行化起台后重跑。不回落裸 URL。`);
}

export async function waitReady(port, timeoutMs, logPath, fingerprint, tickMs = 500) {
  const t0 = Date.now();
  let reachable = false;
  let lastStatus = 0;
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`);
      lastStatus = res.status;
      // 200=本代浏览器信任栅（服务在场）；401/303=上一代 token 门在场。连不上才继续等。
      if (res.ok || res.status === 401 || res.status === 303) {
        reachable = true;
        const verdict = resolveAuthEntry({ port, status: res.status, token: tokenFromLocalLog(logPath), fingerprint });
        if (verdict.ok) return verdict;
        // !ok（token 门但 token 未现）→ 继续轮询：token 行可能晚于端口可达
      }
    } catch { /* 未就绪，继续轮询 */ }
    await new Promise(r => setTimeout(r, tickMs));
  }
  let tail = "";
  try {
    tail = readFileSync(logPath, "utf8").slice(-1200);
  } catch { /* 日志读不到 */ }
  if (reachable) {
    const verdict = resolveAuthEntry({ port, status: lastStatus, token: "", fingerprint });
    throw new Error(`dsh 控制台 ${timeoutMs}ms 内已可达但拿不到可用导航入口（127.0.0.1:${port}）`
      + `——${verdict.refusal}\nconsole.log 尾部：\n${tail || "（无日志）"}`);
  }
  throw new Error(`dsh 控制台 ${timeoutMs}ms 内未就绪（127.0.0.1:${port}）`
    + `——ENV_FAIL 可行动出路：①提高等待阈值后重跑同一命令`
    + `（env SANDBAR_CAPTURE_LANE_BOOT_MS，默认 45000）；②检查端口 127.0.0.1:${port}`
    + `是否被占用/防火墙拦截。console.log 尾部：\n${tail || "（无日志）"}`);
}

export async function main() {
  // 261006：导航入口由认证面裁决（resolveAuthEntry）给出——本代浏览器信任栅下是
  // 裸 URL（token_source=none），上一代 token 门下是带 token 地址（见 waitReady 头注）。
  let navUrl = "";
  let authMode = "";
  let probedStatus = 0;
  let fingerprint = null;       // dsh 认证面指纹（进 auth-surface.json 回执）
  let stagePath = false;        // 台来源：docker/stage-json=true，boot-local=false
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(`[capture-lane] 参数错误：${e.message}`);
    console.error("用法：node capture-lane.mjs --lane <worktree> --out <dir> [--selftest]");
    process.exit(2);
  }

  if (args.selftest) {
    await selftest();
    return;
  }

  if (!args.lane) { console.error("[capture-lane] 缺 --lane <worktree>"); process.exit(2); }
  if (!args.out) { console.error("[capture-lane] 缺 --out <dir>"); process.exit(2); }
  const lane = path.resolve(args.lane);
  const laneWb = existsSync(path.join(lane, "server", "plugins", "workbench"))
    ? path.join(lane, "server", "plugins", "workbench") : path.join(lane, "workbench");
  if (!existsSync(laneWb)) {
    console.error(`[capture-lane] 泳道 workbench 目录不存在：${laneWb}（--lane 应指泳道 worktree 根或其 workbench 目录）`);
    process.exit(2);
  }
  const reject = laneBuildRejectReason(laneWb);
  if (reject) { console.error(`[capture-lane] 拒跑：${reject}`); process.exit(2); }

  // ── 台来源（t260904-19：默认 docker 测试台；自搭 boot 降级为显式 --boot-local）──
  // 三态纪律：docker/镜像缺席=ENV_FAIL 点名退出 2，绝不静默回落自搭台；
  // --stage-json=消费外部舞台（生命周期归调用方，本脚本绝不拆）；--boot-local=显式降级。
  let port = null;
  let ownStageProject = null;   // 本脚本自起的台才负责拆
  let stageProject = null;      // 消费的舞台名（外部或自起），docker logs 提 token 用
  let stageBenchHome = null;    // docker 舞台的台内注册表宿主目录（t261005-16，本脚本自起的台负责清）
  const fetchAlive = async (p) => {
    try { const r = await fetch(`http://127.0.0.1:${p}/`, { signal: AbortSignal.timeout(3000) }); return r.status < 500; }
    catch { return false; }
  };
  if (args.stageJson) {
    let st = null;
    try {
      st = JSON.parse(readFileSync(args.stageJson, "utf8"));
    } catch (e) {
      console.error(`[capture-lane] ENV_FAIL: stage JSON 不可读/畸形（${args.stageJson}：${e.message}）——不回落自搭台`);
      process.exit(2);
    }
    port = st?.ports?.console;
    if (!Number.isInteger(port) || port <= 0) {
      console.error(`[capture-lane] ENV_FAIL: stage JSON 缺 ports.console（project=${st?.project ?? "?"}）——不回落自搭台`);
      process.exit(2);
    }
    if (!(await fetchAlive(port))) {
      console.error(`[capture-lane] ENV_FAIL: 外部舞台已死（console 127.0.0.1:${port} 不可达）——不回落自搭台、不拆外部台（生命周期归调用方）`);
      process.exit(2);
    }
    stageProject = st.project;
    console.log(`[capture-lane] 使用外部舞台 ${st.project}：127.0.0.1:${port}（拆台归调用方）`);
  } else if (!args.bootLocal) {
    const stageCli = path.join(REPO_ROOT, "integration", "stage_docker.py");
    if (!existsSync(stageCli)) {
      console.error(`[capture-lane] ENV_FAIL: stage_docker CLI 不存在（${stageCli}）——本树非全仓布局？`);
      process.exit(2);
    }
    const project = `capture-lane-${process.pid}`;
    const timeoutSec = Number(process.env.SANDBAR_CAPTURE_STAGE_TIMEOUT_SEC || 600);
    // 台内注册表注入（t261005-16，KI-204 验收打回面）：docker 容器若沿用 compose
    // 缺省 SANDBAR_PROJECTS_DIR=/nonexistent，装载器会从挂载的仓内历史种子重播
    // 已退役 suyou 项目（死宿主路径）→ 会话/工作区创建照旧 ENOENT——本票病灶在
    // 生产通路（merge_check 走的正是 docker 舞台）原样复现。修法与 boot-local
    // 通路同源：宿主侧 buildBenchRegistry 造注册表，经 stage_docker 的
    // --fixtures-dir（挂 /fixtures）+ SANDBAR_TEST_PROJECTS_DIR=/fixtures/projects
    // （compose 透传为容器内 SANDBAR_PROJECTS_DIR）注入容器，装载器见 .migrated
    // 即跳过种子（先例 integration/lib_stage_console.mjs 同一通道）。
    stageBenchHome = await mkdtemp(path.join(tmpdir(), "capture-lane-stage-bench-"));
    // 工作区落挂载树内（t261005-16 仲裁第三轮）：容器只认 /fixtures 下的路径，
    // 宿主临时绝对路径＝死目录病灶换路径重演（实锤：容器内 workspace-invalid-path）。
    await buildBenchRegistry(stageBenchHome, {
      workspaceDir: path.join(stageBenchHome, "bench-registry", "workspace"),
      declaredWorkspacePath: "/fixtures/workspace",
    });
    const benchFixturesDir = path.join(stageBenchHome, "bench-registry");
    const up = spawnSync("python3", [stageCli, "up", "--project", project,
      "--services", "full", "--timeout", String(timeoutSec),
      "--fixtures-dir", benchFixturesDir],
      { encoding: "utf8", timeout: timeoutSec * 1000 + 15000,
        env: { ...process.env, SANDBAR_TEST_PROJECTS_DIR: "/fixtures/projects" } });
    if (up.status !== 0) {
      const named = String(up.stderr ?? "").split("\n").filter((l) => l.startsWith("STAGE_")).at(-1);
      console.error(`[capture-lane] ENV_FAIL: docker 测试台起台失败——${named ?? `rc=${up.status} ${String(up.stderr ?? "").slice(0, 200)}`}`);
      process.exit(2);
    }
    const st = JSON.parse(String(up.stdout).trim().split("\n").at(-1));
    port = st.ports.console;
    ownStageProject = st.project;
    stageProject = st.project;
    console.log(`[capture-lane] docker 舞台就绪 ${st.project}：127.0.0.1:${port}（本脚本负责拆台）`);
  } else {
    console.log("[capture-lane] 降级说明：--boot-local 显式走自搭进程台（docker 缺席宿主的人工通路；闸内一律走 docker 舞台）");
  }

  const consoleCmd = (process.env.SANDBAR_CONSOLE_CMD || "dsh --profile sandbar").split(" ");
  const bootTimeoutMs = Number(process.env.SANDBAR_CAPTURE_LANE_BOOT_MS || 45000);
  let tmpHome = null;
  let proc = null;
  let logFd = null;
  let tornDown = false;
  const teardown = () => {
    if (tornDown) return;
    tornDown = true;
    if (ownStageProject) {
      try {
        spawnSync("python3",
          [path.join(REPO_ROOT, "integration", "stage_docker.py"), "down", "--project", ownStageProject],
          { encoding: "utf8", timeout: 180000 });
        console.log(`[capture-lane] 自起舞台 ${ownStageProject} 已拆`);
      } catch { console.error(`[capture-lane] 自起舞台 ${ownStageProject} 拆台失败（down 幂等可重试）`); }
    }
    if (proc && proc.pid && proc.exitCode === null && proc.signalCode === null) {
      try { process.kill(-proc.pid, "SIGTERM"); } catch { try { proc.kill("SIGKILL"); } catch {} }
    }
    if (logFd !== null) { try { closeSync(logFd); } catch { /* 已关 */ } }
    // rmSync（同步）：exit 钩子路径事件循环可能已停，异步 rm 会留 /tmp 残留（t260829-07 review 实测）
    if (tmpHome) { try { rmSync(tmpHome, { recursive: true, force: true }); } catch { /* 留警告 */ } }
    // docker 舞台的台内注册表宿主目录（t261005-16）：bind mount 真源，随拆台同清
    //（容器已停，宿主目录删除无窗口面；docker 分支单独造，boot-local 分支为 null）。
    if (stageBenchHome) { try { rmSync(stageBenchHome, { recursive: true, force: true }); } catch { /* 留警告 */ } }
  };
  process.on("exit", teardown);
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => { teardown(); process.exit(130); });
  }

  try {
    if (port === null) {
    // ── 自搭 boot（--boot-local 降级通路；docker 台模式跳过整段）──
    tmpHome = await mkdtemp(path.join(tmpdir(), "suyou-capture-lane-"));
    // 凭据从用户 DSH_HOME 拷入（截图不需要模型凭据，缺了不致命）。
    // **不拷 settings.yaml**：用户设置可能把 webserver 端口钉死（实测钉 3099，覆盖
    // CLI --port，撞生产控制台=红线事故）——端口必须只由本脚本的临时 --port 决定。
    // 凭据源按项回退（t260901-03）：运行环境常把 DSH_HOME 指到 worktree 内半空
    // 目录（有/无凭据皆有可能），凭据在 [DSH_HOME, $HOME/.dsh] 中取首个含
    // .credentials.yaml 的候选。preset 源仍按 t260901-02 钉死 $HOME（见下），不随此回退。
    // 凭据源（sandbar M1-2 + t261005-16 改绑）：per-key 首查改用台内项目 key
    // （capture-bench，见 buildBenchRegistry）——不再绑定历史 suyou 项目。capture-bench
    // 恒无 per-key 凭据 ⇒ 恒走 legacy 回落链 [DSH_HOME, $HOME/.dsh]，而 DSH_HOME=临时
    // 台且下方已把真 .credentials.yaml 拷入 ⇒ 行为与改绑前一致（截图本不需要模型凭据，
    // 缺了不致命）。**已接受的行为变化**（t261005-16 review 条件 2）：在 ~/.sandbar/
    // projects/suyou/credentials.yaml 在场的机器上，台不再命中该 per-key 凭据，一律
    // 回落 DSH_HOME 拷贝件——落点等价，无净效果。
    const credSrc = resolveCredentialsSource(BENCH_PROJECT_KEY);
    if (credSrc && !perkeyIsHit(BENCH_PROJECT_KEY, credSrc)) {
      console.error(`[capture-lane] 提示：台内项目 ${BENCH_PROJECT_KEY} 无 per-key 凭据，走 legacy 回落 ${credSrc}（契约①b 弃用窗口）`);
    }
    for (const f of [".credentials.yaml"]) {
      if (credSrc) await copyFileP(credSrc, path.join(tmpHome, f)).catch(() => {});
    }
    await buildTempProfile(tmpHome, laneWb);
    // 台内注册表（t261005-16，KI-204 ③）：预置自带 .migrated 标记的注册表根，
    // 阻断装载器从仓内历史种子重播已退役 suyou 项目（新家 ENOENT 病根），
    // 控制台 env 的 SANDBAR_PROJECTS_DIR 指过去（见下方 spawn env 块）。
    const benchRegistryRoot = await buildBenchRegistry(tmpHome);
    // preset 物化（t260901-02）：源=仓库外实体，**不随 env DSH_HOME**（空 DSH_HOME
    // 干净环境模拟时 env 只当隔离台目标；凭据源同因，见上方拷凭据注释）。
    // env SANDBAR_CAPTURE_PRESET_SOURCE 仅作单测/基线桩覆盖。
    const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
      || path.join(process.env.HOME || "", ".dsh", ".agent-presets", "sandbar-integration");
    const presetReject = presetMaterializeRejectReason(presetSrc);
    if (presetReject) { console.error(`[capture-lane] 拒跑：${presetReject}`); process.exit(2); }
    await materializePresets(tmpHome, presetSrc);
    port = await pickFreePort();
    logFd = openSync(path.join(tmpHome, "console.log"), "a");
    // 端口覆盖层：profile cordis.patch.yml 把 webserver 钉死 3099（CLI --port 盖不过
    // profile config）——用 --patch 覆盖层改指临时端口，杜绝碰生产 3099（红线）。
    const portPatch = path.join(tmpHome, "port_patch.yml");
    await (await import("node:fs/promises")).writeFile(
      portPatch,
      `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`,
      "utf8");
    // boot dsh 控制台（同构 docker-compose.test.yml 测试控制台；detached=进程组随拆台回收）
    proc = spawn(consoleCmd[0],
      [...consoleCmd.slice(1), "--patch", portPatch,
       "--port", String(port), "--host", "127.0.0.1", "--no-open"], {
        cwd: REPO_ROOT,
        env: {
          ...process.env,
          DSH_HOME: tmpHome,
          // 台内注册表（t261005-16）：两侧装载器（TS project-registry.ts / Py
          // engine/shared.py registry_root）env 优先级最高（空串/相对路径视为未设，
          // 这里是绝对路径）——控制台从此只看到台内项目 capture-bench（工作区必然
          // 存在），不再重播仓内历史种子。只作用于本临时控制台的 env 块，不外泄。
          SANDBAR_PROJECTS_DIR: benchRegistryRoot,
          // 控制台插件 wf API 指向的外部 Temporal（只读展示）；截图台不依赖它在线
          SANDBAR_TARGET_HOST: process.env.SANDBAR_CAPTURE_TARGET_HOST
            || process.env.SANDBAR_TARGET_HOST || "127.0.0.1:17233",
          // 凭据来源：capture-lane 已把用户真 .credentials.yaml 拷进临时 DSH_HOME
          // （见上方 copyFile 循环），控制台从这里读到真 key——准入与模型调用全通。
          // ⚠️ 不要在此处 env 硬设 DEEPSEEK_API_KEY 假值：env 优先级高于
          // .credentials.yaml，会把真 key 遮蔽成假 key（票 t260831-02 实锤：
          // 会话激活拿假 key 连 provider 必败，data-phase 恒 hero）。
        },
        detached: true,
        stdio: ["ignore", logFd, logFd],
      });
    // 261006：waitReady 现在回认证面裁决结果（{entryUrl, authMode, status}）——
    // 本代浏览器信任栅下裸 URL 即入口；它既是「台真就绪」的判据，也是下游
    // capture.mjs 的导航入口（见 capArgs 的 --url）。
    fingerprint = dshAuthFingerprint({ bin: consoleCmd[0] });
    const vLocal = await waitReady(port, bootTimeoutMs, path.join(tmpHome, "console.log"), fingerprint);
    navUrl = vLocal.entryUrl; authMode = vLocal.authMode; probedStatus = vLocal.status;
    console.log(`[capture-lane] 隔离台就绪：127.0.0.1:${port}（DSH_HOME=${tmpHome}；`
      + `auth surface=${authMode}，probed HTTP ${probedStatus}，入口=${navUrl}）`);
    } else {
      stagePath = true;
      // 舞台通路（外部 stage-json 或自起 docker）：同样由认证面裁决——本代
      // （token_source=none）200 直接过裸 URL；上一代 token 门（401/303）等容器日志
      // 里的 token 现身（legacy 兑换路径原样保留）。取不到且超时=ENV_FAIL 点名退出
      //（拒绝文案点名哪一代的哪个面），不静默回落裸 URL 假跑。
      try {
        fingerprint = dshAuthFingerprint();
        const vStage = await waitReadyStage(port, bootTimeoutMs, stageProject, fingerprint);
        navUrl = vStage.entryUrl; authMode = vStage.authMode; probedStatus = vStage.status;
      } catch (e) {
        console.error(`[capture-lane] ENV_FAIL: ${e.message}——不静默回落裸 URL 假跑（docker 缺席/容器日志不可读属环境面）`);
        process.exit(2);
      }
      console.log(`[capture-lane] 舞台就绪：127.0.0.1:${port}（auth surface=${authMode}，probed HTTP ${probedStatus}，project=${stageProject}）`);
    }
    await mkdir(args.out, { recursive: true });
    // 认证面回执（t261006-02 钉面，ticket required outcome 2/3）：gate 观测面 + dsh
    // 指纹 + 与舞台回执 token_source（producer 读点）的一致性比对（review 条件 1）。
    // 回执路径可由 env SANDBAR_CAPTURE_STAGE_RECEIPT 指入舞台租约/回执 JSON；不一致
    // =漂移信号：大声告警并写进回执（scenario 断言以此为准），不硬退——硬退会让
    // 纯回执缺字段的环境形态也拍不了照。
    let producerTokenSource = null;
    let producerAgreement = "not-provided";
    const receiptPath = process.env.SANDBAR_CAPTURE_STAGE_RECEIPT || "";
    if (receiptPath) {
      try {
        producerTokenSource = JSON.parse(readFileSync(receiptPath, "utf8"))?.token_source ?? null;
        producerAgreement = compareTokenSource(authMode, producerTokenSource);
        if (producerAgreement === "mismatch") {
          console.error(`[capture-lane] ⚠ 认证面漂移信号：舞台回执 token_source=${producerTokenSource}`
            + ` 但 gate 观测 auth surface=${authMode}（${receiptPath}）——代际漂移，scenario 断言将红`);
        }
      } catch (e) {
        producerAgreement = `receipt-unreadable: ${e.message}`;
      }
    }
    const surfReceipt = {
      auth_mode: authMode,
      probed_status: probedStatus,
      token_source_observed: authMode === "browser-trust"
        ? "none" : (stagePath ? "docker-logs" : "console-log"),
      producer_token_source: producerTokenSource,
      producer_agreement: producerAgreement,
      dsh_fingerprint: fingerprint,
      _ticket: "t261006-02 (KI-205 layer 6): capture bench adapted to this dsh generation's auth surface",
    };
    await (await import("node:fs/promises")).writeFile(
      path.join(args.out, "auth-surface.json"), JSON.stringify(surfReceipt, null, 1), "utf8");
    console.log(`[capture-lane] auth surface 回执 → ${path.join(args.out, "auth-surface.json")}`);
    // 状态注入 opt-in（t260901-24）：env SANDBAR_CAPTURE_FIXTURES=1（bench 级开关，
    // 本脚本只认这一个名字）才向 capture.mjs 追加 --fixtures；缺省不传=7 视图口径
    // 逐字节不变，agent_activities 两处调用方的 ui_evidence 证据永不含虚构票。
    // C1 防错配：子进程 env 剥掉 SANDBAR_UI_CAPTURE_FIXTURES（那是 capture.mjs 直跑
    // 通路专用名），保证台内注入单一开关来源——误设 capture 级 env 名也不会在台内
    // 形成第二开关（两 env 名作用域/优先级详见 ui-check/README.md）。
    const fixtureOptIn = process.env.SANDBAR_CAPTURE_FIXTURES === "1";
    if (fixtureOptIn) console.log("[capture-lane] 状态注入已 opt-in（SANDBAR_CAPTURE_FIXTURES=1）：本次截图含 fixture 注入态视图，证据以 fixture-manifest.json 为准");
    const capArgs = [path.join(HERE, "capture.mjs"),
      // 261006：--url 由认证面裁决给出（browser-trust=裸 URL；token-gate=带 token 地址）
      "--url", navUrl || `http://127.0.0.1:${port}/`, "--out", args.out, "--allow-seed"];
    // 旗必须带目录值：capture.mjs 把裸 --fixtures 的缺省值解析成 ""（falsy），
    // 静默不注入——台内显式传本目录 fixtures/ 包（t260901-24 真拍实测发现）。
    if (fixtureOptIn) capArgs.push("--fixtures", path.join(HERE, "fixtures"));
    const capEnv = { ...process.env };
    delete capEnv.SANDBAR_UI_CAPTURE_FIXTURES;
    const cap = spawn(process.execPath, capArgs, {
      cwd: lane,
      env: {
        ...capEnv,
        // 台内造数门旗（t260831-02）：隔离台 DSH_HOME 是临时的，capture.mjs 的
        // seedSessions（建真实会话 + 写本插件 localStorage 账册）只在本路径放行；
        // 直连生产路径不带旗，行为=明确报错交人（只读红线）。
        SANDBAR_UI_CAPTURE_ALLOW_SEED: "1",
        // 泳道不装 node_modules（t260829-02 先例）：playwright-core 从「主树」
        // ui-check 加载。泳道运行时主树 ≠ 本脚本所在树，用 SANDBAR_CAPTURE_MAIN_UI_CHECK
        // 覆盖（指主树 server/ui-check 目录）；缺省=本脚本所在树（主树直跑场景）。
        SANDBAR_PLAYWRIGHT_MODULE: path.join(
          process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK
          || path.join(REPO_ROOT, "server", "ui-check"),
          "node_modules", "playwright-core"),
      },
      stdio: ["ignore", "inherit", "inherit"],
    });
    const code = await new Promise((resolve) => cap.on("close", resolve));
    if (code !== 0) {
      console.error(`[capture-lane] capture.mjs 退出码 ${code}`);
      process.exitCode = code === null ? 1 : code;
    }
  } finally {
    teardown();
  }
  console.log("[capture-lane] 拆台完成（boot 进程组已回收、临时目录已删）");
}

async function selftest() {
  // 1. build 前置三态（0.4：缺失/陈旧拒跑，新鲜放行）
  const tmp = await mkdtemp(path.join(tmpdir(), "capture-lane-selftest-"));
  try {
    const r1 = laneBuildRejectReason(tmp);
    if (!r1 || !/缺失/.test(r1)) throw new Error("缺失 build 应拒跑");
    const wb = path.join(tmp, "server", "plugins", "workbench");
    for (const d of ["lib", "src/client", "src/host"]) await mkdir(path.join(wb, d), { recursive: true });
    await (await import("node:fs/promises")).writeFile(path.join(wb, "lib", "client.js"), "x");
    const old = new Date(Date.now() - 60_000);
    await utimes(path.join(wb, "lib", "client.js"), old, old);
    await (await import("node:fs/promises")).writeFile(path.join(wb, "src", "client", "index.tsx"), "x");
    const r2 = laneBuildRejectReason(wb);
    if (!r2 || !/陈旧/.test(r2)) throw new Error("陈旧 build 应拒跑");
    const fresh = new Date();
    const srcOlder = new Date(Date.now() - 30_000);
    await utimes(path.join(wb, "src", "client", "index.tsx"), srcOlder, srcOlder);
    await utimes(path.join(wb, "lib", "client.js"), fresh, fresh);
    const r3 = laneBuildRejectReason(wb);
    if (r3) throw new Error(`新鲜 build 不应拒跑：${r3}`);
    console.log("[capture-lane] selftest 1/8 绿：build 前置三态（缺失/陈旧拒跑、新鲜放行）");
    // 2. 挑端口
    const p = await pickFreePort();
    if (!(p > 0 && p < 65536)) throw new Error(`端口异常：${p}`);
    console.log(`[capture-lane] selftest 2/8 绿：空闲端口挑选（${p}）`);
    // 3. 临时 profile 组装（真跑一次，检查 sandbar-workbench 软链指到假泳道）
    const fakeLaneWb = path.join(tmp, "fakelane", "workbench");
    await mkdir(path.join(fakeLaneWb, "lib"), { recursive: true });
    await (await import("node:fs/promises")).writeFile(path.join(fakeLaneWb, "lib", "client.js"), "x");
    const profDir = await buildTempProfile(tmp, fakeLaneWb);
    const real = realpathSync(path.join(profDir, "node_modules", "sandbar-workbench"));
    const want = realpathSync(fakeLaneWb);
    if (real !== want) throw new Error(`sandbar-workbench 软链未指向泳道：${real}（期望 ${want}）`);
    console.log("[capture-lane] selftest 3/8 绿：临时 profile 组装（workbench 软链指向泳道）");
    // 4. preset 物化三态（t260901-02）：真源实体落地 / 畸形源拒跑 / 缺失源拒跑。
    //    全部用临时桩目录，不依赖真源在（CI/新机器可跑）；env 覆盖路径不在此测
    //    （materializePresets 直接收参，main() 的 SANDBAR_CAPTURE_PRESET_SOURCE 由基线测）。
    const presetSrcStub = path.join(tmp, "preset-src");
    await mkdir(presetSrcStub, { recursive: true });
    const rMiss = presetMaterializeRejectReason(path.join(tmp, "no-such-preset"));
    if (!rMiss || !/缺失/.test(rMiss)) throw new Error("缺失 preset 源应拒跑");
    const rMalformed = presetMaterializeRejectReason(presetSrcStub);
    if (!rMalformed || !/畸形/.test(rMalformed)) throw new Error("空 preset 源应拒跑");
    await (await import("node:fs/promises")).writeFile(path.join(presetSrcStub, "preset.yml"), "name: t\n");
    await (await import("node:fs/promises")).writeFile(path.join(presetSrcStub, "agent.cordis.yml"), "- id: x\n");
    const rOk = presetMaterializeRejectReason(presetSrcStub);
    if (rOk) throw new Error(`完整桩源不应拒跑：${rOk}`);
    const matDst = await materializePresets(tmp, presetSrcStub);
    if (matDst !== path.join(tmp, ".agent-presets", "sandbar-integration")) {
      throw new Error(`物化落点异常：${matDst}`);
    }
    for (const f of ["preset.yml", "agent.cordis.yml"]) {
      const p = path.join(matDst, f);
      if (!existsSync(p) || statSync(p).isSymbolicLink()) throw new Error(`物化后 ${f} 应为实体文件`);
    }
    console.log("[capture-lane] selftest 4/8 绿：preset 物化三态（缺失/畸形拒跑、完整源实体落地）");
    // 5/6（t260901-24）：状态注入 loadFixtures 三态——真 fixture 包放行；缺目录/坏 JSON/
    // 缺 _fixture 标记/软链桩各自人话拒因。真包路径=本目录 fixtures/（与脚本同树，
    // 泳道 worktree 也带同一份）；畸形桩全用临时目录，不污染真包。
    const cap = await import(path.join(HERE, "capture.mjs").replace(/\\/g, "/"));
    const realFx = await cap.loadFixtures(path.join(HERE, "fixtures"));
    if (realFx["tickets-list"].result.tickets.length < 2) throw new Error("真 fixture 包应含 ≥2 张票");
    const fxStub = path.join(tmp, "fx-stub");
    await mkdir(fxStub, { recursive: true });
    let rFx = null;
    try { cap.loadFixtures(path.join(tmp, "no-such-fx")); } catch (e) { rFx = e.message; }
    if (!rFx || !/缺失/.test(rFx)) throw new Error("缺 fixture 目录应拒跑");
    await (await import("node:fs/promises")).writeFile(path.join(fxStub, "tickets-list.json"), "{bad json", "utf8");
    rFx = null;
    try { cap.loadFixtures(fxStub); } catch (e) { rFx = e.message; }
    if (!rFx || !/解析失败/.test(rFx)) throw new Error("坏 JSON fixture 应拒跑");
    for (const f of cap.FIXTURE_FILES) {
      await (await import("node:fs/promises")).writeFile(path.join(fxStub, f),
        JSON.stringify(f === "tickets-list.json" ? { ok: true, result: { tickets: [] } } : { ok: true }), "utf8");
    }
    rFx = null;
    try { cap.loadFixtures(fxStub); } catch (e) { rFx = e.message; }
    if (!rFx || !/_fixture/.test(rFx)) throw new Error("缺 _fixture 标记应拒跑");
    const linkProbe = path.join(tmp, "fx-link");
    await mkdir(linkProbe, { recursive: true });
    await symlink(path.join(HERE, "fixtures", "tickets-list.json"),
      path.join(linkProbe, "tickets-list.json"));
    for (const f of cap.FIXTURE_FILES) {
      if (f !== "tickets-list.json") {
        await copyFileSync(path.join(HERE, "fixtures", f), path.join(linkProbe, f));
      }
    }
    rFx = null;
    try { cap.loadFixtures(linkProbe); } catch (e) { rFx = e.message; }
    if (!rFx || !/软链/.test(rFx)) throw new Error("软链 fixture 应拒跑");
    console.log("[capture-lane] selftest 5/8 绿：状态注入 loadFixtures 三态（真包放行；缺目录/坏 JSON/缺标记/软链各自人话拒因）");
    // 6/6（t260901-24）：routeDecision 只拦 GET（R3）+ query 不参与匹配（C3）+
    // contentType 恒 application/json（R4）。
    const realFx2 = await cap.loadFixtures(path.join(HERE, "fixtures"));
    const hit = cap.routeDecision("GET", "http://127.0.0.1:3199/sandbar-workbench/api/wf/tickets?project=demo", realFx2);
    if (!hit.fulfill || hit.fixture !== "tickets-list") throw new Error("带查询串的 GET /tickets 应命中 tickets-list（C3）");
    if (hit.fulfill.contentType !== "application/json") throw new Error("fulfill contentType 恒 application/json（R4）");
    const show = cap.routeDecision("GET", "http://x/sandbar-workbench/api/wf/tickets/T-FIX-A", realFx2);
    if (!show.fulfill || show.fixture !== "ticket-show-T-FIX-A") throw new Error("GET show T-FIX-A 应命中");
    for (const op of ["accept", "advance", "dispatch-next", "rework", "update"]) {
      const d = cap.routeDecision("POST", `http://x/sandbar-workbench/api/wf/tickets/T-FIX-A/${op}`, realFx2);
      if (!d.passthrough) throw new Error(`POST ${op} 必须放行（R3 写端点不可被 fulfill 吞）`);
    }
    const proj = cap.routeDecision("GET", "http://x/sandbar-workbench/api/wf/projects", realFx2);
    if (!proj.passthrough) throw new Error("projects 端点应放行走真数据");
    console.log("[capture-lane] selftest 6/8 绿：routeDecision（GET 命中/查询串不影响/POST 恒放行/contentType 硬条款）");
    // 7/7（t261005-16，KI-204 ③）：台内注册表——正常构造落齐三件（.migrated 标记 /
    // project.yaml schema v1 / 工作区目录），畸形输入（project.yaml 落点位已有同名
    // 目录）fail-loud 具名拒因，不静默吞。
    const benchTmp = path.join(tmp, "bench-home");
    await mkdir(benchTmp, { recursive: true });
    const benchRoot = await buildBenchRegistry(benchTmp);
    if (!statSync(path.join(benchRoot, ".migrated")).isFile()) {
      throw new Error("台内注册表缺 .migrated 标记（装载器会重播历史种子）");
    }
    const benchYaml = readFileSync(path.join(benchRoot, BENCH_PROJECT_KEY, "project.yaml"), "utf8");
    // 契约①a schema v1：顶层 `schema:` + `project:` 列表（顶层平铺 key:/name:/dirs:
    // 会被两侧解析器隔离——t261005-16 第一轮仲裁实锤，此处钉死形状防回退）。
    for (const line of ["schema: v1", "project:", `  - key: ${BENCH_PROJECT_KEY}`,
                        "    name: Capture Bench", "    dirs:"]) {
      if (!benchYaml.includes(line)) throw new Error(`台内 project.yaml 缺字段行：${line}（got: ${JSON.stringify(benchYaml)}）`);
    }
    const benchWs = benchYaml.match(/^    dirs:\n\s+-\s+(.+)$/m)?.[1];
    if (!benchWs || !statSync(benchWs).isDirectory()) {
      throw new Error(`台内工作区目录不存在：${benchWs}（建会话必 ENOENT）`);
    }
    const benchClash = path.join(benchTmp, "clash-home");
    await mkdir(path.join(benchClash, "bench-registry", "projects", BENCH_PROJECT_KEY, "project.yaml"),
      { recursive: true });
    let rBench = null;
    try { await buildBenchRegistry(benchClash); } catch (e) { rBench = e.message; }
    if (!rBench) throw new Error("project.yaml 落点位是目录时应 fail-loud，不得静默");
    // 舞台两路分离（t261005-16 仲裁第三轮）：workspaceDir（宿主 mkdir）与
    // declaredWorkspacePath（写进 yaml、容器视角）分离——声明路径必须是挂载树内
    // 容器可创建路径，宿主临时绝对路径＝死目录病灶重演。
    const benchStage = path.join(tmp, "bench-stage-home");
    const stageRoot = await buildBenchRegistry(benchStage, {
      workspaceDir: path.join(benchStage, "bench-registry", "workspace"),
      declaredWorkspacePath: "/fixtures/workspace",
    });
    const stageYaml = readFileSync(path.join(stageRoot, BENCH_PROJECT_KEY, "project.yaml"), "utf8");
    const stageWs = stageYaml.match(/^    dirs:\n\s+-\s+(.+)$/m)?.[1];
    if (stageWs !== "/fixtures/workspace") {
      throw new Error(`舞台通路应声明容器内路径 /fixtures/workspace（got: ${stageWs}）——宿主路径在容器内必死`);
    }
    if (!statSync(path.join(benchStage, "bench-registry", "workspace")).isDirectory()) {
      throw new Error("舞台通路宿主工作区目录未真实创建");
    }
    console.log(`[capture-lane] selftest 7/8 绿：台内注册表（.migrated 标记 + ${BENCH_PROJECT_KEY} schema v1 + 工作区在场；落点位被占 fail-loud；舞台两路分离 declare=/fixtures/workspace）`);
    // 8/8（t261006-02，KI-205 第六层）：认证面裁决表 + 畸形日志输入。同一张表由
    // integration/tests/test_capture_auth_surface.py 以子进程复测（两侧同源）。
    const A = resolveAuthEntry({ port: 3199, status: 200 });
    if (!A.ok || A.authMode !== "browser-trust" || A.entryUrl !== "http://127.0.0.1:3199/") {
      throw new Error("200 应裁 browser-trust 裸 URL 入口");
    }
    const B = resolveAuthEntry({ port: 3199, status: 401, token: "tok123" });
    if (!B.ok || B.authMode !== "token-gate" || B.entryUrl !== "http://127.0.0.1:3199/?token=tok123") {
      throw new Error("401+token 应裁 token-gate 带 token 入口");
    }
    for (const st of [401, 303]) {
      const C = resolveAuthEntry({ port: 3199, status: st, token: "" });
      if (C.ok) throw new Error(`${st} 无 token 应拒绝`);
      for (const need of ["token 门面", "这一代构建", "--trusted-host", "token_source=none", "SANDBAR_CAPTURE_LANE_BOOT_MS"]) {
        if (!C.refusal.includes(need)) throw new Error(`${st} 拒绝文案缺「${need}」（须点名哪一代的哪个面）`);
      }
    }
    const D = resolveAuthEntry({ port: 3199, status: 500 });
    if (D.ok || !/未认识的状态/.test(D.refusal)) throw new Error("未认识状态应拒绝且不猜");
    const E = resolveAuthEntry({ port: 3199, status: 200, fingerprint: { fence: true, tokenOption: false, source: "x" } });
    if (!E.ok || E.authMode !== "browser-trust") throw new Error("带指纹的 200 裁决应不受影响");
    // 畸形日志输入：token 提取安全返回空串，不炸栈。
    const garbageLog = path.join(tmp, "garbage.log");
    await (await import("node:fs/promises")).writeFile(garbageLog, Buffer.from([0x00, 0xff, 0xfe, 0x10, 0x80]) + "x".repeat(200000));
    if (tokenFromLocalLog(garbageLog) !== "") throw new Error("二进制垃圾日志应返回空 token");
    if (tokenFromLocalLog(path.join(tmp, "no-such.log")) !== "") throw new Error("不可读日志应返回空 token");
    const legacyLog = path.join(tmp, "legacy.log");
    await (await import("node:fs/promises")).writeFile(legacyLog,
      "boot\ndsh web: http://127.0.0.1:3199/?token=abc_def12345678901234\n");
    if (tokenFromLocalLog(legacyLog) !== "abc_def12345678901234") throw new Error("legacy 日志应提出 token");
    // 指纹：可注入桩（真 dsh 缺席容忍 → unavailable，不抛）。
    const fpStub = dshAuthFingerprint({ bin: process.execPath, helpArgs: ["-e", "console.log('--trusted-host <a> --port <p>')"] });
    if (fpStub.fence !== true || fpStub.tokenOption !== false) throw new Error(`指纹桩面不符：${JSON.stringify(fpStub)}`);
    const fpTok = dshAuthFingerprint({ bin: process.execPath, helpArgs: ["-e", "console.log('--token <t>')"] });
    if (fpTok.tokenOption !== true) throw new Error("指纹应认出 token 选项（上一代面）");
    const fpMiss = dshAuthFingerprint({ bin: "definitely-not-a-real-binary-t26100602" });
    if (fpMiss.source.indexOf("unavailable") !== 0) throw new Error(`缺席二进制应容忍为 unavailable：${JSON.stringify(fpMiss)}`);
    console.log("[capture-lane] selftest 8/8 绿：认证面裁决表（200 裸 URL / 401+token 兑换 / 401·303 无 token 拒绝点名代际面 / 未知状态不猜）+ 畸形日志安全 + 指纹可注入桩");
    console.log("[capture-lane] selftest 全绿（未 boot 控制台/浏览器）");
  } finally {
    await rm(tmp, { recursive: true, force: true }).catch(() => {});
  }
}

// 入口守卫（t260901-02）：integration 基线要 import 本文件的纯函数做断言——
// 无守卫时 import 即执行 main()（拿基线的 argv 跑，必非预期退出）。直跑不受影响。
const invokedDirectly = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  main().catch((e) => {
    console.error(`[capture-lane] 失败：${e && e.stack || e}`);
    process.exit(1);
  });
}
