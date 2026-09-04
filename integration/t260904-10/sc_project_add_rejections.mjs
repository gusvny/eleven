// sc_project_add_rejections.mjs — t260904-10 场景②：add 拒收面全枚举 + 并发同 key + remove 骨架。
//
// intent（用户可感知行为）：宿主接错参数时，每条拒收路径都「报错可辨（点名原因）+ 注册表
// 字节级零残留」；已注册 key 重跑同判（幂等语义=拒收，不是成功）；并发同 key 双 add 恰
// 一成一拒（无静默覆盖）；remove 本票只交付骨架（恒红点名，注册表不动）。
//
// high-level steps：
//   1. 隔离根 fixture：.migrated 预置 + 手写条目 seedalpha + 隔离条目 qbad（schema v9 畸形），
//      快照基线；此后每条拒收腿断言根快照逐字节不变、无 .tmp. 泄漏；
//   2. key 白名单：大写/下划线/首字符中划线/42 字符拒；41 字符（正则上界）收；
//   3. 根目录形态：缺参（usage）/相对路径/不存在/是文件非目录/多目录输入（epic 验收2：
//      语义化拒收须点名单根模型——裸用法错不算，此腿红=方案窄化发现交仲裁）；
//   4. 已注册重跑同判：两次输出与出口码全等；隔离同名 qbad 拒收；
//   5. 根交叉与互为父子：新根=既有根父目录 / 子目录 / 恰等——均拒且报两个 key；
//   6. legacy：SUYOU_PROJECTS_YAML 在位 → 拒收指路（文案含 env 名），per-key 根与 legacy 文件不动；
//   7. name：空/含 #/含换行拒（文案点名 name）；首尾空白 trim 后收（读回验证=Padded Name）；
//   8. 并发同 key 双 add（不同 name/dir）：恰一成一拒，注册表恰一条目且 name/dirs 自洽不混写；
//   9. remove 点位稳定钉：输出点名 remove、无裸 traceback、注册表不动（票①骨架恒红 /
//      票②真实现，两期皆存活——不钉临时态）。
//
// 出口码口径：语义拒收（FailClosed 通道）钉 exit=1；参数形态错（argparse 面）只钉非 0。
// 安全红线：零 3099/7233/8233 接触、不连 Temporal、只写自建临时目录。
// 实现段落地前本场景红属预期（TDD 信号），arbitrate/merge 期必须绿。
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import {
  REPO_ROOT, SANDBAR, tmpRoot, sbEnv, runCli, cliAdd, cliRemove, pyRegistry, snapshotRoot,
  assertNoTmpLeak, makeChecks,
} from './lib_fix10.mjs';

const c = makeChecks('t260904-10 project add 拒收面');
delete process.env.SUYOU_PROJECTS_YAML;

// ---- 1. fixture：隔离根 + 手写条目 + 隔离条目 ----
const root = tmpRoot('fix10-rej-root-');
writeFileSync(path.join(root, '.migrated'), 'source: fixture\n');
const seedDir = tmpRoot('fix10-seed-dir-');
const fixtureArea = path.dirname(root); // 同一临时区，绝对路径
{
  const d = path.join(root, 'seedalpha');
  mkdirSync(d, { recursive: true });
  writeFileSync(path.join(d, 'project.yaml'), [
    'schema: v1', 'project:', '  - key: seedalpha', '    name: Seed Alpha',
    '    dirs:', `      - ${seedDir}`, '',
  ].join('\n'));
  const q = path.join(root, 'qbad');
  mkdirSync(q, { recursive: true });
  writeFileSync(path.join(q, 'project.yaml'), 'schema: v9\nproject:\n  - key: qbad\n');
}
const add = (key, name, dirs, extraEnv = {}) => cliAdd(root, key, name, dirs, extraEnv);
// 拒收腿的零残留基线比对（成功腿推进基线；详见各腿注释）
let baseline = snapshotRoot(root);
function checkClean(label) {
  const now = snapshotRoot(root);
  c.check(`零残留·${label}`, JSON.stringify(now) === JSON.stringify(baseline),
    `基线=${JSON.stringify(baseline)}\n现况=${JSON.stringify(now)}`);
  c.check(`零 tmp 泄漏·${label}`, assertNoTmpLeak(now));
}

// ---- 2. key 白名单（--dir 用真实存在的无关目录，隔离 key 闸——防目录闸先触发假红） ----
const keyLegDir = tmpRoot('fix10-keydir-');
for (const [label, key] of [
  ['大写', 'Zupper'], ['下划线', 'has_underscore'], ['首字符中划线', '-leading'],
  ['42 字符超上界', 'a'.repeat(42)],
]) {
  const r = add(key, 'X', [keyLegDir]);
  c.check(`白名单拒收·${label}`, r.code !== 0, `exit=${r.code}`);
  c.check(`白名单文案点名 key·${label}`, r.out.toLowerCase().includes('key'), r.out.slice(-300));
  checkClean(label);
}
{
  const boundDir = tmpRoot('fix10-bound-'); // 上界成功腿：根必须真实存在，隔离长度闸
  const r = add('a'.repeat(41), 'Boundary Max', [boundDir]);
  c.check('白名单上界 41 字符收（正则 {0,40}+首字符）', r.code === 0,
    `exit=${r.code}\n${r.out.slice(-400)}`);
  baseline = snapshotRoot(root);
}

// ---- 3. 根目录形态 ----
{
  const r = runCli(['project', 'add', 'zfixnokey'], sbEnv(root)); // 缺必填参数（用法错，旗标/位置两拼写面通吃）
  c.check('缺必填参数拒收（非 0）', r.code !== 0, `exit=${r.code}`);
  checkClean('缺参');
}
{
  const rel = path.join('some', 'relative', 'dir');
  const r = add('zfixrel', 'Rel', [rel]);
  c.check('相对路径拒收', r.code !== 0, `exit=${r.code}`);
  checkClean('相对路径');
}
{
  const r = add('zfixghost', 'Ghost', ['/nonexistent/fix10/zzz']);
  c.check('不存在目录拒收', r.code !== 0, `exit=${r.code}`);
  checkClean('不存在目录');
}
{
  const filePath = path.join(fixtureArea, 'fix10-just-a-file.txt');
  writeFileSync(filePath, 'not a dir\n');
  const r = add('zfixfile', 'FileAsDir', [filePath]);
  c.check('是文件非目录拒收', r.code !== 0, `exit=${r.code}`);
  checkClean('文件冒充目录');
}
{
  // epic 验收2 明文：多条输入是独立拒收路径且「文案点名原因（单根模型）」——
  // 裸 argparse 用法错（unrecognized arguments）不点名单根模型，不算语义化拒收。
  // 此腿红=方案窄化发现（单位置旗标面下多目录不可表达），交仲裁：扩面 or 修约。
  const d1 = tmpRoot('fix10-md1-');
  const d2 = tmpRoot('fix10-md2-');
  const r = cliAdd(root, 'zfixmulti', 'Multi', [d1, d2]);
  c.check('多目录输入拒收（非 0）', r.code !== 0, `exit=${r.code}`);
  c.check('多目录拒收语义可辨（epic 验收2：文案点名单根模型/多目录，裸用法错不算）',
    /单根|多目录|multiple/i.test(r.out),
    `当前输出=${r.out.slice(-300)}`);
  checkClean('多目录');
}

// ---- 4. 已注册幂等同判 + 隔离同名 ----
{
  const d = tmpRoot('fix10-dup-dir-');
  const r1 = add('seedalpha', 'Dup', [d]);
  const r2 = add('seedalpha', 'Dup', [d]);
  c.check('已注册拒收', r1.code !== 0, `exit=${r1.code}`);
  c.check('语义拒收走 FailClosed 通道 exit=1', r1.code === 1, `exit=${r1.code}`);
  c.check('文案点名已注册 key', r1.out.includes('seedalpha'), r1.out.slice(-300));
  c.check('幂等重跑同判同文案（两次输出全等）',
    r1.code === r2.code && r1.out === r2.out,
    `out1=${r1.out.slice(-200)}\nout2=${r2.out.slice(-200)}`);
  checkClean('已注册');
}
{
  const d = tmpRoot('fix10-q-dir-');
  const r = add('qbad', 'Q', [d]);
  c.check('隔离条目同名拒收', r.code !== 0, `exit=${r.code}`);
  c.check('文案点名隔离 key', r.out.includes('qbad'), r.out.slice(-300));
  checkClean('隔离同名');
}

// ---- 5. 根交叉与互为父子（报两个 key） ----
{
  // 专用嵌套 fixture：zfixnbase 注册 nestBase/inner，zfixnest 给 nestBase（父目录）
  // ——父子命中唯一（zfixnbase），不与其它 fixture 目录共享父级产生多命中歧义。
  const nestBase = tmpRoot('fix10-nestbase-');
  const inner = path.join(nestBase, 'inner');
  mkdirSync(inner, { recursive: true });
  const okBase = add('zfixnbase', 'Nbase', [inner]);
  c.check('嵌套前置：zfixnbase 成功接入', okBase.code === 0,
    `exit=${okBase.code}\n${okBase.out.slice(-300)}`);
  baseline = snapshotRoot(root);
  const r = add('zfixnest', 'Nest', [nestBase]); // 既有根的父目录 → 互为父子
  c.check('父目录嵌套拒收', r.code !== 0, `exit=${r.code}`);
  c.check('嵌套文案报既有 key', r.out.includes('zfixnbase'), r.out.slice(-300));
  c.check('嵌套文案报新 key', r.out.includes('zfixnest'), r.out.slice(-300));
  c.check('交叉拒收走 FailClosed 通道 exit=1', r.code === 1, `exit=${r.code}`);
  checkClean('父目录嵌套');
}
{
  const cdir = tmpRoot('fix10-cdir-');
  const ok = add('zfixc', 'Cee', [cdir]);
  c.check('交叉前置：zfixc 成功接入', ok.code === 0, `exit=${ok.code}\n${ok.out.slice(-300)}`);
  baseline = snapshotRoot(root); // 基线推进到含 zfixc
  const sub = path.join(cdir, 'sub');
  mkdirSync(sub, { recursive: true });
  const r1 = add('zfixd', 'Dee', [sub]);
  c.check('子目录嵌套拒收', r1.code !== 0, `exit=${r1.code}`);
  c.check('子嵌套报两个 key（zfixc+zfixd）',
    r1.out.includes('zfixc') && r1.out.includes('zfixd'), r1.out.slice(-300));
  const r2 = add('zfixsame', 'Same', [cdir]); // 恰等=交叉
  c.check('根恰等拒收', r2.code !== 0, `exit=${r2.code}`);
  c.check('恰等报两个 key（zfixc+zfixsame）',
    r2.out.includes('zfixc') && r2.out.includes('zfixsame'), r2.out.slice(-300));
  checkClean('子目录嵌套与恰等');
}

// ---- 6. legacy 拒收指路 ----
{
  const legacyFile = path.join(fixtureArea, 'fix10-legacy-projects.yaml');
  const legacyBody = 'projects:\n  - key: legacyone\n    name: Legacy One\n    dirs:\n      - '
    + path.join(fixtureArea, 'legacyone-dir') + '\n';
  writeFileSync(legacyFile, legacyBody);
  const d = tmpRoot('fix10-legacy-dir-');
  const r = add('zfixlegacy', 'L', [d], { SUYOU_PROJECTS_YAML: legacyFile });
  c.check('legacy 模式拒收', r.code !== 0, `exit=${r.code}`);
  c.check('legacy 文案点名存量 env', r.out.includes('SUYOU_PROJECTS_YAML'), r.out.slice(-300));
  c.check('legacy 语义拒收 exit=1', r.code === 1, `exit=${r.code}`);
  checkClean('legacy');
  c.check('legacy 源文件字节不动',
    readFileSync(legacyFile, 'utf8') === legacyBody);
}

// ---- 7. name 三态 ----
{
  const d = tmpRoot('fix10-name-dir-');
  const rEmpty = add('zfixn1', '', [d]);
  c.check('name 空拒收', rEmpty.code !== 0, `exit=${rEmpty.code}`);
  const rHash = add('zfixn2', 'Has#Tag', [d]);
  c.check('name 含 # 拒收', rHash.code !== 0, `exit=${rHash.code}`);
  c.check('# 拒收文案点名 name', rHash.out.includes('name'), rHash.out.slice(-300));
  c.check('name-# 语义拒收 exit=1', rHash.code === 1, `exit=${rHash.code}`);
  const rNl = add('zfixn3', 'two\nlines', [d]);
  c.check('name 含换行拒收', rNl.code !== 0, `exit=${rNl.code}`);
  checkClean('name 三态');
  const d2 = tmpRoot('fix10-trim-dir-');
  const rTrim = add('zfixtrim', '  Padded Name  ', [d2]);
  c.check('name 首尾空白 trim 后收', rTrim.code === 0, `exit=${rTrim.code}\n${rTrim.out.slice(-300)}`);
  const reg = pyRegistry(root);
  const t = reg.projects.find((p) => p.key === 'zfixtrim');
  c.check('trim 读回验证：注册名=Padded Name（无残留空白）',
    t && t.name === 'Padded Name', JSON.stringify(t));
  baseline = snapshotRoot(root);
}

// ---- 8. 并发同 key 双 add：恰一成一拒，无静默覆盖 ----
{
  const r1dir = tmpRoot('fix10-race1-');
  const r2dir = tmpRoot('fix10-race2-');
  const { spawn } = await import('node:child_process');
  const mk = (name, dir) => new Promise((resolve) => {
    const p = spawn('python3', [SANDBAR, 'project', 'add',
      '--key', 'zfixrace', '--name', name, '--dir', dir],
    { cwd: REPO_ROOT, env: sbEnv(root), encoding: 'utf8' });
    let out = '';
    p.stdout.on('data', (x) => { out += x; });
    p.stderr.on('data', (x) => { out += x; });
    p.on('close', (code) => resolve({ code, out }));
  });
  const [a, b] = await Promise.all([mk('Race One', r1dir), mk('Race Two', r2dir)]);
  c.check('并发同 key：恰一成一拒',
    (a.code === 0) !== (b.code === 0),
    `a=${a.code} b=${b.code}\na.out=${a.out.slice(-200)}\nb.out=${b.out.slice(-200)}`);
  const reg = pyRegistry(root);
  const racers = reg.projects.filter((p) => p.key === 'zfixrace');
  c.check('并发后注册表恰一条 zfixrace', racers.length === 1, JSON.stringify(racers));
  const consistent = racers.length === 1
    && ((racers[0].name === 'Race One' && racers[0].dirs[0] === r1dir)
      || (racers[0].name === 'Race Two' && racers[0].dirs[0] === r2dir));
  c.check('并发赢家条目自洽（name/dirs 同源，无混写）', consistent, JSON.stringify(racers));
  const q = reg.quarantined.filter((x) => x.dir && x.dir.includes('zfixrace'));
  c.check('并发不产隔离条目', q.length === 0, JSON.stringify(q));
  baseline = snapshotRoot(root);
}

// ---- 9. remove 点位在且不裸崩、注册表不动（票①=骨架，票②=真实现，本钉两期皆存活） ----
{
  const ghost = 'zfixghostkey'; // 未注册 key：票①恒红点位 / 票② fail-closed 未知 key，两期都非 0
  const r = cliRemove(root, ghost);
  c.check('remove 点位在（输出点名 remove）', r.out.includes('remove'),
    `exit=${r.code}\n${r.out.slice(-300)}`);
  c.check('remove 不裸崩（无未处理 traceback）', !r.out.includes('Traceback'),
    `exit=${r.code}\n${r.out.slice(-300)}`);
  checkClean('remove 未注册 key');
  const rj = cliRemove(root, ghost, {}, true);
  c.check('remove --json 不裸崩', !rj.out.includes('Traceback'), `exit=${rj.code}`);
  checkClean('remove --json');
}

c.finish();
