// capture-lane-preset.mjs —— 隔离台 preset 物化基线（t260901-02）。
//
// 断言 server/ui-check/capture-lane.mjs 的 presetMaterializeRejectReason /
// materializePresets 三态：缺失源拒跑、畸形源拒跑（空目录/缺关键文件）、完整源
// 实体复制落地（非软链）。全用临时桩目录 + env 覆盖路径（main() 侧
// SANDBAR_CAPTURE_PRESET_SOURCE 解耦性由此函数直测覆盖），不 boot 控制台、不碰
// 网络、不碰 3099。跑法：node integration/baselines/capture-lane-preset.mjs

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
  // ① 缺失源 → 人话拒因（指路重建，不自造假 preset）
  const missing = path.join(tmp, "no-such");
  const r1 = presetMaterializeRejectReason(missing);
  assert(r1 && /缺失/.test(r1), `缺失源应拒跑，得到：${r1}`);
  assert(/cordis\.patch\.yml/.test(r1), "拒因应指路 cordis.patch.yml 注释");

  // ② 畸形源：空目录 / 缺 preset.yml / 缺 agent.cordis.yml → 拒跑
  const stub = path.join(tmp, "stub");
  await mkdir(stub, { recursive: true });
  assert(/畸形/.test(presetMaterializeRejectReason(stub) || ""), "空目录应拒跑");
  await writeFile(path.join(stub, "preset.yml"), "name: t\n");
  assert(/畸形/.test(presetMaterializeRejectReason(stub) || ""), "缺 agent.cordis.yml 应拒跑");
  await writeFile(path.join(stub, "agent.cordis.yml"), "- id: x\n");

  // ③ 完整源 → 实体复制落地，非软链（roster 只扫实体）
  const home = path.join(tmp, "fake-dsh-home");
  const dst = await materializePresets(home, stub);
  assert(dst === path.join(home, ".agent-presets", "sandbar-integration"),  // naming-compat
    `物化落点异常：${dst}`);
  for (const f of ["preset.yml", "agent.cordis.yml"]) {
    const p = path.join(dst, f);
    assert(existsSync(p), `物化后缺 ${f}`);
    assert(!statSync(p).isSymbolicLink(), `物化后 ${f} 应为实体文件，不是软链`);
  }

  // ④ 软链源同样落地为实体复制（临时家外软链不被 roster 扫，物化必须解链）
  const linkDir = path.join(tmp, "link-src");
  await symlink(stub, linkDir);
  const dst2 = await materializePresets(path.join(tmp, "home2"), linkDir);
  const st = await stat(path.join(dst2, "preset.yml"));
  assert(st.isFile(), "软链源物化后应为实体文件");

  console.log("[capture-lane-preset] 基线全绿：缺失/畸形拒跑、完整源实体落地、软链源解链复制");
} finally {
  await rm(tmp, { recursive: true, force: true }).catch(() => {});
}
