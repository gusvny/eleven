#!/usr/bin/env python3
"""t261008-25 scenario 1: FAILED ticket disposition journey (registry:
t261008-25-failed-ticket-disposition).

User journey (KI-223, ticket raw request): today a FAILED terminal ticket is visible
on the board but unreachable by every collection/cleanup surface — cancel says
"already terminal, no action taken", prune/archive-legacy never see it. After this
ticket the operator must be able to: (1) reach a named, reason-required archive exit
with a FAILED ticket; (2) have the exit refuse malformed input structurally with zero
side effects; (3) have the archived record keep the failure class and stay queryable
(the exit must never launder a failure out of sight); (4) see board display and the
collection faces AGREE about the ticket (no visible-but-untouchable state); (5) filter
the board by terminal class so failures are a visible category.

Face under test (offline, real client.py command layer over stubbed Temporal;
fixture creates its OWN ticket/project — never touches other projects' tickets).

Public-contract pins (implementation-refactor-proof):
  J1 reachability: cmd_ticket_archive_terminal on a FAILED ticket -> ok receipt with
     the failure class kept (terminal_status="FAILED"), reason+who verbatim, and a
     manifest on disk with schema=v1, legacy=false, archived_by, reason verbatim.
  J2 empty reason refused structurally (ok:false) with ZERO side effects (no data
     dir / no manifest appears).
  J3 non-string reason (list / int) refused structurally — never str()-coerced into
     a silent archive; zero side effects.
  J4 missing who refused structurally; zero side effects (a named exit never stays
     op-local).
  J5 status guards: RUNNING refused (never archive a live ticket); COMPLETED refused
     (the exit must not become a side door around the normal archive/prune path);
     CONTINUED_AS_NEW refused (KI-025: never treat live as terminal); zero writes.
  J6 stays queryable: _read_archive_manifest reports state=ok, and ticket-prune
     DRY-RUN with injected entries counts the archived FAILED ticket into its
     would-delete list while the fake deleter is never invoked (dry-run promise).
  J7 idempotency: a second archive call on the same ticket skips honestly and never
     overwrites the real archive (manifest bytes unchanged).
  J8 no silent sweep: the command is single-ticket by shape — it is registered as
     ticket-archive-terminal and a call without a ticket_id is a structured error,
     not a batch over historical tickets.
  J9 board/collection agreement (L3): the seeded board shows the FAILED row (that is
     today's visible face); after archiving, the same ticket is counted by the prune
     dry-run face; ticket-list with a status filter shows the failure as a visible
     category (exactly the FAILED rows, an honest filter receipt); an unknown status
     token is a structured error (no silent empty table); without a filter the board
     row set is unchanged (display-layer regression pin).

Legs on the not-yet-landed faces (archive exit, board filter) are RED before
implement (TDD signal) and must be green at arbitrate/merge.
Run: PY=server/engine/.venv/bin/python; "$PY" -B integration/t261008-25/sc_t261008_25_failed_ticket_disposition.py (cwd=repo root)
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import lib_t26100825 as fx  # noqa: E402
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

TID = 'ki223-fixture-001'
REASON = 'terminal failure retired by ki223 fixture: no recovery path, audit kept'
WHO = 'ki223-integration'
LEGS = []


def check(name, cond, detail=''):
    LEGS.append(bool(cond))
    print('[%s] %s%s' % ('PASS' if cond else 'FAIL', name, ('：' + detail) if detail else ''))


def arch_args(**over):
    a = {'ticket_id': TID, 'who': WHO, 'reason': REASON, 'project': fx.FIXTURE_PROJECT}
    a.update(over)
    return {k: v for k, v in a.items() if v is not None}


def files_under(root):
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())


def main():
    os.environ.pop('SANDBAR_CALLER_PROJECT', None)
    os.environ['SANDBAR_CALLER_PROJECT'] = fx.FIXTURE_PROJECT  # same-project named exit
    fx.install_data_root()
    fx.install_client({TID: fx.FakeHandle('FAILED')})

    cmd = getattr(fx.client_mod, 'cmd_ticket_archive_terminal', None)

    # ---- J8 single-ticket shape / registration ----
    check('J8a COMMANDS registers ticket-archive-terminal (named exit is a real entry)',
          'ticket-archive-terminal' in (getattr(fx.client_mod, 'COMMANDS', None) or {}),
          'commands=%r' % (sorted(k for k in (getattr(fx.client_mod, 'COMMANDS', {}) or {})
                                  if 'archive' in k or 'prune' in k),))
    check('J8b usage text declares ticket-archive-terminal',
          'ticket-archive-terminal' in str(getattr(fx.client_mod, 'USAGE', '') or ''))
    check('J8c call without ticket_id is a structured error, not a batch',
          cmd is not None and not asyncio.run(cmd({'who': WHO, 'reason': REASON})).get('ok', True))

    # ---- J1 reachability + failure class kept ----
    if cmd is None:
        check('J1 archive exit reachable on FAILED ticket', False,
              'cmd_ticket_archive_terminal missing (implement not landed; TDD red)')
    else:
        r = asyncio.run(cmd(arch_args()))
        ok = bool(r.get('ok'))
        check('J1a archive exit reaches a FAILED ticket', ok,
              json.dumps(r, ensure_ascii=False, default=str)[:400])
        mp = fx.manifest_path(TID)
        m = json.loads(mp.read_text(encoding='utf-8')) if mp.is_file() else {}
        check('J1b manifest keeps the failure class verbatim (never rewritten to success)',
              m.get('terminal_status') == 'FAILED' and m.get('schema') == 'v1'
              and m.get('legacy') is False,
              'manifest=%s' % json.dumps(m, ensure_ascii=False, default=str)[:300])
        check('J1c manifest is a NAMED exit record (reason + who verbatim, no laundering)',
              m.get('reason') == REASON and m.get('archived_by') == WHO,
              'reason_match=%s who_match=%s' % (m.get('reason') == REASON,
                                                m.get('archived_by') == WHO))

        # ---- J2/J3/J4 malformed input: structured refusal, zero side effects ----
        root = fx.manifest_path(TID).parent
        before = files_under(root)
        for label, bad in (('J2 empty reason refused structurally, zero side effects', '   '),
                           ('J3a non-string reason (list) refused structurally, zero writes', ['x']),
                           ('J3b non-string reason (int) refused structurally, zero writes', 7)):
            rr = asyncio.run(cmd(arch_args(reason=bad)))
            after = files_under(root)
            check(label, not rr.get('ok', True) and after == before,
                  'ok=%r files_unchanged=%s' % (rr.get('ok'), after == before))
        rr = asyncio.run(cmd(arch_args(who=None)))
        after = files_under(root)
        check('J4 missing who refused structurally, zero writes',
              not rr.get('ok', True) and after == before, 'ok=%r' % rr.get('ok'))

        # ---- J5 status guards (each on its own handle; zero writes) ----
        for label, st in (('J5a RUNNING refused (never archive a live ticket)', 'RUNNING'),
                          ('J5b COMPLETED refused (no side door past the normal path)', 'COMPLETED'),
                          ('J5c CONTINUED_AS_NEW refused (KI-025: not terminal)', 'CONTINUED_AS_NEW')):
            fx.install_client({TID: fx.FakeHandle(st)})
            rr = asyncio.run(cmd(arch_args()))
            after = files_under(root)
            check(label, not rr.get('ok', True) and after == before,
                  'status=%s ok=%r unchanged=%s' % (st, rr.get('ok'), after == before))
        fx.install_client({TID: fx.FakeHandle('FAILED')})

        # ---- J6 stays queryable: manifest ok + prune dry-run counts it ----
        read = fx.client_mod._read_archive_manifest(TID, fx.FIXTURE_PROJECT)
        check('J6a archive stays queryable (manifest state=ok, not hidden)',
              read.get('state') == 'ok', 'state=%r detail=%r' % (read.get('state'), read.get('detail')))
        deleted_calls = []
        pr = asyncio.run(fx.client_mod.cmd_ticket_prune(
            {'project': fx.FIXTURE_PROJECT},
            entries=[{'id': TID, 'sa_project': fx.FIXTURE_PROJECT, 'close_ts': 0}],
            deleter=lambda wf_id: deleted_calls.append(wf_id)))
        pb = pr.get('result') or pr
        check('J6b prune dry-run AGREES: archived FAILED ticket is in the cleanup face',
              pr.get('ok') and pb.get('dry_run') is True and TID in (pb.get('deleted') or []),
              'deleted=%r failed=%r' % (pb.get('deleted'), pb.get('failed')))
        check('J6c dry-run promise: the real deleter is never invoked',
              deleted_calls == [])
        # review_plan condition 2: the audit record survives an ACTUAL prune — the
        # real deleter deletes the Temporal workflow only; the on-disk manifest (the
        # durable named record) must still be readable afterwards (execute=True here
        # with the fake deleter standing in for DeleteWorkflowExecution).
        pr2 = asyncio.run(fx.client_mod.cmd_ticket_prune(
            {'project': fx.FIXTURE_PROJECT, 'execute': True},
            entries=[{'id': TID, 'sa_project': fx.FIXTURE_PROJECT, 'close_ts': 0}],
            deleter=lambda wf_id: deleted_calls.append(wf_id)))
        pb2 = pr2.get('result') or pr2
        read2 = fx.client_mod._read_archive_manifest(TID, fx.FIXTURE_PROJECT)
        check('J6d audit record survives a real prune (workflow deleted, manifest kept)',
              pr2.get('ok') and pb2.get('dry_run') is False
              and deleted_calls == [TID]
              and read2.get('state') == 'ok'
              and json.loads(fx.manifest_path(TID).read_text(encoding='utf-8'))
              .get('terminal_status') == 'FAILED',
              'deleted=%r manifest_state=%r' % (pb2.get('deleted'), read2.get('state')))

        # ---- J7 idempotency: no overwrite of a real archive ----
        bytes_before = fx.manifest_path(TID).read_bytes()
        rr = asyncio.run(cmd(arch_args()))
        check('J7 second call skips honestly and never overwrites the archive',
              fx.manifest_path(TID).read_bytes() == bytes_before,
              'receipt_ok=%r manifest_unchanged=%s' % (rr.get('ok'),
                                                       fx.manifest_path(TID).read_bytes() == bytes_before))

    # ---- J9 board face: visibility, filter, agreement ----
    rows = [fx._Wf('ki223-fixture-001', 'FAILED', fx.FIXTURE_PROJECT),
            fx._Wf('ki223-fixture-002', 'COMPLETED', fx.FIXTURE_PROJECT),
            fx._Wf('ki223-fixture-003', 'RUNNING', fx.FIXTURE_PROJECT)]
    handles = {r.id: fx.FakeHandle(r.status.name) for r in rows}
    fx.install_client(handles, rows)

    lst = asyncio.run(fx.client_mod.cmd_ticket_list({}))
    lb = lst.get('result') or lst
    ids_default = sorted(t.get('id') for t in (lb.get('tickets') or []))
    check('J9a board (no filter) shows the FAILED row — display-layer default unchanged',
          lst.get('ok') and 'ki223-fixture-001' in ids_default
          and len(ids_default) == 3, 'ids=%r' % ids_default)

    lf = asyncio.run(fx.client_mod.cmd_ticket_list({'status': 'FAILED'}))
    lfb = lf.get('result') or lf
    ids_f = sorted(t.get('id') for t in (lfb.get('tickets') or []))
    check('J9b status filter makes failures a visible category (exactly the FAILED rows)',
          lf.get('ok') and ids_f == ['ki223-fixture-001'], 'ids=%r' % ids_f)
    sf = lfb.get('status_filter') or {}
    check('J9c filter receipt is honest (a filtered/empty result is never silent)',
          sf.get('applied') == ['FAILED'] and sf.get('matched') == len(ids_f),
          'status_filter=%r' % (sf,))

    lu = asyncio.run(fx.client_mod.cmd_ticket_list({'status': 'FAILED,TERMINATED'}))
    lub = lu.get('result') or lu
    ids_u = sorted(t.get('id') for t in (lub.get('tickets') or []))
    check('J9d multi-token filter is a union',
          lu.get('ok') and ids_u == ['ki223-fixture-001'], 'ids=%r' % ids_u)

    lk = asyncio.run(fx.client_mod.cmd_ticket_list({'status': 'NOT_A_STATUS'}))
    check('J9e unknown status token is a structured error (no silent empty table)',
          not lk.get('ok', True), 'ok=%r' % lk.get('ok'))

    # J9f agreement face: the archived ticket is BOTH on the board face (above) and in
    # the cleanup face (J6b) — no visible-but-untouchable state. Re-assert on the
    # same fixture state so the two faces are read against one disposition.
    check('J9f board display and collection faces agree about the archived FAILED ticket',
          'ki223-fixture-001' in ids_default and fx.manifest_path(TID).is_file(),
          'board_sees=%s manifest=%s' % ('ki223-fixture-001' in ids_default,
                                         fx.manifest_path(TID).is_file()))

    fx.cleanup()
    if all(LEGS):
        print('ALL GREEN (%d legs)' % len(LEGS))
        return EXIT_PASS
    print('RED legs=%d/%d (pre-implement TDD red expected on unlanded faces)' %
          (LEGS.count(False), len(LEGS)))
    return EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
