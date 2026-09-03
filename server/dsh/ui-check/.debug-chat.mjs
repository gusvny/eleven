// 诊断探针（临时，不入库）：隔离台 boot + 种子 + 点会话行 + 全量遥测
import { mkdtemp, copyFile, writeFile, symlink, readdir, rm, mkdir } from "node:fs/promises";
import { existsSync, readFileSync, statSync, readdirSync, openSync, closeSync } from "node:fs";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { chromium } from "./node_modules/playwright-core/index.mjs";

const REPO_ROOT = "/Users/user/Documents/suyou";
const LANE = path.resolve(process.argv[2] || "/Users/user/Documents/suyou/.worktrees/t260831-02");
const laneWb = path.join(LANE, "server", "dsh", "workbench");

async function pickFreePort() {
  const net = await import("node:net");
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
  });
}

const tmpHome = await mkdtemp(path.join(tmpdir(), "debug-chat-"));
const profDir = path.join(tmpHome, "profiles", "suyou");
await mkdir(profDir, { recursive: true });
const repoProfile = path.join(REPO_ROOT, "server", "dsh", "profile");
for (const f of ["cordis.yml", "cordis.patch.yml", "package.json"]) {
  const s = path.join(repoProfile, f);
  if (existsSync(s)) await copyFile(s, path.join(profDir, f));
}
const nm = path.join(profDir, "node_modules");
await mkdir(nm, { recursive: true });
const repoNm = path.join(repoProfile, "node_modules");
for (const name of readdirSync(repoNm)) {
  const dest = name === "suyou-workbench" ? path.join(LANE, "server", "dsh", "workbench")
    : (() => { try { return realpathSync(path.join(repoNm, name)); } catch { return null; } })();
  if (dest) await symlink(dest, path.join(nm, name));
}
const userDsh = path.join(process.env.HOME || "", ".dsh");
if (existsSync(path.join(userDsh, ".credentials.yaml")))
  await copyFile(path.join(userDsh, ".credentials.yaml"), path.join(tmpHome, ".credentials.yaml")).catch(() => {});
const port = await pickFreePort();
const portPatch = path.join(tmpHome, "port_patch.yml");
await writeFile(portPatch, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, "utf8");
const logPath = path.join(tmpHome, "console.log");
const logFd = openSync(logPath, "a");
const proc = spawn("/opt/homebrew/bin/dsh", ["--profile", "suyou", "--patch", portPatch,
  "--port", String(port), "--host", "127.0.0.1", "--no-open"], {
  cwd: "/Users/user/Documents/suyou",
  env: { ...process.env, DSH_HOME: tmpHome,
         DEEPSEEK_API_KEY: "sk-capture-lane-dummy" },
  detached: true, stdio: ["ignore", logFd, logFd],
});
// 等就绪
let up = false;
for (let i = 0; i < 60; i++) {
  try { const r = await fetch(`http://127.0.0.1:${port}/`); if (r.ok) { up = true; break } } catch {}
  await new Promise(r => setTimeout(r, 500));
}
console.log("console up:", up, "port:", port);
if (!up) { console.log(readFileSync(logPath, "utf8").slice(-800)); process.exit(1); }

const b = await chromium.launch({ channel: "chrome", headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const consoleMsgs = [], pageErrors = [], badReqs = [];
p.on("console", (m) => consoleMsgs.push(`[${m.type()}] ${m.text()}`.slice(0, 300)));
p.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));
p.on("requestfailed", (r) => badReqs.push(`FAIL ${r.url().slice(0, 120)} ${r.failure()?.errorText}`));
p.on("response", (r) => { if (r.status() >= 400) badReqs.push(`HTTP ${r.status()} ${r.url().slice(0, 120)}`); });

await p.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
console.log("phase(初始):", await p.evaluate(() => document.querySelector("[data-phase]")?.getAttribute("data-phase")));

// 种子：global-session/open ×2 + 账册
const base = `http://127.0.0.1:${port}`;
const pr = await fetch(`${base}/suyou-workbench/api/wf/projects`).then(r => r.json());
const project = pr?.result?.projects?.find(x => x && typeof x.key === "string")?.key;
console.log("project:", project);
const ids = [];
for (let i = 0; i < 2; i++) {
  const d = await fetch(`${base}/suyou-workbench/api/global-session/open`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ project }) }).then(r => r.json());
  console.log("open", i, "→", JSON.stringify(d).slice(0, 160));
  if (d?.ok && d?.result?.session_id) ids.push([d.result.session_id, d.result.cwd ?? ""]);
}
await p.evaluate(([key, proj, rows]) => {
  localStorage.setItem(key, JSON.stringify(rows.map(([id, cwd], i) => ({
    id, project: proj, cwd, lastOpenedAt: Date.now() - i * 1000 }))));
}, ["suyou-workbench-opened-sessions-v1", project, ids]);
await p.reload({ waitUntil: "networkidle" }).catch(() => {});
await p.waitForTimeout(2000);
const rows = p.locator("[data-wb-session-row]");
console.log("MRU 行数:", await rows.count());

// 点击 + 时序采样
await rows.first().dispatchEvent("click").catch(async () => { await rows.first().click({ force: true }) });
const badBefore = badReqs.length;
for (let t = 0; t < 16; t++) {
  const phase = await p.evaluate(() => document.querySelector("[data-phase]")?.getAttribute("data-phase"));
  const ta = await p.locator("textarea:visible").count();
  const modal = await p.locator('button:has-text("Configure later"), button:has-text("Add an API key")').count();
  console.log(`t+${(t * 1.25).toFixed(1)}s phase=${phase} textarea=${ta} modal=${modal} newErr=${(pageErrors.length + badReqs.length - badBefore)}`);
  if (phase === "active") break;
  await p.waitForTimeout(1250);
}
await p.screenshot({ path: "/tmp/debug-chat-final.png" });
console.log("--- 浏览器 console（全部）---");
for (const m of consoleMsgs.slice(-25)) console.log(" ", m);
console.log("--- page errors ---", pageErrors.slice(-5));
console.log("--- bad requests ---", badReqs.slice(-8));
await b.close();
try { process.kill(-proc.pid, "SIGKILL"); } catch {}
try { rmSync(tmpHome, { recursive: true, force: true }); } catch {}
