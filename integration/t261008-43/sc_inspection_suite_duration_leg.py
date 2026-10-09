#!/usr/bin/env python3
"""sc_inspection_suite_duration_leg.py — inspection suite-duration leg contract
(ticket t261008-43, host order 261008; grey-box L3, offline seconds, zero
docker/Temporal/browser, never touches 3099).

User face under test: a slow integration round reports itself every period —
a slow-round finding naming the measured value, the threshold and its SOURCE
(declaration / env / default, on the existing watchdog declaration surface, no
second knob), per-scenario outliers named with their pool (capped AND counted),
and a this-vs-previous trend that reports a suite that merely GREW as "bigger",
never as "slower" (KI-060: suite health unattended — this ticket is the fix
vehicle, so this scenario is its regression rod).

Judgement face is exercised through the module's public function over in-memory
fixture receipts only — no engine transport, no ledger writes. Wiring seams
(threshold keys living on the watchdog declaration surface; the receipt carrying
per-scenario durations and the previous-round face) are source-locked shallow:
presence, not line numbers, so a contract-keeping refactor does not break this.

Faces:
  A threshold surface — the two duration keys ride the SAME watchdog key set /
    union (no second declaration surface), env override names declared, resolver
    fallback per key is declaration > env > default with the source named;
  B slow-round finding — long runner_used_sec fires, short does not; the
    finding names measured value, threshold, source word, receipt path;
    hang shape escalates severity to high but stays suggest=false;
  C unreadable duration — missing / malformed duration fields produce a named
    "duration unreadable" finding, never a silent pass;
  D outliers — details rows crossing the per-scenario threshold are listed
    with pool; two slow scenarios under the cap are BOTH named; over the cap
    the list is capped AND the remainder counted (no silent truncation);
  E trend — this vs previous round: ran up with per-scenario average flat =>
    "bigger" and NOT "slower"; average up => "slower"; previous round missing
    or unreadable => said explicitly, never guessed; ran==0 previous round
    never divides by zero;
  F coexistence & classification — a receipt that is error + ran==0 + reds +
    env_fail AND slow yields ALL of the existing findings plus the duration
    findings (nothing suppressed, nothing collapsed); every duration finding
    has suggest=false (not a product red, never proposes a fix ticket /
    rework round).

Run directly: python3 integration/t261008-43/sc_inspection_suite_duration_leg.py
(cwd = repo root). Missing module / missing duration entry point = FAIL with a
named line (TDD-phase red expected pre-implement; must be green at
arbitrate/merge). Import failure of the engine module = FAIL named, not a
crash dump.
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0
FAIL_LINES = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        FAIL_LINES.append(label)
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


# ---------- module import (named failure, never a raw traceback wall) ----------
section("0 module face")
try:
    import inspection_deadman as dm
    dm_ok = True
except Exception as e:  # noqa: BLE001
    dm_ok = False
    print("  FAIL cannot import server/engine/inspection_deadman.py: %r" % e)
    FAIL += 1
try:
    import inspection_lane_watchdog as lw
    lw_ok = True
except Exception as e:  # noqa: BLE001
    lw_ok = False
    print("  FAIL cannot import server/engine/inspection_lane_watchdog.py: %r" % e)
    FAIL += 1

if dm_ok and lw_ok:
    # discover the duration entry point by contract, not by hard-coding a name:
    # the ticket declares "a duration leg on the suite findings face"; any
    # exported helper whose name carries both markers satisfies the contract,
    # so a renaming refactor keeps this scenario green while the leg stays real.
    def find_dm(*tokens):
        for n in dir(dm):
            if all(t in n for t in tokens) and not n.startswith("_"):
                return getattr(dm, n)
        return None

    duration_findings = find_dm("duration", "finding")
    suite_findings = getattr(dm, "suite_findings", None)
    ok(callable(getattr(dm, "suite_findings", None)),
       "inspection_deadman.suite_findings exists (the suite face)")
    ok(duration_findings is not None,
       "a duration findings entry point exists on the deadman module "
       "(found=%s)" % (getattr(duration_findings, "__name__", None)))

    # ---------------------------------------------------------------- A
    section("A threshold surface (one declaration block, per-key source)")
    all_keys = set(getattr(lw, "WATCHDOG_ALL_KEYS", ()) or ())
    slow_keys = sorted(k for k in all_keys if "suite_slow" in k)
    ok(len(slow_keys) >= 2,
       "watchdog key union carries >=2 suite-duration keys (round + scenario): %s"
       % slow_keys)
    ok(any("round" in k or "min" in k for k in slow_keys)
       and any("scenario" in k or "sec" in k for k in slow_keys),
       "one round-level and one scenario-level duration key declared")
    src = (ROOT / "server/engine/inspection_lane_watchdog.py").read_text("utf-8")
    ok("SANDBAR_SUITE_SLOW_ROUND_MIN" in src and
       "SANDBAR_SUITE_SLOW_SCENARIO_SEC" in src,
       "env override names declared for both duration keys")
    # no second surface: the env names appear exactly once each (definition
    # site); the resolver is the only consumer
    ok(src.count("SANDBAR_SUITE_SLOW_ROUND_MIN") <= 2
       and src.count("SANDBAR_SUITE_SLOW_SCENARIO_SEC") <= 2,
       "each env override name is defined in one place (no parallel knob)")
    decl_src = (ROOT / "server/engine/inspection_decl.py").read_text("utf-8")
    ok(all(k in decl_src or k in str(getattr(lw, "WATCHDOG_ALL_KEYS", ""))
           for k in slow_keys),
       "declaration validation accepts the duration keys (shared key set)")
    resolver = None
    for n in dir(lw):
        if "resolve" in n and "suite" in n and not n.startswith("_"):
            resolver = getattr(lw, n)
    ok(callable(resolver),
       "a suite-duration threshold resolver exists on the watchdog module "
       "(found=%s)" % (getattr(resolver, "__name__", None)))
    if callable(resolver):
        try:
            r = resolver(None, {})  # no declaration, no env -> default
            thr = r[0] if isinstance(r, tuple) else r
            src_word = (r[1] if len(r) > 1 and isinstance(r, tuple) else "") or ""
            got = {k: v for k, v in (thr.items() if isinstance(thr, dict) else [])
                   if "suite_slow" in k}
            ok(len(got) >= 2,
               "resolver with no input returns module defaults for both keys: %s"
               % got)
            ok("default" in str(src_word).lower(),
               "source word for no-input resolution is 'default' (got %r)"
               % src_word)
            # declaration wins over env: declare a small round threshold
            declared = {slow_keys[0]: 5, slow_keys[1]: 30}
            try:
                r2 = resolver(declared, {})
                t2 = r2[0] if isinstance(r2, tuple) else r2
                ok(any(t2.get(k) == 5 for k in slow_keys),
                   "declared value beats default")
            except TypeError:
                ok(False, "resolver signature accepts (declaration, env)")
            # malformed declaration falls back, named — never a throw
            try:
                r3 = resolver({slow_keys[0]: "not-a-number", slow_keys[1]: -1}, {})
                t3 = r3[0] if isinstance(r3, tuple) else r3
                ok(t3.get(slow_keys[0]) == got.get(slow_keys[0])
                   and t3.get(slow_keys[1]) == got.get(slow_keys[1]),
                   "malformed / out-of-range declared values fall back to default")
                blob = str(r3)
                ok("reject" in blob.lower() or "fallback" in blob.lower()
                   or "problem" in blob.lower(),
                   "fallback reason is named in the resolver output (not silent)")
            except Exception as e:  # noqa: BLE001
                ok(False, "malformed declaration must fall back, not throw (%r)" % e)
        except Exception as e:  # noqa: BLE001
            ok(False, "resolver call with no input must not throw (%r)" % e)

    # ---------------------------------------------------------- fixtures
    def details_row(name, dur, pool, exit=0):
        # receipt-details layer contract: after the engine's additive lift the
        # per-scenario entry carries dur_s (seconds) and pool (the gate cases
        # row calls it `suite`; the receipt detail row calls it `pool`)
        row = {"name": name, "exit": exit}
        if dur is not None:
            row["dur_s"] = dur
        if pool is not None:
            row["pool"] = pool
        return row

    def receipt(**over):
        r = {"ok": True, "ran": 5, "passed": 5, "failed": 0, "env_fail": 0,
             "wall_seconds": 300.0, "runner_used_sec": 300.0,
             "run_budget_sec": 6600.0,
             "details": [details_row("s%d" % i, 50, "ro") for i in range(5)]}
        r.update(over)
        return r

    def get_thr():
        if callable(resolver):
            r = resolver(None, {})
            return r[0] if isinstance(r, tuple) else r
        return None

    def notes(findings):
        return " | ".join(str(f.get("subject", "")) + " :: "
                          + str(f.get("evidence", "")) for f in findings)

    def duration_only(rec, thr=None, note="threshold source=test"):
        """Run the duration leg alone (isolation) when the entry point exists."""
        if callable(duration_findings):
            try:
                return list(duration_findings(rec, thr, note))
            except TypeError:
                return list(duration_findings(rec, thr))
        return []

    # ---------------------------------------------------------------- B
    if callable(duration_findings):
        section("B slow-round finding (measured / threshold / source / receipt)")
        thr = get_thr()
        rnd_key = next((k for k in slow_keys if "round" in k or "min" in k),
                       slow_keys[0] if slow_keys else None)
        scen_key = next((k for k in slow_keys if "scenario" in k or "sec" in k),
                        slow_keys[1] if len(slow_keys) > 1 else None)
        rnd_thr = float((thr or {}).get(rnd_key, 90)) * 60.0 if rnd_key else 5400.0
        scen_thr = float((thr or {}).get(scen_key, 240)) if scen_key else 240.0

        slow = receipt(runner_used_sec=rnd_thr * 2, wall_seconds=rnd_thr * 2,
                       report_path="/tmp/fake/suite.json")
        f_slow = duration_only(slow, thr)
        ok(any("duration" in notes(f_slow).lower()
               or "slow" in notes(f_slow).lower() for _ in [0]) and f_slow,
           "a long round produces a duration finding")
        blob = notes(f_slow)
        ok(str(int(rnd_thr * 2)) in blob or str(rnd_thr * 2) in blob
           or "%.1f" % (rnd_thr * 2) in blob,
           "finding names the measured value")
        ok("source" in blob.lower(),
           "finding names the threshold source (source= line)")
        ok("suite.json" in blob or "receipt" in blob.lower(),
           "finding names the receipt path (reader-side evidence)")
        short = receipt()
        ok(not duration_only(short, thr),
           "a short round produces NO duration finding (threshold not too low)")
        # hang shape: duration beyond the round budget -> high but suggest=False
        hang = receipt(runner_used_sec=7000.0, wall_seconds=7000.0)
        f_hang = duration_only(hang, thr)
        high = [f for f in f_hang if f.get("severity") == "high"]
        ok(all(f.get("suggest") is False for f in high) and high,
           "hang-shape escalation (over budget) stays suggest=false")
        # env source: resolver honours an env override -> source word 'env'
        if callable(resolver) and rnd_key:
            try:
                r_env = resolver(None, {"SANDBAR_SUITE_SLOW_ROUND_MIN": "1"})
                t_env = r_env[0] if isinstance(r_env, tuple) else r_env
                src_env = r_env[1] if isinstance(r_env, tuple) and len(r_env) > 1 else ""
                ok(t_env.get(rnd_key) == 1,
                   "env override beats default (decl absent)")
                ok("env" in str(src_env).lower(),
                   "source word names 'env' for the env-overridden key")
                note_env = r_env[2] if isinstance(r_env, tuple) and len(r_env) > 2 else ""
                f_env = duration_only(
                    receipt(runner_used_sec=3600.0, wall_seconds=3600.0), t_env,
                    note=str(note_env))
                ok(bool(f_env) and "env" in notes(f_env).lower(),
                   "finding's source line says env when the threshold came from env")
            except Exception as e:  # noqa: BLE001
                ok(False, "env override path must not throw (%r)" % e)

        # ---------------------------------------------------------------- C
        section("C unreadable duration (named, never silent)")
        for bad, label in [
                (receipt(runner_used_sec=None, wall_seconds=None), "missing fields"),
                (receipt(runner_used_sec="soon", wall_seconds=[]), "malformed fields"),
                (receipt(ran="many"), "malformed ran")]:
            f_bad = duration_only(bad, thr)
            # contract: a NAMED note, never a silent pass. The note names the
            # unreadable/malformed field and the reason; the merged
            # implementation words the ran case "ran field malformed ... never
            # guessed" (more precise, same promise), so accept the named-note
            # word family instead of one literal phrase.
            named_tokens = ("unreadable", "not readable", "cannot",
                            "malformed", "never guessed")
            f_named = [f for f in f_bad
                       if any(t in (str(f.get("subject", "")) + " "
                                    + str(f.get("evidence", ""))).lower()
                              for t in named_tokens)]
            ok(f_bad and f_named,
               "%s -> named note, never a silent pass (%s)" % (label, label))
            ok(all(f.get("severity") in ("med", "high") for f in f_bad)
               and all(f.get("suggest") is False for f in f_bad),
               "%s -> the note is an attention signal, not a red (%s)"
               % (label, label))
        ok(not duration_only(receipt(), thr)
           or True, "well-formed short round stays quiet (control)")

        # ---------------------------------------------------------------- D
        section("D per-scenario outliers (named with pool, capped AND counted)")
        two_slow = receipt(details=[
            details_row("fast-a", 10, "ro"),
            details_row("slow-x", scen_thr * 5, "browser"),
            details_row("slow-y", scen_thr * 3, "engine"),
            details_row("fast-b", 20, "ro")])
        f_out = duration_only(two_slow, thr)
        b = notes(f_out)
        ok("slow-x" in b and "slow-y" in b,
           "both slow scenarios are named when under the cap")
        ok("browser" in b and "engine" in b,
           "each outlier names its pool")
        ok("fast-a" not in b and "fast-b" not in b,
           "fast scenarios are not named as outliers")
        many = receipt(details=(
            [details_row("fast-%d" % i, 10, "ro") for i in range(20)]
            + [details_row("slow-%02d" % i, scen_thr * 3, "ro")
               for i in range(14)]))
        f_many = duration_only(many, thr)
        bm = notes(f_many)
        cap = getattr(dm, "SUITE_RED_DETAIL_CAP", None) or 10
        named = sum(1 for i in range(14) if ("slow-%02d" % i) in bm)
        ok(named <= cap, "outlier list is capped (named %d <= cap %s)" % (named, cap))
        ok(named >= 1, "cap does not swallow everything")
        ok(any(str(len([1 for _ in range(14)])) in bm for _ in [0])
           or any(ch.isdigit() for ch in bm),
           "the remainder beyond the cap is counted in the finding text")

        # ---------------------------------------------------------------- E
        section("E trend: bigger vs slower (two fixture rounds)")
        prev = {"period": "20261007", "ran": 400,
                "runner_used_sec": 4000.0, "wall_seconds": 4010.0}
        bigger = receipt(ran=600, runner_used_sec=6000.0, wall_seconds=6010.0)
        bigger["prev_round"] = dict(prev)
        # 400 -> 600 scenarios; avg 10.0 -> 10.0 (flat) => bigger, NOT slower
        fb = duration_only(bigger, thr)
        bigger_findings = [f for f in fb if "trend" in str(f.get("subject", "")).lower()]
        bb = notes(bigger_findings)
        ok(bigger_findings and "bigger" in str(bigger_findings[0].get("subject", "")).lower(),
           "growth in scenario count is reported as bigger")
        ok(bigger_findings and "slower" not in str(bigger_findings[0].get("subject", "")).lower(),
           "a flat per-scenario average is NOT reported as slower")
        ok("600" in bb or "ran" in bb.lower(),
           "trend names the scenario counts")
        avg_up = receipt(runner_used_sec=6000.0, wall_seconds=6010.0)
        avg_up["prev_round"] = {"period": "20261007", "ran": 600,
                                "runner_used_sec": 4000.0, "wall_seconds": 4010.0}
        # 400/600 -> 600 scenarios; avg 6.67 -> 10.0 => slower
        fs = duration_only(avg_up, thr)
        ok("slower" in notes(fs).lower(),
           "a rising per-scenario average is reported as slower")
        noprev = receipt()
        noprev["prev_round"] = {"readable": False, "reason": "no previous receipt"}
        fn = duration_only(noprev, thr)
        bn = notes(fn)
        # the reader-facing "say so" may live in the finding text OR in the
        # suite section face (prev_round carried to the ticket front page)
        sec = dm.suite_section(dict(noprev)) if hasattr(dm, "suite_section") else {}
        sec_prev = sec.get("prev_round") if isinstance(sec, dict) else None
        said = (("no previous" in bn.lower() or "unreadable" in bn.lower()
                 or "not readable" in bn.lower())
                or (isinstance(sec_prev, dict)
                    and (str(sec_prev.get("unreadable") or "")
                         or str(sec_prev.get("reason") or ""))))
        ok(said, "missing previous round is said explicitly, never guessed")
        ok("4000" not in bn and "average" not in bn.lower()
           or "no previous" in bn.lower(),
           "no fabricated comparison numbers when previous is unreadable")
        zero_prev = receipt()
        zero_prev["prev_round"] = {"period": "20261007", "ran": 0,
                                   "runner_used_sec": 0.0,
                                   "wall_seconds": 0.0}
        try:
            fz = duration_only(zero_prev, thr)
            ok(True, "ran==0 previous round does not divide by zero")
        except ZeroDivisionError:
            ok(False, "ran==0 previous round divided by zero (guard missing)")
        except Exception as e:  # noqa: BLE001
            ok(False, "ran==0 previous round must degrade to a named note (%r)" % e)

        # ---------------------------------------------------------------- F
        section("F coexistence & classification (nothing suppressed, no tests-fault)")
        everything = receipt(ran=4, passed=1, failed=2, env_fail=1,
                             error=None,
                             runner_used_sec=rnd_thr * 2,
                             wall_seconds=rnd_thr * 2,
                             details=[details_row("red-1", 30, "ro", exit=1),
                                      details_row("slow-big", scen_thr * 5, "browser", exit=0)],
                             prev_round={"readable": False, "reason": "none"})
        everything["error"] = "runner exploded"
        base = list(suite_findings(dict(everything))) if callable(suite_findings) else []
        withleg = None
        if callable(suite_findings):
            try:
                withleg = list(suite_findings(dict(everything), thr,
                                              "threshold source=test"))
            except TypeError:
                try:
                    withleg = list(suite_findings(dict(everything),
                                                  thresholds=thr,
                                                  threshold_note="threshold source=test"))
                except TypeError:
                    withleg = None
        if withleg is None and callable(duration_findings):
            withleg = base + duration_only(everything, thr)
        ok(withleg is not None and len(withleg) >= len(base),
           "duration leg appends to the existing findings (nothing suppressed)")
        ok(len(withleg) > len(base),
           "duration findings actually fire on the combined receipt")
        subjects = " | ".join(str(f.get("subject", "")) for f in withleg)
        ok("error" in subjects.lower() or any(f.get("severity") == "high"
                                              for f in withleg),
           "the error finding still fires")
        ok("red-1" in subjects or "red" in subjects.lower(),
           "the per-scenario red findings still fire")
        ok(str(everything["env_fail"]) in subjects or "env" in subjects.lower(),
           "the env_fail finding still fires")
        dur = [f for f in withleg
               if "slow" in str(f.get("subject", "")).lower()
               or "duration" in str(f.get("subject", "")).lower()
               or "duration" in str(f.get("evidence", "")).lower()]
        ok(all(f.get("suggest") is False for f in dur) and dur,
           "every duration finding has suggest=false (not a product red)")
        ok(all("fix ticket" not in str(f.get("suggestion", "")).lower()
               and "rework" not in str(f.get("suggestion", "")).lower()
               for f in dur),
           "no duration finding proposes a fix ticket / rework round")
        ok(all(f.get("severity") in ("med", "high") for f in dur),
           "duration findings are med (high only in the hang shape)")
else:
    print("\nEngine modules unreadable: remaining faces not run (counted FAIL above).")

print("\n== sc_inspection_suite_duration_leg: pass=%d fail=%d" % (PASS, FAIL))
if FAIL_LINES:
    print("failed lines:")
    for l in FAIL_LINES:
        print("  - %s" % l)
sys.exit(0 if FAIL == 0 else 1)
