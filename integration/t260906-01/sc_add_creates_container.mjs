// sc_add_creates_container.mjs — t260906-01 场景①：新目录容器代建一步接入旅程。
//
// intent（用户可感知行为，工单验收「新目录接入=建目录+脚手架+注册一步完成且报告列生成物」）：
//   根目录不存在（含父目录链）时 `sandbar project add` 一次成功——
//   A. 目录代建（mkdir parents，含父目录链）+ 容器脚手架全清单在盘；
//   B. --json 机器口径：root_created=true、scaffold.created 逐项可判；
//   C. 模板表与引擎仓真源 sha256 逐字节一致（同源模板不造两份）；
//   D. 接入报告（JSON warnings + 文本两形态）含「容器未含 git 仓库」提示（container-no-git）；
//   E. 全程零 git 调用（PATH 注入记录型 git 桩：调用日志空 + 项目树无 .git）；
//   F. 注册条目落盘（key/dirs 可读回）。
//
// 台别：SANDBAR_PROJECTS_DIR 隔离注册表根（临时目录）+ 假 git PATH 桩；零 3099/7233/8233
// 接触、不连 Temporal、只写自建临时目录。实现落地前本场景红属预期（TDD 信号），
// arbitrate/merge 期必须绿。
import { createHash } from 'node:crypto';
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import {
  REPO_ROOT, tmpRoot, sbEnv, runCli, makeChecks, treeSnapshot,
} from '../t260904-14/lib_fix14.mjs';

const c = makeChecks('t260906-01 新目录容器代建一步接入');
delete process.env.SANDBAR_PROJECTS_YAML;

const ENGINE_TABLE = path.join(REPO_ROOT, 'server', 'model-routes.yaml');
const sha16 = (p) => createHash('sha256').update(readFileSync(p)).digest('hex').slice(0, 32);

// 假 git 桩：被调用即记账（记录到 calls.log）并退出 0——记账面让「零 git 调用」可机械判定。
const fakeBin = tmpRoot('t260906-gitstub-');
const gitCalls = path.join(fakeBin, 'calls.log');
writeFileSync(path.join(fakeBin, 'git'),
  `#!/bin/sh\necho "cwd=$(pwd) args=$*" >> "${gitCalls}"\nexit 0\n`);
chmodSync(path.join(fakeBin, 'git'), 0o755);
const envWithFakeGit = (regRoot, extra = {}) =>
  sbEnv(regRoot, { PATH: fakeBin + path.delimiter + process.env.PATH, ...extra });

const EXPECTED_FILES = [
  'CLAUDE.md',
  'notes/epics/.gitkeep',
  'notes/discussions/.gitkeep',
  'docs/.gitkeep',
  'server/model-routes.yaml',
];

// ---- A/B/C/E/F：--json 深路径代建（父目录链也不存在）----
{
  const regRoot = tmpRoot('t260906-reg1-');
  const projRoot = path.join(tmpRoot('t260906-area1-'), 'deep', 'nested', 'myproj');
  const r = runCli(['project', 'add', '--key', 'deepk', '--name', 'Deep', '--dir', projRoot, '--json'],
    envWithFakeGit(regRoot));
  c.check('不存在根（含父链）add 成功 exit 0', r.code === 0, `exit=${r.code}\n${r.out.slice(-500)}`);

  let j = null;
  try { j = JSON.parse(r.out.slice(r.out.indexOf('{'))); } catch { /* 下方判 */ }
  c.check('--json 可解析且 ok', j !== null && j.ok === true, r.out.slice(-300));
  c.check('root_created=true（代建标记）', j?.root_created === true, JSON.stringify(j?.root_created));
  c.check('scaffold.created 含全部生成物',
    EXPECTED_FILES.every((f) => (j?.scaffold?.created ?? []).includes(f)),
    JSON.stringify(j?.scaffold));
  c.check('scaffold.skipped 空（新目录无跳过）', (j?.scaffold?.skipped ?? []).length === 0,
    JSON.stringify(j?.scaffold?.skipped));
  c.check('warnings 含 container-no-git（容器无 git 提示）',
    (j?.warnings ?? []).some((w) => w.code === 'container-no-git' && w.message.includes('未含 git 仓库')),
    JSON.stringify(j?.warnings));

  c.check('目录代建在盘（含父链）', existsSync(projRoot) && existsSync(path.dirname(projRoot)),
    projRoot);
  c.check('脚手架生成物逐项在盘', EXPECTED_FILES.every((f) => existsSync(path.join(projRoot, f))),
    JSON.stringify(EXPECTED_FILES.map((f) => existsSync(path.join(projRoot, f)))));
  c.check('模板表与引擎仓真源逐字节一致（sha256）',
    sha16(path.join(projRoot, 'server', 'model-routes.yaml')) === sha16(ENGINE_TABLE),
    'copy != engine source');
  c.check('CLAUDE.md 骨架含接力入口与无 git 须知',
    readFileSync(path.join(projRoot, 'CLAUDE.md'), 'utf8').includes('未含 git 仓库'));

  const noGit = (dir) => readdirSync(dir, { withFileTypes: true })
    .every((e) => e.name !== '.git' && (!e.isDirectory() || noGit(path.join(dir, e.name))));
  c.check('项目树无 .git（容器式：全程无 git 操作）', existsSync(projRoot) && noGit(projRoot));
  c.check('零 git 调用（假 git 桩记账为空）', !existsSync(gitCalls),
    existsSync(gitCalls) ? readFileSync(gitCalls, 'utf8').slice(-300) : '');

  const entry = path.join(regRoot, 'deepk', 'project.yaml');
  c.check('注册条目落盘且含 key/dirs',
    existsSync(entry) && readFileSync(entry, 'utf8').includes('key: deepk')
      && readFileSync(entry, 'utf8').includes(projRoot),
    entry);
}

// ---- D：文本形态报告（生成物清单 + 代建标注 + 无 git 提示）----
{
  const regRoot = tmpRoot('t260906-reg2-');
  const projRoot = path.join(tmpRoot('t260906-area2-'), 'plain', 'proj');
  const r = runCli(['project', 'add', '--key', 'plaink', '--name', 'Plain', '--dir', projRoot],
    envWithFakeGit(regRoot));
  c.check('文本形态 add 成功', r.code === 0, `exit=${r.code}\n${r.out.slice(-400)}`);
  c.check('报告含「生成物清单」', r.out.includes('生成物清单'), r.out.slice(-500));
  c.check('报告标注「本次代建，含父目录」', r.out.includes('本次代建，含父目录'), r.out.slice(-500));
  c.check('报告含 container-no-git 提示与「未含 git 仓库」',
    r.out.includes('container-no-git') && r.out.includes('未含 git 仓库'), r.out.slice(-500));
}

// ---- E 补充：假 git 桩在场时注册表侧同样零 git 调用（第二条子用例共用同一桩）----
{
  c.check('两子用例累计零 git 调用', !existsSync(gitCalls),
    existsSync(gitCalls) ? readFileSync(gitCalls, 'utf8').slice(-300) : '');
}

c.finish();
