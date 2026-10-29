# t261030-05 — reproduction of the two line-round verdicts that moved with the round

Both cases were reported as load-coupled: they failed in a full round on the develop
line (99c65939) and passed alone on the same tree. Neither cause is machine load. Both
are deterministic once the round's own tree content is put back around the case.

## 1. `t261004-22-d2b-carrier-wait-contract` (in-round `pass=8 fail=6`)

Read the run header first: `~/.sandbar/projects/sandbar/ledger/scenario-runs.jsonl`
carries the failing case's own tail (`failed_detail`). The receipt shows legs B and C
ending in `1 passed` — the engine case saw REAL process enumeration, so the fixture's
PATH stubs were bypassed.

Cause: ticket t261029-38 (landed on the develop line, commit 8d38ece0) changed
`integration/tools/sweep_tmp_fixtures.py` to exec the probes by absolute path
(`/usr/bin/pgrep`, `/usr/sbin/lsof`) through `probe_bin()`, and added a one-pass
`lsof -nP -w -F pcn` to `live_carriers`. A stub directory on PATH cannot shadow an
absolute path, so both fault legs fabricated nothing and the case passed both of them.

Reproduce offline, without a round and without load:

```sh
git -C <repo> archive develop | tar -x -C /tmp/t261030-05-repro
ln -sfn <repo>/server/engine/.venv /tmp/t261030-05-repro/server/engine/.venv
cp <repo>/integration/t261004-22/sc_d2b_carrier_wait_contract.py \
   /tmp/t261030-05-repro/integration/t261004-22/
cd /tmp/t261030-05-repro
/Users/user/Documents/sandbar/server/engine/.venv/bin/python \
  integration/t261004-22/sc_d2b_carrier_wait_contract.py
```

The old fixture reports `summary: pass=8 fail=6` (B3/B4, C1..C4 red) — the same numbers
the round printed. The fixed fixture reports `summary: pass=19 fail=0` on the same tree.

Fix: the fault is injected at the OS boundary instead of through PATH. A
`sitecustomize` module on the pytest child's `PYTHONPATH` answers every `pgrep`/`lsof`
exec, whatever path or argument form the probe face uses, and appends each exec to a
marker file. An injection that intercepts nothing books the named state
`probe_injection_ineffective` and judges no product leg, so a changed probe face can
never again be read as a product verdict.

## 2. `t260907-04-naming-grep-assert` (in-round `SUMMARY pass=6 fail=1`)

Cause: the guard's pattern matched the retired-name prefix inside the sister project's
literal `project-content-integ-run-` (the retired name as a substring of another identifier),
which ticket t261029-38 brought into
`integration/tools/tmp_leak_receipt.py`, its tests and `integration/t261029-38/`
(six lines). The verdict followed unrelated tree content, not load.

Reproduce: export the develop tree as above and run
`python3 integration/t260907-04/sc_naming_grep_assert.py` — it reports
`SUMMARY pass=6 fail=1` and names the six lines. With the whole-token boundary it
reports `SUMMARY pass=11 fail=0`.

## What was NOT load-sensitive

Neither case moved under a competing CPU/IO load (16 busy loops + temp-dir churn, load
average 16 -> 36): the d2b case went 59.6 s -> 66.8 s and stayed green, the naming case
1.0 s -> 2.1 s and stayed green. Numbers do not decide either verdict any more.
