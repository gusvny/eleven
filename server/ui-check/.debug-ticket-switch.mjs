// 生产 3099 工单切换场景探针（用户授权）：A 建会话打字 → 切 B → 切回 A → 内容保留断言
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

// 进工单台视图（📋 图标）
const boardIcon = p.locator('[title*="工单"]').first();
if (await boardIcon.count()) { await boardIcon.click({ timeout: 3000 }).catch(() => {}); await p.waitForTimeout(2000); }

// 点第一个工单行（侧栏进行中工单或台面行）
const row = p.locator(".wb-table tbody tr").first();
if (await row.count()) {
  await row.click({ timeout: 3000 }).catch((e) => console.log("行点击失败:", String(e).slice(0, 80)));
  await p.waitForTimeout(4000);
  console.log("工单 A 打开后 phase:", await phase());
  // 找当前会话 id（shell 的 current）
  const cur = await p.evaluate(() => {
    const w = window;
    return w.__workbenchDebug?.currentSessionId ?? "(探针无钩子)";
  });
  console.log("current 会话:", String(cur).slice(0, 80));
  // 打字
  const composer = p.locator("textarea:visible").first();
  if (await composer.count()) {
    await composer.click();
    await composer.type("工单A切换保留测试标记XYZZY");
    await composer.press("Enter");
    await p.waitForTimeout(3000);
    const msg = await p.locator('text=工单A切换保留测试标记XYZZY').count();
    console.log("A 消息出现:", msg > 0);
  } else { console.log("A 无 composer"); }
  await p.screenshot({ path: "/tmp/tswitch-A.png" });
}

// 切到另一个工单（第二行）
const row2 = p.locator(".wb-table tbody tr").nth(1);
if (await row2.count()) {
  await row2.click({ timeout: 3000 }).catch(() => {});
  await p.waitForTimeout(4000);
  console.log("工单 B 打开后 phase:", await phase());
  await p.screenshot({ path: "/tmp/tswitch-B.png" });
}

// 切回第一个工单
const row1 = p.locator(".wb-table tbody tr").first();
if (await row1.count()) {
  await row1.click({ timeout: 3000 }).catch(() => {});
  await p.waitForTimeout(4000);
  console.log("切回 A 后 phase:", await phase());
  const back = await p.locator('text=工单A切换保留测试标记XYZZY').count();
  console.log("切回后 A 消息还在:", back > 0);
  await p.screenshot({ path: "/tmp/tswitch-back-A.png" });
}
console.log("--- 浏览器 console（尾部 15）---");
for (const m of consoleMsgs.slice(-15)) console.log(" ", m);
console.log("--- page errors ---", pageErrors.slice(-3));
await b.close();
