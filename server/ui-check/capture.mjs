#!/usr/bin/env node
// capture.mjs —— 溯游控制台 UI 验收截图通道（t260828-09 建，t260829-07 扩视图清单）。
//
// 用途：UI 票验收证据。由工单引擎 worker（无沙箱，同 merge_check 通路）代跑，
//   也供人手动补跑；t260829-07 起通常经 capture-lane.mjs 一键隔离台调用（本脚本
//   只管对一个 --url 截全部视图，隔离台组装在 capture-lane.mjs）。
// 只读红线：只 GET 打开控制台页面并做导航点击（语义锚定位），不提交任何表单、
//   不发工单、不碰任何进程端口。「新建工单弹层」视图只点开弹层、绝不点提交。
//
// 用法：
//   node capture.mjs --url <console> --out <dir>     # 截图（缺省 url 见 SANDBAR_CONSOLE_URL）
//   node capture.mjs --selftest                      # 干跑：不起浏览器，校验参数/目录可写
//   node capture.mjs --allow-seed ...                # 仅隔离台：允许台内造数（建会话+写账册）；
//                                                    # 直连/生产路径绝不能带此旗
//   node capture.mjs --fixtures <dir> ...            # 状态注入（t260901-24）：拦截 wf 读端点回
//                                                    # fixture 票，让实拍到达审批抽屉/泳道并行态；
//                                                    # 仅隔离台路径（--allow-seed 同现）可用，且显式
//                                                    # opt-in（capture-lane 缺省不传，见其 SANDBAR_CAPTURE_FIXTURES）
//
// 环境变量：
//   SANDBAR_CONSOLE_URL        控制台地址，缺省 http://127.0.0.1:3099（测试环境 3199）
//   SANDBAR_UI_CAPTURE_TIMEOUT_MS  整体超时，缺省 60000（activity 侧另有 120s 兜底）
//   SANDBAR_UI_CAPTURE_ALLOW_SEED=1  与 --allow-seed 等价（env 通路，t260831-02 同款）
//   SANDBAR_UI_CAPTURE_FIXTURES=1    与 --fixtures 等价（env 通路）；注意 capture-lane 只认
//                                  自己的 SANDBAR_CAPTURE_FIXTURES（bench 级开关），两者名字
//                                  不通用——错设本台 env 名=不注入（无告警，行为=7 视图），
//                                  正确做法是经 capture-lane 的 env 或直跑本脚本带 --fixtures。
//   SANDBAR_UI_CAPTURE_BOARD_MS  板面就绪断言预算，缺省 15000（t260910-05）；非有限正数
//                                  （NaN/0/负/非数字）回落缺省并 loud 提示一行——错设成
//                                  畸形值不会让板面视图静默失效（本清单 env 名错设无告警
//                                  的同族坑，见上一条教训）。
//
// 视图清单（t260829-07 六视图 + 立项单列表；尽力视图失败置非零退出码但不阻断其余；
// t261005-16 起另设「具名跳过」：数据缺席类（如新家零立项）跳过不截图、不记失败、
// 不计退出码，但必须具名可读——尽力失败（渲染/断言故障）与合法空数据两种口径分开）：
//   console-default.png      hero 落地页（必成视图，失败即整体非零退出）
//   console-board.png        工单入口（侧栏「工单列表」视图图标）——快门前过板面就绪
//                            断言（t260910-05）：筛选条在场且（行卡≥1 或 空态在场），
//                            未就绪=loud 报错不交图（废图防线）
//   console-epics.png        立项单列表（侧栏「立项单」视图图标 → .wb-ep-root）
//   console-new-ticket.png   新建工单弹层打开态（只开不提交——「新建后」的只读红线
//                            降级口径，t260829-07 review 定案；真新建=写操作不豁免）
//   console-sessions.png     项目会话区行（票② R8 改锚 t260904-05：data-wb-psess-row 可见 +
//                            旧左栏 .wb-sess-* 不在场——本票已按设计删除左栏会话区）
//   console-refresh.png      刷新回归（reload 后再截，防「刷新回不去」回归）
//   console-chat.png         chat 态（打开已有会话，data-phase=active）
//
// fixture 态专属视图（t260901-24，仅 --fixtures 注入模式进 VIEWS；缺省清单不含）：
//   console-approval.png     审批抽屉打开态（T-FIX-A awaiting-human ✋；只看不批）
//   console-lane-parallel.png 泳道并行态（T-FIX-B 双 ▶，.wb-d2-par ≥2）
//
// 导航定位一律语义锚（title/data-phase/稳定类名），禁哈希类名选择器；
// 截图带字节级同帧检测（同帧=导航未生效，非 0 退出）。
//
// 终态回收：正常/报错/超时/信号（SIGINT/SIGTERM）四条路径都关闭 browser，
//   process exit 钩子兜底，不留孤儿 chromium。

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync, lstatSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

/**
 * 控制台导航（260928 修，KI-156）：原来一律 `waitUntil: "networkidle"`，而控制台是**持续轮询**
 * 的台面——网络永不落 idle ⇒ 首屏导航在慢台/并发下超时（实案：capture 族台已就绪却拍到 401/
 * 超时）。改为 domcontentloaded + 显式沉降等待；真实就绪判据交给各视图自己的 waitFor。
 */
async function gotoConsole(page, url, timeoutMs) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await page.waitForTimeout(800);
}

function parseArgs(argv) {
  const args = { url: null, out: null, selftest: false, allowSeed: false, fixtures: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--url") args.url = argv[++i] ?? "";
    else if (a === "--out") args.out = argv[++i] ?? "";
    else if (a === "--selftest") args.selftest = true;
    else if (a === "--allow-seed") args.allowSeed = true;
    else if (a === "--fixtures") args.fixtures = argv[++i] ?? "";
    else throw new Error(`未知参数：${a}`);
  }
  return args;
}

/* ── 状态注入（t260901-24）：fixture 票预置到指定 stage/门 ──
 * 根因：隔离台全新空家（Temporal 不在线）→ wf tickets 恒空 → ui_evidence 只能拍
 * 7 张「渲染正常级」。方案：浏览器层 page.route 拦截 wf 读端点回 fixture JSON
 * （不改 workbench/node.ts、不碰 Temporal）。三条硬纪律：
 *   ① opt-in 门旗（R2）：--fixtures 旗或 env SANDBAR_UI_CAPTURE_FIXTURES=1 双通路等价
 *      （t260831-02 门旗同款），且必须与 --allow-seed 同现（联锁）——直连真生产台
 *      带注入=把假票注进真台，绝不允许。缺省（两通路都不开）= 7 视图口径逐字节不变。
 *   ② 只拦 GET（R3）：POST accept/advance/dispatch-next/rework/update 恒 passthrough。
 *   ③ fulfill 恒显式 contentType application/json（R4）：客户端 res.json() 依赖，
 *      缺了会静默渲染空态=伪造「渲染正常」。
 * LIFO 取舍（R5，写明非遗漏）：Playwright 路由 LIFO 匹配、多 handler 易被反超——
 * 本设计单 handler 内部经 routeDecision 分派，从结构上绕开。
 * 证据自证（R2 补丁）：PNG 无法自标注入态——fixture 模式下 stdout 打 FIXTURE-MODE 行
 * + out 目录落 fixture-manifest.json（URL→fixture 映射），审读人对照。
 * loadFixtures 实体性校验（R1③，镜像 presetMaterializeRejectReason）：普通实体文件
 * （拒软链）、JSON 可解析、_fixture 标记在、必需键在——证据素材源缺/畸形一律 loud
 * 拒跑（严格侧），不静默降级渲染空态。 */

/** fixture 文件名→必需键形状表（与客户端消费同构：TicketRow/TicketDetail/Wf/TicketDiffResult）。 */
export const FIXTURE_FILES = [
  "tickets-list.json", "ticket-show-T-FIX-A.json", "ticket-show-T-FIX-B.json",
  "ticket-diff-T-FIX-A.json", "workflows.json",
];
const TICKET_ROW_KEYS = ["id", "stage", "stage_state", "workflow"];
const TICKET_DETAIL_KEYS = ["id", "stage", "stage_state", "status", "timeline", "results"];

/** 加载并校验 fixture 目录。返回 {文件名去 .json → 对象}；任何不合规=抛人话拒因
 * （调用方 main 捕获后退出 2——证据素材宁可拒跑不可半真半假）。纯同步、零副作用，
 * 供基线黑盒 import（capture.mjs 入口守卫保证 import 无副作用）。 */
export function loadFixtures(dir) {
  if (!dir || !existsSync(dir) || !statSync(dir).isDirectory()) {
    throw new Error(`fixture 目录缺失或不是目录：${dir}`);
  }
  const out = {};
  for (const f of FIXTURE_FILES) {
    const p = path.join(dir, f);
    let st;
    try { st = lstatSync(p); } catch {
      throw new Error(`fixture 缺文件：${p}`);
    }
    if (st.isSymbolicLink()) {
      throw new Error(`fixture 不允许软链（实体性校验，镜像 presetMaterializeRejectReason 的「软链不被扫描」类防呆）：${p}`);
    }
    if (!st.isFile()) throw new Error(`fixture 不是普通文件：${p}`);
    if (!path.resolve(p).startsWith(path.resolve(dir) + path.sep)) {
      throw new Error(`fixture 路径越出 fixture 目录：${p}`);
    }
    let v;
    try { v = JSON.parse(readFileSync(p, "utf8")); } catch (e) {
      throw new Error(`fixture JSON 解析失败：${p}——${e.message}`);
    }
    if (v?._fixture !== true) {
      throw new Error(`fixture 缺 "_fixture": true 标记（证据自证字段，审读人据此对照 manifest）：${p}`);
    }
    out[f.replace(/\.json$/, "")] = v;
  }
  // 形状校验：列表（含内嵌 workflows——客户端主通路是 /tickets 响应里的 data.workflows）。
  // 票数组宽容读：顶层 tickets（t260901-24 并行测试合同形状）或 result.tickets（客户端
  // 响应形状）皆可，文件内两者同值冗余并存亦合法。
  const list = out["tickets-list"];
  const tickets = Array.isArray(list?.tickets) ? list.tickets : list?.result?.tickets;
  if (!Array.isArray(tickets) || tickets.length < 2) {
    throw new Error("fixture tickets-list.json 形状不合规：tickets（顶层或 result.tickets）须为 ≥2 元素数组（T-FIX-A awaiting-human + T-FIX-B running）");
  }
  for (const t of tickets) {
    for (const k of TICKET_ROW_KEYS) {
      if (!(k in (t ?? {}))) throw new Error(`fixture tickets-list.json 票缺字段 ${k}（TicketRow 同构）`);
    }
  }
  if (!Array.isArray(list?.workflows) && !(Array.isArray(list?.result?.workflows))) {
    // 客户端读 data.workflows（顶层）；result.workflows 为响应全形状冗余。
    // 缺省宽容（t04 干跑桩不内嵌 workflows）：此时由 workflows.json 文件兜底。
    console.log("[capture] 警告：tickets-list.json 未内嵌 workflows，泳道图模板链以 workflows.json 为准");
  }
  // workflows.json（宽容形状：{workflows:[…]} 即可，order/stages 由消费方自取）
  const wfFile = out["workflows"];
  if (!Array.isArray(wfFile?.workflows) || wfFile.workflows.length === 0) {
    throw new Error("fixture workflows.json 形状不合规：workflows 须为非空数组（模板链，含 id/order/stages）");
  }
  // 详情两份（裸 detail 对象 + _fixture 标记在顶层；fulfill 时由 routeDecision 包
  // {ok,result} 适配客户端 res.json() 的响应形状）。
  for (const id of ["T-FIX-A", "T-FIX-B"]) {
    const d = out[`ticket-show-${id}`];
    if (!d || typeof d !== "object") throw new Error(`fixture ticket-show-${id}.json 形状不合规：缺 detail 对象`);
    for (const k of TICKET_DETAIL_KEYS) {
      if (!(k in d)) throw new Error(`fixture ticket-show-${id}.json 票缺字段 ${k}（TicketDetail 同构）`);
    }
    if (!Array.isArray(d.timeline)) throw new Error(`fixture ticket-show-${id}.json：timeline 须为数组`);
    if (typeof d.results !== "object" || d.results === null) {
      throw new Error(`fixture ticket-show-${id}.json：results 须为对象（lane-states.ts attempts 推导依赖）`);
    }
  }
  // diff（裸对象即可；真实载荷形状由消费端软降级，不做逐键硬卡）
  if (!out["ticket-diff-T-FIX-A"] || typeof out["ticket-diff-T-FIX-A"] !== "object") {
    throw new Error("fixture ticket-diff-T-FIX-A.json 形状不合规：缺 diff 对象（TicketDiffResult 同构）");
  }
  return out;
}

/** 路由决策纯函数（R3/R4 锚，基线黑盒消费）：仅 GET 且命中 wf 读端点时 fulfill；
 * 一切 POST（accept/advance/dispatch-next/rework/update 写端点）与未知路径恒放行。
 * URL 只比 pathname 不比 query（R3/C3：withProject 会挂 ?project=，整串匹配会静默
 * 放行 → 空列表 → 伪造「渲染正常」，正是本票根治的病）。返回
 * {fulfill:{status,contentType,body}, fixture:名} 或 {passthrough:true}。 */
export function routeDecision(method, url, fixtures) {
  if (method !== "GET") return { passthrough: true };
  let u;
  try { u = new URL(url); } catch { return { passthrough: true }; }
  const p = u.pathname;
  // wrapResult：show/diff 的 fixture 是裸 detail 对象（t260901-24 并行测试合同形状），
  // fulfill 时包 {ok:true,result} 适配客户端 apiGet 的 data.ok===true 断言。
  const wrapResult = (name) => ({
    fulfill: {
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, result: fixtures[name] }),
    },
    fixture: name,
  });
  const fulfill = (name) => ({
    fulfill: { status: 200, contentType: "application/json", body: JSON.stringify(fixtures[name]) },
    fixture: name,
  });
  if (p === "/sandbar-workbench/api/wf/tickets") return fulfill("tickets-list");
  let m = p.match(/^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)$/);
  if (m) {
    const key = `ticket-show-${decodeURIComponent(m[1])}`;
    return fixtures[key] ? wrapResult(key) : { passthrough: true };
  }
  m = p.match(/^\/sandbar-workbench\/api\/wf\/tickets\/([^/]+)\/diff$/);
  if (m) {
    const key = `ticket-diff-${decodeURIComponent(m[1])}`;
    return fixtures[key] ? wrapResult(key) : { passthrough: true };
  }
  if (p === "/sandbar-workbench/api/wf/workflows") return fulfill("workflows");
  return { passthrough: true };
}

// 浏览器获取：优先系统 Chrome（channel:"chrome"），探测不到退 playwright 自带
// chromium；两者都不可用 → 明确报错非零退出（不静默降级）。
async function launchBrowser(playwright) {
  try {
    return await playwright.chromium.launch({ channel: "chrome", headless: true });
  } catch (e) {
    console.error(`[capture] 系统 Chrome 不可用（${e.message.split("\n")[0]}），退 playwright chromium`);
  }
  return playwright.chromium.launch({ headless: true });
}

// ── 台内会话种子（t260831-02 加）──
// 隔离台（capture-lane）= 临时 DSH_HOME + 全新 localStorage，MRU 账册必为空，
// chat 态视图（console-chat.png，selfcheck 证据闸要件）永远开不出来。这里做
// 「台内造数」：经隔离台自己的 API 建会话（global-session/open，无工单前缀）+
// page.evaluate 写本插件账册（LEDGER_KEY，仅浏览器本地，不碰服务端数据）。
// ⚠️ Bench-gate（红线）：种子**只在 --allow-seed（或 env
// SANDBAR_UI_CAPTURE_ALLOW_SEED=1）显式放行时**才可能执行——capture 每次
// browser.newContext() 都是全新上下文，localStorage 必为空，MRU 行任何环境
// 都不存在；不设门控的话，agent_activities 的直连兜底路径（--url 指向生产
// 3099）会往生产控制台真实 POST 建会话，绕开只读红线。capture-lane 隔离台
// 的 DSH_HOME 是临时的，台内造数不违红线——所以门旗由隔离台路径显式传入
//（capture-lane 传 --allow-seed 或设该 env；直连路径永远不带旗标，行为退回
// 旧的「明确报错交人」）。造两个会话，MRU 来回视图（两会话切换）才有素材。
const LEDGER_KEY = "sandbar-workbench-opened-sessions-v1";

/** 种子消息防呆（畸形输入用例的锚，t260901-03）：空/超长/控制字符 → 人话拒因，否则 null。
 *  seedChatMessage 的实际消息词可 env 覆盖，本函数供调用前防呆与基线单测。 */
export function validateSeedText(text) {
  if (typeof text !== "string" || text.length === 0) return "种子消息为空或非字符串";
  if (text.length > 2000) return `种子消息超长（${text.length} 字符 > 2000）`;
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)) return "种子消息含控制字符";
  return null;
}

/** 账册条目集（容错读；坏 JSON/非数组/脏条目一律剔脏——空 id 也是脏），不抛。 */
export function parseLedgerIds(raw) {
  try {
    const v = JSON.parse(raw ?? "[]");
    if (!Array.isArray(v)) return [];
    return v.map((e) => e && typeof e === "object" ? e.id : null)
      .filter((x) => typeof x === "string" && x !== "");
  } catch { return []; }
}

/** 账册键（capture-chat-active 基线与插件账册同键；供单测/外部锚定）。 */
export { LEDGER_KEY };

// ── 板面就绪断言（t260910-05 截图内容断言）──
// 病灶：板面视图在主列表渲染完成前按快门，拍到无操作按钮的废图，且走查 agent 是
// 文本模型看不了像素、合并闸只查文件存在性——废图全绿混进归档无人发现。修法：把
// 「拍到该拍的」机械化——快门前断言板面就绪锚在场，断言失败=截图失败不交图（run
// 抛错走既有 failures[]→exitCode=1 链传导 prepare_ui_evidence 红，禁止对断言单独
// 包 try/catch「不阻断」——那会做出「不交图但全链绿」的半吊子）。
/** 板面就绪锚（语义锚，禁哈希类名）：筛选条=操作面在场；行卡=主列表已渲染；
 *  空态=数据为空但已渲染完（.wb-empty「没有符合筛选的工单。」，src/client/index.tsx）。 */
export const BOARD_ANCHORS = { chips: ".wb-chip-btn", rows: ".wb-card", empty: ".wb-empty" };
/** 就绪预算缺省值（SANDBAR_UI_CAPTURE_BOARD_MS 畸形时回落到此，见 resolveBoardBudgetMs）。 */
export const BOARD_BUDGET_DEFAULT_MS = 15000;

/** 就绪预算解析（纯函数，供 selftest/场景单测）：非有限正数（NaN/0/负/非数字/空串）
 *  → 回落缺省 15000 并置 defaulted=true（调用方 loud 提示一行，不静默吞、不因畸形
 *  env 拒跑）；合法值原样透传。 */
export function resolveBoardBudgetMs(raw) {
  const n = Number(raw);
  if (raw === undefined || raw === null || raw === "" || !Number.isFinite(n) || n <= 0) {
    return { ms: BOARD_BUDGET_DEFAULT_MS, defaulted: true };
  }
  return { ms: n, defaulted: false };
}

/** 板面就绪断言：轮询至「筛选条在场 且（行卡 ≥1 或 人话空态在场）」，超时 loud 抛错
 *  （附三锚计数诊断，沿用 chat 态诊断写法）。探针异常（locator.count 炸）即刻 loud，
 *  不静默不重试吞掉。budgetMs 显式传参优先（场景失败分支钉极小值用），否则读 env。
 *  桩 page 契约（sc_capture_board_assert 依赖）：只需 locator(sel).count()。 */
export async function assertBoardReady(page, budgetMs) {
  const { ms, defaulted } = resolveBoardBudgetMs(budgetMs ?? process.env.SANDBAR_UI_CAPTURE_BOARD_MS);
  if (defaulted && budgetMs === undefined) {
    console.log(`[capture] SANDBAR_UI_CAPTURE_BOARD_MS 畸形（须为有限正数）→ 回落缺省 ${BOARD_BUDGET_DEFAULT_MS}ms（loud 提示，不静默）`);
  }
  const deadline = Date.now() + ms;
  const count = async (sel) => {
    try {
      return await page.locator(sel).count();
    } catch (e) {
      throw new Error(`板面就绪探针失败（${sel}）：${e?.message ?? e}——按失败处理，不交图`);
    }
  };
  for (;;) {
    const chips = await count(BOARD_ANCHORS.chips);
    const rows = await count(BOARD_ANCHORS.rows);
    const empty = await count(BOARD_ANCHORS.empty);
    if (chips > 0 && (rows > 0 || empty > 0)) {
      return `板面就绪（筛选条=${chips} 行卡=${rows} 空态=${empty}）`;
    }
    if (Date.now() >= deadline) {
      throw new Error(`板面未就绪（${ms}ms 预算耗尽）：筛选条=${chips} 行卡=${rows} 空态=${empty}`
        + `——主列表渲染未完成，拒拍废图（t260910-05 截图内容断言）`);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
}

/** 板面视图统一 run：切视图 → 就绪断言（抛错即该视图失败=不 shoot=无图）。 */
async function openBoardView(page) {
  const anchor = await openView(page, "Tickets");
  const ready = await assertBoardReady(page);
  return `${anchor} → ${ready}`;
}

/** 板面视图统一 run 工厂（t260910-05 P1 接线锁）：返回「切视图 → 就绪断言」的
 *  run 函数（抛错即该视图失败=不 shoot=无图）。条目与场景共用此工厂产出的同一
 *  函数对象；条目被解绑回裸 openView 时，sc_capture_board_assert 的零 DOM 死板面
 *  腿必红（桩只满足 openView 导航面，未接断言的条目会照常 resolve=真红）。 */
export function makeBoardRun() {
  return (page) => openBoardView(page);
}

/** 板面三视图导出条目（t260910-05 P1 接线锁）：default/dark/light 三条 run 收敛到
 *  模块级可导出**数组**面（sc_capture_board_assert findViewEntries 按数组识别），
 *  main 的 VIEWS 与深浅外观循环都从这里取条目——场景桩 page 驱动同一批对象，条目
 *  被解绑即场景红（KI-051 行为锁，不用字面源文本锚）。外观切换（emulateMedia）留在
 *  主循环：条目只管「导航+就绪断言」，桩 page 无需 emulateMedia 面。
 *  与 design_integration_tests 兄弟段预置的 sc_capture_board_assert.mjs 契约对齐
 *  （导出面=makeBoardRun/assertBoardReady/BOARD_ANCHORS + 数组条目；本文件改动不得
 *  单方面破坏该契约，汇合时以场景为准）。 */
export const BOARD_VIEWS = [
  { file: "console-board.png", title: "工单入口（板面就绪断言）", run: makeBoardRun() },
  { file: "console-board-dark.png", title: "工单入口（dark 外观，板面就绪断言）", scheme: "dark", run: makeBoardRun() },
  { file: "console-board-light.png", title: "工单入口（light 外观，板面就绪断言）", scheme: "light", run: makeBoardRun() },
];

async function seedSessions(page, url) {
  const base = url.replace(/\/$/, "");
  // ① 项目注册表：取第一个项目 key（新建落点；隔离台通常单项目）
  const pr = await fetch(`${base}/sandbar-workbench/api/wf/projects`).then((r) => r.json());
  const project = pr?.result?.projects?.find((p) => p && typeof p.key === "string")?.key;
  if (!project) throw new Error("台内造数失败：/api/wf/projects 无可用项目 key");
  // ② 建两个真实会话（host 端落盘，id 真实可 open）
  const ids = [];
  for (let i = 0; i < 2; i++) {
    const d = await fetch(`${base}/sandbar-workbench/api/global-session/open`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project }),
    }).then((r) => r.json());
    if (!d?.ok || typeof d?.result?.session_id !== "string" || d.result.session_id === "") {
      throw new Error(`台内造数失败：global-session/open ${JSON.stringify(d?.error ?? d)}`);
    }
    ids.push({ id: d.result.session_id, cwd: typeof d.result.cwd === "string" ? d.result.cwd : "" });
  }
  // ②.5 cwd 非空断言（t260901-03）：cwd 为空则插件 blank 自愈分支（entry.cwd 真值
  // 前置）必不触发，等 25s 超时才知道——造数期就 loud 快速失败（capture-redline-gate
  // R2 的验收棒依赖本行为）。
  for (const x of ids) {
    if (!x.cwd) throw new Error(`台内造数失败：global-session/open 返回 cwd 为空（项目 ${project} 注册表 dirs 为空）——blank 自愈必不触发，不继续`);
  }
  // ③ 写账册（浏览器 localStorage）+ 刷新，让顶部入口 MRU 行出现
  await page.evaluate(([key, project2, rows]) => {
    const entries = rows.map(([id, cwd], i) => ({
      id, project: project2, cwd, lastOpenedAt: Date.now() - i * 1000,
    }));
    localStorage.setItem(key, JSON.stringify(entries));
  }, [LEDGER_KEY, project, ids.map((x) => [x.id, x.cwd])]);
  await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  return ids.map((x) => x.id);
}

// chat 态导航：分路径语义（t260901-02 修订）。
// - 直连路径（无 --allow-seed，只读红线）：只点「打开已有会话」（项目会话区
//   行的 tab [data-wb-psess-tab]），绝不点「+ 钮」（真实创建
//   会话=写操作）。无已有会话可开 → 明确报错，不静默降级。
// - 隔离台路径（--allow-seed 已放行台内造数）：点项目行台上「+ 钮」
//   （[data-wb-psess-new]，工厂同款语义：绑工作区+复用 blank+staging 打开）。
//   实证（dbg-chat.mjs，t260901-02）：seedSessions 经 global-session/open 自铸的
//   会话不绑工作区，平台语义「hero ⟺ 当前会话 blank」下点它永远停在 hero——
//   session-entry.tsx L343 注释自证「自铸会话…永远停在 hero」。preset 缺失根治
//   后 chat 态仍失败的残留根因即此；台内造数语义下点新建与自铸同权，非写生产。
// 出厂 ConversationRoot 的 data-phase 取值是 hero/settling/active（无 "chat"），
// 打开会话成功后根元素应翻到 data-phase="active"——以此为视图变化断言，防同帧假成功。
async function navigateToChat(page, allowSeed = false) {
  // 浏览器 console 回执（票 t260831-02 审读结论）：chat 打不开时把页面侧
  // console/pageerror 带回来定位——没有它，staging 层真因只能靠猜。
  const browserConsole = [];
  page.on("console", (m) => {
    const line = `[${m.type()}] ${m.text()}`.slice(0, 300);
    if (browserConsole.length < 60) browserConsole.push(line);
  });
  page.on("pageerror", (e) => {
    if (browserConsole.length < 60) browserConsole.push(`[pageerror] ${String(e).slice(0, 300)}`);
  });
  let anchor = "";
  if (allowSeed) {
    // 隔离台：先确保有项目（新建按钮无项目时禁用——seedSessions 顺带把项目注册表
    // 拉通，失败会抛人话报错），再点「+ 新建会话」走工厂同款 staging。
    await seedSessions(page, page.url());
    const newBtn = page.locator("[data-wb-psess-new]").first();
    try {
      await newBtn.waitFor({ state: "visible", timeout: 8000 });
    } catch {
      throw new Error("隔离台造数后未找到项目行「+ 钮」（[data-wb-psess-new]）——" +
        "会话入口未挂载或项目未注册，查 seedSessions 与 sandbar-workbench 挂载日志。");
    }
    await forceClick(newBtn, 5000);
    // 遮罩先让路再写值（t260901-03 Step ①）：准入模态的 mask 拦 pointer/focus，
    // 不先关掉 seedChatMessage 的写值配方会被干扰。
    await dismissAdmissionModal(page).catch((e) => { throw new Error(`台内造数失败（遮罩拦截）：${e.message}`); });
    // 让会话有可见内容（平台语义：composerPhase blank 恒 hero，只有真消息才翻
    // active——t260901-02 dbg-chat 实证链）。造一条最小消息：--allow-seed 已放行
    // 台内造数，此为一次真实模型调用（凭据=临时家 .credentials.yaml，源由
    // capture-lane 按 per-key 优先/legacy 回落解析拷入，与生产台同源）。
    try {
      await seedChatMessage(page);
    } catch (e) {
      // 失败面补浏览器 console 尾部（t260929 修定位）：台内建会话的失败唯一留痕处是
      // workbench 的 console.error（「新建会话失败：…」），不带上就只能靠猜——
      // 旧文案把两个猜测（machineBusy / 准入模态）当结论，实际把诊断引向了错误方向。
      throw new Error(`${e.message}；浏览器 console 尾部=${browserConsole.slice(-20).join(" | ") || "（无输出）"}`);
    }
    anchor = "隔离台项目行「+ 钮」+ 种子消息（[data-wb-psess-new]，真内容驱动 active）";
  } else {
    const row = page.locator("[data-wb-psess-tab]").first();
    try {
      await row.waitFor({ state: "visible", timeout: 8000 });
    } catch {
      throw new Error(
        "项目行没有可开的会话 tab（[data-wb-psess-tab]），且未带 --allow-seed（台内造数门旗，" +
        "仅隔离台路径可带）。只读红线禁止点「+ 新建会话」造 chat 态；隔离台请由 capture-lane 传 " +
        "--allow-seed（或 env SANDBAR_UI_CAPTURE_ALLOW_SEED=1）后重跑。"
      );
    }
    await forceClick(row, 5000);
    anchor = "项目会话区 tab 锚（[data-wb-psess-tab]）";
  }
  // 等 active；窗口期内若出厂弹「Add an API key」准入模态（隔离台无 key 实测会弹，
  // 遮罩挡会话激活——票 t260831-02 目视实锤），点「Configure later」让路后继续等。
  // 隔离台带种子消息：模型往返有延迟，预算放宽（env 可调，缺省 90s）。
  const activeBudgetMs = Number(process.env.SANDBAR_UI_CAPTURE_CHAT_ACTIVE_MS || (allowSeed ? 90000 : 25000));
  const deadline = Date.now() + activeBudgetMs;
  let active = false;
  while (Date.now() < deadline) {
    if (await page.locator('[data-phase="active"]').count()) { active = true; break }
    const later = page.locator('button:has-text("Configure later")').first();
    try {
      if (await later.isVisible()) { await later.click(); console.log("[capture] key 准入模态已点 Configure later"); }
    } catch { /* 模态时隐时现，下一轮再试 */ }
    await page.waitForTimeout(500);
  }
  if (!active) {
    const conTail = browserConsole.length
      ? "；浏览器 console 尾部：\n" + browserConsole.slice(-15).join("\n")
      : "；浏览器 console 无任何输出（点击处理链可能未绑定/静默返回）";
    throw new Error("点击会话入口后 " + Math.round(activeBudgetMs / 1000) + "s 内未出现 [data-phase=\"active\"]（出厂 chat 态语义锚），导航疑似未生效" + conTail);
  }
  // 截图前最后一道模态网（t260901-03 Step ①）：active 已到但准入模态可能在此窗口
  // 再弹/未关尽——关掉并确认消失，否则 chat 证据被遮挡。
  await dismissAdmissionModal(page);
  // 用户消息上屏等待（t260901-03 验收走查打回修复）：active 相位翻转快于转录渲染，
  // 直接截图可能只有模型占位行而无用户消息气泡——隔离台路径必须等消息词进转录。
  if (allowSeed) await waitForSeedOnTranscript(page, seedPromptText());
  return anchor;
}

/** 种子消息词唯一出口（seedChatMessage 发送与 waitForSeedOnTranscript 校验同源，
 * env SANDBAR_UI_CAPTURE_SEED_PROMPT 覆盖时两侧一致）。 */
function seedPromptText() {
  return process.env.SANDBAR_UI_CAPTURE_SEED_PROMPT || "（截图台造数）请只回复两个字：收到";
}

/** 隔离台种子消息（t260901-02 根因 #2）：平台语义「空内容会话恒 hero」（composerPhase
 * blank ⟺ 无可见会话内容，dbg-chat 反编译 dsh-client-ui-conversation 实证），点新建/
 * 开自铸会话都停在 hero，data-phase=active 必须有真消息驱动。输入配方（遮罩 _mask_
 * 拦 pointer 事件、键盘 focus 不稳，普通 type/fill/click 均失效的绕法）：
 *   ① textarea 上用 prototype native setter 写 value + dispatch bubbling input
 *      （React 受控组件 onChange 生效，playwright fill 同理但受 mask 干扰更稳的是直评）；
 *   ② DOM 直点 send 按钮（aria-label="Send message"）。
 * 消息词可 env SANDBAR_UI_CAPTURE_SEED_PROMPT 覆盖；发送即一次真实模型往返。
 *
 * ⚠️ 0.1.5 composer 换壳（t260929 实证，本夹具 chat 视图恒红的根因）：编辑器从
 * `<textarea>` 换成 **Lexical 富文本**——`div[contenteditable][data-composer-input]`
 * （dsh-client-ui-conversation 的 Editor 宿主，`editor.setEditable(editable)` 把
 * live/machineBusy 的合成结果落到 contenteditable 属性上）。所以：
 *   - 元素锚：优先 `[data-composer-input]`（平台机读锚），回落 `textarea`（0.1.1）；
 *   - 可编辑判据：contenteditable="true"（不是 textarea 的 readOnly/disabled）；
 *   - 写值通路：`keyboard.insertText` 走**真输入事件**（Lexical 只认自己的
 *     beforeinput/input 处理链，原型 value setter 对 contenteditable 无意义）；
 *   - 发送面不变：send 按钮 aria-label 仍是平台 i18n `input.send` = "Send message"。 */
async function seedChatMessage(page) {
  const promptText = seedPromptText();
  const badPrompt = validateSeedText(promptText);
  if (badPrompt) throw new Error(`台内造数失败：${badPrompt}`);
  // 新建会话到 composer 挂稳有窗口期（过早拿到的是将被换装的 hero composer，
  // 写进去会被换掉——t260901-02 实测 value 恒空）。重试写：每次现查 composer、
  // 写后回读校验，不粘住即等 1s 重来（最多 20s）。
  // charter 注入后（session-entry.tsx 点「+」即提交 charter）composer 进入
  // machineBusy：平台 InputBar 把它置不可编辑，此刻写值必被 React 受控回冲。
  // 且隔离台可能弹「Add an API key」准入模态把会话压在 inert——不点掉
  // 「Configure later」composer 永远不会 editable。所以写值前先等 composer
  // 可编辑（0.1.5：contenteditable="true"；0.1.1：textarea 非 readOnly 非
  // disabled，最长 120s，期间顺手点准入模态让路）；data-phase 是否翻 active
  // 不作为前置（平台 class 是 CSS-module 哈希名，不能当选择器用，只认稳定的
  // data-phase / [data-composer-input] 锚）。
  const editableDeadline = Date.now() + Number(process.env.SANDBAR_UI_CAPTURE_COMPOSER_EDITABLE_MS || 120000);
  // composer 探针（双版）：0.1.5 = [data-composer-input] 的 contenteditable，
  // 0.1.1 = textarea。返回 {kind, loc}；两版都不在场=null。
  const probeComposer = async () => {
    const ce = page.locator("[data-composer-input]").first();
    if (await ce.count()) return { kind: "lexical", loc: ce };
    const ta = page.locator("textarea").first();
    if (await ta.count()) return { kind: "textarea", loc: ta };
    return null;
  };
  const isEditable = async (c) => c.kind === "lexical"
    ? await c.loc.evaluate((el) => el.getAttribute("contenteditable") === "true").catch(() => false)
    : !(await c.loc.evaluate((el) => el.readOnly || el.disabled).catch(() => true));
  let composer = null;
  while (Date.now() < editableDeadline) {
    const later = page.locator('button:has-text("Configure later")').first();
    try {
      if (await later.isVisible()) { await later.click(); console.log("[capture] key 准入模态已点 Configure later"); }
    } catch { /* 模态时隐时现，下一轮再试 */ }
    const cand = await probeComposer();
    if (cand && await isEditable(cand)) { composer = cand; break; }
    await page.waitForTimeout(1000);
  }
  if (!composer) {
    // 诊断面（260929 修：旧诊断只报 textarea 数组，「一句人话猜两个原因」+ 空诊断
    // 把定位引向 machineBusy，而实测根因常在别处——按「报错必须精确」补齐自证面）：
    // 平台 composer 不可编辑 ⟺ disabled（!live/inert/blocked/removed）或 machineBusy
    // （input.phase ∈ adjudicating|submitting）；composer 元素是否在场 + contenteditable
    // 取值区分「没渲染」/「渲染了但被禁」（inert=无活会话或无工作区绑定）；psess 计数 +
    // 账册 active tab 证明「+ 钮」点击是否真的把会话立在台面上；浏览器 console 尾部
    // 承接 handleNew 的 console.error（建会话失败的唯一留痕处）。
    const diag = await page.evaluate(() => {
      const c = document.querySelector("[data-composer-input]");
      return {
        phases: [...document.querySelectorAll("[data-phase]")].map((e) => e.getAttribute("data-phase")),
        composerEl: c ? {
          contenteditable: c.getAttribute("contenteditable"),
          disabled: c.getAttribute("aria-disabled"),
          placeholder: (c.getAttribute("data-placeholder") || c.getAttribute("placeholder") || "").slice(0, 60),
        } : null,
        textareas: document.querySelectorAll("textarea").length,
        editables: document.querySelectorAll("[contenteditable]").length,
        psess: {
          newBtn: document.querySelectorAll("[data-wb-psess-new]").length,
          row: document.querySelectorAll("[data-wb-psess-row]").length,
          tab: document.querySelectorAll("[data-wb-psess-tab]").length,
          activeTab: document.querySelectorAll("[data-wb-psess-tab][data-active=true], [data-wb-psess-tab][data-active]").length,
        },
        dialogs: [...document.querySelectorAll('[role="dialog"]')].map((d) => (d.innerText || "").slice(0, 120)),
        bodyExcerpt: (document.body.innerText || "").slice(0, 400),
      };
    }).catch((e) => String(e));
    throw new Error("composer 在 120s 内未恢复可编辑（平台 composer 被禁：会话未 live/无工作区绑定/"
      + "machineBusy，或准入模态未让路），诊断=" + JSON.stringify(diag));
  }
  let filled = "";
  let lastErr = "";
  if (composer.kind === "lexical") {
    // Lexical 写值：先聚焦（DOM 直评，绕开 mask 拦 pointer），再 keyboard.insertText
    // 发真输入事件；回读编辑器文本校验（不粘住=清空重来，最多 20 轮）。
    for (let i = 0; i < 20; i++) {
      const cur = await composer.loc.evaluate((el) => el.innerText || el.textContent || "").catch(() => "");
      if (cur.includes(promptText)) { filled = promptText; break; }
      if (cur.trim() !== "") {
        await composer.loc.evaluate((el) => el.focus()).catch(() => {});
        await page.keyboard.press("ControlOrMeta+a").catch(() => {});
        await page.keyboard.press("Backspace").catch(() => {});
      }
      await composer.loc.evaluate((el) => el.focus()).catch((e) => { lastErr = String(e); });
      await page.keyboard.insertText(promptText).catch((e) => { lastErr = String(e); });
      await page.waitForTimeout(300);
    }
    if (filled !== promptText) {
      const seen = await composer.loc.evaluate((el) => (el.innerText || el.textContent || "").slice(0, 120)).catch(() => "");
      const diag = await page.evaluate(() => ({
        phases: [...document.querySelectorAll("[data-phase]")].map((e) => e.getAttribute("data-phase")),
        composerContenteditable: document.querySelector("[data-composer-input]")?.getAttribute("contenteditable") ?? null,
      })).catch((e) => String(e));
      throw new Error("种子消息写入 composer 失败（Lexical 编辑器 20 轮后文本=" + JSON.stringify(seen)
        + (lastErr ? "，末次异常=" + lastErr : "") + "，诊断=" + JSON.stringify(diag) + "）");
    }
  } else {
    for (let i = 0; i < 20; i++) {
      const ta = page.locator("textarea").first();
      if (!(await ta.count())) { await page.waitForTimeout(1000); continue; }
      filled = await ta.evaluate((el, txt) => {
        el.focus();
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
        setter.call(el, txt);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return el.value;
      }, promptText).catch((e) => { lastErr = String(e); return ""; });
      if (filled === promptText) break;
      await page.waitForTimeout(1000);
    }
    if (filled !== promptText) {
      const diag = await page.evaluate(() => {
        const tas = [...document.querySelectorAll("textarea")];
        return {
          phases: [...document.querySelectorAll("[data-phase]")].map((e) => e.getAttribute("data-phase")),
          textareas: tas.map((t) => ({
            cls: (t.className || "").slice(0, 60), disabled: t.disabled, readOnly: t.readOnly,
            visible: !!(t.offsetWidth || t.offsetHeight),
          })),
        };
      }).catch((e) => String(e));
      throw new Error("种子消息写入 composer 失败（重试 20s 后 value=" + JSON.stringify(filled)
        + (lastErr ? "，末次异常=" + lastErr : "")
        + "，诊断=" + JSON.stringify(diag) + "）");
    }
  }
  await page.waitForTimeout(300); // 让 React onChange 落 state
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find((x) =>
      /send message/i.test(x.getAttribute("aria-label") || ""));
    if (!b) return "no-send-button";
    b.click();
    return b.disabled ? "send-button-disabled" : "sent";
  });
  if (clicked !== "sent") {
    // 兜底：聚焦后回车（部分布局无 aria-label 按钮时）
    await composer.loc.evaluate((el) => el.focus()).catch(() => {});
    await page.keyboard.press("Enter");
    console.log("[capture] send 按钮不可用（" + clicked + "），已退避回车提交");
  }
}

/** 用户消息上屏等待（t260901-03 验收走查打回修复）：active 相位翻转为触发点，天然
 * 快于转录渲染——慢模型日截图可能只有「Deep diving…」占位而无用户消息气泡，chat
 * 证据不合格。发完种子消息后等会话转录（document.body.innerText）含消息词，预算
 * env SANDBAR_UI_CAPTURE_TRANSCRIPT_MS 可调（缺省 30s，独立于 CH_ACTIVE_MS 预算），
 * 超时 loud 报错不静默出图。 */
async function waitForSeedOnTranscript(page, promptText) {
  const budgetMs = Number(process.env.SANDBAR_UI_CAPTURE_TRANSCRIPT_MS || 30000);
  const deadline = Date.now() + budgetMs;
  while (Date.now() < deadline) {
    const onScreen = await page.evaluate((txt) =>
      (document.body.innerText || "").includes(txt), promptText).catch(() => false);
    if (onScreen) {
      console.log("[capture]   种子消息已上屏（会话转录含消息词）");
      return;
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`种子消息 ${budgetMs}ms 内未上屏（会话转录不含消息词）——chat 证据缺用户消息气泡，loud 失败`);
}

/** 点击侧栏视图图标（语义锚 title）切中列视图。
 * 出厂 UI 可能有遮罩层（mask）拦截指针事件——普通 click 超时后退避为 DOM 直点
 * （仍是只读导航语义：只切换视图，不提交任何表单）。 */
async function forceClick(locator, timeoutMs = 5000) {
  try {
    await locator.click({ timeout: timeoutMs });
  } catch {
    await locator.evaluate((el) => el.click());
  }
}

/** 准入模态关闭（t260901-03 Step ①）：出厂「Add an API key」准入模态在隔离台全新
 * DSH_HOME 下会弹并盖住后续交互/截图（票 t260831-02 目视实锤）——点「Configure
 * later」（无则首个可用钮/Escape）后轮询等 [role=dialog] 消失（≤8s）。只读导航语义：
 * 只点关闭/稍后，不提交任何配置。返回 null=本就无模态，否则人话锚点。
 * @throws {Error} 让路后 dialog 仍残留（遮罩拦截会污染后续一切视图与截图）。 */
async function dismissAdmissionModal(page) {
  const hadDialog = await page.locator('[role="dialog"]').count();
  if (!hadDialog) return null;
  const later = page.locator('button:has-text("Configure later")').first();
  try {
    if (await later.isVisible()) await later.click({ timeout: 2000 });
    else throw new Error("no Configure later");
  } catch {
    const dialog = page.locator('[role="dialog"]').first();
    try {
      const btn = dialog.locator("button:enabled").first();
      if (await btn.count()) await btn.click({ timeout: 2000 }).catch(() => {});
      else await page.keyboard.press("Escape").catch(() => {});
    } catch { /* 下一轮轮询兜底 */ }
  }
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (!(await page.locator('[role="dialog"]').count())) {
      console.log("[capture] 准入模态已关闭（chat 证据不被遮挡）");
      return "准入模态已关闭";
    }
    await page.waitForTimeout(400);
  }
  throw new Error("准入模态让路后仍残留（[role=dialog] 8s 未消失）——chat 证据将被遮挡，loud 失败");
}

/** 首屏就绪：出厂「Internal Testing Notice」（Continue 按钮）在全新 DSH_HOME 首次
 * 打开时弹出并盖住其后全部视图（票 t260829-07 实锤）——先等它出现则
 * 点掉（Continue=关闭提示框，只读导航语义，不提交任何表单），超时未出现则继续。
 * reload 后可能再弹，每个视图入口前都可安全重复调用。返回人话锚点或 null。 */
async function dismissNotice(page) {
  try {
    const btn = page.locator("button", { hasText: /continue|继续/i }).first();
    await btn.waitFor({ state: "visible", timeout: 4000 });
    await forceClick(btn);
    await btn.waitFor({ state: "hidden", timeout: 3000 }).catch(() => { /* 已消失即可 */ });
    return "出厂 notice 已关闭（Continue）";
  } catch {
    return null; // 未出现，继续
  }
}

/** 点击侧栏视图图标（语义锚 title）切中列视图。
 *
 *  title 真源 = 插件 PROJECT_ICON_SPECS（server/plugins/workbench/src/client/project-icons.tsx：
 *  Tickets / Docs / Model Routes / Epics / Project Settings）。宿主令 260925「控制台 UI
 *  文案英文化」把这四枚图标 title 从中文改名（提交 31b9ff3 / t260926 批），本夹具漏改 ⇒
 *  全部视图点击恒失败、chat 视图连带红（260929 修；KI-048 同族的「锚文案会自缚」前车之鉴）。
 *  报错面因此必须报出 DOM 实有 title，不再断言单一结论——旧文案「插件未挂载或侧栏收起」
 *  把「改名」这一真因彻底遮住，定位全靠手翻截图。 */
async function openView(page, title, waitSelector, waitMs = 3000) {
  const icon = page.locator(`.wb-view-icon[title="${title}"]`).first();
  let expanderTried = false;
  try {
    await icon.waitFor({ state: "visible", timeout: 5000 });
  } catch {
    // 261001 口径同步：侧栏做过「行内收纳」改造后，Docs / Model Routes / Project Settings
    // 三枚图标**只在展开位展开后才渲染**（常驻 = 工单 Tickets + 立项单 Epics 两枚，
    // 外加一枚 `data-wb-more-views` 的 ⋯ 展开钮；契约见
    // server/plugins/workbench/tests/executor-entry-css-contract.mjs C5）。
    // 故：目标图标不可见时**先展开收纳位再找一次**。只认 `data-wb-more-views` 属性、
    // 不认文案（展开后 title 会切成 "Fewer views"），且仅在未展开态点击——避免把
    // 后续视图调用变成「收起」。
    const exp = page.locator(".wb-view-icon[data-wb-more-views]").first();
    if (await exp.count().catch(() => 0)) {
      const expTitle = await exp.getAttribute("title").catch(() => "");
      if (expTitle === "More views") {
        expanderTried = true;
        await forceClick(exp).catch(() => {});
        await page.waitForTimeout(200);
        try {
          await icon.waitFor({ state: "visible", timeout: 5000 });
        } catch { /* 落到下面统一报错（诊断里带上「已展开过」这一事实） */ }
      }
    }
    if (!(await icon.isVisible().catch(() => false))) {
      const present = await page.evaluate(() => [...new Set([...document.querySelectorAll(".wb-view-icon")]
        .map((e) => e.getAttribute("title")).filter(Boolean))]).catch(() => []);
      throw new Error(`侧栏视图图标不可见（[title="${title}"]）——工单台插件未挂载、侧栏收起，`
        + `或被收纳在「More views」展开位内/图标 title 已改名`
        + (expanderTried ? "（已尝试展开「More views」收纳位）" : "")
        + `（DOM 实有：${present.length ? present.join(",") : "无 .wb-view-icon"}）`);
    }
  }
  await forceClick(icon);
  if (waitSelector) {
    try {
      await page.waitForSelector(waitSelector, { timeout: waitMs });
    } catch {
      throw new Error(`点击「${title}」后未出现 ${waitSelector}（视图未切换或数据为空）`);
    }
  }
  // 持续轮询台面永不落 idle（KI-156）：settle 用 domcontentloaded，真实就绪由上方的元素 waitFor 承担
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  return `[title="${title}"]`;
}

/** 具名跳过（t261005-16，仲裁 gen1 修向 (a)）：数据缺席是隔离台/新家的**合法状态**
 * （新家零票零立项，fixture 注入又是 opt-in、生产 ui_evidence 通路恒无 fixture），
 * 不是渲染故障——视图据此走「具名跳过」：不截图、不记失败、不计入退出码，但必须
 * 具名可读（证据闸口径：缺证据要具名，不许静默）。渲染/断言类失败仍走 failures→exit 1。 */
export class SkipView extends Error {}

/** 新建工单弹层打开态（只开不提交——只读红线降级口径）。需先切到立项单视图且
 * 至少有一个立项可进详情；链路任一步不可达即报错（尽力视图，不阻断其余）。
 * 立项单列表为空 = 新家合法状态 → SkipView 具名跳过（t261005-16）。
 *
 * 按钮文案真源=epics.tsx:459（宿主令 260925 英文化后＝「＋ New Ticket」，旧文案
 * 「＋ 新建工单」随 t260926 批退役；同批 integration/t260907-08 的同类锚已改）。 */
async function openNewTicketModal(page) {
  await openView(page, "Epics", ".wb-ep-root");
  const chip = page.locator(".wb-ep-code").first();
  try {
    await chip.waitFor({ state: "visible", timeout: 5000 });
  } catch {
    throw new SkipView("立项单列表为空（.wb-ep-code 无行）——新家/隔离台零票零立项的合法状态，数据缺席具名跳过（非渲染故障）");
  }
  await forceClick(chip);
  const btn = page.locator(".wb-ep-btn-green", { hasText: "New Ticket" }).first();
  try {
    await btn.waitFor({ state: "visible", timeout: 5000 });
  } catch {
    const labels = await page.locator(".wb-ep-btn-green").allInnerTexts().catch(() => []);
    throw new Error(`立项详情未出现「＋ New Ticket」按钮（.wb-ep-btn-green）`
      + `——按钮文案可能已改名（DOM 实有：${labels.length ? labels.map((s) => s.trim()).join(" | ") : "无 .wb-ep-btn-green"}）`);
  }
  await forceClick(btn);
  try {
    await page.waitForSelector(".wb-ep-modal", { timeout: 5000 });
  } catch {
    throw new Error("点击「＋ New Ticket」后弹层未出现（.wb-ep-modal）");
  }
  return "立项详情 → ＋ New Ticket（只开不提交）";
}

// 健全性断言（t260829-01 建；t260831-02 修正 refresh 假阳性）：多张截图若字节级
// 相同 = 导航没生效的同帧假验收，大声报错退出非 0。例外：console-refresh.png
// **不在 pairwise 袋里**——refresh 视图的回归语义是「刷新回得去」，reload 后回到
// default 同款首页、字节相同是正确行为（首页确定性渲染时更然），旧闸把它判死是
// 假阳性（票 t260831-02 实锤）。它的专属断言在 main 的
// 刷新回归段：存在、非空白，回得去时与 default 一致（只加分不拦路）。
const REFRESH_SHOT = "console-refresh.png";
// sessions 视图是「断言视图」：不导航，DOM 断言在视图函数内完成——截图与 default
// 同帧是正确行为（票 t260831-02 实锤判明），摘出 pairwise 袋。
const SESSIONS_SHOT = "console-sessions.png";
async function assertDistinct(shots) {
  const { createHash } = await import("node:crypto");
  const seen = new Map();
  for (const p of shots) {
    if (path.basename(p) === REFRESH_SHOT) continue; // 专属断言单独做，不进 pairwise 袋
    if (path.basename(p) === SESSIONS_SHOT) continue; // 同上（断言视图，同帧正确）
    const h = createHash("sha256").update(await readFile(p)).digest("hex");
    if (seen.has(h)) {
      throw new Error(`截图同帧假成功：${p} 与 ${seen.get(h)} 字节级完全相同（sha256=${h.slice(0, 12)}…），导航/视图变化未生效`);
    }
    seen.set(h, p);
  }
}

// playwright 加载：优先本目录 node_modules；泳道 checkout 不装依赖（t260829-02
// 先例）时退 SANDBAR_PLAYWRIGHT_MODULE 指主树 playwright-core 包目录。selftest 与
// 实拍共用（t260901-03：此前 selftest 不走路径兜底，泳道里 selftest 必红）。
async function loadPlaywright() {
  try {
    return await import("playwright-core");
  } catch (e) {
    const alt = process.env.SANDBAR_PLAYWRIGHT_MODULE;
    if (alt) {
      try {
        const { pathToFileURL } = await import("node:url");
        const mod = await import(pathToFileURL(path.join(alt, "index.js")).href);
        return mod.default ?? mod; // CJS 包经 ESM import 时导出在 default 下
      } catch (e2) {
        throw new Error(`playwright-core 加载失败（${alt}）：${e2.message}`);
      }
    }
    throw new Error(`playwright-core 未安装：${e.message}（先在 server/ui-check/ 下 npm install，或由 capture-lane 传 SANDBAR_PLAYWRIGHT_MODULE）`);
  }
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(`[capture] 参数错误：${e.message}`);
    console.error("用法：node capture.mjs --url <console> --out <dir> [--selftest]");
    process.exit(2);
  }
  const url = args.url || process.env.SANDBAR_CONSOLE_URL || "http://127.0.0.1:3099";
  const timeoutMs = Number(process.env.SANDBAR_UI_CAPTURE_TIMEOUT_MS || 60000);
  if (!args.out) {
    console.error("[capture] 缺 --out <dir>（截图输出目录）");
    process.exit(2);
  }
  if (existsSync(args.out) && !statSync(args.out).isDirectory()) {
    console.error(`[capture] --out 不是目录：${args.out}`);
    process.exit(2);
  }
  await mkdir(args.out, { recursive: true });

  // ── 状态注入门旗与联锁（t260901-24 R1①/R2）──
  // 双通路归一：--fixtures 旗 / env SANDBAR_UI_CAPTURE_FIXTURES=1 等价（与 --allow-seed
  // 的旗/env 双通路同款）。联锁：fixtureMode 必须与 allowSeed（旗/env 归一）同现——
  // 注入仅隔离台路径合法，直连真生产台带注入=把假票注进真台，退出 2 人话拒跑。
  const allowSeed = args.allowSeed || process.env.SANDBAR_UI_CAPTURE_ALLOW_SEED === "1";
  // 裸 --fixtures（旗后不带目录值 → 空串）按「用缺省 ui-check/fixtures 包」处理，
  // 不静默关闸——真拍实测空串曾 falsy 掉整个注入（t260901-24）。
  const fixtureFlag = args.fixtures === null ? null : (args.fixtures || "@default");
  const fixtureMode = fixtureFlag !== null || process.env.SANDBAR_UI_CAPTURE_FIXTURES === "1";
  const fixtureManifest = [];
  const isFixtureView = (file) => file === "console-approval.png" || file === "console-lane-parallel.png";

  // 视图清单（声明式；见文件头注释）。run 返回锚点说明；抛错=该视图失败。
  const VIEWS = [
    // t260910-05：板面条目=导出数组面 BOARD_VIEWS 的同一条目对象（P1 接线锁——
    // selftest 校验 run 身份相等，解绑回裸 openView = selftest 红 + 场景红）。
    { ...BOARD_VIEWS.find((v) => v.file === "console-board.png") },
    { file: "console-epics.png", title: "立项单列表",
      run: (page) => openView(page, "Epics", ".wb-ep-root") },
    { file: "console-new-ticket.png", title: "新建工单弹层打开态",
      run: (page) => openNewTicketModal(page) },
    { file: "console-sessions.png", title: "项目会话区行（票② R8 改锚）",
      run: async (page) => {
        const entry = page.locator("[data-wb-psess-row]").first();
        await entry.waitFor({ state: "visible", timeout: 8000 });
        // 票② R8 口径反转：顶部行入口与样式族必须不在场（t260904-05 已退役）
        const stale = await page.locator(".wb-sessTop, [data-wb-session-entry]").count();
        if (stale > 0) throw new Error(`顶部会话入口残留 ${stale} 个（票② R8 应已退役）`);
        return "项目会话区（[data-wb-psess-row] 可见；顶部行不在场，未点击）";
      } },
    // t260907-05 命名迁移验收面：插件按新包名经农场新链装载的视图证据——
    // 文档=workbench 插件 DocsSection；模型路由=providers 插件（独立包，
    // 能渲染=农场 sandbar-providers 链解析通了）。
    { file: "console-docs.png", title: "文档视图（workbench 插件 DocsSection）",
      run: (page) => openView(page, "Docs", ".wb-doc-root") },
    { file: "console-providers.png", title: "模型路由视图（providers 插件经农场新链装载证明）",
      run: (page) => openView(page, "Model Routes", ".syp-root") },
  ];

  // fixture 态专属视图（t260901-24）：仅注入模式追加进 VIEWS；缺省清单逐字节不变
  // （非 fixture 模式这两张根本不存在，不是「跳过」）。断言口径（方案 R6）：锚不在场
  // 即 loud 失败，不静默出图。
  if (fixtureMode) {
    VIEWS.push(
      {
        file: "console-approval.png", title: "审批抽屉（fixture T-FIX-A awaiting-human）",
        run: async (page) => {
          await openView(page, "Tickets");
          // 行锚=列表 v5 平铺行卡 .wb-card（原表格行 tr.wb-row 随 v5 改版退役）：
          // 票 T-FIX-A stage_state=awaiting-human ⇒ deriveTicketState→'waiting'
          // （ticket-list-model.ts:75），故 data-state 取 waiting 而非 stage_state 原值。
          const row = page.locator('.wb-card[data-state="waiting"]', { hasText: "T-FIX-A" }).first();
          try {
            await row.waitFor({ state: "visible", timeout: 8000 });
          } catch {
            throw new Error("列表未见 T-FIX-A 行（.wb-card[data-state=waiting]，票 T-FIX-A 为 awaiting-human ⇒ waiting）——fixture 注入未生效或 /tickets 未被拦截（查 fixture-manifest.json）");
          }
          await forceClick(row);
          const step = page.locator('.wb-d2-step[data-s="awaiting-human"]').first();
          try {
            await step.waitFor({ state: "visible", timeout: 8000 });
          } catch {
            throw new Error("详情抽屉未见 awaiting-human 步（.wb-d2-step[data-s=awaiting-human] ✋）——抽屉未开或 fixture detail 未驱动推导");
          }
          return "T-FIX-A 行（awaiting-human，审批→推进键在场）→ 详情抽屉 ✋ 步锚（只看不批，不点任何签字/打回提交）";
        },
      },
      {
        file: "console-lane-parallel.png", title: "泳道并行态（fixture T-FIX-B 双 ▶）",
        run: async (page) => {
          // 先回干净首页再进（上一个视图开着详情抽屉，防列表被抽屉遮挡）
          await gotoConsole(page, url, timeoutMs).catch(() => {});
          await openView(page, "Tickets");
          const row = page.locator(".wb-card", { hasText: "T-FIX-B" }).first();
          try {
            await row.waitFor({ state: "visible", timeout: 8000 });
          } catch {
            throw new Error("列表未见 T-FIX-B 行——fixture 注入未生效或 /tickets 未被拦截（查 fixture-manifest.json）");
          }
          await forceClick(row);
          try {
            await page.waitForFunction(
              () => document.querySelectorAll('.wb-d2-step[data-s="running"]').length >= 2,
              null, { timeout: 8000 },
            );
          } catch {
            throw new Error("详情步进条未见 ≥2 个 ▶（.wb-d2-step[data-s=running]）——fixture timeline 双 running 未驱动 lane-states 规则 4");
          }
          const par = await page.locator(".wb-d2-par").count();
          if (par < 2) {
            throw new Error(`并行分叉徽标 .wb-d2-par 仅 ${par} 个（期望 ≥2）——活跃步数组未成立，泳道并行态证据不成立`);
          }
          return "T-FIX-B 详情步进条双 ▶（implement ∥ design_integration_tests，.wb-d2-par ≥2）";
        },
      },
    );
  }

  if (args.selftest) {
    // 干跑：不起浏览器。校验 playwright 依赖可加载 + 参数/env 合法 + 输出目录可写。
    try {
      await loadPlaywright();
    } catch (e) {
      console.error(`[capture] selftest 红：${e.message}`);
      process.exit(3);
    }
    // 板面就绪断言接线身份锁（t260910-05 P1，行为锁的自检半）：VIEWS 板面条目必须
    // 引用导出数组面 BOARD_VIEWS 同一条目的同一 run 函数对象——被解绑回裸
    // openView 时身份不等，selftest 红（闸上红绿半=sc_capture_board_assert 桩驱动
    // 导出条目）。
    const boardExport = BOARD_VIEWS.find((v) => v.file === "console-board.png");
    const boardEntry = VIEWS.find((v) => v.file === "console-board.png");
    if (!boardExport || !boardEntry || boardEntry.run !== boardExport.run) {
      console.error("[capture] selftest 红：VIEWS 板面条目未引用导出条目 BOARD_VIEWS 的同一 run（接线解绑，t260910-05 P1）");
      process.exit(3);
    }
    for (const e of BOARD_VIEWS) {
      if (typeof e.run !== "function" || !e.file.startsWith("console-board")) {
        console.error("[capture] selftest 红：BOARD_VIEWS 条目缺 run/file（导出面形状漂移）");
        process.exit(3);
      }
    }
    for (const e of BOARD_VIEWS.filter((v) => v.scheme)) {
      if (typeof e.scheme !== "string" || !e.file.startsWith("console-board-")) {
        console.error("[capture] selftest 红：BOARD_VIEWS 深浅外观条目缺 scheme（导出面形状漂移）");
        process.exit(3);
      }
    }
    // 预算解析三态（纯函数，C3）：合法透传 / 畸形回落缺省置 defaulted。
    const budOk = resolveBoardBudgetMs("50");
    const budBad = resolveBoardBudgetMs("abc");
    if (budOk.ms !== 50 || budOk.defaulted || budBad.ms !== BOARD_BUDGET_DEFAULT_MS || !budBad.defaulted) {
      console.error("[capture] selftest 红：SANDBAR_UI_CAPTURE_BOARD_MS 解析三态不符（畸形须回落缺省并置 defaulted）");
      process.exit(3);
    }
    const probe = path.join(args.out, ".selftest-probe");
    await writeFile(probe, "ok");
    // 具名跳过机制形状锁（t261005-16）：SkipView 是 Error 子类（视图循环按
    // instanceof 分流：跳过不进 failures、不计退出码），导出面在位供场景/审读用。
    if (!(SkipView.prototype instanceof Error)) {
      console.error("[capture] selftest 红：SkipView 不是 Error 子类（具名跳过分流失据，t261005-16）");
      process.exit(3);
    }
    console.log(`[capture] selftest 绿：依赖在位，url=${url}，out=${args.out} 可写，视图数=${VIEWS.length + 3}，板面就绪断言接线身份锁绿（t260910-05），具名跳过机制形状绿（t261005-16）`);
    process.exit(0);
  }

  // ── 联锁拒跑 + fixture 素材加载（真跑路径；selftest 干跑已在上方分支退出，
  // t04 合同：干跑不经 fixture 目录在位性，参数层放行语义）──
  if (fixtureMode && !allowSeed) {
    console.error("[capture] 拒跑：状态注入（--fixtures / SANDBAR_UI_CAPTURE_FIXTURES=1）仅隔离台路径可用" +
      "（须与 --allow-seed 或 SANDBAR_UI_CAPTURE_ALLOW_SEED=1 同现）。直连真控制台注入假票=污染真数据，绝不允许。");
    process.exit(2);
  }
  let fixtures = null;
  if (fixtureMode) {
    const fixturesDir = fixtureFlag === "@default"
      ? path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures") : fixtureFlag;
    try {
      fixtures = loadFixtures(fixturesDir);
    } catch (e) {
      console.error(`[capture] fixture 加载拒跑（证据素材缺/畸形宁可拒跑不静默降级）：${e.message}`);
      process.exit(2);
    }
    console.log(`[capture] FIXTURE-MODE 已开启（注入目录 ${fixturesDir}）——` +
      "wf 读端点将回 fixture 票（T-FIX-A awaiting-human / T-FIX-B 并行），截图为注入态证据，审读以 fixture-manifest.json 为准");
  }

  let playwright;
  try {
    playwright = await loadPlaywright();
  } catch (e) {
    console.error(`[capture] ${e.message}`);
    process.exit(3);
  }

  const browser = await launchBrowser(playwright);
  // exit 钩子兜底：任何路径退出都尝试关浏览器，不留孤儿进程
  let closed = false;
  const closeBrowser = () => { if (!closed) { closed = true; browser.close().catch(() => {}); } };
  process.on("exit", closeBrowser);
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => { closeBrowser(); process.exit(130); });
  }

  const shots = [];
  const failures = [];
  const skipped = [];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    // charter 豁免门旗（workbench session-entry.tsx 同源约定）：隔离台无真
    // agent 会话，charter prompt 永远挂 machineBusy、composer 恒 readOnly，
    // 种子消息写不进去——预置门旗让注入跳过，由种子消息自己驱动 active。
    // 必须在首个 goto 之前注入（addInitScript 时序）。
    if (args.allowSeed) {
      await page.addInitScript(() => {
        try { localStorage.setItem("sandbar-ui-capture-skip-charter", "1"); } catch { /* 尽力而为 */ }
      });
    }
    // fixture 路由 install（t260901-24 R5）：必须在首个 page.goto 之前——否则首屏
    // /tickets 已打到真端点（空家=空列表）。单 handler 内部经 routeDecision 按
    // method+pathname 分派（Playwright 路由 LIFO 匹配的坑从结构上绕开，取舍非遗漏）。
    if (fixtureMode) {
      await page.route("**/api/wf/**", (route) => {
        const req = route.request();
        const d = routeDecision(req.method(), req.url(), fixtures);
        if (d.fulfill) {
          if (fixtureManifest.length < 500) {
            fixtureManifest.push({ url: req.url(), fixture: d.fixture });
          }
          return route.fulfill(d.fulfill);
        }
        return route.continue();
      });
    }
    const shoot = async (name) => {
      const p = path.join(args.out, name);
      await page.screenshot({ path: p, fullPage: true });
      shots.push(p);
      console.log(`[capture] ${p}`);
    };
    // hero 落地页（必成视图——失败即整体失败）
    try {
      await gotoConsole(page, url, timeoutMs);
      // 首屏就绪：出厂 notice 弹出则先关（盖住后续所有视图，见 dismissNotice 注释）
      const dismissed = await dismissNotice(page);
      if (dismissed) console.log(`[capture]   ${dismissed}`);
      await shoot("console-default.png");
    } catch (e) {
      console.error(`[capture] hero 落地页截图失败（必成视图）：${e.message}`);
      process.exit(1);
    }
    // 尽力视图：逐个试，单视图失败记失败不阻断
    for (const v of VIEWS) {
      try {
        await dismissNotice(page); // notice 若再弹（如 reload 后）先关
        const anchor = await v.run(page);
        await shoot(v.file);
        console.log(`[capture]   锚=${anchor}`);
        // 弹层视图截完即复位（防污染后续视图）
        if (v.file === "console-new-ticket.png") {
          await page.keyboard.press("Escape").catch(() => {});
          await gotoConsole(page, url, timeoutMs).catch(() => {});
        }
      } catch (e) {
        // 具名跳过（t261005-16）：SkipView=数据缺席的合法台面状态——不截图、
        // 不记失败、不计退出码，但必须具名可读（缺证据要具名，不许静默）。
        if (e instanceof SkipView) {
          skipped.push(`${v.title}：${e.message}`);
          console.log(`[capture]   视图跳过（具名，数据缺席，非失败）：${v.title}——${e.message}`);
          continue;
        }
        // R6 口径（t260901-24）：fixture 视图失败走既有 best-effort 通路（整 run 退出码 1），
        // 但失败行带 FIXTURE-MODE 前缀——审读人据此读作「注入/fixture 数据问题，修 fixture
        // 重拍」，而非「渲染故障」；worker 侧软失败不拦主链语义不变。
        const label = fixtureMode && isFixtureView(v.file)
          ? `状态注入视图失败（FIXTURE-MODE）：${v.title}` : v.title;
        failures.push(`${label}：${e.message}`);
        console.error(`[capture] 视图失败（尽力视图，不阻断）：${label}——${e.message}`);
      }
    }
    // 刷新回归（reload 后再截一张）+ 专属断言（t260831-02）：存在、非空白；
    // 与 default 字节一致=「回得去」的正向证据（一致只加分不拦路，避免把
    // 首页的良性动态渲染误判成失败——同帧闸假阳性的教训同源）。
    try {
      await page.reload({ waitUntil: "domcontentloaded", timeout: timeoutMs });
      await page.waitForTimeout(800);
      await dismissNotice(page); // 全新 home 下 reload 后 notice 可能再弹
      await shoot("console-refresh.png");
      const { createHash } = await import("node:crypto");
      const rp = path.join(args.out, "console-refresh.png");
      const st = await (await import("node:fs/promises")).stat(rp);
      if (st.size < 2048) throw new Error(`console-refresh.png 仅 ${st.size} 字节（疑似空白页）`);
      const def = path.join(args.out, "console-default.png");
      if (existsSync(def)) {
        const hR = createHash("sha256").update(await readFile(rp)).digest("hex");
        const hD = createHash("sha256").update(await readFile(def)).digest("hex");
        if (hR === hD) console.log("[capture]   刷新回得去：console-refresh ≡ console-default（字节一致）");
        else console.log("[capture]   刷新后与 default 有差异（首页含动态渲染，不判失败，人工看图确认）");
      }
    } catch (e) {
      failures.push(`刷新回归：${e.message}`);
      console.error(`[capture] 视图失败（尽力视图，不阻断）：刷新回归——${e.message}`);
    }
    // 深浅外观证明（t260907-05 验收面③）：主题跟随 prefers-color-scheme
    // （theme.ts 口径），emulateMedia 切换后各拍工单列表一张——改名后的
    // 装载链在两种外观下都成立；拍完恢复仿真（防污染 chat 态）。
    // t260910-05：条目从导出面 BOARD_VIEWS 取（P1 接线锁，同 VIEWS 板面条目）；
    // 外观切换留在主循环，条目只管「导航+就绪断言」（桩 page 无需 emulateMedia）。
    for (const entry of BOARD_VIEWS.filter((v) => v.scheme)) {
      try {
        await page.emulateMedia({ colorScheme: entry.scheme });
        const anchor = await entry.run(page);
        await shoot(entry.file);
        console.log(`[capture]   锚=${anchor}（${entry.scheme} 外观）`);
      } catch (e) {
        failures.push(`外观 ${entry.scheme}：${e.message}`);
        console.error(`[capture] 视图失败（尽力视图，不阻断）：外观 ${entry.scheme}——${e.message}`);
      }
    }
    await page.emulateMedia(null).catch(() => {});
    // chat 态（打开已有会话）
    try {
      const anchor = await navigateToChat(page, args.allowSeed || process.env.SANDBAR_UI_CAPTURE_ALLOW_SEED === "1");
      await page.waitForLoadState("networkidle").catch(() => {});
      // 截后断言（t260901-03 Step ① 双保险）：截图时刻 DOM 必须零 dialog——
      // 有模态在场 = chat 证据被遮挡，按失败记，不静默出图。
      const dialogAtShot = await page.locator('[role="dialog"]').count();
      if (dialogAtShot > 0) throw new Error(`chat 截图时刻仍有 ${dialogAtShot} 个 [role=dialog]（准入模态遮挡证据），按失败处理`);
      await shoot("console-chat.png");
      console.log(`[capture]   锚=${anchor}`);
    } catch (e) {
      failures.push(`chat 态：${e.message}`);
      console.error(`[capture] 视图失败（尽力视图，不阻断）：chat 态——${e.message}`);
    }
    // 健全性闸：任何两张截图字节级相同 → 抛错非 0（防同帧假验收）。
    await assertDistinct(shots);
    console.log("[capture] 健全性断言绿：各视图截图字节级不同");
    await ctx.close();
  } finally {
    closeBrowser();
  }
  if (shots.length === 0) {
    console.error("[capture] 一张截图都没产出");
    process.exit(1);
  }
  if (failures.length > 0) {
    console.error(`[capture] ${failures.length} 个尽力视图失败：\n  - ${failures.join("\n  - ")}`);
    process.exitCode = 1;
  }
  if (skipped.length > 0) {
    // 具名跳过汇总（t261005-16）：数据缺席不进退出码，但证据缺口要可读可审计。
    console.log(`[capture] ${skipped.length} 个视图具名跳过（数据缺席，非失败，不计退出码）：\n  - ${skipped.join("\n  - ")}`);
  }
  // 注入态证据自证（t260901-24 R2）：PNG 无法自标——落 manifest（URL→fixture 映射）
  // 供审读人对照哪些端点被注入。写失败只告警不遮蔽截图结果。
  if (fixtureMode) {
    const mp = path.join(args.out, "fixture-manifest.json");
    try {
      await writeFile(mp, JSON.stringify({
        _fixture: true,
        mode: "FIXTURE-MODE（t260901-24 状态注入；本目录截图含注入态视图，非纯真台实拍）",
        intercepted: fixtureManifest,
      }, null, 1), "utf8");
      console.log(`[capture] FIXTURE-MODE manifest → ${mp}（${fixtureManifest.length} 次拦截）`);
    } catch (e) {
      console.error(`[capture] 警告：fixture-manifest.json 写入失败（证据自证缺失）：${e.message}`);
    }
  }
  console.log(`[capture] 完成：${shots.length} 张 → ${args.out}`);
}

// 仅直接执行（node capture.mjs）时跑 main；被基线 import 复用纯函数
// （validateSeedText / parseLedgerIds / loadFixtures / routeDecision）时零副作用
// （t260901-03、t260901-24）。
import { pathToFileURL, fileURLToPath } from "node:url";
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((e) => {
    console.error(`[capture] 失败：${e && e.stack || e}`);
    process.exit(1);
  });
}
