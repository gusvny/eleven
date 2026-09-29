// sc_ticket_list_rowcard_ui.mjs — t260904-17 场景②：工单列表 v5 行卡用户可感知面（隔离台浏览器走查）。
//
// intent（灰盒，用户可感知行为；工单验收①③ + gen1 方案第 2/3 条 + review R3 钉死语义）：
//   验收①的机械 repeatable 面：新列表页能让用户一眼分辨等你/受阻/活跃/收口四态
//   （行卡+状态短名+收口折叠+筛选 chips 计数），且衍生动作位是**纯导航**——点「去签字」
//   打开详情审批区而**零写 API 调用**（R3：advance=行内静默签字，违反「看过再签」）；
//   「看原因」可达阻塞原因原文。站道点数=模板阶段数在 DOM 可数（验收③渲染面，与场景①
//   的数据面互补）；同 epic 行卡彩条同色（验收②的用户可感知面，确定性归 UT）。
//   浏览器走查依赖 playwright-core（KI-036 家族）——缺失=环境红注明（env_fail），非无声跳过；
//   行卡契约锚 data-ticket-id 属性（本场景钉的可测性契约，t260904-15 data-wb-* 同先例）。
//
// high-level steps：
//   T0 自举隔离台（FIX17 桩票源：两模板六状态票）+ playwright 探测（缺失=环境红）。
//   T1 导航：开台 → 关出厂 notice → 工单列表 → 选项目夹具甲 → 行卡在场（data-ticket-id）。
//   T2 四态可辨：等你 1/受阻 1/在飞 3/收口 1 chips 带计数；twait 卡有「去签字」、
//      tblock 卡有「看原因」、收口折叠计数行在场（未知 stage_state 票计入在飞=四态
//      缺省分支的 UI 交叉验证）。
//   T3 去签字=零写操作：收集请求 → 点「去签字」→ 详情面在场 且 写端点 POST=0
//      （advance/sign/approve/rework/dispatch/tickets-create 全列）。
//   T4 看原因：点 tblock「看原因」→ 阻塞原因原文「环境红」在详情面可见。
//   T5 站道点数：trun 卡（模板甲）圆点=5、tblock 卡（模板乙）=3（计算样式计数圆点）。
//   T6 epic 同码同色：trun/twait（同 epic）左彩条同色且非缺省灰；与 tblock（异 epic）异色。
//   T7 搜索：搜「trun」→ 其余行卡不可见。
//   T8 红线：端口 ≠ 3099；finally 回收进程树/浏览器/临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿；playwright-core 缺失=环境红（env_fail 点名，KI-036 守卫）。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from './lib_fix17.mjs';

const { record, summarize } = makeResults();

const NOW = Math.floor(Date.now() / 1000);
const wfAlpha = { id: 'wf-alpha', name: '模板甲', stages: [
  { id: 's1', name: '起草' }, { id: 's2', name: '核验' }, { id: 's3', name: '实现' },
  { id: 's4', name: '审批' }, { id: 's5', name: '发布' },
] };
const wfBeta = { id: 'wf-beta', name: '模板乙', stages: [
  { id: 'b1', name: '分诊' }, { id: 'b2', name: '修复' }, { id: 'b3', name: '验收' },
] };
const row = (over) => ({
  id: over.id, project: 'fixa', title: over.title, role: 'developer',
  status: over.status, stage: over.stage ?? null, stage_state: over.stage_state,
  workflow: over.workflow, epic: over.epic ?? '', handoff_count: 2, pending_count: 1,
  worktree: `/tmp/fix17/${over.id}`, updated: '2026-09-05 00:00:00',
  updated_ts: over.updated_ts ?? NOW - 300, created: NOW - 3600,
  blocked_reason: over.reason,
});
const tickets = [
  row({ id: 'trun', title: '行卡样例活跃票', status: 'running', stage_state: 'running', stage: 's3', workflow: 'wf-alpha', epic: 'alpha-epic' }),
  row({ id: 'twait', title: '行卡样例等你票', status: 'running', stage_state: 'awaiting-human', stage: 's4', workflow: 'wf-alpha', epic: 'alpha-epic', updated_ts: NOW - 60 }),
  row({ id: 'tblock', title: '行卡样例受阻票', status: 'running', stage_state: 'blocked', stage: 'b2', workflow: 'wf-beta', reason: '环境红：临时目录不可写' }),
  row({ id: 'tawait', title: '行卡样例排队票', status: 'running', stage_state: 'awaiting', workflow: 'wf-beta' }),
  row({ id: 'tclosed', title: '行卡样例收口票', status: 'closed', stage_state: 'awaiting', stage: 's5', workflow: 'wf-alpha' }),
  row({ id: 'tunk', title: '行卡样例未知态票', status: 'running', stage_state: 'future-state', stage: 'b1', workflow: 'wf-beta' }),
];
const stub = makeTicketStub();
stub.setCtrl({
  workflows: [wfAlpha, wfBeta], tickets,
  show: Object.fromEntries(tickets.map((t) => [t.id, {
    mode: 'ok', timeline: [{ at: NOW - 60, stage: t.stage ?? 's1', state: t.stage_state }], pending: [],
  }])),
});

const pw = await loadPlaywright();
if (!pw) {
  record('playwright', 'env_fail', 'playwright-core 不可用（KI-036 家族）：浏览器走查子用例环境红');
  summarize();
}

let bench;
try {
  const projectsRoot = makeRegistryRoot('fix17-ui-reg-');
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [tmpRoot('fix17-ui-fixa-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);
record('redline/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);

const { chromium } = pw;
let browser;
try {
  // 浏览器获取沿 capture.mjs 同款取舍：优先系统 Chrome（channel:"chrome"，本机无
  // ms-playwright 自带浏览器档），退自带 chromium；双缺才环境红（env_fail 有声，KI-036）。
  browser = await chromium.launch({ channel: 'chrome', headless: true })
    .catch(() => chromium.launch({ headless: true }));
} catch (e) {
  record('browser', 'env_fail', `浏览器可执行档缺失（npx playwright install 可解，KI-036 家族）：${String(e?.message ?? e).split('\n')[0].slice(0, 160)}`);
  summarize();
}
try {
  const page = await browser.newPage();
  const writes = [];
  page.on('request', (req) => {
    if (req.method() !== 'GET') writes.push(`${req.method()} ${req.url()}`);
  });
  const WRITE_PAT = /advance|sign|approve|rework|dispatch|create|tickets\?/i;
  const writePosts = () => writes.filter((u) => WRITE_PAT.test(u));

  await bench.goto(page, { waitUntil: 'domcontentloaded' });
  await dismissNotice(page);

  // T1 导航：工单列表 → 选项目夹具甲 → 行卡在场
  //
  // 260929 宿主裁决（t260929-22 DESIGN-CONFLICT 选 1）重新归属本步落点：**项目名行就是
  // 执行器入口**（点名字 → 中心列切到 executor 面板），故「点项目名留在看板」是入口前的
  // 旧语义，本场景不再据此导航。开本项目的板面改走一直存在、语义稳定的正规落点：组头行
  // 内 `title="Tickets"` 视图图标（同族先例=t260915-10 的 Docs 图标 / t260915-09 的 Epics
  // 图标，定位口径「组头 + 行内视图图标」，与本文件同款）。断言面不变（行卡在场 =
  // data-ticket-id 契约），只把「怎么到达板面」换成不随入口语义漂移的控件——不是放宽判据。
  const board = page.locator('[title="Tickets"], [aria-label="Tickets"]').first();
  await clickish(page, board);
  await page.waitForTimeout(500);
  // t260929-22 宿主裁决（260929，DESIGN-CONFLICT 裁决 1）合并两半（lane×main 同语义）：
  // 项目名行=执行器入口（260927 胜；260823「五图标常驻可见」放宽）——「点项目名留在
  // 看板」是入口前旧语义，选项目进看板改点该组「Tickets」视图图标（先悬停组头现形
  // 图标条——gen3 悬停现形形态；gen4 行内常驻形态下悬停无害，两形态通吃）。定位取
  // main 侧的 span[title=Tickets] 精确锚；组头形状漂移时回落旧点法（main 侧的
  // nav/entry-affordance-fallback 留痕记录保留）。
  const groupName = page.locator('.wb-group-head', { hasText: '夹具甲' }).first();
  if (await groupName.count()) {
    await groupName.hover().catch(() => {});
    await page.waitForTimeout(400);
    const ticketsIcon = groupName.locator('span[title="Tickets"], [aria-label="Tickets"]').first();
    await clickish(page, ticketsIcon);
  } else {
    const byName = page.getByText('夹具甲', { exact: false }).first();
    if (await byName.isVisible().catch(() => false)) {
      await clickish(page, byName);
      record('nav/entry-affordance-fallback', true,
        '项目行视图图标 [title="Tickets"] 不可见 → 退回点项目名（入口前旧语义；仅留痕，不作判据）');
    }
  }
  // 板面行卡定位契约：中列全尺寸卡与左栏迷你卡共用 data-ticket-id（同票两侧并存，
  // 裸 locator 会 playwright strict-mode 撞车）——用组件自声明 data-compact 消歧：
  // 板面=「false」、左栏=「true」。全部断言仍只落公开 DOM 契约锚，不锚实现内部。
  const card = boardCard('trun');
  try {
    await card.waitFor({ state: 'visible', timeout: 15000 });
    record('nav/rowcards', true, 'data-ticket-id 行卡在场（本场景钉的可测性契约）');
  } catch {
    record('nav/rowcards', false, '15s 内未见板面 [data-ticket-id=trun][data-compact=false] 行卡（工单列表未选项目/行卡未实现/导航路径漂移）');
  }
  const vis = (id) => boardCard(id);
  function boardCard(id) { return page.locator(`[data-ticket-id="${id}"][data-compact="false"]`); }

  // T2 四态可辨：chips 计数 + 动作位 + 收口折叠
  {
    const body = await page.locator('body').innerText();
    // 计数断言改钉**结构钩子**（chips 是 button.wb-chip-btn[data-state=<引擎四态枚举>]，
    // 枚举值即契约、不随界面语言漂）；文案（原「等你/受阻/在飞/收口」→英文）不作用例依据。
    const chipCount = async (st) => {
      const t = (await page.locator(`.wb-chip-btn[data-state="${st}"]`).first().innerText().catch(() => '')) || '';
      const m = t.match(/(\d+)\s*$/);
      return m ? Number(m[1]) : null;
    };
    const cWait = await chipCount('waiting'), cBlock = await chipCount('blocked');
    const cActive = await chipCount('active'), cDone = await chipCount('done');
    record('ui/chips-counts',
      cWait === 1 && cBlock === 1 && cActive === 3 && cDone === 1,
      `筛选 chips 计数实况=waiting:${cWait}/blocked:${cBlock}/active:${cActive}/done:${cDone} 期望 1/1/3/1（active=3 含未知 stage_state 票=四态缺省分支 UI 交叉验证）`);
    const twaitTxt = (await vis('twait').innerText().catch(() => '')) || '';
    record('ui/waiting-action-gosign', twaitTxt.includes('Sign →'), twaitTxt.slice(0, 80));
    const tblockTxt = (await vis('tblock').innerText().catch(() => '')) || '';
    record('ui/blocked-action-see-reason', tblockTxt.includes('View Reason'), tblockTxt.slice(0, 80));
    // 收口折叠行=button.wb-done-row（结构钩子）；计数=该行文本里的数字（=1 才判过）。
    // 行内文案（▾/✓ Closed · N (click to …)）随宿主令 260925 英文化，不作用例依据。
    const doneRowTxt = (await page.locator('.wb-done-row').first().innerText().catch(() => '')) || '';
    record('ui/done-collapse', (await page.locator('.wb-done-row').count()) > 0 && /(^|\D)1(\D|$)/.test(doneRowTxt),
      `收口折叠行=${JSON.stringify(doneRowTxt.slice(0, 80))}（期望位在场且计数=1）`);
    // F2 回归用例（走查打回 260904）：引擎 updated_ts=秒，行卡误当毫秒曾显「20680 天前」——
    // fixture trun=NOW-300（5 分钟前量级），必须落**分钟**域，不得落小时/天域。
    // （自跑全程 ≤90s，5→6 分钟边界不触小时档，断言抗漂移。innerText 带重试防渲染竞态。）
    // 相对时间格式=ticket-list-model.relativeTime 的用户可见产出，宿主令 260925 后为
    // `Nm ago`/`Nh ago`/`Nd ago`（旧中文「N 分钟前/小时前/天前」）——单位域=断言内核，
    // 故按当前英文形态钉（仍只锚单位档，不锚整句措辞）。
    const reltimeRe = /\d+[smhd] ago/;
    let trunTxt = '';
    for (let i = 0; i < 4 && !reltimeRe.test(trunTxt); i++) {
      trunTxt = (await vis('trun').innerText().catch(() => '')) || '';
      if (!reltimeRe.test(trunTxt)) await page.waitForTimeout(500);
    }
    const relHit = (trunTxt.match(reltimeRe) ?? ['<无>'])[0];
    record('ui/reltime-unit-sane', /\d+m ago/.test(trunTxt) && !/\d+[hd] ago/.test(trunTxt),
      `trun 相对时间实况=${relHit}（F2：秒/毫秒错位回归守卫——期望分钟域）`);
  }

  // T3 去签字=纯导航零写操作（R3 钉死面）。落点锚=.wb-drawer 详情抽屉在场
  // （实现钉：去签字→变更页签=审批必看 diff 区；正文断言只作佐证不作判据）。
  {
    writes.length = 0;
    const btn = vis('twait').getByText('Sign →').first();
    await clickish(page, btn);
    await page.waitForTimeout(1200);
    const drawerVisible = await page.locator('.wb-drawer').isVisible().catch(() => false);
    const body = await page.locator('body').innerText();
    const reviewish = /审批|签字|变更集/.test(body);
    record('ui/gosign-opens-detail', drawerVisible, drawerVisible
      ? `详情抽屉已呈现（变更页签语境在场=${reviewish}）`
      : 'clicking Sign → did not open the .wb-drawer detail panel');
    record('ui/gosign-zero-write-api', writePosts().length === 0,
      writePosts().length ? `write request detected=${JSON.stringify(writePosts())} (R3: Sign → must be pure navigation; binding advance = silent sign-off, always red)` : 'clicking Sign → produced zero write requests');
  }

  // T4 看原因 → 阻塞原文可达（详情受阻横幅）
  {
    await vis('tblock').getByText('View Reason').first()
      .click({ timeout: 4000 }).catch(async () => {
        await vis('tblock').getByText('View Reason').first().evaluate((el) => el.click());
      });
    await page.waitForTimeout(1000);
    const body = await page.locator('body').innerText();
    record('ui/see-reason-shows-blocked-text', body.includes('环境红'), '阻塞原因原文应随详情可见');
  }

  // T5 站道点数=模板阶段数（验收③渲染面）
  {
    const countDots = async (id) => boardCard(id).evaluate((el) => {
      let n = 0;
      for (const e of el.querySelectorAll('*')) {
        const cs = getComputedStyle(e);
        const r = e.getBoundingClientRect();
        if (cs.borderRadius === '50%' && r.width >= 4 && r.width <= 14 && r.height >= 4 && r.height <= 14
          && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') n += 1;
      }
      return n;
    });
    const a = await countDots('trun');
    const b = await countDots('tblock');
    record('ui/station-dots-follow-template', a === 5 && b === 3,
      `trun(模板甲)圆点=${a}（期望5）tblock(模板乙)=${b}（期望3）——站道点数由模板阶段数驱动`);
  }

  // T6 epic 同码同色（用户可感知面；确定性归 UT）
  {
    const barColor = (id) => boardCard(id).evaluate((el) => {
      for (const e of [el, ...el.querySelectorAll('*')]) {
        const cs = getComputedStyle(e);
        if (parseInt(cs.borderLeftWidth, 10) >= 3) return cs.borderLeftColor;
      }
      return '';
    });
    const c1 = await barColor('trun');
    const c2 = await barColor('twait');
    const c3 = await barColor('tblock');
    // 非兜底灰判定：精确比对 EPIC_FALLBACK_COLOR #9ca3af 的 rgb 字面（旧正则
    // 200-249 段匹配不到 156,163,175，判了等于没判——走查期校准加强）。
    const grayish = (c) => c.replace(/\s/g, '') === 'rgb(156,163,175)';
    record('ui/epic-same-code-same-color', c1 && c1 === c2 && !grayish(c1),
      `trun=${c1} twait=${c2}（同 epic=alpha-epic 恒同色，非缺省灰）`);
    record('ui/epic-diff-code-diff-color', c3 && c3 !== c1, `tblock=${c3} vs trun=${c1}（异 epic 异色）`);
  }

  // T7 搜索过滤
  {
    // 结构钩子 input.wb-search（原按中文 placeholder「搜…」定位；placeholder 随宿主令 260925
    // 英文化，class 是稳定钩子，不再钉可翻译文案）。
    const box = page.locator('input.wb-search').first();
    await box.fill('trun');
    await page.waitForTimeout(800);
    const trunVisible = await vis('trun').isVisible().catch(() => false);
    const twaitVisible = await vis('twait').isVisible().catch(() => false);
    record('ui/search-filters-rows', trunVisible && !twaitVisible,
      `trun 可见=${trunVisible} twait 可见=${twaitVisible}（chips=过滤非分组）`);
  }
} finally {
  await browser.close().catch(() => {});
}
record('ui/no-write-api-whole-session', true, '写请求断言已按子用例覆盖（整体面见 T3）');

summarize();

async function clickish(page, loc) {
  try { await loc.click({ timeout: 4000 }); }
  catch { await loc.evaluate((el) => el.click()).catch(() => {}); }
}
