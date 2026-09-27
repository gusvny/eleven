"""t260927 缺口 5——项目外置模板的目录面与拓扑导出面（宿主令直修，L2/L3 灰盒锁）。

缺口（nusuyou 需求书三点九节）：项目外置模板（`paths.workflow_modules` 那一类）此前
只接进了校验/创建/运行三面，**目录面（workflow.py list）与拓扑导出面（票面 topology）
都没接**——外置模板的票在控制台里看不到泳道图：
  · `python3 server/tools/workflow.py '{"op":"list"}'` 只列 dev-lane ⇒ 前端
    `wfById[detail.workflow_id]` 查不到拓扑 ⇒ 泳道图不渲染、行卡操作位降级；
  · `ticket.py show <外置模板票>` 的 topology=None（外置模板的 workflow 类在项目仓，
    其 snapshot() 不含引擎导出面）⇒ 渲染器没有可画的图。

覆盖（按验收口径三层）：
  1. 目录面并入外置模板（正例：id/name/lane/stages/topology 齐；反例：「非该项目 /
     未声明」注入根 → 面仍恰 {dev-lane}，收窄守卫零放宽）；
  2. 拓扑导出三态：内置（登记表声明拓扑，含并行组）/ 外置（由模板类 STAGES 导出，
     线性链+人门 kind 正确）/ 未知（None，绝不冒充）；
  3. 零回归：默认面仍是 {dev-lane}；SANDBAR_FIXTURE_TEMPLATES 语义不变（不置=无夹具行，
     置 1=夹具行照进）；dev-lane 行形状逐键不变；内置票的票面拓扑兜底零 spawn。

灰盒纪律：断言只落公开面（CLI 回执 json / stderr 点名 / 票面字典），不锚内部实现；
夹具全本地（临时 per-key 注册根 + 真形状模块），真 registry 有/无登记都不影响断言。
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent
REPO = ENGINE_DIR.parent.parent

# 真形状外置模板模块：temporalio @workflow.defn + STAGES（含人门段）——与项目侧
# 模板同形状，段声明就是它的拓扑真源。
GOOD_TMPL = '''TEMPLATE_ID = "{tid}"
TEMPLATE_NAME = "外置流"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage


@workflow.defn
class {cls}(TicketWorkflowBase):
    STAGES = (
        Stage(id="px-one", name="一段", role="developer", next="px-two", parts=("agent",)),
        Stage(id="px-two", name="二段（人）", role="integration", exit="human",
              revision_to="px-one", parts=("human",)),
    )
    PATCH_ID = "{patch}"
    TEMPLATE_ID = "{tid}"
    TEMPLATE_NAME = "外置流"
    TEMPLATE_LANE = "main"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''

DEV_LANE_ROW_KEYS = {'id', 'name', 'lane', 'stages', 'topology'}
DEV_LANE_STAGE_KEYS = {'id', 'role', 'name', 'next', 'exit', 'fanout', 'revision_to',
                       'parts', 'acceptance'}


# ---------------------------------------------------------------------------
# 夹具与工具
# ---------------------------------------------------------------------------

def _stage_registry(root: pathlib.Path, key: str = 'ext-probe',
                    modules: dict = None) -> pathlib.Path:
    """临时 per-key 注册根（SANDBAR_PROJECTS_DIR 目录模式）：project.yaml 声明
    workflow_modules + 模块落盘。`.migrated` 预置=拒绝 legacy 迁移写（夹具只读）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / '.migrated').write_text('', 'utf-8')
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    (pd / 'project.yaml').write_text(
        'schema: v1\nproject:\n  - key: %s\n    name: 外置模板探针\n    dirs:\n'
        '      - %s\npaths:\n  workflow_modules: %s\n'
        % (key, pd, ','.join('mods/%s' % m for m in (modules or {}))), 'utf-8')
    (pd / 'mods').mkdir(exist_ok=True)
    for fname, body in (modules or {}).items():
        (pd / 'mods' / fname).write_text(body, 'utf-8')
    return root


def _empty_registry(root: pathlib.Path) -> pathlib.Path:
    """未声明任何 workflow_modules 的注册根（「非该项目 / 未声明」反例面）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / '.migrated').write_text('', 'utf-8')
    return root


def _env_for(root, tmp_path, fixture_templates=None):
    env = dict(os.environ)
    env['SANDBAR_PROJECTS_DIR'] = str(root)
    env['TEMPORAL_ADDRESS'] = '127.0.0.1:1'   # 不可达端口：连了即红（本面零 Temporal）
    env['PYTHONPYCACHEPREFIX'] = str(tmp_path / 'pycache')
    if fixture_templates is None:
        env.pop('SANDBAR_FIXTURE_TEMPLATES', None)
    else:
        env['SANDBAR_FIXTURE_TEMPLATES'] = fixture_templates
    return env


def _run_workflow_list(root, tmp_path, fixture_templates=None):
    """真通道：spawn server/tools/workflow.py（引擎 venv 解释器=目录面真实运行形态），
    返回 (rows, stderr)。"""
    py = ENGINE_DIR / '.venv' / 'bin' / 'python'
    if not py.is_file():
        pytest.skip('引擎 venv 缺失（外置模板类面不可加载，真通道不可测）')
    proc = subprocess.run([str(py), str(REPO / 'server' / 'tools' / 'workflow.py'),
                           '{"op":"list"}'],
                          cwd=str(REPO), env=_env_for(root, tmp_path, fixture_templates),
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, 'list 非零退出：%s' % (proc.stderr[-400:],)
    return json.loads(proc.stdout)['workflows'], proc.stderr


def _load_workflow_mod():
    spec = importlib.util.spec_from_file_location(
        '_wfmod_t260927', REPO / 'server' / 'tools' / 'workflow.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_wfmod_t260927'] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_ticket_mod():
    spec = importlib.util.spec_from_file_location(
        '_ticketmod_t260927', REPO / 'server' / 'tools' / 'ticket.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_ticketmod_t260927'] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# ① 目录面并入项目外置模板（正例）+「未声明」反例
# ---------------------------------------------------------------------------

def test_list_merges_project_external_template(tmp_path):
    """正例：项目登记的外置模板进目录面，带 stages 与 topology；内置行零回归。"""
    pytest.importorskip('temporalio', reason='外置模板类面现算需引擎依赖（venv 面验证）')
    root = _stage_registry(tmp_path / 'projects', 'ext-probe',
                           {'px.py': GOOD_TMPL.format(tid='ext-probe-flow',
                                                      cls='ExtProbeFlow',
                                                      patch='ext-probe-v1')})
    rows, err = _run_workflow_list(root, tmp_path)
    by_id = {r['id']: r for r in rows}

    assert 'ext-probe-flow' in by_id, '外置模板未进目录面（stderr=%s）' % err[-400:]
    ext = by_id['ext-probe-flow']
    assert ext['name'] == '外置流' and ext['lane'] == 'main'
    assert [s['id'] for s in ext['stages']] == ['px-one', 'px-two']
    # 段行形状与内置同键（控制台站道/角色/执行主体消费面零分叉）
    assert set(ext['stages'][0]) >= DEV_LANE_STAGE_KEYS
    assert ext['stages'][0]['parts'] == ['agent']
    # 拓扑导出：节点=段全集、边引用合法、人门 kind 正确（kind 投影与 STAGES 同口径）
    topo = ext['topology']
    assert isinstance(topo, dict) and topo['version'] == 'topology-v1'
    assert topo['template'] == 'ext-probe-flow'
    assert [n['id'] for n in topo['nodes']] == ['px-one', 'px-two']
    kinds = {n['id']: n['kind'] for n in topo['nodes']}
    assert kinds == {'px-one': 'agent', 'px-two': 'human'}
    node_ids = set(kinds)
    assert all(a in node_ids and b in node_ids for a, b in topo['edges'])
    assert topo['groups'] == []   # 外置模板无并行组声明：导出线性链，不冒充并行

    # 内置行零回归：形状/段集/声明拓扑（含并行组）逐项不变
    dev = by_id['dev-lane']
    assert set(dev) == DEV_LANE_ROW_KEYS
    assert dev['lane'] == 'worktree'
    assert len(dev['stages']) == 10
    assert set(dev['stages'][0]) == DEV_LANE_STAGE_KEYS
    assert len(dev['topology']['nodes']) == 10 and len(dev['topology']['groups']) == 2


def test_list_without_declaration_keeps_narrow_default_face(tmp_path):
    """反例（零回归硬锁）：注册根里没有任何 workflow_modules 声明 → 面仍恰 {dev-lane}。"""
    root = _empty_registry(tmp_path / 'projects')
    rows, err = _run_workflow_list(root, tmp_path)
    assert [r['id'] for r in rows] == ['dev-lane'], (rows, err[-300:])
    # 面外项目（本机真注册表里的 nusuyou 等）不得因「机器上有登记」漏进注入面
    assert 'content-studio' not in {r['id'] for r in rows}


def test_declared_but_absent_template_is_named_on_stderr(tmp_path):
    """未进目录面的已声明模板必须点名（需求③：宿主不必在 UI 里找半天）。

    两形态：①名面已接受、类面拒收（id 可辨）→ 按 id 点名；②名面即拒（无 defn 类，
    id 不可辨）→ 按模块路径+检查项点名。两种都不得静默。"""
    root = _stage_registry(tmp_path / 'projects', 'ext-probe', {
        'ghost.py': ('TEMPLATE_ID = "ext-probe-ghost"\nTEMPLATE_NAME = "缺席探针"\n'
                     'from temporalio import workflow\n'
                     'import no_such_module_xyz\n\n\n'
                     '@workflow.defn\nclass GhostFlow:\n    pass\n'),
        'shapeless.py': 'TEMPLATE_ID = "ext-probe-shapeless"\nTEMPLATE_NAME = "无类探针"\n',
    })
    rows, err = _run_workflow_list(root, tmp_path)
    ids = {r['id'] for r in rows}
    assert 'ext-probe-ghost' not in ids and 'ext-probe-shapeless' not in ids, \
        '未通过类面的模块不得冒充进目录面'
    assert 'ext-probe-ghost' in err and '未在目录面' in err, \
        '类面拒收的已声明模板未按 id 点名（stderr=%r）' % err[-400:]
    assert 'no_such_module_xyz' in err, '点名须带原因（缺什么）'
    assert 'shapeless.py' in err and '模板类不可辨' in err, \
        '名面即拒的畸形模块未点名模块路径+检查项（stderr=%r）' % err[-400:]


def test_fixture_env_semantics_unchanged(tmp_path):
    """零回归：SANDBAR_FIXTURE_TEMPLATES 语义不变（不置=无夹具行；置 1=夹具行照进）。"""
    pytest.importorskip('temporalio', reason='v2 注册表导入需引擎依赖')
    root = _empty_registry(tmp_path / 'projects')
    rows_off, _ = _run_workflow_list(root, tmp_path)
    assert {r['id'] for r in rows_off} == {'dev-lane'}
    rows_on, _ = _run_workflow_list(root, tmp_path, fixture_templates='1')
    ids_on = {r['id'] for r in rows_on}
    assert {'dev-lane', 'fixture-two-step'} <= ids_on, ids_on


# ---------------------------------------------------------------------------
# ② 拓扑导出三态（内置 / 外置 / 未知）
# ---------------------------------------------------------------------------

def test_topology_three_states():
    """_topology_of 三态：内置=登记表声明拓扑；外置=项目面现算拓扑；未知=None。"""
    wf = _load_workflow_mod()
    dev = wf._topology_of('dev-lane')
    assert isinstance(dev, dict) and len(dev['groups']) == 2, '内置声明拓扑（含真并行组）'

    derived = {'ext-flow': {'version': 'topology-v1', 'template': 'ext-flow',
                            'name': '外置', 'nodes': [{'id': 'a', 'label': 'A',
                                                       'role': 'developer',
                                                       'kind': 'agent', 'parts': []}],
                            'edges': [], 'groups': []}}
    assert wf._topology_of('ext-flow', derived)['template'] == 'ext-flow'
    # 未知模板：两档都没有 → None（不冒充）
    assert wf._topology_of('no-such-template') is None
    assert wf._topology_of('no-such-template', derived) is None
    # 内置 id 优先吃登记表（不被项目面覆盖）
    assert len(wf._topology_of('dev-lane', derived)['nodes']) == 10


def test_build_topology_from_stages_fail_closed():
    """段声明导出：dict 形态两吃、kind 投影同 STAGES；空段/畸形段 fail-closed。"""
    import template_topology as tt

    topo = tt.build_topology_from_stages('t', 'T', [
        {'id': 'a', 'name': '甲', 'role': 'developer', 'next': 'b', 'parts': ['agent']},
        {'id': 'b', 'name': '乙', 'role': 'integration', 'exit': 'human',
         'parts': ['human']},
        {'id': 'c', 'name': '丙', 'role': 'ops', 'agent': False, 'parts': ['script']},
    ])
    assert topo['version'] == 'topology-v1' and topo['template'] == 't'
    assert [n['kind'] for n in topo['nodes']] == ['agent', 'human', 'gate']
    assert topo['edges'] == [['a', 'b'], ['b', 'c']]

    with pytest.raises(ValueError):
        tt.build_topology_from_stages('t', 'T', [])            # 空段：无可画拓扑
    with pytest.raises(ValueError):
        tt.build_topology_from_stages('t', 'T', [{'id': '', 'name': 'x'}])   # 缺 id
    with pytest.raises(ValueError):
        tt.build_topology_from_stages('t', 'T', [{'id': 'a', 'name': 'x'},
                                                 {'id': 'a', 'name': 'y'}])  # id 重复
    # 未知模板仍 None（登记表挡在导出面前）
    assert tt.export_template_topology('no-such-template') is None


# ---------------------------------------------------------------------------
# ③ 票面 topology 兜底（外置模板票有图可画；内置票零 spawn）
# ---------------------------------------------------------------------------

_EXT_FACES = {
    'class_available': ['ext-flow'],
    'names': {'dev-lane': 'DevLaneWorkflow', 'ext-flow': 'ExtFlow'},
    'rejections': [],
    'builtin': ['dev-lane'],
    'declared_projects': 1,
    'projects_scanned': 1,
    'templates': {'ext-flow': {
        'name': '外置流', 'lane': 'main', 'workspace_dir': False,
        'stages': [{'id': 'a', 'role': 'developer', 'name': '甲'},
                   {'id': 'b', 'role': 'integration', 'name': '乙'}],
        'topology': {'version': 'topology-v1', 'template': 'ext-flow', 'name': '外置流',
                     'nodes': [{'id': 'a', 'label': '甲', 'role': 'developer',
                                'kind': 'agent', 'parts': ['agent']},
                               {'id': 'b', 'label': '乙', 'role': 'integration',
                                'kind': 'human', 'parts': ['human']}],
                     'edges': [['a', 'b']], 'groups': []},
        'topology_error': '',
    }},
}


def test_ticket_face_topology_fallback_for_external_template(monkeypatch, capsys):
    """外置模板票：快照无 topology → 回落模板级导出（创建面同源回执）。"""
    ticket = _load_ticket_mod()
    monkeypatch.setattr(ticket, '_template_faces', lambda: _EXT_FACES)
    meta = {'workflow_id': 'ext-flow', 'topology': None}
    ticket._template_topology_fallback(meta)
    assert meta['topology']['template'] == 'ext-flow'
    assert [n['kind'] for n in meta['topology']['nodes']] == ['agent', 'human']


def test_ticket_face_topology_builtin_and_present_are_untouched(monkeypatch):
    """零回归：内置票不 spawn（快路径）；已有拓扑的票不被覆写。"""
    ticket = _load_ticket_mod()
    calls = []

    def _boom():
        calls.append(1)
        raise AssertionError('内置票/已有拓扑的票不得触达权威模板面')

    monkeypatch.setattr(ticket, '_template_faces', _boom)
    builtin = {'workflow_id': 'dev-lane', 'topology': None}
    ticket._template_topology_fallback(builtin)
    assert builtin['topology'] is None and calls == []
    have = {'workflow_id': 'ext-flow', 'topology': {'template': 'ext-flow', 'nodes': []}}
    ticket._template_topology_fallback(have)
    assert have['topology'] == {'template': 'ext-flow', 'nodes': []} and calls == []


def test_ticket_face_topology_unknown_and_unreachable_stay_none(monkeypatch, capsys):
    """未知模板 / 权威面不可达：保持 None（不冒充）且点名原因，绝不炸 show。"""
    ticket = _load_ticket_mod()
    monkeypatch.setattr(ticket, '_template_faces',
                        lambda: {'templates': {'other-flow': {'topology': None}}})
    meta = {'workflow_id': 'ext-flow', 'topology': None}
    ticket._template_topology_fallback(meta)          # 回执无该模板 → 不冒充
    assert meta['topology'] is None

    def _fail():
        raise ValueError('权威模板面不可达（template-faces 子进程故障）')

    monkeypatch.setattr(ticket, '_template_faces', _fail)
    meta2 = {'workflow_id': 'ext-flow', 'topology': None}
    ticket._template_topology_fallback(meta2)         # 面不可达 → 不炸、点名
    assert meta2['topology'] is None
    assert '不可达' in capsys.readouterr().err
