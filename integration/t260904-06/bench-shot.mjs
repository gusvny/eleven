#!/usr/bin/env node
/**
 * bench-shot.mjs —— t260904-06 spec 卡 UI 证据通道（泳道自备，capture.mjs 同族）。
 *
 * 为什么不是 capture-lane 一键：capture-lane 的 fixture 目录钉死主树 ui-check/fixtures
 * （bench 级开关只认 =1，目录不可指），本票需要「带 spec 的 fixture 票」才能拍进
 * spec 卡，故按 KI-036 记录的 t260904-01 先例自写 bench-shot：
 *   t260904-19 起台=docker 舞台（integration/stage_docker.py，自搭进程 boot 退役）；
 *   仍复用主树 ui-check 的已测导出件（capture.routeDecision 等），
 *   boot 临时 DSH_HOME 隔离台（临时端口，不碰 3099），playwright 层注入 fixture 票，
 *   DOM 断言 + 前后截图落 .suyou/screenshots/。
 *
 * 只读红线：只 GET + 语义锚点击（开抽屉），不提交表单、不发工单、不碰任何进程端口；
 * boot 进程四条路径（正常/报错/超时/信号）全回收（kill 进程组 + 关 fd + 删临时目录）。
 *
 * 用法：node bench-shot.mjs --lane <泳道root> --main <主树root> --out <泳道.suyou/screenshots>
 */

import { spawn } from "node:child_process";
import { closeSync, existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { copyFile, mkdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import process from "node:process";

function parseArgs(argv) {
  const a = { lane: null, main: null, out: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--lane") a.lane = argv[++i];
    else if (argv[i] === "--main") a.main = argv[++i];
    else if (argv[i] === "--out") a.out = argv[++i];
  }
  for (const k of ["lane", "main", "out"]) if (!a[k]) throw new Error(`缺 --${k}`);
  return a;
}

/** spec 原文：优先从主树样张 B 卡抽取（=真单 t260904-05 spec 转写，验收口径 2268 字），
 *  取不到退内置固定串（断言改为对 spec.length 自洽，徽标契约不依赖样张在场）。
 *  抽取用 div 配平游走（正则懒匹配会越过卡片真实闭合边界，实测多吞 275 字）。 */
function extractSpec(mainRoot) {
  const mock = path.join(mainRoot, "notes", "discussions", "260904-spec-card-mockup.html");
  try {
    const html = readFileSync(mock, "utf8");
    const anchor = html.indexOf('data-v="B"');
    if (anchor < 0) return null;
    const open = html.lastIndexOf("<div", anchor);
    const token = /<\/?div[^>]*>/g;
    token.lastIndex = open;
    let depth = 0, ttlCloseEnd = -1, end = -1, innerDepth = 0, seenInner = false;
    for (let m = token.exec(html); m; m = token.exec(html)) {
      if (m[0].startsWith("</")) {
        depth--;
        if (seenInner && innerDepth > 0) innerDepth--;
        if (seenInner && innerDepth === 0 && ttlCloseEnd < 0) { ttlCloseEnd = m.index + m[0].length; seenInner = false; }
      } else {
        if (depth === 1) { seenInner = true; innerDepth = 1; }
        depth++;
      }
      if (depth === 0) { end = m.index; break; }
    }
    if (open >= 0 && ttlCloseEnd > 0 && end > ttlCloseEnd) {
      const text = html.slice(ttlCloseEnd, end).trim();
      if (text.length > 100) return text;
    }
  } catch { /* 样张不可达 → fallback */ }
  return null;
}

const FALLBACK_SPEC = "执行规格（fallback 固定串）：" + "样张不可达时的确定性桩文本，用于锁「徽标=spec.length」契约。".repeat(40);

// ---- fixture 票（浏览器层注入，不落任何真数据）----
function buildFixtures(mainRoot) {
  const spec = extractSpec(mainRoot) ?? FALLBACK_SPEC;
  const fxDir = path.join(mainRoot, "server", "dsh", "ui-check", "fixtures");
  const list = JSON.parse(readFileSync(path.join(fxDir, "tickets-list.json"), "utf8"));
  const baseShow = JSON.parse(readFileSync(path.join(fxDir, "ticket-show-T-FIX-A.json"), "utf8"));
  const mkRow = (id, title) => ({
    id, role: "developer", status: "running", title, workflow: "dev-lane", epic: "",
    stage: "implement", stage_state: "running", handoff_count: 0, pending_count: 0,
    worktree: ".lane/fixture", workspace: { type: "worktree", path: "/tmp/suyou-fixture/bench" },
    created: 1700000000, updated: "01-01 00:00", updated_ts: 1700000000, pending: [],
  });
  const row05 = mkRow("T-SPEC-05", "【fixture 注入票】spec 卡 B 形态（2268 字规格，默认展开限高滚动）");
  const rowEmpty = mkRow("T-SPEC-EMPTY", "【fixture 注入票】无 spec 老票（空整卡不渲染对照）");
  list.tickets = [row05, rowEmpty];
  // 客户端 reloadTickets 读 data.result?.tickets（result=对象形态）；
  // 主树默认 fixture 的 result 是数组（260901-24 后客户端改形状，默认包未跟）——
  // 本 fixture 按现役客户端形状给（空列表不是有效证据）。
  list.result = { tickets: [row05, rowEmpty] };
  const mkShow = (id, title, body, withSpec) => ({
    ...baseShow, id, title, workflow_id: "dev-lane", stage: "implement", stage_state: "running",
    status: "running", role: "developer", acceptance: [], checks: {}, handoffs: [], pending: [],
    log: [], gate_runs: [], timeline: [], results: {}, signatures: {},
    body, ...(withSpec ? { spec } : {}),
  });
  return {
    spec,
    map: {
      "tickets-list": list,
      "ticket-show-T-SPEC-05": mkShow("T-SPEC-05", row05.title, "（原始需求样例）ui 上工单只显示原始需求，spec 字段没显示——单独开票加。", true),
      "ticket-show-T-SPEC-EMPTY": mkShow("T-SPEC-EMPTY", rowEmpty.title, "（原始需求样例）老票没有 spec 字段，详情不应出现 spec 卡。", false),
    },
  };
}

// ---- 隔离台 boot / 拆台（capture-lane 同构，四条路径全回收）----
async function pickFreePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, "127.0.0.1", () => { const p = srv.address().port; srv.close(() => resolve(p)); });
    srv.on("error", reject);
  });
}
async function waitReady(port, timeoutMs, logPath) {
  const url = `http://127.0.0.1:${port}/`;
  const dl = Date.now() + timeoutMs;
  while (Date.now() < dl) {
    try { const r = await fetch(url); if (r.ok) return; } catch { /* 未就绪 */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  let tail = "";
  try { tail = readFileSync(logPath, "utf8").split("\n").filter(Boolean).slice(-5).join("\n"); } catch { /* 无日志 */ }
  throw new Error(`隔离台 ${timeoutMs}ms 未就绪（${url}）\nconsole.log 尾部：\n${tail}`);
}
async function bootConsole(mainRoot, laneWb, onProc) {
  // t260904-19：docker 舞台（自搭进程 boot 退役）。repoDir 挂哪个树，/repo/server/dsh/workbench
  // 就是谁——before 变体挂主树（测主 workbench），after 变体挂泳道（测泳道 build）；
  // profile 经 buildStageProfile 容器内路径物化（sandbar-workbench→/repo/... 随 repoDir 切换）。
  const stage = await import(pathToFileURL(path.join(REPO_ROOT, "integration", "stage_docker.mjs")).href);
  const tmpHome = mkdtempSync(path.join(tmpdir(), "suyou-bench-shot-"));
  const clean = () => { if (tmpHome) { try { rmSync(tmpHome, { recursive: true, force: true }); } catch { /* 留警告 */ } } };
  try {
    const profileDir = stage.buildStageProfile({
      repoProfileDir: path.join(REPO_ROOT, "server", "dsh", "profile"),
      laneWorkbenchDir: "/repo/server/dsh/workbench",
      tmpHome,
    });
    const variant = path.resolve(laneWb).startsWith(path.resolve(mainRoot) + path.sep) ? "main" : "lane";
    const st = stage.stageUp({
      project: `bench-shot-${variant}-${process.pid}`,
      services: "dsh",
      repoDir: mainRoot,       // before/after 的被测树（REPO 挂载）
      profileDir,
      timeoutSec: Number(process.env.BENCH_SHOT_STAGE_TIMEOUT_SEC ?? 600),
    });
    onProc(null, null, null, st.project);
    return { port: st.ports.console, tmpHome };
  } catch (e) { clean(); throw e; }
}
function makeTeardown() {
  // t260904-19：回收对象=自起 docker 舞台。回收原语=spawnSync 调 stage_docker down
  // （同步：exit/信号钩子里都可靠；down 幂等，CLI 内含零残留核验）。
  let project = null, done = false;
  const down = () => {
    if (!project) return;
    const r = spawnSync(process.execPath,
      [path.join(REPO_ROOT, "integration", "stage_docker.py"), "down", "--project", project],
      { encoding: "utf8", timeout: 180000 });
    if (r.status === 0) console.log(`[bench-shot] 舞台 ${project} 已拆`);
    else console.error(`[bench-shot] 舞台 ${project} 拆台异常（down 幂等可重试）：${String(r.stderr ?? "").slice(0, 160)}`);
  };
  const teardown = () => { if (done) return; done = true; down(); };
  process.on("exit", () => { if (!done) { done = true; down(); } });
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { teardown(); process.exit(130); });
  return { teardown, inject: (_p, _fd, _cl, proj) => { project = proj ?? project; } };
}

// ---- 页面助手（capture.mjs 同款语义锚，本文件内联拷贝：原函数未导出）----
async function forceClick(locator, timeoutMs = 5000) {
  try { await locator.click({ timeout: timeoutMs }); } catch { await locator.evaluate((el) => el.click()); }
}
async function dismissAdmission(page) {
  const dlg = page.locator("[role=dialog]").first();
  if (!(await dlg.isVisible().catch(() => false))) return null;
  const later = page.getByText("Configure later").first();
  if (await later.isVisible().catch(() => false)) { await forceClick(later); } else { await page.keyboard.press("Escape"); }
  for (let i = 0; i < 16; i++) {
    if (!(await dlg.isVisible().catch(() => false))) return "准入模态已让路（Configure later / Escape）";
    await page.waitForTimeout(500);
  }
  throw new Error("准入模态让路失败（遮罩会污染后续视图与截图）");
}

// ---- 断言 ----
let pass = 0, fail = 0;
const failures = [];
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`); }
  else { fail++; failures.push(label); console.error(`  FAIL ${label}`); }
}

async function shoot(page, url, fixtures, variant, outDir) {
  const consoleErrs = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrs.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => consoleErrs.push(`pageerror: ${String(e).slice(0, 300)}`));
  try {
    await shootInner(page, url, fixtures, variant, outDir);
  } catch (e) {
    try {
      await page.screenshot({ path: path.join(outDir, `debug-${variant}.png`), fullPage: true });
      const probe = await page.evaluate(() => ({
        text: document.body.innerText.replace(/\n{2,}/g, "\n").slice(0, 600),
        icons: document.querySelectorAll(".wb-view-icon").length,
        rows: document.querySelectorAll("tr").length,
        wbRows: document.querySelectorAll("tr.wb-row").length,
        root: document.querySelector("#root, [data-wb]")?.constructor?.name ?? null,
      }));
      console.error(`[bench-shot] 诊断（debug-${variant}.png 已存）：icons=${probe.icons} rows=${probe.rows} wbRows=${probe.wbRows}\n页面文本头：\n${probe.text}\nconsole 错误：\n  ${consoleErrs.slice(0, 10).join("\n  ") || "（无）"}`);
    } catch (e2) { console.error(`[bench-shot] 诊断失败：${e2.message}`); }
    throw e;
  }
}

async function shootInner(page, url, fixtures, variant, outDir) {
  await page.route("**/api/wf/**", (route) => {
    const { routeDecision } = routeDecisionMod;
    const req = route.request();
    const d = routeDecision(req.method(), req.url(), fixtures.map);
    if (process.env.BENCH_SHOT_ROUTE_LOG) console.log(`[route] ${req.method()} ${req.url()} -> ${d.fulfill ? d.fulfill.fixture : "passthrough"}`);
    if (d.fulfill) return route.fulfill(d.fulfill);
    return route.continue();
  });
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  console.log(`[${variant}] ${await dismissAdmission(page) ?? "无准入模态"}`);
  const icon = page.locator('.wb-view-icon[title="工单列表"]').first();
  await icon.waitFor({ state: "visible", timeout: 10000 });
  await forceClick(icon);
  await page.waitForSelector("tr.wb-row", { timeout: 10000 });

  // 视图①：带 spec 票（T-SPEC-05）。after=本票改动后应有卡并全量断言；
  // before=主树旧 bundle 基线，spec 卡必须不存在（改动前 UI 证据）。
  const row = page.locator("tr.wb-row", { hasText: "T-SPEC-05" }).first();
  await forceClick(row);
  await page.waitForSelector(".wb-drawer-head", { timeout: 10000 });
  await page.waitForTimeout(300);
  if (variant === "after") {
    const card = page.locator(".wb-d2-spec").first();
    await card.waitFor({ state: "visible", timeout: 8000 });
    ok(await page.locator(".wb-d2-spec").count() === 1, `[${variant}] 有 spec 票恰好渲染 1 张 spec 卡`);
    ok((await page.locator(".wb-d2-spec .ttl").innerText()).includes("执行规格（spec）"), `[${variant}] ttl=「执行规格（spec）」`);
    ok((await page.locator(".wb-d2-spec .cnt").innerText()).trim() === `${fixtures.spec.length} 字`,
      `[${variant}] 字数徽标=「${fixtures.spec.length} 字」（=spec.length，样张真文=2268 字）`);
    const cs = await card.evaluate((el) => {
      const s = getComputedStyle(el);
      return { maxH: s.maxHeight, ovf: s.overflowY, blw: s.borderLeftWidth, blc: s.borderLeftColor,
        scrollH: el.scrollHeight, clientH: el.clientHeight,
        posOk: el.previousElementSibling?.classList.contains("wb-d2-body") };
    });
    ok(cs.maxH === "260px", `[${variant}] computed max-height:260px（实测 ${cs.maxH}）`);
    ok(cs.ovf === "auto", `[${variant}] computed overflow-y:auto（实测 ${cs.ovf}）`);
    ok(cs.blw === "4px" && cs.blc === "rgb(9, 105, 218)", `[${variant}] 蓝左边条 4px #0969da（实测 ${cs.blw}/${cs.blc}）`);
    ok(cs.scrollH > cs.clientH, `[${variant}] 限高滚动成立（scrollH ${cs.scrollH} > clientH ${cs.clientH}）`);
    ok(cs.posOk, `[${variant}] spec 卡紧贴正文卡正下方（prev sibling=wb-d2-body，钉顶区位置契约）`);
    await page.screenshot({ path: path.join(outDir, `${variant}-spec-full.png`), fullPage: true });
    await card.screenshot({ path: path.join(outDir, `${variant}-spec-closeup.png`) });
  } else {
    ok(await page.locator(".wb-d2-spec").count() === 0, `[${variant}] 基线：主树旧 bundle 无 spec 卡（改动前 UI）`);
    await page.screenshot({ path: path.join(outDir, `${variant}-spec-full.png`), fullPage: true });
  }

  // 视图②：无 spec 老票（空整卡不渲染对照；before 基线天然 0 卡，仅 after 出图）
  if (variant === "after") {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.locator('.wb-view-icon[title="工单列表"]').first().waitFor({ state: "visible", timeout: 10000 });
    await forceClick(page.locator('.wb-view-icon[title="工单列表"]').first());
    await page.waitForSelector("tr.wb-row", { timeout: 10000 });
    await forceClick(page.locator("tr.wb-row", { hasText: "T-SPEC-EMPTY" }).first());
    await page.waitForSelector(".wb-drawer-head", { timeout: 10000 });
    await page.waitForTimeout(300);
    ok(await page.locator(".wb-d2-spec").count() === 0, `[${variant}] 无 spec 老票整卡不渲染（老票兼容）`);
    await page.screenshot({ path: path.join(outDir, `${variant}-empty-full.png`), fullPage: true });
  }
}

let routeDecisionMod = null;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const laneWb = existsSync(path.join(args.lane, "server", "dsh", "workbench"))
    ? path.join(args.lane, "server", "dsh", "workbench") : path.join(args.lane, "workbench");
  const mainWb = path.join(args.main, "server", "dsh", "workbench");
  const outDir = args.out;
  await mkdir(outDir, { recursive: true });
  const fixtures = buildFixtures(args.main);
  console.log(`[bench-shot] spec 原文长度=${fixtures.spec.length}` +
    `${existsSync(path.join(args.main, "notes", "discussions", "260904-spec-card-mockup.html")) ? "（样张 B 卡抽取）" : "（fallback 桩）"}`);
  routeDecisionMod = await import(pathToFileURL(path.join(args.main, "server", "dsh", "ui-check", "capture.mjs")).href);
  const pwPath = process.env.SUYOU_PLAYWRIGHT_MODULE
    ?? path.join(args.main, "server", "dsh", "ui-check", "node_modules", "playwright-core");
  // CJS 包经 ESM import 时导出在 default 下（capture.mjs loadPlaywright 同款口径）
  const pwMod = await import(pathToFileURL(path.join(pwPath, "index.js")).href);
  const { chromium } = pwMod.default ?? pwMod;
  let browser;
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true }).catch(() => chromium.launch({ headless: true }));
    for (const [variant, wbDir] of [["before", mainWb], ["after", laneWb]]) {
      const { teardown, inject } = makeTeardown();
      try {
        const { port } = await bootConsole(args.main, wbDir, inject);
        console.log(`[${variant}] 隔离台就绪 127.0.0.1:${port}（workbench=${wbDir}）`);
        const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
        const page = await ctx.newPage();
        await shoot(page, `http://127.0.0.1:${port}/`, fixtures, variant, outDir);
        await ctx.close();
      } finally { teardown(); }
    }
  } finally {
    await browser?.close().catch(() => {});
  }
  writeFileSync(path.join(outDir, "bench-shot-report.json"), JSON.stringify({
    ticket: "t260904-06", pass, fail, failures,
    spec_len: fixtures.spec.length, at: new Date().toISOString(),
  }, null, 2));
  console.log(`\nbench-shot: pass=${pass} fail=${fail}`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((e) => { console.error(`[bench-shot] ${e.message}`); process.exit(1); });
