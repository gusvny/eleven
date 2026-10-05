# -*- coding: utf-8 -*-
"""t261005-12 gate recording moved to the ENGINE process + the reader-visible
failure face — unit tests.

Coverage (the four ticket requirements + the three review-plan conditions):
- routing: the gate verdict rows (enforced pass / refusal / epic scope) are
  submitted through client._submit_engine_delivery (face=actions-record) — the
  captured payload is asserted (face/body/identity block); the caller process
  no longer writes the ledger directly (A2 face: a broken submission seam =
  zero rows);
- identity discipline: the payload identity block carries project = the
  gate-resolved key, session = the env session (the caller_session_id source),
  channel = the gate channel derivation — never a caller-asserted key;
- row boundary (t261004-11 C3 unchanged): an exempt pass = zero payloads and
  zero rows; an enforced pass and every refusal land one row each (via the
  production perform_delivery dispatch; record_from_gate stays the single
  enforcement point);
- failure visibility (requirement 2): all four failure shapes (submission
  refused / submission raised / malformed receipt / engine-side append failed)
  are named in record_note (exact check named, never a fabricated success);
  the gate verdict never moves (fail-open);
- last-failure marker face: an engine-side append failure writes
  executor-actions.last-failure.json under <projects_root>/<key>/ (fields
  at/why/error/op/ticket; malformed input never crashes; a second failure
  keeps the LAST failure only); the panel read face is pinned by panel tests.
- the ticket-start face (the third gate-funnel call site, review condition 1):
  the epic scope verdict routes through the engine submission and lands its row.

Zero Temporal / zero network / zero git throughout; the projects root and the
ledger directory are injected tmp dirs via env.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import pytest

import client as cl  # noqa: E402
import executor_actions as ea  # noqa: E402
import executor_delivery as ed  # noqa: E402
import executor_grants as eg  # noqa: E402

NOW_MS = 1_700_000_000_000


@pytest.fixture()
def iso(monkeypatch, tmp_path):
    """Isolation: projects root + flat ledger seam + declaration root all point at
    tmp; the idem accelerator set is cleared per test."""
    root = tmp_path / 'projects'
    flat = tmp_path / 'flat-ledger'
    root.mkdir()
    flat.mkdir()
    monkeypatch.setenv('SANDBAR_PROJECTS_DIR', str(root))
    monkeypatch.setenv('SANDBAR_EXECUTOR_ACTIONS_DIR', str(flat))
    monkeypatch.delenv(eg.CALLER_SESSION_ENVS[0], raising=False)
    monkeypatch.delenv(eg.CALLER_SESSION_ENVS[1], raising=False)
    ea.reset_for_test()
    yield {'root': root, 'flat': flat, 'decl': root / 'p1'}
    ea.reset_for_test()


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


# ---------- shared stand-in: an in-process engine (production perform_delivery dispatch, rows via the real record_from_gate) ----------

def install_fake_engine(monkeypatch, mode='perform'):
    """Replace client._submit_engine_delivery with an in-process engine stand-in.

    mode='perform': run the production executor_delivery.perform_delivery
    dispatch (the default handler lands rows via the real record_from_gate) —
    the gate -> delivery -> ledger row semantics are fully real except the
    Temporal transport. mode='refuse'/'raise'/'bad-receipt'/'append-fail':
    inject the matching failure shape (review conditions 2/3 test rods). Returns
    the capture list (payload assertions).
    """
    calls = []

    async def _submit(identity, face, body):
        calls.append({'identity': dict(identity), 'face': face, 'body': body})
        if mode == 'refuse':
            return {'ok': False, 'error': 'engine-unreachable: connection refused (injected)'}
        if mode == 'raise':
            raise RuntimeError('engine delivery unavailable (injected)')
        if mode == 'bad-receipt':
            return {'ok': True, 'result': 'not-a-dict'}
        if mode == 'append-fail':
            return {'ok': True, 'result': {'appended': False, 'failed': True,
                                           'error': 'OSError: injected unwritable ledger'}}
        payload = ed.delivery_payload(face, identity['project'], identity, body)
        receipt = ed.perform_delivery(payload, now_ms=int(time.time() * 1000))
        if receipt.get('ok'):
            return {'ok': True, 'result': receipt}
        return {'ok': False, 'error': receipt.get('error') or 'delivery refused'}

    monkeypatch.setattr(cl, '_submit_engine_delivery', _submit)
    return calls


@pytest.fixture(autouse=True)
def _engine_submit_stub(monkeypatch):
    """Per-test default stand-in (individual tests reinstall to override)."""
    install_fake_engine(monkeypatch)


# ---------- routing + identity discipline (requirements 1/3) ----------

def test_gate_pass_submits_actions_record_payload(iso, monkeypatch):
    _declare(iso, {'grants': {'sign': True}, 'executor_sessions': ['sess-gate-1']})
    monkeypatch.setenv('DSH_SESSION_ID', 'sess-gate-1')
    calls = install_fake_engine(monkeypatch)
    g = asyncio.run(cl._executor_grant_gate({'src': 'arg', 'channel_src': 'arg'},
                                            'sign', 'p1', ticket='T-1'))
    assert g['err'] is None and 'record_note' not in g
    assert len(calls) == 1
    c = calls[0]
    assert c['face'] == 'actions-record'
    assert c['body']['op'] == 'sign' and c['body']['ticket'] == 'T-1'
    assert c['body']['verdict'].get('allowed') is True
    assert c['body']['channel'] == 'arg'
    # identity discipline: the identity block = gate-resolved values; never a
    # caller-asserted key
    assert c['identity']['project'] == 'p1'
    assert c['identity']['session'] == 'sess-gate-1'
    assert c['identity']['channel'] == 'arg' and c['identity']['identity_src'] == 'arg'
    assert 'session' not in c['body']   # the body carries no session — the session rides the identity block only
    # the row lands through the production dispatch
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'allowed'
    assert rows[0]['session'] == 'sess-gate-1' and rows[0]['channel'] == 'arg'


def test_gate_refusal_recorded_via_engine(iso):
    _declare(iso, {'grants': {'sign': False}})
    g = asyncio.run(cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'},
                                            'rerun', 'p1', ticket='T-2'))
    assert g['err'] is not None and 'record_note' not in g
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'refused'
    assert rows[0]['reason'] != '' and rows[0]['grant'] == ''


def test_exempt_pass_zero_payload_zero_row(iso, monkeypatch):
    _declare(iso, {'grants': {'sign': True}})
    calls = install_fake_engine(monkeypatch)
    g = asyncio.run(cl._executor_grant_gate({'src': 'none'}, 'sign', 'p1', ticket='T-1'))
    assert g['err'] is None and g['keys'] == {}
    assert calls == [] and _rows(iso) == [], 'exempt pass: no delivery run, no row (C3)'


def test_ticket_start_epic_scope_routes_through_engine(iso, monkeypatch):
    """Review condition 1: the ticket-start face (the third gate-funnel call
    site) routes through the engine submission too."""
    _declare(iso, {'grants': {'open-ticket': True},
                   'open_ticket_epics': ['epic-x'], 'open_ticket_cap': 3,
                   'executor_sessions': ['sess-ts-1']})
    monkeypatch.setenv('DSH_SESSION_ID', 'sess-ts-1')
    # the epic prose file the existence check reads (projects-root fallback anchor)
    epics = iso['root'] / 'p1' / 'notes' / 'epics'
    epics.mkdir(parents=True, exist_ok=True)
    (epics / 'epic-x.md').write_text('# epic-x\n', encoding='utf-8')
    calls = install_fake_engine(monkeypatch)
    g = asyncio.run(cl._executor_grant_gate(
        {'src': 'arg', 'channel_src': 'arg'}, 'ticket-start', 'p1', ticket='T-9',
        epic='epic-x', write_set=['notes/foo.md'], open_count=0))
    assert g['err'] is None, str(g['err'])[:200]
    assert g['keys'].get('executor_grant_op') == 'open-ticket'
    assert len(calls) == 1 and calls[0]['body']['op'] == 'ticket-start'
    assert calls[0]['body']['verdict'].get('allowed') is True
    rows = _rows(iso)
    assert len(rows) == 1 and rows[0]['decision'] == 'allowed'
    assert rows[0]['session'] == 'sess-ts-1'


# ---------- failure visibility (requirement 2 + review condition 3) ----------

def test_submission_refusal_named_verdict_unchanged(iso, monkeypatch, capsys):
    _declare(iso, {'grants': {'sign': True}})
    install_fake_engine(monkeypatch, mode='refuse')
    g = asyncio.run(cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'},
                                            'sign', 'p1', ticket='T-1'))
    assert g['err'] is None, 'fail-open: the verdict never moves'
    assert g['keys'].get('executor_grant_op') == 'sign'
    note = g.get('record_note') or ''
    assert 'unreachable' in note and 'engine-unreachable: connection refused (injected)' in note, \
        'the note names the exact failed check verbatim (never a fabricated success)'
    assert _rows(iso) == [], 'caller writes zero rows when the engine is unreachable'
    assert capsys.readouterr().err != '', 'the failure is announced on stderr'
    assert ea.WRITE_FAILURES >= 1


def test_submission_raise_named(iso, monkeypatch, capsys):
    _declare(iso, {'grants': {'sign': True}})
    install_fake_engine(monkeypatch, mode='raise')
    g = asyncio.run(cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'},
                                            'sign', 'p1', ticket='T-1'))
    assert g['err'] is None
    note = g.get('record_note') or ''
    assert 'delivery-submission' in note and 'unavailable' in note
    assert _rows(iso) == []
    assert capsys.readouterr().err != ''


def test_malformed_receipt_named(iso, monkeypatch, capsys):
    """Review condition 2: a receipt present but of the wrong shape = named
    refusal — never a fabricated success, never a crash."""
    _declare(iso, {'grants': {'sign': True}})
    install_fake_engine(monkeypatch, mode='bad-receipt')
    g = asyncio.run(cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'},
                                            'sign', 'p1', ticket='T-1'))
    assert g['err'] is None and g['keys'].get('executor_grant_op') == 'sign'
    note = g.get('record_note') or ''
    assert 'delivery-receipt-shape' in note and 'str' in note
    assert capsys.readouterr().err != ''


def test_engine_side_append_failure_named(iso, monkeypatch):
    install_fake_engine(monkeypatch, mode='append-fail')
    _declare(iso, {'grants': {'sign': True}})
    g = asyncio.run(cl._executor_grant_gate({'src': 'cwd', 'channel_src': 'cwd'},
                                            'sign', 'p1', ticket='T-1'))
    assert g['err'] is None
    note = g.get('record_note') or ''
    assert 'executor-actions append' in note and 'OSError' in note


# ---------- last-failure marker face (engine-side real IO) ----------

def test_last_failure_marker_written_and_last_only(iso, monkeypatch, capsys):
    marker = iso['root'] / 'p1' / 'executor-actions.last-failure.json'
    ledger_dir = iso['flat']
    os.chmod(ledger_dir, 0o500)
    try:
        r = ea.record_executor_action('p1', 'sign', ticket='T-1', session='s',
                                      decision='allowed', now_ms=NOW_MS)
        assert r.get('failed') is True and r.get('appended') is False
        assert marker.exists(), 'the marker is the reader-visible face (req 2)'
        m = json.loads(marker.read_text(encoding='utf-8'))
        assert all(k in m for k in ('at', 'why', 'error', 'op', 'ticket', 'project'))
        assert m['ticket'] == 'T-1' and m['project'] == 'p1'
        # a second failure keeps the last one only (last-only, not an unbounded log)
        ea.record_executor_action('p1', 'sign', ticket='T-2', session='s',
                                  decision='allowed', now_ms=NOW_MS + 1)
        m2 = json.loads(marker.read_text(encoding='utf-8'))
        assert m2['ticket'] == 'T-2' and 'T-1' != m2['ticket']
        assert capsys.readouterr().err != ''
    finally:
        os.chmod(ledger_dir, 0o700)


def test_last_failure_marker_paths_match_panel_shape(iso):
    """Cross-language path drift lock: the engine last_failure_path mirrors the
    panel executorActionsFailureFile shape (flat seam = same dir; default =
    project root). The panel side is pinned by panel tests; this pins the
    engine side."""
    p = ea.last_failure_path('p1')
    assert p.name == 'executor-actions.last-failure.json'
    assert p == iso['root'] / 'p1' / 'executor-actions.last-failure.json'


def test_last_failure_marker_write_failure_never_raises(iso, monkeypatch, capsys):
    # the project root is unwritable too: the marker face is best-effort — never
    # raises, never moves the write verdict
    os.chmod(iso['root'], 0o500)
    try:
        ea.record_last_failure('p1', 'append failed at /x', 'OSError: boom',
                               op='sign', ticket='T-1')
        assert not (iso['root'] / 'p1' / 'executor-actions.last-failure.json').exists()
        assert capsys.readouterr().err != '', 'marker write failure is announced'
    finally:
        os.chmod(iso['root'], 0o700)


# ---------- structural rods ----------

def test_gate_is_async_and_submission_seam_exists():
    """The routing seam is present (scenario A1 rod): client._submit_engine_delivery
    exists and the gate is async (engine recording = one async funnel)."""
    assert callable(cl._submit_engine_delivery)
    assert callable(cl._record_gate_engine_side)
    import inspect
    assert inspect.iscoroutinefunction(cl._executor_grant_gate)
    assert inspect.iscoroutinefunction(cl._record_gate_engine_side)
