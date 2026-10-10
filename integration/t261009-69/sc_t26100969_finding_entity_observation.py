#!/usr/bin/env python3
"""sc_t26100969_finding_entity_observation.py — a finding is an entity in the
ledger and its sightings are observations (ticket t261009-69, develop-buffer
Phase 2 P2-f first half).

Run directly:
python3 integration/t261009-69/sc_t26100969_finding_entity_observation.py
(cwd = repo root).

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser,
never touches 3099/7233. Every ledger lives in a temp dir; the real project
store is never written.

The user-perceivable contract this entry owns (t261009-69 spec (1)-(5)):

  A  ID WIDENING WITHOUT RENUMBERING SEMANTICS — mint_finding_id returns
     SIXTEEN hex characters; the same content mints the same id across
     periods; a wording-only change (why / suggestion / severity / quote)
     keeps the id (identity is rule + object locations, never wording);
     evidence order and path cosmetics do not change the id.

  B  ENTITY + OBSERVATION ARE TWO RECORDS ON DISK — a sighting writes ONE
     finding entity row (content-minted id) and ONE observation row keyed
     (finding, period) with NO id of its own; re-seeing the same finding in
     a later period appends a NEW OBSERVATION and never a second entity
     (duplicate suppression is visible in the notes, not silent).

  C  "HOW LONG HAS THIS BEEN OPEN" IS A QUERY — finding_history answers,
     from the stored rows alone: first seen, how many periods, last sighting
     with its verification outcome; proof is read back from the ledger files
     on disk, never from a return value alone.

  D  DEGRADE AND NAME, NEVER SILENT — a corrupt ledger line is skipped but
     COUNTED (corrupt_lines) and never raises; the good rows survive; an
     absent ledger is a named empty (available / reason), never fabricated
     history; a sighting whose entity row is missing stays VISIBLE
     (orphan_sightings); a finding whose verification FAILED this period
     still gets an observation naming the failure (downgrade-and-name kept).

  E  LEGACY 8-HEX IDS KEEP RESOLVING — an old stored id resolves on the read
     face by prefix (id_resolution names the rule); history is never
     renumbered by the widening.

Anchors are the public contract names of inspection_review_ledger /
inspection_inspect (append_findings, append_observations, observation_keys,
finding_history, mint_finding_id, legacy_id_matches), never line numbers —
a contract-preserving refactor stays green. Intent split: review-ledger
rotation / skip / stub / coverage faces belong to t261006-12-review-ledger-
rotation (not re-asserted here); the id-recipe internals and per-rule
finding truth tables belong to developer L1; produce-mode doc face is
t260925-01; the relation kind "originates from a finding" is this ticket's
named non-goal. Engine modules unimportable = ENV_FAIL exit 2.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


try:
    import inspection_inspect as insp  # noqa: E402
    import inspection_review_ledger as rev  # noqa: E402
except Exception as e:  # engine tree absent/unimportable
    print("ENV_FAIL: engine inspection modules unimportable (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(2)

missing = [n for n in ("append_findings", "append_observations",
                       "observation_keys", "finding_history",
                       "load_jsonl_rows")
           if not hasattr(rev, n)]
if missing:
    print("FAIL missing contract faces in inspection_review_ledger: %s"
          % ", ".join(missing))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, len(missing)))
    sys.exit(1)


def jsonl_rows(path):
    """Reader-side truth: parse the file on disk ourselves, never trust a
    return receipt (reader-side acceptance discipline)."""
    p = Path(path)
    if not p.exists():
        return None  # absent is meaningful
    out = []
    for line in p.read_text("utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except ValueError:
            out.append({"__corrupt__": True})
    return out


def a_finding(subject="Docs index drifts from design",
              path="docs/a.md", line=3):
    return {
        "subject": subject,
        "why": "the index misses the section added last week",
        "suggestion": "regenerate the index",
        "severity": "med",
        "evidence": [{"path": path, "line": line,
                      "quote": "see the section"}],
    }


PERIOD1, PERIOD2, PERIOD3 = "20261001", "20261002", "20261003"

tmp = Path(tempfile.mkdtemp(prefix="sc_t26100969_"))
try:
    # ---------- A id widening ----------
    section("A id widened to 16 hex; identity is content, never wording")
    fid = insp.mint_finding_id(a_finding())
    ok(bool(re.fullmatch(r"[0-9a-f]{16}", fid)),
       "mint returns 16 hex (got %r)" % (fid[:20] if fid else fid))

    f_worded = a_finding()
    f_worded["why"] = "re-worded entirely"
    f_worded["suggestion"] = "different words"
    f_worded["severity"] = "high"
    f_worded["evidence"][0]["quote"] = "different quote text"
    ok(insp.mint_finding_id(f_worded) == fid,
       "wording-only change (why/suggestion/severity/quote) keeps the id")

    f_order = a_finding()
    f_order["evidence"].append({"path": "docs/b.md", "line": 9, "quote": "q"})
    f_rev = a_finding()
    f_rev["evidence"] = list(reversed(f_order["evidence"]))
    ok(insp.mint_finding_id(f_order) == insp.mint_finding_id(f_rev),
       "evidence ORDER does not change the id (sorted locations)")

    f_win = a_finding(path="docs\\sub\\c.md")
    f_unix = a_finding(path="docs/sub/c.md")
    ok(insp.mint_finding_id(f_win) == insp.mint_finding_id(f_unix),
       "path cosmetics (backslash) do not change the id")

    f_other = a_finding(subject="A different problem altogether")
    ok(insp.mint_finding_id(f_other) != fid,
       "a different rule+object mints a DIFFERENT id")

    # ---------- B entity + observation are two records ----------
    section("B entity row + observation row on disk; re-seeing never duplicates")
    led = tmp / "ledgers"
    led.mkdir(parents=True, exist_ok=True)
    fpath, opath = led / "findings.jsonl", led / "observations.jsonl"

    ok(jsonl_rows(fpath) is None, "no entity ledger before the first sighting")

    # malformed control: a finding with NO minted id is named, never written
    n_bad = rev.append_findings(tmp / "bad.jsonl", [{"subject": "no id here"}])
    ok(n_bad.get("entity_rows_malformed") == 1 and
       jsonl_rows(tmp / "bad.jsonl") is None,
       "an id-less finding is refused BY NAME, never written as an entity")

    f1 = a_finding()
    id1 = insp.mint_finding_id(f1)
    f1["id"] = id1  # the caller mints (with_ids); the entity face stores it
    n1 = rev.append_findings(fpath, [f1])
    o1 = rev.append_observations(
        opath, [{"finding": id1, "period": PERIOD1,
                 "verification": "verified"}],
        known_keys=rev.observation_keys(jsonl_rows(opath) or []))

    ent = jsonl_rows(fpath)
    obs = jsonl_rows(opath) or []
    ok(n1.get("ledger_written") == 1 and ent and len(ent) == 1,
       "first sighting writes exactly ONE entity row")
    ok(ent and ent[0].get("id") == id1,
       "the entity row carries the content-minted id")
    ok(o1.get("ledger_written") == 1 and len(obs) == 1,
       "the sighting writes exactly ONE observation row")
    ok(obs and "id" not in obs[0] and obs[0].get("finding") == id1
       and obs[0].get("period") == PERIOD1,
       "observation has NO id; its key is (finding, period)")
    ok(obs and obs[0].get("verification") == "verified",
       "the observation carries what was seen this period")

    # re-see the same content in a later period (re-graded, same identity)
    f2 = a_finding()
    f2["severity"] = "high"
    f2["id"] = insp.mint_finding_id(f2)  # same content -> same id
    ok(f2["id"] == id1, "a re-graded sighting mints the SAME id")
    known = rev.observation_keys(obs)
    n2 = rev.append_findings_ex(fpath, [f2], existing_ids={id1})
    o2 = rev.append_observations(
        opath, [{"finding": id1, "period": PERIOD2,
                 "verification": "verified"}], known_keys=known)
    ent2 = jsonl_rows(fpath)
    obs2 = jsonl_rows(opath) or []
    ok(n2.get("entity_duplicates_skipped") == 1 and len(ent2) == 1,
       "re-seeing appends NO second entity (duplicate skipped, NAMED)")
    ok(o2.get("ledger_written") == 1 and len(obs2) == 2,
       "re-seeing appends a NEW observation for the new period")
    ok((id1, PERIOD2) in rev.observation_keys(obs2),
       "the new sighting keys on (finding, period)")

    # a duplicate (finding, period) is refused with a named count
    # (the caller passes the keys it just loaded — the declared contract)
    o2b = rev.append_observations(
        opath, [{"finding": id1, "period": PERIOD2,
                 "verification": "verified"}],
        known_keys=rev.observation_keys(jsonl_rows(opath) or []))
    ok(o2b.get("observation_duplicates_skipped") == 1 and
       len(jsonl_rows(opath) or []) == 2,
       "the same (finding, period) never writes twice (named skip)")

    # unverified this period still gets an observation that NAMES the failure
    o3 = rev.append_observations(
        opath, [{"finding": id1, "period": PERIOD3,
                 "verification": "downgraded",
                 "verification_note":
                     "the quoted line is no longer in the file"}],
        known_keys=rev.observation_keys(jsonl_rows(opath) or []))
    obs3 = jsonl_rows(opath) or []
    last = obs3[-1] if obs3 else {}
    ok(o3.get("ledger_written") == 1 and len(obs3) == 3,
       "an unverified sighting STILL gets its observation")
    ok(last.get("period") == PERIOD3 and
       last.get("verification") == "downgraded" and
       bool(last.get("verification_note")),
       "the failed verification is NAMED on the observation, not dropped")

    # ---------- C the query, not the re-derivation ----------
    section("C first seen / periods seen / last sighting answered FROM the ledger")
    h = rev.finding_history(fpath, opath, id1)
    ok(h.get("available") is True, "the history query answers available")
    ok(h.get("first_seen") == PERIOD1,
       "first seen answered from the ledger (%s)" % h.get("first_seen"))
    ok(h.get("periods_seen_count") == 3 and
       h.get("periods_seen") == [PERIOD1, PERIOD2, PERIOD3],
       "periods seen = the three periods, counted by query")
    ok(isinstance(h.get("last_sighting"), dict) and
       h["last_sighting"].get("period") == PERIOD3 and
       h["last_sighting"].get("verification") == "downgraded",
       "last sighting carries the newest period AND its verification outcome")

    # reader-side proof: the answer is DERIVABLE FROM THE FILES ALONE
    files_only = [r for r in (jsonl_rows(opath) or [])
                  if r.get("finding") == id1]
    ok(sorted(r["period"] for r in files_only) == [PERIOD1, PERIOD2, PERIOD3],
       "the same answer is reconstructible from the raw ledger files "
       "(a query over rows, not a recomputation from period reports)")

    # ---------- D degrade and name ----------
    section("D malformed/absent inputs degrade and NAME, never silently lie")
    broken = tmp / "broken"
    broken.mkdir()
    (broken / "findings.jsonl").write_text(
        json.dumps({"id": "a" * 16, "period": PERIOD1}) + "\n"
        + "{not json at all\n"
        + json.dumps({"id": "b" * 16, "period": PERIOD2}) + "\n",
        encoding="utf-8")
    brows, bnotes = rev.load_jsonl_rows(broken / "findings.jsonl", "x")
    ok(bnotes.get("corrupt_lines") == 1 and len(brows) == 2,
       "a corrupt line is dropped AND counted (corrupt_lines=1); the two "
       "good rows survive")
    ok(rev.finding_history(broken / "no_such_dir" / "findings.jsonl",
                           broken / "no_such_dir" / "observations.jsonl",
                           "c" * 16).get("available") is False,
       "an absent ledger answers not-available, never raises and never "
       "fabricates history")
    h_absent = rev.finding_history(tmp / "none.jsonl", tmp / "none2.jsonl",
                                   "a" * 16)
    ok(bool(h_absent.get("reason")) or
       bool(h_absent.get("notes")),
       "the not-available answer NAMES why (a reason or a ledger note "
       "travels in the payload)")

    # an observation whose entity row is missing stays visible
    orphan = tmp / "orphan"
    orphan.mkdir()
    (orphan / "observations.jsonl").write_text(
        json.dumps({"finding": "d" * 16, "period": PERIOD1,
                    "verification": "verified"}) + "\n", encoding="utf-8")
    (orphan / "findings.jsonl").write_text("", encoding="utf-8")
    h_orph = rev.finding_history(orphan / "findings.jsonl",
                                 orphan / "observations.jsonl", "e" * 16)
    ok(True, "orphan probe: entity-less ledger queried without raising")
    ok(isinstance(h_orph.get("orphan_sightings"), list),
       "orphan sightings have a declared place in the read face's answer")

    # ---------- E legacy ids ----------
    section("E widening does not renumber history")
    old_id = hashlib.sha256(b"legacy finding").hexdigest()[:8]
    ok(insp.legacy_id_matches(old_id, old_id + fid[:8]) or
       insp.legacy_id_matches(old_id, fid),
       "the prefix rule resolves an old 8-hex stored id to the widened id")
    legacy = tmp / "legacy"
    legacy.mkdir()
    (legacy / "findings.jsonl").write_text(
        json.dumps({"id": old_id, "subject": "legacy finding"}) + "\n",
        encoding="utf-8")
    (legacy / "observations.jsonl").write_text(
        json.dumps({"finding": old_id, "period": "20260901",
                    "verification": "verified", "at": 1791500000000}) + "\n",
        encoding="utf-8")
    h_legacy = rev.finding_history(legacy / "findings.jsonl",
                                   legacy / "observations.jsonl", old_id)
    ok(h_legacy.get("available") is True and
       h_legacy.get("first_seen") == "20260901",
       "a stored 8-hex id still resolves to its finding and its history "
       "(history is not renumbered by the widening)")
    ok("legacy" in str(h_legacy.get("id_resolution", "")) or
       h_legacy.get("id_resolution") == "exact",
       "the receipt says HOW the id was matched (id_resolution: %s)"
       % h_legacy.get("id_resolution"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
