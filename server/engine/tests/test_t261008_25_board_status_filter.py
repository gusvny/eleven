"""t261008-25 KI-223 Step 3: board status filter at `ticket-list` (display layer).

Pins:
- `status=FAILED` returns exactly the FAILED rows plus an honest `status_filter`
  receipt (an empty filtered result is never silent);
- comma list unions (FAILED,TERMINATED — note TERMINATED rows stay off the board by
  the pre-existing torn-down rule, and the filter never resurrects them);
- unknown token = structured refusal, zero queries needed;
- default behavior unchanged: no `args.status` → no filter keys, same row set.

Display-layer proof: the fake visibility feed is scanned once with the SAME query for
both calls; the filter drops rows client-side after the run-merge.
"""
import asyncio
import time

import client
import shared


def _ts(epoch_s):
    return type("Dt", (), {"timestamp": lambda self: epoch_s})()


class FakeWf:
    def __init__(self, tid, status, project="sandbar"):
        self.id = tid
        self.status = type("ExecStatus", (), {"name": status})()
        self.task_queue = shared.TASK_QUEUE
        old = time.time() - 30 * 86400     # outside the closed-hydrate window
        self.start_time = _ts(time.time() - 40 * 86400)
        self.close_time = _ts(time.time()) if status in ("FAILED", "COMPLETED") else _ts(old)
        self.typed_search_attributes = _SA(project)


class _SA:
    def __init__(self, project):
        self._p = project

    def get(self, key):
        return self._p


FEED = [
    FakeWf("t260901-01", "CANCELED"),
    FakeWf("t260901-02", "FAILED"),
    FakeWf("t260901-03", "COMPLETED"),
    FakeWf("t260901-04", "TIMED_OUT"),
    FakeWf("t260901-05", "TERMINATED"),
]


class FakeClient:
    queries = []

    async def list_workflows(self, query):
        FakeClient.queries.append(query)
        for wf in FEED:
            yield wf


def _run(coro):
    return asyncio.run(coro)


def _list(monkeypatch, args):
    monkeypatch.setattr(client, "_connect",
                        lambda: asyncio.sleep(0, result=FakeClient()))
    return _run(client.cmd_ticket_list(args))


def test_failed_filter_returns_only_failed_rows(monkeypatch):
    FakeClient.queries.clear()
    r = _list(monkeypatch, {"status": "FAILED"})
    assert r["ok"], r
    ids = [t["id"] for t in r["result"]["tickets"]]
    assert ids == ["t260901-02"]
    assert r["result"]["status_filter"] == {"applied": ["FAILED"], "matched": 1}


def test_token_is_case_insensitive_and_stripped(monkeypatch):
    r = _list(monkeypatch, {"status": " failed , CANCELED "})
    assert r["ok"], r
    ids = sorted(t["id"] for t in r["result"]["tickets"])
    assert ids == ["t260901-01", "t260901-02"]
    assert r["result"]["status_filter"]["applied"] == ["FAILED", "CANCELED"]


def test_unknown_token_structured_refusal(monkeypatch):
    FakeClient.queries.clear()
    r = _list(monkeypatch, {"status": "failed,EATING"})
    assert not r["ok"]
    assert "EATING" in r["error"] and "ExecutionStatus" in r["error"]
    assert FakeClient.queries == []     # refused before any query


def test_no_status_arg_default_unchanged(monkeypatch):
    r = _list(monkeypatch, {})
    assert r["ok"]
    assert "status_filter" not in r["result"]
    ids = {t["id"] for t in r["result"]["tickets"]}
    # TERMINATED stays off the board by the pre-existing torn-down rule; the default
    # row set is exactly what the unfiltered face always collected
    assert ids == {"t260901-01", "t260901-02", "t260901-03", "t260901-04"}


def test_failed_rows_carry_the_failed_status_honestly(monkeypatch):
    # the filter composes with the t260919-02 honest failed row: filtering to FAILED
    # shows the failure as a visible category, not an unsortable row
    r = _list(monkeypatch, {"status": "FAILED"})
    row = r["result"]["tickets"][0]
    assert row["exec_status"] == "FAILED" and row["status"] == "failed"
