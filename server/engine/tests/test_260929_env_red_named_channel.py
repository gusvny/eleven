#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""260929 直修 B1（宿主令·不开票）：环境红**具名通道**（纯加性）回归电池。

背景：集成门每轮固定有 ~11 条「环境红」（供给/共享台跑不起来，exit=2 → 闸判
`not-checked × external`），但此前**只有计数没有名单**——回执/汇总/票面都答不出
「红的是哪几条」。B1 只加具名字段，不改任何判定；本电池锁「新键在场 + 缺键回落为空
+ 既有判定与计数零改动」。

三处生产缝各一条用例，**全部真入口**、离线秒级（无网络/无 Temporal/无 docker；
闸侧用例走桩执行器 + 桩基线，零真 git）：

  A. 执行器（integration/run_scenarios.py）：`INTEG_SUMMARY` 恒带
     `env_red_names`（排序去重名单）+ `env_red_count`（int），判据=本层既有
     `env_like`（exit 2 / spawn -8）；既有键与计数逐项不变、rc 三态语义不变；
     报告落档同带 `env_red_names`。
  B. 闸（server/tools/verify_lane.py `lane=integ`）：回执 `env_red` 取源=**用例级
     权威判决面**（not-checked × external 的判决），**绝不**从文本行
     `ENV_FAIL [...] exit=N` 反推（那条面已知与闸判决不一致：spawn 失败 -8
     执行器记 env、闸按败计）；`green` 判据零改动；无规范行可判（旧执行器形态）
     =空列表。
  C. 引擎（shared.IntegrationRunResult + agent_activities 翻译）：新字段缺省空
     列表（老回放/老回执零漂移）；真回执带键原样透传；缺键/非列表畸形 → 空列表。
"""
import asyncio
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "server" / "engine"))
sys.path.insert(0, str(REPO / "server" / "tools"))

import agent_activities as aa  # noqa: E402
import failure_protocol as fp  # noqa: E402
import shared  # noqa: E402
import verify_lane  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rs_envred_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


# ============================ A. 执行器汇总行 ============================

def _drive(entries, tmp_path, monkeypatch):
    """注入假场景表跑执行器主路径（真 main()），返回 (rc, stdout)。离线秒级。"""
    table = []
    for i, (name, script) in enumerate(entries):
        p = tmp_path / ("s%d.py" % i)
        p.write_text(script, encoding="utf-8")
        table.append((name, "环境红具名通道电池（假场景）", "python3 %s" % p, "ro"))
    monkeypatch.setattr(rs, "SCENARIOS", table)
    monkeypatch.setattr(rs, "_sweep_residue_stages", lambda: None)
    monkeypatch.setattr(rs, "_docker_hygiene", lambda: None)
    monkeypatch.setattr(rs, "batch_preboot", lambda consumers: True)
    monkeypatch.setattr(rs, "batch_teardown", lambda: None)
    monkeypatch.setenv("SANDBAR_POOL_CONC", "1")          # 确定序（池内池间都串行）
    monkeypatch.delenv(rs.RUN_BUDGET_ENV, raising=False)  # 不触预算收口支路
    monkeypatch.delenv("SANDBAR_SCENARIO_EXCLUDE_POOLS", raising=False)
    monkeypatch.chdir(tmp_path)                           # 报告落档进 tmp，不脏工作树
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rs.main()
    return rc, buf.getvalue()


def _summary_of(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            return json.loads(ln[len("INTEG_SUMMARY "):])
    return None


def test_a_env_red_names_present_and_named(tmp_path, monkeypatch):
    """A1：环境红具名（真值）+ 既有键/计数零改动；A2：全绿时键在场且为空。"""
    rc, out = _drive(
        [("zz-env-red", "raise SystemExit(2)\n"),       # 环境面红（判别为哪几条）
         ("zz-prod-red", "raise SystemExit(1)\n"),      # 产品红：不得进环境红名单
         ("zz-green", "print('ok')\n")],
        tmp_path, monkeypatch)
    s = _summary_of(out)
    assert s is not None, out[-2000:]
    # 新键在场（additive）：名单 + 计数
    assert "env_red_names" in s and "env_red_count" in s, sorted(s)
    assert s["env_red_names"] == ["zz-env-red"], s["env_red_names"]
    assert s["env_red_count"] == 1 and isinstance(s["env_red_count"], int), s
    # 既有键与计数一个没动（rc 三态口径照旧：产品红优先 → rc=1）
    for k in ("ran", "pass", "fail", "not_checked", "wall_s", "concurrency",
              "pool_config", "env_fingerprint", "expected", "budget_env", "timings"):
        assert k in s, "既有键丢失：%s" % k
    assert (s["ran"], s["pass"], s["fail"], s["not_checked"]) == (3, 1, 1, 1), s
    assert rc == 1, (rc, out[-800:])
    # 报告落档同带 env_red_names（同名单同源）
    reps = sorted((tmp_path / "out").glob("integration-report-*.json"))
    assert reps, "报告未落档"
    doc = json.loads(reps[-1].read_text(encoding="utf-8"))
    assert doc["env_red_names"] == ["zz-env-red"], doc.get("env_red_names")
    assert doc["env_fail"] == 1 and doc["fail"] == 1, doc


def test_a2_all_green_keeps_key_empty(tmp_path, monkeypatch):
    """A2：全绿轮里新键**在场且为空**（消费方无需分支），rc 三态不变（0）。"""
    rc, out = _drive([("zz-green", "print('ok')\n")], tmp_path, monkeypatch)
    s = _summary_of(out)
    assert rc == 0 and s is not None, out[-800:]
    assert s["env_red_names"] == [] and s["env_red_count"] == 0, s
    assert (s["ran"], s["pass"], s["fail"], s["not_checked"]) == (1, 1, 0, 0), s


# ============================ B. 闸回执 ============================

_STUB_SPEC_ROWS = r'''#!/usr/bin/env python3
import json, sys
def row(name, status, cause, reason, evidence, dur=0.1):
    print(json.dumps({"name": name, "status": status, "cause": cause,
                      "reason": reason, "evidence": evidence, "dur_s": dur}))
row("stub-green", "pass", "", "", "")
# 环境面红：not-checked × external（带证据；闸判 record 不拦=促治理不堵）
row("stub-env-red", "not-checked", "external", "prepare_missing",
    "docker 不可用：共享台起不来（exit=2）")
# 文本三态行另点名一条**只活在文本面**的名字：具名通道**不得**采信它
print("ENV_FAIL [stub-text-only] exit=-8 (0.1s)")
print("SCENARIOS ran=2 pass=1 fail=0 env_fail=1 na=0 (0s)")
print("INTEG_SUMMARY " + json.dumps({
    "ran": 2, "pass": 1, "fail": 0, "not_checked": 1, "wall_s": 0.2,
    "concurrency": 1, "pool_config": "", "expected": 2,
    "env_red_names": ["stub-env-red", "stub-text-only"],
    "env_red_count": 2}))
sys.exit(2)
'''

_STUB_TEXT_ONLY = r'''#!/usr/bin/env python3
import sys
print("ENV_FAIL [stub-legacy-env] exit=2 (0.1s)")
print("SCENARIOS ran=1 pass=0 fail=0 env_fail=1 na=0 (0s)")
sys.exit(2)
'''


def _build_lane(tmp_path, executor_src):
    lane = tmp_path / "lane"
    (lane / "integration").mkdir(parents=True, exist_ok=True)
    (lane / "integration" / "lib_env.py").write_text("# 桩协议库\n", encoding="utf-8")
    (lane / "integration" / "stub_executor.py").write_text(executor_src, encoding="utf-8")
    (lane / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/stub_executor.py\n", encoding="utf-8")
    return lane


def _fake_healthy_baseline(lane):
    """桩基线：满基线在场 + 指纹与泳道相等（真 gated 环境里正常轮就是这一形态）。
    没有它，not-checked 一律降 unknown（「答不了锅不硬裁」），env_red 本就该空。"""
    lane_fp = fp.env_fingerprint(verify_lane._env_fp_parts(lane))

    def _fake(root, cmd, base, timeout, env=None, **kw):
        return True, [], None, "main@stub", lane_fp, None
    return _fake


def test_b_receipt_env_red_comes_from_case_verdict_not_text_line(tmp_path, monkeypatch):
    """B1：回执 `env_red` = 用例级权威判决面名字；文本行名字**不采信**；判定零改动。"""
    lane = _build_lane(tmp_path, _STUB_SPEC_ROWS)
    monkeypatch.setenv("SANDBAR_GATE_BASELINE", "1")
    monkeypatch.setattr(verify_lane, "_run_baseline", _fake_healthy_baseline(lane))
    res = verify_lane.run({"lane": "integ", "path": str(lane)})
    assert "env_red" in res, sorted(res)
    assert res["env_red"] == ["stub-env-red"], res["env_red"]
    # 反面钉：文本面/执行器自报面里的名字都不得进回执（取源=用例级判决，不反推）
    assert "stub-text-only" not in res["env_red"], res["env_red"]
    # `green` 判据零改动：not-checked×external=record 不拦 → 本轮仍绿（促治理不堵）
    assert res["green"] is True, (res["green"], res.get("detail_red"))
    # 既有回执键与文本面计数照旧（-8 那条仍按文本口径计 fail，未被具名通道改写）
    assert (res["ran"], res["pass"], res["fail"], res["env_fail"]) == (1, 0, 1, 0), res
    assert res["cases"] and {c["status"] for c in res["cases"]} == {"pass", "not-checked"}


def test_b2_old_text_only_executor_yields_empty_names(tmp_path, monkeypatch):
    """B2：旧执行器形态（无规范行可判）=空列表（不造名单、不猜），判红口径照旧。"""
    lane = _build_lane(tmp_path, _STUB_TEXT_ONLY)
    monkeypatch.setattr(verify_lane, "_run_baseline", _fake_healthy_baseline(lane))
    res = verify_lane.run({"lane": "integ", "path": str(lane)})
    assert res["env_red"] == [], res.get("env_red")
    assert res["green"] is False and res["env_fail"] == 1, res


# ============================ C. 引擎翻译 ============================

class _FakeProc:
    returncode = 0
    pid = 424242

    def __init__(self, payload):
        self._payload = payload

    async def communicate(self):
        return json.dumps(self._payload).encode("utf-8"), b""


def _run_activity(tmp_path, monkeypatch, result_obj):
    payload = {"ok": True, "result": result_obj}

    async def _fake_create(*argv, **kw):
        return _FakeProc(payload)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    args = shared.IntegrationRunArgs(ticket_id="t260929-b1", worktree=str(tmp_path))
    return asyncio.run(aa.run_integration_tests(args))


def test_c_result_default_is_empty_list():
    """C1：新字段缺省空列表（老回放/老载荷零漂移）。"""
    assert shared.IntegrationRunResult().env_red == []


def test_c_receipt_key_passthrough_and_missing_key_falls_back(tmp_path, monkeypatch):
    """C2：真回执带键 → 原样透传；缺键 → 空列表；非列表畸形 → 空列表（不炸）。"""
    r = _run_activity(tmp_path, monkeypatch, {
        "lane": "integ", "green": True, "ran": 3, "pass": 2, "fail": 0,
        "env_fail": 1, "env_red": ["b-env", "a-env"], "cases": [], "scenarios": []})
    assert r.error == "" and r.env_red == ["b-env", "a-env"], (r.error, r.env_red)
    assert (r.ran, r.passed, r.failed, r.env_fail) == (3, 2, 0, 1)   # 计数零改动
    # 缺键（老闸/老回放形态）→ 空列表，且旧字段照旧带上来
    r2 = _run_activity(tmp_path, monkeypatch, {
        "lane": "integ", "green": True, "ran": 2, "pass": 1, "fail": 0,
        "env_fail": 1, "cases": [], "scenarios": []})
    assert r2.env_red == [] and r2.env_fail == 1, (r2.env_red, r2.env_fail)
    # 非列表畸形（外部输入三态之一）→ 空列表，不抛
    r3 = _run_activity(tmp_path, monkeypatch, {
        "lane": "integ", "green": True, "ran": 1, "pass": 1, "fail": 0,
        "env_fail": 0, "env_red": "zz-env", "cases": [], "scenarios": []})
    assert r3.env_red == [], r3.env_red
