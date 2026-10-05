"""事件账本单测（t260928-13；epic project-executor 第一片）。

覆盖面（对齐方案 [R1]–[R6] 与验收清单）：
  - 行形状：完整字段 / <4KB / 畸形 payload（非 dict、非串 reason、超长 reason、缺键）
  - 幂等：同 idem 重投只一行（热集）；冷进程（清加速集）文件已有键仍只一行（[R4]）
  - [R3]：同票同 seq 不同 run_id ⇒ 两行（新 run 不被旧键错压制）
  - fail-open：账本目录只读 ⇒ 不 raise、stderr 点名、计数器进（[R5]）；
    gaps 同目录同样只读 ⇒ 双失败仍不 raise（保证面=stderr+计数器）
  - 撕裂行：末行无换行/JSON 坏 ⇒ 跳过计数、照常追加
  - 配置：undeclared/disabled ⇒ emitted:false 零文件（验收⑧）；畸形块逐键回落；
    enabled:true 放行
  - 轮转/清扫：_maybe_rotate 超限归档、_sweep 只删过窗归档（活动文件永不碰）
  - rebuild：盘面文件缺行+重复 idem ⇒ 补缺一行、重复计数、不重复修复（[R2]）

全程零真 Temporal/零网络：活动函数直调（append_event 核心单点），账本目录钉在
SANDBAR_EVENT_LEDGER_DIR 的 tmp_path。
"""
import json
import os
import time

import pytest

import event_ledger as el


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每用例独立账本目录 + 独立注册表根 + 清缓存（配置缓存/加速集跨用例污染面）。"""
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(tmp_path / 'ledger'))
    monkeypatch.setenv('SANDBAR_PROJECTS_DIR', str(tmp_path / 'projects'))
    (tmp_path / 'projects').mkdir(exist_ok=True)
    el.reset_config_for_test()
    yield
    el.reset_config_for_test()


def _enable(tmp_path):
    """造一个「引擎所属项目」声明 event_ledger enabled 的注册表（[R1] 解析面走真文件）。

    260928 复核修复：**dirs 必须真覆盖引擎仓根**。旧夹具写的是 `paths:\\n  - /somewhere`
    （dirs 指向别处）——它把「只要带 paths 段就算引擎所属项目」这个**错误判据固化成预期**，
    于是本 bug 在 24 个用例全绿的前提下静默出厂。夹具现在按真规则造（见 `_decoy` 反例）。"""
    root = el._projects_root()
    d = root / 'alpha'
    d.mkdir(exist_ok=True)
    (d / 'project.yaml').write_text(
        'schema: v1\n'
        'project:\n  - key: engine-owner\n    dirs:\n      - %s\n'
        'paths:\n  - /somewhere\n'
        'event_ledger:\n  enabled: true\n  keep_days: 14\n  max_mb: 512\n' % el.ENGINE_REPO,
        encoding='utf-8')
    el.reset_config_for_test()
    return root


def _decoy(root, name='aaa-decoy', declare=True, dirs='/somewhere/else'):
    """干扰条目：目录名**字母序更早**、带 `paths:` 段与列表项、dirs **不覆盖**引擎仓根。

    这正是 t260928-13 出厂版本的错误判据会误选的那种条目（实测命中 dengzhufpv）。"""
    d = root / name
    d.mkdir(exist_ok=True)
    body = 'schema: v1\nproject:\n  - key: %s\n    dirs:\n      - %s\npaths:\n  - /somewhere\n' % (
        name, dirs)
    if declare:
        body += 'event_ledger:\n  enabled: true\n  keep_days: 7\n  max_mb: 64\n'
    (d / 'project.yaml').write_text(body, encoding='utf-8')
    el.reset_config_for_test()
    return d


def test_engine_project_lookup_ignores_decoy_entry(tmp_path):
    """干预防线：字母序更早、带 paths 段但不覆盖引擎仓根的条目**不得**被选中。"""
    root = _enable(tmp_path)
    _decoy(root)
    got = el._find_engine_project_yaml(root)
    assert got == root / 'alpha' / 'project.yaml', '选中了干扰条目：%s' % got


def test_engine_project_lookup_accepts_ancestor_dir(tmp_path):
    """祖先也算覆盖（worktree 在主仓树下时命中的就是这条语义）。"""
    root = tmp_path / 'projects'
    d = root / 'owner'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'project.yaml').write_text(
        'project:\n  - key: owner\n    dirs:\n      - %s\npaths:\n  - /somewhere\n'
        % el.ENGINE_REPO.parent, encoding='utf-8')
    el.reset_config_for_test()
    assert el._find_engine_project_yaml(root) == d / 'project.yaml'


def test_declaration_in_non_owner_does_not_enable(tmp_path):
    """**本 bug 的精确回归锁**：声明写在非引擎所属项目里 ⇒ 引擎账本**不得**启用。

    旧实现下这条会红（它认了干扰条目的声明，引擎账本按别人的 keep_days 走）。"""
    root = el._projects_root()
    _decoy(root, declare=True)          # 只有干扰条目声明 enabled
    el.reset_config_for_test()
    cfg = el.event_ledger_config(projects_root=root)
    assert cfg['enabled'] is False, '非所属项目的声明被误采纳：%s' % cfg
    assert cfg['keep_days'] == el.DEFAULT_KEEP_DAYS


def test_resolver_agrees_with_audit(tmp_path):
    """一致性锁：同一组夹具下，本模块解析器与 audit 版**必须选中同一文件**
    （两处实现不得漂移；本模块刻意不 import audit，靠本锁防分裂）。"""
    import audit as au
    root = _enable(tmp_path)
    _decoy(root)
    (root / 'zzz-worktree-owner').mkdir(exist_ok=True)
    (root / 'zzz-worktree-owner' / 'project.yaml').write_text(
        'project:\n  - key: wt\n    dirs:\n      - %s\npaths:\n  - /x\n' % el.ENGINE_REPO,
        encoding='utf-8')
    assert el.ENGINE_REPO == au.ENGINE_REPO, '引擎仓根口径分歧'
    assert el._find_engine_project_yaml(root) == au._engine_project_yaml(root)
    # 解析器口径逐条对齐（形状按真实 project.yaml：dirs: 独占一行、列表项缩进）
    for text in (
            'schema: v1\nproject:\n  - key: k\n    dirs:\n      - %s\n' % el.ENGINE_REPO,
            'schema: v1\nproject:\n  - key: k\n    dirs:\n      - %s\n' % el.ENGINE_REPO.parent,
            'schema: v1\nproject:\n  - key: k\n    dirs:\n      - /elsewhere\npaths:\n  - /x\n',
            'project: alpha\npaths:\n  - /somewhere\n',           # 旧夹具形状：两版都不认
            'project:\n  - key: k\n    dirs:\n      - /a\n    other: x\n',
            'project:\n  - key: k\n    dirs:\n      - /a\n      - %s\n' % el.ENGINE_REPO,
            'project:\n  - key: k\n    dirs:\n      - /x  # dirs 在别的条目里\n',
            'project:\n  - dirs: inline-not-a-block\n',
            'project:\n  - key: k\n    dirs:\n      - /a  # 注释吃掉\n',
            ''):                                                    # 空文件不炸
        assert el._dirs_cover_engine(text) == au._dirs_cover_engine(text), \
            '口径分歧：%r' % text


def _payload(tmp_path, seq=1, run='run-1', ticket='t1', project='alpha', **kw):
    p = {'v': el.SCHEMA_V, 'project': project, 'scope': 'project', 'ticket': ticket,
         'workflow': 'DevLaneWorkflow', 'template': 'dev-lane', 'stage': 'implement',
         'state': 'running', 'reason': '进入本步', 'gen': 2,
         'ts': '2026-09-28T10:00:00', 'seq': seq, 'run_id': run,
         'idem': '%s|%s|%s|%d' % (project, ticket, run, seq),
         'engine': 3}
    p.update(kw)
    return p


def _lines(tmp_path, project='alpha'):
    f = el.ledger_path(project, tmp_path / 'ledger')
    if not f.exists():
        return []
    out = []
    for x in f.read_text(encoding='utf-8').splitlines():
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except ValueError:
            pass    # 撕裂行：读取面跳过（与模块扫描面同口径）
    return out


# ---------- 行形状 ----------

def test_line_fields_complete(tmp_path):
    _enable(tmp_path)
    res = el.append_event(_payload(tmp_path), tmp_path / 'ledger')
    assert res['emitted'] is True
    (line,) = _lines(tmp_path)
    for k in ('v', 'project', 'scope', 'ticket', 'workflow', 'template', 'stage',
              'state', 'reason', 'gen', 'ts', 'seq', 'run_id', 'idem', 'engine'):
        assert k in line, k
    assert line['v'] == el.SCHEMA_V
    assert line['scope'] == 'project'
    assert line['engine'] == el.ENGINE_VERSION_V2


def test_line_under_4kb_and_truncation(tmp_path):
    # 超长 reason：截断点名在行内，行 <4KB
    _enable(tmp_path)
    res = el.append_event(_payload(tmp_path, reason='x' * 99999), tmp_path / 'ledger')
    assert res['emitted'] is True
    data = el.ledger_path('alpha', tmp_path / 'ledger').read_bytes()
    assert len(data.splitlines()[0]) < el.LINE_LIMIT
    (line,) = _lines(tmp_path)
    assert line['reason'].endswith(el.REASON_TRUNC_MARK)


@pytest.mark.parametrize('bad', [
    'not-a-dict',
    None,
    {'reason': ['list'], 'seq': 'x'},       # 非串 reason + 非整数 seq
    {'project': 42, 'ticket': None},        # 非串/None 字段
])
def test_malformed_payload_never_raises(tmp_path, bad):
    res = el.append_event(bad, tmp_path / 'ledger')
    assert res.get('emitted') in (True, False)
    assert 'error' not in res or res.get('failed') is not True
    for line in _lines(tmp_path):
        assert len(json.dumps(line)) < el.LINE_LIMIT


# ---------- 幂等 [R3][R4] ----------

def test_redelivery_same_idem_single_line(tmp_path):
    _enable(tmp_path)
    p = _payload(tmp_path)
    assert el.append_event(p, tmp_path / 'ledger')['emitted'] is True
    res = el.append_event(dict(p), tmp_path / 'ledger')     # 重投（同 payload）
    assert res.get('dedup') is True
    assert len(_lines(tmp_path)) == 1


def test_cold_cache_file_scan_still_dedupes(tmp_path, monkeypatch):
    # [R4] 冷进程：加速集被清空，文件里已有该键 ⇒ 仍只一行（文件扫=权威面）
    _enable(tmp_path)
    p = _payload(tmp_path)
    el.append_event(p, tmp_path / 'ledger')
    el._SEEN.clear()
    res = el.append_event(dict(p), tmp_path / 'ledger')
    assert res.get('dedup') is True
    assert len(_lines(tmp_path)) == 1


def test_new_run_same_seq_not_suppressed(tmp_path):
    _enable(tmp_path)
    # [R3] 同票同 seq、不同 run_id（新工作流 run）⇒ 两行，绝不错压
    el.append_event(_payload(tmp_path, seq=1, run='run-A'), tmp_path / 'ledger')
    res = el.append_event(_payload(tmp_path, seq=1, run='run-B'), tmp_path / 'ledger')
    assert res['emitted'] is True
    assert len(_lines(tmp_path)) == 2


# ---------- fail-open [R5] ----------

def test_write_failure_fail_open_loud(tmp_path, capsys):
    ro = tmp_path / 'ro'
    _enable(tmp_path)
    ro.mkdir()
    os.chmod(ro, 0o500)     # 只读：账本与 gaps 同目录 ⇒ 双失败
    before = el.WRITE_FAILURES
    try:
        res = el.append_event(_payload(tmp_path), ro)
        assert res.get('failed') is True
        assert el.WRITE_FAILURES == before + 1
        err = capsys.readouterr().err
        assert 'event_ledger' in err and 'alpha' in err
    finally:
        os.chmod(ro, 0o700)


def test_torn_last_line_skipped_and_counted(tmp_path):
    f = tmp_path / 'ledger' / 'alpha.jsonl'
    _enable(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps(_payload(tmp_path), ensure_ascii=False)
    f.write_text(good + '\n{"idem": "torn', encoding='utf-8')     # 末行撕裂无换行
    before = el.WRITE_FAILURES
    res = el.append_event(_payload(tmp_path, seq=2, run='run-1'), tmp_path / 'ledger')
    assert res['emitted'] is True
    assert el.WRITE_FAILURES == before + 1        # 撕裂行计数（可见面），不致命
    lines = _lines(tmp_path)
    assert len(lines) == 2 and lines[-1]['seq'] == 2   # 撕裂行不参与去重也不致死


# ---------- 配置面（验收⑧ + [R1]） ----------

def test_undeclared_zero_behaviour(tmp_path):
    # 注册表空（未声明）⇒ emitted:false，零文件
    res = el.append_event(_payload(tmp_path), tmp_path / 'ledger')
    assert res == {'emitted': False, 'why': res['why']}
    assert 'not declared' in res['why']
    assert not (tmp_path / 'ledger' / 'alpha.jsonl').exists()
    assert not (tmp_path / 'ledger').exists() or not list((tmp_path / 'ledger').iterdir())


def test_declared_enabled_writes(tmp_path):
    _enable(tmp_path)
    res = el.append_event(_payload(tmp_path), tmp_path / 'ledger')
    assert res['emitted'] is True
    assert len(_lines(tmp_path)) == 1


def test_malformed_config_block_falls_back_per_key(tmp_path):
    root = el._projects_root()
    d = root / 'alpha'
    d.mkdir(exist_ok=True)
    (d / 'project.yaml').write_text(
        'schema: v1\nproject:\n  - key: alpha\n    dirs:\n      - %s\n'
        'paths:\n  - /x\nevent_ledger:\n  enabled: true\n'
        '  keep_days: banana\n  max_mb: -3\n' % el.ENGINE_REPO, encoding='utf-8')
    el.reset_config_for_test()
    cfg = el.event_ledger_config(root)
    assert cfg['enabled'] is True                 # 合法键生效
    assert cfg['keep_days'] == el.DEFAULT_KEEP_DAYS   # 非整数逐键回落
    assert cfg['max_mb'] == -3                        # ≤0=关 rolling（audit 同语义）


# ---------- 轮转/清扫 ----------

def test_maybe_rotate_and_sweep(tmp_path):
    d = tmp_path / 'ledger'
    d.mkdir()
    active = el.ledger_path('alpha', d)
    active.write_text('x' * 1024, encoding='utf-8')
    cfg = {'keep_days': 14, 'max_mb': 1}
    el._maybe_rotate(active, dict(cfg, max_mb=0))       # ≤0=关
    assert active.exists() and active.stat().st_size == 1024
    el._maybe_rotate(active, cfg)                        # 1KB < 1MB：不动
    assert active.exists()
    # 真触发一次 rolling（max_mb=1 ⇒ 阈值 1MB）
    big = el.ledger_path('beta', d)
    big.write_text('x' * (1024 * 1024 + 1), encoding='utf-8')
    el._maybe_rotate(big, {'keep_days': 14, 'max_mb': 1})
    assert not big.exists()                      # 活动文件已改名归档
    arch = [p for p in d.iterdir() if p.name.startswith('beta.jsonl.2026')
            or p.name.startswith('beta.jsonl.20')]
    assert len(arch) == 1 and arch[0].stat().st_size == 1024 * 1024 + 1
    # 造一个「keep 窗外」的归档名：用 2020 年的日戳
    old = d / 'alpha.jsonl.20200101-000000-abc123'
    old.write_text('old', encoding='utf-8')
    recent = d / ('alpha.jsonl.%s-000000-abc123' % time.strftime('%Y%m%d'))
    recent.write_text('recent', encoding='utf-8')
    el._sweep('alpha', {'keep_days': 14, 'max_mb': 0}, d)
    assert not old.exists()
    assert recent.exists()
    assert active.exists()                  # 活动文件永不碰
    assert el._parse_archive_day('alpha.jsonl.20200101-000000-abc123', 'alpha.jsonl') == '20200101'
    assert el._parse_archive_day('alpha.jsonl.weird', 'alpha.jsonl') is None


# ---------- rebuild [R2]（盘面端到端） ----------

def _timeline(tmp_path, run='run-1'):
    return [
        {'at': '2026-09-28T10:00:00', 'stage': 'create_plan', 'state': 'awaiting',
         'reason': 'adopt', 'ledger_seq': 1, 'ledger_run': run},
        {'at': '2026-09-28T10:01:00', 'stage': 'implement', 'state': 'running',
         'reason': '进入本步', 'gen': 1, 'ledger_seq': 2, 'ledger_run': run},
        {'at': '2026-09-28T10:02:00', 'stage': 'implement', 'state': 'authorized',
         'reason': '非迁移条目（直接 timeline.append，无标记）'},     # 天然不参与
    ]


def test_rebuild_heals_missing_line_reports_duplicate(tmp_path):
    _enable(tmp_path)
    # 盘面初始：写 seq=1 一行（模拟运行期已落账）
    el.append_event(_payload(tmp_path, seq=1, run='run-1', stage='create_plan',
                             state='awaiting', reason='adopt',
                             ts='2026-09-28T10:00:00'), tmp_path / 'ledger')
    # 人为毁账：把 seq=1 复制成重复两行（duplicate 伪影），此时 seq=2 整行缺失
    f = el.ledger_path('alpha', tmp_path / 'ledger')
    lines = f.read_text(encoding='utf-8').splitlines()
    f.write_text(lines[0] + '\n' + lines[0] + '\n', encoding='utf-8')  # 重复 idem ×2
    report = el.ledger_rebuild('alpha', 't1', _timeline(tmp_path),
                               workflow_class='DevLaneWorkflow',
                               template_id='dev-lane', ledger_dir=tmp_path / 'ledger')
    assert report['expected'] == 2          # 无标记条目不参与
    assert report['duplicate_idem'] == 1
    assert report['missing_added'] == 1     # 只补 seq=2 缺行；重复行绝不重复修复
    assert report['present'] == 2
    out = _lines(tmp_path)
    assert len(out) == 3                    # seq1 ×2（盘上伪影保留）+ 补 seq2 ×1
    idems = [x['idem'] for x in out]
    assert len([i for i in idems if i.endswith('|1')]) == 2
    assert len([i for i in idems if i.endswith('|2')]) == 1


def test_expected_lines_from_timeline_shape():
    evs = el.expected_lines(_timeline(None), 'alpha', 't1', 'DevLaneWorkflow', 'dev-lane')
    assert len(evs) == 2
    assert evs[0]['idem'] == 'alpha|t1|run-1|1'
    assert evs[1]['state'] == 'running'


def test_ledger_rebuild_no_enabled_gate_needed(tmp_path):
    # 未声明（停用）项目也能补历史：rebuild 是派生投影面，与增量开关正交
    report = el.ledger_rebuild('alpha', 't1', _timeline(tmp_path),
                               ledger_dir=tmp_path / 'ledger')
    assert report['missing_added'] == 2 and report['present'] == 2


# ---------- mixin 载荷面（monkeypatch temporalio.workflow，零真 Temporal） ----------

def _fake_workflow(monkeypatch, run_id='run-XYZ'):
    # 钉 base.workflow（mixin 解析 workflow 的真命名空间），而非 temporalio 真壳——
    # 全量语境下 t260922_09 的 _spy 桩会泄漏进 base.workflow，钉真壳会被它覆盖。
    from types import SimpleNamespace
    import base
    monkeypatch.setattr(base, 'workflow', SimpleNamespace(
        patched=lambda pid: True,
        info=lambda: SimpleNamespace(run_id=run_id),
        logger=SimpleNamespace(info=lambda *a, **k: None)))


def _mixin_owner(project='alpha', ticket='t1'):
    from base import TicketEventLedgerMixin
    class Owner(TicketEventLedgerMixin):
        pass
    o = Owner()
    o.meta = {'project': project, 'workflow_id': 'dev-lane'}
    o.ticket_id = ticket
    o.template_id = 'dev-lane'
    o.timeline = []       # enqueue 合同=_mark 在 timeline.append 之后调用（i=len-1）
    return o


def test_mixin_enqueue_payload_and_idem(monkeypatch):
    _fake_workflow(monkeypatch)
    o = _mixin_owner()
    entry = {'at': '2026-09-28T10:00:00', 'stage': 'implement', 'state': 'running',
             'reason': '进入本步', 'gen': 3}
    o.timeline.append(entry)          # _mark 合同：先 append 后 enqueue
    o._ledger_enqueue(entry)
    # [R-merge]：timeline 条目零标记（票面形状逐字不变）；标记走 _ledger_marks
    assert 'ledger_seq' not in entry and 'ledger_run' not in entry
    assert o._ledger_marks == [{'i': 0, 'seq': 1, 'run': 'run-XYZ'}]
    (ev,) = o._ledger_pending
    assert ev['idem'] == 'alpha|t1|run-XYZ|1'
    assert ev['seq'] == 1 and ev['run_id'] == 'run-XYZ' and ev['gen'] == 3
    assert ev['workflow'] == 'Owner' and ev['template'] == 'dev-lane'
    assert ev['engine'] == el.ENGINE_VERSION_V2
    o._ledger_enqueue({**entry, 'state': 'done'})
    assert o._ledger_pending[1]['seq'] == 2
    assert o._ledger_pending[1]['idem'] == 'alpha|t1|run-XYZ|2'


def test_mixin_enqueue_outside_workflow_noop(monkeypatch):
    # 离场环境（patched 抛错）：零行为、不打断调用方（存量单测直调 _mark 面守卫）
    from types import SimpleNamespace
    import base
    def _boom(pid):
        raise RuntimeError('not in workflow')
    monkeypatch.setattr(base, 'workflow', SimpleNamespace(patched=_boom))
    o = _mixin_owner()
    entry = {'at': 'x', 'stage': 's', 'state': 'st', 'reason': ''}
    o._ledger_enqueue(entry)
    assert o._ledger_pending is None and 'ledger_seq' not in entry


# ---------- [R-merge] 回归（merge_check 打回面）：全量顺序下的裸实例入队不炸 ----------

def test_bare_instance_after_shell_swap_never_raises(monkeypatch):
    # 全量语境模拟：别的用例把 base.workflow 换成 patched 恒 True 的桩之后，
    # 裸 object.__new__ 实例（未跑 _init、无 meta 键/template_id 属性）走 _mark
    # ⇒ 入队全防御不抛（曾炸：AttributeError: no attribute 'template_id'）。
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import base
    import dev_lane
    stub = SimpleNamespace(
        patched=lambda pid: True,
        info=lambda: SimpleNamespace(run_id='run-STUB'),
        logger=SimpleNamespace(info=lambda *a, **k: None),
        now=lambda: datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(base, 'workflow', stub)       # mixin 侧壳（真凶面）
    monkeypatch.setattr(dev_lane, 'workflow', stub)   # _mark/_now_iso 侧壳
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    wf.timeline = []
    wf._gens = {}
    wf._detail_face_on = False
    wf.ticket_id = 't-1'      # 与 _mk_wf 同形：ticket_id 在、template_id 不在（真凶）
    # t260928-20（review C2）：project-scope 类解析空项目 ⇒ 绝不冒充 engine 行——
    # 本行跳过（pending 空、seq 不留空洞、marks 无残留），LOUD 点名，主流程零打断。
    captured = []
    stub.logger = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda msg, *a: captured.append(msg % a if a else msg))
    wf._mark('implement', 'running', '进入本步')
    assert wf._ledger_pending == [] and wf._ledger_seq == 0 and wf._ledger_marks == []
    assert len(captured) == 1 and '项目键为空' in captured[0]
    # timeline 条目零标记（四键逐字锁面）——跳过只影响账面，票面照旧
    assert set(wf.timeline[-1]) == {'at', 'stage', 'state', 'reason'}


# ---------- [R-merge] marks 轨 rebuild（snapshot 的 ledger_marks 现役面） ----------

def _marks(run='run-1'):
    return [{'i': 0, 'seq': 1, 'run': run}, {'i': 1, 'seq': 2, 'run': run}]


def test_expected_lines_marks_track_ignores_untagged_entries():
    tl = [
        {'at': 'a', 'stage': 'create_plan', 'state': 'awaiting', 'reason': 'adopt'},
        {'at': 'b', 'stage': 'implement', 'state': 'running', 'reason': '进入本步', 'gen': 1},
        {'at': 'c', 'stage': 'implement', 'state': 'authorized', 'reason': '非迁移'},
    ]
    evs = el.expected_lines(tl, 'alpha', 't1', 'DevLaneWorkflow', 'dev-lane',
                            marks=_marks())
    assert len(evs) == 2
    assert evs[0]['idem'] == 'alpha|t1|run-1|1'
    assert evs[0]['stage'] == 'create_plan' and evs[1]['stage'] == 'implement'


def test_ledger_rebuild_marks_track_heals_disk(tmp_path):
    _enable(tmp_path)
    # 盘面先落 seq=1（模拟运行期已写），随后盘面只剩它（seq=2 缺失）
    el.append_event(_payload(tmp_path, seq=1, run='run-1', stage='create_plan',
                             state='awaiting', reason='adopt',
                             ts='a'), tmp_path / 'ledger')
    tl = [
        {'at': 'a', 'stage': 'create_plan', 'state': 'awaiting', 'reason': 'adopt'},
        {'at': 'b', 'stage': 'implement', 'state': 'running', 'reason': '进入本步'},
    ]
    report = el.ledger_rebuild('alpha', 't1', tl, marks=_marks(),
                               ledger_dir=tmp_path / 'ledger')
    assert report['expected'] == 2 and report['missing_added'] == 1
    assert report['present'] == 2
    # duplicate_idem=「expected idem 盘面已存在」的计数：seq1 在盘=1（正常在场，
    # 非伪影；真重复伪影场景见 test_rebuild_heals_missing_line_reports_duplicate）
    assert report['duplicate_idem'] == 1
    lines = _lines(tmp_path)
    assert [x['seq'] for x in lines] == [1, 2]


def test_ledger_rebuild_bad_marks_index_skipped(tmp_path):
    # 畸形 marks（下标越界/坏 seq）不炸、逐条跳过（外部输入面防御）
    tl = [{'at': 'a', 'stage': 's', 'state': 'st', 'reason': ''}]
    evs = el.expected_lines(tl, 'alpha', 't1', marks=[
        {'i': 9, 'seq': 1, 'run': 'r'},     # 越界
        {'i': 0, 'seq': 0, 'run': 'r'},     # 坏 seq
        {'i': 0, 'seq': 2, 'run': ''},      # 坏 run
        {'i': 0, 'seq': 3, 'run': 'r'},     # 唯一合法
    ])
    assert len(evs) == 1 and evs[0]['seq'] == 3
