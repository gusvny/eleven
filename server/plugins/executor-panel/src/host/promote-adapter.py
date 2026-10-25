#!/usr/bin/env python3
"""promote-adapter.py — the engine-side WRITE adapter of the executor panel's
signed promotion act (t261025-12, design ruling: executor-operational-envelope
-v1 section 5).

Why this file exists: the panel performs the signed act by calling the
ENGINE'S promotion writer — never by reimplementing it. This adapter imports
``develop_promote`` and calls ``promote_buffer(project, line_id, signer)``:
the writer validates everything first (green certification, declared line,
fast-forward, and — since this ticket — the signer identity rule) and refuses
by name before moving any ref, then moves main and appends the promotion row
to the delivery ledger. Nothing here invents a refusal vocabulary of its own:
a ``PromotionRefused`` travels out VERBATIM as the receipt's ``reason``, so
the panel shows the engine's own words (``no_green_certification``,
``promotion_not_fast_forward``, ``signer_is_agent_role_name``, ...), never a
generic failure.

Invocation: python3 promote-adapter.py <project-key> <line-id> <signer>
Exit code is always 0 with ONE strict JSON receipt on stdout (single line,
like every engine receipt) when the adapter itself ran; a crash is a
traceback on stderr and the TS reader names that. The receipt:
  {ok: true,  row: <the recorded promotion row>}
  {ok: false, reason: <the engine's named refusal, verbatim>}
"""

import json
import sys
from pathlib import Path

# The engine modules live at server/engine; this file lives at
# server/plugins/executor-panel/src/host/. parents[4] is the server dir.
SERVER_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SERVER_DIR / "engine"))

import develop_promote as dp  # noqa: E402


def _fail(reason):
    return {"ok": False, "reason": str(reason)[:500]}


def _emit(doc):
    sys.stdout.write(json.dumps(doc, ensure_ascii=False,
                                separators=(",", ":")) + "\n")


def main(argv):
    if len(argv) != 4:
        _emit(_fail("usage: promote-adapter.py <project-key> <line-id> <signer>"))
        return 0
    project, line_id, signer = argv[1], argv[2], argv[3]
    if not project or not line_id or not signer:
        _emit(_fail("promote_refused:project/line/signer must all be non-empty"))
        return 0
    try:
        row = dp.promote_buffer(project, line_id, signer)
    except dp.PromotionRefused as e:
        # the engine's own refusal vocabulary, verbatim — the panel never
        # translates, summarizes or genericizes it
        _emit(_fail(str(e)))
        return 0
    except dp.PromoteError as e:
        _emit(_fail("promotion_act_failed:%s" % e))
        return 0
    _emit({"ok": True, "row": row})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
