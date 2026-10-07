# t261008-03 — Zero-scenario conclusion (design_integration_tests)

## Why zero new executable scenarios

The deliverable is a rewrite of **one prose sentence** in `server/engine/README.md`
§18 (the three-strike ledger of the replay-guard delivery rule). There is no
executable face: no code path, no API, no state machine, no resource lifecycle
changes. The fault being fixed is a **factual citation error in human-read
operations documentation** (KI-201 attributed a wrong ticket id; fix tickets
t261005-14/-15 were mislabeled as frozen tickets), which misleads post-mortem
triage by a human reader.

Per the zero-scenario ruling (host order 20260903, precedent t260903-05), a
snapshot-type / prose document does not get a machine regression pin: a scenario
asserting the exact sentence bytes would rot on every lawful rewording of the
paragraph while guarding nothing the machine consumes. README §18 is not parsed
by any machine consumer — the scenario registry (`integration/run_scenarios.py`
SCENARIOS) and `docs/index.json` were checked; no parser reads this section.

## Intent-level duplication check

The global scenario registry was scanned for doc-fact-check intents: existing
source-text anchors (`source-text` label in `integration/test_anchors.json`)
guard engine faces and declared gate refusal copies — none covers the §18
ledger sentence. No existing scenario's intent overlaps this ticket's.

## Embedded self-check (reader-reproducible, not a registered scenario)

A reader can independently verify the fix's acceptance from the repo root:

```sh
# Reads the whole Three-strike ledger paragraph (it spans many lines, so the
# checks run paragraph-scoped, not line-scoped) and asserts every acceptance
# fact. Prints PASS/FAIL per check; any FAIL = fix incomplete or out of scope.
python3 - <<'EOF'
import re
t = open('server/engine/README.md').read()
ledger = re.search(r'Three-strike ledger.*?E9DAA05_LANDED_AT`?\)?\.?', t, re.S).group(0)
checks = {
    'KI-201 cites t261004-32 / 775bdb1 and the frozen set':
        all(s in ledger for s in ['KI-201','t261004-32','775bdb1','t261005-02','t261005-06','t261004-36']),
    'the wrong "t260908 fix" label is gone': 't260908 fix' not in ledger,
    't261005-14/-15 named as the guard-landing fix tickets':
        't261005-14' in ledger and 't261005-15' in ledger,
    'KI-203 covers the t261005-09 / -10 freeze':
        'KI-203' in ledger and 't261005-09' in ledger and 't261005-10' in ledger,
    'KI-212 entry unchanged and guard constants kept':
        all(s in ledger for s in ['KI-212','t261006-07','t261005-10','t261006-13','COUNTER_RESET_PATCH_ID','E9DAA05_LANDED_AT']),
}
for k, v in checks.items(): print(('PASS' if v else 'FAIL'), k)
raise SystemExit(0 if all(checks.values()) else 1)
EOF
```

All five checks must print PASS (exit 0) after implement. Any FAIL means the fix
is incomplete or drifted beyond the ticket's scope boundary.

Note: the dispatch text's acceptance line spells the ids `t260904-32` /
`t260904-36`; the KI ledger (KI-201, notes/debts/known-issues.md line 3445) and
the dev_lane.py CL-1 comment both say **t261004-32** / **t261004-36** — the
ledger is the ticket-designated source of truth, so the self-check above pins
the ledger spellings (review_plan gen0 condition #1).
