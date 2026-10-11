#!/usr/bin/env node
// sc_t26100972_bench_boot_anchor.mjs —— 隔离台本尊能启动、锚不破岗（t261009-72）。
//
// intent（灰盒 L3，用户可感知行为；工单验收 (1)(2)(4) 的 boot 面）：t261009-70 的
// survivor log 定死了根因——夹具仓经 env SANDBAR_REPO 声明，而插件树从 lane worktree
// 加载，repo-anchor 的锚岗（SANDBAR_ANCHOR_MISMATCH before any write）当场合拒 ⇒
// 插件树装不上、控制台永不就绪、本族全部场景 45s env_fail（全史 16/16 零绿，KI-01M4JKQVMW…
// /KI-01M4JJWGWZ…）。修复后承诺（harness 侧声明方式改为 profile patch 的 config.repo，
// server/** 锚岗一字不动）：
//   S1 隔离台在 fix17 boot 面真正就绪：即便宿主环境串进一个**指向别处 checkout 的
//      env SANDBAR_REPO**（对抗注入=当初肇事的同一形态），boot 也不被它污染——
//      harness 的 bench env 面必须对该变量免疫（模块头不变量：夹具仓只走 config.repo）。
//   S2 锚岗不破：env 源外部锚在 linked worktree 里仍判 SANDBAR_ANCHOR_MISMATCH，
//      config.repo 源外部锚与位置推导仍放行（verdict 表钉死=验收 (2) 的测试化）。
//   S3 引擎通道落在夹具桩上：HTTP 工单列表返回夹具行、桩轨迹出现 ticket:list——
//      证明 repo 锚确实解析到夹具仓的 .venv/bin/python 符链（config.repo 生效的
//      用户可感知证据），不是「插件装上了但引擎通道哑火」。
//   S4 红线与回收：随机高端口（禁 3099 用户面/7233 真源面）；teardown 后 tmpHome
//      物理消失。
// intent 分界（防重复）：boot 失败的证据面（survivor/tail）=t261009-70；HTTP 工单列表
// 契约细节（路由壳/四态字段/enrich 预算）=t260904-17 sc_ticket_list_http_contract——
// 本条只借那张网的最小一针（200+行数+轨迹）作「引擎通道活着」的信号，不重复其断言；
// 浏览器渲染面=t261009-53/-22/-23 族。env_fail 语义不动：boot 失败在**本条**记 FAIL
// （本条的全部存在意义就是它必须 boot），唯独 dsh/profile 依赖物理缺失才 ENV_FAIL。
// 三态（t260904-12）：fail>0 或全 na=exit 1；env_fail>0=exit 2。
// 实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。

import { existsSync } from 'node:fs'
import {
  makeRegistryRoot, writeProjectEntry, makeTicketStub, bootConsole,
  teardownOnExit, api, makeResults, tmpRoot, REPO_ROOT,
} from '../t260904-17/lib_fix17.mjs'
import { anchorGuardError, isLinkedWorktree, OWN_ROOT } from '../../server/plugins/repo-anchor.mjs'

const { record, summarize } = makeResults();

// ---- fixture：一模板两票（够 engine 通道出一行即达意，细节归 sc_ticket_list） ----
const NOW = Math.floor(Date.now() / 1000);
const wf = { id: 'wf-fix72', name: '夹具流程', stages: [
  { id: 's1', name: '起草' }, { id: 's2', name: '收尾' },
] };
const tickets = [
  { id: 'fix72a', project: 'fix72', title: 'boot-face row', role: 'developer',
    status: 'running', stage: 's1', stage_state: 'running', workflow: 'wf-fix72',
    epic: '', handoff_count: 0, pending_count: 0, worktree: '/tmp/fix72/a',
    updated: '2026-10-09 00:00:00', updated_ts: NOW - 60, created: NOW - 600 },
];
const stub = makeTicketStub();
stub.setCtrl({ workflows: [wf], tickets, show: {} });

// 对抗注入：往宿主进程塞「指向别处 checkout 的 env SANDBAR_REPO」——当初肇事的同一
// 形态。修复后的 bench env 面显式免疫它；若实现回潮（不删/不换 seam），锚岗当场拒、
// S1 红=精确点名回归。
process.env.SANDBAR_REPO = tmpRoot('fix72-foreign-repo-');

let bench = null;
try {
  const projectsRoot = makeRegistryRoot('fix72-reg-');
  writeProjectEntry(projectsRoot, 'fix72', 'boot-face fixture', [tmpRoot('fix72-proj-')]);
  bench = await bootConsole(projectsRoot, stub);
} catch (e) {
  const msg = String(e?.message ?? e);
  const missingDeps = /ENOENT|dsh|依赖缺失|node_modules|主树插件/.test(msg) && !/就绪超时|ready|timeout/i.test(msg);
  if (missingDeps) {
    record('S1/boot-ready', 'env_fail', `隔离台依赖物理缺失（非本票缺陷面）：${msg.slice(0, 200)}`);
  } else {
    record('S1/boot-ready', false,
      `隔离台未就绪——本条的存在意义即它必须 boot；若尾迹含 SANDBAR_ANCHOR_MISMATCH 即锚缝回潮：${msg.slice(0, 400)}`);
  }
  summarize();
}
teardownOnExit(bench.teardown);

// ---- S1 boot 就绪（含对抗注入后的存活） ----
record('S1/boot-ready', true, `${bench.base}（宿主串入的 foreign env SANDBAR_REPO 被免疫）`);

// ---- S2 锚岗 verdict 表（验收 (2)：guard 不弱化的测试化钉死） ----
{
  const foreign = tmpRoot('fix72-guard-foreign-');
  let linked = false;
  try { linked = isLinkedWorktree(OWN_ROOT); } catch { /* 判定面照给 */ }
  const envVerdict = anchorGuardError(foreign, 'env SANDBAR_REPO');
  record('S2/env-foreign-refused', typeof envVerdict === 'string' && envVerdict.includes('SANDBAR_ANCHOR_MISMATCH'),
    `linked=${linked} verdict=${JSON.stringify(envVerdict).slice(0, 120)}`);
  const cfgVerdict = anchorGuardError(foreign, 'config.repo');
  record('S2/config-repo-passes', cfgVerdict === null, JSON.stringify(cfgVerdict));
  const locVerdict = anchorGuardError(foreign, 'location-derived');
  record('S2/location-derived-passes', locVerdict === null, JSON.stringify(locVerdict));
}

// ---- S3 引擎通道落在夹具桩（config.repo 生效的可感知证据） ----
{
  const t0 = stub.traceSizeAt ? stub.traceSizeAt() : 0;
  const r = await api(bench.base, 'GET', '/sandbar-workbench/api/wf/tickets?project=fix72');
  record('S3/list-200', r.status === 200, `status=${r.status} ${String(r.text).slice(0, 120)}`);
  const rows = (r.body?.result ?? r.body ?? {}).tickets ?? [];
  record('S3/fixture-row-served', rows.length === tickets.length && rows[0]?.id === 'fix72a',
    `rows=${rows.length}`);
  const ops = (stub.traceSince ? stub.traceSince(t0) : []).map((x) => x.op);
  record('S3/engine-channel-on-stub', ops.some((o) => o === 'ticket:list'),
    `trace=${JSON.stringify(ops)}`);
}

// ---- S4 红线与回收 ----
record('S4/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);
{
  const home = bench.tmpHome;
  bench.teardown();
  record('S4/reclaim', !existsSync(home), home);
}
summarize();
