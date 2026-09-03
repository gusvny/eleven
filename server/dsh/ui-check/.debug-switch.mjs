// 生产 3099 切换场景探针（用户授权）：会话 A/B 来回切换，检查内容保留
import { chromium } from "./node_modules/playwright-core/index.mjs";

const b = await chromium.launch({ channel: "chrome", headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const consoleMsgs = [], pageErrors = [];
p.on("console", (m) => consoleMsgs.push(`[${m.type()}] ${m.text()}`.slice(0, 260)));
p.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 260)));

await p.goto("http://127.0.0.1:3099/", { waitUntil: "networkidle" });
await p.waitForTimeout(3000);
const phase = () => p.evaluate(() => document.querySelector("[data-phase]")?.getAttribute("data-phase"));
console.log("phase(初始):", await phase());

// ① 新建会话 A
const newBtn = p.locator('button:has-text("新建会话"), button:has-text("New Session"), [aria-label*="New session" i]').first();
if (await newBtn.count()) { await newBtn.click({ timeout: 3000 }).catch(() => {}); }
for (let t = 0; t < 10; t++) {
  if (await p.evaluate(() => document.querySelector('[data-phase="active"]')?.offsetParent !== null)) break;
  await p.waitForTimeout(1250);
}
console.log("A 新建后 phase:", await phase());
// A 打字 + Enter
const composer = p.locator("textarea:visible").first();
if (await composer.count()) {
  await composer.click();
  await composer.type("会话A的测试内容");
  await composer.press("Enter");
  await p.waitForTimeout(3000);
  const msgA = await p.locator('text=会话A的测试内容').count();
  console.log("A 消息出现:", msgA > 0);
}
await p.screenshot({ path: "/tmp/switch-A.png" });

// ② 新建会话 B
if (await newBtn.count()) { await newBtn.click({ timeout: 3000 }).catch(() => {}); }
for (let t = 0; t < 10; t++) {
  if (await p.evaluate(() => document.querySelector('[data-phase="active"]')?.offsetParent !== null)) break;
  await p.waitForTimeout(1250);
}
console.log("B 新建后 phase:", await phase());
await p.screenshot({ path: "/tmp/switch-B.png" });

// ③ 切回 A：点 MRU/顶行的会话 A 行
const rows = p.locator("[data-wb-session-row]");
console.log("MRU 行数:", await rows.count());
const rowTexts = await rows.allTextContents().catch(() => []);
console.log("行文本:", rowTexts.map(t => t.slice(0, 40)));
// 点含「会话A的测试内容」的行（MRU 行标题通常是首条消息摘要）
let target = null;
for (const t of rowTexts) { if (t.includes("会话A")) { target = rowTexts.indexOf(t); break } }
if (target !== null && target >= 0) {
  await rows.nth(target).click({ timeout: 3000 }).catch((e) => console.log("行点击失败:", String(e).slice(0, 80)));
  await p.waitForTimeout(3000);
}
console.log("切回 A 后 phase:", await phase());
const back = await p.locator('text=会话A的测试内容').count();
console.log("切回后 A 内容出现:", back > 0);
await p.screenshot({ path: "/tmp/switch-back-A.png" });
console.log("--- 浏览器 console（尾部 15）---");
for (const m of consoleMsgs.slice(-15)) console.log(" ", m);
console.log("--- page errors ---", pageErrors.slice(-3));
await b.close();
