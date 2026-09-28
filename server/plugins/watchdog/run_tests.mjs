#!/usr/bin/env node
// watchdog 源级 UT 执行器（照 workbench run_tests 同款约定）：
// tests/*.mjs 各自可独立 node 执行（exit 0 = 过）；cwd=仓库根由本执行器保证。
import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const testsDir = join(repo, "server/plugins/watchdog/tests");
const HELPERS = new Set(["lib.mjs"]);
const files = readdirSync(testsDir).filter((f) => f.endsWith(".mjs") && !HELPERS.has(f)).sort();
let ran = 0, failed = 0;
for (const f of files) {
  const p = spawnSync("node", [join(testsDir, f)], { cwd: repo, encoding: "utf8", timeout: 120000 });
  ran += 1;
  if (p.status === 0) {
    console.log(`PASS [${f}]`);
  } else {
    failed += 1;
    console.log(`FAIL [${f}] exit=${p.status}`);
    const tail = ((p.stdout || "") + (p.stderr || "")).split("\n").filter(Boolean).slice(-8)
      .map((l) => "    " + l).join("\n");
    if (tail) console.log(tail);
  }
}
console.log(`WATCHDOG_TESTS ran=${ran} pass=${ran - failed} fail=${failed}`);
process.exit(failed === 0 ? 0 : 1);
