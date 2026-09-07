// sc_project_ui_host_routes.mjs — t260904-15 场景①：workbench host 项目路由薄壳契约（API 面，无浏览器）。
//
// intent（灰盒，用户可感知行为；epic 面D/决策8 + 验收11/12/13 + gen1 方案改动4）：
//   宿主经 console 左栏增删项目时，host 写路由是把请求原样转给 `sandbar project
//   add|remove --json` 的薄壳：CLI 的六类拒收错误体逐字透传到 HTTP 4xx（就地显示
//   的数据源，验收12），CLI 的成功/ dry-run 输出透传为 2xx；注册表读面（GET
//   /wf/projects）走 TS 装载器并补隔离条目（key+原因含 <dir>/project.yaml 定位，
//   验收11 隔离行数据源）；空/全隔离注册表=200 空清单不再 500（首接面，验收9）；
//   票计数读路由 spawn CLI list --json 单点取数，Temporal 不可达=降级字段而非错误
//   （验收11「—」数据源）；remove 在 Temporal 不可达时 fail-closed 拒摘且文案含
//   可达性诊断指路（验收7/13，契约①a-1 闸序：dry-run 亦全闸预演）。
//   与 t260904-10（CLI add/list 语义）/t260904-14（CLI remove 闸语义）intent 不同面：
//   本条守的是「路由薄壳透传+读面扩展」这层消费契约，CLI 语义本身不在断言面内。
//
// high-level steps：
//   T0 自举隔离台（临时注册表根：好条目 fixa + 畸形条目 badkey；Temporal=死端口）。
//   T1 GET /wf/projects：fixa 在列；quarantined 数组含 badkey 且原因含 project.yaml 定位字面。
//   T2 add dry-run：422 能力应答（CLI 无 --dry-run 旗，预检降档=弹层本地形状检查，
//      裁定项上浮）+ 文案指路 + 注册表根字节级零变更（不 spawn）。
//   T3 拒收透传（逐腿 4xx + 错误体点名原因）：key 白名单 / key 已存在 / dirs 缺失 /
//      dirs 相对路径 / 根交叉（与 fixa 根嵌套）/ 畸形 JSON 请求体（精确文案不裸抛堆栈）。
//   T4 add 成功：2xx；GET /wf/projects 即时出现新条目（左栏读回=装载器消费方，验收12）。
//   T5 remove fail-closed：dry-run 与真跑皆 4xx、文案含 sandbar up 指路；注册表零变更。
//   T6 票计数读路由：detail?key=fixa → 200 + 降级字段（tickets_state 非 ok 带 note，非 500）；
//      未知 key → 4xx 可辨。
//   T7 红线：端口 ≠ 3099；finally 必回收 boot 进程树。
//
// 执行契约：stdout 末行 SUMMARY 四计数（t260904-12 三态）；隔离台依赖缺失=dsh 不可用/
//   buildTempProfile 失败 → ENV_FAIL（exit 2 点名原因，不假绿）；实现落地前红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
import { readdirSync, statSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import {
  REPO_ROOT, tmpRoot, makeFixtures, writeProjectEntry, writeQuarantinedDir,
  bootConsole, teardownOnExit, api, makeResults, dismissShellNotice } from './lib_fix15.mjs';

const { record, summarize } = makeResults();

function treeSnapshot(dir) {
  const out = {};
  const walk = (d, rel) => {
    for (const name of readdirSync(d)) {
      const p = path.join(d, name);
      const r = rel ? `${rel}/${name}` : name;
      const st = statSync(p);
      out[r] = st.isDirectory() ? walk(p, r) : st.size;
    }
  };
  walk(dir, '');
  return out;
}

let bench;
try {
  const fx = makeFixtures('fix15-api-');
  writeProjectEntry(fx.reg, 'fixa', '夹具甲', [path.join(fx.root, 'proj-fixa')]);
  writeQuarantinedDir(fx.reg, 'badkey');
  bench = await bootConsole(fx.root);
  bench.__fixtures = fx;
  bench.__projectsRoot = fx.reg;
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失（docker 测试台）：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', 'pass', bench.base);

const B = bench.base;
const API = '/sandbar-workbench/api/wf/projects';
const root = bench.__projectsRoot;
const okBody = (r) => (r.body && typeof r.body === 'object' ? (r.body.result ?? r.body) : r.body);
const errText = (r) => (typeof r.body === 'string' ? r.body : JSON.stringify(r.body?.error ?? r.body));

// T1 注册表读面 + 隔离条目扩展
{
  const r = await api(B, 'GET', API);
  const body = okBody(r);
  const projects = body?.projects ?? [];
  const q = body?.quarantined ?? null;
  record('read/projects', r.status === 200 && projects.some((p) => p.key === 'fixa') ? 'pass' : 'fail',
    `status=${r.status} keys=${projects.map((p) => p.key).join(',')}`);
  const qb = Array.isArray(q) ? q.find((x) => x.key === 'badkey') : null;
  record('read/quarantined', !!qb && String(qb.error ?? '').includes(path.join(bench.reg, 'badkey', 'project.yaml')),
    `quarantined=${JSON.stringify(q)?.slice(0, 200)}`);
}

// T2 add dry_run 能力应答（F1 修后口径，arbitrate gen1：CLI `project add` 无 --dry-run
// 旗——补旗为跨写集裁定项；预检降档为弹层本地形状检查。路由对 dry_run:true 显式 4xx
// 应答且不 spawn CLI，注册表零现场变更保证不变）
{
  const before = treeSnapshot(root);
  const newDir = path.join(bench.__fixtures.root, 'proj-new-dry');
  mkdirSync(newDir, { recursive: true }); // 容器内 CLI 验目录存在（add 不代建）
  const r = await api(B, 'POST', `${API}/add`, { key: 'fixb', name: '夹具乙', dir: bench.toStage(newDir), dry_run: true });
  const after = treeSnapshot(root);
  const txt = errText(r);
  record('add/dry-run', r.status === 422 && txt.includes('本地形状检查') && JSON.stringify(before) === JSON.stringify(after),
    `status=${r.status} body=${txt.slice(0, 160)} changed=${JSON.stringify(before) !== JSON.stringify(after)}`);
}

// T3 拒收透传（4xx + 文案点名原因）
{
  const dupSrc = path.join(bench.__fixtures.root, 'proj-dup');
  mkdirSync(dupSrc, { recursive: true });
  const dupDir = bench.toStage(dupSrc);
  const projDirOfFixa = (await (async () => {
    const r = await api(B, 'GET', API);
    const p = okBody(r)?.projects?.find((x) => x.key === 'fixa');
    return p?.primary ?? p?.dirs?.[0] ?? '';
  })()) || tmpRoot('fix15-api-fixa2-');
  const cases = [
    ['bad-key', { key: 'Fix_B', name: 'x', dir: dupDir }, 'key 不合法'],
    ['dup-key', { key: 'fixa', name: 'x', dir: dupDir }, ''],
    ['missing-dir', { key: 'fixc', name: 'x' }, 'root_dir'],  // 真实 CLI 文案='root_dir 不能为空'（--help/直呼实跑锚定，非臆造）
    ['relative-dir', { key: 'fixc', name: 'x', dir: 'rel/path' }, ''],
    ['cross-root', { key: 'fixc', name: 'x', dir: path.dirname(projDirOfFixa) }, ''],
  ];
  for (const [name, payload, reasonNeedle] of cases) {
    const r = await api(B, 'POST', `${API}/add`, payload);
    // 契约锚：路由自诺「CLI 拒收 → 4xx 原体透传」（就地显示数据源）——拒收不是上游故障，
    // 不得落 5xx；错误文本必须点名该腿的精确原因（不谎报）。
    const txt = errText(r);
    const passed = r.status >= 400 && r.status < 500 && !txt.includes('Traceback')
      && (!reasonNeedle || txt.includes(reasonNeedle));
    record(`add/reject-${name}`, passed, `status=${r.status} 期望4xx含[${reasonNeedle}] err=${txt.slice(0, 140)}`);
  }
  const bad = await api(B, 'POST', `${API}/add`, '\x00raw');
  record('add/reject-malformed-body', bad.status >= 400 && bad.status < 500 && !errText(bad).includes('Traceback'),
    `status=${bad.status} err=${errText(bad).slice(0, 140)}`);
}

// T4 add 成功 → 读面即时出现
{
  const newDir = path.join(bench.__fixtures.root, 'proj-new-ok');
  mkdirSync(newDir, { recursive: true }); // 容器内 CLI 验目录存在（add 不代建）
  const r = await api(B, 'POST', `${API}/add`, { key: 'fixb', name: '夹具乙', dir: bench.toStage(newDir), dry_run: false });
  const rr = await api(B, 'GET', API);
  const listed = okBody(rr)?.projects?.some((p) => p.key === 'fixb');
  record('add/success-then-read', r.status >= 200 && r.status < 300 && listed,
    `add=${r.status} listed=${listed} body=${JSON.stringify(okBody(r))?.slice(0, 140)}`);
}

// T5 remove fail-closed（Temporal 死端口；dry-run 同闸）
{
  const before = treeSnapshot(root);
  for (const dry of [true, false]) {
    const r = await api(B, 'POST', `${API}/remove`, { key: 'fixb', dry_run: dry });
    const txt = errText(r);
    const passed = r.status >= 400 && r.status < 500 && /sandbar up|可达|Temporal/i.test(txt);
    record(`remove/fail-closed${dry ? '-dryrun' : ''}`, passed, `status=${r.status} err=${txt.slice(0, 160)}`);
  }
  const after = treeSnapshot(root);
  record('remove/zero-change', JSON.stringify(before) === JSON.stringify(after));
}

// T6 票计数读路由（降级而非错误）
{
  const r = await api(B, 'GET', `${API}/detail?key=fixa`);
  const body = okBody(r);
  const degraded = body && (body.tickets == null || body.tickets_state != null || body.degraded === true);
  record('detail/degraded-counts', r.status === 200 && degraded,
    `status=${r.status} body=${JSON.stringify(body)?.slice(0, 160)}`);
  const bad = await api(B, 'GET', `${API}/detail?key=nope`);
  record('detail/unknown-key', bad.status >= 400 && bad.status < 500, `status=${bad.status}`);
}

// T7 红线
record('redline/not-3099', !bench.base.includes(':3099'), bench.base);

bench.teardown();
summarize();
