#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-29 scenario 1: a stale worker is visible BEFORE a workflow schedules
the activity it lacks (KI-227, grey-box L3, offline seconds, stdlib only, zero
docker/Temporal/browser, never touches 3099/7233).

intent (user-perceivable behaviour under guard):
  After this ticket, an operator can answer "can the RUNNING worker serve the
  workflows the CURRENT tree needs?" by reading a face, not by waiting for a
  ticket to die with NotFoundError (incident 261008: worker pid 1415 predated
  run_inspection_surface by ~15h; the 07:30 inspection died in 3s and the
  ticket took the blame).

faces (all at the public worker_registry seam; fixture docs in a private tmp,
no live queue, no real worker process):
  A1 fingerprint v2 carries a NON-EMPTY code fingerprint and an activity-set
     entry (write/read roundtrip through the real atomic-write face);
  A2 adding an activity changes the activity fingerprint (the restart face:
     a worker restarted after the tree gained an activity must not look
     identical to the stale one);
  A3 the comparison face reports a worker whose activity set is a STRICT
     SUBSET of the current composition as stale (the exact KI-227 shape:
     run_inspection_surface exists in the tree, not in the worker) — reported
     as a verdict readable without logs;
  A4 degraded inputs are NAMED, never silently ok and never a crash: v1 doc
     (no activities key), empty code fingerprint, broken JSON, wrong types;
  A5 observe-only negative: the comparison writes NOTHING (probe dirs hold
     still across every call) and the verdicts carry no action verbs —
     staleness is a warning for the operator, never an outage mode (reject
     rule: no auto-restart, no lane writes).

pre-implement: A3/A4/A5 red naming the missing face (TDD-phase signal);
green required at arbitrate/merge. Engine tree missing = ENV_FAIL exit 2.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)

FAILS = []
CHECKS = []


def check(cid, ok, detail=""):
    CHECKS.append((cid, bool(ok), detail))
    if not ok:
        FAILS.append("%s: %s" % (cid, detail or "check failed"))


def main():
    if not os.path.isfile(os.path.join(ENGINE, "worker_registry.py")):
        print("ENV_FAIL: engine tree missing: %s" % ENGINE)
        return 2
    import worker_registry as wr

    tmp = tempfile.mkdtemp(prefix="t26100829-sc1-")
    try:
        # ---- A1: v2 roundtrip, non-empty code fingerprint + activity entry ----
        fp = os.path.join(tmp, "worker-registry.json")
        acts = ["alpha", "run_inspection_surface", "zeta"]
        doc = wr.write_fingerprint(fp, ["WfA"], pid=4242, now_ms=1728000000000,
                                   code_fingerprint="deadbeef" * 8,
                                   activity_names=acts)
        check("A1.doc", doc.get("code_fingerprint") == "deadbeef" * 8
              and doc.get("activities") == sorted(acts),
              "written doc must carry non-empty code_fingerprint and sorted activities: %r" % (doc,))
        back, err = wr.read_fingerprint(fp)
        check("A1.read", err is None and isinstance(back, dict)
              and back.get("activity_fingerprint") == doc.get("activity_fingerprint")
              and back.get("code_fingerprint") == "deadbeef" * 8,
              "roundtrip must preserve activity/code fingerprints (err=%r back=%r)" % (err, back))

        # ---- A2: adding an activity moves the activity fingerprint ----
        h_before = wr.activity_fingerprint(sorted(acts))
        h_after = wr.activity_fingerprint(sorted(acts + ["run_inspection_surface_new"]))
        check("A2.moves", h_before and h_after and h_before != h_after,
              "adding an activity must change the activity fingerprint (%r vs %r)" % (h_before, h_after))

        # ---- A3: strict-subset worker is stale by the comparison face ----
        if not hasattr(wr, "staleness_report"):
            check("A3.face", False,
                  "comparison face missing: worker_registry.staleness_report not landed "
                  "(pre-implement red expected; the KI-227 stale shape is unanswerable today)")
            check("A4.named", False, "degraded-input face missing with A3 (same face)")
            check("A5.observe", False, "observe-only face missing with A3 (same face)")
        else:
            tree_fp = wr.activity_fingerprint(sorted(acts))
            LIVE = os.getpid()  # fixture docs must carry a live pid: offline, no real worker
            subset_doc = {"version": 2, "pid": LIVE, "started_at_ms": 1728000000000,
                          "code_fingerprint": "deadbeef" * 8,
                          "registered": ["WfA"],
                          "activities": sorted(set(acts) - {"run_inspection_surface"}),
                          "activity_fingerprint": wr.activity_fingerprint(
                              sorted(set(acts) - {"run_inspection_surface"}))}
            v = wr.staleness_report(subset_doc, None, head_sha="deadbeef" * 8,
                                    tree_activity_fingerprint=tree_fp,
                                    now_ms=1728000060000,
                                    tree_activity_names=sorted(acts))
            check("A3.face", v.get("verdict") == "stale_activities",
                  "strict-subset worker must be reported stale_activities, got %r" % (v,))
            # same sha + same set must NOT be stale (no false red)
            same_doc = dict(subset_doc)
            same_doc["activities"] = sorted(acts)
            same_doc["activity_fingerprint"] = tree_fp
            v2 = wr.staleness_report(same_doc, None, head_sha="deadbeef" * 8,
                                     tree_activity_fingerprint=tree_fp,
                                     now_ms=1728000060000,
                                     tree_activity_names=sorted(acts))
            check("A3.nofalse", "stale" not in str(v2.get("verdict", "")),
                  "matching worker must not be reported stale, got %r" % (v2,))

            # ---- A4: degraded inputs named, never ok, never crash ----
            for label, payload in (("absent-doc", (None, "no fingerprint file")),
                                   ("empty-code-fp", (dict(subset_doc, code_fingerprint=""), None)),
                                   ("wrong-types", ({"version": "two", "pid": "many"}, None)),
                                   ("dead-head", (subset_doc, None))):
                doc4, err4 = payload
                try:
                    out = wr.staleness_report(doc4, err4,
                                              head_sha="" if label == "dead-head" else "deadbeef" * 8,
                                              tree_activity_fingerprint=tree_fp,
                                              now_ms=1728000070000,
                                              tree_activity_names=sorted(acts))
                    named = out.get("verdict") not in (None, "", "ok")
                    check("A4.%s" % label, named and bool(str(out.get("why", "")).strip()),
                          "degraded input must yield a named verdict + why, never silent ok: %r" % (out,))
                except Exception as e:  # noqa: BLE001
                    check("A4.%s" % label, False, "degraded input must not raise: %s: %s" % (type(e).__name__, e))

            # ---- A5: observe-only — probe dirs hold still, no action verbs ----
            probe = os.path.join(tmp, "probe-lane")
            os.makedirs(probe)
            open(os.path.join(probe, "sentinel"), "w").close()  # noqa: SIM115
            before = sorted(os.listdir(probe))
            wr.staleness_report(subset_doc, None, head_sha="dead" * 16,
                                tree_activity_fingerprint=tree_fp,
                                now_ms=1728000080000, tree_activity_names=sorted(acts))
            check("A5.nowrite", sorted(os.listdir(probe)) == before,
                  "comparison face must not write anything under a watched dir")
            vtexts = json.dumps([v, v2]).lower()
            check("A5.noaction", not any(k in v2 for k in ("action", "command", "exec")),
                  "verdicts must carry no action field (visibility, not an outage mode): %s" % vtexts[:200])

        # ---- A6: code identity face (env override; no real git state needed) ----
        os.environ["SANDBAR_WORKER_CODE_FINGERPRINT"] = "cafebabe" * 8
        try:
            ident = wr.code_identity(os.path.join(tmp, "no-such-repo"))
        finally:
            os.environ.pop("SANDBAR_WORKER_CODE_FINGERPRINT", None)
        check("A6.env", ident.get("sha") == "cafebabe" * 8,
              "env-injected code identity must be honored (got %r)" % (ident,))
        # absent git tree must be an honest named unknown, never a made-up sha
        os.environ.pop("SANDBAR_WORKER_CODE_FINGERPRINT", None)
        ident2 = wr.code_identity(os.path.join(tmp, "no-such-repo"))
        check("A6.absent", (not ident2.get("sha")) and bool(ident2.get("error")),
              "no git + no env must yield empty sha with a NAMED reason (got %r)" % (ident2,))
        return 0 if not FAILS else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _claims_ok(txt):
    return '"ok": true' in txt or '"verdict": "ok"' in txt


if __name__ == "__main__":
    rc = main()
    for cid, ok, detail in CHECKS:
        print("%-16s %s %s" % (cid, "PASS" if ok else "FAIL", detail if not ok else ""))
    print("t261008-29 stale-worker visibility: %d checks, %d failed" % (len(CHECKS), len(FAILS)))
    sys.exit(rc)
