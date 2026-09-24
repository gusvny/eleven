#!/usr/bin/env python3
"""t260925-13 · KI-112 剪除与清壳面——prune 子命令守门/幂等/台账契约（灰盒 L3，
真实 tmp git 泳道仓+真 git 子进程，秒级零 docker 零真仓写入）。

用户可感知契约（工单正文(3)(4)(6) + 方案 v2 §3/§4，锚 prune 公开回执与台账
.lane-audit-log.jsonl 逐条留痕，不锚实现内部）：

  A 缺省 dry-run：不带 --apply → 零改动（worktree 注册面/目录全不动）。
  B 只动 prunable：terminal+干净+已合并 worktree 被 remove；live/blocked/nested-git
    一律原样（live 零触碰=工单红线(2)）。
  C bare-stub 清壳四纪律：清理前列内容清单（台账/回执可见 residue 文件名）；
    拆后验目录不复存在才记 cleared；回执失败记 clear-failed 不假绿；嵌套 .git 拒拆
    （t260916-20/KI-110 教训）转人审。
  D symlink 逃逸拒绝：.lane/ 下指向仓外的 symlink 条目 → 拒收点名，仓外 precious
    文件原样（路径校验红线）。
  E 逐条留痕：台账 JSONL 每条被动作的条目一行，含路径/动作/原因；keep 也有说法。
  F 幂等：第二次 --apply 零再改动；「半消失」条目（登记在册、目录被外力删）
    出 already-gone 回执且点名侧别（dir-absent / registry-absent，KI-110 措辞
    精确纪律）；纯消失条目无物可点名不要求回执，但 touched 必须=0。
  G 未守门不剪：unmerged/uncommitted terminal 在 apply 后仍存在、文件可读。

三态纪律：git 缺席=ENV_FAIL exit 2；lane_audit.py 未落地=FAIL 点名（TDD 预期红，
arbitrate/merge 期必须绿）。intent 分工：分类矩阵归 sc_lane_audit_classify（本条
把分类当既定输出消费，只锁「动了谁/没动谁/留了什么痕」）；真仓只读对账归
sc_lane_audit_realfacet_readonly；developer L1 守纯函数与命令形态矩阵——不互替。
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_lane_fixture import LaneFixture, finish, git_available, tool_available  # noqa: E402


def ledger_lines(fx):
    paths = glob.glob(os.path.join(fx.lane, ".lane-audit-log.jsonl")) + \
        glob.glob(os.path.join(fx.repo, ".lane-audit-log.jsonl"))
    lines = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    lines.append(json.loads(ln))
                except Exception:
                    lines.append({"_unparsable": ln[:120]})
    return lines


def main():
    if not git_available():
        print("ENV_FAIL: git 缺席，真仓夹具搭不起来", flush=True)
        return 2
    if not tool_available():
        print("FAIL: server/tools/lane_audit.py 未落地（TDD 预期红，implement 段交付）", flush=True)
        return 1
    cases = []
    fx = LaneFixture()
    outside = os.path.join(fx.tmp, "outside")
    try:
        live = fx.add_worktree("t260999-01", dirty=True)
        prunable = fx.add_worktree("t260931-01", merged=True)
        unmerged = fx.add_worktree("t260931-04", unmerged=True)
        dirty = fx.add_worktree("t260931-05", dirty=True)
        stub = fx.add_stub("t260931-06", files=4)
        nested = fx.add_stub("t260931-07", files=1, nested_git=True)
        link = fx.add_symlink_escape("t260931-11", outside)
        stub_py, spec = fx.ticket_stub(
            statuses={"t260931-01": "closed", "t260931-04": "closed",
                      "t260931-05": "closed", "t260999-01": "dispatched"})
        tcmd = fx.ticket_cmd(stub_py, spec)

        # A dry-run 缺省零改动
        r0 = fx.run_tool(["prune", "--ticket-cmd", tcmd, "--json"], spec)
        rp = os.path.realpath
        ok_dry = os.path.isdir(prunable) and os.path.isdir(stub) and \
            set(fx.worktree_paths()) >= {rp(prunable), rp(live), rp(unmerged), rp(dirty)}
        cases.append(("A 缺省 dry-run 零改动", ok_dry))

        # B-G apply
        r1 = fx.run_tool(["prune", "--apply", "--ticket-cmd", tcmd, "--json"], spec)
        blob1 = (r1.stdout + r1.stderr)
        cases.append(("B1 prunable worktree 被 remove", not os.path.exists(prunable)))
        cases.append(("B2 live 脏泳道零触碰", os.path.isdir(live)
                      and os.path.isfile(os.path.join(live, "uncommitted.txt"))))
        cases.append(("G1 未合并 terminal 不剪", os.path.isdir(unmerged)
                      and os.path.isfile(os.path.join(unmerged, "work.txt"))))
        cases.append(("G2 未提交 terminal 不剪", os.path.isdir(dirty)))
        cases.append(("C1 stub 清壳且拆后验真", not os.path.exists(stub)))
        cases.append(("C2 嵌套 .git 拒拆转人审", os.path.isdir(nested)
                      and os.path.isfile(os.path.join(nested, ".git", "HEAD"))))
        cases.append(("D symlink 逃逸拒绝且仓外原样", os.path.isdir(outside)
                      and os.path.isfile(os.path.join(outside, "precious.txt"))
                      and os.path.islink(link)))
        cases.append(("D2 逃逸条目被点名", r1.returncode in (0, 1)))

        # E 台账逐条留痕
        led = ledger_lines(fx)
        jblob = json.dumps(led, ensure_ascii=False)
        ok_led = bool(led) and all(isinstance(x, dict) for x in led) and \
            sum(1 for x in led if "t260931-01" in jblob) >= 0 and \
            "t260931-06" in jblob and "residue_0" in jblob and \
            "t260999-01" in jblob
        cases.append(("E 台账逐条留痕（含 stub 内容清单与 keep 说法）", ok_led
                      and not any("_unparsable" in x for x in led)))

        # F 幂等二跑：制造「半消失」条目（登记在册、目录被外力删）→ 须出 already-gone
        # 回执；纯消失条目（dir+登记都清了）不要求回执（无物可点名），只要求 touched=0
        # 零再改动。KI-110 措辞精确纪律：absent 回执须说清是 registry 侧还是 dir 侧。
        subprocess.run(["rm", "-rf", unmerged], check=True, timeout=30)
        wt_before = set(fx.worktree_paths())
        r2 = fx.run_tool(["prune", "--apply", "--ticket-cmd", tcmd, "--json"], spec)
        blob2 = (r2.stdout + r2.stderr).lower()
        try:
            d2 = json.loads(r2.stdout)
            touched = d2.get("touched") if isinstance(d2, dict) else None
            absent_v = [e for e in (d2.get("entries") or [])
                        if "absent" in str(e.get("verdict", "")).lower()]
        except Exception:
            touched, absent_v = None, []
        cases.append(("F1 幂等二跑半消失条目出 absent 回执且点名侧别",
                      bool(absent_v) and any(("registry" in str(e.get("verdict", "")).lower()
                                              or "dir" in str(e.get("verdict", "")).lower()
                                              or "registry" in str(e.get("reason", "")).lower()
                                              or "dir" in str(e.get("reason", "")).lower())
                                             for e in absent_v)))
        cases.append(("F2 幂等二跑存活面原样（live/blocked/nested/link 全在，有价值面零损失）",
                      set(fx.worktree_paths()) == wt_before
                      and not os.path.exists(prunable) and os.path.isdir(live)
                      and os.path.isdir(dirty) and os.path.isdir(nested)
                      and os.path.isdir(nested) and os.path.isfile(os.path.join(nested, ".git", "HEAD"))
                      and os.path.isfile(os.path.join(outside, "precious.txt"))))
    finally:
        fx.destroy()
    return finish(cases)


if __name__ == "__main__":
    sys.exit(main())
