# KI-438 — the survivor judgement is now local to this case (t261031-13)

Entry: `t260916-26-boot-evidence` (`sc_t26091626_boot_evidence.mjs`, F leg
`lane-bench-pre-log-failure-named-no-fabrication`).

## Incident

The 22:15Z develop-buffer round booked this leg red with
`fabricatedSurvivors=fix17-console-ready-1793399545791-74344.log`. The same case
passed standalone in 0.2 s on the same tree.

Mechanism: `survivorsNow()` took a before/after difference over
`readdirSync(os.tmpdir())` filtered on the `fix17-console-` prefix. `os.tmpdir()`
is machine-shared. A concurrent case that boots a console writes
`fix17-console-ready-<ts>-<pid>.log` there (`lib_fix17.captureBootFailure`), and
the F leg's window is about 0.2 s. The leg measured its neighbours, not itself.
This machine's shared temp root held 221 stale `fix17-console-*` files when this
ticket started, so the collision is not a rare event.

## Reproduction (on the code before the fix)

A microtask plants a decoy `fix17-console-ready-<ts>-<pid+1>.log` in the
machine-shared temp root. The microtask runs after the `before` snapshot and
before the `after` snapshot, so the collision needs no timing luck. The leg went
red with the foreign file:

```
FAIL t260916-26 boot evidence: 1/7 red — first: lane-bench-pre-log-failure-named-no-fabrication:
this case is booked as having fabricated survivor files:
fix17-console-ready-1793405879859-90757.log —
fabricatedSurvivors=fix17-console-ready-1793405879859-90757.log foreignDecoyLanded=true resolved=false
```

The same red comes out through the runner entry
(`python3 integration/run_scenarios.py --only t260916-26-boot-evidence`,
status `fail`, reason `assert_mismatch`).

A second reproduction runs a real sibling process: it writes
`fix17-console-ready-<ts>-<pid>.log` into the shared temp root at a 4 ms cadence
while the runner runs the case on the OLD code. The leg went red with 23 foreign
files:

```
FAIL [t260916-26-boot-evidence] exit=1 (0.2s)
fabricatedSurvivors=fix17-console-ready-1793406433287-9379.log,
fix17-console-ready-1793406433291-9379.log, ... (23 names)
```

The same sibling process plus the NEW code: green.

## The rule now (three lines)

1. The case points `os.tmpdir()` (= `TMPDIR`) at a temp root of its own
   (`t26091626-boot-evidence-scope-*`) before it produces any evidence, and
   removes that root on exit.
2. `survivorsNow()` reads only that root. Every survivor this case can write
   lands there, so the before/after difference can only contain this case's own
   files.
3. A FOREIGN file is any `fix17-console-*` name in the machine-shared temp root.
   Another process wrote it. This case neither claims nor counts it.

The survivor-location contract is untouched: the bench lib still copies into
`os.tmpdir()`. The fix changes WHOSE files are counted, never WHETHER a real
survivor is checked. Leg B still requires that the survivor the message names
exists after the temp home is reclaimed, and it now also requires that this
survivor sits inside the case's own scope.

## Both directions

- Foreign decoy present: green. The F leg reports
  `fabricatedSurvivors=none foreignDecoyLanded=true`, and the G leg
  (`lane-bench-survivor-scope-sees-own-evidence`) shows the scope saw
  `fix17-console-scope-canary-*.log` written through the production seam.
- Genuine fabrication through this case's own path still reds (mutation run,
  bench lib patched locally and reverted):
  - survivor only, nothing quoted: `fabricatedSurvivors=fix17-console-bootfail-mutation-*.log`;
  - invented log through the evidence path: `quotes a log tail although no log
    ever existed` plus `fabricatedSurvivors=fix17-console-bootfail-projects-*.log`.

## Limits

- The decoy is planted by this case, not by a real concurrent case. The runner
  cannot schedule the collision on request, so the stand-in is a timer plus a
  stated `foreignDecoyLanded` field: an attack that did not fire fails the leg
  instead of passing it silently.
- The decoy lives in the machine-shared temp root for about one millisecond. A
  concurrent copy of this leg that still runs the OLD code can count it in its
  own window — the same exposure the incident had. It goes away once every lane
  runs this version.
- The scope trusts that `os.tmpdir()` follows `TMPDIR` (POSIX). Leg G is the
  guard: if the production evidence path ever stops writing into the case's root,
  G reds and names the scope as vacuous.
- Nothing here changes the bench lib, the 45 s boot default, or any other case.
