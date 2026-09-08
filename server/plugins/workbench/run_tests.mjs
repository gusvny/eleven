#!/usr/bin/env node
// workbench 源级 UT 执行器（JS UT 层的家；manifest 退役收编，t260902 宿主令直改）。
// 约定：tests/*.mjs 各自可独立 node 执行（exit 0 = 过）；cwd=仓库根由本执行器保证。
import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const testsDir = join(repo, "server/plugins/workbench/tests");
// 辅助脚本（被测试带参调用，非独立入口）不裸跑
const HELPERS = new Set(["golden.mjs", "reconcile-tokens.mjs"]);
const files = readdirSync(testsDir).filter((f) => f.endsWith(".mjs") && !HELPERS.has(f)).sort();
let ran = 0, failed = 0;
for (const f of files) {
  const p = spawnSync("node", [join(testsDir, f)], { cwd: repo, encoding: "utf8", timeout: 600000 });
  ran += 1;
  if (p.status === 0) {
    console.log(`PASS [${f}]`);
  } else {
    failed += 1;
    console.log(`FAIL [${f}] exit=${p.status}`);
    const tail = ((p.stdout || "") + (p.stderr || "")).split("\n").filter(Boolean).slice(-6)
      .map((l) => "    " + l).join("\n");
    if (tail) console.log(tail);
  }
}
console.log(`WORKBENCH_TESTS ran=${ran} pass=${ran - failed} fail=${failed}`);
process.exit(failed === 0 ? 0 : 1);
