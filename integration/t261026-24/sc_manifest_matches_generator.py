#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch-stage exception manifest matches its generator (t261026-24).

Grey-box L2 contract, offline seconds, zero docker, zero Temporal.

Intent
------
The batch-stage exception manifest (integration/batch_stage_exceptions.json) is a
machine-consumed artefact: the t260921-06 sentinel reads it as the sanctioned
exemption list for its consumer-census invariant. Its single declared writer is
the generator integration/t260921-06/gen_batch_stage_exceptions.py (ROWS ->
sorted -> json.dumps indent=2, ensure_ascii=False, trailing newline).

This ticket removes rows from BOTH files in lockstep. The failure surface this
scenario pins: the JSON is edited but the generator ROWS go stale (or the other
way round). The sentinel cannot catch that drift - it only checks the JSON - so
the removed rows silently RESURRECT the next time anyone runs the generator,
and rows that were re-labeled or corrected are silently lost. This is the F7
loss class the manifest rows already carry in their own evidence fields
(worker squash dropped manifest rows twice before a deterministic re-add was
introduced).

Faces
-----
A1 the manifest bytes equal exactly what the generator would write today
   (same sort, same serialization) - any drift is FAIL, naming the row-count
   delta and the first differing entry names;
A2 no duplicate entries in either face;
A3 every ROWS entry carries the five schema keys with non-empty
   reason/evidence (the contract the sentinel's schema check pins on the JSON,
   mirrored here on the writer side).

Generator module unavailable = ENV_FAIL exit 2. Manifest missing = ENV_FAIL
exit 2 (the sentinel would red separately; this scenario pins writer/reader
agreement, not existence).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEG = HERE.parents[0]
REPO = HERE.parents[1]
GEN = INTEG / "t260921-06" / "gen_batch_stage_exceptions.py"
MANIFEST = INTEG / "batch_stage_exceptions.json"
SCHEMA_KEYS = ("entry", "pool", "project_pattern", "reason", "evidence")

failures = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def die_env(msg):
    print("ENV_FAIL: %s" % msg, flush=True)
    return 2


def load_generator():
    import importlib.util
    if not GEN.exists():
        return None, "generator missing: %s" % GEN
    spec = importlib.util.spec_from_file_location("gen_batch_stage_exceptions", GEN)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # top level only: imports + ROWS, no writes
    except Exception as exc:  # noqa: BLE001 - import failure is an env face
        return None, "generator import failed: %r" % (exc,)
    return mod, None


def main() -> int:
    for p in (GEN, MANIFEST):
        if not p.exists():
            return die_env("input missing: %s" % p)
    gen, err = load_generator()
    if gen is None:
        return die_env(err)

    rows = sorted(gen.ROWS, key=lambda r: r["entry"])
    expected = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    actual = MANIFEST.read_text(encoding="utf-8")
    exp_names = [r.get("entry") for r in rows]
    act_names = [r.get("entry") for r in json.loads(actual)]

    # A1 writer/reader agreement, byte-identical
    if actual == expected:
        ok(True, "A1 manifest bytes == generator rendering (%d rows)" % len(rows))
    else:
        import difflib
        exp_rows = json.loads(expected)
        act_rows = json.loads(actual)
        only_writer = sorted(set(exp_names) - set(act_names))
        only_reader = sorted(set(act_names) - set(exp_names))
        shared = sorted(set(exp_names) & set(act_names))
        changed = [
            n for n in shared
            if next(r for r in exp_rows if r.get("entry") == n)
            != next(r for r in act_rows if r.get("entry") == n)
        ]
        detail = ""
        if only_writer or only_reader or changed:
            detail = (" rows-in-generator-not-in-json=%s rows-in-json-not-in-generator=%s "
                      "changed-rows=%s" % (only_writer, only_reader, changed))
        else:
            detail = " same row set, bytes differ (formatting/order): first diff=%s" % (
                next((l for l in difflib.unified_diff(
                    actual.splitlines(), expected.splitlines(), lineterm="")),
                ""),)
        ok(False, "A1 manifest != generator rendering (json=%d rows, generator=%d rows)%s"
           % (len(act_rows), len(exp_rows), detail))

    # A2 no duplicate entries on either face
    ok(len(exp_names) == len(set(exp_names)),
       "A2 generator rows unique (%d entries)" % len(exp_names))
    ok(len(act_names) == len(set(act_names)),
       "A2 manifest rows unique (%d entries)" % len(act_names))

    # A3 schema keys non-empty on the writer side
    bad = [r.get("entry") for r in rows
           if any(not str(r.get(k, "")).strip() for k in SCHEMA_KEYS)]
    ok(not bad, "A3 all generator rows carry the five schema keys non-empty%s"
       % ("" if not bad else " - bad=%s" % bad))

    print("MANIFEST_MATCH_SUMMARY rows=%d failures=%d" % (len(rows), len(failures)),
          flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
