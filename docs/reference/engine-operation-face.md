# The engine operation face

Read this file on demand. It is the full form of the two-line pointer in
`server/session_charter.md`.

## The one entrance

    PY=<engine_root>/server/engine/.venv/bin/python
    TK=<engine_root>/server/tools/ticket.py
    $PY $TK '{"op":"list","project":"<project_key>"}'

`ticket.py` takes ONE argument: the whole JSON object, with `op` inside it. It is
the only recommended operation face. It mints short ticket ids, enforces the
`notes/` write set, writes one line per call to `admin.log`, exits non zero on a
failure, and answers with a structured error.

## Every write carries the caller project identity

    "caller_project": "<project_key>"

Inside the engine repository the cwd fallback is deliberately off. The cwd in
that tree names the engine that is called, not the session that calls it. A
write without the identity is refused by the cross project gate. The refusal
reads: `调用方项目身份未声明（SANDBAR_CALLER_PROJECT 未注入且无显式参数）`.

## Commands

- Board read: `{"op":"list","project":"<key>"}`
- One ticket: `{"op":"show","id":"tXXXXXX-XX"}`
- Open a ticket:
  `{"op":"create","workflow":"dev-lane","project":"<key>","caller_project":"<key>","epic":"<epic code>","title":"...","spec":"...","write_set":["..."]}`
  The epic needs a declaration first. The ticket id is auto minted and is unique
  across the project: on a collision, pick another and submit again.
- Send back:
  `{"op":"rework","id":"...","caller_project":"<key>","to_stage":"implement","note":"why"}`
  When a merge check or a mechanical check is red, `to_stage` is mandatory. The
  default sends the ticket back to its current stage and burns one empty round.
- Sign:
  `{"op":"sign","id":"...","caller_project":"<key>","by":"<who>","decision":"approve","gate":"merge","note":"..."}`
  An empty `gate` means the human stage that is waiting.
- Rerun the current stage while blocked:
  `{"op":"retry_qc","id":"...","caller_project":"<key>","by":"..."}`
- Pause or resume between stages:
  `{"op":"pause"|"resume","id":"...","caller_project":"<key>","by":"..."}`

## Form is the biggest trap

The `ticket.py` CLI entry landed on 260910-06. Before that the file was a library
with no `__main__`, so running it printed nothing and looked like a silent entry
failure. After the entry landed the whole JSON is still ONE argument:
`ticket.py list '{...}'` (a sub command plus a JSON argument) answers that the
argument is not valid JSON. Before you follow any written instruction, check its
form with one read only command.

## The bare entrance

    $PY <engine_root>/server/engine/client.py <sub command> JSON

(`ticket-list`, `ticket-query`, `ticket-start`, `ticket`). This is the low level
channel for debugging and fault work. It has no `notes/` write set gate and it
needs a hand written ticket id, so do not use it for daily work. Its receipts
carry an `entry_hint` that points back at `ticket.py`.
