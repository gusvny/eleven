// sc_project_list_report.mjs — t260904-10 场景③：list 报告契约 + 票计数降级三态。
//
// intent（用户可感知行为）：宿主跑 `sandbar project list` 能看到全部注册与隔离条目——
// 隔离条目的原因必须含 `<dir>/project.yaml` 定位（可顺手找到坏文件）；没有注册条目的
// 保留目录（如 data/）不出现；`--json` 与人读同列同构；票计数依赖 Temporal，服务不可达
// 或 SDK 缺失时计数列显式降级提示但命令不红（exit 0）——且两种降级态的输出可辨
// （KI-039 教训：依赖缺失不得被吞成「无数据」，也不得与「服务不可达」混同）。
//
// high-level steps：
//   1. 隔离根 fixture：.migrated 预置 + 手写注册条目 lista/listb + 畸形隔离条目 qbad2
//      + 无 project.yaml 的保留目录 datadirc（装载语义=跳过，list 不得列出）；
//   2. 人读 list：exit 0、含 lista/listb、隔离行含 qbad2 与 <root>/qbad2/project.yaml 字面、
//      不含 datadirc；
//   3. --json list：可解析、同列同构（深度按 key 字段收集）、隔离原因含同款定位字面；
//   4. 降级①服务不可达：SUYOU_TARGET_HOST=127.0.0.1:1（死端口，显式 env 钉死防缺省外溢
//      生产 7233）→ exit 0、条目照列、输出捕获；
//   5. 降级②SDK 缺失：PYTHONPATH 前置空壳 temporalio 包（temporalio.client import 失败）
//      → exit 0、条目照列、输出与①可辨（两态输出不全等）；
//   6. 正常计数腿（测试台可达才跑）：探测测试台 17233，可达则 SUYOU_TARGET_HOST=127.0.0.1:17233 +
//      SUYOU_NAMESPACE=suyou-test 跑 --json，exit 0 且条目在列；不可达=ENV_FAIL
//      （三态契约：缺测试环境绝不 exit 0 假绿，exit 2 并打印缺什么）。
//
// 安全红线：零 3099 接触；对 Temporal 的唯一接触是显式死端口（降级注入）与测试台 17233
// 的只读探测；绝不以缺省 env 跑 list（防误连生产 7233）。
// 实现段落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { writeFileSync, mkdirSync } from 'node:fs';
import { createConnection } from 'node:net';
import path from 'node:path';
import {
  tmpRoot, sbEnv, runCli, extractJson, deepFind, makeChecks, TEST_TARGET,
} from './lib_fix10.mjs';

const c = makeChecks('t260904-10 project list 报告');
delete process.env.SUYOU_PROJECTS_YAML;

// 本地镜像计数（lib_fix10 不暴露计数面且不在本票写集）：供 ENV_FAIL 提前收口时
// 打印四态 SUMMARY（pass/fail/env_fail/na，三态契约 §7.3）
let passN = 0, failN = 0;
const rawCheck = c.check.bind(c);
c.check = (name, cond, detail) => { if (cond) passN += 1; else failN += 1; return rawCheck(name, cond, detail); };

// ---- 1. fixture ----
const root = tmpRoot('fix10-list-root-');
writeFileSync(path.join(root, '.migrated'), 'source: fixture\n');
const mkEntry = (key, name) => {
  const d = tmpRoot(`fix10-${key}-dir-`);
  mkdirSync(path.join(root, key), { recursive: true });
  writeFileSync(path.join(root, key, 'project.yaml'), [
    'schema: v1', 'project:', `  - key: ${key}`, `    name: ${name}`,
    '    dirs:', `      - ${d}`, '',
  ].join('\n'));
};
mkEntry('lista', 'List A');
mkEntry('listb', 'List B');
{
  mkdirSync(path.join(root, 'qbad2'), { recursive: true });
  writeFileSync(path.join(root, 'qbad2', 'project.yaml'), 'schema: v9\nproject:\n  - key: qbad2\n');
  mkdirSync(path.join(root, 'datadirc'), { recursive: true }); // 保留位目录：无 project.yaml
}
const qbad2Yaml = path.join(root, 'qbad2', 'project.yaml');

// ---- 2. 人读 list ----
const human = runCli(['project', 'list'], sbEnv(root));
c.check('list exit 0（只读报告不红）', human.code === 0, `exit=${human.code}\n${human.out.slice(-400)}`);
c.check('人读含注册条目 lista', human.out.includes('lista'));
c.check('人读含注册条目 listb', human.out.includes('listb'));
c.check('隔离条目在列且点名 qbad2', human.out.includes('qbad2'));
c.check(`隔离原因含 project.yaml 定位字面（${qbad2Yaml}）`, human.out.includes(qbad2Yaml),
  human.out.slice(-400));
c.check('保留目录 datadirc 不列（装载语义=跳过）', !human.out.includes('datadirc'));

// ---- 3. --json 同构 ----
const js = runCli(['project', 'list', '--json'], sbEnv(root));
c.check('list --json exit 0', js.code === 0, `exit=${js.code}\n${js.out.slice(-400)}`);
const json = extractJson(js.out);
c.check('--json 机器可解析', json !== null, js.out.slice(-400));
// --json 对隔离条目的暴露形状不钉字段名（隔离契约=条目在列+原因含 <dir>/project.yaml
// 定位字面，实现可用 dir/error 或派生 key 等形状）——按字符串在场判定。
for (const k of ['lista', 'listb']) {
  c.check(`--json 深含注册条目 ${k}（key 字段=schema v1 词汇）`,
    json !== null && deepFind(json, 'key', k).length > 0);
}
c.check('--json 隔离条目 qbad2 在列', json !== null && JSON.stringify(json).includes('qbad2'));
c.check('--json 隔离原因含 project.yaml 定位字面',
  json !== null && JSON.stringify(json).includes(qbad2Yaml));
c.check('--json 不含 datadirc', json !== null && !JSON.stringify(json).includes('datadirc'));

// ---- 4. 降级①：服务不可达（死端口注入，显式 env 防缺省外溢生产） ----
const envDead = sbEnv(root, { SUYOU_TARGET_HOST: '127.0.0.1:1', SUYOU_NAMESPACE: 'suyou-test' });
const dead = runCli(['project', 'list'], envDead);
c.check('Temporal 不可达时 list 仍 exit 0（降级不红）', dead.code === 0,
  `exit=${dead.code}\n${dead.out.slice(-400)}`);
c.check('不可达态条目照列（lista 仍在）', dead.out.includes('lista'));

// ---- 5. 降级②：temporalio SDK 缺失（PYTHONPATH 空壳包注入；KI-039：依赖缺失≠无数据） ----
const shim = tmpRoot('fix10-sdkshim-');
mkdirSync(path.join(shim, 'temporalio'), { recursive: true });
writeFileSync(path.join(shim, 'temporalio', '__init__.py'), '');
// 故意不建 temporalio/client.py → `from temporalio.client import Client` = ImportError 族
const basePy = (process.env.PYTHONPATH || '').trim();
const envSdk = sbEnv(root, {
  SUYOU_TARGET_HOST: '127.0.0.1:1', SUYOU_NAMESPACE: 'suyou-test',
  PYTHONPATH: basePy ? `${shim}${path.delimiter}${basePy}` : shim,
});
const sdk = runCli(['project', 'list'], envSdk);
c.check('SDK 缺失时 list 仍 exit 0（降级不红，KI-039 教训）', sdk.code === 0,
  `exit=${sdk.code}\n${sdk.out.slice(-400)}`);
c.check('SDK 缺失态条目照列', sdk.out.includes('lista'));
c.check('两种降级态输出可辨（不可达≠SDK 缺失，不得吞成同文案）', dead.out !== sdk.out,
  '两态输出全等——三态降级语义未落地');

// ---- 6. 正常计数腿（测试台可达才跑；不可达=ENV_FAIL，三态契约绝不假绿） ----
const reachable = await new Promise((resolve) => {
  const s = createConnection(17233, '127.0.0.1');
  s.setTimeout(800);
  s.on('connect', () => { s.destroy(); resolve(true); });
  s.on('error', () => resolve(false));
  s.on('timeout', () => { s.destroy(); resolve(false); });
});
if (reachable) {
  const live = runCli(['project', 'list', '--json'],
    sbEnv(root, { SUYOU_TARGET_HOST: TEST_TARGET, SUYOU_NAMESPACE: 'suyou-test' }));
  c.check('测试台可达：list --json exit 0', live.code === 0, `exit=${live.code}`);
  const liveJson = extractJson(live.out);
  c.check('测试台可达：条目照列', liveJson !== null && deepFind(liveJson, 'key', 'lista').length > 0);
} else {
  // 环境红（exit 2）：缺测试台不算失败也不算跳过——绝不 exit 0 假绿
  console.log('  [ENV_FAIL] 正常计数腿：测试台 17233 不可达（真实覆盖在隔离台环境）');
  console.log(`SUMMARY pass=${passN} fail=${failN} env_fail=1 na=0`);
  console.log('ENV_FAIL: 测试台 17233 不可达（正常计数腿无测试环境）');
  process.exit(2);
}

c.finish();
