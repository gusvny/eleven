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

/** 泳道 build 前置校验（方案 0.4 拒跑语义）。返回 null=可跑，否则为人话拒因。 */
export function laneBuildRejectReason(laneWbDir) {
  const lib = path.join(laneWbDir, "lib", "client.js");
  if (!existsSync(lib)) {
    return `泳道 build 缺失：${lib} 不存在。先在泳道构建：` +
      `cd <lane>/server/plugins/workbench && npx -y tsdown@0.22.2 -c tsdown.config.ts`;
  }
  const buildM = statSync(lib).mtimeMs;
  let newestSrc = 0;
  let newestPath = "";
  for (const sub of ["src/client", "src/host", "src/shared"]) {
    const dir = path.join(laneWbDir, sub);
    if (!existsSync(dir)) continue; // 泳道没有的子目录不算陈旧证据
    for (const f of listFilesRecursive(dir)) {
      const m = statSync(f).mtimeMs;
      if (m > newestSrc) { newestSrc = m; newestPath = path.relative(laneWbDir, f); }
    }
  }
  // 容差 2s：git checkout 按树序写文件，同批检出的 lib/src mtime 相差毫秒级
  // （t260903-12 两建实雷：18ms 写序差被误判陈旧→拒跑）。分钟级陈旧仍必拦
  // （防伪语义不变：拍陈旧 build 截图=证据造假）。
  const MTIME_TOL_MS = 2000;
  if (newestSrc > buildM + MTIME_TOL_MS) {
    return `泳道 build 陈旧：lib/client.js（${new Date(buildM).toISOString()}）早于源码 ` +
      `${newestPath}（${new Date(newestSrc).toISOString()}，容差 ${MTIME_TOL_MS}ms）。` +
      `拍陈旧 build 的截图=证据造假，先在泳道重建 bundle 再跑。`;
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

/**
 * 等台就绪，并返回**带 token 的首页地址**（260928 修，KI-156）。
 *
 * dsh 0.1.5 起 web 走**浏览器会话门**：匿名 `GET /` 恒 401（body=`dsh web authentication
 * required; …`）。旧判据只认 `res.ok` ⇒ 台其实已经起来、却永远判「未就绪」→ 45s 超时 →
 * 截图族全缺（实案：capture-chat-e2e / -active 两条场景红，日志尾部就是台自己打的 token 行）。
 * 新判据：**响应可达即算服务在场**（200/303/401 都收，连接被拒不收）；同时从 console.log
 * 抓 `dsh web: http://…/?token=…` 那行，把带 token 的地址当作导航入口（首次跳转兑换 cookie）。
 * 先例：`server/tools/stage_console.sh:640` 的自动认证（从 console.log 提 token 传给断言库）。
 */
function authUrlFromLog(logPath) {
  try {
    const log = readFileSync(logPath, "utf8");
    const m = log.match(/https?:\/\/[^\s"'<>]*[?&]token=[A-Za-z0-9._~-]+/g);
    return m ? m[m.length - 1] : "";
  } catch { return ""; }
}

async function waitReady(port, timeoutMs, logPath, tickMs = 500) {
  const t0 = Date.now();
  let reachable = false;
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`);
      // 401=会话门（服务已在场）；303/200=已放行。只有连不上才继续等。
      if (res.ok || res.status === 401 || res.status === 303) reachable = true;
      if (reachable) {
        const auth = authUrlFromLog(logPath);
        if (auth) return auth;
      }
    } catch { /* 未就绪，继续轮询 */ }
    await new Promise(r => setTimeout(r, tickMs));
  }
  let tail = "";
  try {
    tail = readFileSync(logPath, "utf8").slice(-1200);
  } catch { /* 日志读不到 */ }
  throw new Error(reachable
    ? `dsh 控制台 ${timeoutMs}ms 内**已可达但取不到带 token 首页地址**（127.0.0.1:${port}；`
      + `会话门需 /?token= 兑换 cookie，拿不到就不该按匿名 401 页继续截图）。console.log 尾部：\n${tail || "（无日志）"}`
    : `dsh 控制台 ${timeoutMs}ms 内未就绪（127.0.0.1:${port}）。console.log 尾部：\n${tail || "（无日志）"}`);
}

export async function main() {
  // 260928：带 token 的首页入口（会话门兑换用；见 waitReady 头注）
  let navUrl = "";
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
    console.log(`[capture-lane] 使用外部舞台 ${st.project}：127.0.0.1:${port}（拆台归调用方）`);
  } else if (!args.bootLocal) {
    const stageCli = path.join(REPO_ROOT, "integration", "stage_docker.py");
    if (!existsSync(stageCli)) {
      console.error(`[capture-lane] ENV_FAIL: stage_docker CLI 不存在（${stageCli}）——本树非全仓布局？`);
      process.exit(2);
    }
    const project = `capture-lane-${process.pid}`;
    const timeoutSec = Number(process.env.SANDBAR_CAPTURE_STAGE_TIMEOUT_SEC || 600);
    const up = spawnSync("python3", [stageCli, "up", "--project", project,
      "--services", "full", "--timeout", String(timeoutSec)],
      { encoding: "utf8", timeout: timeoutSec * 1000 + 15000 });
    if (up.status !== 0) {
      const named = String(up.stderr ?? "").split("\n").filter((l) => l.startsWith("STAGE_")).at(-1);
      console.error(`[capture-lane] ENV_FAIL: docker 测试台起台失败——${named ?? `rc=${up.status} ${String(up.stderr ?? "").slice(0, 200)}`}`);
      process.exit(2);
    }
    const st = JSON.parse(String(up.stdout).trim().split("\n").at(-1));
    port = st.ports.console;
    ownStageProject = st.project;
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
    // 凭据源（sandbar M1-2）：per-key 项目目录 ~/.sandbar/projects/suyou/credentials.yaml
    // 优先（UI 检查台固定服务 suyou 项目），未命中走既有 [DSH_HOME, $HOME/.dsh] legacy
    // 回退链（t260901-03）——统一经 creds-source.mjs（agent_activities.py 同构真源）。
    // preset 源仍按 t260901-02 钉死 $HOME（见下），不随此回退。
    const credSrc = resolveCredentialsSource("suyou");
    if (credSrc && !perkeyIsHit("suyou", credSrc)) {
      console.error(`[capture-lane] 提示：项目凭据未迁 ~/.sandbar/projects/suyou/credentials.yaml，仍用 legacy ${credSrc}（契约①b 弃用窗口）`);
    }
    for (const f of [".credentials.yaml"]) {
      if (credSrc) await copyFileP(credSrc, path.join(tmpHome, f)).catch(() => {});
    }
    await buildTempProfile(tmpHome, laneWb);
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
    // 260928：waitReady 现在回**带 token 的首页地址**（dsh 0.1.5 会话门）——它既是
    // 「台真就绪」的判据，也是下游 capture.mjs 的导航入口（见 capArgs 的 --url）。
    navUrl = await waitReady(port, bootTimeoutMs, path.join(tmpHome, "console.log"));
    console.log(`[capture-lane] 隔离台就绪：127.0.0.1:${port}（DSH_HOME=${tmpHome}；`
      + `带 token 入口=${navUrl ? "已取到" : "缺"}）`);
    } else {
      console.log(`[capture-lane] docker 台模式：preset 物化/凭据拷贝不适用（DSH_HOME 在容器卷内）；` +
        `chat 种子如需用户 preset 请用 --boot-local 人工通路`);
    }
    await mkdir(args.out, { recursive: true });
    // 状态注入 opt-in（t260901-24）：env SANDBAR_CAPTURE_FIXTURES=1（bench 级开关，
    // 本脚本只认这一个名字）才向 capture.mjs 追加 --fixtures；缺省不传=7 视图口径
    // 逐字节不变，agent_activities 两处调用方的 ui_evidence 证据永不含虚构票。
    // C1 防错配：子进程 env 剥掉 SANDBAR_UI_CAPTURE_FIXTURES（那是 capture.mjs 直跑
    // 通路专用名），保证台内注入单一开关来源——误设 capture 级 env 名也不会在台内
    // 形成第二开关（两 env 名作用域/优先级详见 ui-check/README.md）。
    const fixtureOptIn = process.env.SANDBAR_CAPTURE_FIXTURES === "1";
    if (fixtureOptIn) console.log("[capture-lane] 状态注入已 opt-in（SANDBAR_CAPTURE_FIXTURES=1）：本次截图含 fixture 注入态视图，证据以 fixture-manifest.json 为准");
    const capArgs = [path.join(HERE, "capture.mjs"),
      // 260928：优先用带 token 的地址（首次跳转兑换会话 cookie；否则 capture.mjs 拍到的是 401 页）
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
    console.log("[capture-lane] selftest 1/6 绿：build 前置三态（缺失/陈旧拒跑、新鲜放行）");
    // 2. 挑端口
    const p = await pickFreePort();
    if (!(p > 0 && p < 65536)) throw new Error(`端口异常：${p}`);
    console.log(`[capture-lane] selftest 2/6 绿：空闲端口挑选（${p}）`);
    // 3. 临时 profile 组装（真跑一次，检查 sandbar-workbench 软链指到假泳道）
    const fakeLaneWb = path.join(tmp, "fakelane", "workbench");
    await mkdir(path.join(fakeLaneWb, "lib"), { recursive: true });
    await (await import("node:fs/promises")).writeFile(path.join(fakeLaneWb, "lib", "client.js"), "x");
    const profDir = await buildTempProfile(tmp, fakeLaneWb);
    const real = realpathSync(path.join(profDir, "node_modules", "sandbar-workbench"));
    const want = realpathSync(fakeLaneWb);
    if (real !== want) throw new Error(`sandbar-workbench 软链未指向泳道：${real}（期望 ${want}）`);
    console.log("[capture-lane] selftest 3/6 绿：临时 profile 组装（workbench 软链指向泳道）");
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
    console.log("[capture-lane] selftest 4/6 绿：preset 物化三态（缺失/畸形拒跑、完整源实体落地）");
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
    console.log("[capture-lane] selftest 5/6 绿：状态注入 loadFixtures 三态（真包放行；缺目录/坏 JSON/缺标记/软链各自人话拒因）");
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
    console.log("[capture-lane] selftest 6/6 绿：routeDecision（GET 命中/查询串不影响/POST 恒放行/contentType 硬条款）");
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
