#!/usr/bin/env python3
# t260924 巡检拆除诚实性回归棒（宿主 260924 直修令「全修好」；事故回归纪律：一修一棒）。
# 棒1 预算错配：审查预算缺省 60 分钟（260923/260924 连续超时空壳的根）。
# 棒2 拆后验证+幂等精确化：teardown_lane 假「已清」治理（目录壳残留点名）+幂等
#     形态（is not a working tree / not found）不再谎报失败。
# 棒3 清扫认目录壳：sweep_inspection_lanes 收「裸目录壳」形态 + 嵌套仓拒拆守卫。
# 棒4 agent_home 泳道锚守卫：sanitize_agent_home 纯函数矩阵。
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENG = os.path.join(ROOT, "server", "engine")
sys.path.insert(0, ENG)

P = F = 0


def ok(cond, label):
    global P, F
    if cond:
        P += 1
        print("ok    " + label)
    else:
        F += 1
        print("FAIL  " + label)


# ---------- 棒1：审查预算 ----------
from inspection_inspect import (DEFAULT_INSPECT_TIMEOUT_MIN,  # noqa: E402
                                INSPECT_DEADLINE_MARGIN_SEC,
                                sanitize_agent_home, sweep_stub_dir_names)
ok(DEFAULT_INSPECT_TIMEOUT_MIN == 60, "审查预算缺省=60 分钟（260924 调大定值）")
ok(DEFAULT_INSPECT_TIMEOUT_MIN * 60 > INSPECT_DEADLINE_MARGIN_SEC, "预算>复核余量（不等式形状）")

# ---------- 棒2/3：agent_activities 源序锁 ----------
src = open(os.path.join(ENG, "agent_activities.py"), encoding="utf-8").read()
ok('"is not a working tree" not in err' in src, "幂等形态①登记本就无=静默（不谎报警）")
ok('"not found" not in err' in src, "幂等形态②分支本就无=静默（不谎报警）")
ok("目录壳残留：%s（worktree 登记/分支已清；目录未除）" in src,
   "拆后逐 tree 验目录：壳在即点名（假「已清」治理）")
ok(src.count("removed_dir_stubs") >= 1, "清扫回执带 removed_dir_stubs 面（写侧）")
flow_src = open(os.path.join(ENG, "inspection_flow.py"), encoding="utf-8").read()
ok(flow_src.count("removed_dir_stubs") >= 2 and "目录壳 %d" in flow_src,
   "拆除回落渲染读 removed_dir_stubs 并点名目录壳数（读侧）")
ok("未注册嵌套仓形态" in src and "shutil.rmtree" in src and "stub_embedded_repo" in src,
   "清扫认裸目录壳 + 三态守卫接线")
ok(src.count("sanitize_agent_home(") == 1, "agent_home 守卫唯一接线点")

# ---------- 棒4：纯函数矩阵 ----------
import pathlib  # noqa: E402
tmp_home = pathlib.Path("/tmp/agent-home-t260924/x")
fb = pathlib.Path("/fallback/agent-home")
h, note = sanitize_agent_home(tmp_home, fb, "it-1")
ok(h == tmp_home and note == "", "/tmp 隔离台不受影响（无 .lane 段原样放行）")
lane_home = pathlib.Path("/repo/.lane/inspection-integration-tests-20260924/server/engine/out/x")
h, note = sanitize_agent_home(lane_home, fb, "it-1")
ok(h == fb / "it-1" and "泳道锚回落" in note, "泳道锚（.lane 段）回落主仓并点名")
h, note = sanitize_agent_home(pathlib.Path("/repo/lane-x/home"), fb, "it-1")
ok(h == pathlib.Path("/repo/lane-x/home") and note == "", "整段匹配才拦（.lanefoo 之类不误伤）")
from inspection_inspect import stub_embedded_repo  # noqa: E402
listing = ["inspection-integration-tests-20260924", "integration-tests-20260924",
           "inspection-integration-tests-20260925", "t260922-04", "dev-x"]
ok(sweep_stub_dir_names(listing, "integration-tests", target="20260924")
   == ["inspection-integration-tests-20260924", "integration-tests-20260924"],
   "定向态：本期两形都收、别期/开发泳道不碰")
ok(sweep_stub_dir_names(listing, "integration-tests", keep="20260926")
   == ["inspection-integration-tests-20260924", "inspection-integration-tests-20260925",
       "integration-tests-20260924"],
   "水位态：早于水位的壳自愈面（20260926 本期不出手）")
ok(sweep_stub_dir_names(listing, "integration-tests") == []
   and sweep_stub_dir_names(listing, "") == [],
   "空 instance/双空=[]（判不准不动）")
ok(sweep_stub_dir_names(["inspection-integration-tests-x1", "integration-tests-abc"], "integration-tests",
                        target="20260924") == [],
   "非数字期号不收（畸形名判不准不动）")
# 三态守卫矩阵（260926 验货精修：worktree 痕迹 vs 真仓）
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    t = pathlib.Path(td)
    a = t / "gitfile_stub"; a.mkdir(); (a / ".git").write_text("gitdir: ../x")
    (a / "junk.txt").write_text("x")
    ok(stub_embedded_repo(a) is None, "态①顶层 .git 文件=worktree 痕迹，壳可清（不误伤）")
    b = t / "repo_stub"; b.mkdir(); (b / ".git").mkdir()
    ok(stub_embedded_repo(b) == b / ".git", "态②顶层 .git 目录=独立仓根，拒拆点名")
    c = t / "nested_stub"; c.mkdir(); (c / "sub").mkdir(); (c / "sub" / ".git").mkdir()
    ok(stub_embedded_repo(c) == c / "sub" / ".git", "态③嵌套 .git=未注册嵌套仓，拒拆点名")
    d = t / "bare_stub"; d.mkdir(); (d / "agent-home").mkdir()
    ok(stub_embedded_repo(d) is None, "纯杂物壳（无任何 .git）可清")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (P, F))
sys.exit(1 if F else 0)
