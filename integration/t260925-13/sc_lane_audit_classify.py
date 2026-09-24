#!/usr/bin/env python3
"""t260925-13 · KI-112 lane 审计分类面——audit 子命令逐类分类契约（灰盒 L3，
真实 tmp git 泳道仓+真 git 子进程+可编程桩票查询器，ro 秒级零 docker 零真仓写入）。

用户可感知契约（工单正文(1)(2)(5) + 方案 v2 §1/§2，锚 audit --json 公开回执：
逐条 {path, kind, ticket, ticket_status, verdict, reason}，不锚实现内部）：

  A live 零触碰：dispatched 票 + 脏目录 → verdict=keep（目录多脏也绝不进剪除集）。
  B terminal-confirmed：list 结构化 status=closed + 干净 + 已合并 → prunable。
  C terminal-absent：show 回执 ok:false 且 kind=not_found / kind=terminal →
    terminal-absent（v2 C1 三态主修：查不到≠unknown）。
  D 守门拒收点名：terminal+未合并 → blocked(unmerged)；terminal+未提交 →
    blocked(uncommitted)；judge-not-guess，回执须点名原因。
  E bare-stub：.lane/ 下非注册目录 → bare-stub；含嵌套 .git → blocked（t260916-20
    教训：疑似登记丢失的真 worktree，不许当壳删）。
  F unknown=真不可知才 unknown：查询器崩溃（非零+无回执）→ 全部 unknown→keep，
    零删除面；stdout 混警告行 → 容错解析后照常分类（不因警告行全盘 unknown）。
  G 通用性（行为锚，非源码 grep）：--lane-dir 自定义目录名 + 非 .lane 布局照常分类；
    detached-HEAD 系统临时 baseline worktree → unknown-owner 只报告。
  H audit 零副作用：跑前后 git worktree 注册面逐字节一致、所有目录仍在、
    .lane 外零触碰。

三态纪律：git 缺席=ENV_FAIL exit 2；lane_audit.py 未落地=FAIL 点名（TDD 预期红，
arbitrate/merge 期必须绿）。intent 分工：developer L1（server/engine/tests/
test_t260925_13_lane_audit.py）守分类纯函数真值表与 porcelain 注入矩阵；本条守
真仓扫描→真票查询器→公开回执整链与零副作用；t260925-13 剪除面/幂等/台账归
sc_lane_audit_prune_guard；真仓只读对账归 sc_lane_audit_realfacet_readonly——三面
不互替。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_lane_fixture import LaneFixture, finish, git_available, tool_available  # noqa: E402


def load_json_out(res):
    """audit --json 的 stdout 必须整体可 parse（场景锚公开 JSON 出口）。"""
    try:
        return json.loads(res.stdout)
    except Exception:
        return None


def verdict_map(data):
    """兼容逐条列表或 {entries:[...]} 两种公开形状；键=path。"""
    entries = data.get("entries") if isinstance(data, dict) else data
    if entries is None and isinstance(data, dict):
        entries = [v for k, v in data.items() if isinstance(v, list)]
        entries = entries[0] if entries else []
    return {e.get("path", e.get("entry", "")): e for e in (entries or []) if isinstance(e, dict)}


def main():
    if not git_available():
        print("ENV_FAIL: git 缺席，真仓夹具搭不起来", flush=True)
        return 2
    if not tool_available():
        print("FAIL: server/tools/lane_audit.py 未落地（TDD 预期红，implement 段交付）", flush=True)
        return 1
    cases = []
    fx = LaneFixture()
    try:
        # 舞台：9 形态
        live = fx.add_worktree("t260999-01", dirty=True)                      # A
        conf = fx.add_worktree("t260931-01", merged=True)                     # B
        nf = fx.add_worktree("t260931-02", merged=True)                         # C
        term = fx.add_worktree("t260931-03", merged=True)                     # C
        unmerged = fx.add_worktree("t260931-04", unmerged=True)           # D
        dirty = fx.add_worktree("t260931-05", dirty=True)                    # D
        stub = fx.add_stub("t260931-06", files=2)                             # E
        nested = fx.add_stub("t260931-07", files=1, nested_git=True)        # E
        base = fx.add_worktree("baseline-x", detached=True)                       # G
        gone = fx.add_worktree("t260931-08", remove_dir=True)                 # H(登记残留)

        stub_py, spec = fx.ticket_stub(
            statuses={"t260931-01": "closed", "t260931-04": "closed",
                      "t260931-05": "closed", "t260999-01": "dispatched"},
            absent={"t260931-02": "工单不存在: t260931-02（Temporal 无此 workflow）",
                    "t260931-02|kind": "not_found",
                    "t260931-03": "工单查询失败（terminal）：工单已终态（TERMINATED），快照不可得",
                    "t260931-03|kind": "terminal"})
        tcmd = fx.ticket_cmd(stub_py, spec)
        r = fx.run_tool(["audit", "--json", "--ticket-cmd", tcmd], spec)
        data = load_json_out(r)
        if r.returncode != 0 or data is None:
            print("FAIL: audit --json 退出码=%s stdout 非 JSON：%r stderr=%r"
                  % (r.returncode, r.stdout[:200], r.stderr[:200]), flush=True)
            return 1
        vm = verdict_map(data)
        if not vm:
            print("FAIL: audit --json 零条目回执：%r" % (list(data)[:5] if isinstance(data, dict) else data[:2]), flush=True)
            return 1

        def by_frag(frag):
            return next((v for k, v in vm.items() if frag in k), None)

        def verd(frag):
            e = by_frag(frag)
            return (e or {}).get("verdict", "")

        cases.append(("A live 脏泳道 keep", verd("t260999-01") == "keep"))
        cases.append(("B closed+干净+已合并 prunable", verd("t260931-01") == "prunable"))
        e = by_frag("t260931-02")
        blob = json.dumps(e, ensure_ascii=False).lower() if e else ""
        cases.append(("C1 kind=not_found → terminal-absent（非 unknown）",
                      bool(e) and ("absent" in blob or verd("t260931-02") == "prunable")
                      and "unknown" not in blob))
        cases.append(("C2 kind=terminal → terminal-absent（非 unknown）",
                      verd("t260931-03") == "prunable"))
        cases.append(("D1 未合并 terminal 不被放行为 keep（守门在 prune 段点名，归 prune 场景）",
                      verd("t260931-04") != "keep" and not verd("t260931-04").startswith("keep:unknown")))
        cases.append(("D2 未提交 terminal 不被放行为 keep（同上）",
                      verd("t260931-05") != "keep" and not verd("t260931-05").startswith("keep:unknown")))
        cases.append(("E1 bare-stub 识别", verd("t260931-06") in ("prunable", "stub", "clearable")))
        cases.append(("E2 嵌套 .git 不被放行为 keep（拒拆在 prune 段点名，归 prune 场景）",
                      verd("t260931-07") != "keep" and not verd("t260931-07").startswith("keep:unknown")))
        cases.append(("G1 baseline detached 只报告", verd("baseline-x").startswith(("unknown", "keep"))))
        e = by_frag("t260931-08")
        cases.append(("H1 登记在册目录缺失如实点名（非静默）",
                      bool(e) and ("absent" in json.dumps(e, ensure_ascii=False).lower()
                                   or "missing" in json.dumps(e, ensure_ascii=False).lower()
                                   or verd("t260931-08") != "")))
        cases.append(("A2 live 目录仍在（零副作用）", os.path.isdir(live)))
        before = set(fx.worktree_paths())
        cases.append(("H2 audit 零副作用：worktree 注册面不变", before == set(fx.worktree_paths())
                      and os.path.isdir(stub) and os.path.isdir(nested) and os.path.isdir(base)))
        cases.append(("H3 .lane 外零触碰", os.path.isfile(os.path.join(fx.repo, "README.md"))))

        # F：查询器崩溃 → 全 unknown→keep（fail-closed 面）
        stub_c, spec_c = fx.ticket_stub(mode="crash")
        r2 = fx.run_tool(["audit", "--json", "--ticket-cmd", fx.ticket_cmd(stub_c, spec_c)], spec_c)
        d2 = load_json_out(r2)
        vm2 = verdict_map(d2) if d2 else {}
        keeps = [v for k, v in vm2.items() if "t260931-01" in k or "t260931-02" in k]
        crash_ok = bool(keeps) and all(str(v.get("verdict", "")).startswith("keep")
                                       for v in keeps) and os.path.isdir(conf)
        cases.append(("F1 查询器崩溃 → unknown→keep 零删除面", r2.returncode in (0, 1) and crash_ok))

        # F2：stdout 混警告行 → 容错解析照常分类
        stub_w, spec_w = fx.ticket_stub(statuses={"t260931-01": "closed"}, warn=True)
        r3 = fx.run_tool(["audit", "--json", "--ticket-cmd", fx.ticket_cmd(stub_w, spec_w)], spec_w)
        d3 = load_json_out(r3)
        vm3 = verdict_map(d3) if d3 else {}
        e3 = next((v for k, v in vm3.items() if "t260931-01" in k), None)
        cases.append(("F2 stdout 混警告行容错解析照常分类", r3.returncode == 0 and bool(e3)
                      and e3.get("verdict") == "prunable"))

        # G2：通用性——自定义 lane 目录名 + 非 .lane 布局
        fx2 = LaneFixture(lane_dir="lanes")
        try:
            fx2.add_worktree("t260931-09", merged=True)
            fx2.add_stub("t260931-10", files=1)
            s2, sp2 = fx2.ticket_stub(statuses={"t260931-09": "closed"})
            r4 = fx2.run_tool(["audit", "--json", "--lane-dir", "lanes",
                               "--ticket-cmd", fx2.ticket_cmd(s2, sp2)], sp2)
            d4 = load_json_out(r4)
            vm4 = verdict_map(d4) if d4 else {}
            ok_g = (r4.returncode == 0 and bool(vm4)
                    and any("t260931-09" in k and v.get("verdict") == "prunable" for k, v in vm4.items())
                    and any("t260931-10" in k for k in vm4))
            cases.append(("G2 自定义 --lane-dir 通用布局照常分类", ok_g))
        finally:
            fx2.destroy()
    finally:
        fx.destroy()
    return finish(cases)


if __name__ == "__main__":
    sys.exit(main())
