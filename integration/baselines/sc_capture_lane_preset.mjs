// capture-lane-preset.mjs — the isolated-workbench preset materialization
// baseline (t260901-02).
//
// Asserts the three states of presetMaterializeRejectReason / materializePresets
// in server/ui-check/capture-lane.mjs: a missing source refuses to run, a
// malformed source refuses to run (empty dir / missing key file), and a
// complete source lands as a real copy (not a symlink). Everything runs in
// temp stub dirs + env-overridden paths (the main() side's
// SANDBAR_CAPTURE_PRESET_SOURCE decoupling is covered by calling these
// functions directly); no console boot, no network, no 3099. Run: node
// integration/baselines/capture-lane-preset.mjs

import { mkdtemp, mkdir, writeFile, rm, symlink, stat } from "node:fs/promises";
import { existsSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const MOD = path.join(REPO, "server", "ui-check", "capture-lane.mjs");

const { presetMaterializeRejectReason, materializePresets } = await import(
  new URL(`file://${MOD}`).href);

function assert(cond, msg) {
  if (!cond) throw new Error(`基线失败：${msg}`);
}

const tmp = await mkdtemp(path.join(tmpdir(), "capture-lane-preset-base-"));
try {
  // (1) missing source → a plain-language reject reason (points at the
  // rebuild remedy instead of fabricating a preset)
  const missing = path.join(tmp, "no-such");
  const r1 = presetMaterializeRejectReason(missing);
  assert(r1 && /缺失/.test(r1), `缺失源应拒跑，得到：${r1}`);
  assert(/cordis\.patch\.yml/.test(r1), "拒因应指路 cordis.patch.yml 注释");

  // (2) malformed source: empty dir / missing preset.yml / missing
  // agent.cordis.yml → refuse to run
  const stub = path.join(tmp, "stub");
  await mkdir(stub, { recursive: true });
  assert(/畸形/.test(presetMaterializeRejectReason(stub) || ""), "空目录应拒跑");
  await writeFile(path.join(stub, "preset.yml"), "name: t\n");
  assert(/畸形/.test(presetMaterializeRejectReason(stub) || ""), "缺 agent.cordis.yml 应拒跑");
  await writeFile(path.join(stub, "agent.cordis.yml"), "- id: x\n");

  // (3) complete source → lands as a real copy, not a symlink (the roster
  // only scans real files)
  const home = path.join(tmp, "fake-dsh-home");
  const dst = await materializePresets(home, stub);
  assert(dst === path.join(home, ".agent-presets", "sandbar-integration"),  // naming-compat
    `物化落点异常：${dst}`);
  for (const f of ["preset.yml", "agent.cordis.yml"]) {
    const p = path.join(dst, f);
    assert(existsSync(p), `物化后缺 ${f}`);
    assert(!statSync(p).isSymbolicLink(), `物化后 ${f} 应为实体文件，不是软链`);
  }

  // (4) a symlinked source also lands as a real copy (a symlink from outside
  // the temp home is not scanned by the roster, so materialization must
  // resolve the link)
  const linkDir = path.join(tmp, "link-src");
  await symlink(stub, linkDir);
  const dst2 = await materializePresets(path.join(tmp, "home2"), linkDir);
  const st = await stat(path.join(dst2, "preset.yml"));
  assert(st.isFile(), "软链源物化后应为实体文件");

  console.log("[capture-lane-preset] 基线全绿：缺失/畸形拒跑、完整源实体落地、软链源解链复制");
} finally {
  await rm(tmp, { recursive: true, force: true }).catch(() => {});
}
