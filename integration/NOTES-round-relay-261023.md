# 261023 — a green round that never got a run row (open finding)

## What was observed

Two consecutive line rounds finished with `fail=0` (729 ran / 705 pass / 24 env_fail)
and wrote their face (`rounds/run-*/face.json`, state=done) and their report, but the
project ledger `~/.sandbar/projects/sandbar/ledger/scenario-runs.jsonl` gained **no row**
for them:

- `run-01M5KKMN497AXDJRP317XQGBSQ` (revision f3d1c2d4) — face done, 0 fail, no row.
- the round before it — same shape.

Without a run row the engine cannot cite a run, so it cannot mint a certification
(`run id missing` is a hard refusal by design), which is why the line stayed frozen
while the suite was already green.

## Where the pieces live

- `integration/line_round_runner.py:575` reads the suite's own header back from the
  run-scoped ledger and `:659 read_header()` returns it; the runner prints it as ONE
  JSON line on stdout (that print is the relay contract).
- The engine side persists it in `server/engine/develop_certify.py:2037` (`runs_store`
  → append a row) and then builds the certification in the same block (`:2052`).
- Both the row and the cert live or die together: if the block does not run, neither
  lands.

## Leading hypothesis (not yet proven)

The rounds that lost their row are the ones that **overlapped**: the host/agent drops a
forced-round marker (`engine_ops.py round`) while the scheduled 20-minute tick is about
to fire, so two rounds race for the one guard. The loser's header reaches stdout but the
engine's persist block is never reached (the round is joined/aborted), and nothing names
the loss on the face.

## Next steps (in order)

1. Reproduce deliberately: drop a marker while a round is running, then check
   `scenario-runs.jsonl` and the engine log for the aborted attempt.
2. Make the loss impossible to miss: when the engine joins/aborts a round it must write
   a named `round_aborted` row or a face reason, never nothing.
3. Operationally until fixed: do not drop forced markers while a round runs; let the
   scheduled tick own the cadence (one round at a time).
