# Engine conversion handover packet — t261021-11 (gen1 implement)

Write set of this ticket is `integration/` only, so the engine conversion the
arbitrate verdict ordered (code-fault) cannot be applied here. This packet
makes the conversion mechanical for the round that carries
`server/engine/path_gates.py` + `server/engine/agent_activities.py`
(write-set widening by the host, or a follow-up ticket).

Scope = the failing scenario's acceptance face (legs A + D), which is exactly
`path_gates.py:838` plus the 12 `note`/`notes` builder literals the scenario
named. Every replacement preserves behavior: same `%s`/`%d` slots, same join
shapes, only the copy and the separators become ASCII. CJK **data** crossing
the templates must keep flowing verbatim (scenario leg E guards this).

## A. path_gates.py

1. Line 838 (inside `gate_refusal_note`, `unauthorized_path` branch):

```diff
-        desc = "only %s" % "、".join(rule.get("prefixes") or ())
+        desc = "only %s" % ", ".join(rule.get("prefixes") or ())
```

## B. agent_activities.py note/notes builders

2. Line 1949:

```diff
-        notes.append("分类器入参畸形（非串列表），本段未判")
+        notes.append("classifier input malformed (not a list of strings); "
+                     "this stage did not judge")
```

3. Line 2320:

```diff
-        note += "；假仓库 %s 已隔离到 %s" % (fake.name, dst.relative_to(cwd))
+        note += "; fake repo %s quarantined to %s" % (fake.name, dst.relative_to(cwd))
```

4. Lines 3651–3653 (one expression):

```diff
-                    note = ("越权改动已自动处置（%s），工作区已干净——本段无需代落盘"
-                            % "；".join(remediation)) if remediation \
-                        else "工作区已干净，无需代落盘"
+                    note = ("Out-of-scope changes auto-disposed (%s); worktree "
+                            "is clean — nothing to settle on this stage's behalf"
+                            % "; ".join(remediation)) if remediation \
+                        else "Worktree is clean; nothing to settle on this stage's behalf"
```

5. Line 3655:

```diff
-                        note += "；%s" % runtime_exempt_note
+                        note += "; %s" % runtime_exempt_note
```

6. Line 3668 (named source):

```diff
-                note += "；本轮已自动处置：%s" % "；".join(remediation)
+                note += "; auto-disposed this round: %s" % "; ".join(remediation)
```

7. Line 3672:

```diff
-                note += "；%s" % fresh_diag
+                note += "; %s" % fresh_diag
```

8. Line 3777:

```diff
-        notes.append("工作区已干净，无需代落盘")
+        notes.append("Worktree is clean; nothing to settle on this stage's behalf")
```

9. Line 3782 (named source):

```diff
-        notes.append("本轮已自动处置：%s" % "；".join(remediation))
+        notes.append("Auto-disposed this round: %s" % "; ".join(remediation))
```

10. Line 8271 (capped note-list tail; mirrors the workbench copy — see anchors):

```diff
-        note += "（等共 %d 条）" % len(notes)
+        note += " (and %d more in total)" % len(notes)
```

11. Line 8365:

```diff
-            note += "（" + "；".join(notes) + "）"
+            note += " (" + "; ".join(notes) + ")"
```

12. Line 9523:

```diff
-            note += "; archive/move-out failed for %d image(s) left in the lane " \
-                    "(a human can retrieve them): %s" % (len(kept), "、".join(kept))
+            note += "; archive/move-out failed for %d image(s) left in the lane " \
+                    "(a human can retrieve them): %s" % (len(kept), ", ".join(kept))
```

## C. Anchors that key on the converted copy (move together, same change)

- `server/plugins/workbench/src/host/agent-usage.ts:329` — mirrors the `（等共 N 条）` tail: switch to `` ` (and ${s1s.length} more in total)` ``.
- `server/plugins/workbench/src/host/agent-live.ts:153, :250` — `（等共 N 个）` type/classification tails: `(and ${n} more in total)`.
- `server/plugins/workbench/smoke/agent-usage.mjs:319–326` — asserts `等共 27 个`: update to the new tail (guard intent unchanged).
- `server/engine/tests/test_t260916_19_gate_deadlock.py` — `CLEAN_NOTE = "工作区已干净，无需代落盘"` (line 49) and the `本轮已自动处置` assertions (lines 393/401/429/446): update constants/assertions to the new English copy; the *negative* asserts (`not in note`) flip to the English phrase, the positive one at 446 to `auto-disposed this round`. Verify each against the note actually produced by the exercised path before committing.
- `server/engine/tests/test_t260911_03_path_gates.py:304` — uses its own copy of the clean-note literal as a non-refusal probe: still passes after conversion (is_gate_refusal keys on `path_gate_reason=`), update the literal to the new English for clarity.

## D. Post-conversion checklist in integration/ (this ticket's own assets)

1. Delete the two `xfail(strict=True)` markers in
   `integration/tests/test_engine_face_language.py` (`test_gate_refusal_note_two_prefix_list_ascii`,
   `test_auto_quarantine_trailer_literals_ascii`) — strict xfail makes XPASS a
   loud failure, so the marker removal is forced, not optional.
2. Regenerate the ledger: `python3 integration/lint_engine_face_language.py --write-inventory`,
   then delete the entries whose literals are gone (the stale-entry check goes
   red until the ledger is pruned — that is the drift brake working). After a
   complete surface conversion the `defect` list must be empty; entries that
   remain need a written re-classification (evidence), not silent keeping.
3. Scenario `integration/t261021-11/sc_t26102111_engine_face_english.py` must
   go 12/12 green — that is the acceptance proof. Do not touch its assertions.
4. `pytest integration/tests/test_engine_face_language.py` and
   `python3 integration/lint_tests.py` must both be green.

---

Applied in this ticket (implement gen4): sections A+B plus the two remediation
item strings (`已挪档` / `已回滚` at what were lines 2529/2577) — the leg-D
scanner stays at 0 findings and the engine anchor tests pass with the English
keys. Converted here as well: the workbench mirror tails (`agent-usage.ts:328`,
`agent-live.ts` formatCappedTypes/formatSuspectGroups, `smoke/agent-usage.mjs`
assertion) — the console face must be English (host order 260925). The engine
source they mirror, `_format_capped`'s `（等共 %d 个）` tail
(agent_activities.py ~line 602), is a DIFFERENT site and stays in the L26
ledger as debt for the sweep ticket; the mirrors are now intentionally ahead
of it. Additional engine-test anchors
found keying on the converted clean-note copy, OUTSIDE this ticket's union
write set (must move with the copy in the sweep ticket or the engine test pool
goes red): `server/engine/tests/test_t260914_01_settle_lane_stance.py:37
(CLEAN_NOTE)`, `server/engine/tests/test_t26101621_settle_multirepo.py:167
(inline expected note)` — both are one-line literal swaps to `"Worktree is
clean; nothing to settle on this stage's behalf"`.


UPDATE (implement gen5): `server/engine/path_gates.py` turned out to be on
the PROTECTED list (it is the gate's own source) - a write-set entry cannot
license it and the protected hit also disarms auto-disposal for the batch. The
line-838 conversion is saved unmodified as `.sandbar/t261021-11_path_gates.patch`
(792 bytes, one hunk) and reverted in the lane; the unit fixture for it is back
under `xfail(strict=True)` naming this debt. Landing the patch requires the
main-tree route; the two named-source legs of the scenario stay red until then
(leg A only - leg D, the agent_activities family, is converted and green).

UPDATE (implement gen9, operator ruling): the two clean-worktree settle-note
strings are ALLOW-MARKED copy (`copy-lang-allow:t261016-21`) and were restored
byte-for-byte to the Chinese main wording (ternary else branch in the settle
gate block, and the clean-worktree notes.append). The restored lines carry the
marker inline; the L26 ledger certifies the string as `allow-exempt` with the
marker as evidence, and regeneration now preserves certified override entries.
`test_t260916_19_gate_deadlock.py` CLEAN_NOTE moved back with the copy. All
other conversions stand.

Residual handover: `server/engine/tests/test_t261002_10_codegen_freshness.py`
(outside every write set so far) pins the SOURCE literal
`note += "；%s" % fresh_diag` as a structural anchor; the conversion made it
`note += "; %s" % fresh_diag`, so that one test stays red until its anchor is
updated to the ASCII joiner (one line, mechanical, needs the file in a write
set). It is not an allow-marked string.

UPDATE (implement gen10, operator ruling): the fresh_diag joiner is the third
test-pinned literal and was restored the same way: agent_activities.py line
~3674 reads `note += "；%s" % fresh_diag  # copy-lang-allow:t261016-21` again;
the L26 ledger certifies `；%s` as `allow-exempt` with the marker as evidence;
`pytest server/engine/tests/test_t261002_10_codegen_freshness.py` -> 12 passed.
Standing rule recorded: any literal an out-of-write-set test pins is kept and
marked, never fought. Three allow-exempt strings are now certified in the
ledger (two clean-worktree settle notes + this joiner); every other conversion
stands.
