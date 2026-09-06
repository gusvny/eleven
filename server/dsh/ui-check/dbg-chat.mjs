// 一次性调试（t260901-02 implement）：隔离台 boot → 造数 → 点会话行 → dump 状态。
// 落 /tmp，不入仓库交付面。用法：node dbg-chat.mjs
// t260904-19 注：本件是生产调试件（非场景资产），不经 docker 测试台——自搭 boot
// 面随票退役后仍保留原样供人工调试；勿在闸内/场景内引用（闸内一律走 docker 台）。
import { spawn } from "node:child_process";
import { closeSync, copyFileSync, existsSync, openSync, mkdirSync } from "node:fs";
import {
  copyFile as copyFileP, mkdir, mkdtemp, readdir, symlink, rm,
} from "node:fs/promises";
import { realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { perkeyIsHit, resolveCredentialsSource } from "./creds-source.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const lane = process.argv[2] || REPO_ROOT;
const laneWb = path.join(lane, "server", "dsh", "workbench");

const { buildTempProfile, materializePresets, presetMaterializeRejectReason } =
  await import(new URL(`file://${path.join(HERE, "capture-lane.mjs")}`).href);

const net = await import("node:net");
const port = await new Promise((res, rej) => {
  const s = net.createServer(); s.once("error", rej);
  s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
});
const tmpHome = await mkdtemp(path.join(tmpdir(), "dbg-chat-"));
// 凭据源（sandbar M1-2）：per-key 优先、legacy 回落，与 capture-lane 同口径（creds-source.mjs）。
const cred = resolveCredentialsSource("suyou");
if (cred && !perkeyIsHit("suyou", cred)) {
  console.error(`[dbg-chat] 提示：项目凭据未迁 ~/.sandbar/projects/suyou/credentials.yaml，仍用 legacy ${cred}（契约①b 弃用窗口）`);
}
if (cred) await copyFileP(cred, path.join(tmpHome, ".credentials.yaml")).catch(() => {});
await buildTempProfile(tmpHome, laneWb);
const psrc = process.env.SUYOU_CAPTURE_PRESET_SOURCE
  || path.join(process.env.HOME || "", ".dsh", ".agent-presets", "suyou-integration");
if (presetMaterializeRejectReason(psrc)) throw new Error("preset 源缺失");
await materializePresets(tmpHome, psrc);
const logFd = openSync(path.join(tmpHome, "console.log"), "a");
const portPatch = path.join(tmpHome, "port_patch.yml");
await (await import("node:fs/promises")).writeFile(portPatch,
  `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, "utf8");
const proc = spawn("dsh", ["--profile", "suyou", "--patch", portPatch,
  "--port", String(port), "--host", "127.0.0.1", "--no-open"], {
  cwd: REPO_ROOT, env: { ...process.env, DSH_HOME: tmpHome }, detached: true,
  stdio: ["ignore", logFd, logFd],
});
const teardown = () => { try { process.kill(-proc.pid, "SIGKILL"); } catch {} rmSyncHome(); };
const rmSyncHome = () => { try { require("node:fs").rmSync(tmpHome, { recursive: true, force: true }); } catch {} };
process.on("exit", () => { try { process.kill(-proc.pid, "SIGKILL"); } catch {} });
{
  const deadline = Date.now() + 60000;
  for (;;) {
    if (Date.now() > deadline) { console.error("boot 超时"); teardown(); process.exit(1); }
    try { const r = await fetch(`http://127.0.0.1:${port}/`); if (r.ok) break; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
}
console.log("boot ok", port);
const { chromium } = await import(path.join(HERE, "node_modules", "playwright-core", "index.mjs"));
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage();
const logs = [];
page.on("console", (m) => logs.push(`[${m.type()}] ${m.text()}`.slice(0, 400)));
page.on("pageerror", (e) => logs.push(`[pageerror] ${String(e).slice(0, 400)}`));
page.on("requestfailed", (r) => logs.push(`[reqfail] ${r.url()} ${r.failure()?.errorText}`));
await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle", timeout: 30000 });
try { const b = page.locator("button", { hasText: /continue|继续/i }).first();
  await b.waitFor({ state: "visible", timeout: 4000 }); await b.click(); } catch {}
// 造数
const pr = await (await fetch(`http://127.0.0.1:${port}/suyou-workbench/api/wf/projects`)).json();
const project = pr?.result?.projects?.[0]?.key;
const d = await (await fetch(`http://127.0.0.1:${port}/suyou-workbench/api/global-session/open`, {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ project }),
})).json();
console.log("open =>", JSON.stringify(d).slice(0, 400));
const sid = d.result.session_id, cwd = d.result.cwd;
await page.evaluate(([k, p2, id, c2]) => {
  localStorage.setItem(k, JSON.stringify([{ id, project: p2, cwd: c2, lastOpenedAt: Date.now() }]));
}, ["suyou-workbench-opened-sessions-v1", project, sid, cwd]);
await page.reload({ waitUntil: "networkidle", timeout: 30000 }).catch(() => {});
try { const b = page.locator("button", { hasText: /continue|继续/i }).first();
  await b.waitFor({ state: "visible", timeout: 3000 }); await b.click(); } catch {}
const nb = page.locator("[data-wb-psess-new]").first();
await nb.waitFor({ state: "visible", timeout: 8000 });
console.log("new-btn disabled=", await nb.getAttribute("disabled"), "title=", await nb.getAttribute("title"));
await nb.click({ timeout: 5000 }).catch(async () => { await nb.evaluate((el) => el.click()); });
await page.waitForTimeout(6000);
// 尝试在 composer 打字，看 phase 是否翻 active
const ta = page.locator("textarea").first();
console.log("textarea count=", await page.locator("textarea").count());
if (await ta.count()) {
  const edit = await page.evaluate(() => [...document.querySelectorAll("textarea,[contenteditable='true'],[contenteditable='']")].map(e => ({tag: e.tagName, cls: String(e.className||'').slice(0,100), ph: e.placeholder || e.getAttribute('data-placeholder') || '', vis: !!e.offsetParent, id: e.id})));
  console.log("editables=", JSON.stringify(edit));
  await ta.evaluate(el=>{el.focus();});
  // React 受控组件：native setter + input 事件（绕遮罩/焦点）
  const filled = await ta.evaluate((el) => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, "只回复：好");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return el.value;
  });
  console.log("native-set value=", JSON.stringify(filled));
  await page.waitForTimeout(500);
  console.log("draft value=", JSON.stringify(await ta.evaluate(el=>el.value)), "disabled=", await ta.evaluate(el=>el.disabled));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1000);
  console.log("draft after enter=", JSON.stringify(await ta.evaluate(el=>el.value)));
  // 找 send 按钮
  const btns = await page.evaluate(() => [...document.querySelectorAll("button")].map(b => ({al: b.getAttribute("aria-label")||"", t: (b.textContent||"").trim().slice(0,24), dis: b.disabled})).filter(b => /send|发送|提交/i.test(b.al + b.t)));
  console.log("send-ish buttons=", JSON.stringify(btns));
  const sent = await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find(b => /send message/i.test(b.getAttribute("aria-label")||""));
    if (!b) return "<none>";
    b.click(); return "clicked disabled=" + b.disabled;
  });
  console.log("send click:", sent);
  await page.waitForTimeout(1500);
  console.log("draft after send=", JSON.stringify(await ta.evaluate(el=>el.value)));
}
for (let i=0;i<90;i++){ const ph=await page.evaluate(()=>document.querySelector("[data-phase]")?.getAttribute("data-phase")); if(ph==="active"){console.log("phase=active after",i,"s");break} if(i%10===9)console.log("t="+i,ph); await page.waitForTimeout(1000);} 
// 追加等 60s 轮询 phase
for (let i=0;i<60;i++){ const ph=await page.evaluate(()=>document.querySelector("[data-phase]")?.getAttribute("data-phase")||"<none>"); if(ph==="active"){console.log("phase active after",i,"s");break} await page.waitForTimeout(1000);} 
console.log("all phases:", await page.evaluate(()=>[...document.querySelectorAll("[data-phase]")].map(e=>e.getAttribute("data-phase")).join(",")));
console.log("notice =", await page.evaluate(() => document.querySelector("[data-wb-psess-notice]")?.textContent || "<none>"));
console.log("current rows:", await page.evaluate(() => [...document.querySelectorAll("[data-wb-psess-tab]")].map(e => `${e.getAttribute("data-active")}:${e.getAttribute("title")?.split("\n")[0]}`).join(" | ")));
await page.waitForTimeout(8000);
const phase = await page.evaluate(() => {
  const el = document.querySelector("[data-phase]");
  return el ? el.getAttribute("data-phase") : "<no data-phase>";
});
const cur = await page.evaluate(() => {
  const els = [...document.querySelectorAll("[data-wb-psess-tab]")];
  return els.map((e) => `${e.getAttribute("data-active")}:${e.getAttribute("title")?.split("\n")[0]}`).join(" | ");
});
console.log("data-phase =", phase);
console.log("rows:", cur);
console.log("---- browser console ----");
console.log(logs.slice(-40).join("\n") || "(空)");
await browser.close();
teardown();
