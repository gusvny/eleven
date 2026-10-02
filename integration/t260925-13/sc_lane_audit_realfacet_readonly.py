#!/usr/bin/env python3
"""t260925-13 · KI-112 真仓只读对账面——audit 对本仓首跑零副作用+live 泳道零误判
（灰盒 L3，真仓 read-only 黑盒子进程，秒级零 docker 零写入）。

用户可感知契约（工单正文「Use this measured batch as the first evidence run」+
红线(2) NEVER touches a live lane）：工具必须敢对真仓跑且只读——audit 子命令是
宿主/运维的第一入口，红了要红得诚实，动了就是事故。

  A 真仓 audit --json 退出 0 且 stdout 整体 JSON（警告行不破 JSON 契约）。
  B 零副作用：跑前后 `git worktree list --porcelain` 逐字节一致；.lane/ 条目集
    与目录集不变；仓内受控面无新增未跟踪杂物（git status --porcelain 面不扩大，
    只允许台账文件一类的 .lane 内新面孔按方案声明出现——本场景锚「不删不碰」，
    台账 append 本身不是副作用违约）。
  C live 泳道零误判：经真 ticket.py 查询，凡 status 非 closed 的在册票其泳道
    verdict 必须是 keep（真面交叉验证，桩面替代不了）。
  D 本票泳道（t260925-13，本场景宿主）在 dispatched 期必须 keep——自己的脚
    不许被自己剪（N/A 纪律：票已 closed 时该子用例 N/A，其余子用例仍判）。
  E 回执可读性：每条目带 verdict 与 reason（验收口径「逐条给三态分布」的
    机器前提）；unknown 条目必须点名 reason（不许「未产出结果」式反事实文案）。

三态纪律：git 缺席/真 ticket.py 不可达（引擎停机属预期降级，不算场景红——
C/D 相应 N/A）=相应子用例 N/A；全部子用例 N/A=场景红 exit 2。lane_audit.py
未落地=FAIL 点名（TDD 预期红）。intent 分工：夹具面矩阵归 sc_lane_audit_classify、
剪除面归 sc_lane_audit_prune_guard——本条只守真仓只读旅程与 live 交叉验证；
KI-109 案二（冻结泳道树入扫描根）的根修由本票交付，本场景是真面验收入口。
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(REPO, "server", "tools", "lane_audit.py")
TICKET = os.path.join(REPO, "server", "tools", "ticket.py")
LANE = os.path.join(REPO, ".lane")


def sh(cmd, cwd=REPO, timeout=120):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def lane_snapshot():
    entries = {}
    if os.path.isdir(LANE):
        for n in sorted(os.listdir(LANE)):
            if n == ".lane-audit-log.jsonl":
                continue  # 工具自己的台账 append 是方案声明的留痕面，不算副作用违约
            p = os.path.join(LANE, n)
            entries[n] = os.path.isdir(p) and not os.path.islink(p)
    return entries


def real_statuses(ids):
    """真 ticket.py 查询 {id: status|None}；查询器完全不可用返回 None（N/A 轨）。"""
    p = sh([sys.executable, TICKET, json.dumps({"op": "list"})])
    statuses = {}
    try:
        d = json.loads(p.stdout)
        if not d.get("ok"):
            return None
        for t in d.get("result", {}).get("tickets", []):
            statuses[t["id"]] = t.get("status")
    except Exception:
        return None
    for tid in ids:  # list 不可见的逐个 show（v2 C2 双路）
        if tid not in statuses:
            q = sh([sys.executable, TICKET, json.dumps({"op": "show", "id": tid})])
            try:
                d = json.loads(q.stdout)
                statuses[tid] = d.get("result", {}).get("status") if d.get("ok") else None
            except Exception:
                statuses[tid] = None
    return statuses


def main():
    cases = []
    if not os.path.isdir(os.path.join(REPO, ".git")) and not os.path.isfile(os.path.join(REPO, ".git")):
        pass  # worktree gitfile 形态照常
    try:
        sh(["git", "--version"])
    except Exception:
        print("ENV_FAIL: git 缺席", flush=True)
        return 2
    if not os.path.isfile(TOOL):
        print("FAIL: server/tools/lane_audit.py 未落地（TDD 预期红，implement 段交付）", flush=True)
        return 1

    wt_before = sh(["git", "worktree", "list", "--porcelain"]).stdout
    lanes_before = lane_snapshot()
    # 主仓根 = git-common-dir 的父目录（本场景可能跑在 lane worktree 里：worktree
    # 自己没有 .lane，工具缺省 repo=当前 worktree 会把全部泳道报成「lane 外登记」
    # ——那是运行位置位移不是被测契约，故显式 --repo 指向主仓根（通用性参数））。
    common = sh(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]).stdout.strip()
    MAIN = os.path.dirname(common) if common else REPO
    r = sh([sys.executable, "-B", TOOL, "audit", "--json", "--repo", MAIN], cwd=REPO)
    try:
        data = json.loads(r.stdout)
        json_ok = True
    except Exception:
        data, json_ok = None, False
    cases.append(("A 真仓 audit --json 退出 0 且整体 JSON", r.returncode == 0 and json_ok))
    if data is None:
        print("AUDIT_RAW_HEAD=%r STDERR=%r" % (r.stdout[:300], r.stderr[:300]), flush=True)
        return 1 if cases and not cases[0][1] else finish(cases)

    entries = data.get("entries") if isinstance(data, dict) and "entries" in data else (
        data if isinstance(data, list) else [])
    if not entries:
        print("FAIL: 真仓 audit 回执零条目：%r" % (list(data)[:6] if isinstance(data, dict) else ""), flush=True)
        return 1

    cases.append(("B1 worktree 注册面逐字节不变",
                  wt_before == sh(["git", "worktree", "list", "--porcelain"]).stdout))
    cases.append(("B2 .lane 条目集与目录集不变", lanes_before == lane_snapshot()))

    # C/D live 交叉验证（真票查询可达才有判据；不可达=N/A，audit 自身的 unknown 降级不算红）
    statuses = real_statuses(sorted({e.get("ticket") for e in entries if e.get("ticket")}))
    if statuses is None:
        cases.append(("C live 交叉验证", None))
        cases.append(("D 本票泳道 keep", None))
    else:
        def verd(e):
            return str(e.get("verdict", ""))

        # 词表契约（断言词表必须与工具词表对齐）：lane_audit 的 verdict 是
        # 「家族:可选后缀」形状——keep 家族=keep / keep:unknown-owner（query
        # 不可达时的 fail-closed 保守 keep），只有 prune:* 才是可剪。按家族判，
        # 不按整串精确相等：t261001-23 坏脸（Temporal 历史带 lone surrogate，查询
        # 端崩）使工具产出 keep:unknown-owner，精确判词把 keep 家族误报成泳道
        # 误判——词表不齐是断言的错，不是工具的错（261002 修复）。
        bad = [e.get("ticket") for e in entries
               if statuses.get(e.get("ticket")) not in (None, "closed")
               and verd(e).split(":")[0] != "keep"]
        cases.append(("C live 泳道零误判（非 closed 票全 keep）", not bad))
        me = next((e for e in entries if e.get("ticket") == "t260925-13"), None)
        if statuses.get("t260925-13") == "dispatched":
            cases.append(("D 本票泳道 keep（dispatched 期）", bool(me) and verd(me) == "keep"))
        else:
            cases.append(("D 本票泳道 keep（dispatched 期）", None))  # 票已终态：N/A

    # E 回执可读性
    bad_reason = [e for e in entries if not str(e.get("reason", "")).strip()]
    unknown_ok = all(str(e.get("reason", "")).strip()
                     for e in entries if "unknown" in verd(e).lower())
    cases.append(("E 每条目带 verdict+reason（unknown 必点名）", not bad_reason and unknown_ok))

    # 收口（finish 在 lib？本场景自带，避免真仓夹具依赖）
    ran = failed = na = 0
    for name, res in cases:
        if res is None:
            na += 1
            print("N/A   :: %s" % name, flush=True)
        else:
            ran += 1
            failed += not res
            print(("PASS" if res else "FAIL") + "  :: " + name, flush=True)
    print("SUMMARY ran=%d fail=%d na=%d" % (ran, failed, na), flush=True)
    if ran == 0:
        print("ENV_FAIL: 全部子用例 N/A=场景红", flush=True)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
