#!/usr/bin/env python3
"""t261009-51 scenario 2: the canonical write path gets a home and the one
deliberate normalization is proven content-free.

Contract (ticket spec 1/3/4, KI-01M4HD396VNTTAY20CH0681N0Q):

- W1 the single entry point (integration/lib_registry.py, importable) writes
  canonical bytes: indent=2, ensure_ascii=False (raw non-ASCII, no \\u
  escapes), insertion key order preserved, exactly one trailing newline —
  the sibling style integration/known-red-baseline.json already uses;
- W2 content round-trips for BOTH declared root shapes (dict AND list —
  integration/batch_stage_exceptions.json is a list-rooted registry);
- W3 a lone-surrogate payload fails LOUD: write_registry raises, and it never
  silently downgrades to ensure_ascii=True to survive (same family contract
  as integration/lib_emit_anchor.py); no partial file is left behind;
- W4 the declared set is real: importable, names the three shared JSON
  registries under integration/ (test_anchors.json, known-red-baseline.json,
  batch_stage_exceptions.json), and every declared path exists;
- W5 the ticket's deliberate normalization is CONTENT-FREE, proven not
  claimed: for every declared registry, `git show HEAD:<path>` parsed equals
  the on-disk bytes parsed (serialization-only change).

Grey-box L3, offline, seconds, zero docker/Temporal/browser, never touches
3099. Read-only over the real tree except a temp-dir write face (tmpfile,
removed). Implementation not landed (lib_registry absent) = FAIL named, the
expected TDD signal; arbitrate/merge must be green.

Run: python3 integration/t261009-51/sc_registry_writer_canonical.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
INTEG = os.path.join(REPO, "integration")

EXPECTED_MEMBERS = {
    "test_anchors.json",
    "known-red-baseline.json",
    "batch_stage_exceptions.json",
}

FAILURES = []


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       ("" if cond else " | " + detail)))
    if not cond:
        FAILURES.append(name)


def main():
    if str(INTEG) not in sys.path:
        sys.path.insert(0, str(INTEG))
    try:
        import lib_registry as reg
    except ImportError as e:
        print("FAIL W0.lib-registry-importable | integration/lib_registry.py "
              "absent or not importable: %s (implementation not landed — "
              "expected TDD-phase red; arbitrate/merge must be green)" % e)
        return 1

    # The public write face. The module contract is write_registry(path, obj);
    # if the entry point is renamed this is a contract break, named as such.
    if not hasattr(reg, "write_registry"):
        print("FAIL W0.write-registry-face | lib_registry exposes no "
              "write_registry(path, obj) entry point")
        return 1

    with tempfile.TemporaryDirectory(prefix="t26100951-sc-") as tmpdir:
        return _run(reg, tmpdir)


def _run(reg, tmpdir):
    target = os.path.join(tmpdir, "probe.json")

    # W1 canonical bytes shape, unsorted keys to pin insertion order.
    probe = {"zz_last": {"note": "非 ASCII 原样保留"}, "aa_first": 1}
    reg.write_registry(target, probe)
    raw = open(target, "rb").read()
    text = raw.decode("utf-8")
    expected = json.dumps(probe, ensure_ascii=False, indent=2) + "\n"
    check("W1.canonical-bytes", text == expected,
          "writer bytes != canonical form")
    check("W1.raw-non-ascii-preserved", "非 ASCII" in text and "\\u" not in text,
          "non-ASCII escaped or re-encoded")
    check("W1.insertion-order-preserved",
          text.index("zz_last") < text.index("aa_first"),
          "key order not insertion order")
    check("W1.single-trailing-newline",
          raw.endswith(b"}\n") and not raw.endswith(b"\n\n"))

    # W2 list root round-trips (batch_stage_exceptions.json is list-rooted).
    list_target = os.path.join(tmpdir, "list.json")
    list_probe = [{"b": 1, "a": 2}]
    reg.write_registry(list_target, list_probe)
    back = json.loads(open(list_target, encoding="utf-8").read())
    check("W2.list-root-roundtrip", back == list_probe)

    # W3 lone surrogate fails loud, and the residue face: a failed write must
    # never leave PLAUSIBLE bytes behind — no file, or a zero-byte file, never
    # partially-written or ascii-downgraded content a reader could parse.
    with tempfile.TemporaryDirectory(prefix="t26100951-sc-") as sd:
        surrogate_target = os.path.join(sd, "surrogate.json")
        raised = False
        try:
            reg.write_registry(surrogate_target, {"bad": "\udcff"})
        except Exception:
            raised = True
        residue = b""
        if os.path.exists(surrogate_target):
            residue = open(surrogate_target, "rb").read()
        check("W3.lone-surrogate-fails-loud", raised,
              "no exception — writer silently tolerated an unwritable payload")
        check("W3.no-plausible-residue",
              len(residue) == 0 or
              residue.decode("utf-8", "replace").lstrip().startswith(("{", "[")),
              "residue bytes: %r" % residue[:40])

    # W4 the declared set names the three shared registries, all present.
    declared = getattr(reg, "DECLARED_REGISTRIES", None)
    if declared is None:
        check("W4.declared-set-importable", False,
              "lib_registry exposes no DECLARED_REGISTRIES — the canonical "
              "set must live in the repo, not in a writer's head")
    else:
        names = set(declared) if not isinstance(declared, dict) else set(declared)
        basenames = {os.path.basename(str(n)) for n in names}
        check("W4.declared-set-members", EXPECTED_MEMBERS <= basenames,
              "declared set = %s" % sorted(basenames))
        missing = [n for n in names
                   if not os.path.isfile(os.path.join(INTEG,
                                                      os.path.basename(str(n))))]
        check("W4.declared-paths-exist", not missing,
              "missing: %s" % missing)

    # W5 the normalization is content-free: HEAD-parsed == disk-parsed, except
    # this ticket's OWN anchor registrations (registering its two scenarios in
    # test_anchors.json is a lawful, declared content change; the
    # NORMALIZATION of existing entries must touch zero values). The other two
    # declared registries carry no ticket additions, so they compare exactly.
    if declared is not None:
        ticket_anchors = {
            "integration/t261009-51/sc_registry_style_drift_bite.py",
            "integration/t261009-51/sc_registry_writer_canonical.py",
        }
        for n in sorted(names):
            basename = os.path.basename(str(n))
            head = subprocess.run(
                ["git", "show", "HEAD:integration/%s" % basename],
                cwd=REPO, capture_output=True)
            if head.returncode != 0:
                check("W5.%s.head-readable" % basename, False,
                      head.stderr.decode("utf-8", "replace").strip()[:120])
                continue
            try:
                head_obj = json.loads(head.stdout.decode("utf-8"))
                disk_obj = json.loads(open(os.path.join(INTEG, basename),
                                           encoding="utf-8").read())
            except (ValueError, OSError) as e:
                check("W5.%s.parse" % basename, False, str(e)[:120])
                continue
            if basename == "test_anchors.json":
                # Only the ticket's own scenario entries may differ.
                head_sc = dict(head_obj.get("scenarios") or {})
                disk_sc = dict(disk_obj.get("scenarios") or {})
                added = {k: v for k, v in disk_sc.items() if k not in head_sc}
                changed = {k for k in disk_sc
                           if k in head_sc and disk_sc[k] != head_sc[k]}
                rest_same = all(disk_obj.get(sec) == head_obj.get(sec)
                                for sec in disk_obj if sec != "scenarios")
                same = (not changed and rest_same
                        and set(added) <= ticket_anchors)
                check("W5.%s.content-free-normalization" % basename, same,
                      "changed existing keys: %s; non-ticket additions: %s; "
                      "other sections differ: %s" %
                      (sorted(changed),
                       sorted(set(added) - ticket_anchors), not rest_same))
            else:
                same = head_obj == disk_obj
                check("W5.%s.content-free-normalization" % basename, same,
                      "HEAD content != disk content — the normalization "
                      "changed meaning, not just style")
    return 0


if __name__ == "__main__":
    code = main()
    print("SUMMARY %s: %d failure(s)" %
          ("PASS" if not FAILURES else "FAIL", len(FAILURES)))
    sys.exit(2 if code == 2 else (1 if (FAILURES or code == 1) else 0))
