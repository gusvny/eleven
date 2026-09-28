# -*- coding: utf-8 -*-
"""t260928-20 单测：事件账本第二族接线（巡检两链）+ 引擎级行（spawner/watcher/
dispatcher scan）+ mixin 的 scope/project 分流（review C2 防冒充守卫）。

覆盖面（对齐派单规格 1–7 与 review C1–C4）：
  - 巡检两链 _enter 入队：行形状完好（project=身份链真源、gen=文档化常量 0、
    scope=project）、snapshot 门内带 ledger_marks（C1 rebuild 权威面）
  - 引擎行：_ledger_scope="engine" ⇒ scope=engine、project 空哨兵、ticket=workflow id；
    活动侧 engine-owner 解析（key: 行优先，目录名回落；解析失败=announce-only 缺口，
    C3 选型：不造幻影项目文件）
  - C2 防冒充：project-scope 类解析空项目 ⇒ 跳过+点名，绝不写成 engine 行；
    engine 类恒 engine 行（不读 meta）
  - 重入/重跑安全：同 run 重放同序列 ⇒ idem 相同（活动侧去重兜住）；新 run_id
    ⇒ 新键不被旧键吞
  - 每类重放安全：patched=False 桩下五个新接线类全零行为（老 RUNNING 实例零变化）
  - fail-open：冲刷活动异常绝不打断主流程
  - 源码锁：ContentPipelineWorkflow 刻意豁免（不继承 mixin）——漂移即红

全程零真 Temporal / 零网络：base.workflow 钉桩（test_event_ledger 同款），账本目录
钉 SANDBAR_EVENT_LEDGER_DIR 的 tmp_path。
"""
import json
from types import SimpleNamespace

import pytest

import event_ledger as el
import base as base_mod
from base import TicketEventLedgerMixin


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(tmp_path / 'ledger'))
    monkeypatch.setenv('SANDBAR_PROJECTS_DIR', str(tmp_path / 'projects'))
    (tmp_path / 'projects').mkdir(exist_ok=True)
    el.reset_config_for_test()
    el.reset_engine_project_for_test()
    yield
    el.reset_config_for_test()
    el.reset_engine_project_for_test()


def _enable_engine_owner(tmp_path, key='engine-owner'):
    """造一个 dirs 覆盖引擎仓根、声明 event_ledger enabled 的注册条目（真规则夹具，
    test_event_ledger._enable 同款），键名可指定（测 key: 行优先解析）。"""
    root = el._projects_root()
    d = root / 'alpha-dirname'
    d.mkdir(exist_ok=True)
    (d / 'project.yaml').write_text(
        'schema: v1\n'
        'project:\n  - key: %s\n    dirs:\n      - %s\n'
        'event_ledger:\n  enabled: true\n' % (key, el.ENGINE_REPO),
        encoding='utf-8')
    el.reset_config_for_test()
    el.reset_engine_project_for_test()
    return root


def _stub(monkeypatch, run_id='run-N1', patched=True, wf_id='wf-1',
          warnings=None, now='2026-09-28T10:00:00', execute_activity=None):
    log = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda msg, *a: (warnings.append(msg % a if a else msg)
                                 if warnings is not None else None),
        error=lambda *a, **k: None)
    stub = SimpleNamespace(
        patched=lambda pid: patched,
        info=lambda: SimpleNamespace(run_id=run_id, workflow_id=wf_id),
        logger=log,
        now=lambda: SimpleNamespace(isoformat=lambda timespec='seconds': now))
    if execute_activity is not None:
        stub.execute_activity = execute_activity
    # 钉各消费模块的 workflow 名（_enter/_ledger_note 用各自模块的 workflow 符号，
    # 真壳在测试进程会抛 NotInWorkflowEventLoop——与 test_event_ledger 同款钉法）
    import inspection_flow as flow
    import workflows as wf_mod
    monkeypatch.setattr(base_mod, 'workflow', stub)
    monkeypatch.setattr(flow, 'workflow', stub)
    monkeypatch.setattr(wf_mod, 'workflow', stub)
    return stub


def _lines(tmp_path, name):
    p = tmp_path / 'ledger' / name
    if not p.is_file():
        return []
    return [json.loads(x) for x in
            p.read_text(encoding='utf-8').splitlines() if x.strip()]


# ---------- 巡检两链：_enter 入队 + snapshot marks（C1） ----------

def _periodic(project_key='proj-a'):
    import inspection_flow as flow
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    wf.stage, wf.stage_state, wf.status = '', 'running', 'running'
    wf.decision, wf.face, wf.timeline = '', {}, []
    wf._close_sig, wf._gate_err, wf._patched = None, '', True
    wf._code_stamp, wf._input = '', SimpleNamespace(project_key=project_key)
    return wf


def _produce(project_key='proj-b'):
    import inspection_flow as flow
    wf = object.__new__(flow.InspectionProduceWorkflow)
    wf.stage, wf.stage_state, wf.status = '', 'running', 'running'
    wf.decision, wf.face, wf.timeline = '', {}, []
    wf._close_sig, wf._gate_err, wf._patched = None, '', True
    wf._authorized, wf._rerun_paths = [], []
    wf._input = SimpleNamespace(project_key=project_key)
    return wf


def test_periodic_enter_enqueues_wellformed_project_row(monkeypatch):
    _stub(monkeypatch, run_id='run-P1')
    wf = _periodic('proj-a')
    wf._enter('inspect', 'running', '审查开始')
    assert set(wf.timeline[-1]) == {'at', 'stage', 'state', 'reason'}  # 票面逐字不变
    (ev,) = wf._ledger_pending
    assert ev['scope'] == 'project' and ev['project'] == 'proj-a'
    assert ev['stage'] == 'inspect' and ev['seq'] == 1
    # gen=文档化常量 0：本族无代数维度，诚实记 0，绝不伪造（派单规格 item 4）
    assert ev['gen'] == 0
    assert ev['idem'] == 'proj-a|%s|run-P1|1' % ev['ticket']


def test_periodic_snapshot_carries_ledger_marks(monkeypatch):
    """C1：终态硬杀下 pending 丢失 ⇒ rebuild 权威面=snapshot 的 ledger_marks。"""
    _stub(monkeypatch, run_id='run-P1')
    wf = _periodic('proj-a')
    wf._patched = False
    assert 'ledger_marks' not in wf.snapshot()   # 老实例（门关）⇒ 零新键
    wf._patched = True
    wf._enter('setup', 'running', '进')
    snap = wf.snapshot()
    assert snap['ledger_marks'] == [{'i': 0, 'seq': 1, 'run': 'run-P1'}]
    # marks+timeline ⇒ rebuild 出同源行（派生投影）
    evs = el.expected_lines(wf.timeline, 'proj-a', snap['id'],
                            'InspectionPeriodicWorkflow', 'inspection-lite',
                            marks=snap['ledger_marks'])
    assert len(evs) == 1 and evs[0]['gen'] == 0
    assert evs[0]['idem'] == 'proj-a|%s|run-P1|1' % evs[0]['ticket']


def test_produce_enter_enqueues_and_marks(monkeypatch):
    _stub(monkeypatch, run_id='run-B1')
    wf = _produce('proj-b')
    wf._enter('produce', 'running', '首趟产出')
    (ev,) = wf._ledger_pending
    assert ev['project'] == 'proj-b' and ev['scope'] == 'project'
    assert ev['gen'] == 0
    assert wf.snapshot()['ledger_marks'] == [{'i': 0, 'seq': 1, 'run': 'run-B1'}]


def test_project_family_rerun_and_new_run_idem(monkeypatch, tmp_path):
    """规格 item 5：同 run 重放（Temporal 重执行同一 history，同 run_id 同 seq）
    ⇒ 同 idem（活动去重兜住，不落第二行）；新 run ⇒ 新键不被旧键吞。"""
    _enable_engine_owner(tmp_path)
    _stub(monkeypatch, run_id='run-R1')
    wf = _periodic('proj-r')
    wf._enter('report', 'running', 'r')
    wf._enter('close', 'awaiting-human', '等人')     # 第二个迁移：seq 推进
    ev1, ev2 = wf._ledger_pending
    assert ev1['seq'] == 1 and ev2['seq'] == 2
    assert ev1['idem'] != ev2['idem']                # 不同迁移 ⇒ 不同键
    assert el.append_event(ev1, tmp_path / 'ledger')['emitted'] is True
    assert el.append_event(ev1, tmp_path / 'ledger') == {
        'emitted': False, 'dedup': True, 'path': str(tmp_path / 'ledger' / 'proj-r.jsonl')}
    # 重放形态：同 run 重执行第一条迁移（新实例、同 run_id、同 seq）⇒ 同键被压
    _stub(monkeypatch, run_id='run-R1')
    replay = _periodic('proj-r')
    replay._enter('report', 'running', 'r')
    assert replay._ledger_pending[0]['idem'] == ev1['idem']
    assert el.append_event(replay._ledger_pending[0], tmp_path / 'ledger')['dedup'] is True
    # 新 run（合法新跑）：run_id 换代 ⇒ 键不同 ⇒ 不被旧键吞
    _stub(monkeypatch, run_id='run-R2')
    wf2 = _periodic('proj-r')
    wf2._enter('report', 'running', 'r')
    (ev3,) = wf2._ledger_pending
    assert ev3['idem'] != ev1['idem']
    assert el.append_event(ev3, tmp_path / 'ledger')['emitted'] is True
    assert len(_lines(tmp_path, 'proj-r.jsonl')) == 2


# ---------- C2 防冒充守卫 + 引擎行 ----------

def test_project_scope_empty_project_skips_and_warns(monkeypatch):
    """C2：project-scope 类解析空项目 ⇒ 跳过+点名，绝不冒充 engine 行。"""
    warnings = []
    _stub(monkeypatch, warnings=warnings)
    wf = _periodic('')                           # 无身份（旧调度 payload 面）
    wf._enter('setup', 'running', '进')
    assert wf._ledger_pending == []              # 无行
    assert wf._ledger_seq == 0 and wf._ledger_marks == []   # seq 不留空洞
    assert len(warnings) == 1 and '项目键为空' in warnings[0]


def test_engine_scope_class_emits_engine_row(monkeypatch):
    """引擎级类恒 engine 行：project=空哨兵（活动侧解析）、不读 meta、ticket=workflow id。"""
    _stub(monkeypatch, run_id='run-E1', wf_id='inspection-spawn-demo')
    class FakeSpawner(TicketEventLedgerMixin):
        _ledger_scope = "engine"
    wf = FakeSpawner()
    wf._ledger_note('spawn', 'running', '起票')
    (ev,) = wf._ledger_pending
    assert ev['scope'] == 'engine' and ev['project'] == ''
    assert ev['ticket'] == 'inspection-spawn-demo'
    assert ev['gen'] == 0 and ev['seq'] == 1
    assert ev['idem'] == '|inspection-spawn-demo|run-E1|1'


def test_ticket_falls_back_to_workflow_id(monkeypatch):
    """无 ticket_id 属性的类（巡检两链/引擎发射器）：ticket=workflow id——rebuild
    派生投影用它对账，缺了闭环即断。"""
    _stub(monkeypatch, run_id='run-T1', wf_id='inspection-periodic-XYZ')
    wf = _periodic('proj-t')
    assert not hasattr(wf, 'ticket_id')
    wf._enter('setup', 'running', '进')
    (ev,) = wf._ledger_pending
    assert ev['ticket'] == 'inspection-periodic-XYZ'
    assert ev['idem'] == 'proj-t|inspection-periodic-XYZ|run-T1|1'


def test_engine_row_lands_in_engine_owner_ledger(monkeypatch, tmp_path):
    """活动侧解析：engine 行落引擎所属项目账本，行内 project 字段同键改写。"""
    _enable_engine_owner(tmp_path, key='owner-key')
    _stub(monkeypatch, run_id='run-E1', wf_id='inspection-watcher-demo')
    class FakeWatcher(TicketEventLedgerMixin):
        _ledger_scope = "engine"
    wf = FakeWatcher()
    wf._ledger_note('poll', 'running', 'watcher running')
    (ev,) = wf._ledger_pending
    assert el.append_event(ev, tmp_path / 'ledger')['emitted'] is True
    (line,) = _lines(tmp_path, 'owner-key.jsonl')
    assert line['project'] == 'owner-key' and line['scope'] == 'engine'
    assert line['ticket'] == 'inspection-watcher-demo'


def test_engine_project_key_prefers_yaml_key_over_dirname(tmp_path):
    _enable_engine_owner(tmp_path, key='the-key')
    assert el._engine_project_key() == 'the-key'
    el.reset_engine_project_for_test()


def test_engine_project_key_falls_back_to_dirname(tmp_path):
    root = el._projects_root()
    d = root / 'dir-name'
    d.mkdir(parents=True)
    # dirs 是列表项内层键（`    dirs:` 缩进行）——dirs-覆盖-引擎仓根规则的真形态
    (d / 'project.yaml').write_text(
        'project:\n  - note: no explicit key here\n    dirs:\n      - %s\n'
        % el.ENGINE_REPO, encoding='utf-8')
    assert el._engine_project_key() == 'dir-name'


def test_engine_row_unresolved_owner_announce_only(monkeypatch, tmp_path, capsys):
    """C3 选型（announce-only）：注册表缺席 ⇒ 不落文件、不造幻影项目、stderr 点名。"""
    _stub(monkeypatch)
    got = el.append_event({'scope': 'engine', 'project': '', 'ticket': 'wf-1',
                           'stage': 'scan', 'state': 'running', 'reason': '',
                           'seq': 1, 'run_id': 'run-E1',
                           'idem': '|wf-1|run-E1|1'}, tmp_path / 'ledger')
    assert got['emitted'] is False and got['failed'] is True
    assert 'engine-owner' in got['why']
    err = capsys.readouterr().err
    assert '账面写失败' in err and '?engine' in err
    assert list((tmp_path / 'ledger').iterdir() if (tmp_path / 'ledger').is_dir() else []) == []


def test_engine_row_disabled_project_zero_files(monkeypatch, tmp_path):
    """未声明/停用 ⇒ 零行为（规格 item 7 继承）：enabled 闸在解析之后仍然生效。"""
    _enable_engine_owner(tmp_path)
    # 把声明去掉（未声明形态）
    (el._find_engine_project_yaml(el._projects_root())).write_text(
        'project:\n  - key: owner\n    dirs:\n      - %s\n' % el.ENGINE_REPO,
        encoding='utf-8')
    el.reset_config_for_test()
    got = el.append_event({'scope': 'engine', 'project': '', 'ticket': 'wf',
                           'stage': 's', 'state': 'st', 'reason': '', 'seq': 1,
                           'run_id': 'r', 'idem': '|wf|r|1'}, tmp_path / 'ledger')
    assert got['emitted'] is False and '未声明' in got['why']


# ---------- 每类重放安全（规格 item 6）：patched=False ⇒ 五类全零行为 ----------

def test_old_instances_replay_with_zero_change(monkeypatch):
    _stub(monkeypatch, patched=False)
    import inspection_flow as flow
    import workflows as wf_mod
    # 巡检两链：_enter 零入队
    wf = _periodic('proj-a')
    wf._enter('setup', 'running', '进')
    assert wf._ledger_pending is None and wf._ledger_marks is None
    assert set(wf.timeline[-1]) == {'at', 'stage', 'state', 'reason'}
    # 无 timeline 类：_ledger_note 零入队
    for cls in (flow.InspectionPeriodicSpawnWorkflow,
                flow.InspectionTicketCountWatcherWorkflow,
                wf_mod.DispatcherScanWorkflow):
        inst = object.__new__(cls)
        inst._ledger_note('scan', 'running', 'x')
        assert inst._ledger_pending is None and inst._ledger_marks is None


def test_flush_fail_open_on_activity_error(monkeypatch):
    """规格 item 7 继承：活动级异常绝不打断主流程（fail-open 兜底面）。"""
    import asyncio

    def _boom(*a, **k):
        raise RuntimeError('activity unavailable')
    _stub(monkeypatch, execute_activity=_boom)
    wf = _periodic('proj-a')
    wf._enter('setup', 'running', '进')
    assert len(wf._ledger_pending) == 1          # flush 前在队
    import asyncio
    asyncio.run(wf._ledger_flush())              # 不抛 = fail-open 成立
    assert wf._ledger_pending == []              # 排空（丢失面由活动侧留痕）
    # 空 pending 面：零活动命令直接返回（主循环热路径不加负担）
    _stub(monkeypatch)
    asyncio.run(_periodic('proj-a')._ledger_flush())


# ---------- 源码锁：接线矩阵与刻意豁免 ----------

def test_wiring_matrix_and_contentpipeline_exempt():
    import inspection_flow as flow
    import workflows as wf_mod
    wired = {flow.InspectionPeriodicWorkflow: 'project',
             flow.InspectionProduceWorkflow: 'project',
             flow.InspectionPeriodicSpawnWorkflow: 'engine',
             flow.InspectionTicketCountWatcherWorkflow: 'engine',
             wf_mod.DispatcherScanWorkflow: 'engine',
             wf_mod.ContentPipelineWorkflow: None}
    for cls, scope in wired.items():
        has = issubclass(cls, TicketEventLedgerMixin)
        if scope is None:
            # ContentPipelineWorkflow 刻意豁免：step-1 向后兼容壳（模板族 260904 退役，
            # 非执行器之手）——接了也是死观测面；漂移（被接上）即红，人工复评
            assert not has, '%s 不应继承 mixin（刻意豁免）' % cls.__name__
        else:
            assert has, '%s 应已接线' % cls.__name__
            assert cls._ledger_scope == scope
