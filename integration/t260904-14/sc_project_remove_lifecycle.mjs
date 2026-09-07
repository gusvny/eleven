// sc_project_remove_lifecycle.mjs — t260904-14 场景①：默认摘除生命周期（可逆摘除+归档链）。
//
// intent（用户可感知行为，立项验收6/10 + gen2 方案）：宿主 `sandbar project remove
// --key <k>` 默认（无 purge 旗）= 可逆摘除——project.yaml 退役移位（原文件不在、
// project.yaml.retired-* 在位）、data/（归档+metrics）与 credentials.yaml 字节不动、
// 两侧装载器（Python shared / TS suyou-projects.ts）不再列该项目且其余项目装载不变；
// re-add 同 key 成功且 data/tickets/ 归档链不断；摘除报告含 .lane/ 泳道清单（只报不删）
// 与 closed 未归档差集黄牌（列票号）；被 prune 清掉历史的已归档票（Temporal list 消失、
// fs 归档在）不得假阴成未归档；在飞闸对 RUNNING 非空=拒摘报票号且零现场变更；
// --dry-run 全闸预演、注册表根字节级零变更。
//
// high-level steps：全程桩 poc_dir（--root 指桩树，假 client.py 票通道经 FIX14_CTRL
// 可控注入），零真 Temporal（C3 表：本场景全腿零环境依赖，不涉 env_fail 豁免）：
//   1. 隔离注册表根（.migrated 预置 + fixture 条目 rmmain/rmkeep/rmjs/rmdry，各带
//      data/tickets 合法归档 + metrics + credentials.yaml + 项目根 .lane 残骸）；
//   2. rmmain 默认摘除（人读）：exit 0、退役两态、data/credentials 字节不变、
//      .lane 残骸原样、报告含泳道票号与数据处置词汇；
//   3. 双侧装载：rmmain 消失、rmkeep 在列且条目字节不动、零隔离；
//   4. re-add rmmain：exit 0、Python 装载复列、归档链连续（archive.json 仍在）；
//   5. rmjs --json：差集黄牌列票号 tx9（manifest 缺=未归档）；prune 票 tj1 的假阴
//      判别在场景② purge 拒腿与本票单测 prune 注入（负向字符串断言易被合法报告
//      词汇误伤，不在此钉）；
//   6. rmdry --dry-run：exit 0、注册表根字节级快照逐键全等、条目未退役；
//   7. RUNNING 非空：exit 1、报票号、注册表根字节级零变更。
//
// 安全红线：零 3099/7233/8233 接触；票通道全走桩 client.py；注册表根与项目根全为
// 自建临时目录。实现段落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { readFileSync, existsSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import {
  REPO_ROOT, tmpRoot, sbEnv, runCli, pyRegistry, extractJson, makeChecks,
  writeProjectEntry, writeArchive, writeLaneDebris, treeSnapshot,
  subtreeUnchanged, makeStubRoot,
} from './lib_fix14.mjs';

const c = makeChecks('t260904-14 project remove 生命周期（桩 poc_dir）');
delete process.env.SANDBAR_PROJECTS_YAML;

// ---- 1. fixture：隔离注册表根 + 桩 poc_dir ----
const root = tmpRoot('fix14-lc-root-');
const stub = makeStubRoot();
writeFileSync(path.join(root, '.migrated'), 'source: fixture\n');

const mkFixture = (key, name, ids) => {
  const projDir = tmpRoot(`fix14-${key}-proj-`);
  writeProjectEntry(root, key, name, [projDir]);
  for (const [id, variant] of ids) writeArchive(root, key, id, variant);
  writeFileSync(path.join(root, key, 'credentials.yaml'), 'dummy: credentials\n');
  mkdirSync(path.join(root, key, 'data', 'metrics'), { recursive: true });
  writeFileSync(path.join(root, key, 'data', 'metrics', 'm.json'), '{"fixture":1}\n');
  writeLaneDebris(projDir, `t-lane-${key}-1`);
  return projDir;
};
mkFixture('rmmain', 'Remove Main', [['ta1', 'valid'], ['ta2', 'valid']]);
const keepProjDir = mkFixture('rmkeep', 'Remove Keep', [['tk1', 'valid']]);
mkFixture('rmjs', 'Remove Json', [['tj1', 'valid']]);
mkFixture('rmdry', 'Remove Dry', [['td1', 'valid']]);

const retiredOf = (key) => readdirSync(path.join(root, key))
  .find((n) => n.startsWith('project.yaml.retired-'));

// ---- 2. rmmain 默认摘除（人读输出）----
const beforeKeep = readFileSync(path.join(root, 'rmkeep', 'project.yaml'), 'utf8');
const mainDataBefore = treeSnapshot(path.join(root, 'rmmain', 'data'));
const credBefore = readFileSync(path.join(root, 'rmmain', 'credentials.yaml'), 'utf8');
stub.setCtrl({ mode: 'ok', tickets: [
  { id: 'ta1', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmmain', sa_epic: '' },
  { id: 'ta2', exec_status: 'COMPLETED', close_ts: 2, sa_project: 'rmmain', sa_epic: '' },
  { id: 'tk1', exec_status: 'COMPLETED', close_ts: 3, sa_project: 'rmkeep', sa_epic: '' },
] });
const rem = stub.remove(root, 'rmmain');
c.check('默认摘除 exit 0', rem.code === 0, `exit=${rem.code}\n${rem.out.slice(-500)}`);
c.check('project.yaml 已退役移位（原文件不在）',
  !existsSync(path.join(root, 'rmmain', 'project.yaml')));
c.check('退役文件 project.yaml.retired-* 在位（可逆摘除）', Boolean(retiredOf('rmmain')),
  `key 目录=${JSON.stringify(readdirSync(path.join(root, 'rmmain')))}`);
c.check('data/（归档+metrics）字节不动', subtreeUnchanged(mainDataBefore,
  treeSnapshot(path.join(root, 'rmmain', 'data')), ''));
c.check('credentials.yaml 字节不动',
  readFileSync(path.join(root, 'rmmain', 'credentials.yaml'), 'utf8') === credBefore);
c.check('.lane/ 泳道残骸只报不删（项目根 .lane 目录仍在）',
  existsSync(path.join(keepProjDir, '.lane', 't-lane-rmkeep-1')));
c.check('报告含 .lane 票号 t-lane-rmmain-1（只报清单）', rem.out.includes('t-lane-rmmain-1'),
  rem.out.slice(-500));
c.check('报告含数据处置字节数账目（credentials.yaml 字面——gen2 方案承诺「报告逐项字节数账目」）',
  rem.out.includes('credentials.yaml'), rem.out.slice(-500));
c.check('报告含数据处置词汇 data（字节数账目面）', rem.out.includes('data'),
  rem.out.slice(-500));

// ---- 3. 双侧装载：摘除可见、其余不变、零隔离 ----
const after = pyRegistry(root);
const keys = after.projects.map((p) => p.key);
c.check('Python 装载不再列 rmmain', !keys.includes('rmmain'), `实际=${JSON.stringify(keys)}`);
c.check('Python 装载仍列 rmkeep', keys.includes('rmkeep'));
c.check('重装载零隔离', after.quarantined.length === 0, JSON.stringify(after.quarantined));
c.check('rmkeep 条目字节不动（其余项目装载不变）',
  readFileSync(path.join(root, 'rmkeep', 'project.yaml'), 'utf8') === beforeKeep);
process.env.SANDBAR_PROJECTS_DIR = root; // TS registryRoot() 每调用现读 env（票①场景同款）
const ts = await import(
  pathToFileURL(path.join(REPO_ROOT, 'server', 'dsh', 'suyou-projects.ts')).href);
const reg = ts.loadRegistry();
const tsKeys = reg.projects.map((p) => p.key);
c.check('TS 装载不再列 rmmain', !tsKeys.includes('rmmain'), `实际=${JSON.stringify(tsKeys)}`);
c.check('TS 装载仍列 rmkeep', tsKeys.includes('rmkeep'));
c.check('TS 侧零隔离', (reg.quarantined || []).length === 0,
  JSON.stringify(reg.quarantined || []));

// ---- 4. re-add 同 key：归档链连续（验收6 后半）----
const readdDir = tmpRoot('fix14-rmmain-readd-');
const readd = runCli(['project', 'add', '--key', 'rmmain', '--name', 'Remove Main',
  '--dir', readdDir], sbEnv(root));
c.check('re-add rmmain exit 0', readd.code === 0, `exit=${readd.code}\n${readd.out.slice(-400)}`);
const afterRe = pyRegistry(root);
c.check('re-add 后 Python 装载复列 rmmain',
  afterRe.projects.some((p) => p.key === 'rmmain'));
c.check('归档链连续：ta1/ta2 归档 manifest 原样在位',
  existsSync(path.join(root, 'rmmain', 'data', 'tickets', 'ta1', 'archive.json')) &&
  existsSync(path.join(root, 'rmmain', 'data', 'tickets', 'ta2', 'archive.json')));

// ---- 5. rmjs --json：差集黄牌列票号（C1：manifest 缺=未归档）----
stub.setCtrl({ mode: 'ok', tickets: [
  // tj1 已归档但被 prune（通道不返回）——它的假阴判别在场景② purge 拒腿，不在此钉
  { id: 'tx9', exec_status: 'COMPLETED', close_ts: 9, sa_project: 'rmjs', sa_epic: '' },
] });
const remJs = stub.remove(root, 'rmjs', ['--json']);
c.check('rmjs --json 默认摘除 exit 0（黄牌不阻塞默认摘除）', remJs.code === 0,
  `exit=${remJs.code}\n${remJs.out.slice(-500)}`);
const js = extractJson(remJs.out);
c.check('--json 机器可解析', js !== null, remJs.out.slice(-400));
const jsStr = js === null ? '' : JSON.stringify(js);
c.check('差集黄牌列票号 tx9（fs 目录在/manifest 缺=未归档，C1 缺失态）',
  jsStr.includes('tx9'), jsStr.slice(0, 600));
c.check('rmjs 退役在位', Boolean(retiredOf('rmjs')));

// ---- 6. rmdry --dry-run：全闸预演、注册表根字节级零变更 ----
const rootBefore = treeSnapshot(root);
const dry = stub.remove(root, 'rmdry', ['--dry-run']);
c.check('dry-run exit 0', dry.code === 0, `exit=${dry.code}\n${dry.out.slice(-500)}`);
c.check('dry-run 输出含目标 key（预演报告）', dry.out.includes('rmdry'));
c.check('dry-run 注册表根字节级零变更（逐键全等）',
  JSON.stringify(rootBefore) === JSON.stringify(treeSnapshot(root)));
c.check('dry-run 后 rmdry project.yaml 仍在（未退役）',
  existsSync(path.join(root, 'rmdry', 'project.yaml')));

// ---- 7. 在飞闸注入：RUNNING 非空=拒摘报票号、零现场变更 ----
const rootBefore2 = treeSnapshot(root);
stub.setCtrl({ mode: 'ok', tickets: [
  { id: 'tr7', exec_status: 'RUNNING', close_ts: 0, sa_project: 'rmdry', sa_epic: '' },
] });
const rej = stub.remove(root, 'rmdry');
c.check('在飞非空=拒摘 exit 1', rej.code === 1, `exit=${rej.code}\n${rej.out.slice(-500)}`);
c.check('拒摘逐条报票号 tr7', rej.out.includes('tr7'), rej.out.slice(-500));
c.check('拒摘零现场变更（注册表根字节级全等）',
  JSON.stringify(rootBefore2) === JSON.stringify(treeSnapshot(root)));
c.finish();
