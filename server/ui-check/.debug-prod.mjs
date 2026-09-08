// 生产 3099 探针 v2（用户授权）：选 workspace → 新建会话 → 全量遥测
import { chromium } from "./node_modules/playwright-core/index.mjs";

const b = await chromium.launch({ channel: "chrome", headless: true });
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const consoleMsgs = [], pageErrors = [], badReqs = [];
p.on("console", (m) => consoleMsgs.push(`[${m.type()}] ${m.text()}`.slice(0, 260)));
p.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 260)));
p.on("requestfailed", (r) => badReqs.push(`FAIL ${r.url().slice(0, 120)} ${r.failure()?.errorText}`));
p.on("response", (r) => { if (r.status() >= 400) badReqs.push(`HTTP ${r.status()} ${r.url().slice(0, 120)}`); });

await p.goto("http://127.0.0.1:3099/", { waitUntil: "networkidle" });
await p.waitForTimeout(3000);
const phase = () => p.evaluate(() => document.querySelector("[data-phase]")?.getAttribute("data-phase"));
console.log("phase(初始):", await phase());

// ① 选 workspace：点开 hero 的 workspace 下拉，选含 suyou 的选项
const wsBtn = p.locator('button:has-text("Choose workspace"), [class*="orkspace"] button, button:has-text("suyou")').first();
if (await wsBtn.count()) {
  await wsBtn.click({ timeout: 3000 }).catch((e) => console.log("ws 点击失败:", String(e).slice(0, 80)));
  await p.waitForTimeout(1200);
  // 下拉选项：role=option 或含 suyou 的可点项
  const opt = p.locator('[role="option"]:has-text("suyou")').first();
  if (await opt.count()) {
    await opt.click({ timeout: 2000 }).catch(() => {});
    console.log("workspace 已选: suyou");
  } else {
    console.log("下拉选项未找到（列出可见文本供排查）:");
    const texts = await p.locator('[role="option"], [role="menuitem"], li').allTextContents().catch(() => []);
    console.log(texts.slice(0, 8).map(t => t.slice(0, 40)));
  }
  await p.waitForTimeout(800);
  await p.screenshot({ path: "/tmp/prod-v2-1-ws-selected.png" });
} else {
  console.log("无 workspace 选择器");
}

// ② 新建会话
const newBtn = p.locator('button:has-text("新建会话"), button:has-text("New Session"), [aria-label*="New session" i]').first();
if (await newBtn.count()) {
  await newBtn.click({ timeout: 3000 }).catch((e) => console.log("新建点击失败:", String(e).slice(0, 80)));
  for (let t = 0; t < 10; t++) {
    if (await p.evaluate(() => document.querySelector('[data-phase="active"]')?.offsetParent !== null)) break;
    await p.waitForTimeout(1250);
  }
  console.log("新建后 phase:", await phase());
  const ta = await p.locator("textarea:visible").count();
  console.log("textarea 可见:", ta);
  await p.screenshot({ path: "/tmp/prod-v2-2-after-new.png" });
}

// ③ 打字 + Enter（真发消息）
const composer = p.locator("textarea:visible").first();
if (await composer.count()) {
  await composer.click();
  await composer.type("探针测试消息（可忽略）");
  await p.screenshot({ path: "/tmp/prod-v2-3-typed.png" });
  await composer.press("Enter");
  await p.waitForTimeout(5000);
  const userMsg = await p.locator('text=探针测试消息').count();
  console.log("消息发出后: 用户消息出现 =", userMsg > 0);
  await p.screenshot({ path: "/tmp/prod-v2-4-after-send.png" });
}
console.log("--- 浏览器 console（尾部 15）---");
for (const m of consoleMsgs.slice(-15)) console.log(" ", m);
console.log("--- page errors ---", pageErrors.slice(-3));
console.log("--- bad requests ---", badReqs.slice(-4));
await b.close();
