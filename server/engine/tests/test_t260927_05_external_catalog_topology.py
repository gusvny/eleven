"""t260927-05：外置模板目录合并 + 拓扑导出（catalog & topology for project templates）。

覆盖面（对票面验收逐条）：
  A. template_topology.topology_from_stages —— STAGES 线性投影（类属性/dict 双形态、
     kind 投影、空序列/缺 id fail-closed）；
  B. workflow.py list —— 项目外置模板行并入（positive + 未声明反例 + project 过滤
     无跨项目泄漏 + faces 故障 catalog_note 点名 + 默认面零回归）；
  C. workflow.py list/show —— faces 回执畸形（外部输入用例纪律）fail-closed 点名；
  D. workflow.py show —— 外置 id 走权威面推导视图；真未知 id 维持旧 raise 契约；
  E. ticket.py _v2_query —— 快照缺拓扑时经 template-faces 回落；快照有拓扑零变化；
     faces 故障不炸、回落 None。

faces 子进程通道一律 monkeypatch 桩（固定文件复现，不靠真外部源/真注册表）。
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ENGINE = HERE.parent
TOOLS = ENGINE.parent / 'tools'

sys.path.insert(0, str(ENGINE))
import template_topology as tt  # noqa: E402

# workflow.py / ticket.py 都是脚本型工具：按路径装载（不改它们的结构）。
def _load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wf = _load_mod('_t26092705_workflow', TOOLS / 'workflow.py')


# ---------------------------------------------------------------------------
# A. topology_from_stages
# ---------------------------------------------------------------------------

class _St:
    """类属性形态的 Stage 桩（与引擎 Stage 同形子集）。"""
    def __init__(self, id, name='', role='', exit='', parts=()):
        self.id, self.name, self.role, self.exit, self.parts = id, name, role, exit, parts


def test_stages_linear_projection_classform():
    topo = tt.topology_from_stages('content-studio', 'Content Studio', (
        _St('draft', '起草', 'developer', '', ('agent',)),
        _St('check', '机检', '', '', ('script',)),
        _St('sign', '人审', '', 'human', ('human',)),
    ))
    assert topo['version'] == 'topology-v1'
    assert topo['template'] == 'content-studio'
    assert [n['id'] for n in topo['nodes']] == ['draft', 'check', 'sign']
    kinds = {n['id']: n['kind'] for n in topo['nodes']}
    assert kinds == {'draft': 'agent', 'check': 'gate', 'sign': 'human'}
    # 线性顺序边、无并行组（STAGES 不携带分叉信息，绝不猜拓扑）
    assert topo['groups'] == []
    assert topo['edges'] == [['draft', 'check'], ['check', 'sign']]


def test_stages_projection_dict_form_and_defaults():
    topo = tt.topology_from_stages('x', '', [{'id': 'a'}, {'id': 'b', 'name': '乙'}])
    assert topo['name'] == 'x'
    assert topo['nodes'][0]['label'] == 'a'
    assert topo['nodes'][1]['label'] == '乙'
    assert all(n['kind'] == 'agent' for n in topo['nodes'])


def test_stages_projection_fail_closed():
    with pytest.raises(ValueError):
        tt.topology_from_stages('x', 'x', [])            # 空序列
    with pytest.raises(ValueError):
        tt.topology_from_stages('x', 'x', [{'name': '无 id'}])  # 缺 id


def test_builtin_export_unknown_still_none():
    # 已有契约零回归：静态表未声明的模板= None（绝不 fake）
    assert tt.export_template_topology('content-studio') is None
    assert tt.export_template_topology('no-such') is None
    assert tt.export_template_topology('dev-lane')['template'] == 'dev-lane'


# ---------------------------------------------------------------------------
# B/C/D. workflow.py list / show
# ---------------------------------------------------------------------------

_EXT_ROW = {'id': 'content-studio', 'name': 'Content Studio', 'lane': 'worktree',
            'stages': [{'id': 'draft', 'role': 'developer', 'name': '起草'}],
            'project': 'nusuyou', 'topology': {'template': 'content-studio', 'nodes': [1]}}
_OTHER_ROW = {'id': 'other-proj-tpl', 'name': 'Other', 'lane': 'worktree',
              'stages': [{'id': 's1', 'role': '', 'name': 's1'}],
              'project': 'another', 'topology': None}


def _stub_rows(monkeypatch, rows, note=''):
    monkeypatch.setattr(wf, '_faces_catalog', lambda project=None: (rows, note)
                        if project is None else
                        ([r for r in rows if r['project'] == project], note))


def test_list_merges_project_rows(monkeypatch):
    _stub_rows(monkeypatch, [_EXT_ROW, _OTHER_ROW])
    out = wf.run({'op': 'list'})
    ids = [w['id'] for w in out['workflows']]
    assert 'dev-lane' in ids                       # 内置面零回归
    assert 'content-studio' in ids                 # 项目模板并入
    row = next(w for w in out['workflows'] if w['id'] == 'content-studio')
    assert row['stages'] and row['project'] == 'nusuyou'
    assert row['topology'] == {'template': 'content-studio', 'nodes': [1]}
    assert 'catalog_note' not in out               # 正常路径无缺席注记


def test_list_project_filter_no_leakage(monkeypatch):
    _stub_rows(monkeypatch, [_EXT_ROW, _OTHER_ROW])
    out = wf.run({'op': 'list', 'project': 'nusuyou'})
    ids = [w['id'] for w in out['workflows']]
    assert 'content-studio' in ids
    assert 'other-proj-tpl' not in ids             # 未声明方不可见（无全局泄漏）


def test_list_default_face_zero_regression(monkeypatch):
    # 未声明任何项目（faces 无项目行）→ 默认面形状与旧契约一致：仅 yaml 行、无 note
    _stub_rows(monkeypatch, [])
    out = wf.run({'op': 'list'})
    # 宿主令 260930：内置面加一格 light-lane（轻道泳道）——目录面按 yaml 参考目录列行，
    # 「未声明项目不泄漏」的语义不变（无项目行、无 note）。
    assert [w['id'] for w in out['workflows']] == ['dev-lane', 'light-lane', 'quickmanual-lane']
    assert 'catalog_note' not in out


def test_list_faces_failure_named_not_fatal(monkeypatch):
    _stub_rows(monkeypatch, [], note='project template face unreachable (TimeoutExpired)')
    out = wf.run({'op': 'list'})
    # 通道不炸（宿主令 260930：内置面含 light-lane）
    assert [w['id'] for w in out['workflows']] == ['dev-lane', 'light-lane', 'quickmanual-lane']
    assert 'project template face unreachable' in out['catalog_note']  # 缺席点名


def test_faces_catalog_malformed_receipts(monkeypatch):
    """外部输入畸形用例：非 JSON / ok=false / 缺键——一律 fail-closed 点名不静默。"""
    class P:
        def __init__(self, stdout):
            self.stdout, self.stderr = stdout, ''
    cases = [
        ('not-json', 'non-JSON'),
        (json.dumps({'ok': False, 'error': 'boom'}), 'rejected'),
        (json.dumps({'ok': True, 'result': {}}), 'malformed'),            # 缺 templates
        (json.dumps({'ok': True, 'result': {'templates': {}, 'class_available': [1],
                                            'builtin': []}}), 'malformed'),  # 类型错
    ]
    for stdout, expect in cases:
        monkeypatch.setattr(wf.subprocess, 'run',
                            lambda cmd, **kw: P(stdout), raising=True)
        rows, note = wf._faces_catalog()
        assert rows == []
        assert expect in note


def test_show_external_id_via_faces(monkeypatch):
    _stub_rows(monkeypatch, [_EXT_ROW])
    t = wf.run({'op': 'show', 'id': 'content-studio'})
    assert t['id'] == 'content-studio' and t['stages']


def test_show_unknown_id_keeps_raise(monkeypatch):
    _stub_rows(monkeypatch, [])
    with pytest.raises(ValueError, match='模板不存在'):
        wf.run({'op': 'show', 'id': 'no-such-anywhere'})


# ---------------------------------------------------------------------------
# 仲裁返工（gen1）：Gap 1 拒收声明必须点名；Gap 2 退化 STAGES 的 topology=None
# 必须有名有姓（topology_error 透传 + stderr 点名）。
# ---------------------------------------------------------------------------

def _faces_receipt(monkeypatch, result):
    class P:
        stdout, stderr = json.dumps({'ok': True, 'result': result}), ''
    monkeypatch.setattr(wf.subprocess, 'run', lambda cmd, **kw: P(), raising=True)


def test_rejections_named_in_catalog_note(monkeypatch, capsys):
    """Gap 1：声明了但被加载口拒收 → note + stderr 点名，绝不静默。"""
    _faces_receipt(monkeypatch, {
        'templates': {}, 'class_available': [], 'builtin': ['dev-lane'],
        'rejections': [{'project': 't05brk', 'module': 'mods/broken.py',
                        'check': '畸形', 'detail': '模板类不可辨'}],
    })
    rows, note = wf._faces_catalog()
    assert rows == []
    assert 'project t05brk declares external template (module mods/broken.py)' in note
    assert 'not in the catalog' in note and '畸形' in note
    assert 't05brk' in capsys.readouterr().err            # stderr 有痕


def test_list_surfaces_rejection_note(monkeypatch):
    """Gap 1 经 run(list)：note 上台为 catalog_note（用户不在 UI 里打空手）。"""
    _faces_receipt(monkeypatch, {
        'templates': {}, 'class_available': [], 'builtin': ['dev-lane'],
        'rejections': [{'project': 'p1', 'module': 'mods/broken.py',
                        'check': '畸形', 'detail': 'x'}],
    })
    out = wf.run({'op': 'list'})
    ids = [w['id'] for w in out['workflows']]
    # 默认面行集不变（宿主令 260930：= 内置面 {dev-lane, light-lane}，无外置行泄漏）
    assert ids == ['dev-lane', 'light-lane', 'quickmanual-lane']
    assert 'p1 declares external template' in out['catalog_note']


def test_rejection_filter_by_project(monkeypatch):
    """拒收点名同样按声明方过滤（未声明方不见别项目的缺席）。"""
    _faces_receipt(monkeypatch, {
        'templates': {}, 'class_available': [], 'builtin': ['dev-lane'],
        'rejections': [{'project': 'p1', 'module': 'm.py', 'check': 'c', 'detail': 'd'},
                       {'project': 'p2', 'module': 'n.py', 'check': 'c', 'detail': 'd'}],
    })
    _rows, note = wf._faces_catalog(project='p1')
    assert 'p1' in note and 'p2' not in note


def test_degenerate_stages_topology_named(monkeypatch, capsys):
    """Gap 2：STAGES=() → topology=None 但 topology_error 透传 + stderr 点名。"""
    _faces_receipt(monkeypatch, {
        'templates': {'t05-empty': {'name': 'Empty', 'lane': 'worktree',
                                    'stages': [], 'project': 'p1',
                                    'topology': None,
                                    'topology_error': 'ValueError: STAGES 空序列'}},
        'class_available': ['t05-empty'], 'builtin': ['dev-lane'], 'rejections': [],
    })
    rows, note = wf._faces_catalog()
    assert len(rows) == 1
    assert rows[0]['topology'] is None
    assert rows[0]['topology_error'] == 'ValueError: STAGES 空序列'  # 不匿名
    assert 't05-empty' in capsys.readouterr().err
    assert note == ''  # 行在目录里，非缺席——note 不掺入


def test_healthy_template_has_no_topology_error(monkeypatch):
    """正常模板行 topology_error=None（形状稳定，消费面零分支负担）。"""
    _faces_receipt(monkeypatch, {
        'templates': {'ok-tpl': {'name': 'OK', 'lane': 'worktree',
                                 'stages': [{'id': 'a'}], 'project': 'p1',
                                 'topology': {'nodes': [1]}, 'topology_error': ''}},
        'class_available': ['ok-tpl'], 'builtin': ['dev-lane'], 'rejections': [],
    })
    rows, note = wf._faces_catalog()
    assert rows[0]['topology'] == {'nodes': [1]}
    assert rows[0]['topology_error'] is None and note == ''


# ---------------------------------------------------------------------------
# E. ticket.py _v2_query 拓扑回落
# ---------------------------------------------------------------------------

tk = _load_mod('_t26092705_ticket', TOOLS / 'ticket.py')


def _stub_query(monkeypatch, snap_topology, workflow_id='content-studio'):
    """_v2_query 的 _poc/_shared/_template_faces 三依赖全桩（不 spawn 真子进程）。"""
    monkeypatch.setattr(tk, '_poc', lambda sub, payload, caller=None: {
        'ok': True,
        'result': {'engine': 'template-as-code-v2',
                   'ticket': {'workflow_id': workflow_id},
                   'snapshot': {'topology': snap_topology, 'stage_acceptance': []}},
    })
    monkeypatch.setattr(tk, '_shared', lambda: types.SimpleNamespace(
        ENGINE_V2='template-as-code-v2'))
    calls = {}

    def _faces():
        calls['n'] = calls.get('n', 0) + 1
        return {'templates': {'content-studio': {'topology': {'template': 'content-studio',
                                                              'nodes': ['n1']}}}}
    monkeypatch.setattr(tk, '_template_faces', _faces)
    return calls


def test_query_topology_fallback_for_external(monkeypatch):
    calls = _stub_query(monkeypatch, snap_topology=None)
    meta, _snap = tk._v2_query('t1')
    assert meta['topology'] == {'template': 'content-studio', 'nodes': ['n1']}
    assert calls['n'] == 1


def test_query_snapshot_topology_wins(monkeypatch):
    calls = _stub_query(monkeypatch, snap_topology={'template': 'snap', 'nodes': []})
    meta, _snap = tk._v2_query('t1')
    assert meta['topology'] == {'template': 'snap', 'nodes': []}
    assert calls.get('n') is None  # 快照有拓扑 → 权威面通道零调用（零回归）


def test_query_unknown_template_keeps_none(monkeypatch):
    _stub_query(monkeypatch, snap_topology=None, workflow_id='no-such-template')
    meta, _snap = tk._v2_query('t1')
    assert meta['topology'] is None  # known-unknown：不 fake


def test_query_faces_failure_degrades_named(monkeypatch, capsys):
    _stub_query(monkeypatch, snap_topology=None)
    def _boom():
        raise ValueError('权威模板面不可达（template-faces 子进程故障）：timeout')
    tk._template_faces = _boom  # noqa: F841——monkeypatch.setattr 同效，直接换桩
    monkeypatch.setattr(tk, '_template_faces', _boom)
    meta, _snap = tk._v2_query('t1')
    assert meta['topology'] is None                # 回落 None，show 不炸
    assert 'template-faces' in capsys.readouterr().err  # stderr 点名有痕
