# Chore ticket (ready to file): declare the bundle build entry

## Title
Declare `entry:` for the workbench bundle pair in server/merge-checks.yaml (t261009-42 follow-up)

## Body
t261009-42 lands the engine half of the bundle-freshness redesign: merge-check item 3.5
now rebuilds a declared chain in a temp copy and byte-compares when the lane diff touches
the declared src prefix, with a three-state verdict (rebuilt-and-identical = green,
rebuilt-and-different = stale red, could-not-establish = degraded red naming the step).

The optional per-pair `entry:` / `budget_s:` keys are read by the engine, but the
declaration itself is outside t261009-42's write set. Until this one-line declaration
lands, the declared pair keeps the legacy diff-based verdict — which is exactly the
unsatisfiable red that blocked t261009-35 and t261009-41 on 261010.

## Change (the whole ticket)

```yaml
 bundle_pairs:
   - src: server/plugins/workbench/src/client/
     out: server/plugins/workbench/lib/
+    entry: server/plugins/workbench/build-client.sh
+    budget_s: 600
```

`budget_s: 600` is optional (engine default is 600 when omitted); declared explicitly so
the policy lives in the project repo, not the engine.

## Acceptance
- After landing, rerun t261009-35 and t261009-41: both rebuild byte-identical output, so
  merge_check item 3.5 goes green with the evidence line naming rebuilt-and-identical.
- A lane that changes bundled src without rebuilding still reds (rebuilt-and-different).
