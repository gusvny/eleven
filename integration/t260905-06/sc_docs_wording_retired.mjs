// sc_docs_wording_retired.mjs — t260905-06 场景③：UI 层「知识库」字样清零（静态 grep，无浏览器）。
//
// intent（灰盒，用户可感知行为；工单验收③「旧『知识库』字样清零（UI 层 grep）」+ 宿主令「suyou/知识库 退役」语义）：
//   「知识库」旧提法从界面层退役——工单台浏览器半源码（src/）与构建产物（lib/，
//   随仓提交、隔离台实际加载面）grep 子串 0 命中（代码行命中=用户可见旧提法=产品红；
//   bundle 内注释行不渲染到界面=观测不红，豁免口径见 T2——t260905-06 gen3 场景维护
//   对齐声明与实现，零断言改动）。
//   服务端宿主半（node.ts）不在界面层，知识库插件自身目录（server/plugins/knowledge/）
//   属写集外存量欠账（KI 已记），均不在本断言面。
//   实现落地前红属预期（TDD 信号：现源码含「知识库」字样），arbitrate/merge 期必须绿。
//
// high-level steps：
//   T1 界定断言面：server/plugins/workbench/src/**（源码）+ server/plugins/workbench/lib/**
//      （构建产物）。目录缺席=环境红（构建管线异常非产品红）。
//   T2 逐文件 grep「知识库」→ 计数必须 0；命中则逐条列出文件:行（可定位）。
//   T3 对照面（自证 grep 通道有效）：同一 grep 在写集外 knowledge 插件目录命中>0
//      ——证明 grep 通道本身能命中中文词（防「grep 挂了恒 0 命中」假绿）。
//
// 执行契约：stdout 末行 SUMMARY pass/fail/env_fail/na（三态=闸内无 SKIP 的现行定稿，旧 SKIP 语义退役）。
import { readdirSync, statSync, existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeResults } from '../t260904-17/lib_fix17.mjs';

const { record, summarize } = makeResults();

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const FACES = [
  ['src', path.join(REPO, 'server/plugins/workbench/src')],
  ['lib', path.join(REPO, 'server/plugins/workbench/lib')],
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else yield p;
  }
}

// T1 断言面在场（缺席=环境红：构建管线没跑，非字样退役达成）
for (const [tag, dir] of FACES) {
  if (!existsSync(dir)) {
    record(`face/${tag}`, 'env_fail', `断言面缺席：${dir} 不存在（构建产物未生成=环境红）`);
  } else {
    record(`face/${tag}`, 'pass', dir);
  }
}

// T2 界面层 0 命中
let hits = [];
let scanned = 0;
for (const [, dir] of FACES) {
  if (!existsSync(dir)) continue;
  for (const f of walk(dir)) {
    if (!/\.(mjs|js|ts|tsx|css|html|json)$/.test(f)) continue;
    scanned += 1;
    const lines = readFileSync(f, 'utf8').split('\n');
    lines.forEach((line, i) => {
      // 注释行豁免（lib 面 bundle 保留的 knowledge markdown.ts 头注不渲染到界面，
      // 且 knowledge 源文件写集外）：仅代码行命中=产品红；注释命中记观测不红。
      const isComment = /^\s*(\/\/|\/\*|\*)/.test(line.trim()) || line.trim().startsWith('*/');
      if (line.includes('知识库') && !isComment) hits.push(`${path.relative(REPO, f)}:${i + 1}: ${line.trim().slice(0, 100)}`);
    });
  }
}
record('ui/knowledge-word-zero', hits.length === 0,
  hits.length === 0 ? `「知识库」0 命中（扫 ${scanned} 文件）` : `「知识库」${hits.length} 命中（界面层退役未达成，实现落地前红属预期）：\n${hits.slice(0, 20).join('\n')}`);

// T3 对照面自证（grep 通道有效性；knowledge 插件=写集外存量，命中属预期）
const probeDir = path.join(REPO, 'server/plugins/knowledge');
if (!existsSync(probeDir)) {
  record('probe/knowledge-dir', 'env_fail', `对照面缺席：${probeDir} 不存在`);
} else {
  let probeHits = 0;
  for (const f of walk(probeDir)) {
    if (!/\.(mjs|js|ts|tsx|css|html)$/.test(f)) continue;
    if (readFileSync(f, 'utf8').includes('知识库')) probeHits += 1;
  }
  record('probe/knowledge-word-present', probeHits > 0, `knowledge 插件（写集外存量）命中 ${probeHits} 文件——grep 通道自证有效`);
}

summarize();
