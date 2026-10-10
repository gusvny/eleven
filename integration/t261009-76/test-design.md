# t261009-76 — L3/L2 test design (integration)

Ticket: the develop-buffer opt-in is unreachable from intake — nothing built
`DevLaneTicketInput`, so no ticket could name its lane version or line through
`ticket.py create` (KI-01M4HBC9ANXZXQRDQR54Z9C0MZ, instance four).

Registry entries (pool `ro`, `integration/run_scenarios.py`):

1. `t261009-76-intake-optin-journey` — `sc_intake_optin_journey.py`
   Faces:
   - A opt-in carried by the real intake: a payload naming
     `lane_version="develop-buffer-v1"` + a declared line, driven through the
     client intake's input-construction capability (contract-name discovery —
     never a hand-instantiated dataclass), reads as opted in (version parses
     to develop-buffer-v1, line id names a fixture-declared line); explicit
     `legacy-v1` stays lawful.
   - B named refusals at intake, before the workflow starts (offline process
     is the proof): unknown version names the value AND lists the registry;
     whitespace / underscore / uppercase / non-string versions are refused as
     MALFORMED (non-string never stringified); develop-buffer with an empty
     `develop_line_id` refused by name; an undeclared line id refused naming
     the id AND the declared list read back from the fixture `lines.json`
     (declaration = single truth, no duplicated list); `legacy-v1` carrying a
     line id refused; the fields on a non-dev-lane template refused.
   - C absence stays legacy: neither field → plain `TicketInput` of the exact
     legacy type, no lane attributes, the engine `getattr` default stays the
     in-flight replay guard — no silent migration.
2. `t261009-76-intake-optin-face` — `sc_intake_optin_face.py`
   Faces: A the create op's DECLARED schema carries `lane_version` and
   `develop_line_id` with semantic descriptions (`additionalProperties`
   refused ⇒ the declaration is the opt-in's reachability through the tool
   face); B the ticket list projection carries `lane_version`/`develop_line`
   from the engine rows with old-row tolerance (`.get` + empty-string
   fallback, never a KeyError on an older-engine row).

Failure surfaces covered: missing call site for a landed mechanism (the KI
class — positive face A1 fails named if no intake seam constructs the input);
malformed/absent/lawful-but-wrong opt-in input; silent stringification of a
wrong type; undeclared line id (the single-truth rule); foreign-template
field smuggling; silent migration of legacy payloads; in-flight replay
(getattr default); ticket face silently dropping the lane fields.

Intent-level non-duplication (checked against the global registry): the
version-name truth tables, pin/proven landing, ledger row, and legacy
coexistence faces are owned by `t261009-46-optin-landing-journey` /
`t261009-46-legacy-path-untouched` and are NOT re-asserted here — this pair
owns only the intake seam (payload → input / refusal) and the ticket face.
Known reds at design time (expected TDD signal, developer implement stage in
flight): both entries red until the intake carries the fields; green required
at the integration gate / merge.

Run (repo root):
    PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
    "$PY" -B integration/t261009-76/sc_intake_optin_journey.py
    "$PY" -B integration/t261009-76/sc_intake_optin_face.py
