#!/usr/bin/env python3
"""Close the evidence-answerable request heads (host ruling 261026, option a).

What it does, in two steps, with no guessing:

1. For every head listed in integration/requests-close-261026.md, attach the
   engine's own resolution condition `{"kind": "ticket_closed", "ticket": "<id>"}`
   through `request_thread.condition_op` (append-only, attributed to the caller
   session).
2. Run `request_sweep.sweep_project`, which closes each head only when the
   delivery-ledger / ticket-status evidence actually holds, and writes ONE
   `resolved` row whose `evidence` is the observed row.

WHO MAY RUN IT. The engine's identity gate decides, not this script: the caller
session id must be named in the project's `executor-grants.json`
(`executor_sessions`) or registered in `sessions.json` (request_thread
classify_source). An unnamed or borrowed session is refused by name, which is
the correct behaviour - do not work around it by editing either file.

    SANDBAR_EXECUTOR_SESSION=session-... python3 integration/close_requests_by_evidence.py --dry-run
    SANDBAR_EXECUTOR_SESSION=session-... python3 integration/close_requests_by_evidence.py --apply

`--dry-run` prints one line per head: the condition it would attach and whether
the evidence already holds. `--apply` attaches and sweeps.

Every refusal is printed verbatim; the script exits non-zero if any head was
refused, so a partial run is visible rather than silent.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "server", "engine")
LIST = os.path.join(HERE, "requests-close-261026.md")
PROJECT = "sandbar"

sys.path.insert(0, ENGINE)


def heads_from_list(path):
    """(head id, first cited ticket) for every table row of the review list."""
    out = []
    row = re.compile(r"^\|\s*(\d+)\s*\|\s*`(req-[0-9]+-[0-9]+)`\s*\|\s*([a-z-]+)\s*\|\s*([^|]+)\|")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = row.match(line.strip())
            if not m:
                continue
            _n, head, _kind, tickets = m.groups()
            first = tickets.split(",")[0].strip()
            if re.match(r"^t\d{6}-\d{2}$", first):
                out.append((head, first))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="attach and sweep (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="print what would happen")
    args = ap.parse_args()
    apply = bool(args.apply) and not args.dry_run

    import request_sweep
    import request_thread

    pairs = heads_from_list(LIST)
    if not pairs:
        print("no heads parsed from %s - refusing to continue" % LIST)
        return 2
    print("%d heads in the review list" % len(pairs))

    env = dict(os.environ)
    env.setdefault("SANDBAR_CALLER_PROJECT", PROJECT)
    failures = 0
    for head, ticket in pairs:
        cond = {"kind": "ticket_closed", "ticket": ticket}
        if not apply:
            print("would attach %s -> %s" % (head, json.dumps(cond)))
            continue
        got = request_thread.condition_op(
            {"op": "condition", "project": PROJECT, "id": head,
             "resolves_when": cond}, 0, 1, env=env)
        if not got.get("ok"):
            failures += 1
            print("REFUSED condition %s: %s" % (head, json.dumps(got, ensure_ascii=False)))
    if not apply:
        print("dry run: nothing written")
        return 0

    out = request_sweep.sweep_project(PROJECT, 0, 1, env=env)
    print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
