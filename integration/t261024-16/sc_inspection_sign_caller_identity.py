#!/usr/bin/env python3
"""t261024-16 scenario: inspection human-gate sign x caller identity (grey-box L3,
isolated stage, real ticket, exclusive).

User story (ticket t261024-16): the inspection period's human gate leaked on both
sides of the caller-identity dimension. The sign handler judged the cross-project
gate BEFORE the close-signature validation, so under the t260925-08 refuse default an
undeclared caller's refusal masked every named refusal (agent self-sign invisible on
the face, gate_error never showed the rule) AND ate the human sign (ticket never
closed). The fix (a) validates the signature first so every refusal names its own
rule, and (b) records-and-allows an undeclared human sign at the sign call site only
(policy="record" there; every other op keeps the knob). This scenario pins the
caller-identity surface of that fix. The four acceptance assertions of
t260915-08-sign-journey (undeclared human sign closes; agent refused; wrong gate
refused; board row) live there and are NOT repeated here — intent division:
sign-journey owns "the sign channel closes the ticket", this case owns "the sign
channel judges caller identity honestly per identity class".

Sub-cases:
  A. guard — declared FOREIGN caller sign refused by name: the refusal text names the
     cross-project rule (both projects readable); the ticket stays in the gate and
     never reaches a terminal state. Guard for the reorder: validate-first must not
     open the foreign-caller channel.
  B. guard — agent sign with a DECLARED OWN-project caller still refused by name:
     the self-sign rule wins regardless of how clean the caller identity is.
  C. injected — absent who stays fail-closed AND the refusal names the missing who
     (not a generic cross-project text): a malformed payload is refused for ITS OWN
     reason, never masked by an unrelated gate.
  D. core — undeclared human sign (the workbench-bare channel) is accepted AND the
     acceptance is recorded, not silent: the ticket closes, the ledger lands with
     human_gate.who, and the ticket face/timeline carries a named record row for the
     undeclared-caller sign (auditable acceptance — "record, not refuse" promise).

Sub-case C/D are red before the fix lands (TDD signal); A/B are guards and must stay
green across the fix. Three-state contract: missing bench/temporalio = ENV_FAIL exit
2, named; no SKIP.

Run: python3 -B integration/t261024-16/sc_inspection_sign_caller_identity.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t260905-03"))
import lib_inspection as lib  # noqa: E402

_STAMP = os.getpid() % 100000
INSTANCE = "integration-tests-%05d" % _STAMP
DECL = """schema: v1
instances:
  - id: %s
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 30 7 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % INSTANCE

SIGN_WHO = "human-scenario"          # not an agent role name
FOREIGN_PROJECT = "caller-foreign-proj"   # valid key shape, NOT the ticket's project
OWN_PROJECT = "sandbar"              # the fixture ticket's project (== target)
POLL_OPEN = 90
POLL_ERR = 20
POLL_CLOSE = 180
TERMINAL = "closed"


def run_ledger(instance_id):
    """This run's OWN ledger: the ledger dir accumulates one file per instance+period,
    and same-day runs can share a ticket id (t-shape ids are date-sequential), so the
    lib's ticket-id scan can return an EARLIER run's doc. The instance-stamped
    filename is unambiguous — read exactly that file."""
    base = (os.environ.get("SANDBAR_INSPECTION_DIR")
            or os.path.join(lib.TP_DIR, "out", "inspection"))
    try:
        names = [n for n in sorted(os.listdir(base))
                 if n.startswith("inspection-%s-" % instance_id)
                 and n.endswith(".json") and not n.endswith("-verdicts.json")]
    except OSError:
        return None
    if not names:
        return None
    try:
        with open(os.path.join(base, names[-1]), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ticket_state(tid):
    _proc, parsed = lib.run_client("ticket", {"op": "query", "ticket_id": tid})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        return None, None
    r = parsed.get("result") or {}
    return r, (r.get("snapshot") if isinstance(r.get("snapshot"), dict) else None)


def ticket_query_v2(tid):
    _proc, parsed = lib.run_client("ticket-query", {"ticket_id": tid})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        return None
    res = parsed.get("result")
    return res if isinstance(res, dict) else None


def poll(fn, timeout, interval):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return True, last
        time.sleep(interval)
    return False, last


def sign(tid, who, gate, decision="approve", note="", caller_project=None):
    """Workbench-style sign channel (client.py ticket op=sign -> Temporal sign signal).

    caller_project: None = inherit the ambient environment untouched; a string
    (INCLUDING "") injects SANDBAR_CALLER_PROJECT into the client subprocess only
    (spawn_env whitelist carries it; target/namespace red-line keys untouched).
    "" forces the undeclared identity even when the parent shell has an injected
    caller project (empty env = unset semantics in the identity chain)."""
    extra = None
    if caller_project is not None:
        extra = {"SANDBAR_CALLER_PROJECT": caller_project}
    _proc, parsed = lib.run_client("ticket", {
        "op": "sign", "ticket_id": tid,
        "input": {"who": who, "gate": gate, "decision": decision, "note": note},
    }, env=extra)
    return parsed


def snapshot_text(snap):
    """Every user-readable string on the ticket face (face values + timeline rows),
    lower-cased — the grey-box read surface for named refusals and record rows.
    Anchors substrings, never internal key names."""
    chunks = []

    def _walk(v):
        if isinstance(v, str):
            chunks.append(v.lower())
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _walk(x)
    _walk((snap or {}).get("face"))
    _walk((snap or {}).get("timeline"))
    # gate_error / blocked_reason are top-level snapshot keys, not face keys — the
    # user reads the refusal exactly there.
    _walk({"gate_error": (snap or {}).get("gate_error"),
           "blocked_reason": (snap or {}).get("blocked_reason")})
    return " ".join(chunks)


def main() -> int:
    lib.require_entry(lib.CLIENT, "client ticket face (sign channel)")
    lib.require_entry(lib.TRIGGER, "inspection trigger entry")

    failures = []
    private_queue = "suyou-insp-signid-%05d" % _STAMP
    os.environ["SANDBAR_TASK_QUEUE"] = private_queue
    workdir = tempfile.mkdtemp(prefix="sandbar-t26102416-signid-")
    decl = os.path.join(workdir, "decl.yaml")
    with open(decl, "w", encoding="utf-8") as f:
        f.write(DECL)
    clean = lib.clean_tree("sign-caller-identity")
    lib.seed_surface_bootstrap(INSTANCE, clean.base_sha)
    tid = None
    bench = None
    try:
        # Self-supply the plain-process bench FIRST (this scenario runs standalone,
        # no docker supply step): every later client/trigger/worker child targets
        # 17233. die_env inside this try still passes through the finally below, so
        # the bench is reaped on the ENV_FAIL path too.
        bench = lib.start_process_bench()
        # Bounded readiness wait: the bench endpoint can lag its start by a beat.
        parsed = None
        for _ in range(10):
            _proc, parsed = lib.run_client("schedule-list", {})
            if isinstance(parsed, dict) and parsed.get("ok") is True:
                break
            time.sleep(1.0)
        if not (isinstance(parsed, dict) and parsed.get("ok") is True):
            lib.die_env("cannot verify: temporalio missing or test stage unreachable "
                        "(schedule-list not ok: %r) — this journey needs a real stage "
                        "and a real ticket, no fake red, no fake green"
                        % (str(parsed)[:160]))
        with lib.StageWorker(private_queue):
            proc, trig = lib.run_trigger(
                ["trigger", "--instance", INSTANCE, "--decl-path", decl,
                 "--repo-root", clean.root])
            if not (isinstance(trig, dict) and trig.get("ok") is True):
                failures.append("trigger did not pass: %r | stderr=%s"
                                % (trig, (proc.stderr or "")[:200]))
            else:
                tid = str((trig.get("result") or {}).get("ticket_id") or "")
                if not tid:
                    failures.append("trigger receipt carried no ticket_id: %r"
                                    % (trig.get("result"),))
                lib.note_started_ticket(tid)

                def at_gate():
                    _r, snap = ticket_state(tid)
                    if not snap:
                        return None
                    if snap.get("stage") == "close" \
                            and snap.get("stage_state") == "awaiting-human":
                        return snap
                    return None
                ok_gate, snap = poll(at_gate, POLL_OPEN, 2)
                if not ok_gate:
                    _r, s = ticket_state(tid)
                    print("SNAP %s" % json.dumps(s or {}, ensure_ascii=False)[:1500],
                          flush=True)
                    failures.append("ticket %s did not reach close/awaiting-human in "
                                    "%ds (stage=%r state=%r) — human-gate leg broken"
                                    % (tid, POLL_OPEN, s and s.get("stage"),
                                       s and s.get("stage_state")))
                else:
                    q = ticket_query_v2(tid)
                    gate_id = (((q or {}).get("ticket") or {}).get("gate_id")
                               or "inspection-close")

                    # A. guard: declared FOREIGN caller refused by name, ticket stays
                    parsed_a = sign(tid, SIGN_WHO, gate_id,
                                    note="t261024-16 A foreign caller",
                                    caller_project=FOREIGN_PROJECT)
                    if not (isinstance(parsed_a, dict) and parsed_a.get("ok") is True):
                        failures.append("A: foreign-caller sign failed at the channel "
                                        "level (channel should deliver, workflow refuse):"
                                        " %r" % (parsed_a,))
                    else:
                        def a_refused():
                            _r, sA = ticket_state(tid)
                            if not sA:
                                return None
                            txt = snapshot_text(sA)
                            if "cross-project" in txt or FOREIGN_PROJECT in txt:
                                return txt
                            return None
                        okA, txtA = poll(a_refused, POLL_ERR, 2)
                        if not okA:
                            failures.append("A: foreign-caller sign not refused by name "
                                            "within %ds (refusal must name the "
                                            "cross-project rule)" % POLL_ERR)
                        def a_still_open():
                            _r, sA2 = ticket_state(tid)
                            return bool(sA2 and sA2.get("stage_state") == "awaiting-human"
                                        and sA2.get("status") != TERMINAL)
                        okA2, _ = poll(a_still_open, 2, 1)
                        if not okA2:
                            failures.append("A: foreign-caller sign left the gate open — "
                                            "ticket left awaiting-human or went terminal")

                    # B. guard: agent who + declared OWN project still refused by name
                    parsed_b = sign(tid, "developer", gate_id,
                                    note="t261024-16 B agent own project",
                                    caller_project=OWN_PROJECT)
                    if not (isinstance(parsed_b, dict) and parsed_b.get("ok") is True):
                        failures.append("B: agent sign failed at the channel level "
                                        "(channel should deliver, workflow refuse): %r"
                                        % (parsed_b,))
                    else:
                        def b_refused():
                            _r, sB = ticket_state(tid)
                            if not sB:
                                return None
                            txt = snapshot_text(sB)
                            return txt if "agent" in txt else None
                        okB, _ = poll(b_refused, POLL_ERR, 2)
                        if not okB:
                            _r, sB2 = ticket_state(tid)
                            failures.append("B: agent self-sign not refused by name "
                                            "(gate_error=%r) — the self-sign guard must "
                                            "survive the reorder regardless of caller "
                                            "identity"
                                            % (sB2 and sB2.get("gate_error"),))

                    # C. injected: absent who refused for its own reason (fail-closed,
                    # named), not masked by the cross-project text
                    parsed_c = sign(tid, "", gate_id,
                                    note="t261024-16 C absent who")
                    channel_c_refused = not (isinstance(parsed_c, dict)
                                             and parsed_c.get("ok") is True)
                    if channel_c_refused:
                        reason_c = json.dumps(parsed_c, ensure_ascii=False).lower()
                        if "who" not in reason_c:
                            failures.append("C: channel-level refusal does not name the "
                                            "missing who: %r" % (str(parsed_c)[:200],))
                    else:
                        def c_refused():
                            _r, sC = ticket_state(tid)
                            if not sC:
                                return None
                            txt = snapshot_text(sC)
                            return txt if "who" in txt else None
                        okC, _ = poll(c_refused, POLL_ERR, 2)
                        if not okC:
                            _r, sC2 = ticket_state(tid)
                            failures.append("C: absent-who sign not refused by name "
                                            "within %ds (gate_error=%r) — a malformed "
                                            "payload must be refused for its own reason, "
                                            "fail-closed"
                                            % (POLL_ERR, sC2 and sC2.get("gate_error")))
                    def c_not_terminal():
                        _r, sC3 = ticket_state(tid)
                        return bool(sC3 and sC3.get("status") != TERMINAL)
                    okC2, _ = poll(c_not_terminal, 2, 1)
                    if not okC2:
                        failures.append("C: absent-who sign closed the ticket — "
                                        "fail-closed broken")

                    # D. core: undeclared (bare) human sign accepted AND recorded.
                    # The empty-string override is deliberate: an ambient
                    # SANDBAR_CALLER_PROJECT (e.g. a lane-agent shell) must not
                    # silently upgrade this sub-case to declared-same-project —
                    # empty env = unset semantics in the identity chain, and the
                    # client cwd (repo tree) never derives, so the stamp lands on
                    # the undeclared sentinel exactly as the bare workbench does.
                    parsed_d = sign(tid, SIGN_WHO, gate_id,
                                    note="t261024-16 D bare human sign",
                                    caller_project="")
                    if not (isinstance(parsed_d, dict) and parsed_d.get("ok") is True):
                        failures.append("D: bare human sign refused at the channel: %r"
                                        % (parsed_d,))
                    else:
                        def closed():
                            _r, sD = ticket_state(tid)
                            return bool(sD and sD.get("status") == TERMINAL)
                        okD, _ = poll(closed, POLL_CLOSE, 3)
                        if not okD:
                            _r, sD2 = ticket_state(tid)
                            failures.append("D: bare human sign did not close the ticket "
                                            "in %ds (status=%r) — the undeclared-human "
                                            "channel must be record-and-allow at the sign "
                                            "gate"
                                            % (POLL_CLOSE, sD2 and sD2.get("status")))
                        else:
                            # Reader side: the closing receipts are read from the
                            # durable ledger (the offline reader's complete face:
                            # face + stage machine + timeline), not from the writer's
                            # ok receipt. The final ledger write completes before the
                            # workflow returns, but the read is still polled briefly.
                            def ledger_receipt():
                                led = run_ledger(INSTANCE)
                                if isinstance(led, dict) \
                                        and isinstance(led.get("human_gate"), dict) \
                                        and led["human_gate"].get("who") == SIGN_WHO:
                                    return led
                                return None
                            okL, ledger = poll(ledger_receipt, 30, 2)
                            if not okL:
                                led = run_ledger(INSTANCE)
                                failures.append("D: closing ledger receipt missing "
                                                "(out/inspection/, human_gate.who=%r) — "
                                                "audit chain broken; ledger keys=%r"
                                                % ((led or {}).get("human_gate"),
                                                   sorted(led)[:12] if isinstance(led, dict)
                                                   else led))
                            else:
                                low = json.dumps(ledger, ensure_ascii=False).lower()
                                if "undeclared" not in low:
                                    failures.append("D: the undeclared-caller sign left "
                                                    "no named record in the ledger "
                                                    "(face+timeline) — acceptance must be "
                                                    "recorded, not silent (record, not "
                                                    "refuse)")
    finally:
        if bench is not None:
            try:
                bench.down()
            except Exception as e:  # noqa: BLE001
                print("WARN: bench teardown: %s" % e, flush=True)

    if failures:
        for f in failures:
            print("FAIL_REASON %s" % f, flush=True)
        print("RESULT FAIL (%d)" % len(failures), flush=True)
        return 1
    print("RESULT PASS", flush=True)
    return 0


if __name__ == "__main__":
    lib.reexec_venv_if_missing()
    sys.exit(main())
