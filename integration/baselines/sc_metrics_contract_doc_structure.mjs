// t260901-11 M0 集成测试：契约文档存在性与结构（黑盒文档基线）
// 验收对象：docs/design/metrics-api契约v1.md
//  - 存在、frontmatter 齐全（title/category/tags/status/updated）
//  - 四段结构 Problem → Requirement → Nongoal → Proposal 齐全且有序
//  - 契约豁免声明在文档开头
//  - 文末来源标签 `> 来源立项：metrics`
// 文档缺失 = FAIL（本测试守交付物存在性，不做依赖 SKIP）

import { readFileSync, existsSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const DOC = 'docs/design/metrics-api契约v1.md';
const UI = 'docs/design/metrics面板ui规划.md';

check('契约文档存在', existsSync(DOC), `${DOC} 不存在`);
check('UI 规划存在（被指针引用方）', existsSync(UI));

if (existsSync(DOC)) {
  const text = readFileSync(DOC, 'utf8');

  // frontmatter
  const fm = text.match(/^---\n([\s\S]*?)\n---/);
  check('frontmatter 存在', !!fm);
  if (fm) {
    for (const f of ['title:', 'category:', 'tags:', 'status:', 'updated:']) {
      check(`frontmatter 含 ${f}`, fm[1].includes(f));
    }
  }

  // 四段结构，顺序 Problem → Requirement → Nongoal → Proposal
  const headings = [...text.matchAll(/^#{2,3} (.+)$/gm)].map(m => m[1]);
  const idx = (re) => headings.findIndex(h => re.test(h));
  const iP = idx(/Problem/i), iR = idx(/Requirement/i), iN = idx(/Nongoal/i), iPr = idx(/Proposal/i);
  check('四段齐全', iP >= 0 && iR >= 0 && iN >= 0 && iPr >= 0,
    `Problem=${iP} Requirement=${iR} Nongoal=${iN} Proposal=${iPr}`);
  check('四段有序 P→R→N→Pr', iP < iR && iR < iN && iN < iPr);

  // 契约豁免声明（豁免「Proposal 无 API 名/字段名」自查项）
  check('写作指南豁免声明存在',
    /豁免/.test(text) && /字段级冻结/.test(text));

  // 来源标签
  check('来源立项标签', text.includes('> 来源立项：metrics'));

  // 契约指针回指（对 UI 规划的三处 delta 之一）
  const ui = existsSync(UI) ? readFileSync(UI, 'utf8') : '';
  check('UI 规划含契约指针（字段级契约以契约为准）',
    /metrics-api契约v1/.test(ui), 'UI 规划未引用契约文档');
} else {
  check('契约文档内容可检（前置存在）', false, '文档缺失，跳过内容断言');
}

console.log(`SUMMARY pass=${pass} skip=0 fail=${fail}`);
process.exit(fail > 0 ? 1 : 0);
