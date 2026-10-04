# -*- coding: utf-8 -*-
"""t261004-11 执行器动作项目账（executor_actions）——单测。

覆盖（方案 gen1 验收杆逐条）：
- 行形状：allowed 行恰含 {v,at,op,ticket,grant,grant_source,session,channel,decision,idem}
  （reason 键省略，C4）；refused 行恰为上述集合 + reason（非空，C4）；
- 行 < 4096 字节；reason 超限截断不崩、单条良行出；
- refused 记录在案：元权限反锁 / 面外 op / 声明缺席（grant="" + reason 带 why）；
- idem：进程内命中去重、冷进程扫盘去重、跨时间桶=新行（桶界伪影已声明）；
- append 失败：闸结局不变、stderr 点名、WRITE_FAILURES 计数、gaps 行在场、
  gaps 再失败仍不 raise；
- 空项目键/畸形 decision=拒收不落盘（不产畸形文件，announce 在案）；
- 轮转：max_mb 阈值 rename；清扫：keep_days 只删老归档（base_path 参数面，
  event_ledger 缺省行为回归钉）；enabled=False 仍落账（C2 无条件记账锁）；
- 闸接线（C3）：enforced 放行/拒收各一行；豁免放行零行零文件行为；
  三处闸漏斗的行 channel ∈ arg/env/cwd；
- 零回归：_executor_grant_gate 拒收回执与记账 sink 关/开逐字节一致。

全程零 Temporal/零网络/零 git；projects 根/账本目录经 env 注入临时目录，
绝不触 3099/7233、绝不写真 ~/.sandbar。
"""
import json
import os
import time
from pathlib import Path

import pytest

import client as cl  # noqa: E402
import event_ledger as el  # noqa: E402
import executor_actions as ea  # noqa: E402
import executor_grants as eg  # noqa: E402

NOW_MS = 1_700_000_000_000
ALLOWED_KEYS = {'v', 'at', 'op', 'ticket', 'grant', 'grant_source',
                'session', 'channel', 'decision', 'idem'}
REFUSED_KEYS = ALLOWED_KEYS | {'reason'}


@pytest.fixture()
def iso(monkeypatch, tmp_path):
    """隔离环境：projects 根 + 平铺账本缝 + 声明根都指 tmp；加速集每例清零。"""
    root = tmp_path / 'projects'
    flat = tmp_path / 'flat-ledger'
    root.mkdir()
    flat.mkdir()
    monkeypatch.setenv('SANDBAR_PROJECTS_DIR', str(root))
    monkeypatch.setenv('SANDBAR_EXECUTOR_ACTIONS_DIR', str(flat))
    monkeypatch.delenv(eg.CALLER_SESSION_ENVS[0], raising=False)
    monkeypatch.delenv(eg.CALLER_SESSION_ENVS[1], raising=False)
    ea.reset_for_test()
    el.reset_config_for_test()
    yield {'root': root, 'flat': flat, 'decl': root / 'p1'}
    ea.reset_for_test()
    el.reset_config_for_test()


def _rows(iso, key='p1'):
    f = iso['flat'] / ('%s.jsonl' % key)
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]


def _declare(iso, doc):
    d = iso['decl']
    d.mkdir(parents=True, exist_ok=True)
    full = {'version': 1}
    full.update(doc)
    (d / eg.DECL_FILE).write_text(json.dumps(full), encoding='utf-8')


# ---------- 行形状（C4） ----------

def test_allowed_row_exact_key_set(iso):
    r = ea.record_executor_action('p1', 'ticket.sign', ticket='T-1', grant='sign',
                                  grant_source='grants.sign @ /x/executor-grants.json',
                                  session='s-1', channel='cwd', decision='allowed',
                                  now_ms=NOW_MS)
    assert r.get('appended') is True
    rows = _rows(iso)
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == ALLOWED_KEYS, 'allowed row omits the reason key (C4)'
    assert row['decision'] == 'allowed' and row['op'] == 'ticket.sign'
    assert row['ticket'] == 'T-1' and row['grant'] == 'sign'
    assert row['at'] == NOW_MS and row['v'] == ea.SCHEMA_V == 1


def test_refused_row_exact_key_set_and_reason(iso):
    r = ea.record_executor_action('p1', 'rerun', decision='refused',
                                  reason='not granted', session='s-1', channel='arg',
                                  now_ms=NOW_MS)
    assert r.get('appended') is True
    row = _rows(iso)[0]
    assert set(row.keys()) == REFUSED_KEYS
    assert row['reason'] == 'not granted' and row['grant'] == ''


def test_line_under_4kb_and_reason_truncation(iso):
    r = ea.record_executor_action('p1', 'sign', decision='refused',
                                  reason='x' * 100_000, now_ms=NOW_MS)
    assert r.get('appended') is True
    f = iso['flat'] / 'p1.jsonl'
    raw = f.read_bytes()
    assert len(raw.splitlines()) == 1
    assert len(raw) < ea.LINE_LIMIT
    row = json.loads(raw)
    assert row['reason'].endswith(ea.REASON_TRUNC_MARK)


# ---------- refused 的三种来源（元权限反锁/面外 op/声明缺席） ----------

def test_meta_op_refusal_recorded_with_empty_grant(iso):
    v = eg.judge_core('cwd', eg.META_OP, 'p1', lambda k: {'ok': False, 'kind': 'absent'},
                      NOW_MS, audit_sink=None)
    ea.record_from_gate(eg.META_OP, 'p1', 'T-9', v, 'cwd', now_ms=NOW_MS, session='s')
    row = _rows(iso)[0]
    assert row['decision'] == 'refused' and row['grant'] == ''
    assert '反锁' in row['reason'] and row['ticket'] == 'T-9'


def test_unmapped_op_refusal_recorded(iso):
    v = eg.judge_core('cwd', 'no-such-op', 'p1', lambda k: {'ok': True, 'decl': {},
                                                            'grants': {}},
                      NOW_MS, audit_sink=None)
    ea.record_from_gate('no-such-op', 'p1', '', v, 'cwd', now_ms=NOW_MS, session='')
    row = _rows(iso)[0]
    assert row['decision'] == 'refused' and row['grant'] == ''
    assert row['op'] == 'no-such-op'


def test_not_granted_refusal_carries_grant_source(iso):
    _declare(iso, {'grants': {'sign': False}})
    load = eg.load_declaration('p1')
    v = eg.judge_core('cwd', 'sign', 'p1', lambda k: load, NOW_MS, audit_sink=None)
    ea.record_from_gate('sign', 'p1', 'T-1', v, 'cwd', now_ms=NOW_MS, session='s-1')
    row = _rows(iso)[0]
    assert row['decision'] == 'refused' and row['grant'] == ''
    assert 'executor-grants.json' in row['reason']


# ---------- idem ----------

def test_idem_dedup_inprocess_and_cold_and_bucket(iso):
    kw = dict(project='p1', op='sign', ticket='T-1', session='s-1', channel='cwd',
              decision='refused', reason='not granted')
    assert ea.record_executor_action(now_ms=NOW_MS, **kw)['appended'] is True
    assert ea.record_executor_action(now_ms=NOW_MS + 1000, **kw).get('deduped') is True
    assert len(_rows(iso)) == 1, 'same logical attempt: one line only'
    # 冷进程：加速集清零（重试来自新 client 进程），扫盘兜底仍认得
    ea.reset_for_test()
    assert ea.record_executor_action(now_ms=NOW_MS + 2000, **kw).get('deduped') is True
    assert len(_rows(iso)) == 1
    # 真实的再次执行（数小时后=新桶）=新行
    assert ea.record_executor_action(now_ms=NOW_MS + ea.IDEM_BUCKET_MS * 2,
                                     **kw)['appended'] is True
    assert len(_rows(iso)) == 2


# ---------- 失败面（fail-open 且 LOUD） ----------

def test_append_failure_loud_and_gate_outcome_unchanged(iso, monkeypatch, capsys):
    ro = iso['flat'] / ('p1.jsonl')
    ro.write_text('')  # 文件在场
    ro.chmod(0o444)
    ea.reset_for_test()
    try:
        r = ea.record_executor_action('p1', 'sign', decision='allowed',
                                      grant='sign', now_ms=NOW_MS)
        assert r.get('failed') is True and r.get('appended') is False
        assert ea.WRITE_FAILURES >= 1, 'failure is counted (never silent)'
        err = capsys.readouterr().err
        assert 'executor-actions' in err and 'p1' in err, 'stderr line names the project'
        gaps = iso['flat'] / ea.GAPS_BASENAME
        assert gaps.exists() and json.loads(gaps.read_text().splitlines()[-1])['gap'] is True
    finally:
        ro.chmod(0o644)


def test_gap_write_failure_still_no_raise(iso, monkeypatch):
    monkeypatch.setattr(ea, '_write_gap_record',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
    monkeypatch.setattr(ea, 'actions_path',
                        lambda p, d=None: Path('/nonexistent-ro/x/p1.jsonl'))
    r = ea.record_executor_action('p1', 'sign', decision='allowed', now_ms=NOW_MS)
    assert r.get('failed') is True, 'double failure still never raises'


# ---------- 拒收面（空键/畸形字段） ----------

def test_empty_project_key_rejected_no_file(iso, capsys):
    r = ea.record_executor_action('', 'sign', decision='allowed', now_ms=NOW_MS)
    assert r.get('failed') is True and r.get('appended') is False
    assert list(iso['flat'].iterdir()) == [] or \
        all(not p.name.endswith('.jsonl') or p.name == ea.GAPS_BASENAME
            for p in iso['flat'].iterdir()), 'no malformed ledger file created'
    assert 'p1' not in (iso['flat'] / '..').resolve().name  # trivial keep-alive
    assert capsys.readouterr().err != ''


def test_bad_decision_rejected(iso, capsys):
    r = ea.record_executor_action('p1', 'sign', decision='maybe', now_ms=NOW_MS)
    assert r.get('failed') is True
    assert _rows(iso) == [], 'unknown decision value is never written'
    assert capsys.readouterr().err != ''


def test_refused_without_reason_gets_placeholder(iso, capsys):
    r = ea.record_executor_action('p1', 'sign', decision='refused', reason='  ',
                                  now_ms=NOW_MS)
    assert r.get('appended') is True
    row = _rows(iso)[0]
    assert row['reason'] != '' and set(row.keys()) == REFUSED_KEYS
    assert capsys.readouterr().err != '', 'placeholder is announced, not silent'


# ---------- 轮转/清扫/启用闸（C2） ----------

def test_rotate_fires_at_max_mb(iso, monkeypatch):
    # max_mb 走 int 口径（event_ledger 同源），用 1MB 阈值 + 预置 1.5MB 活动文件
    big = iso['flat'] / 'p1.jsonl'
    big.write_bytes(b'x' * (1536 * 1024))
    ea.reset_for_test()
    monkeypatch.setattr(ea, '_retention_cfg',
                        lambda: {'enabled': False, 'keep_days': 14, 'max_mb': 1})
    ea.record_executor_action('p1', 'sign', decision='allowed', now_ms=NOW_MS)
    names = [p.name for p in iso['flat'].iterdir()]
    assert any(n.startswith('p1.jsonl.') for n in names), \
        'archive rename happened (event ledger rotation policy, no second mechanism)'


def test_sweep_deletes_only_old_archives_via_base_path(iso):
    d = iso['flat']
    old = d / 'p1.jsonl.20200101-000000-abc123'
    new = d / 'p1.jsonl.29991231-000000-def456'
    old.write_text('{}\n')
    new.write_text('{}\n')
    el._sweep('p1', {'keep_days': 14}, base_path=d / 'p1.jsonl')
    assert not old.exists() and new.exists(), 'base_path sweep removes only old archives'


def test_sweep_default_behaviour_unchanged(iso, tmp_path):
    # event_ledger 缺省路径回归钉：base_path 缺省时仍从 ledger_path 推导
    dd = tmp_path / 'ledger'
    dd.mkdir()
    old = dd / 'events.jsonl.20200101-000000-abc123'
    old.write_text('{}\n')
    monkey_dir = dd
    el._sweep('sweep-default-probe', {'keep_days': 14}, ledger_dir=monkey_dir.parent)
    # 平铺缝形状 <dir>/<project>.jsonl → 归档 events.jsonl.* 不属该名，不删（形状外跳过）
    assert old.exists(), 'default sweep still honours the ledger_path-derived name'


def test_recording_unconditional_when_event_ledger_disabled(iso, monkeypatch):
    _declare(iso, {})  # p1 has a project dir; no event_ledger block anywhere
    monkeypatch.setattr(ea, '_retention_cfg',
                        lambda: {'enabled': False, 'keep_days': 14, 'max_mb': 512})
    r = ea.record_executor_action('p1', 'sign', decision='allowed', grant='sign',
                                  now_ms=NOW_MS)
    assert r.get('appended') is True, 'enabled=False does NOT gate recording (C2)'
    assert len(_rows(iso)) == 1


# ---------- 闸接线（C3 + 零回归） ----------

def test_gate_records_enforced_and_refused_but_not_exempt(iso, monkeypatch):
    _declare(iso, {'grants': {'sign': True}})
    monkeypatch.setattr(ea, '_retention_cfg',
                        lambda: {'enabled': False, 'keep_days': 14, 'max_mb': 512})
    ident = {'src': 'cwd', 'channel_src': 'cwd'}

    # 豁免通道（none）：零行零文件行为
    g0 = cl._executor_grant_gate({'src': 'none'}, 'sign', 'p1', ticket='T-1')
    assert g0['err'] is None and _rows(iso) == [], 'exempt pass writes no row (C3)'

    # enforced 放行：一行 allowed，channel=cwd（op 用授予面原词 'sign'——
    # 引擎写 op 走 op_label，'ticket.sign' 不在固定授予面，会 fail-closed 拒收）
    g1 = cl._executor_grant_gate(ident, 'sign', 'p1', ticket='T-1')
    assert g1['err'] is None
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'allowed'
    assert rows[0]['channel'] in ('arg', 'env', 'cwd')

    # 拒收：再一行 refused（rerun 是另一 op=另一 idem，正常成行）
    _declare(iso, {'grants': {'sign': False}})
    ea.reset_for_test()
    g2 = cl._executor_grant_gate(ident, 'rerun', 'p1', ticket='T-1')
    assert g2['err'] is not None
    rows = _rows(iso)
    assert len(rows) == 2 and rows[-1]['decision'] == 'refused'
    assert rows[-1]['reason'] != '' and rows[-1]['grant'] == ''


def test_gate_receipt_identical_with_recording_on_off(iso, monkeypatch, capsys):
    _declare(iso, {'grants': {}})
    ident = {'src': 'cwd', 'channel_src': 'cwd'}
    receipt_off = cl._executor_grant_gate(ident, 'sign', 'p1', ticket='T-1')
    rows = _rows(iso)
    assert len(rows) == 1, 'recording happened'
    # 记账关闭（模拟 sink 失败面）=闸回执不变（fail-open：记账不动写结局）
    def _boom(*a, **k):
        raise RuntimeError('sink exploded')
    monkeypatch.setattr(ea, 'record_from_gate', _boom)
    receipt_on = cl._executor_grant_gate(ident, 'sign', 'p1', ticket='T-1')
    assert receipt_on == receipt_off, 'gate receipt byte-identical regardless of recording'
    ea.reset_for_test()  # restore the module attr cleanup order (monkeypatch reverts)
    assert capsys.readouterr().err != '', 'a raised sink is announced on stderr, not silent'


def test_gate_row_carries_caller_session_from_env(iso, monkeypatch):
    _declare(iso, {'grants': {'sign': True}})
    monkeypatch.setenv(eg.CALLER_SESSION_ENVS[0], 'sess-from-env')
    monkeypatch.setattr(ea, '_retention_cfg',
                        lambda: {'enabled': False, 'keep_days': 14, 'max_mb': 512})
    g = cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'}, 'sign', 'p1',
                                ticket='T-1')
    assert g['err'] is None
    row = _rows(iso)[0]
    assert row['session'] == 'sess-from-env', \
        'the acting session is read from the declaration-channel read (scenario A1 face)'


def test_record_from_gate_allowed_row_fields(iso):
    load = {'ok': True, 'file': '/x/executor-grants.json', 'decl': {},
            'grants': {'sign': True}, 'night_tier': None, 'executor_sessions': []}
    v = eg.judge_core('cwd', 'sign', 'p1', lambda k: load, NOW_MS, audit_sink=None)
    ea.record_from_gate('ticket.sign', 'p1', 'T-2', v, 'cwd', now_ms=NOW_MS,
                        session='s-9')
    row = _rows(iso)[0]
    assert row['decision'] == 'allowed' and row['grant'] == 'sign'
    assert row['grant_source'].startswith('grants.sign @ ')
    assert row['session'] == 's-9'


# ---------- t261004-31 declared-executor-session seam: recording boundary (channel=declared-session) ----------

def test_seam_channel_enforced_allowance_writes_one_row(iso):
    load = {'ok': True, 'file': '/x/executor-grants.json', 'decl': {},
            'grants': {'sign': True}, 'night_tier': None, 'executor_sessions': ['s-1']}
    v = eg.judge_core('declared-session', 'sign', 'p1', lambda k: load, NOW_MS,
                      audit_sink=None, declared_sessions=('s-1',), caller_session='s-1')
    assert v['allowed'] is True and v['enforced'] is True
    ea.record_from_gate('sign', 'p1', 'T-1', v, 'declared-session',
                        now_ms=NOW_MS, session='s-1')
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'allowed'
    assert rows[0]['channel'] == 'declared-session' and rows[0]['grant'] == 'sign'


def test_seam_channel_refusal_writes_one_row(iso):
    load = {'ok': True, 'file': '/x/executor-grants.json', 'decl': {},
            'grants': {}, 'night_tier': None, 'executor_sessions': ['s-1']}
    v = eg.judge_core('declared-session', 'sign', 'p1', lambda k: load, NOW_MS,
                      audit_sink=None, declared_sessions=('s-1',), caller_session='s-1')
    assert v['allowed'] is False
    ea.record_from_gate('sign', 'p1', 'T-1', v, 'declared-session',
                        now_ms=NOW_MS, session='s-1')
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'refused'
    assert rows[0]['channel'] == 'declared-session'


def test_seam_exempt_pass_still_records_nothing(iso):
    # Exempt channel (src=none, seam not open): no row — the recording boundary of
    # this ledger is unchanged (gen1 C3 ruling).
    v = eg.judge_core('none', 'sign', 'p1', lambda k: {'ok': True, 'grants': {}},
                      NOW_MS, audit_sink=None)
    assert v['allowed'] is True and v['enforced'] is False
    ea.record_from_gate('sign', 'p1', 'T-1', v, 'none', now_ms=NOW_MS, session='s-1')
    assert _rows(iso) == []
