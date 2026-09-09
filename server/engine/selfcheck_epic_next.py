#!/usr/bin/env python3
"""selfcheck_epic_next — selfcheck for the epic-next pre-run (t260828-08).

Zero Temporal server, zero model, zero real agent spawns (stub + monkeypatch +
fixed fixtures).

Coverage:
  A. epic_state_key: sha1 of sorted "id:closed|open" rows (order-independent /
     current ticket forced closed — the review-item-2 wording of t260828-08;
     cross-checked against the host's stateKeyFromRows computing the same
     literal on both sides);
  B. build_suggest_next_prompt: contains the result-file path / full epic text /
     ticket summary / template whitelist / three-state contract samples
     (ok/done/failed);
  C. _parse_suggest_result three-state validation: ok passes / done / failed
     pass through / non-object / missing fields / unknown status (malformed
     input cases); C2 (t260901-01) write_set pass-through and cleaning, nine
     failure modes + done/failed unaffected + ticket.py allow_empty_write_set
     source lock;
  D. _consume_suggest_result: ok writes the cache / hallucinated template id
     refused, no cache write / done cached / failed not cached / invalid JSON
     not cached / empty state_key not cached / cache content schema;
  E. prepare_epic_next (monkeypatched _epic_ticket_rows + SANDBAR_EPICS_DIR
     temporary fixture): archive read / exists=False degradation / illegal code
     shape degraded / state_key forces the current ticket closed;
  F. suggest_next stub path (SANDBAR_SUGGEST_STUB): ok/done/invalid variants and
     their cache behavior.

Exit code 0 = all green; non-zero = at least one red (details on stderr).
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import sys
import tempfile as _tf
from pathlib import Path as _P

POC = _P(__file__).resolve().parent
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
import shared  # noqa: E402
from agent_activities import (  # noqa: E402
    _consume_suggest_result, _parse_suggest_result, prepare_epic_next, suggest_next,
)
from shared import (  # noqa: E402
    AgentStageArgs, EpicNextPrepArgs, build_suggest_next_prompt, epic_next_precache_path,
    epic_state_key,
)

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  FAIL %s" % label)


def section(t: str) -> None:
    print("\n== %s" % t)


# ---------------------------------------------------------------- fixtures
ROWS = [{"id": "t-demo-01", "status": "closed", "closed": True},
        {"id": "t-demo-02", "status": "open", "closed": False}]
# Same fixture and same literal as EXPECT_STATE_KEY in workbench smoke/epic-precache.mjs:
# both sides compute it independently; whoever drifts goes red (t260828-08 review
# item 2: the current ticket is forced closed).
EXPECT_STATE_KEY = "703be9fa425d23a851b7aa8c060dad56f1570b37"
EPIC_MD = "# 立项单：demo-epic\n\n| 字段 | 值 |\n| --- | --- |\n| 状态 | 已立项（执行中） |\n"


def _args(tmp: str, epic: str = "demo-epic", state_key: str = EXPECT_STATE_KEY) -> AgentStageArgs:
    return AgentStageArgs(
        ticket_id="t-demo-02", stage_id="suggest_next", role="integration",
        prompt="p", workspace={"type": "dir", "path": tmp},
        result_file="%s/.suyou/stage_suggest_next_gen0.json" % tmp,  # naming-compat
        log_file="%s/.suyou/agent_suggest_next_gen0.log" % tmp,  # naming-compat
        gen=0, epic=epic, state_key=state_key)


# ---------------------------------------------------------------- A. state_key
section("A. epic_state_key 口径")
ok(epic_state_key(ROWS, "t-demo-02") == EXPECT_STATE_KEY,
   "fixture 双算字面量一致（当前票强制 closed）")
ok(epic_state_key(ROWS, "") != EXPECT_STATE_KEY,
   "不强制 closed 时字面量不同（强制口径确生效）")
ok(epic_state_key(list(reversed(ROWS)), "t-demo-02") == EXPECT_STATE_KEY,
   "行顺序无关（sorted）")
ok(epic_state_key([{"id": "t1"}], "t1") == epic_state_key([{"id": "t1", "closed": True}], ""),
   "缺 closed 键的行，当前票仍按强制 closed 口径计入")

# ---------------------------------------------------------------- B. prompt
section("B. build_suggest_next_prompt")
md = build_suggest_next_prompt(
    code="demo-epic", epic_markdown=EPIC_MD, tickets_summary='[{"id": "t-demo-02"}]',
    workflows=[{"id": "dev-lane", "name": "开发泳道"}],  # since 260904 the template surface is dev-lane only
    result_path="/tmp/r.json")
ok("/tmp/r.json" in md, "含结果文件路径（agent 唯一写点）")
ok("demo-epic" in md and EPIC_MD in md, "含立项代号与全文")
ok("t-demo-02" in md, "含工单汇总")
ok("dev-lane" in md and "proofread" not in md, "含模板白名单清单（260904 起仅 dev-lane）")
ok("开新 dev-lane 票" in md and "main 侧直跑验证" in md, "两类出路措辞在位")
ok('"status":"ok"' in md and '"status":"done"' in md and '"status":"failed"' in md,
   "三态契约样例齐（与 host buildSuggestPrompt 的两态差异点）")

# ---------------------------------------------------------------- C. three-state validation
section("C. _parse_suggest_result 三态校验（含畸形输入）")
kind, sug, err = _parse_suggest_result({"status": "ok", "workflow": "dev-lane", "title": "t",
                                        "body": "b", "rationale": "r"})
ok(kind == "ok" and sug and sug["workflow"] == "dev-lane", "ok 形态放行且只留白名单字段")
ok(_parse_suggest_result({"status": "done", "summary": "s"})[0] == "done", "done 形态放行")
k2, s2, _ = _parse_suggest_result({"status": "failed", "reason": "没活"})
ok(k2 == "failed" and s2["reason"] == "没活", "failed 透传 reason")
ok(_parse_suggest_result({"status": "failed"})[1]["reason"] != "", "failed 缺 reason 给人话缺省")
ok(_parse_suggest_result("not-dict")[1] is None, "非对象拒收")
ok(_parse_suggest_result({"status": "ok", "title": "t"})[1] is None, "ok 缺 workflow 拒收")
ok(_parse_suggest_result({"status": "ok", "workflow": "dev-lane"})[1] is None, "ok 缺 title 拒收")
ok(_parse_suggest_result({"status": "whatever"})[1] is None, "未知 status 拒收")
ok(_parse_suggest_result(None)[1] is None, "null 拒收")

# ------------------------------------------------- C2. write_set pass-through and cleaning (t260901-01)
section("C2. _parse_suggest_result write_set 透传（t260901-01，清洗口径=_valid_write_set_entry）")
_WS_OK = "server/engine/client.py"


def _ws_of(raw):
    return _parse_suggest_result(raw)[1]["write_set"]


ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": [" a.py ", _WS_OK]}) == ["a.py", _WS_OK], "合法条目 strip 后保序保留")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["a.py", "a.py", " b.py "]}) == ["a.py", "b.py"], "去重保序（首现胜出）")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": [None, 123, True, ["x"], {"a": 1}]}) == [], "非字符串元素整条丢弃")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["", "   "]}) == [], "空串/纯空白丢弃")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["/abs/x.py", "\\x.py", "a\\b.py"]}) == [], "绝对路径与反斜杠丢弃")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["C:/x.py", "c:/y.py", "Z:/z.py"]}) == [], "Windows 盘符（大小写）丢弃")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["a/../b.py", "../up.py"]}) == [], "含 '..' 段丢弃")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t",
           "write_set": ["ok.py", "/bad", "../up", 42, " ok.py "]}) == ["ok.py"],
   "混合：只留合法，不抛错")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t"}) == [], "字段缺失 → 空数组不阻塞")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t", "write_set": "junk"}) == [],
   "非列表（字符串）→ 空数组不阻塞")
ok(_ws_of({"status": "ok", "workflow": "d", "title": "t", "write_set": 42}) == [],
   "非列表（数字）→ 空数组不阻塞")
k3, s3, _ = _parse_suggest_result({"status": "done", "summary": "s", "write_set": ["x.py"]})
ok(k3 == "done" and "write_set" not in s3, "done 形态不受影响（不带 write_set）")
k4, s4, _ = _parse_suggest_result({"status": "failed", "reason": "x", "write_set": ["x.py"]})
ok(k4 == "failed" and "write_set" not in s4, "failed 形态不受影响（不带 write_set）")
# suggest-side cleaning vs create-side rejection: the wording difference is
# declared here (create-side validate_write_set_args rejects instead of cleaning)
okr, _, err = shared.validate_write_set_args(["ok.py", "/bad"], False)
ok(not okr and "非法条目" in err, "建票口仍拒收不清洗（口径未漂移）")
# ticket.py source lock (t260901-01, same pattern as selfcheck_ui_acceptance):
# both the schema and the payload wiring are asserted
_ticket_src = (POC.parent.parent / "tools" / "ticket.py").read_text("utf-8")
ok("'allow_empty_write_set': {'type': 'boolean'" in _ticket_src,
   "ticket.py schema 已声明 allow_empty_write_set")
ok("'allow_empty_write_set': bool(a.get('allow_empty_write_set'))" in _ticket_src,
   "ticket.py _create payload 透传 allow_empty_write_set")
_poc_src = (POC / "client.py").read_text("utf-8")
ok("validate_write_set_args(" in _poc_src and "allow_empty_write_set" in _poc_src,
   "引擎口校验单点仍在 client.py")

# ---------------------------------------------------------------- D. interpretation + cache
section("D. _consume_suggest_result 判读与缓存")
_d = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-en-"))
shared.REPO_ROOT  # noqa: B018  (make sure the module is loaded)
_orig_root = agent_activities.REPO_ROOT
agent_activities.REPO_ROOT = _d  # redirect cache writes to the temp directory


def _cache_of(code: str):
    p = epic_next_precache_path(_d, code)
    if not p.is_file():
        return None
    return _json.loads(p.read_text("utf-8"))


a = _args(str(_d))
(_d / "r_ok.json").write_text(_json.dumps(
    {"status": "ok", "workflow": "dev-lane", "title": "下一单", "body": "b",
     "rationale": "r"}), "utf-8")
res = _consume_suggest_result(_d / "r_ok.json", a)
cache = _cache_of("demo-epic")
ok(res is not None and res.status == "ok" and "下一单" in res.summary, "ok 判读 status=ok")
ok(cache is not None and cache["suggestion"]["workflow"] == "dev-lane"
   and cache["state_key"] == EXPECT_STATE_KEY and cache["ticket_id"] == "t-demo-02"
   and cache["epic"] == "demo-epic" and isinstance(cache["ts"], int),
   "ok 落缓存且 schema 符 EpicNextCache（互指 host readPrecache）")

(_d / "r_hallu.json").write_text(_json.dumps(
    {"status": "ok", "workflow": "made-up-wf", "title": "t"}), "utf-8")
res = _consume_suggest_result(_d / "r_hallu.json", a)
ok(res is not None and res.status == "failed" and "不在可用清单" in res.summary,
   "幻觉模板 id 拒收（防幻觉闸，软失败）")

(_d / "r_done.json").write_text(_json.dumps({"status": "done", "summary": "都做完了"}), "utf-8")
res = _consume_suggest_result(_d / "r_done.json", a)
cache = _cache_of("demo-epic")
ok(res is not None and res.status == "ok" and "可结项" in res.summary, "done 判读=可结项")
ok(cache is not None and cache["suggestion"] == {"status": "done", "summary": "都做完了"},
   "done 也落缓存（host 出结项卡）")

(_d / "r_failed.json").write_text(_json.dumps({"status": "failed", "reason": "x"}), "utf-8")
ok(_consume_suggest_result(_d / "r_failed.json", a).status == "failed", "failed 判读软失败")
(_d / "r_bad.json").write_text("{not-json", "utf-8")
ok(_consume_suggest_result(_d / "r_bad.json", a).status == "failed", "非法 JSON 判读软失败")
ok(epic_next_precache_path(_d, "demo-epic").is_file(), "合法结果落缓存")

# empty state_key / empty epic: validated but not cached (dirty keys must not
# pollute the hit wording)
(_d / "r_ok2.json").write_text(_json.dumps(
    {"status": "ok", "workflow": "dev-lane", "title": "t2"}), "utf-8")
res = _consume_suggest_result(_d / "r_ok2.json", _args(str(_d), epic="", state_key=""))
ok(res is not None and res.status == "ok", "无 epic/state_key 判读仍 ok（不落缓存）")
agent_activities.REPO_ROOT = _orig_root

# ---------------------------------------------------------------- E. prepare_epic_next
section("E. prepare_epic_next（fixture + monkeypatch 查询）")
_epics = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-en-epics-"))
(_epics / "demo-epic.md").write_text(EPIC_MD, "utf-8")
# t260907-07: prepare now goes through shared.resolve_epics_dir (env
# SANDBAR_EPICS_DIR read first), so the fixture is injected via env (matching
# the ":16 docstring" wording "SANDBAR_EPICS_DIR temporary fixture"); we no
# longer monkeypatch agent_activities.EPICS_DIR (nothing consumes that binding
# anymore). An empty project falls back to the engine anchor only after the env
# check, so the fixture applies to every construction below (none pass project).
_orig_epics_env = os.environ.get("SANDBAR_EPICS_DIR")
os.environ["SANDBAR_EPICS_DIR"] = str(_epics)
_orig_rows = agent_activities._epic_ticket_rows


async def _fake_rows(epic: str):
    return list(ROWS)


agent_activities._epic_ticket_rows = _fake_rows
prep = asyncio.run(prepare_epic_next(EpicNextPrepArgs(ticket_id="t-demo-02", epic="demo-epic")))
ok(prep.exists and prep.epic_markdown == EPIC_MD, "立项全文读入")
ok(prep.state_key == EXPECT_STATE_KEY, "prepare 侧 state_key 含当前票强制 closed 口径")
ok(prep.tickets == ROWS, "关联工单行内联返回（workflow 内零 IO）")
agent_activities._epic_ticket_rows = _fake_rows  # keep it (a different impl is swapped in below, then restored)


async def _boom(epic: str):
    raise RuntimeError("temporal 不可达")


agent_activities._epic_ticket_rows = _boom
prep = asyncio.run(prepare_epic_next(EpicNextPrepArgs(ticket_id="t-demo-02", epic="demo-epic")))
ok(prep.exists and prep.tickets == [] and prep.state_key != "",
   "查询故障降级为空行表（不硬失败，state_key 仍可算）")
agent_activities._epic_ticket_rows = _orig_rows
prep2 = asyncio.run(prepare_epic_next(EpicNextPrepArgs(ticket_id="t", epic="missing-epic")))
ok(prep2.exists is False, "档案不存在 → exists=False（workflow 侧留痕跳过）")
prep3 = asyncio.run(prepare_epic_next(EpicNextPrepArgs(ticket_id="t", epic="../etc")))
ok(prep3.exists is False, "代号形状非法 → exists=False（防穿）")
if _orig_epics_env is None:
    del os.environ["SANDBAR_EPICS_DIR"]
else:
    os.environ["SANDBAR_EPICS_DIR"] = _orig_epics_env

# ---------------------------------------------------------------- F. suggest_next stub
section("F. suggest_next stub 路径（SANDBAR_SUGGEST_STUB，零模型/零 spawn）")
for mode, expect in (("ok", "ok"), ("done", "ok"), ("failed", "failed"),
                     ("invalid", "failed")):
    d = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-en-stub-"))
    os.environ["SANDBAR_SUGGEST_STUB"] = mode
    agent_activities.REPO_ROOT = d
    try:
        res = asyncio.run(suggest_next(_args(str(d))))
    finally:
        os.environ.pop("SANDBAR_SUGGEST_STUB", None)
        agent_activities.REPO_ROOT = _orig_root
    ok(res.status == expect, "stub %s → %s（实测 %s）" % (mode, expect, res.status))
    if mode in ("ok", "done"):
        ok(epic_next_precache_path(d, "demo-epic").is_file(), "stub %s 落缓存" % mode)
    if mode == "invalid":
        ok(epic_next_precache_path(d, "demo-epic").is_file() is False
           or _cache_of("demo-epic") is None, "stub invalid 不落缓存")
    if res.status == "failed" and mode == "failed":
        ok("给不出" in res.summary or "放弃" in res.summary or res.summary != "",
           "stub failed 留人话 summary")

print("\n%d passed, %d failed" % (PASS, FAIL))
if FAILURES:
    print("FAILURES:", file=sys.stderr)
    for f in FAILURES:
        print("  - %s" % f, file=sys.stderr)
sys.exit(0 if FAIL == 0 else 1)
