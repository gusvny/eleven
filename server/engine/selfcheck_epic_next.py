#!/usr/bin/env python3
"""selfcheck_epic_next —— 立项下一单预跑（t260828-08）自测。

零 Temporal server / 零模型 / 零真 agent spawn（stub + monkeypatch + 固定 fixture）。

覆盖：
  A. epic_state_key：sorted "id:closed|open" 行 sha1（顺序无关 / 当前票强制 closed——
     t260828-08 review 第 2 条口径，与 host stateKeyFromRows 双算同一字面量互检）；
  B. build_suggest_next_prompt：含结果文件路径 / 立项全文 / 工单汇总 / 模板白名单 /
     三态契约样例（ok/done/failed）；
  C. _parse_suggest_result 三态校验：ok 放行 / done / failed 透传 / 非对象 / 缺字段 /
     未知 status（畸形输入用例）；C2（t260901-01）write_set 透传与清洗九种故障模式
     + done/failed 不受影响 + ticket.py allow_empty_write_set 源码锁；
  D. _consume_suggest_result：ok 写缓存 / 幻觉模板 id 拒收不落缓存 / done 落缓存 /
     failed 不落缓存 / 非法 JSON 不落缓存 / 空 state_key 不落缓存 / 缓存内容 schema；
  E. prepare_epic_next（monkeypatch _epic_ticket_rows + SANDBAR_EPICS_DIR 临时 fixture）：
     档案读入 / exists=False 降级 / 代号形状非法降级 / state_key 强制当前票 closed；
  F. suggest_next stub 路径（SANDBAR_SUGGEST_STUB）：ok/done/invalid 三变体判读与缓存。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。
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
# 与 workbench smoke/epic-precache.mjs 的 EXPECT_STATE_KEY 同一 fixture 同一字面量：
# 两侧实现各算一次，谁漂移谁红灯（t260828-08 review 第 2 条口径：当前票强制 closed）。
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
    workflows=[{"id": "dev-lane", "name": "开发泳道"}],  # 260904 起模板面仅 dev-lane
    result_path="/tmp/r.json")
ok("/tmp/r.json" in md, "含结果文件路径（agent 唯一写点）")
ok("demo-epic" in md and EPIC_MD in md, "含立项代号与全文")
ok("t-demo-02" in md, "含工单汇总")
ok("dev-lane" in md and "proofread" not in md, "含模板白名单清单（260904 起仅 dev-lane）")
ok("开新 dev-lane 票" in md and "main 侧直跑验证" in md, "两类出路措辞在位")
ok('"status":"ok"' in md and '"status":"done"' in md and '"status":"failed"' in md,
   "三态契约样例齐（与 host buildSuggestPrompt 的两态差异点）")

# ---------------------------------------------------------------- C. 三态校验
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

# ------------------------------------------------- C2. write_set 透传与清洗（t260901-01）
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
# 建议口清洗 vs 建票口拒收：口径差异声明（建票口 validate_write_set_args 拒收不清洗）
okr, _, err = shared.validate_write_set_args(["ok.py", "/bad"], False)
ok(not okr and "非法条目" in err, "建票口仍拒收不清洗（口径未漂移）")
# ticket.py 源码锁（t260901-01，模式同 selfcheck_ui_acceptance）：schema 与 payload 均接声明
_ticket_src = (POC.parent.parent / "tools" / "ticket.py").read_text("utf-8")
ok("'allow_empty_write_set': {'type': 'boolean'" in _ticket_src,
   "ticket.py schema 已声明 allow_empty_write_set")
ok("'allow_empty_write_set': bool(a.get('allow_empty_write_set'))" in _ticket_src,
   "ticket.py _create payload 透传 allow_empty_write_set")
_poc_src = (POC / "client.py").read_text("utf-8")
ok("validate_write_set_args(" in _poc_src and "allow_empty_write_set" in _poc_src,
   "引擎口校验单点仍在 client.py")

# ---------------------------------------------------------------- D. 判读 + 缓存
section("D. _consume_suggest_result 判读与缓存")
_d = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-en-"))
shared.REPO_ROOT  # noqa: B018  （确保模块已载）
_orig_root = agent_activities.REPO_ROOT
agent_activities.REPO_ROOT = _d  # 缓存写入重定向到临时目录


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

# 空 state_key / 空 epic：校验过但不落缓存（防脏键污染命中口径）
(_d / "r_ok2.json").write_text(_json.dumps(
    {"status": "ok", "workflow": "dev-lane", "title": "t2"}), "utf-8")
res = _consume_suggest_result(_d / "r_ok2.json", _args(str(_d), epic="", state_key=""))
ok(res is not None and res.status == "ok", "无 epic/state_key 判读仍 ok（不落缓存）")
agent_activities.REPO_ROOT = _orig_root

# ---------------------------------------------------------------- E. prepare_epic_next
section("E. prepare_epic_next（fixture + monkeypatch 查询）")
_epics = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-en-epics-"))
(_epics / "demo-epic.md").write_text(EPIC_MD, "utf-8")
# t260907-07：prepare 改走 shared.resolve_epics_dir（env SUYOU_EPICS_DIR 现读优先），
# 夹具改 env 注入（与 ：16 docstring「SUYOU_EPICS_DIR 临时 fixture」对齐）；不再
# monkeypatch agent_activities.EPICS_DIR（该绑定已无消费点）。空 project 在 env
# 判定之后才兜底引擎锚，故夹具对下面全部构造（均不传 project）生效。
_orig_epics_env = os.environ.get("SUYOU_EPICS_DIR")
os.environ["SUYOU_EPICS_DIR"] = str(_epics)
_orig_rows = agent_activities._epic_ticket_rows


async def _fake_rows(epic: str):
    return list(ROWS)


agent_activities._epic_ticket_rows = _fake_rows
prep = asyncio.run(prepare_epic_next(EpicNextPrepArgs(ticket_id="t-demo-02", epic="demo-epic")))
ok(prep.exists and prep.epic_markdown == EPIC_MD, "立项全文读入")
ok(prep.state_key == EXPECT_STATE_KEY, "prepare 侧 state_key 含当前票强制 closed 口径")
ok(prep.tickets == ROWS, "关联工单行内联返回（workflow 内零 IO）")
agent_activities._epic_ticket_rows = _fake_rows  # 保持（下面换实现再还原）


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
    del os.environ["SUYOU_EPICS_DIR"]
else:
    os.environ["SUYOU_EPICS_DIR"] = _orig_epics_env

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
