# -*- coding: utf-8 -*-
"""t261009-35 UT — _v2_query detail assembly carries paused/paused_phase (engine face, stubbed _poc).

Run: python3 server/plugins/workbench/tests/test_t261009_35_v2_query_pause.py
(exit 0 = pass; also collectable by pytest). No network / no real Temporal.

Background: the engine snapshot carries paused/paused_phase at top level
(TicketPauseMixin product). The list row face (server/engine/client.py, both
branches) already merges the pair; the detail assembly (ticket.py _v2_query)
projected a fixed key list that dropped both, so ticket show carried no pause
state and the console detail button always said Pause. Fix: _v2_query projects
the two keys with the same normalization as the row face — bool(...) /
str(... or ''), absent key = False / '' (never a fabricated 'unknown', never
derived from stage_state).

This UT stubs _poc with fixed receipt shapes (malformed input reproduced by
stub, never against a real external source) and pins the engine-side
normalization contract:
  - normal: paused=True / at_gate passes through;
  - missing keys: False / '' (no 'unknown');
  - non-boolean truthy ('yes'/1): bool-coerced True (review_plan condition 1
    wording: coercion, not verbatim passthrough);
  - non-boolean falsy (''/0): coerced False; paused_phase=None -> '';
  - engine version mismatch -> None (contract unchanged).
Host passthrough shape and derivation-layer assertions live in
t261009-35-detail-paused.mjs (the layers split the work); the real-chain
end-to-end lives in integration/t261009-35/sc_detail_pause_faces.mjs
(engine integration gate tier).
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]          # tests -> workbench -> plugins -> server -> repo root


def _load_ticket_mod():
    spec = importlib.util.spec_from_file_location(
        '_ticket_t261009_35', REPO / 'server' / 'tools' / 'ticket.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_ticket_t261009_35'] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_ticket_mod()
ENGINE_V2 = MOD._shared().ENGINE_V2
_passed = 0
_failed = 0


def _query_with_snapshot(snap, engine=ENGINE_V2):
    """Stub _poc: fixed receipt shape, snapshot supplied per case (malformed
    shapes freely constructible)."""
    receipt = {
        'ok': True,
        'result': {
            'engine': engine,
            'ticket': {'id': 't261009-35', 'status': 'running',
                       'stage': 'implement', 'stage_state': 'running'},
            'pulse': None,
            'snapshot': snap,
        },
    }
    MOD._poc = lambda subcmd, payload, caller=None: receipt
    return MOD._v2_query('t261009-35')


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f'  ok {label}')
    else:
        _failed += 1
        print(f'  FAIL {label}')


def main():
    print('== t261009-35 _v2_query paused/paused_phase (engine face, stubbed _poc)')

    meta, snap = _query_with_snapshot({'paused': True, 'paused_phase': 'at_gate'})
    check(meta['paused'] is True and meta['paused_phase'] == 'at_gate',
          'C1 normal: paused=True / paused_phase=at_gate pass through')
    check(isinstance(meta['paused'], bool) and isinstance(meta['paused_phase'], str),
          'C2 shape: paused is boolean, paused_phase is string')

    meta, _ = _query_with_snapshot({})
    check(meta['paused'] is False and meta['paused_phase'] == '',
          "C3 missing keys -> False / '' (no 'unknown', no stage_state derivation)")

    meta, _ = _query_with_snapshot({'paused': 'yes'})
    check(meta['paused'] is True,
          "C4 non-boolean truthy 'yes' -> bool-coerced True (normalized, not passed through verbatim)")
    meta, _ = _query_with_snapshot({'paused': 1})
    check(meta['paused'] is True, 'C5 non-boolean truthy 1 -> True')
    meta, _ = _query_with_snapshot({'paused': ''})
    check(meta['paused'] is False, "C6 non-boolean falsy '' -> False")
    meta, _ = _query_with_snapshot({'paused': True, 'paused_phase': None})
    check(meta['paused_phase'] == '', 'C7 paused_phase=None -> empty string')
    meta, _ = _query_with_snapshot({'paused': True, 'paused_phase': 7})
    check(meta['paused_phase'] == '7', 'C8 non-string paused_phase -> str normalized (same as the row face)')

    check(_query_with_snapshot({'paused': True}, engine='v1') is None,
          'C9 engine version mismatch -> None (not_found contract unchanged; untouched by this ticket)')

    # Same-source check: the detail-face normalization must stay key-for-key
    # identical to the row face (client.py, both branches) — a source lock on
    # the row face so the two faces cannot drift silently (one source).
    client_src = (REPO / 'server' / 'engine' / 'client.py').read_text(encoding='utf-8')
    check("bool((snap or {}).get(\"paused\"))" in client_src
          and "str((snap or {}).get(\"paused_phase\") or \"\")" in client_src,
          'C10 source lock: the row face (server/engine/client.py) normalization is untouched')
    check('paused' in (REPO / 'server' / 'tools' / 'ticket.py').read_text(encoding='utf-8'),
          'C11 source lock: the detail assembly (ticket.py) now projects paused')

    print(f'\nSUMMARY pass={_passed} fail={_failed}')
    return 0 if _failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
