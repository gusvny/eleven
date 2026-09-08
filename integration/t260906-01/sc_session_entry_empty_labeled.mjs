// sc_session_entry_empty_labeled.mjs — t260906-01 场景④：空项目会话入口可发现。
//
// intent（用户可感知行为，工单验收「接入后新会话入口可发现」——只读探针实证 24px 无字
// 小方块「钮在但认不出」）：
//   A. 账册空=「＋ 新建会话」带字按钮：wb-psess-new-labeled 变体 + tabs.length===0
//      条件分支在 src 在场；
//   B. 同批 lib/client.js 锚在场——lib 锚=bundle 重建看守（KI-052：客户端半每次请求
//      从盘现读，盘上 bundle 旧=改了也看不见）；
//   C. data-wb-psess-new 数据锚保留（有 tab 恢复 24px 方块形态，既有 smoke 旧断言
//      project-sessions.mjs S3 不回归）；
//   D. 接入弹层预检口径退役「存在性」措辞、改「将自动创建」（代建口径同步）。
//
// 台别：src+lib 双锚灰盒（同 project-sessions.mjs S3 守卫手法）；真 DOM 呈现由合并闸
// ui_evidence 截图证据面覆盖（KI-036/044 家族），本场景不重复 browser 腿。
// 实现落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { makeChecks } from '../t260904-14/lib_fix14.mjs';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO_ROOT = path.resolve(HERE, '..', '..');
const c = makeChecks('t260906-01 空项目会话入口可发现');
delete process.env.SANDBAR_PROJECTS_YAML;

const WB = path.join(REPO_ROOT, 'server', 'plugins', 'workbench');
const srcRow = path.join(WB, 'src', 'client', 'project-session-row.tsx');
const srcModal = path.join(WB, 'src', 'client', 'project-modals.tsx');
const libClient = path.join(WB, 'lib', 'client.js');

c.check('workbench 客户端源与 lib 产物在位',
  existsSync(srcRow) && existsSync(srcModal) && existsSync(libClient),
  [srcRow, srcModal, libClient].filter((p) => !existsSync(p)).join(', '));

const row = readFileSync(srcRow, 'utf8');
const modal = readFileSync(srcModal, 'utf8');
const lib = readFileSync(libClient, 'utf8');

// ---- A：空态带字按钮（src 源锚）----
c.check('「＋ 新建会话」带字文案在 src', row.includes('新建会话'), 'label missing');
c.check('labeled 变体类 wb-psess-new-labeled 在 src', row.includes('wb-psess-new-labeled'));
c.check('空态条件分支 tabs.length === 0 在 src', /tabs\.length\s*===\s*0/.test(row));

// ---- B：lib 产物同批（bundle 重建看守，KI-052 错窗防线）----
c.check('「新建会话」锚在 lib/client.js', lib.includes('新建会话'), 'lib bundle 未重建？');
c.check('wb-psess-new-labeled 锚在 lib/client.js', lib.includes('wb-psess-new-labeled'),
  'lib bundle 未重建？');

// ---- C：数据锚与方块形态保留（有 tab 恢复现行形态）----
c.check('data-wb-psess-new 数据锚保留', row.includes('data-wb-psess-new'));
c.check('24px 方块基准样式保留（wb-psess-new 24×24）',
  /width:\s*24px/.test(row) && /height:\s*24px/.test(row));

// ---- D：接入弹层代建口径 ----
// 「存在性」退役锚定渲染文案：注释行豁免（内部注释不属用户可感知面，归 developer L1）。
const offenders = modal.split('\n')
  .filter((l) => l.includes('存在性') && !l.trim().startsWith('*') && !l.trim().startsWith('/*'));
c.check('弹层渲染文案无「存在性」旧口径（注释行豁免）', offenders.length === 0,
  offenders.join(' | ').slice(0, 300));
c.check('弹层预检口径含「自动创建」', modal.includes('自动创建'), '新口径缺');
c.check('弹层口径锚同批在 lib/client.js', lib.includes('自动创建'), 'lib bundle 未重建？');

c.finish();
