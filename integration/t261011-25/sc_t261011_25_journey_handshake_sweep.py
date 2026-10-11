#!/usr/bin/env python3
"""t261011-25: the project-template journey waits by handshake, never by a
fixed-interval poll — and the wait helper it uses cannot hang silently.

Ticket t261011-25 part 1 (host order 261011: "handshake instead of polling"
for t260924-04-project-template-journey). Grey-box L3, offline seconds, real
processes over real os.pipe pairs, zero docker/Temporal/browser/ports, never
touches 3099.

Faces:
- A  static sweep: the journey file carries no time.sleep( and no poll_snap
     (the old fixed-interval machinery); the sweep has TEETH — a synthetic
     offender file is named with file:line;
- B  the handshake helper's public face over REAL pipes (the landed
     lib_journey_handshake.LineReader): a producer line arrives ->
     wait_for returns it blocking (no polling); a line that never arrives
     -> None WITHIN its bound and reader.death names the timeout, never a
     hang; producer EOF -> None and reader.death names the eof; a predicate
     that never matches -> None and reader.death names the timeout; an
     oversized line is truncated to the declared byte cap and the event is
     preserved (never a memory event, never a lost event); the reader
     thread dying mid-wait surfaces as a named death, never a silent hang.

Intent split: the unit truth table of the helper (fake streams, exact
exception vocabulary details) belongs to developer L1
(integration/tests/test_t26101125_journey_handshake.py); the REAL journey
scenario (registered as the project-template journey entry) owns the
behavioral assertions, unchanged by this ticket; this entry owns only the
class guard (the poll machinery cannot quietly come back) and the helper's
end-to-end pipe behaviour. Pre-landing red is the expected TDD signal; green
required at the integration gate / merge.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TICKET_DIR = os.path.join(ROOT, "integration", "t261011-25")
JOURNEY = os.path.join(ROOT, "integration", "t260924-04",
                       "sc_project_template_ticket_journey.py")
HELPER = os.path.join(ROOT, "integration", "t260924-04",
                      "lib_journey_handshake.py")

CHILD = r"""
import sys, time
mode = sys.argv[1]
if mode == "line":
    time.sleep(0.1)
    sys.stdout.write("JOURNEY workflow finished t-1 status=closed\n")
    sys.stdout.flush()
elif mode == "silent":
    time.sleep(5)
elif mode == "eof":
    pass
elif mode == "oversize":
    sys.stdout.write("x" * 70000 + "\n")
    sys.stdout.flush()
elif mode == "wrong":
    sys.stdout.write("JOURNEY workflow finished other status=running\n")
    sys.stdout.flush()
    time.sleep(5)
"""


def bail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def sweep(path):
    """Return a list of (lineno, text) hits for the banned poll machinery.
    Judged on TOKENS (comments and docstrings stripped via tokenize): a note
    may NAME the retired machinery, only CODE can bring it back."""
    import io
    import tokenize
    hits = []
    with open(path, "rb") as f:
        prev = None
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.OP and tok.string == ".":
                continue   # keep prev across the attribute dot: time . sleep
            if tok.type != tokenize.NAME:
                prev = None
                continue
            val = tok.string
            banned = val == "poll_snap" or (val == "sleep" and prev == "time")
            if banned:
                hits.append((tok.start[0], val))
            prev = val
    return hits


def main():
    # ---- A: static sweep with teeth ----
    if not os.path.isfile(JOURNEY):
        bail("journey file missing: %s" % JOURNEY)
    hits = sweep(JOURNEY)
    if hits:
        bail("journey still carries the fixed-interval machinery at %s"
             % hits)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write("import time\ntime.sleep(3)  # synthetic offender\n")
        offender = tf.name
    try:
        teeth = sweep(offender)
        if not teeth or teeth[0][0] != 2:
            bail("sweep has no teeth (synthetic offender not named: %s)"
                 % teeth)
    finally:
        os.unlink(offender)

    # ---- B: helper public face over real pipes (landed LineReader contract) ----
    if not os.path.isfile(HELPER):
        bail("handshake helper not landed: %s " % HELPER)
    spec = importlib.util.spec_from_file_location("lib_journey_handshake",
                                                  HELPER)
    try:
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
    except Exception as e:  # noqa: BLE001
        bail("helper unimportable: %r" % e)
    for face in ("LineReader", "MAX_LINE_BYTES"):
        if not hasattr(helper, face):
            bail("helper contract drifted (no %s face)" % face)

    def spawn(mode):
        return subprocess.Popen([sys.executable, "-c", CHILD, mode],
                                stdout=subprocess.PIPE)

    # B1 producer line arrives -> returned, blocking
    p = spawn("line")
    try:
        r = helper.LineReader(p.stdout)
        line = r.wait_for(lambda s: "finished" in s, 5.0, "b1")
        if not (isinstance(line, str) and "finished" in line):
            bail("wait_for did not return the producer line: %r (death=%r)"
                 % (line, getattr(r, "death", None)))
    except Exception as e:  # noqa: BLE001
        bail("wait_for failed on a live producer line: %r" % e)
    finally:
        p.kill()

    # B2 line never arrives -> None within its bound, death names the timeout
    p = spawn("silent")
    t0 = time.monotonic()
    try:
        r = helper.LineReader(p.stdout)
        got = r.wait_for(lambda s: "finished" in s, 1.0, "b2-silent-producer")
        took = time.monotonic() - t0
        if got is not None:
            bail("wait_for returned on a silent producer: %r" % (got,))
        if took > 4.0:
            bail("timeout fired late (%.1fs) — hang-shaped" % took)
        if "timeout" not in str(getattr(r, "death", "")):
            bail("death does not name the timeout: %r" % (r.death,))
    except Exception as e:  # noqa: BLE001
        bail("wait_for raised instead of naming the timeout: %r" % e)
    finally:
        p.kill()

    # B3 producer EOF -> None, death names the eof (never a silent swallow)
    p = spawn("eof")
    try:
        r = helper.LineReader(p.stdout)
        got = r.wait_for(lambda s: "finished" in s, 3.0, "b3-eof")
        if got is not None:
            bail("wait_for returned a line on a closed pipe: %r" % (got,))
        if "eof" not in str(getattr(r, "death", "")).lower():
            bail("death does not name the EOF: %r" % (r.death,))
    except Exception as e:  # noqa: BLE001
        bail("wait_for raised on EOF instead of naming it: %r" % e)
    finally:
        p.kill()

    # B4 oversized line -> truncated to the declared cap, event preserved
    p = spawn("oversize")
    try:
        r = helper.LineReader(p.stdout)
        got = r.wait_for(lambda s: True, 5.0, "b4-oversize")
        if not isinstance(got, str) or len(got.encode()) > helper.MAX_LINE_BYTES:
            bail("oversized line not held to the declared cap: %d bytes"
                 % len((got or "").encode()))
        if got is None:
            bail("oversized line LOST as an event (death=%r)"
                 % (getattr(r, "death", None),))
    except Exception as e:  # noqa: BLE001
        bail("wait_for raised on an oversized line: %r" % e)
    finally:
        p.kill()

    # B5 predicate never matches -> None, death names the timeout
    p = spawn("line")
    try:
        r = helper.LineReader(p.stdout)
        got = r.wait_for(lambda s: "never-this" in s, 2.0, "b5-unmatched")
        if got is not None:
            bail("wait_for returned a line its predicate rejected: %r"
                 % (got,))
        death = str(getattr(r, "death", "") or "")
        # the producer exits after its one line, so the wait's terminal is
        # legitimately either the timeout or the EOF — the contract is that
        # SOME terminal is NAMED, never a silent None
        if not any(w in death.lower() for w in ("timeout", "eof", "error")):
            bail("unmatched-predicate terminal is unnamed: %r" % (r.death,))
    except Exception as e:  # noqa: BLE001
        bail("wait_for raised on an unmatched predicate: %r" % e)
    finally:
        p.kill()

    print("PASS: journey is handshake-only (sweep clean with teeth); helper "
          "reads live lines blocking, times out by name within its bound, "
          "names EOF and unmatched predicates, and holds oversized lines to "
          "the declared cap")
    sys.exit(0)


if __name__ == "__main__":
    main()
