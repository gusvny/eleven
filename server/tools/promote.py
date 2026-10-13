#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promote.py — the host-signed promotion of a certified prefix (develop-buffer
design goal 11), the ONE operational entry to the wired driver.

The develop-buffer certify chain ends at a line certification; moving that
certified prefix to ``main`` is a separate, human-signed act. The act lives in
``develop_promote.promote_buffer`` (validate everything, fast-forward main,
record). This tool is its host-facing front: ONE JSON argument on argv.

  {op:"promote", project, line, signer, authority?, on_behalf_of?, note?,
   caller_project?}

- ``signer`` is the person signing (design: one human signature per
  promotion). The durable account is the promotion row itself (signer /
  on_behalf_of / authority / at) — the ledger is the audit trail.
- Refusals are named (red or absent certification, not fast-forwardable,
  undeclared line, withdrawal guard) and exit NON-ZERO with ok:false —
  never a silent no-op, never a partial act.
- ``caller_project`` declares the caller's project identity (cross-project
  gate, t260915-12); promotion writes to the target project's ledger, so a
  mismatched identity is refused.

Read-only probe: {op:"promotable", project, line} reports the latest
green certification a promotion would rest on (no ref moves, no record).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402
import shared  # noqa: E402

PROJECT_KEY_RE = shared.PROJECT_KEY_RE


def _bad(msg):
    return {"ok": False, "error": msg}


def _valid_project(v):
    return isinstance(v, str) and PROJECT_KEY_RE.match(v)


def run(a):
    if not isinstance(a, dict):
        return _bad("args must be a JSON object")
    op = str(a.get("op") or "").strip()
    project = str(a.get("project") or "").strip()
    line = str(a.get("line") or "").strip() or "develop-buffer"
    caller = str(a.get("caller_project") or "").strip()
    if not _valid_project(project):
        return _bad("malformed project key: %r" % (project,))
    if caller and caller != project:
        return _bad("cross_project_refused: caller %r != target %r"
                    % (caller, project))
    try:
        rows, bad = dc.read_rows(dc.ledger_path(project))
    except Exception as e:  # noqa: BLE001
        return _bad("delivery ledger unreadable: %s" % str(e)[:200])
    if bad:
        return _bad("delivery ledger has %d malformed line(s)" % len(bad))
    if op == "promotable":
        cert = dp._latest_green_cert(rows, line, project)
        return {"ok": True, "op": op, "line": line,
                "green_certification": cert["id"] if cert else None,
                "certified_revisions": cert["repos"] if cert else None}
    if op != "promote":
        return _bad("unknown op %r (promote|promotable)" % (op,))
    signer = str(a.get("signer") or "").strip()
    if not signer:
        return _bad("promotion_missing_signer (the act is human-signed)")
    try:
        row = dp.promote_buffer(
            project, line, signer,
            authority=a.get("authority") or None,
            on_behalf_of=a.get("on_behalf_of") or None,
            note=a.get("note") or None)
    except dp.PromotionRefused as e:
        return _bad("promotion refused: %s" % e)
    except dp.PromoteError as e:
        return _bad("promotion failed: %s" % e)
    return {"ok": True, "op": op, "promotion": row["id"],
            "certification": row["certification"], "line": row["line"],
            "tickets": row["tickets"], "main_after": row["main_after"],
            "worktree_sync_notes": row.get("worktree_sync_notes", [])}


def main(argv):
    if len(argv) != 2:
        print(json.dumps(_bad("usage: promote.py '{json}'"), ensure_ascii=False))
        return 2
    try:
        args = json.loads(argv[1])
    except ValueError as e:
        print(json.dumps(_bad("malformed JSON arg: %s" % e), ensure_ascii=False))
        return 2
    out = run(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
