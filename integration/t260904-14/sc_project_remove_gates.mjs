// sc_project_remove_gates.mjs — t260904-14 场景②：闸语义面（在飞真票/不可达/purge/dry-run/
// 最后项目/legacy/未注册/隔离同名）。
//
// intent（用户可感知行为，立项验收5/7/8/9 + gen2 方案 C3 表）：remove 的 fail-closed
// 闸逐道可辨且语义腿零环境依赖——
//   真票腿（唯一 env_fail 豁免，C3 表）：隔离台起真 running 票 → 拒摘报票号 →
//     收口（cancel）→ 重跑 remove 成功（验收5 全段，含 M3 续步）；
//   Temporal 不可达 → fail-closed 拒摘，文案含可达性诊断指路（先 sandbar up）（验收7）；
//   sdk-missing 与不可达两态输出可辨（KI-039）；通道坏 JSON=拒摘；
//   purge 双旗：差集非空（含 manifest 缺失/畸形两形，C1）=拒并列票号、过闸真删 data/
//     但 credentials.yaml 不动、--purge-credentials 独立生效、双旗可组合；
//   dry-run 含 purge 旗=只出将删清单、注册表根字节级零变更（验收8）；
//   摘最后一个项目：无 --confirm-last=拒，带旗=零条目警告在文、装载器空表抛错语义可辨
//     （验收9）；
//   legacy env（SANDBAR_PROJECTS_YAML）在位=拒收点名存量 env（gen1 R4 模式闸）；
//   key 未注册=拒且零现场变更；隔离条目同名=拒且与未注册区分报（含 project.yaml 定位）。
//
// 台别（C3 表逐腿钉死）：真票腿=temporalite 自举真台（依赖缺席=env_fail（exit 2）
//   并打印缺什么，唯一豁免腿）；其余全部腿=桩 poc_dir（--root 指桩树，假 client.py 经
//   FIX14_CTRL 注入），零环境依赖——注入缝在桩侧，环境缺失假绿被三态契约堵死（KI-046）。
// 安全红线：零 3099 接触；自举台只在随机高端口+临时 db，finally 必杀（资源回收）；
//   env 逐腿显式钉死防缺省外溢生产 7233。实现段落地前本场景红属预期（TDD 信号），
//   arbitrate/merge 期必须绿。
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import path from 'node:path';
import {
  tmpRoot, sbEnv, runCli, pyLookupRaw, makeChecks,
  writeProjectEntry, writeArchive, treeSnapshot, subtreeUnchanged,
  makeStubRoot, provisionRealRig, REPO_ROOT,
} from './lib_fix14.mjs';

const c = makeChecks('t260904-14 project remove 闸语义');
delete process.env.SANDBAR_PROJECTS_YAML;

const stub = makeStubRoot();
const retiredOf = (root, key) => {
  try {
    return readdirSync(path.join(root, key))
      .find((n) => n.startsWith('project.yaml.retired-'));
  } catch { return undefined; }
};

// 通用 fixture：隔离注册表根 + 条目 + 归档组 + credentials + metrics
const newRoot = (prefix) => tmpRoot(prefix);
const mkEntry = (root, key, ids) => {
  writeFileSync(path.join(root, '.migrated'), 'source: fixture\n');
  const projDir = tmpRoot(`fix14-${key}-proj-`);
  writeProjectEntry(root, key, key, [projDir]);
  for (const [id, variant] of ids || []) writeArchive(root, key, id, variant);
  writeFileSync(path.join(root, key, 'credentials.yaml'), 'dummy: credentials\n');
  mkdirSync(path.join(root, key, 'data', 'metrics'), { recursive: true });
  writeFileSync(path.join(root, key, 'data', 'metrics', 'm.json'), '{"fixture":1}\n');
  return projDir;
};

// client.py 直呼（真通道，仅真票腿用；cwd=仓根，消费 SANDBAR_TARGET_HOST/NAMESPACE env）
function pyTicket(clientArgs, env) {
  const r = spawnSync('python3', ['server/engine/client.py', ...clientArgs],
    { cwd: REPO_ROOT, env, encoding: 'utf8', timeout: 60000 });
  return { code: r.status === null ? -1 : r.status, out: (r.stdout || '') + (r.stderr || '') };
}

// =====================================================================
// 腿 A（真票腿，唯一 env_fail 豁免）：真台起 running 票 → 拒摘报票号 → cancel → remove 成功
// =====================================================================
{
  const rig = await provisionRealRig();
  if (!rig.ok) {
    c.envFail('真票腿（验收5 全段）', `${rig.reason}——C3 唯一 env_fail 豁免腿（隔离台环境补真跑）`);
  } else {
    try {
      const root = newRoot('fix14-gate-real-');
      mkEntry(root, 'rmgate', []);
      const env = sbEnv(root, {
        SANDBAR_TARGET_HOST: rig.target, SANDBAR_NAMESPACE: rig.namespace,
      });
      const tid = 't260904-14-gate';
      const st = pyTicket(['ticket-start',
        JSON.stringify({ ticket_id: tid, template_id: 'dev-lane', project: 'rmgate' })], env);
      if (st.code !== 0) {
        c.envFail('真票腿（验收5 全段）',
          `ticket-start 未成（隔离台参数/锚定口径差异）：${st.out.slice(-200)}`);
      } else {
        const rem1 = runCli(['project', 'remove', '--key', 'rmgate'], env);
        c.check('真票在飞=拒摘 exit 1（验收5 前半）', rem1.code === 1,
          `exit=${rem1.code}\n${rem1.out.slice(-400)}`);
        c.check('拒摘报票号', rem1.out.includes(tid), rem1.out.slice(-400));
        const cc = pyTicket(['cancel',
          JSON.stringify({ workflow_id: tid, reason: 't260904-14 场景收口' })], env);
        if (cc.code !== 0) {
          c.envFail('真票腿收口后半', `cancel 未成：${cc.out.slice(-200)}`);
        } else {
          const rem2 = runCli(['project', 'remove', '--key', 'rmgate'], env);
          c.check('收口后 remove 成功（验收5 后半/M3 续步）', rem2.code === 0,
            `exit=${rem2.code}\n${rem2.out.slice(-400)}`);
          c.check('收口后退役在位', Boolean(retiredOf(root, 'rmgate')));
        }
      }
    } finally {
      rig.child.kill('TERM'); // 资源回收：自举台必杀（资源生命周期纪律）
    }
  }
}

// =====================================================================
// 腿 B（桩 poc_dir，零环境依赖腿）：不可达 / sdk-missing / 坏 JSON 三态 fail-closed
// =====================================================================
{
  const root = newRoot('fix14-gate-unreach-');
  mkEntry(root, 'keeper', []); // 防撞「最后项目闸」：本腿断言面不在 confirm-last
  mkEntry(root, 'rmun', []);
  stub.setCtrl({ mode: 'exit', stderr: 'dial tcp 127.0.0.1:1: connect: connection refused' });
  const dead = stub.remove(root, 'rmun');
  c.check('Temporal 不可达=拒摘 exit 1（验收7 fail-closed）', dead.code === 1,
    `exit=${dead.code}\n${dead.out.slice(-400)}`);
  c.check('不可达文案含可达性诊断指路（sandbar up）', dead.out.includes('sandbar up'),
    dead.out.slice(-400));
  c.check('不可达态零现场变更（project.yaml 在位）',
    existsSync(path.join(root, 'rmun', 'project.yaml')));

  stub.setCtrl({ mode: 'sdk' });
  const sdk = stub.remove(root, 'rmun');
  c.check('sdk-missing=拒摘 exit 1（KI-039：依赖缺失不得吞成可摘）', sdk.code === 1,
    `exit=${sdk.code}\n${sdk.out.slice(-400)}`);
  c.check('两态输出可辨（不可达≠SDK 缺失）', dead.out !== sdk.out,
    '两态输出全等——三态语义未落地');

  stub.setCtrl({ mode: 'badjson' });
  const bad = stub.remove(root, 'rmun');
  c.check('通道坏 JSON=拒摘 exit 1（畸形输入 fail-closed）', bad.code === 1,
    `exit=${bad.code}\n${bad.out.slice(-400)}`);
}

// =====================================================================
// 腿 C（桩 poc_dir，零环境依赖腿）：purge 双旗 + C1 三态 + dry-run 清单
// =====================================================================
{
  // C1 缺失态：目录在/manifest 缺 → 差集含该票 → purge 拒并列票号、data/ 不动
  const root = newRoot('fix14-gate-purge1-');
  mkEntry(root, 'keeper', []); // 防撞「最后项目闸」：本腿断言面不在 confirm-last
  mkEntry(root, 'rmpg', [['tp1', 'valid'], ['tp9', 'missing']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'tp1', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmpg', sa_epic: '' },
    { id: 'tp9', exec_status: 'COMPLETED', close_ts: 9, sa_project: 'rmpg', sa_epic: '' },
  ] });
  const dataBefore = treeSnapshot(path.join(root, 'rmpg', 'data'));
  const ref1 = stub.remove(root, 'rmpg', ['--purge-data']);
  c.check('purge-data 差集非空=拒 exit 1（验收8）', ref1.code === 1,
    `exit=${ref1.code}\n${ref1.out.slice(-400)}`);
  c.check('purge 拒列票号 tp9（manifest 缺=未归档，C1 缺失态）', ref1.out.includes('tp9'),
    ref1.out.slice(-400));
  c.check('purge 被拒后 data/ 字节不动',
    subtreeUnchanged(dataBefore, treeSnapshot(path.join(root, 'rmpg', 'data')), ''));

  // C1 畸形态：manifest 坏 JSON → fail-closed 红、点名 <id>/archive.json
  const root2 = newRoot('fix14-gate-purge2-');  mkEntry(root2, 'keeper', []);
  mkEntry(root2, 'rmpb', [['tb1', 'valid'], ['tbad', 'badjson']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'tb1', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmpb', sa_epic: '' },
    { id: 'tbad', exec_status: 'COMPLETED', close_ts: 2, sa_project: 'rmpb', sa_epic: '' },
  ] });
  const ref2 = stub.remove(root2, 'rmpb', ['--purge-data']);
  c.check('manifest 畸形=红（C1 畸形态，不静默归侧）', ref2.code === 1,
    `exit=${ref2.code}\n${ref2.out.slice(-400)}`);
  c.check('红文案点名 <id>/archive.json',
    ref2.out.includes('tbad') && ref2.out.includes('archive.json'), ref2.out.slice(-400));

  // 过闸真删：差集空 → data/ 删、credentials.yaml 不动、退役在位
  const root3 = newRoot('fix14-gate-purge3-');  mkEntry(root3, 'keeper', []);
  mkEntry(root3, 'rmpd', [['td2', 'valid']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'td2', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmpd', sa_epic: '' },
  ] });
  const ok1 = stub.remove(root3, 'rmpd', ['--purge-data']);
  c.check('purge-data 过闸 exit 0', ok1.code === 0, `exit=${ok1.code}\n${ok1.out.slice(-400)}`);
  c.check('purge-data 后 data/ 已删', !existsSync(path.join(root3, 'rmpd', 'data')));
  c.check('purge-data 不动 credentials.yaml',
    existsSync(path.join(root3, 'rmpd', 'credentials.yaml')));
  c.check('purge-data 后退役在位', Boolean(retiredOf(root3, 'rmpd')));

  // --purge-credentials 独立生效：只删 credentials、data/ 不动
  const root4 = newRoot('fix14-gate-purge4-');  mkEntry(root4, 'keeper', []);
  mkEntry(root4, 'rmpc', [['tc2', 'valid']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'tc2', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmpc', sa_epic: '' },
  ] });
  const data4 = treeSnapshot(path.join(root4, 'rmpc', 'data'));
  const ok2 = stub.remove(root4, 'rmpc', ['--purge-credentials']);
  c.check('purge-credentials 独立 exit 0（验收8 独立生效）', ok2.code === 0,
    `exit=${ok2.code}\n${ok2.out.slice(-400)}`);
  c.check('purge-credentials 后 credentials.yaml 已删',
    !existsSync(path.join(root4, 'rmpc', 'credentials.yaml')));
  c.check('purge-credentials 不动 data/',
    subtreeUnchanged(data4, treeSnapshot(path.join(root4, 'rmpc', 'data')), ''));

  // 双旗组合：两者都删
  const root5 = newRoot('fix14-gate-purge5-');  mkEntry(root5, 'keeper', []);
  mkEntry(root5, 'rmpcc', [['td3', 'valid']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'td3', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmpcc', sa_epic: '' },
  ] });
  const ok3 = stub.remove(root5, 'rmpcc', ['--purge-data', '--purge-credentials']);
  c.check('双旗组合 exit 0', ok3.code === 0, `exit=${ok3.code}\n${ok3.out.slice(-400)}`);
  c.check('双旗后 data/ 与 credentials.yaml 俱删',
    !existsSync(path.join(root5, 'rmpcc', 'data')) &&
    !existsSync(path.join(root5, 'rmpcc', 'credentials.yaml')));

  // dry-run + purge 旗：将删清单、注册表根字节级零变更
  const root6 = newRoot('fix14-gate-drypurge-');  mkEntry(root6, 'keeper', []);
  mkEntry(root6, 'rmdrp', [['td4', 'valid']]);
  stub.setCtrl({ mode: 'ok', tickets: [
    { id: 'td4', exec_status: 'COMPLETED', close_ts: 1, sa_project: 'rmdrp', sa_epic: '' },
  ] });
  const before6 = treeSnapshot(root6);
  const dry = stub.remove(root6, 'rmdrp', ['--dry-run', '--purge-data', '--purge-credentials']);
  c.check('dry-run+purge 旗 exit 0（预演不执行）', dry.code === 0,
    `exit=${dry.code}\n${dry.out.slice(-400)}`);
  c.check('将删清单含 credentials 与 data 词汇（路径+字节+票计数面）',
    dry.out.includes('credentials') && dry.out.includes('data'), dry.out.slice(-400));
  c.check('dry-run+purge 注册表根字节级零变更',
    JSON.stringify(before6) === JSON.stringify(treeSnapshot(root6)));
}

// =====================================================================
// 腿 D（桩 poc_dir，零环境依赖腿）：最后项目 --confirm-last（验收9）
// =====================================================================
{
  const root = newRoot('fix14-gate-last-');
  mkEntry(root, 'rmlast', []);
  stub.setCtrl({ mode: 'ok', tickets: [] });
  const noFlag = stub.remove(root, 'rmlast');
  c.check('摘最后一个项目无确认旗=拒 exit 1（验收9）', noFlag.code === 1,
    `exit=${noFlag.code}\n${noFlag.out.slice(-400)}`);
  c.check('拒文案点名确认旗 --confirm-last', noFlag.out.includes('--confirm-last'),
    noFlag.out.slice(-400));
  c.check('拒后条目仍在位（零现场变更）',
    existsSync(path.join(root, 'rmlast', 'project.yaml')));

  const yes = stub.remove(root, 'rmlast', ['--confirm-last']);
  c.check('带 --confirm-last 摘除 exit 0', yes.code === 0,
    `exit=${yes.code}\n${yes.out.slice(-400)}`);
  c.check('零条目警告在文（点名装载器空表语义）',
    yes.out.includes('零条目') || yes.out.includes('空'), yes.out.slice(-400));
  const probe = pyLookupRaw(root, 'rmlast');
  c.check('摘除后按 key 查询面空表抛错（契约①a 零条目=抛错列原因，assert_registry_nonempty）',
    probe.code !== 0 && probe.out.includes('没有任何项目条目'),
    `code=${probe.code} out=${probe.out.slice(-200)}`);
}

// =====================================================================
// 腿 E（桩 poc_dir，零环境依赖腿）：legacy 模式闸 / key 未注册 / 隔离同名
// =====================================================================
{
  const root = newRoot('fix14-gate-misc-');
  mkEntry(root, 'keeper', []); // 防撞「最后项目闸」：本腿断言面不在 confirm-last
  mkEntry(root, 'rmleg', []);
  const legacyFile = path.join(tmpRoot('fix14-legacy-'), 'projects.yaml');
  writeFileSync(legacyFile, 'projects: []\n');
  const leg = stub.remove(root, 'rmleg', [], { SANDBAR_PROJECTS_YAML: legacyFile });
  c.check('legacy env 在位=拒收（模式闸，R4）', leg.code === 1,
    `exit=${leg.code}\n${leg.out.slice(-400)}`);
  c.check('拒收点名存量 env SANDBAR_PROJECTS_YAML', leg.out.includes('SANDBAR_PROJECTS_YAML'),
    leg.out.slice(-400));
  c.check('legacy 拒收零现场变更', existsSync(path.join(root, 'rmleg', 'project.yaml')));

  const beforeSnap = treeSnapshot(root);
  const unknown = stub.remove(root, 'nosuchkey');
  c.check('key 未注册=拒 exit 1', unknown.code === 1,
    `exit=${unknown.code}\n${unknown.out.slice(-400)}`);
  c.check('未注册拒零现场变更',
    JSON.stringify(beforeSnap) === JSON.stringify(treeSnapshot(root)));

  mkdirSync(path.join(root, 'rmq'), { recursive: true });
  writeFileSync(path.join(root, 'rmq', 'project.yaml'),
    'schema: v9\nproject:\n  - key: rmq\n    name: Q\n    dirs:\n      - /tmp/x\n');
  const quar = stub.remove(root, 'rmq');
  c.check('隔离条目同名=拒 exit 1', quar.code === 1,
    `exit=${quar.code}\n${quar.out.slice(-400)}`);
  c.check('隔离同名报含 <dir>/project.yaml 定位（与未注册区分）',
    quar.out.includes('rmq') && quar.out.includes('project.yaml'), quar.out.slice(-400));
}

c.finish();
