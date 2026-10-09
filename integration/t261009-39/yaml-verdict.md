# t261009-39 — verdict on the generated workflow yaml (for t261008-47)

## Ruling

Of the three candidate states in the ticket, **(b) is the true mechanism**: the
yaml is generator output (`server/engine/gen_workflows_doc.py`, from
`<Class>.STAGES`), never hand-edited. But regenerating on main today is a
**no-op**, because main's engine code is still Chinese and main's Chinese yaml
is already exactly that code's output. The lane's English yaml is **not
drift** — it is the correct output of the lane's anglicized code.

Evidence (all run this session):

- `server/engine/.venv/bin/python gen_workflows_doc.py --check` on main
  (HEAD=ff068ff7): `check 绿：yaml 与代码一致且过 workflow.py 校验`, exit 0.
- Same check on an extracted copy of `lane/t261008-47` (tip b12b2de1, via
  `git archive`): `check 绿`, exit 0.
- Full regeneration inside the lane temp copy rewrote both yaml files with
  read-back green and **zero diff** against the tree's committed yaml.
- `git log --oneline 798b7f95..HEAD -- server/workflows/` → 0 commits: main
  has not touched the two files since the branch point.

(a) is false: applying the revert would leave the lane with English code and
Chinese yaml — its own check would go red. (c) is false: the generator named
above is exactly what produces them.

## Watch item for the merge gate (binding)

The invariant **"engine copy and its generated yaml land as one commit"**
binds the t261008-47 → main merge: the branch carries `dev_lane.py` /
`light_lane.py` / `ui_copy_guard.py` and `dev-lane.yaml` (62 lines) /
`light-lane.yaml` (10 lines) together, and they must merge together. Merging
the code without the yaml — or the yaml without the code — turns the
generator's check red on the receiving tree.

## The revert patch

`integration/t261008-47/yaml-revert-to-main.patch` (15,101 bytes) is **no
longer applicable and no longer needed**: it reverts the lane's yaml to main's
Chinese revision, which would break the lane's own generator check. t261008-47
owns that path and should discard it.

## Regression pin

`server/engine/tests/test_t261009_39_yaml_follows_code.py` (this ticket)
mechanizes the assertion: the generator's `--check` must be green on the
committed tree, a full regeneration in a temp copy must byte-match the
committed yaml, and a corrupted temp copy must be reported as drift (exit 1,
named template — not an import crash).

Docs read: none (no design doc governs the generator; its contract lives in
its own module docstring).
