# Slice 2 ticket draft — the Certification tab in the executor panel

> Drafted by t261009-41 implement (plan v2 §R1 / review C2): this is the
> follow-up ticket the host signs so the split is one reviewable text, not a
> vague debt. Scope/acceptance exactly as plan v2 §R1 states. Ticket text in
> English per host order 260924.

## Title

The Certification tab in the executor panel: render the certification face from the develop ledgers (t261009-41 Slice 2)

## Spec

The host asked for "a tab in the executor UI that shows the state of
certification, and the certify operation". Slice 1 (t261009-41) delivered the
whole face-derivation model — `server/plugins/workbench/src/client/certification-model.ts`
(`deriveCertificationFace`), unit-tested, bound to the engine projections by the
golden fixture (`server/plugins/workbench/tests/fixtures/t261009-41-certification-fixture.json`,
contract pytest `integration/t261009-41/test_model_fixture_contract.py`). What
is missing is the surface: nothing renders the face, and no route reads the
develop ledgers.

Scope (write set: `server/plugins/executor-panel/src/` + `server/plugins/executor-panel/tests/`):

1. **Read-only develop-ledger reader** (host module): read
   `~/.sandbar/projects/<key>/develop/lines.json` and `.../develop/landings.jsonl`
   (shapes: `server/engine/develop_line.py` `load_lines` / `_landing_rows`),
   the delivery ledger `.../ledger/delivery.jsonl`
   (`develop_certify.py` `ledger_path` / `read_rows`), and the promotion ledger
   (`develop_promote.py` `promotion_path` / `read_promotion_rows`). Missing
   files / malformed rows degrade to a named reason — never invented data.
2. **Projection step**: from the raw rows, derive the engine projections the
   model consumes — `freeze_state`, `ticket_wait_state` (with an honest
   `is_green` run reader from run headers; when run headers are absent the
   caller passes no silent default), `ticket_outcome` — and assemble the
   `CertificationInput` (plus `ticketMeta`: title + epic from the ticket
   store). Run the projections in a subprocess through the engine venv
   fallback chain (`server/engine/.venv/bin/python` first), or port the
   projection calls behind a named seam — implementer's choice, decided in its
   plan; no second implementation of the projection rules either way.
3. **API route**: `GET /sandbar-executor-panel/api/certification?project=<key>`
   — registered in `PANEL_API_ROUTES` (single route-table source), parity-test
   locked, returning the derived `CertificationFace` plus the raw input arrays
   the panel needs for links. No write path: certify/promote stays a
   record-signed operation out of scope here except where the mock shows the
   dialog (the dialog may render; its submit needs the promotion engine call
   and is gated on the signer face — stage it with the tab read-only first if
   the promotion write face is not landed).
4. **The tab**: a `Certification` entry in `panel-page.ts`'s tab row rendering
   the face exactly as the approved mock
   (`notes/discussions/261009-executor-certification-tab-mock.html`, v15)
   draws it: one combobox line picker; the `.linebar` with the fixed 9px
   delivered cap and one boundary; counts inside segments only; `auto rounds`
   switch + `run now`; the waiting/certified tables (ticket id → ticket,
   round id → record, title + epic on every ticket row); the rounds table
   (auto/manual, labelled summing result, green/red·blockers, `line <sha>`);
   `Promote N` disabled only at zero, alive through freeze; the one-line
   freeze banner with the blockers named. English copy, data untranslated, no
   emoji. Rule 9 stands: `roundState` renders what records carry; no
   scheduler face until the engine-side chaining mechanism lands.

## Acceptance

- The mock is the yardstick: a person opening the executor panel sees the
  Certification tab showing a real line's bar, boundary, tables and rounds
  from the ledgers, and can promote the certified part through the signed
  dialog (or the dialog is explicitly absent and named, if the promotion
  write face is staged separately).
- Route + tab covered by `executor-panel` unit/page tests (existing `.mjs`
  conventions, e.g. `page.test.mjs`); the face logic itself is NOT re-tested
  there — Slice 1's model tests and the fixture contract own it.
- No integration scenario may be executed by the developer stage; the gate
  runs `t261009-41-certification-face-seam` and the fixture-contract entry.
- Counted-once, no-invented-token, no-glyph and no-scheduler rules verified on
  the rendered markup (anchors, not copy).

## Out of scope

- Round chaining / auto-round scheduling (engine-side mechanism, staged
  separately — dispatch rule 9).
- The promote write path beyond rendering the dialog, if the promotion engine
  entry is not yet consumable from the panel; declared, not smuggled.
