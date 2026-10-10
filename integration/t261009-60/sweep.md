# t261009-60 — machine-global namespace sweep (engine test suite)

Ticket: tests that assert "no leftovers" must not read a machine-global
namespace. The reported instance is a sample of a class; this records the
sweep of the whole class, not just the named test.

## Commands run (2026-10-10, worktree t261009-60)

```
grep -rn "gettempdir|tempfile.gettempdir|glob(\"bundle-freshness|leftovers" server/engine/tests/
grep -rn "glob(|iterdir(|listdir(" server/engine/tests/*.py   # then manually filtered to unscoped hits
grep -rn "TemporaryDirectory|mkdtemp|NamedTemporaryFile" server/engine/*.py
grep -rniE "port ?=|localhost:[0-9]+|127\.0\.0\.1:[0-9]+" server/engine/tests/*.py
grep -rn "~/|expanduser|Path.home" server/engine/tests/*.py
```

## Verdicts

| File | Shape found | Verdict |
|---|---|---|
| `test_t261009_42_bundle_freshness.py` | `glob(gettempdir() + "bundle-freshness-*")` leftover assertion | **CHANGED** — assertion now globs the test's own `tmp_path` after patching `TMPDIR` + `tempfile.tempdir` |
| `test_t260926_tmp_fixture_water.py` | leak-regression already runs child pytest under a private `$TMPDIR`; `gettempdir()` (line ~513) is read-only scan *input*, not a leftover assertion | no change (model citizen) |
| `test_t260904_02_worker_meta.py` | leftover assertion scoped to `self.tmp` | no change |
| `test_t261006_08_shutdown_reclaim.py`, `test_t260917_08_env_fail_signal.py` | `gettempdir()` used only as a benign `cwd` for child processes, never globbed/asserted | no change |
| `test_t261001_12_ledger_location.py` | `os.listdir(path.parent)` — parent is the test's own tmp dir | no change |
| all other glob/iterdir hits (gate deadlock, ledgers, executor actions, naming compat, inspection aggregate, …) | scoped to `tmp_path` / `self.tmp` / repo-relative dirs | no change |
| fixed ports / home-relative leftover shapes | none found | no change |

## Receipts (host ruling 2026-10-10T04:42Z: the decoy must be a DIRECT child of `tempfile.gettempdir()`, measured from the engine venv)

Real temp root (engine venv): `/var/folders/7l/_74p2gy11bz094t_c53ngpzw0000gn/T` (macOS `$TMPDIR`, NOT `/tmp`).

| Experiment | Command shape | Receipt |
|---|---|---|
| TRUE pre-fix shape (both temp-root patches removed), FOREIGN decoy planted as direct child of the root | `mkdir -p "$T/bundle-freshness-prefix-receipt"` then pytest the patched-copy file | `FAILED test_zz60_prefix_shape.py::test_rebuild_temp_copy_reaped_on_every_path` — `1 failed in 0.41s` |
| same pre-fix shape, decoy removed (`rmdir`) | — | `1 passed in 0.31s` |
| POST-FIX (committed code), same FOREIGN decoy at the same direct-child position | `mkdir -p "$T/bundle-freshness-integration-decoy"` then pytest the real test | `1 passed in 0.19s` (immune to others' dirs) |
| POST-FIX, decoy removed | — | `1 passed in 0.18s` |
| POST-FIX teeth: OWN unreaped residue inside the scoped root | mutation copy planting `(tmp_path/"bundle-freshness-own-residue").mkdir()` (not committed) | `FAILED ...::test_rebuild_temp_copy_reaped_on_every_path` — `1 failed in 0.37s` |

Impossibility-check rule (corrected per ruling): a decoy placed under any OTHER
fresh directory (e.g. `$(mktemp -d)/bundle-freshness-alien`, or `/tmp` itself —
`gettempdir()` is `/var/folders/...`) is INVISIBLE to a gettempdir-level glob
and proves nothing; only a direct child of the measured root is evidence.
All mutation copies were deleted after the runs (negative controls not committed).

## Result

Exactly one member of the class existed; it is fixed. No assertion weakened,
no production change (`agent_activities.py:4984` untouched), no load-sensitive
roster row booked (the quiet-rerun route is inert for engine unit tests —
separate fault mode, out of scope here).
