// Integration test for ticket t260901-03 — capture seed gate red lines & fault surface.
//
// Intent (black-box, user perspective):
//   The capture evidence tool may create sessions and SEND A SEED MESSAGE only inside an
//   isolated lane console and only with an explicit flag; against any other console it
//   must refuse loudly without performing a single write. These are the red lines that
//   keep the evidence chain honest. All cases run against a hermetic MOCK console
//   (localhost ephemeral port, no Docker, no real console) and assert both the process
//   outcome and the mock's request log (writes that never happened must be provable):
//     R1 no flag -> loud nonzero exit whose error names the missing gate, and the mock
//        records ZERO POST /global-session/open (no write was attempted anywhere);
//     R2 flag + seed API returns empty cwd -> fast explicit failure naming the cwd
//        check (blank self-heal can never trigger), NOT a 25s hero-timeout hang;
//     R3 flag + seed API errors -> loud failure naming 台内造数失败 with the API error;
//     R4 console unreachable -> loud nonzero exit within budget (no silent hang).
//
// Environment: none required from the caller. playwright-core resolves from the main
// checkout via `git rev-parse --git-common-dir` (same precedent as ticket-validate).
// ENV_FAIL (exit 2) when playwright/browser unavailable (三态契约 §7.3：缺环境绝不 exit 0).
// Everything else must PASS on
// a correct implementation; the R2 cwd assertion lands with this ticket's fix, so this
// suite is expected to FAIL on pre-fix code (that is the acceptance bar).

import { spawn } from "node:child_process";
import { execFileSync } from "node:child_process";
import http from "node:http";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const LANE_ROOT = process.cwd();
const CAPTURE = path.join(LANE_ROOT, "server", "dsh", "ui-check", "capture.mjs");
const CASE_TIMEOUT_MS = 120000;

const results = [];
function record(name, status, detail = "") {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ""}`);
}

// ---------- prechecks ----------

const nodeMajor = Number(process.versions.node.split(".")[0]);
if (nodeMajor < 22) {
  console.log(`ENV_FAIL: node ${process.versions.node} < 22（本套件要求 node >= 22）`);
  console.log("SUMMARY pass=0 fail=0 env_fail=1 na=0");
  process.exit(2);
}

function resolveMainUiCheck() {
  const env = process.env.SUYOU_CAPTURE_MAIN_UI_CHECK;
  if (env && existsSync(path.join(env, "node_modules", "playwright-core", "index.mjs"))) return env;
  try {
    const common = execFileSync("git", ["rev-parse", "--git-common-dir"], { cwd: LANE_ROOT, encoding: "utf8" }).trim();
    const cand = path.resolve(LANE_ROOT, common, "..", "server", "dsh", "ui-check");
    if (existsSync(path.join(cand, "node_modules", "playwright-core", "index.mjs"))) return cand;
  } catch { /* not a git checkout — fall through */ }
  const local = path.join(LANE_ROOT, "server", "dsh", "ui-check");
  if (existsSync(path.join(local, "node_modules", "playwright-core", "index.mjs"))) return local;
  return null;
}

async function loadPlaywright(mainUiCheck) {
  const candidates = [];
  if (process.env.SUYOU_PLAYWRIGHT_PATH) candidates.push(process.env.SUYOU_PLAYWRIGHT_PATH);
  if (mainUiCheck) candidates.push(path.join(mainUiCheck, "node_modules", "playwright-core", "index.mjs"));
  candidates.push("playwright-core");
  for (const c of candidates) {
    try { return await import(c); } catch { /* try next */ }
  }
  return null;
}

const mainUiCheck = resolveMainUiCheck();
const playwright = await loadPlaywright(mainUiCheck);

async function browserAvailable() {
  if (!playwright) return false;
  let browser = null;
  try { browser = await playwright.chromium.launch({ channel: "chrome", headless: true }); }
  catch { try { browser = await playwright.chromium.launch({ headless: true }); } catch { return false; } }
  await browser.close().catch(() => {});
  return true;
}

// ---------- mock console ----------

/** 假控制台：只应答 capture 造数会碰的三个端点，其余 404。记录每个请求。 */
function startMockConsole(mode) {
  const requests = []; // { method, url }
  let openCalls = 0;
  const server = http.createServer((req, res) => {
    requests.push({ method: req.method, url: req.url });
    const json = (code, body) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.url === "/sandbar-workbench/api/wf/projects") {
      json(200, { ok: true, result: { projects: [{ key: "demo", name: "demo", dirs: ["/tmp/mock-demo"], primary: "/tmp/mock-demo" }] } });
    } else if (req.url === "/sandbar-workbench/api/global-session/open") {
      openCalls += 1;
      if (mode === "error") json(500, { ok: false, error: "mock: 造数端点故障" });
      else if (mode === "emptycwd") json(200, { ok: true, result: { session_id: `chat-mock-${openCalls}`, created: true, cwd: "" } });
      else json(200, { ok: true, result: { session_id: `chat-mock-${openCalls}`, created: true, cwd: "/tmp/mock-demo" } });
    } else if (req.url === "/" || req.url.startsWith("/?")) {
      res.writeHead(200, { "content-type": "text/html" });
      res.end("<!doctype html><html><head><title>mock console</title></head><body></body></html>");
    } else {
      res.writeHead(404); res.end("nope");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, requests, openCalls: () => openCalls }));
  });
}

// ---------- capture runner ----------

async function runCapture({ url, allowSeed, outDir }) {
  const args = [CAPTURE, "--url", url, "--out", outDir];
  if (allowSeed) args.push("--allow-seed");
  return await new Promise((resolve) => {
    const child = spawn(process.execPath, args, {
      cwd: LANE_ROOT,
      detached: true,
      env: {
        ...process.env,
        // 门旗只经 argv 传；env 旗在 R1 必须缺席，显式删除防环境污染
        SUYOU_UI_CAPTURE_ALLOW_SEED: allowSeed ? "1" : "",
        SUYOU_PLAYWRIGHT_MODULE: mainUiCheck ? path.join(mainUiCheck, "node_modules", "playwright-core") : process.env.SUYOU_PLAYWRIGHT_MODULE || "",
      },
    });
    let stdout = "", stderr = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stderr += d; });
    let timedOut = false;
    const t0 = Date.now();
    const timer = setTimeout(() => {
      timedOut = true;
      try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
    }, CASE_TIMEOUT_MS);
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: timedOut ? "timeout" : code, stdout, stderr, both: `${stdout}\n${stderr}`, elapsedMs: Date.now() - t0, timedOut });
    });
  });
}

async function closedPort() {
  const net = await import("node:net");
  return await new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

// ---------- scenarios ----------

if (!(await browserAvailable())) {
  for (const name of ["R1 no-flag-no-write-redline", "R2 empty-cwd-fast-fail", "R3 seed-api-error-loud",
    "R4 console-unreachable-loud"]) {
    record(name, "env_fail", "playwright-core 不可解析或无可用浏览器");
  }
} else {
  const work = await mkdtemp(path.join(tmpdir(), "capture-redline-"));

  // R1 只读红线：不带门旗 → 明确报错、且全程零写（mock 请求日志为证）
  {
    const mock = await startMockConsole("ok");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: false, outDir: path.join(work, "r1") });
      const writes = mock.requests.filter((q) => q.method === "POST" && q.url.includes("global-session/open")).length;
      const namedGate = /未带 --allow-seed/.test(r.both);
      const ok = !r.timedOut && r.code !== 0 && namedGate && writes === 0;
      record("R1 no-flag-no-write-redline", ok ? "pass" : "fail",
        `exit=${r.code}；报错点名缺门旗=${namedGate}；造数写请求=${writes}（必须为 0）`);
    } finally { mock.server.close(); }
  }

  // R2 畸形输入·空 cwd：门旗在位、造数端点回空 cwd → 快速显式失败（非 25s 挂）
  {
    const mock = await startMockConsole("emptycwd");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: true, outDir: path.join(work, "r2") });
      const namesCwd = /cwd/.test(r.both);
      // 快速失败预算 90s（t260907-05 arbitrate gen4 修正：原 60s 为空载机估计值，
      // 共享机器资源竞争下逻辑全真的显式失败实测 77.8s 被误判——预算锚定「显著小于
      // 120s 挂死兜底、保留非挂死区分度」，四项逻辑断言（exit≠0/点名 cwd/造数请求/
      // 未超时）原样不动）。
      const fast = r.elapsedMs < 90000;
      const ok = !r.timedOut && r.code !== 0 && namesCwd && fast && mock.openCalls() >= 1;
      record("R2 empty-cwd-fast-fail", ok ? "pass" : "fail",
        `exit=${r.code}；报错含 cwd 检查=${namesCwd}；耗时=${(r.elapsedMs / 1000).toFixed(1)}s（须 <90s 快速失败、非 120s 挂死形态）；造数请求=${mock.openCalls()}`);
    } finally { mock.server.close(); }
  }

  // R3 异常注入·造数端点 500：报错须点名「台内造数失败」并带回 API 错误
  {
    const mock = await startMockConsole("error");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: true, outDir: path.join(work, "r3") });
      const named = /台内造数失败/.test(r.both);
      const ok = !r.timedOut && r.code !== 0 && named;
      record("R3 seed-api-error-loud", ok ? "pass" : "fail",
        `exit=${r.code}；报错点名台内造数失败=${named}`);
    } finally { mock.server.close(); }
  }

  // R4 异常注入·控制台不可达：预算内 loud 非零退出，不静默挂死
  {
    const port = await closedPort();
    const r = await runCapture({ url: `http://127.0.0.1:${port}/`, allowSeed: false, outDir: path.join(work, "r4") });
    const ok = !r.timedOut && r.code !== 0 && r.both.trim().length > 0;
    record("R4 console-unreachable-loud", ok ? "pass" : "fail",
      `exit=${r.code}；耗时=${(r.elapsedMs / 1000).toFixed(1)}s（预算 ${CASE_TIMEOUT_MS / 1000}s）；stderr 非空=${r.both.trim().length > 0}`);
  }

  await rm(work, { recursive: true, force: true }).catch(() => {});
}

const pass = results.filter((r) => r.status === "pass").length;
const fail = results.filter((r) => r.status === "fail").length;
const envFail = results.filter((r) => r.status === "env_fail").length;
const na = results.filter((r) => r.status === "na").length;
console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`);
const allNa = na > 0 && pass + fail + envFail === 0;
process.exit(fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0);
