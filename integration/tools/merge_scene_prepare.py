#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_scene_prepare — create the conflict scene for a develop-line carrier.

Why this exists (ticket t261013-06): the carrier lane is based on main, so the
landing would conflict in 15 files. The design's remedy is that the lane merges
the line and lands again, and a worktree's ``.git`` is a gitfile into the main
repository, so an agent sandbox cannot run that merge. It runs on the worker or
host surface through the engine's existing activity.

Two rounds were lost to defects in the handed-over one-liner (a bare python
without ``temporalio``, then an empty Temporal address). This tool replaces the
one-liner so that both classes are structural instead:

* the interpreter is checked, and the address comes from the engine's own single
  source (``shared.TARGET_HOST`` / ``shared.NAMESPACE``);
* the lane is identified and guarded before anything runs, so a wrong working
  directory can never merge into the wrong checkout;
* every exit path is named, and a failure exits non-zero.

Exit codes: 0 = the scene exists (created now, or already present), 2 = refused
or failed (always named).
"""
import argparse
import json
import os
import subprocess
import sys

TICKET = "t261013-06"
DEFAULT_BRANCH = "lane/t261013-06"
DEFAULT_LINE = "develop"
GIT_TIMEOUT_S = 120


class PrepareError(Exception):
    """The scene cannot be prepared. Always a named reason, never a guess."""


def git(args, lane):
    try:
        proc = subprocess.run(["git"] + list(args), cwd=lane, capture_output=True,
                              text=True, timeout=GIT_TIMEOUT_S, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrepareError("git %s unusable in %s: %s" % (" ".join(args), lane, exc))
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def check_lane(lane, branch, line):
    """Guard the lane before any activity runs. Returns the line's sha."""
    if not os.path.isdir(lane):
        raise PrepareError("lane_missing: %s is not a directory" % lane)
    rc, top, err = git(["rev-parse", "--show-toplevel"], lane)
    if rc != 0 or not top:
        raise PrepareError("lane_not_a_worktree: git rev-parse --show-toplevel failed in %s: %s"
                           % (lane, err or "no output"))
    if os.path.realpath(top) != os.path.realpath(lane):
        raise PrepareError("lane_root_mismatch: the working directory %s is not the top level of a "
                           "checkout (%s) — run this from the lane root" % (lane, top))
    rc, head_branch, _err = git(["rev-parse", "--abbrev-ref", "HEAD"], lane)
    if rc != 0:
        raise PrepareError("lane_head_unreadable in %s" % lane)
    if head_branch != branch:
        raise PrepareError("lane_branch_mismatch: HEAD is %r, expected %r — refusing to merge into "
                           "another lane" % (head_branch, branch))
    rc, sha, err = git(["rev-parse", "--verify", "%s^{commit}" % line], lane)
    if rc != 0 or not sha:
        raise PrepareError("line_ref_unresolved: %r is not a commit in %s: %s"
                           % (line, lane, err or "no output"))
    return sha.splitlines()[0].strip()


def scene_state(lane, line):
    """'present' when a merge is in progress, 'merged' when the line is already
    an ancestor of HEAD, else 'absent'. The two settled shapes are no-ops."""
    rc, _out, _err = git(["rev-parse", "--verify", "MERGE_HEAD"], lane)
    if rc == 0:
        return "present"
    rc, _out, _err = git(["merge-base", "--is-ancestor", line, "HEAD"], lane)
    if rc == 0:
        return "merged"
    return "absent"


def load_address(lane, host, namespace):
    """The Temporal address, from the engine's own single source.

    An explicit override needs no import (tests, operators); otherwise the
    address comes from the lane's own ``server/engine/shared.py``, and an
    unavailable engine tree is a named refusal, never an empty string.
    """
    if host and namespace:
        return host, namespace
    engine = os.path.join(lane, "server", "engine")
    tools = os.path.join(lane, "server", "tools")
    for path in (engine, tools):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        import shared  # noqa: PLC0415 — resolved from the lane's own engine tree
    except Exception as exc:  # noqa: BLE001
        raise PrepareError("engine_shared_unimportable: %s: %s — run this tool with the engine "
                           "interpreter (server/engine/.venv/bin/python)"
                           % (type(exc).__name__, exc))
    resolved_host = host or getattr(shared, "TARGET_HOST", "")
    resolved_ns = namespace or getattr(shared, "NAMESPACE", "")
    if not resolved_host or not resolved_ns:
        raise PrepareError("temporal_address_unresolved: host=%r namespace=%r (shared.TARGET_HOST / "
                           "shared.NAMESPACE are empty)" % (resolved_host, resolved_ns))
    return resolved_host, resolved_ns


def activity_call(lane, host, namespace, ticket, branch, line):
    try:
        import engine_ops  # noqa: PLC0415 — from the lane's server/tools
    except Exception as exc:  # noqa: BLE001
        raise PrepareError("engine_ops_unimportable: %s: %s — run this tool with the engine "
                           "interpreter (server/engine/.venv/bin/python)"
                           % (type(exc).__name__, exc))
    payload = {"ticket_id": ticket, "worktree": lane, "branch": branch, "base_ref": line}
    return engine_ops._run_activity(host, namespace, "prepare_conflict_resolution", payload), payload


def scene_receipt_verdict(out):
    """Judge an activity receipt. Returns (ok, action, conflict_files, error).

    The invocation's ``ok`` only says the activity ran. The merge's own outcome
    is the INNER receipt (``result.ok``): a merge that failed there (measured:
    ``git merge develop 失败（非冲突）: fatal: Unable to write index.``) must never
    be reported as a created scene (t261013-06 arbitration finding A).
    """
    if not isinstance(out, dict):
        return False, "activity refused or failed", None, "receipt_not_an_object:%r" % (out,)
    inner = out.get("result") if isinstance(out.get("result"), dict) else {}
    if not out.get("ok"):
        return False, "activity invocation failed", None, str(out.get("error") or "")
    if not inner.get("ok"):
        return (False, "merge failed (the activity ran but the merge did not)",
                inner.get("conflict_files"), str(inner.get("error") or ""))
    if inner.get("conflict_files"):
        return True, "merge scene created", inner.get("conflict_files"), ""
    if inner.get("up_to_date"):
        return True, "no action: the line was already contained (idempotent)", None, ""
    return (True, "merge completed with no conflicts (the activity committed the merge itself)",
            None, "")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Create the conflict scene for the develop-line carrier (t261013-06): merge the "
                    "line into the lane through the engine's own activity. Idempotent.")
    parser.add_argument("--lane", default=".", help="the lane root (default: the current directory)")
    parser.add_argument("--ticket", default=TICKET, help="the ticket id (default: %s)" % TICKET)
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="the lane branch (default: %s)"
                        % DEFAULT_BRANCH)
    parser.add_argument("--line", default=DEFAULT_LINE, help="the line ref to merge (default: %s)"
                        % DEFAULT_LINE)
    parser.add_argument("--host", default="", help="override the Temporal host (tests, operators)")
    parser.add_argument("--namespace", default="", help="override the Temporal namespace")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the guards, the resolved address and the payload; call nothing")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    lane = os.path.realpath(args.lane)
    result = {"lane": lane, "ticket": args.ticket, "branch": args.branch, "line": args.line}
    try:
        line_sha = check_lane(lane, args.branch, args.line)
        result["line_sha"] = line_sha
        state = scene_state(lane, args.line)
        result["scene"] = state
        if state == "present":
            result["action"] = "none: the conflict scene is already in the worktree (idempotent)"
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if state == "merged":
            result["action"] = "none: the line is already contained in HEAD (idempotent)"
            print(json.dumps(result, ensure_ascii=False))
            return 0
        host, namespace = load_address(lane, args.host, args.namespace)
        result["temporal_host"] = host
        result["temporal_namespace"] = namespace
        if args.dry_run:
            rc, head, _err = git(["rev-parse", "HEAD"], lane)
            result["head"] = head if rc == 0 else ""
            result["payload"] = {"ticket_id": args.ticket, "worktree": lane,
                                 "branch": args.branch, "base_ref": args.line}
            result["action"] = "dry-run: no activity called"
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 0
        out, payload = activity_call(lane, host, namespace, args.ticket, args.branch, args.line)
        result["payload"] = payload
        result["receipt"] = out
        ok, action, conflicts, error = scene_receipt_verdict(out)
        result["conflict_files"] = conflicts
        result["action"] = action
        if error:
            result["receipt_error"] = error
        print(json.dumps(result, ensure_ascii=False)[:4000])
        return 0 if ok else 2
    except PrepareError as exc:
        result["error"] = str(exc)
        result["action"] = "refused"
        print(json.dumps(result, ensure_ascii=False) if not args.dry_run
              else json.dumps(result, ensure_ascii=False, indent=1))
        return 2


if __name__ == "__main__":
    sys.exit(main())
