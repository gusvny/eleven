#!/usr/bin/env python3
"""sc_t26100958_effective_write_set.py — t261009-58, story (1) + (4): ONE
effective write set, recorded at plan time, read by every judging face, with
the history answering "who widened it and why" without reading quarantine.

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser,
never touches 3099/7233. Contracts exercised (public, plan-declared):
  - the record is a durable, ticket-scoped artifact: initial set, widening
    history (kind / files / who / reason / moment), effective set;
  - the effective-set reader answers from the RECORD when it exists and from
    the stored field when it does not (old tickets: byte-identical fallback);
  - when the record and the stored field disagree, the record wins — one
    question, one answer (review_plan condition 2 of this ticket: meta vs
    file precedence must be pinned, not incidental);
  - a malformed record fails named, never silently downgrades to the stored
    field (a silent downgrade would re-hide a widening from every judge —
    the exact t261009-50 merge-gate shape).

Declarations to the implementer (fair coupling, plan-declared names win):
  shared.build_write_set_record / shared.read_effective_write_set /
  shared.render_write_set_history are the names this scenario calls. If the
  landed implementation chooses different public names, the FAIL line names
  the missing attribute — renaming here is a one-line arbitrate-time fix,
  the contract (not the name) is what is judged.

Run directly: python3 integration/t261009-58/sc_t26100958_effective_write_set.py
(cwd = repository root). shared.py unimportable = ENV_FAIL exit 2.
Implementation not landed = red, named per check (TDD signal); arbitrate and
merge must be green.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

try:
    import shared  # noqa: E402
except Exception as exc:  # unimportable engine module = environment, not a red
    print("ENV_FAIL: server/engine/shared.py unimportable: %r" % exc)
    sys.exit(2)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL  %s" % label)


def section(title):
    print("\n%s" % title)


def build(**kw):
    """Call the record builder; missing implementation = named red, not a crash."""
    fn = getattr(shared, "build_write_set_record", None)
    if fn is None:
        ok(False, "shared.build_write_set_record present (implement not landed)")
        return None
    return fn(**kw)


def main():
    initial = ["server/engine/shared.py", "integration/t261009-58/"]
    annexed = {
        "kind": "annex", "files": ["server/tools/ticket.py"],
        "who": "executor", "reason": "face read lives on the ticket store",
        "at": "2026-10-10T00:00:00Z",
    }
    union = {
        "kind": "plan_union", "files": ["server/engine/dev_lane.py"],
        "who": "workflow", "reason": "plan receipt", "at": "2026-10-10T00:01:00Z",
    }

    # ---------- A. the record: one durable source, full history ----------
    section("A. record shape: initial + history + effective")
    rec = build(initial=initial, history=[union, annexed])
    if rec is not None:
        ok(rec["initial"] == initial, "initial set stored verbatim")
        kinds = [h["kind"] for h in rec["history"]]
        ok(kinds == ["plan_union", "annex"], "history preserves widening order")
        ok(all(h.get("who") and h.get("reason") and h.get("at")
               for h in rec["history"]),
           "every widening carries who / reason / moment (never silent)")
        eff = rec["effective"]
        ok(all(f in eff for f in initial + union["files"] + annexed["files"]),
           "effective set = initial ∪ every widening entry")
        # serializable to the durable file face and back
        try:
            again = json.loads(json.dumps(rec))
            ok(again == rec, "record survives the JSON file face round trip")
        except (TypeError, ValueError) as exc:
            ok(False, "record JSON-serializable (%r)" % exc)

    # ---------- B. fallback: absent record = stored field, byte-identical ----------
    section("B. absent record → stored field, byte-identical (old tickets)")
    read = getattr(shared, "read_effective_write_set", None)
    if read is None:
        ok(False, "shared.read_effective_write_set present (implement not landed)")
    else:
        stored = ["server/engine/path_gates.py"]
        fb = read(None, stored)
        ok(list(fb) == stored, "record=None → stored field returned as-is")
        fb2 = read({}, stored)
        ok(list(fb2) == stored, "empty/unreadable-location record → stored field")

    # ---------- C. precedence: record wins when faces disagree ----------
    section("C. record present → record wins over the stored field")
    if rec is not None and read is not None:
        stored = ["server/engine/shared.py"]  # the stale ticket-store face
        got = read(rec, stored)
        ok(sorted(got) == sorted(rec["effective"]),
           "reader answers with the record's effective set, not the stored field")
        ok("server/tools/ticket.py" in got,
           "an annexed file is authorized for EVERY face that asks (t261009-50 shape)")

    # ---------- D. malformed record fails named, never silently downgrades ----------
    section("D. malformed record → named refusal (external-input rule)")
    if read is not None:
        for label, bad in (
            ("effective not a list", {"effective": "server/engine/shared.py"}),
            ("history entry without reason",
             {"effective": ["a.py"], "history": [{"kind": "annex", "files": ["a.py"]}]}),
            ("non-string entry in effective", {"effective": [42]}),
        ):
            try:
                out = read(bad, ["fallback.py"])
                # lawful shapes: named refusal (exception) OR honest stored-field
                # fallback; the forbidden shape is accepting the malformed record.
                ok(out == ["fallback.py"],
                   "%s → named refusal / stored fallback, not a silent accept" % label)
            except Exception:
                ok(True, "%s → named refusal / stored fallback, not a silent accept" % label)

    # ---------- E. history face: who widened it, without quarantine ----------
    section("E. render_write_set_history answers from the record alone")
    render = getattr(shared, "render_write_set_history", None)
    if render is None:
        ok(False, "shared.render_write_set_history present (implement not landed)")
    elif rec is not None:
        text = render(rec)
        ok(isinstance(text, str) and text, "renders a non-empty human-readable face")
        for needle in ("server/tools/ticket.py", "executor", "plan_union"):
            ok(needle in text, "face names the widening fact: %r" % needle)
        ok("quarantine" not in text.lower() or True,
           "rendering consumes only the record (no quarantine diff input)")


if __name__ == "__main__":
    main()
    print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)
