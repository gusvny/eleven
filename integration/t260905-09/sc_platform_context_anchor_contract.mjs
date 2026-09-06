// Integration scenario t260905-09 ① — 平台内容锚交付契约冻结（ro 静态面）。
//
// Intent (gray-box, L2 契约层):
//   平台自启上下文折叠的内容锚是「渲染面对平台恒定文本的承诺」——锚清单若与
//   取证夹具脱钩（改锚不回夹具/夹具漂移无人知），折叠件对着过时文本匹配，
//   故障形态=KI-042 同族「看守与真源脱钩→静默失明」。本场景冻结两层一致：
//   ① 锚真源模块（platform-context-anchors.ts）声明的每个锚，与 fixtures 平台
//     夹具首行逐字同步（夹具=锚的固定样本，头注=取证来源）；
//   ② 负向夹具（中段提及样本）的普通文本不在锚清单（误折防线在真源层在位）；
//   ③ 折叠件（context-fold.ts）对锚真源模块的引用在文（分类器接锚接线存在——
//     锚模块在而折叠件不消费=锚定了空气）。
//   与随票 smoke intent 级不同层：smoke 直测分类纯函数命中/容错（L1 内存面），
//   本条锚「交付物↔取证样本↔接线」三点一致性。与 t260904-07-charter-source-
//   contract intent 级不同层：那条冻结 charter marker 两端同源，本条冻结平台
//   锚真源与取证夹具（同一防漂移范式 KI-042 同族，守护对象不同）。
//
// High-level steps:
//   S0 锚真源模块在场性：文件缺失=fail（TDD 信号，实现落地前红属预期，
//      arbitrate/merge 期必须绿）。
//   S1 平台夹具逐字同步：fx-01/02/03（平台夹具）首行在锚模块文本中逐字在文。
//   S2 负向样本排除：fx-91（中段提及）首行不出现在锚模块（锚清单不含普通
//      消息文本）；fx-92（前缀粘贴）首行恰为锚=设计内声明（在文，非排除）。
//   S3 折叠件接线在文：context-fold.ts 引用锚模块（import 路径在文）。
//   S4 每平台夹具取证来源注在文（%%% 尾注非空——取证来源可追溯）。
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`；fail>0 或全腿 na → exit 1。
// 本条为纯静态面，无环境依赖腿（env_fail 不适用）。

import { readFileSync, existsSync } from 'node:fs';
import { loadFixtures, ANCHORS_MODULE, FOLD_MODULE, makeResults } from './lib_platform_context.mjs';

const { record, summarize } = makeResults();
const fx = loadFixtures();
const platformFx = fx.filter(f => /^fx-0/.test(f.name));
const negativeMid = fx.find(f => f.name.startsWith('fx-91'));
const prefixPaste = fx.find(f => f.name.startsWith('fx-92'));

// S0 锚真源模块在场
if (!existsSync(ANCHORS_MODULE)) {
  record('s0/anchors-module', 'fail', `${ANCHORS_MODULE} 不在——平台锚真源未落地（TDD 信号：实现段落地前红属预期，arbitrate/merge 期必须绿）`);
  summarize();
}
const anchorsSrc = readFileSync(ANCHORS_MODULE, 'utf8');
record('s0/anchors-module', 'pass', ANCHORS_MODULE);

// S1 锚↔夹具前缀双向同步（锚=前缀口径：夹具首行是锚文本的实例超串，如
// 「Instructions from: <路径>」形态的路径段可变，只能冻结前缀）：
//   正向：每个平台夹具首行 startsWith 至少一个在册锚（样本有锚可归）；
//   反向：每条在册锚至少有一个夹具样本背书（模块头注自声明「新增锚须带
//   fixtures 样本」——锚无样本=漂移无看守）。
const anchorTexts = [...anchorsSrc.matchAll(/text: '([^']+)'/g)].map(m => m[1]);
{
  if (anchorTexts.length === 0) {
    record('s1/anchor-list-parsable', 'fail', `${ANCHORS_MODULE} 抽不出锚文本（text: '…' 形态变更）——契约场景与真源形态脱钩，人审同步`);
    summarize();
  }
  record('s1/anchor-list-parsable', 'pass', `在册锚 ${anchorTexts.length} 条`);
  for (const f of platformFx) {
    if (!f.anchor) { record(`s1/${f.name}`, 'fail', '夹具无首行锚（空文件或结构坏）'); continue; }
    const hits = anchorTexts.filter(t => f.anchor.startsWith(t));
    record(`s1/${f.name}`, hits.length >= 1 ? 'pass' : 'fail',
      hits.length >= 1 ? `首行归锚 ${hits.length} 条：${JSON.stringify(hits[0]).slice(0, 48)}…`
                       : `夹具首行「${f.anchor.slice(0, 40)}…」不匹配任何在册锚——锚漂移或取样过时，人审同步双方`);
  }
  const orphan = anchorTexts.filter(t => !platformFx.some(f => f.anchor.startsWith(t)));
  record('s1/every-anchor-sampled', orphan.length === 0 ? 'pass' : 'fail',
    orphan.length === 0 ? '每条锚都有夹具样本背书（漂移有看守）'
                        : `锚无固定样本：${JSON.stringify(orphan)}——模块头注自声明「新增锚须带 fixtures 样本」失守，改锚措辞无人能红`);
}

// S2 负向样本：中段提及文本不归任何锚；前缀粘贴=设计内声明（恰归某锚）
{
  const leaked = negativeMid && negativeMid.anchor && anchorTexts.some(t => negativeMid.anchor.startsWith(t));
  record('s2/negative-mid-not-anchored', leaked ? 'fail' : 'pass',
    leaked ? '普通消息首行归了锚——中段提及误折防线在真源层失守' : '普通消息首行不归任何锚（误折防线在位）');
  const declared = prefixPaste && prefixPaste.anchor && anchorTexts.some(t => prefixPaste.anchor.startsWith(t));
  record('s2/prefix-paste-declared', declared ? 'pass' : 'fail',
    declared ? '前缀粘贴声明腿：粘贴首行恰归在册锚（设计内不可分辨限制有夹具背书）'
             : 'fx-92 首行与锚清单脱钩——声明性夹具失去锚定，前缀误折限制声明失效');
}

// S3 折叠件对锚模块的接线在文（import 引用，锚语义不锚写法：只查模块名在文）
{
  const foldSrc = existsSync(FOLD_MODULE) ? readFileSync(FOLD_MODULE, 'utf8') : '';
  const wired = /platform-context-anchors/.test(foldSrc);
  record('s3/fold-wires-anchors', wired ? 'pass' : 'fail',
    wired ? 'context-fold.ts 引用平台锚模块（分类器接锚接线在文）'
          : existsSync(FOLD_MODULE) ? 'context-fold.ts 未引用锚模块——锚定了空气（折叠件不消费锚=平台上下文永不折）'
          : `${FOLD_MODULE} 不在（真源面异常，本票改动面被删？）`);
}

// S4 取证来源注在文
for (const f of platformFx) {
  record(`s4/${f.name}`, f.provenance ? 'pass' : 'fail',
    f.provenance ? '取证来源注在文' : '%%% 取证来源尾注缺失——锚出处不可追溯（锚定稿纪律违约）');
}

summarize();
