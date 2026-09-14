// Shared prereq helper for capture baselines (t260901-10 arbitrate gen2).
//
// Why: capture-lane.mjs refuses to shoot a stale workbench bundle
// (`laneBuildRejectReason`, server/ui-check/capture-lane.mjs) — anti-fraud:
// "a screenshot of a stale build is faked evidence; better no evidence at
// all". Its own header documents the remedy for the known safe-side false
// positive: "an mtime false alarm (a checkout refreshes mtimes) is a
// safe-side failure: rebuild by hand and re-run" — i.e. rebuild the bundle,
// then re-run.
//
// The gap: a fresh `git worktree` checkout writes files in index order, which
// inverts mtimes between lib/client.js and src/* by milliseconds. Every new
// lane therefore starts "stale" and needs a manual rebuild before any capture
// baseline can run — an environment prerequisite the tests did not ensure
// themselves (tests-fault class, hit by t260901-10 arbitrate 3 rounds in a row).
//
// What this helper does: automate exactly the documented remedy — rebuild the
// bundle from current sources before invoking capture-lane. Two guardrails
// keep this from weakening the anti-fraud semantics:
//   1. Byte-identity: server/plugins/workbench/lib/* are git-tracked. If the
//      rebuild produces different bytes, that is REAL content drift (not an
//      mtime artifact); we restore the tracked files and fail loud, because
//      landing a rebuilt bundle belongs to the ticket that changed the sources.
//   2. No fallback: if tsdown is unresolvable or the build fails, fail loud.
// Screenshots taken after a byte-identical rebuild reflect current sources,
// which is precisely what the stale-build guard exists to guarantee.

import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const WB_REL = path.join("server", "plugins", "workbench");
const SRC_SUBDIRS = ["src/client", "src/host", "src/shared"];
const LIB_REL = path.join(WB_REL, "lib");

function newestIn(dir) {
  let m = 0, p = "";
  const walk = (d) => {
    let entries;
    try { entries = readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const fp = path.join(d, e.name);
      if (e.isDirectory()) walk(fp);
      else {
        const t = statSync(fp).mtimeMs;
        if (t > m) { m = t; p = fp; }
      }
    }
  };
  walk(dir);
  return [m, p];
}

/** Same staleness predicate as capture-lane's guard. null = fresh enough. */
export function laneBuildStaleReason(laneRoot) {
  const wb = path.join(laneRoot, WB_REL);
  const lib = path.join(wb, "lib", "client.js");
  if (!existsSync(lib)) return `build 缺失：${lib}（守卫拒跑前提）`;
  const buildM = statSync(lib).mtimeMs;
  let newest = 0, newestPath = "";
  for (const sub of SRC_SUBDIRS) {
    const [m, p] = newestIn(path.join(wb, sub));
    if (m > newest) { newest = m; newestPath = p; }
  }
  if (newest > buildM) {
    return `build 陈旧：lib/client.js（${new Date(buildM).toISOString()}）早于 ` +
      `${path.relative(laneRoot, newestPath)}（${new Date(newest).toISOString()}）`;
  }
  return null;
}

function mainCheckoutRoot(laneRoot) {
  const r = spawnSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
    { cwd: laneRoot, encoding: "utf8" });
  if (r.status !== 0) return null;
  const gitDir = (r.stdout || "").trim(); // <main>/.git (the worktree gitfile points here)
  return gitDir ? path.dirname(gitDir) : null;
}

/**
 * 构建工具链解析（t260913-01 仲裁修正）：**被测树优先**，主检出回落。
 *
 * 为什么改：重建必须在被测树里执行——工具链随泳道自举
 * （`<lane>/server/plugins/workbench/node_modules/.bin/tsdown`），而主检出常常根本
 * 没有 node_modules（本机实证：main 无该目录、lane 有）。原实现只认主检出的
 * tsdown，于是「新泳道检出 mtime 倒置」这一**已知可自愈**的前提被判成
 * 「无法自动重建」→ 外层把 prepare 型原因记成 FAIL（三态协议违约，实测两条
 * capture 基线整条红）。两处都没有才 fail loud——不静默放过旧 bundle。
 */
export function resolveTsdown(laneRoot) {
  const cands = [path.join(laneRoot, WB_REL, "node_modules", ".bin", "tsdown")];
  const mainRoot = mainCheckoutRoot(laneRoot);
  if (mainRoot) cands.push(path.join(mainRoot, WB_REL, "node_modules", ".bin", "tsdown"));
  for (const cand of cands) {
    if (existsSync(cand)) return cand;
  }
  return null;
}

/**
 * Ensure the lane workbench bundle is not stale-per-mtime. Returns null when
 * fresh (or healed by a byte-identical rebuild); returns a human reason string
 * when the precondition cannot be satisfied (caller must FAIL loud).
 */
export function ensureLaneBuild(laneRoot) {
  const stale = laneBuildStaleReason(laneRoot);
  if (!stale) return null;

  const tsdown = resolveTsdown(laneRoot);
  if (!tsdown) {
    return `${stale}；且无法自动重建（被测树与主检出均无 ` +
      `${WB_REL}/node_modules/.bin/tsdown）。按守卫指路人工重建后重跑。`;
  }

  const wb = path.join(laneRoot, WB_REL);
  const r = spawnSync(tsdown, ["-c", "tsdown.config.ts"], {
    cwd: wb,
    encoding: "utf8",
    env: { ...process.env, PATH: `${path.dirname(tsdown)}:${process.env.PATH}` },
  });
  if (r.status !== 0) {
    return `${stale}；自动重建失败（tsdown exit=${r.status}）：` +
      `${((r.stderr || "") + (r.stdout || "")).trim().slice(-240)}`;
  }

  // Guardrail 1: byte-identity of the tracked build outputs.
  const dirty = spawnSync("git", ["status", "--porcelain", "--", LIB_REL],
    { cwd: laneRoot, encoding: "utf8" });
  if ((dirty.stdout || "").trim() !== "") {
    spawnSync("git", ["checkout", "--", LIB_REL], { cwd: laneRoot });
    return `${stale}；自动重建产出与 git 不一致字节（真实内容漂移，非 mtime 误报），` +
      `已恢复原状。bundle 重建落盘是 src 归属工单的活，不能由测试代落。`;
  }

  const still = laneBuildStaleReason(laneRoot);
  return still ? `${stale}；自动重建后仍判陈旧：${still}` : null;
}
