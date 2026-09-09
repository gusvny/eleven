// t260901-11 M0 integration test: contract document existence and structure
// (black-box documentation baseline)
// Under acceptance: docs/design/metrics-api契约v1.md
//  - exists, frontmatter complete (title/category/tags/status/updated)
//  - the four-section structure Problem → Requirement → Nongoal → Proposal
//    present and ordered
//  - the contract exemption statement at the top of the document
//  - the trailing source tag `> 来源立项：metrics`
// Missing document = FAIL (this test guards deliverable existence and never
// waves a missing environment through; the three-state contract §7.3 has no
// legacy bypass semantics inside the gate)

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

  // Four-section structure, ordered Problem → Requirement → Nongoal → Proposal
  const headings = [...text.matchAll(/^#{2,3} (.+)$/gm)].map(m => m[1]);
  const idx = (re) => headings.findIndex(h => re.test(h));
  const iP = idx(/Problem/i), iR = idx(/Requirement/i), iN = idx(/Nongoal/i), iPr = idx(/Proposal/i);
  check('四段齐全', iP >= 0 && iR >= 0 && iN >= 0 && iPr >= 0,
    `Problem=${iP} Requirement=${iR} Nongoal=${iN} Proposal=${iPr}`);
  check('四段有序 P→R→N→Pr', iP < iR && iR < iN && iN < iPr);

  // Contract exemption statement (exempts the self-check item "Proposal has
  // no API names / field names")
  check('写作指南豁免声明存在',
    /豁免/.test(text) && /字段级冻结/.test(text));

  // Source tag
  check('来源立项标签', text.includes('> 来源立项：metrics'));

  // Contract pointer back-reference (one of the three deltas against the UI plan)
  const ui = existsSync(UI) ? readFileSync(UI, 'utf8') : '';
  check('UI 规划含契约指针（字段级契约以契约为准）',
    /metrics-api契约v1/.test(ui), 'UI 规划未引用契约文档');
} else {
  check('契约文档内容可检（前置存在）', false, '文档缺失，跳过内容断言');
}

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
