// sc_docs_project_anchor.mjs — t260910-10 场景①②+注入：docs tree/doc 按项目根解析（KI-070 API 主干，隔离台 HTTP 直读）。
//
// intent（灰盒，用户可感知行为；工单必含①② + 执行钩子畸形输入面）：
//   多项目工单台上，任何一个项目打开「文档」视图，读到的必须是该项目自己的 docs/notes
//   ——不是引擎仓 sandbar 的（KI-070 宿主实报「任何项目都只读 sandbar docs」的 API 终态
//   修复判据）。断言三面：
//   ① 项目锚面：非 sandbar 夹具项目（真目录真文件真读）下 tree 出夹具篇目（根级+嵌套）、
//      绝不含 sandbar 定稿库签名篇目；doc 真读出夹具正文且全文无 sandbar 内容串入（正反
//      两面）；notes scope 同构断言（夹具 notes 在场、sandbar epics/ 不串）。
//   ② 缺省/未锚回落面：不带 project 的 tree/doc 读引擎仓 sandbar 真库篇目（resolved
//      source='default'），无夹具内容串入——旧行为零回归。
//   ③ 注入面（project 是本票新增消费的外部输入）：未注册 key 显式 400 且 error 点名
//      「未知项目」、响应无 resolved、绝不静默回落 sandbar 篇目（回落=数据串仓，比报错糟）；
//      空 scope 目录诚实降级（200 empty=true + 人话 reason 非空，不 500 不谎报，KI-025 族）。
//   可观测契约：200 体挂 resolved={source,key,root}（project-anchor resolvedMark 六面路由
//   统一口径）；root=夹具注册主目录逐字节相等=「服务端把 root 解析到项目根」的 KI-070 终态
//   判据。端口红线 ≠3099/7233；lib_fix17 自举（临时注册表+双夹具项目），零浏览器依赖
//   （不探 playwright，纯 API 场景无 KI-036 家族环境用例）。
//   与 t260905-06-doc-read-through intent 不同面：那条锁缺省锚（单仓）阅读旅程+穿路径白名单
//   +窄栏 UI，本条锁多项目锚解析/回落/注入——穿路径白名单不重复设计（既有 T1 已覆盖）。
//   实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
//
// high-level steps：
//   T0 自举隔离台（lib_fix17：临时注册表根 + fixa「夹具甲」=docs/mini.md+docs/sub/深篇.md+
//      notes/备忘.md、fixb「夹具乙」=docs/单篇.md 无 notes/）；端口红线记录。
//   T1 项目锚 tree：tree?project=fixa&scope=docs → 200、篇目含 mini.md 与 sub/深篇.md、
//      无 terminology.md、全文无「项目术语表」、resolved={project,fixa,root=夹具根逐字节}。
//   T2 项目锚 doc：doc?project=fixa&scope=docs&path=mini.md → 200 正文含夹具标题、
//      全文无「项目术语表」/「毕业规则」（sandbar docs+notes 双签名不串）。
//   T3 项目锚 notes：tree?project=fixa&scope=notes → 含 备忘.md、无 epics/ 签名。
//   T4 缺省回落：无 project tree → sandbar 篇目（terminology.md）在场、无 mini.md、
//      resolved source='default'；doc terminology.md 含「项目术语表」、无夹具串入。
//   T5 未注册 key：tree?project=<不存在>&scope=docs → 400、error 含「未知项目」、
//      无 resolved、无 sandbar 篇目（不静默回落）。
//   T6 空目录诚实降级：tree?project=fixb&scope=notes（目录缺席）→ 200、empty=true、
//      reason 非空字符串、groups 空（措辞不锚字面——reason 是人话契约不是常量）。
//   T7 红线+回收：finally teardown 进程树/临时目录；SUMMARY 三态。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿，旧 SKIP 语义退役）。
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, makeResults,
} from '../t260904-17/lib_fix17.mjs';

const { record, summarize } = makeResults();

const stub = makeTicketStub();

// ---- T0 夹具：非 sandbar 真目录（前哨兵词全部夹具独有，防与 sandbar 真库内容撞车）----
function writeFxa(root) {
  const docs = path.join(root, 'docs');
  mkdirSync(path.join(docs, 'sub'), { recursive: true });
  mkdirSync(path.join(root, 'notes'), { recursive: true });
  writeFileSync(path.join(docs, 'mini.md'), [
    '---',
    'title: 夹具甲指南',
    'status: active',
    'updated: 2026-09-10',
    'category: reference',
    '---',
    '',
    '# 夹具甲正文标题',
    '',
    '夹具甲独有内容哨兵。',
    '',
    '## 小节甲',
    '',
    '小节甲正文。',
    '',
    '## 小节乙',
    '',
    '小节乙正文。',
    '',
  ].join('\n'));
  writeFileSync(path.join(docs, 'sub', '深篇.md'), [
    '---',
    'title: 夹具甲深篇',
    'status: draft',
    '---',
    '',
    '# 夹具甲深篇正文',
    '',
  ].join('\n'));
  writeFileSync(path.join(root, 'notes', '备忘.md'), [
    '---',
    'title: 夹具甲备忘',
    '---',
    '',
    '# 夹具甲备忘正文',
    '',
  ].join('\n'));
}

function writeFxb(root) {
  const docs = path.join(root, 'docs');
  mkdirSync(docs, { recursive: true });
  writeFileSync(path.join(docs, '单篇.md'), [
    '---',
    'title: 夹具乙单篇',
    '---',
    '',
    '# 夹具乙单篇正文',
    '',
  ].join('\n'));
  // 有意不建 notes/ ——T6 空 scope 诚实降级子用例的载体
}

const regRoot = makeRegistryRoot('t260910-10-anchor-reg-');
const fixaRoot = tmpRoot('t260910-10-fixa-');
writeFxa(fixaRoot);
writeProjectEntry(regRoot, 'fixa', '夹具甲', [fixaRoot]);
const fixbRoot = tmpRoot('t260910-10-fixb-');
writeFxb(fixbRoot);
writeProjectEntry(regRoot, 'fixb', '夹具乙', [fixbRoot]);

let bench;
try {
  bench = await bootConsole(regRoot, stub);
} catch (e) {
  record('bench/boot', 'env_fail', `隔离台依赖缺失：${String(e?.message ?? e).slice(0, 200)}`);
  summarize();
}
teardownOnExit(bench.teardown);
record('bench/boot', true, bench.base);
record('redline/ports', bench.port !== 3099 && bench.port !== 7233, `port=${bench.port}`);

// ---- HTTP 直读（read_through 同款形状）----
async function getJson(pathname) {
  try {
    const r = await fetch(`${bench.base}${pathname}`, { signal: AbortSignal.timeout(15000) });
    return { status: r.status, body: await r.json().catch(() => null) };
  } catch (e) { return { status: 0, body: null, err: String(e) }; }
}
// 树聚合形状属实现自由度——扁平化收集 .md 篇目，断言只锚「篇目可达」不锚树形（灰盒浅绑定）。
function collectPaths(node, out) {
  if (!node || typeof node !== 'object') return out;
  if (Array.isArray(node)) { for (const x of node) collectPaths(x, out); return out; }
  for (const [k, v] of Object.entries(node)) {
    if (typeof v === 'string' && /\.md$/.test(v)) out.push(v);
    else if (k === 'path' && typeof v === 'string') out.push(v);
    else collectPaths(v, out);
  }
  return out;
}

const DOC_API = '/sandbar-workbench/api/wf/docs';

// ---- T1 项目锚 tree（夹具甲读自己的 docs）----
const t1 = await getJson(`${DOC_API}/tree?project=fixa&scope=docs`);
if (t1.status !== 200 || !t1.body) {
  record('anchor/tree-fixture', 'fail', `GET tree?project=fixa&scope=docs → ${t1.status}（实现落地前红属预期）`);
} else {
  const paths = collectPaths(t1.body, []);
  const raw = JSON.stringify(t1.body);
  record('anchor/tree-fixture-own', paths.includes('mini.md') && paths.includes('sub/深篇.md'),
    `夹具篇目可达 mini.md=${paths.includes('mini.md')} sub/深篇.md=${paths.includes('sub/深篇.md')}（共 ${paths.length} 篇）`);
  record('anchor/tree-no-sandbar', !paths.some((p) => p.includes('terminology')) && !raw.includes('项目术语表'),
    `sandbar 签名篇目不串：terminology 路径=${paths.some((p) => p.includes('terminology'))} 「项目术语表」文本=${raw.includes('项目术语表')}`);
  const rv = t1.body.resolved;
  record('anchor/resolved-mark', !!rv && rv.source === 'project' && rv.key === 'fixa' && rv.root === fixaRoot,
    `resolved=${JSON.stringify(rv ?? null)} 期望={project,fixa,root=${fixaRoot}}（root 逐字节=KI-070 终态判据）`);
}

// ---- T2 项目锚 doc 真读（工单必含①的 doc 半；正反两面）----
const t2 = await getJson(`${DOC_API}/doc?project=fixa&scope=docs&path=${encodeURIComponent('mini.md')}`);
if (t2.status !== 200 || !t2.body) {
  record('anchor/doc-fixture', 'fail', `GET doc?project=fixa… → ${t2.status}（实现落地前红属预期）`);
} else {
  const raw = JSON.stringify(t2.body);
  record('anchor/doc-fixture-read', raw.includes('夹具甲正文标题'),
    `夹具正文读出=${raw.includes('夹具甲正文标题')}（title=${String(t2.body?.result?.title ?? '').slice(0, 40)}）`);
  record('anchor/doc-no-sandbar', !raw.includes('项目术语表') && !raw.includes('毕业规则'),
    `sandbar docs/notes 双签名不串：项目术语表=${raw.includes('项目术语表')} 毕业规则=${raw.includes('毕业规则')}`);
}

// ---- T3 项目锚 notes scope（夹具 notes 在场、sandbar epics 不串）----
const t3 = await getJson(`${DOC_API}/tree?project=fixa&scope=notes`);
if (t3.status !== 200 || !t3.body) {
  record('anchor/tree-fixture-notes', 'fail', `GET tree?project=fixa&scope=notes → ${t3.status}`);
} else {
  const paths = collectPaths(t3.body, []);
  record('anchor/notes-fixture-own', paths.some((p) => p.endsWith('备忘.md')) && !paths.some((p) => p.includes('epics/')),
    `夹具 notes 可达 备忘.md=${paths.some((p) => p.endsWith('备忘.md'))} epics/ 不串=${!paths.some((p) => p.includes('epics/'))}（共 ${paths.length} 篇）`);
}

// ---- T4 缺省/未锚回落引擎仓（工单必含②；旧行为零回归）----
const t4 = await getJson(`${DOC_API}/tree?scope=docs`);
if (t4.status !== 200 || !t4.body) {
  record('default/tree-fallback', 'fail', `GET tree?scope=docs（无 project）→ ${t4.status}`);
} else {
  const paths = collectPaths(t4.body, []);
  const rv = t4.body.resolved;
  record('default/tree-sandbar', paths.some((p) => p.endsWith('terminology.md')) && !paths.includes('mini.md'),
    `缺省读引擎仓：terminology.md=${paths.some((p) => p.endsWith('terminology.md'))} 夹具不串=${!paths.includes('mini.md')}（共 ${paths.length} 篇）`);
  record('default/resolved-default', !!rv && rv.source === 'default' && rv.key === null,
    `resolved=${JSON.stringify(rv ?? null)} 期望 source='default' key=null`);
}
const t4b = await getJson(`${DOC_API}/doc?scope=docs&path=${encodeURIComponent('terminology.md')}`);
const t4raw = JSON.stringify(t4b.body ?? {});
record('default/doc-sandbar', t4b.status === 200 && t4raw.includes('项目术语表') && !t4raw.includes('夹具甲'),
  `缺省 doc 读真库：含「项目术语表」=${t4raw.includes('项目术语表')} 夹具不串=${!t4raw.includes('夹具甲')}（status=${t4b.status}）`);

// ---- T5 未注册 key 注入（本票新增外部输入的畸形子用例；防静默回落）----
const t5 = await getJson(`${DOC_API}/tree?project=no-such-key-9x&scope=docs`);
const t5raw = JSON.stringify(t5.body ?? {});
record('inject/unknown-key-400', t5.status === 400,
  `未知 key → ${t5.status}（期望 400；200=静默回落或忽略键=串仓面，实现落地前红属预期）`);
// workbench anchor refusal copy (project-anchor.ts) is still Chinese as served;
// the pinned property is precision — the error names the unknown key verbatim.
record('inject/unknown-key-reason', t5raw.includes('未知项目'),
  `error 点名未知项目=${t5raw.includes('未知项目')}（报错精确纪律：不伪装「越出」/「不存在」）`);
record('inject/unknown-key-no-resolved', (t5.body?.resolved ?? null) === null,
  `400 体不挂 resolved=${(t5.body?.resolved ?? null) === null}（解析失败无可观测锚）`);
record('inject/unknown-key-no-fallback', !t5raw.includes('terminology.md'),
  `拒绝响应不含 sandbar 篇目=${!t5raw.includes('terminology.md')}（不静默回落=防数据串仓）`);

// ---- T6 空 scope 目录诚实降级（夹具乙无 notes/）----
const t6 = await getJson(`${DOC_API}/tree?project=fixb&scope=notes`);
if (t6.status !== 200 || !t6.body) {
  record('honest/empty-scope', 'fail', `GET tree?project=fixb&scope=notes → ${t6.status}（目录缺席不是服务器错，应 200 降级）`);
} else {
  const r = t6.body.result ?? {};
  record('honest/empty-scope', r.empty === true && typeof r.reason === 'string' && r.reason.length > 0 && Array.isArray(r.groups) && r.groups.length === 0,
    `empty=${r.empty} reason 非空=${typeof r.reason === 'string' && r.reason.length > 0} groups 空=${Array.isArray(r.groups) && r.groups.length === 0}（人话可见，措辞不锚字面）`);
}

summarize();
