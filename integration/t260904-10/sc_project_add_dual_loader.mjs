// sc_project_add_dual_loader.mjs — t260904-10 场景①：add 产出条目的双侧装载一致性。
//
// intent（用户可感知行为）：宿主用 `sandbar project add` 接入一个项目后，该条目立即被
// 两侧装载器一致消费——Python（shared.load_projects_registry，工单锚定闸的数据源）
// 与 TS（suyou-projects.ts loadRegistry，workbench API 消费方）装载出同一条目
// （key/name/dirs 全等）、零隔离；既有条目（tracked 迁移种子产出的 suyou）字节不动
// （决策7 现状不动账）；写入零 tmp 残留；体检报告三词汇（verify.yaml/credentials/paths）
// 在文且不阻塞。
//
// high-level steps：
//   1. 全新隔离根（SANDBAR_PROJECTS_DIR=临时目录，无 .migrated）→ Python 侧首次装载：
//      触发 tracked 种子（server/dsh/projects.yaml）自动播种，断言 suyou 在案+标记落盘；
//   2. 快照注册表根（既有条目字节+目录清单）；
//   3. 真跑 `project add <key> <name> <root_dir> --json`（裸 fixture 根）→ exit 0、
//      --json 可解析、含该 key；
//   4. 真跑 `project add`（人读，裸目录）→ exit 0、输出含 verify.yaml/credentials/paths
//      三词汇（体检报告三类黄牌的契约词汇面）；
//   5. Python 侧重装载：新条目在案零隔离、种子条目字节不变、无 .tmp. 泄漏、dirs=单根恰一条；
//   6. TS 侧 loadRegistry：同一隔离根装出相同 key 集合，逐条 key/name/dirs 与 Python 侧全等；
//   7. 尾腿（契约①b 排他性钉，独立结算）：先布置 per-key 目录+credentials.yaml 再 add
//      应成功——排他性锚 project.yaml 文件而非条目目录。若实现把独占闸架在目录 mkdir 上，
//      此腿红=契约对（体检②「credentials 在位」态在 add 时点由此才可达）；该腿独立失败
//      不连坐主流程断言，交仲裁裁决（改闸实现 or 修约①b）。
//
// 安全红线：零 3099/7233/8233 接触；本场景不连任何 Temporal；只写自建临时目录。
// 实现段落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import {
  REPO_ROOT, tmpRoot, sbEnv, cliAdd, pyRegistry, extractJson,
  snapshotRoot, assertNoTmpLeak, makeChecks,
} from './lib_fix10.mjs';

const c = makeChecks('t260904-10 project add 双侧装载');
delete process.env.SUYOU_PROJECTS_YAML;

// ---- 1. 全新隔离根：Python 侧首装载触发自动播种（真装载语义，不预判不绕过） ----
const root = tmpRoot('fix10-dual-');
const first = pyRegistry(root);
const seededKeys = first.projects.map((p) => p.key);
c.check('首装载零隔离', first.quarantined.length === 0, JSON.stringify(first.quarantined));
c.check('种子自动播种产出 suyou 条目（tracked 种子契约）', seededKeys.includes('suyou'),
  `实际 key 集=${JSON.stringify(seededKeys)}`);
c.check('.migrated 标记由首装载落盘', existsSync(path.join(root, '.migrated')));

// ---- 2. 快照既有现场（决策7 断言基线） ----
const seededSnapshot = snapshotRoot(root);
const suyouBytes = readFileSync(path.join(root, 'suyou', 'project.yaml'), 'utf8');

// ---- 3. add --json 成功路径（裸 fixture 项目根；位置参数面=实现期冻结的 CLI 契约） ----
const dirA = tmpRoot('fix10-proj-a-');
const addA = cliAdd(root, 'zfix10a', 'Fixture Alpha', [dirA], {}, true);
c.check('add zfix10a exit 0', addA.code === 0, `exit=${addA.code}\n${addA.out.slice(-600)}`);
const jsonA = extractJson(addA.out);
c.check('add --json 输出机器可解析', jsonA !== null, addA.out.slice(-400));
c.check('--json 深含新增 key', jsonA !== null && JSON.stringify(jsonA).includes('zfix10a'));

// ---- 4. 人读体检报告：三类黄牌词汇在文（报告不是闸，exit 0） ----
const dirB = tmpRoot('fix10-proj-b-');
const addB = cliAdd(root, 'zfix10b', 'Fixture Beta', [dirB]);
c.check('add zfix10b（人读）exit 0', addB.code === 0, `exit=${addB.code}\n${addB.out.slice(-600)}`);
for (const token of ['verify.yaml', 'credentials', 'paths']) {
  c.check(`体检报告含契约词汇「${token}」`, addB.out.includes(token),
    `输出缺 ${token}：${addB.out.slice(-400)}`);
}

// ---- 5. Python 侧重装载：条目在案、零隔离、既有条目不动、零 tmp 残留 ----
const after = pyRegistry(root);
const keys = after.projects.map((p) => p.key);
for (const k of ['zfix10a', 'zfix10b']) {
  c.check(`Python 侧装载出 ${k}`, keys.includes(k), `实际=${JSON.stringify(keys)}`);
}
c.check('重装载零隔离', after.quarantined.length === 0, JSON.stringify(after.quarantined));
const entryA = after.projects.find((p) => p.key === 'zfix10a');
c.check('条目 dirs=单根模型恰一条且为输入根',
  entryA && entryA.dirs.length === 1 && entryA.dirs[0] === dirA,
  JSON.stringify(entryA));
c.check('种子条目字节不动（决策7）',
  readFileSync(path.join(root, 'suyou', 'project.yaml'), 'utf8') === suyouBytes);
const afterSnapshot = snapshotRoot(root);
c.check('注册表根无 .tmp. 泄漏', assertNoTmpLeak(afterSnapshot));
c.check('既有条目集合不变（新增恰两条 fixture）',
  Object.keys(seededSnapshot).every((k) => afterSnapshot[k] === seededSnapshot[k]));

// ---- 6. TS 侧同构装载（同一隔离根） ----
process.env.SANDBAR_PROJECTS_DIR = root; // TS registryRoot() 每调用现读 env（模块头注契约）
const ts = await import(pathToFileURL(path.join(REPO_ROOT, 'server', 'dsh', 'suyou-projects.ts')).href);
const reg = ts.loadRegistry();
const tsKeys = reg.projects.map((p) => p.key);
c.check('TS 侧装载出全部新条目',
  ['zfix10a', 'zfix10b'].every((k) => tsKeys.includes(k)),
  `TS 实际=${JSON.stringify(tsKeys)}`);
c.check('TS 侧零隔离', (reg.quarantined || []).length === 0, JSON.stringify(reg.quarantined || []));
c.check('TS 侧含种子条目 suyou', tsKeys.includes('suyou'));
for (const k of ['zfix10a', 'zfix10b']) {
  const py = after.projects.find((p) => p.key === k);
  const t = reg.projects.find((p) => p.key === k);
  c.check(`双侧同构 ${k}（key/name/dirs 全等）`,
    py && t && py.name === t.name && JSON.stringify(py.dirs) === JSON.stringify(t.dirs),
    `py=${JSON.stringify(py)} ts=${JSON.stringify(t)}`);
}

// ---- 7. 尾腿（独立结算）：契约①b 排他性钉——先布置 credentials 再 add 应成功 ----
{
  const dirC = tmpRoot('fix10-proj-c-');
  const preDir = path.join(root, 'zfix10c');
  mkdirSync(preDir, { recursive: true });
  writeFileSync(path.join(preDir, 'credentials.yaml'), 'version: 1\nfixture: pre-placed\n');
  const addC = cliAdd(root, 'zfix10c', 'Fixture Gamma', [dirC]);
  const ok = addC.code === 0;
  c.check('契约①b：先布置 per-key 目录与 credentials 再 add 成功（排他锚 project.yaml 文件，'
    + '不锚目录——红=实现 O_EXCL 架在目录 mkdir 上，交仲裁：改闸 or 修约）',
    ok, `exit=${addC.code}\n${addC.out.slice(-400)}`);
  if (ok) {
    c.check('credentials 在位态报告与缺省态可辨（体检②如实亮）', addB.out !== addC.out);
    c.check('zfix10c 报告仍含 credentials 词汇', addC.out.includes('credentials'));
  }
}

c.finish();
