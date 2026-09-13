"""t260913-03 池排除旋钮：verify_lane integ 道消费/例外腿/缺省零回归（L1 电池）。

fixture 泳道（tmp_path）= 迷你 verify.yaml + 迷你注册表 + 桩执行器（桩把所见 env
写进 env_probe.txt，隔离注入有无可断言）：

- a 无声明 + apply=true → 行为与现状一致（env 不注入）——零回归锚；
- b 声明在场 + 不传 apply（巡检/手动形态）→ 恒全跑（验收 E 负锁）；
- c 声明 + apply + write_set 不相交 → env 注入、回执 applied/excluded_count；
- d write_set 命中声明 force_assets → 不注 env、forced_by 点名（验收 D 正腿）；
- e write_set 命中泳道派生资产（import 面）→ forced（R5 闭包腿）；
- f write_set 目录前缀 → forced（前缀语义）；
- g 派生入口失败/泳道缺执行器 → 红 fail-closed 点名、cmd 未跑；
- h 声明畸形 → 整道红 fail-closed；
- i 基线子进程同注 env（红腿时基线口径与泳道一致）；
- j 引擎载荷缺省不透传策略 + dev_lane 唯一 true 站（验收 E 机械锁）；
- k TOOL schema 面暴露 apply_skip_pools（additionalProperties: False 面）。

UT 全程禁网络/真 Temporal/真 git：fixture 泳道是 tmp 目录，桩执行器是本机子进程。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import verify_lane  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shared  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
ENV_KEY = "SANDBAR_SCENARIO_EXCLUDE_POOLS"

MINI_REGISTRY = '''#!/usr/bin/env python3
import json, sys
if "--print-pool-assets" in sys.argv:
    i = sys.argv.index("--print-pool-assets")
    pools = [p for p in (sys.argv[i + 1] if i + 1 < len(sys.argv) else "").split(",") if p]
    unknown = [p for p in pools if p not in ("main", "engine", "exclusive")]
    if unknown:
        sys.stderr.write("未知池：%s\\n" % ",".join(unknown))
        sys.exit(2)
    print(json.dumps({"pools": pools,
                      "assets": ["integration/stub_executor.py", "integration/lib_env.py"],
                      "warnings": []}))
    sys.exit(0)
sys.exit(0)
'''

MINI_REGISTRY_BAD = '''#!/usr/bin/env python3
import sys
sys.stderr.write("派生入口自报坏：注册表读不了\\n")
sys.exit(2)
'''

STUB_OK = '''#!/usr/bin/env python3
import json, os
val = os.environ.get("SANDBAR_SCENARIO_EXCLUDE_POOLS")
open("env_probe.txt", "w").write(val if val is not None else "<unset>")
ex = [p for p in (val or "").split(",") if p]
if ex:
    print("本轮跳过池=%s（少 2 条）" % ",".join(ex))
print("PASS [stub-a] (0.1s)")
print("SCENARIOS ran=1 pass=1 fail=0 env_fail=0 na=0 (0s)")
print("INTEG_SUMMARY " + json.dumps({
    "ran": 1, "pass": 1, "fail": 0, "not_checked": 0, "wall_s": 0.1,
    "concurrency": 1, "pool_config": "", "expected": 1,
    "excluded_pools": ex, "excluded_count": (2 if ex else 0)}))
'''

STUB_RED = '''#!/usr/bin/env python3
import json, os, sys
val = os.environ.get("SANDBAR_SCENARIO_EXCLUDE_POOLS")
open("env_probe.txt", "w").write(val if val is not None else "<unset>")
print("FAIL [stub-red] exit=1")
print("SCENARIOS ran=1 pass=0 fail=1 env_fail=0 na=0 (0s)")
print("INTEG_SUMMARY " + json.dumps({
    "ran": 1, "pass": 0, "fail": 1, "not_checked": 0, "wall_s": 0.1,
    "concurrency": 1, "pool_config": "", "expected": 1}))
sys.exit(1)
'''

DECL = ["  exclude_pools: engine,exclusive",
        "  exclude_pools_force_assets:",
        "    - integration/stage_docker.py",
        "    - server/docker-compose.test.yml"]


def build_lane(tmp_path, decl_lines=(), registry=MINI_REGISTRY, executor=STUB_OK):
    lane = tmp_path / "lane"
    (lane / "integration").mkdir(parents=True, exist_ok=True)
    (lane / "integration" / "run_scenarios.py").write_text(registry, encoding="utf-8")
    (lane / "integration" / "stub_executor.py").write_text(executor, encoding="utf-8")
    (lane / "integration" / "lib_env.py").write_text("# 桩协议库\n", encoding="utf-8")
    lines = ["schema: v1",
             "lanes:",
             "  code:",
             "    write_allow:",
             "      - integration/",
             "integration:",
             "  cmd: python3 integration/stub_executor.py"]
    lines += list(decl_lines)
    (lane / "verify.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lane


def probe_of(lane):
    p = lane / "env_probe.txt"
    return p.read_text(encoding="utf-8") if p.is_file() else None


def run_lane(lane, **kw):
    args = {"lane": "integ", "path": str(lane)}
    args.update(kw)
    return verify_lane.run(args)


def excluded_of(res):
    return (res.get("pool_exclude") or {})


# ---------------- a/b 零回归与巡检负锁 ----------------

def test_a_no_declaration_apply_is_inert(tmp_path):
    lane = build_lane(tmp_path)
    res = run_lane(lane, apply_skip_pools=True)
    assert res["green"] is True, res
    assert probe_of(lane) == "<unset>"
    assert "pool_exclude" not in res


def test_b_declaration_without_apply_runs_everything(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane)
    assert res["green"] is True, res
    assert probe_of(lane) == "<unset>"
    assert "pool_exclude" not in res


# ---------------- c/d/e/f 过滤与例外腿 ----------------

def test_c_disjoint_write_set_injects_declaration(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane, apply_skip_pools=True, write_set=["server/engine/shared.py"])
    assert res["green"] is True, res
    assert probe_of(lane) == "engine,exclusive"
    pe = excluded_of(res)
    assert pe.get("applied") is True
    assert pe.get("declared") == ["engine", "exclusive"]
    assert pe.get("excluded_count") == 2


def test_d_declared_force_asset_forces_full_run(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane, apply_skip_pools=True,
                   write_set=["integration/stage_docker.py"])
    assert probe_of(lane) == "<unset>"
    pe = excluded_of(res)
    assert pe.get("applied") is False
    assert "integration/stage_docker.py" in (pe.get("forced_by") or [])


def test_e_derived_asset_forces_full_run(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane, apply_skip_pools=True, write_set=["integration/lib_env.py"])
    assert probe_of(lane) == "<unset>"
    assert "integration/lib_env.py" in (excluded_of(res).get("forced_by") or [])


def test_f_directory_prefix_forces_full_run(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane, apply_skip_pools=True, write_set=["integration/"])
    assert probe_of(lane) == "<unset>"
    pe = excluded_of(res)
    assert pe.get("applied") is False and pe.get("forced_by")


def test_f2_declared_server_asset_forces_full_run(tmp_path):
    lane = build_lane(tmp_path, DECL)
    res = run_lane(lane, apply_skip_pools=True,
                   write_set=["server/docker-compose.test.yml"])
    assert probe_of(lane) == "<unset>"
    assert "server/docker-compose.test.yml" in (excluded_of(res).get("forced_by") or [])


# ---------------- g/h fail-closed ----------------

def test_g1_derivation_failure_is_fail_closed(tmp_path):
    lane = build_lane(tmp_path, DECL, registry=MINI_REGISTRY_BAD)
    res = run_lane(lane, apply_skip_pools=True, write_set=["server/engine/shared.py"])
    assert res["green"] is False
    assert "派生失败" in (res.get("err") or "")
    assert probe_of(lane) is None


def test_g2_missing_runner_is_fail_closed(tmp_path):
    lane = build_lane(tmp_path, DECL)
    (lane / "integration" / "run_scenarios.py").unlink()
    res = run_lane(lane, apply_skip_pools=True, write_set=["server/engine/shared.py"])
    assert res["green"] is False
    assert "run_scenarios.py" in (res.get("err") or "")
    assert probe_of(lane) is None


@pytest.mark.parametrize("decl", [
    ["  exclude_pools: Engine"],
    ["  exclude_pools: engine engine"],
    ["  exclude_pools:"],
    ["  exclude_pools_force_assets: []"],
    ["  exclude_pools_force_assets: integration/stage_docker.py"],
])
def test_h_malformed_declaration_fails_closed(tmp_path, decl):
    lane = build_lane(tmp_path, decl)
    res = run_lane(lane, apply_skip_pools=True)
    assert res["green"] is False
    assert res.get("err")
    assert probe_of(lane) is None


# ---------------- i 基线同 env ----------------

def test_i_baseline_inherits_exclude_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_GATE_BASELINE", "1")
    captured = {}

    def fake_baseline(root, cmd, base, timeout, env=None, **kw):
        captured["env"] = env
        return True, [], None, "main", None

    monkeypatch.setattr(verify_lane, "_run_baseline", fake_baseline)
    lane = build_lane(tmp_path, DECL, executor=STUB_RED)
    run_lane(lane, apply_skip_pools=True, write_set=["server/engine/shared.py"])
    assert captured.get("env"), "基线未被调用或 env 未透传"
    assert captured["env"].get(ENV_KEY) == "engine,exclusive"


# ---------------- j/k 引擎侧机械锁与 schema 面 ----------------

def test_j_payload_default_never_enables_policy():
    payload = shared.integ_verify_payload("/tmp/lane-x")
    assert payload == {"lane": "integ", "path": "/tmp/lane-x", "baseline": True,
                       "write_set": [], "apply_skip_pools": False}
    args = shared.IntegrationRunArgs(ticket_id="t913", worktree="/tmp/lane-x")
    assert args.apply_skip_pools is False and args.write_set == []
    assert shared.integ_verify_payload("/tmp/lane-x", args.write_set,
                                       args.apply_skip_pools)["apply_skip_pools"] is False


def test_j2_dev_lane_is_the_only_true_site():
    lane_src = (REPO / "server" / "engine" / "dev_lane.py").read_text(encoding="utf-8")
    act_src = (REPO / "server" / "engine" / "agent_activities.py").read_text(encoding="utf-8")
    assert lane_src.count("apply_skip_pools=True") == 1
    assert "apply_skip_pools=True" not in act_src


def test_k_tool_schema_exposes_apply_flag():
    props = verify_lane.TOOL["parameters"]["properties"]
    assert props["apply_skip_pools"]["type"] == "boolean"
    assert verify_lane.TOOL["parameters"]["additionalProperties"] is False
