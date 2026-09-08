// sc_add_scaffold_faultlines.mjs — t260906-01 场景②：容器脚手架故障面对抗。
//
// intent（用户可感知行为，工单验收「已存在目录接入行为一字不变（幂等零覆盖）」+ 方案 R2 三态）：
//   A. 已存在目录接入=树快照逐字节零新增零覆盖（自带自定义 model-routes.yaml 与
//      marker 文件原样不动、JSON scaffold.created 空）；
//   B. 脚手架源表缺失（--root 桩树无 model-routes.yaml）= fail-closed 红 + 点名源路径
//      + 注册表/新建根零残留（回滚含整根移除），绝不吞成空拷贝；
//   C. 源表畸形（缺 default:/roles: 结构锚）= 同上红 + 点名「畸形」；
//   D. 代建×防呆闸交互：新根为已注册根的「尚不存在祖先」仍被闸 d 拒——拒后祖先目录
//      不被代建、既有根与注册表零变更（闸序在代建之前的锚）。
//   （F1 并发同根异 key TOCTOU 为已登记预存洞，本票不修、不入闸——并发注入防假红。）
//
// 台别：SANDBAR_PROJECTS_DIR 隔离注册表根；源表注入=--root 指桩树（shared.py 拷贝自
// 真源，paths.root=桩树 ⇒ scaffold 源表=桩树下同族路径）；零 3099/7233/8233 接触。
// 实现落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import {
  REPO_ROOT, tmpRoot, sbEnv, runCli, makeChecks, treeSnapshot,
  writeProjectEntry, makeStubRoot,
} from '../t260904-14/lib_fix14.mjs';

const c = makeChecks('t260906-01 容器脚手架故障面');
delete process.env.SANDBAR_PROJECTS_YAML;

const add = (root, key, name, dir, extra = []) => runCli(
  ['project', 'add', '--key', key, '--name', name, '--dir', dir, ...extra],
  sbEnv(root));

// ---- A：已存在目录=零覆盖零新增 ----
{
  const regRoot = tmpRoot('t260906-reg3-');
  const projRoot = path.join(tmpRoot('t260906-area3-'), 'exists');
  mkdirSync(path.join(projRoot, 'server'), { recursive: true });
  writeFileSync(path.join(projRoot, 'marker.txt'), 'own data\n');
  writeFileSync(path.join(projRoot, 'server', 'model-routes.yaml'), 'custom: table\n');

  const before = treeSnapshot(projRoot);
  const r = runCli(['project', 'add', '--key', 'existk', '--name', 'Exist', '--dir', projRoot, '--json'],
    sbEnv(regRoot));
  c.check('已存在目录 add 成功', r.code === 0, `exit=${r.code}\n${r.out.slice(-400)}`);
  c.check('树快照逐字节一致（零新增零覆盖）',
    JSON.stringify(before) === JSON.stringify(treeSnapshot(projRoot)),
    'project root mutated');
  let j = null;
  try { j = JSON.parse(r.out.slice(r.out.indexOf('{'))); } catch { /* 下方判 */ }
  c.check('scaffold.created 空（已存在目录不落脚手架）',
    j?.scaffold?.created !== undefined && j.scaffold.created.length === 0,
    JSON.stringify(j?.scaffold));
  c.check('root_created=false', j?.root_created === false, JSON.stringify(j?.root_created));
  c.check('自带自定义表内容原样', readFileSync(path.join(projRoot, 'server', 'model-routes.yaml'), 'utf8') === 'custom: table\n');
}

// ---- B/C：源表缺失/畸形=红+点名源路径+零残留（--root 桩树注入）----
{
  // B 源表缺失：桩树无 server/model-routes.yaml
  const stubMiss = makeStubRoot();
  const regRoot1 = tmpRoot('t260906-reg4-');
  mkdirSync(regRoot1, { recursive: true });
  writeFileSync(path.join(regRoot1, '.migrated'), 'source: fixture\n');
  const newRoot1 = path.join(tmpRoot('t260906-area4-'), 'fresh');
  const r1 = runCli(['--root', stubMiss.stubRoot, 'project', 'add', '--key', 'missk', '--name', 'M',
    '--dir', newRoot1, '--json'], sbEnv(regRoot1, { FIX14_CTRL: stubMiss.ctrlPath }));
  c.check('源表缺失=红', r1.code !== 0, `exit=${r1.code}\n${r1.out.slice(-400)}`);
  c.check('报错点名源路径与缺失语义',
    r1.out.includes('model-routes.yaml') && (r1.out.includes('源表不可读') || r1.out.includes('缺失')),
    r1.out.slice(-400));
  c.check('注册表零残留（无 key 目录）', !existsSync(path.join(regRoot1, 'missk')), regRoot1);
  c.check('新建根被回滚（不存在）', !existsSync(newRoot1), newRoot1);

  // C 源表畸形：桩树有表但缺 roles: 结构锚
  const stubBad = makeStubRoot();
  mkdirSync(path.join(stubBad.stubRoot, 'server'), { recursive: true });
  writeFileSync(path.join(stubBad.stubRoot, 'server', 'model-routes.yaml'),
    '# 畸形桩：两节结构锚均不在场\nalpha: 1\nbeta: 2\n'); // 注意注释本身不得含结构锚字样（字节级锚检查）
  const regRoot2 = tmpRoot('t260906-reg5-');
  mkdirSync(regRoot2, { recursive: true });
  writeFileSync(path.join(regRoot2, '.migrated'), 'source: fixture\n');
  const newRoot2 = path.join(tmpRoot('t260906-area5-'), 'fresh2');
  const r2 = runCli(['--root', stubBad.stubRoot, 'project', 'add', '--key', 'badk', '--name', 'B',
    '--dir', newRoot2, '--json'], sbEnv(regRoot2, { FIX14_CTRL: stubBad.ctrlPath }));
  c.check('源表畸形=红', r2.code !== 0, `exit=${r2.code}\n${r2.out.slice(-400)}`);
  c.check('报错点名「畸形」+源路径', r2.out.includes('畸形') && r2.out.includes('model-routes.yaml'),
    r2.out.slice(-400));
  c.check('畸形腿注册表零残留', !existsSync(path.join(regRoot2, 'badk')), regRoot2);
  c.check('畸形腿新建根被回滚', !existsSync(newRoot2), newRoot2);
}

// ---- D：代建×闸 d 交互（新根=已注册根的「尚不存在」祖先 → 拒且零代建）----
// 注册条目可指向盘上不存在的路径（装载器只解析不 stat）——正是这里允许我们把
// 祖先路径钉成「此刻不存在」：若代建 mkdir 先于闸 d 执行，祖先会被建出来=闸序破坏。
{
  const regRoot = tmpRoot('t260906-reg6-');
  writeFileSync(path.join(regRoot, '.migrated'), 'source: fixture\n');
  const ghostAncestor = path.join(tmpRoot('t260906-area8-'), 'outer', 'wrap'); // 整链均不存在
  writeProjectEntry(regRoot, 'hz', 'Hz', [path.join(ghostAncestor, 'inner')]);
  const beforeReg = JSON.stringify(treeSnapshot(regRoot)); // 基线=add 尝试前（fixture 就位后）

  const r = add(regRoot, 'ghostk', 'Ghost', ghostAncestor);
  c.check('新根=已注册根祖先（路径尚不存在）仍被闸 d 拒', r.code !== 0,
    `exit=${r.code}\n${r.out.slice(-400)}`);
  c.check('拒收文案点名交叉与两个 key',
    r.out.includes('ghostk') && r.out.includes('hz'), r.out.slice(-400));
  c.check('祖先路径未被代建（不存在=闸序在代建之前的锚）', !existsSync(ghostAncestor), ghostAncestor);
  c.check('注册表零残留（无 ghostk）', !existsSync(path.join(regRoot, 'ghostk')), regRoot);
  c.check('注册表快照不变（拒收零写入）',
    JSON.stringify(treeSnapshot(regRoot)) === beforeReg, 'registry mutated');
}

c.finish();
