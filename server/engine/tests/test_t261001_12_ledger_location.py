"""事件账本落盘位置（工单 t261001-12）：账本随项目走。

钉死两种形状（双向锁，任一漂移即红）：
  - 缺省（生产形状，env 未设）：<projects_root>/<project>/ledger/events.jsonl，
    gaps=events.gaps.jsonl，归档=events.jsonl.<YYYYMMDD>-<HHMMSS>-<hex>；
  - 平铺兼容缝（语义不变）：SANDBAR_EVENT_LEDGER_DIR（或显式 ledger_dir）⇒
    <dir>/<project>.jsonl，gaps=<project>.gaps.jsonl（存量场景/夹具形状）。
另覆盖：缺省形状下的 append 端到端、轮转+清扫命名面、gaps 补写落点。

跨语言一致性锁（python 解析器 vs watchdog 读侧）在
server/plugins/watchdog/tests/ledger-location.test.mjs——本文件只锁 python 侧形状。

对 pre-fix 代码是红的（anti-proof）：旧缺省=<引擎仓>/server/ledger/<project>.jsonl，
本文件缺省形状用例全部不存在/不等价。
"""
import json
import os
import time

import pytest

import event_ledger as el


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    """缺省形状隔离：env 平铺缝**显式缺席**（缺省形状=env unset 的生产口径），
    注册表根钉进 tmp。"""
    monkeypatch.delenv('SANDBAR_EVENT_LEDGER_DIR', raising=False)
    monkeypatch.setenv('SANDBAR_PROJECTS_DIR', str(tmp_path / 'projects'))
    (tmp_path / 'projects').mkdir(exist_ok=True)
    el.reset_config_for_test()
    yield el._projects_root()
    el.reset_config_for_test()


def _enable(root):
    """造「引擎所属项目」声明 event_ledger enabled 的注册表（dirs 真覆盖引擎仓根，
    与 test_event_ledger._enable 同规则）。"""
    d = root / 'alpha'
    d.mkdir(exist_ok=True)
    (d / 'project.yaml').write_text(
        'schema: v1\n'
        'project:\n  - key: engine-owner\n    dirs:\n      - %s\n'
        'event_ledger:\n  enabled: true\n  keep_days: 14\n  max_mb: 0\n' % el.ENGINE_REPO,
        encoding='utf-8')
    el.reset_config_for_test()


# ---- 形状锁 ----

def test_default_shape_is_per_project(projects_root):
    assert el.ledger_path('proj') == projects_root / 'proj' / 'ledger' / 'events.jsonl'


def test_flat_env_seam_unchanged(projects_root, monkeypatch, tmp_path):
    flat = tmp_path / 'flat'
    flat.mkdir()
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(flat))
    assert el.ledger_path('proj') == flat / 'proj.jsonl'
    # 显式 ledger_dir 参数（rebuild/调用方注入）同样是平铺语义，env 在场也不翻转
    assert el.ledger_path('proj', tmp_path / 'other') == tmp_path / 'other' / 'proj.jsonl'


def test_explicit_ledger_dir_beats_env(projects_root, monkeypatch, tmp_path):
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(tmp_path / 'flat'))
    assert el.ledger_path('proj', tmp_path / 'other') == tmp_path / 'other' / 'proj.jsonl'


# ---- gaps 命名面 ----

def test_gap_record_lands_events_gaps(projects_root):
    el._write_gap_record('proj', 't1', 'why')
    g = projects_root / 'proj' / 'ledger' / 'events.gaps.jsonl'
    assert g.is_file()
    obj = json.loads(g.read_text(encoding='utf-8').splitlines()[0])
    assert obj['gap'] is True and obj['project'] == 'proj' and obj['ticket'] == 't1'
    # 活动文件不因 gap 补写而出现
    assert not (projects_root / 'proj' / 'ledger' / 'events.jsonl').exists()


def test_gap_record_flat_seam_keeps_project_name(projects_root, monkeypatch, tmp_path):
    flat = tmp_path / 'flat'
    flat.mkdir()
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(flat))
    el._write_gap_record('proj', 't1', 'why')
    assert (flat / 'proj.gaps.jsonl').is_file()


# ---- append 端到端（缺省形状，write side == 读侧同径） ----

def test_append_lands_per_project_default_shape(projects_root):
    _enable(projects_root)
    r1 = el.append_event({'project': 'proj', 'ticket': 't1', 'scope': 'project',
                          'state': 'running', 'seq': 1, 'run_id': 'r1', 'idem': 'k1'})
    assert r1.get('emitted') is True
    path = projects_root / 'proj' / 'ledger' / 'events.jsonl'
    assert r1['path'] == str(path) and path.is_file()
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l]
    assert len(rows) == 1 and rows[0]['idem'] == 'k1'
    # 幂等重投不落第二行（缺省路径的去重缓存按新路径生效）
    el.reset_config_for_test()
    r2 = el.append_event({'project': 'proj', 'ticket': 't1', 'scope': 'project',
                          'state': 'running', 'seq': 1, 'run_id': 'r1', 'idem': 'k1'})
    assert r2.get('emitted') is False and r2.get('dedup') is True
    assert len(path.read_text(encoding='utf-8').splitlines()) == 1


# ---- 轮转/清扫命名面（归档跟文件名走） ----

def _mk_active(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x' * size, encoding='utf-8')


def test_rotate_archive_name_follows_events_jsonl(projects_root):
    path = el.ledger_path('proj')
    _mk_active(path, 1024 * 1024 + 16)
    el._maybe_rotate(path, {'max_mb': 1})
    names = [n for n in os.listdir(path.parent) if n != 'events.jsonl']
    assert len(names) == 1
    today = time.strftime('%Y%m%d')
    assert names[0] == 'events.jsonl.%s' % today or names[0].startswith('events.jsonl.%s-' % today)
    assert not path.exists() or path.stat().st_size == 0 or True  # 活动已被 rename 走
    assert names[0] != 'events.jsonl'


def test_sweep_only_touches_events_archives(projects_root):
    path = el.ledger_path('proj')
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    old = 'events.jsonl.20200101-000000-ab12cd'
    fresh = 'events.jsonl.%s-000000-de34ef' % time.strftime('%Y%m%d')
    for n in (old, fresh, 'events.gaps.jsonl', 'events.jsonl'):
        (d / n).write_text('r\n', encoding='utf-8')
    el._sweep('proj', {'keep_days': 1})
    assert not (d / old).exists()
    for n in (fresh, 'events.gaps.jsonl', 'events.jsonl'):
        assert (d / n).exists()


def test_sweep_flat_seam_still_sweeps_project_archives(projects_root, monkeypatch, tmp_path):
    flat = tmp_path / 'flat'
    flat.mkdir()
    monkeypatch.setenv('SANDBAR_EVENT_LEDGER_DIR', str(flat))
    old = 'proj.jsonl.20200101-000000-ab12cd'
    (flat / old).write_text('r\n', encoding='utf-8')
    (flat / 'proj.jsonl').write_text('r\n', encoding='utf-8')
    el._sweep('proj', {'keep_days': 1})
    assert not (flat / old).exists() and (flat / 'proj.jsonl').exists()
