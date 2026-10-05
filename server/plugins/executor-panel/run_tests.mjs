#!/usr/bin/env node
// executor-panel 源级 UT 执行器（watchdog/workbench run_tests 同款约定）：
// tests/*.mjs 各自可独立 node 执行（exit 0 = 过）；cwd=仓库根由本执行器保证。
//
// t261004-41：--pure 纯 node 模式——只跑不碰真 chromium 的文件（browser-*.test.mjs
// 是 L3 场景层专属，整套真跑 ~110s；纯 node 子集秒级），供 code 道 checks 消费。
// fail-closed：进入 --pure 后任何入选文件若 import 浏览器依赖（playwright /
// chromium / puppeteer），直接红——新浏览器测试不允许静默溜进快道。
import { readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const testsDir = join(repo, "server/plugins/executor-panel/tests");
const HELPERS = new Set(["lib.mjs"]);
// 浏览器族（真 chromium 驱动）：只随 L3 场景跑，永不进 --pure 快道。
const BROWSER_RE = /^browser-.*\.test\.mjs$/;
const BROWSER_DEP_RE = /playwright|chromium|puppeteer/;

const pure = process.argv.includes("--pure");
const all = readdirSync(testsDir).filter((f) => f.endsWith(".mjs") && !HELPERS.has(f)).sort();
const files = pure ? all.filter((f) => !BROWSER_RE.test(f)) : all;

if (pure) {
  // fail-closed 守卫：纯 node 子集里出现浏览器依赖 = 配置错误，不是跳过。
  const sneaky = files.filter((f) => BROWSER_DEP_RE.test(readFileSync(join(testsDir, f), "utf8")));
  if (sneaky.length > 0) {
    console.log(`EXECUTOR_PANEL_TESTS pure-mode violation: browser dependency in non-browser test file(s): ${sneaky.join(", ")}`);
    process.exit(1);
  }
}

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
console.log(`EXECUTOR_PANEL_TESTS mode=${pure ? "pure" : "full"} ran=${ran} pass=${ran - failed} fail=${failed}`);
process.exit(failed === 0 ? 0 : 1);
