// sc_ticket_list_http_contract.mjs — t260904-17 场景①：工单列表 v5 重做的 host 契约面（API，无浏览器）。
//
// intent（灰盒，用户可感知行为；工单验收①-⑥ + gen1 方案第 5/7 条 + review R5/C 条件项）：
//   用户在新工单列表看到的每一行，其数据都来自 GET /wf/tickets——本场景守该路由此票
//   改造后的三层承诺：
//   (1) 列表主数据快而自洽：主响应不被逐票 show 拖住（主请求窗口内零 show 调用——
//       「主数据先行」契约；现状=awaiting-human 逐票 show 阻塞 sendJson，扩 N 倍即
//       KI-003/029 查询饿死族加重面），且四态推导所需字段（status/stage_state/epic/
//       updated_ts/workflow）逐行齐备（验收①的数据面）。
//   (2) 进展 enrichment 有预算：enrich 形状钉为 GET /wf/tickets?project=<key>&enrich=progress
//       [&ids=a,b]（gen1 方案「实现期择一」的二选一裁定，场景与登记 intent 双处钉死）——
//       每票 show 短超时（慢票不拖死 enrich 响应）、并发有上限（轨迹面观测 ≤4）、
//       单票失败/畸形 timeline=该票缺 progress 而整体 200（降级不撒谎：progress 里
//       不得出现错误文案字样，KI-018「错误文案当数据写」根除面）。
//   (3) 模板拓扑与 epic 透传（验收③②的数据面）：≥2 个不同阶段数的模板在响应 workflows
//       里可辨（站道点数=stages.length 的消费源）；epic 独立字段透传（含空 epic）。
//   另守路由壳回归：缺 project/未知 project=400 点名错误、未知方法=405——S2 重写不得破壳
//   （KI-025 kind 不谎报口径延续）。
//   与 UT（server/dsh/workbench/tests/t260904-17-*，四态真值表/哈希色确定性/守卫）intent
//   不同面：本条只守 HTTP 契约，不 import 任何 src/client 模块（KI-023 债族不新增）。
//
// high-level steps：
//   T0 自举隔离台（临时注册表根 + FIX17 桩 python3：fixture 两模板五状态票；Temporal=死端口）。
//   T1 路由壳回归：缺 project=400 点名 / 未知 project=400 / PUT=405。
//   T2 主列表：200 快返回；主请求窗口内 show 调用=0、list 调用≥1（轨迹面）；四态字段逐行齐备。
//   T3 拓扑+epic 透传：响应 workflows 恰两模板且 stages.length 互异（5 vs 3）；票 workflow∈拓扑；
//      epic 独立字段（有码/空串）透传。
//   T4 enrich 默认ctrl：可显票有 progress{stage,state,at}、失败票缺 progress、整体 200、
//      progress 值零错误文案字样。
//   T5 enrich 畸形 timeline：show 回畸形 timeline（缺 stage/state 条目）→ 该票 progress 缺省不炸。
//   T6 enrich 预算：全票 show 延迟 8s → enrich 有界返回（<12s；无超时实现=8s/票×批必红）、
//      并发峰值≤4（轨迹面）、全票降级、仍 200。
//   T7 红线：端口 ≠ 3099/7233；finally 必回收 boot 进程树与临时目录。
//
// 执行契约：stdout 末行 SUMMARY pass=<n> skip=<m> fail=<k>；隔离台依赖缺失（dsh 不可用/
//   profile 依赖缺失）=干净 SKIP（exit 0 注明原因）；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, api, makeResults,
} from './lib_fix17.mjs';

const { record, summarize } = makeResults();

// ---- fixture：两模板（5 段/3 段）× 六状态票 ----
const NOW = Math.floor(Date.now() / 1000);
const wfAlpha = { id: 'wf-alpha', name: '模板甲', stages: [
  { id: 's1', name: '起草' }, { id: 's2', name: '核验' }, { id: 's3', name: '实现' },
  { id: 's4', name: '审批' }, { id: 's5', name: '发布' },
] };
const wfBeta = { id: 'wf-beta', name: '模板乙', stages: [
  { id: 'b1', name: '分诊' }, { id: 'b2', name: '修复' }, { id: 'b3', name: '验收' },
] };
const row = (over) => ({
  id: over.id, project: 'fixa', title: over.title ?? '人话短题', role: 'developer',
  status: over.status, stage: over.stage ?? null, stage_state: over.stage_state,
  workflow: over.workflow, epic: over.epic ?? '', handoff_count: 1, pending_count: 0,
  worktree: `/tmp/fix17/${over.id}`, updated: '2026-09-05 00:00:00',
  updated_ts: over.updated_ts ?? NOW - 300, created: NOW - 3600,
});
const tickets = [
  row({ id: 'trun', status: 'running', stage_state: 'running', stage: 's3', workflow: 'wf-alpha', epic: 'alpha-epic' }),
  row({ id: 'twait', status: 'running', stage_state: 'awaiting-human', stage: 's4', workflow: 'wf-alpha', epic: 'alpha-epic', updated_ts: NOW - 60 }),
  row({ id: 'tblock', status: 'running', stage_state: 'blocked', stage: 'b2', workflow: 'wf-beta', epic: '' }),
  row({ id: 'tawait', status: 'running', stage_state: 'awaiting', stage: null, workflow: 'wf-beta' }),
  row({ id: 'tclosed', status: 'closed', stage_state: 'awaiting', stage: 's5', workflow: 'wf-alpha' }),
  row({ id: 'tunk', status: 'running', stage_state: 'future-state', stage: 'b1', workflow: 'wf-beta' }),
];
const showOk = (timeline) => ({ mode: 'ok', timeline });
const defaultShow = {
  trun: showOk([{ at: NOW - 400, stage: 's2', state: 'running' }, { at: NOW - 100, stage: 's3', state: 'running' }]),
  twait: showOk([{ at: NOW - 90, stage: 's4', state: 'running' }, { at: NOW - 50, stage: 's4', state: 'awaiting-human' }]),
  tblock: showOk([{ at: NOW - 80, stage: 'b2', state: 'running' }, { at: NOW - 40, stage: 'b2', state: 'blocked' }]),
  tawait: { mode: 'fail' },
  tunk: { mode: 'fail' },
  tclosed: { mode: 'fail' },
};

const stub = makeTicketStub();
stub.setCtrl({ workflows: [wfAlpha, wfBeta], tickets, show: defaultShow });

let bench;
try {
  const projectsRoot = makeRegistryRoot('fix17-api-reg-');
  writeProjectEntry(projectsRoot, 'fixa', '夹具甲', [tmpRoot('fix17-api-fixa-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失（dsh/profile 依赖）：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
const B = bench.base;
record('bench/boot', 'pass', B);

// 3099/7233 红线：隔离台端口必须为随机高端口
record('redline/ports', bench.port !== 3099 && bench.port !== 7233,
  `port=${bench.port}（禁 3099 用户操作面/7233 真源面）`);

const LIST = (q = '') => `/suyou-workbench/api/wf/tickets?project=fixa${q}`;
const errText = (r) => (typeof r.body === 'string' ? r.body : JSON.stringify(r.body?.error ?? r.body));

// ---- T1 路由壳回归（S2 重写不得破壳） ----
{
  const r1 = await api(B, 'GET', '/suyou-workbench/api/wf/tickets');
  record('shell/missing-project-400', r1.status === 400 && /project/i.test(errText(r1)),
    `status=${r1.status} err=${errText(r1).slice(0, 120)}`);
  const r2 = await api(B, 'GET', '/suyou-workbench/api/wf/tickets?project=nosuch');
  record('shell/unknown-project-400', r2.status === 400,
    `status=${r2.status} err=${errText(r2).slice(0, 120)}`);
  const r3 = await api(B, 'PUT', LIST());
  record('shell/method-405', r3.status === 405, `status=${r3.status}`);
}

// ---- T2 主列表：快、零 show、四态字段齐备 ----
{
  const t0 = Date.now();
  const size0 = stub.traceSizeAt();
  const r = await api(B, 'GET', LIST());
  const dt = Date.now() - t0;
  record('main/200', r.status === 200, `status=${r.status} ${String(errText(r)).slice(0, 120)}`);
  const body = r.body?.result ?? r.body ?? {};
  const ticketsOut = body.tickets ?? [];
  record('main/rows-all-present', ticketsOut.length === tickets.length,
    `expect=${tickets.length} got=${ticketsOut.length}`);
  record('main/fast-no-show-blocks', dt < 5000,
    `主响应 ${dt}ms（契约=不被逐票 show 拖住；>5s 即退化回阻塞形态）`);
  const during = stub.traceSince(size0).map((x) => x.op);
  record('main/zero-show-during-main', !during.some((o) => o === 'ticket:show'),
    `主窗口调用=${JSON.stringify(during)}（「主数据先行」：show 只许发生在 enrich 阶段）`);
  record('main/list-called', during.some((o) => o === 'ticket:list'), JSON.stringify(during));
  const need = ['id', 'status', 'stage_state', 'epic', 'workflow', 'updated_ts'];
  const bad = ticketsOut.filter((t) => need.some((k) => t?.[k] === undefined));
  record('main/fourstate-fields-complete', ticketsOut.length > 0 && bad.length === 0,
    bad.length ? `缺字段行=${JSON.stringify(bad.map((t) => t?.id))}` : `六行字段齐（含 closed 迁移态/未知 stage_state 行）`);
}

// ---- T3 拓扑与 epic 透传（验收③②数据面） ----
{
  const r = await api(B, 'GET', LIST());
  const body = r.body?.result ?? r.body ?? {};
  const wfs = r.body?.workflows ?? body.workflows ?? [];
  const lens = wfs.map((w) => w?.stages?.length).filter((n) => Number.isFinite(n));
  record('topo/two-templates-differing-stages', wfs.length >= 2 && new Set(lens).size >= 2,
    `模板数=${wfs.length} stages.length=${JSON.stringify(lens)}（站道点数=stages.length 的消费源，验收③）`);
  const wfIds = new Set(wfs.map((w) => w?.id));
  const rows = body.tickets ?? [];
  record('topo/ticket-workflow-in-topo', rows.every((t) => wfIds.has(t?.workflow)),
    rows.map((t) => `${t.id}:${t.workflow}`).join(','));
  const epics = Object.fromEntries(rows.map((t) => [t.id, t.epic]));
  record('epic/passthrough-including-empty', epics.trun === 'alpha-epic' && epics.tblock === '',
    JSON.stringify(epics));
}

// ---- T4 enrich 默认：ok 票有 progress、失败票降级、零错误文案 ----
{
  const r = await api(B, 'GET', LIST('&enrich=progress'));
  record('enrich/200', r.status === 200, `status=${r.status} ${String(errText(r)).slice(0, 120)}`);
  const rows = r.body?.result?.tickets ?? [];
  const by = Object.fromEntries(rows.map((t) => [t.id, t]));
  const has = (id) => Boolean(by[id]?.progress && typeof by[id].progress === 'object');
  record('enrich/ok-tickets-have-progress', has('trun') && has('twait') && has('tblock'),
    JSON.stringify({ trun: by.trun?.progress ?? null, twait: by.twait?.progress ?? null }));
  const p = by.trun?.progress ?? {};
  record('enrich/progress-shape', ['stage', 'state', 'at'].every((k) => p[k] !== undefined),
    `trun.progress=${JSON.stringify(p)}（形状={stage,state,at}）`);
  record('enrich/failed-tickets-degrade', !has('tawait') && !has('tunk'),
    `失败票 progress 在场=${JSON.stringify([by.tawait?.progress, by.tunk?.progress])}（降级≠500≠缺行）`);
  const progBlob = JSON.stringify(rows.map((t) => t?.progress ?? null));
  const leak = /fix17|注入|失败|error|transient/i.test(progBlob);
  record('enrich/no-error-text-in-data', !leak,
    leak ? 'progress 面出现错误文案字样（KI-018「错误文案当数据写」根除面被破坏）' : '数据字段零错误文案');
}

// ---- T5 enrich 畸形 timeline：缺 stage/state 条目 → progress 缺省不炸 ----
{
  stub.setCtrl({
    workflows: [wfAlpha, wfBeta], tickets,
    show: { ...defaultShow, trun: { mode: 'ok', timeline: [null, { foo: 1 }, { at: NOW - 10 }] } },
  });
  const r = await api(B, 'GET', LIST('&enrich=progress'));
  const rows = r.body?.result?.tickets ?? [];
  const trun = rows.find((t) => t.id === 'trun');
  const progressed = rows.filter((t) => t?.progress && t.id !== 'trun').length;
  record('enrich/malformed-timeline-survives',
    r.status === 200 && !(trun?.progress && trun.progress.stage !== undefined) && progressed >= 2,
    `status=${r.status} trun.progress=${JSON.stringify(trun?.progress ?? null)} 其余进展行=${progressed}（畸形条目跳过=既有容错纪律）`);
}

// ---- T6 enrich 预算：全票慢 show → 有界返回 + 并发上限 ----
{
  const slow = {};
  for (const t of tickets) slow[t.id] = { mode: 'delay', ms: 8000, then: 'ok', timeline: [] };
  stub.setCtrl({ workflows: [wfAlpha, wfBeta], tickets, show: slow });
  const size0 = stub.traceSizeAt();
  const t0 = Date.now();
  const r = await api(B, 'GET', LIST('&enrich=progress'));
  const dt = Date.now() - t0;
  const rows = r.body?.result?.tickets ?? [];
  record('enrich/slow-bounded-return', r.status === 200 && dt < 12000,
    `status=${r.status} 耗时=${dt}ms（每票短超时契约：无超时实现=8s/票，串行更久必红）`);
  record('enrich/slow-all-degraded', rows.every((t) => !t?.progress || t.progress.stage === undefined),
    `超时票 progress 在场=${JSON.stringify(rows.filter((t) => t?.progress).map((t) => t.id))}`);
  const shows = stub.traceSince(size0).filter((x) => x.op === 'ticket:show');
  let peak = 0;
  const events = shows.flatMap((s) => [[s.t0, 1], [s.t1, -1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  for (const [, d] of events) { cur += d; peak = Math.max(peak, cur); }
  record('enrich/concurrency-capped', peak > 0 && peak <= 4,
    `show 并发峰值=${peak}（契约=有上限；无界并发随列表规模线性放大 Temporal 查询=KI-003/029 加重面）`);
}

summarize();
