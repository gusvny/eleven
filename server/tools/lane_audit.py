#!/usr/bin/env python3
"""lane_audit —— 泳道残留审计+清理工具（t260925-13，KI-112）。

可重复、留痕、fail-closed 的 `.lane/` 审计+清理能力，非一次性手删：
分类每个 lane 条目（live-lane / terminal-ticket-worktree / bare-stub / unknown-owner /
baseline），绝不动 live 票，拒收并点名有未提交/未合并工作的条目，剪 terminal
worktree、清 bare stub，逐条记台账，幂等可重跑，项目相对路径无 sandbar 硬编码。

票状态三态（评审 C1 定据，全部锚定回执结构化字段，文案只作辅助留痕）：
- terminal-confirmed：list 回执该票 status=closed（terminal 集合={closed}；状态机
  dispatched→settled→verified→closed/rework，verified 保守不含，cancelled 非状态）；
- terminal-absent：回执 ok=false 且结构化 kind ∈ {not_found, terminal}
  （ticket.py QueryError kind：404 not_found=工单不存在；410 terminal=已终态
  TERMINATED 快照不可得）——可剪，仍受未提交+未合并双守门；
- unknown：查询器不可达/非零且回执不可判读/stdout 提取不出合法 JSON/票 id 解析失败
  → keep。语义=真不可知才 unknown；「查询明确说了终态/不存在」不落此态。

bare-stub 清理四条纪律（KI-110 / t260916-20 故障模式取舍清单，逐条有单测）：
1. 先递归列目录内容清单入台账，后删；
2. 嵌套 .git 拒拆（疑似登记丢失的真 worktree）→ blocked:nested-git 转人审；
3. 拆后验目录不复存在才记 cleared（防凭 rc 假绿），否则 clear-failed 点名；
4. already-gone 措辞区分 dir-absent（目录已不在）/ registry-absent（登记已不在）。

参考既有实现声明：不照搬既有清扫实现；上述四条即显式带过来的故障模式清单；
另「scan root 内冻结泳道树」（KI-109 案二）由只清 <lane-dir>/ 白名单路径规避。

用法：
  python3 server/tools/lane_audit.py audit  [--json] [--repo <root>] [--lane-dir .lane]
                                            [--base-ref <ref>] [--ticket-cmd '<tpl>']
  python3 server/tools/lane_audit.py prune --apply [同上]   # 缺省 dry-run

- 票查询默认以 argv 列表 subprocess 调 <repo>/server/tools/ticket.py（不经 shell，
  拼接注入面为零）；--ticket-cmd '<tpl>' 是其他项目接线的逃生口，模板里 {op_json}
  会被替换并经 shell 执行——**注入风险自担**（票 id 来自目录名，属外部输入）。
- 未合并判定基线 --base-ref 缺省探测（origin/HEAD → 本地 main → 报错不猜）；
  不做自动 fetch（有副作用）；台账 reason 带所用 base-ref 当前 commit 短哈希，
  供人审判断「是否基线滞后导致误 blocked」（fail-safe 方向：误 keep 不误删）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

TERMINAL_STATUSES = {"closed"}
ABSENT_KINDS = {"not_found", "terminal"}

# verdict 词汇表
V_KEEP = "keep"
V_PRUNABLE = "prunable"
V_UNKNOWN = "keep:unknown-owner"      # 真不可知 → 留
V_BASELINE = "keep:baseline"          # 归属未确认 → 只报告
V_BLOCKED = "blocked"                 # blocked:<reason>
V_DIR_ABSENT = "already-gone:dir-absent"
V_REGISTRY_ABSENT = "already-gone:registry-absent"


# ---------------------------------------------------------------- 快照模型
@dataclass
class WorktreeEntry:
    """git worktree list --porcelain 的一行解析结果。"""
    path: str
    head: str = ""
    branch: str = ""        # 空=detached HEAD
    malformed: bool = False
    raw: str = ""


@dataclass
class LaneEntry:
    """一个待判定的 lane 条目（worktree / stub / registry-only）。"""
    name: str
    path: str
    kind: str               # worktree | stub | registry-only
    branch: str = ""
    ticket: str = ""        # 从 lane/t<id> 分支名或目录名提取，空=提取失败
    ticket_state: str = ""  # terminal-confirmed | terminal-absent | unknown | live | n/a
    ticket_detail: str = ""
    verdict: str = ""
    reason: str = ""
    base_ref: str = ""
    base_ref_head: str = ""
    contents: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- 通用解析
def extract_ticket_id(branch: str, name: str) -> str:
    """从 lane/t<id> 分支名或目录名提取票 id；两者都取不到返回空（不猜）。"""
    for source in (branch, name):
        if not source:
            continue
        tail = source.rstrip("/").rsplit("/", 1)[-1]
        if (tail.startswith("t") and len(tail) > 1
                and all(c.isdigit() or c == "-" for c in tail[1:])
                and any(c.isdigit() for c in tail[1:])):
            return tail
    return ""


def parse_worktree_porcelain(text: str) -> List[WorktreeEntry]:
    """解析 `git worktree list --porcelain` 输出；不认识的行记 malformed 不崩。"""
    entries: List[WorktreeEntry] = []
    cur: Optional[WorktreeEntry] = None
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        if line.startswith("worktree "):
            cur = WorktreeEntry(path=line[len("worktree "):])
            entries.append(cur)
        elif cur is None:
            entries.append(WorktreeEntry(path="", malformed=True, raw=line))
        elif line.startswith("HEAD "):
            cur.head = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur.branch = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "detached":
            cur.branch = ""
        elif line.startswith("bare"):
            cur.branch = ""
        else:
            cur.malformed = True
            cur.raw = (cur.raw + "\n" + line).strip()
    return entries


def extract_json_loose(stdout: str) -> Optional[dict]:
    """从可能混入非 JSON 警告行的 stdout 提取 JSON 对象（评审 C2 实况容错）。

    先整体 parse；失败则逐行试行级候选；仍失败返回 None（=不可判读）。"""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- 票查询三态
def make_default_op_fn(repo_root: str) -> Callable[[dict], Tuple[int, str, str]]:
    """默认票查询执行器：argv 列表 subprocess 调 <repo>/server/tools/ticket.py，
    不经 shell（评审条件 2：默认路径零拼接注入面）。"""
    script = os.path.join(repo_root, "server", "tools", "ticket.py")

    def op_fn(op: dict) -> Tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, script, json.dumps(op, ensure_ascii=False)],
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    return op_fn


def make_template_op_fn(template: str) -> Callable[[dict], Tuple[int, str, str]]:
    """--ticket-cmd 逃生口：{op_json} 替换后经 shell 执行（注入风险由使用者自担，
    见模块 docstring）。"""

    def op_fn(op: dict) -> Tuple[int, str, str]:
        cmd = template.replace("{op_json}", json.dumps(op, ensure_ascii=False))
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout, proc.stderr

    return op_fn


class TicketQuerier:
    """票状态三态查询器（list+show 双路；查询结果跨条目缓存）。"""

    def __init__(self, op_fn: Callable[[dict], Tuple[int, str, str]]):
        self._op_fn = op_fn
        self._list_status: Optional[Dict[str, str]] = None
        self._list_failed = False
        self._list_error = ""

    def _list_once(self) -> Optional[Dict[str, str]]:
        if self._list_status is not None:
            return self._list_status
        try:
            rc, out, _err = self._op_fn({"op": "list"})
        except Exception as exc:  # 进程不可达/超时等 → 真不可知
            self._list_status = {}
            self._list_failed = True
            self._list_error = f"list-unreachable: {type(exc).__name__}"
            return self._list_status
        obj = extract_json_loose(out)
        if obj is None:
            self._list_status = {}
            self._list_failed = True
            self._list_error = "list-unparseable"
            return self._list_status
        statuses: Dict[str, str] = {}
        for ticket in obj.get("tickets") or []:
            if isinstance(ticket, dict) and ticket.get("id") and isinstance(ticket.get("status"), str):
                statuses[ticket["id"]] = ticket["status"]
        self._list_status = statuses
        self._list_error = "" if obj.get("ok", True) else str(obj.get("error", ""))
        return self._list_status

    def query(self, ticket_id: str) -> Tuple[str, str]:
        """返回 (ticket_state, detail)。state ∈ 上文三态或 live。"""
        statuses = self._list_once()
        if self._list_failed:
            return "unknown", self._list_error  # list 不可达 → 不再 show，真不可知
        status = statuses.get(ticket_id)
        if status is not None:
            if status in TERMINAL_STATUSES:
                return "terminal-confirmed", f"list status={status}"
            return "live", f"list status={status}"
        # list 查不到 → show 双路（list 不带 project 非全可见，评审 C2）
        try:
            rc, out, _err = self._op_fn({"op": "show", "id": ticket_id})
        except Exception as exc:
            return "unknown", f"show-unreachable: {type(exc).__name__}"
        obj = extract_json_loose(out)
        if obj is None:
            return "unknown", f"show-unparseable rc={rc}"
        if obj.get("ok") is False:
            kind = obj.get("kind")
            if isinstance(kind, str) and kind in ABSENT_KINDS:
                note = ""
                text = str(obj.get("error", ""))
                if kind == "not_found" and "工单不存在" not in text:
                    note = " (文案不匹配，留痕)"
                if kind == "terminal" and "已终态" not in text:
                    note = " (文案不匹配，留痕)"
                return "terminal-absent", f"show kind={kind}{note}"
            return "unknown", f"show kind={kind!r} 不可判读"
        # ok 回执：结构化读 status（实测回执形如 {ok, result:{...}}，result 内含 status）
        result = obj.get("result") if isinstance(obj.get("result"), dict) else obj
        status = result.get("status")
        if isinstance(status, str):
            if status in TERMINAL_STATUSES:
                return "terminal-confirmed", f"show status={status}"
            return "live", f"show status={status}"
        return "unknown", "show ok 回执无 status 字段"


# ---------------------------------------------------------------- git 执行层
def git_run(repo_root: str, args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", cwd or repo_root] + args,
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def detect_base_ref(repo_root: str) -> Tuple[str, str, str]:
    """探测默认分支引用；返回 (base_ref, 短哈希, 错误)。探测失败不猜（评审 C5）。"""
    rc, out, _ = git_run(repo_root, ["symbolic-ref", "refs/remotes/origin/HEAD"])
    if rc == 0 and out.strip().startswith("refs/remotes/origin/"):
        ref = out.strip()
    else:
        rc2, out2, _ = git_run(repo_root, ["show-ref", "--verify", "refs/heads/main"])
        if rc2 == 0:
            ref = "main"
        else:
            rc3, out3, _ = git_run(repo_root, ["show-ref", "--verify", "refs/heads/master"])
            if rc3 == 0:
                ref = "master"
            else:
                return "", "", "base-ref 探测失败（origin/HEAD、main、master 均无）不猜"
    rc4, head, _ = git_run(repo_root, ["rev-parse", "--short", ref])
    if rc4 != 0:
        return ref, "", f"base-ref {ref} rev-parse 失败"
    return ref, head.strip(), ""


# ---------------------------------------------------------------- 分类（纯函数）
def classify(
    lane_dir: str,
    worktrees: List[WorktreeEntry],
    ticket_states: Optional[Dict[str, Tuple[str, str]]] = None,
) -> List[LaneEntry]:
    """输入扫描快照 + 票状态三态映射，输出逐条判定（纯函数，可单测）。

    worktrees：porcelain 解析结果全量（含 path 为空的畸形行）；
    ticket_states：票 id → (state, detail)；查不到的 id 一律按 unknown 处理。"""
    lane_real = os.path.realpath(lane_dir)
    ticket_states = ticket_states or {}
    by_path = {}
    for wt in worktrees:
        if wt.path:
            by_path[os.path.realpath(wt.path)] = wt

    entries: List[LaneEntry] = []
    seen: set = set()

    # ① lane 目录下每个条目
    if os.path.isdir(lane_dir):
        for name in sorted(os.listdir(lane_dir)):
            path = os.path.join(lane_dir, name)
            if name.startswith("."):
                continue  # 台账等工具自身产物不判
            seen.add(os.path.realpath(path))
            entry = LaneEntry(name=name, path=path, kind="stub")
            if os.path.realpath(path) in by_path:
                wt = by_path[os.path.realpath(path)]
                entry.kind = "worktree"
                entry.branch = wt.branch
                entry.ticket = extract_ticket_id(wt.branch, name)
            else:
                entry.ticket = extract_ticket_id("", name)
            _attach_ticket_verdict(entry, ticket_states)
            entries.append(entry)

    # ② porcelain 里登记了但目录已不在（registry-only / registry-absent 措辞）
    for rp, wt in by_path.items():
        if rp in seen:
            continue
        if not (rp.startswith(lane_real + os.sep) or rp == lane_real):
            continue  # lane 外登记（baseline 等）在 ③ 处理
        name = os.path.basename(rp)
        entry = LaneEntry(name=name, path=rp, kind="registry-only",
                          branch=wt.branch, ticket=extract_ticket_id(wt.branch, name))
        entry.verdict = V_REGISTRY_ABSENT
        entry.reason = "porcelain 登记在册但目录已不在"
        entries.append(entry)

    # ③ lane 外的登记 worktree（detached HEAD 系统临时目录 = baseline，只报告）
    for rp, wt in by_path.items():
        if rp in seen or rp.startswith(lane_real + os.sep) or rp == lane_real:
            continue
        entry = LaneEntry(name=os.path.basename(rp), path=rp,
                          kind="baseline" if not wt.branch else "outside-worktree",
                          branch=wt.branch, ticket=extract_ticket_id(wt.branch, ""))
        entry.verdict = V_BASELINE if entry.kind == "baseline" else V_UNKNOWN
        entry.reason = ("detached-HEAD 系统临时目录 baseline，归属未确认只报告不剪"
                        if entry.kind == "baseline" else "lane 外登记 worktree，只报告")
        entries.append(entry)

    # ④ porcelain 畸形行：点名不崩
    for wt in worktrees:
        if wt.malformed:
            entry = LaneEntry(name=f"<malformed:{wt.raw[:40]}>", path="", kind="malformed")
            entry.verdict = V_UNKNOWN
            entry.reason = f"porcelain 畸形行不可判读: {wt.raw[:80]}"
            entries.append(entry)

    return entries


def _attach_ticket_verdict(entry: LaneEntry, ticket_states: Dict[str, Tuple[str, str]]) -> None:
    state, detail = ticket_states.get(entry.ticket, ("unknown", "票 id 缺失或查询映射无此票"))
    entry.ticket_state = state
    entry.ticket_detail = detail
    if not entry.ticket:
        entry.verdict = V_UNKNOWN
        entry.reason = "票 id 提取失败，不猜"
        return
    if state == "live":
        entry.verdict = V_KEEP
        entry.reason = f"票 live（{detail}），绝不触碰"
    elif state == "terminal-confirmed":
        entry.verdict = V_PRUNABLE
        entry.reason = f"票已终态（{detail}），待守门后可剪"
    elif state == "terminal-absent":
        entry.verdict = V_PRUNABLE
        entry.reason = f"票不在/已终态不可查（{detail}），待守门后可剪"
    else:
        entry.verdict = V_UNKNOWN
        entry.reason = f"票状态真不可知（{detail}），fail-closed 保留"


# ---------------------------------------------------------------- 守门与执行
def guard_worktree(repo_root: str, entry: LaneEntry, base_ref: str,
                   base_ref_head: str) -> LaneEntry:
    """prunable worktree 双守门：未提交 + 未合并；任一 git 失败即 blocked。"""
    rc, out, err = git_run(repo_root, ["status", "--porcelain"], cwd=entry.path)
    if rc != 0:
        entry.verdict = f"{V_BLOCKED}:git-error"
        entry.reason = f"git status 失败: {err.strip()[:120]}"
        return entry
    if out.strip():
        entry.verdict = f"{V_BLOCKED}:uncommitted"
        entry.reason = f"存在未提交改动 {len(out.strip().splitlines())} 条，拒收点名"
        return entry
    rc, out, err = git_run(repo_root, ["rev-list", "--count", f"{base_ref}..{entry.branch}"])
    if rc != 0:
        entry.verdict = f"{V_BLOCKED}:git-error"
        entry.reason = f"rev-list 失败: {err.strip()[:120]}"
        return entry
    if out.strip() not in ("0", ""):
        entry.verdict = f"{V_BLOCKED}:unmerged"
        entry.reason = (f"{entry.branch} 相对 {base_ref}@{base_ref_head or '?'} 有 "
                        f"{out.strip()} 个独占提交，转人审")
        return entry
    rc, out, err = git_run(repo_root, ["cherry", base_ref, entry.branch])
    if rc != 0:
        entry.verdict = f"{V_BLOCKED}:git-error"
        entry.reason = f"git cherry 失败: {err.strip()[:120]}"
        return entry
    if any(line.startswith("+") for line in out.splitlines()):
        entry.verdict = f"{V_BLOCKED}:unmerged"
        entry.reason = f"git cherry 有未等价提交（基线 {base_ref}@{base_ref_head or '?'}），转人审"
        return entry
    entry.base_ref, entry.base_ref_head = base_ref, base_ref_head
    entry.reason = f"干净且已并入 {base_ref}@{base_ref_head or '?'}，可剪"
    return entry


def list_dir_contents(root: str, limit: int = 200) -> List[str]:
    """纪律 1：递归列目录内容清单（先列后删）。"""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root)
        for fn in sorted(filenames):
            out.append(os.path.normpath(os.path.join(rel, fn)))
            if len(out) >= limit:
                return out
    return out


def has_nested_git(root: str) -> bool:
    """纪律 2：任何深度存在嵌套 .git（文件或目录）即疑似真 worktree。"""
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames or ".git" in filenames:
            return True
        dirnames[:] = [d for d in dirnames if d != ".git"]
    return False


def clear_stub(entry: LaneEntry) -> LaneEntry:
    """清 bare stub：四条纪律落地。"""
    if not os.path.exists(entry.path):
        entry.verdict = V_DIR_ABSENT
        entry.reason = "stub 目录已不在（dir-absent），幂等回执"
        return entry
    entry.contents = list_dir_contents(entry.path)
    if has_nested_git(entry.path):
        entry.verdict = f"{V_BLOCKED}:nested-git"
        entry.reason = "stub 内存在嵌套 .git，疑似登记丢失的真 worktree，拒拆转人审"
        return entry
    import shutil
    try:
        shutil.rmtree(entry.path)
    except OSError as exc:
        entry.verdict = f"{V_BLOCKED}:clear-failed"
        entry.reason = f"rm 失败: {exc}"
        return entry
    if os.path.exists(entry.path):  # 纪律 3：拆后验真，不许凭 rc 假绿
        entry.verdict = f"{V_BLOCKED}:clear-failed"
        entry.reason = "rm 回执成功但目录仍存在，记 clear-failed"
        return entry
    entry.verdict = "cleared"
    entry.reason = f"stub 已清，删除前列清单 {len(entry.contents)} 条"
    return entry


def prune_worktree(repo_root: str, entry: LaneEntry) -> LaneEntry:
    if not os.path.exists(entry.path):
        entry.verdict = V_DIR_ABSENT
        entry.reason = "worktree 目录已不在（dir-absent），幂等回执"
        return entry
    rc, _out, err = git_run(repo_root, ["worktree", "remove", entry.path])
    if rc != 0:
        entry.verdict = f"{V_BLOCKED}:prune-failed"
        entry.reason = f"git worktree remove 失败: {err.strip()[:120]}"
        return entry
    if entry.branch:
        rc, _out, err = git_run(repo_root, ["branch", "-d", entry.branch])
        if rc != 0:
            entry.verdict = f"{V_BLOCKED}:prune-failed"
            entry.reason = f"分支 -d 失败（worktree 已移除）: {err.strip()[:120]}"
            return entry
    if os.path.exists(entry.path):
        entry.verdict = f"{V_BLOCKED}:prune-failed"
        entry.reason = "remove 回执成功但目录仍存在，记 prune-failed"
        return entry
    entry.verdict = "pruned"
    entry.reason = f"worktree 已剪，分支 {entry.branch or '(detached)'} 已 -d"
    return entry


# ---------------------------------------------------------------- 台账
def append_ledger(lane_dir: str, records: List[dict]) -> str:
    os.makedirs(lane_dir, exist_ok=True)
    path = os.path.join(lane_dir, ".lane-audit-log.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for rec in records:
            rec = dict(rec)
            rec["ts"] = ts
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------- 主流程
def scan_and_classify(repo_root: str, lane_dir: str,
                     querier: Optional[TicketQuerier]) -> Tuple[List[LaneEntry], List[str]]:
    """扫描 + 三态查询 + 分类。返回 (entries, warnings)。"""
    warnings: List[str] = []
    rc, out, err = git_run(repo_root, ["worktree", "list", "--porcelain"])
    if rc != 0:
        raise SystemExit(f"lane_audit: git worktree list 失败: {err.strip()}")
    worktrees = parse_worktree_porcelain(out)
    entries = classify(lane_dir, worktrees, {})
    # 逐条查票（stub 无票 id 的直接 unknown，不发起查询）
    ticket_states: Dict[str, Tuple[str, str]] = {}
    if querier is not None:
        for entry in entries:
            if entry.ticket and entry.ticket not in ticket_states:
                ticket_states[entry.ticket] = querier.query(entry.ticket)
    entries = classify(lane_dir, worktrees, ticket_states)
    return entries, warnings


def cmd_audit(args: argparse.Namespace) -> int:
    repo_root = os.path.abspath(args.repo)
    lane_dir = os.path.join(repo_root, args.lane_dir)
    querier = _build_querier(args, repo_root)
    entries, _warnings = scan_and_classify(repo_root, lane_dir, querier)
    records = [_entry_record(e) for e in entries]
    if args.json:
        print(json.dumps({"repo": repo_root, "lane_dir": lane_dir,
                          "entries": records}, ensure_ascii=False, indent=2).encode("utf-8", "backslashreplace").decode("utf-8"))
    else:
        for rec in records:
            print(f"{rec['kind']:14} {rec['name']:44} {rec['verdict']:34} {rec['reason']}")
    try:
        append_ledger(lane_dir, [{"action": "audit", **r} for r in records])
    except OSError as exc:
        print(f"lane_audit: 台账写失败（回执不受影响）：{exc}", file=sys.stderr)
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    if not args.apply:
        print("prune 缺省 dry-run：加 --apply 才执行剪除/清理", file=sys.stderr)
        if args.json:
            print(json.dumps({"dry_run": True}, ensure_ascii=False))
        return 0
    repo_root = os.path.abspath(args.repo)
    lane_dir = os.path.join(repo_root, args.lane_dir)
    querier = _build_querier(args, repo_root)
    entries, _warnings = scan_and_classify(repo_root, lane_dir, querier)
    lane_real = os.path.realpath(lane_dir)
    base_ref, base_head, base_err = detect_base_ref(repo_root) if args.base_ref is None \
        else (args.base_ref, git_run(repo_root, ["rev-parse", "--short", args.base_ref])[1].strip(), "")
    if base_err and args.base_ref is None:
        print(f"lane_audit: {base_err}", file=sys.stderr)
        return 2
    records = []
    touched = 0
    for entry in entries:
        # 白名单路径守卫：只动解析后严格位于 lane 目录下的条目
        if entry.path and not os.path.realpath(entry.path).startswith(lane_real + os.sep):
            entry.verdict = f"{V_BLOCKED}:outside-lane"
            entry.reason = "目标不在 lane 目录白名单内，拒绝"
        elif entry.verdict == V_PRUNABLE and entry.kind == "worktree":
            guard_worktree(repo_root, entry, base_ref, base_head)
            if entry.verdict == V_PRUNABLE:
                prune_worktree(repo_root, entry)
                touched += 1
        elif entry.verdict == V_PRUNABLE and entry.kind == "stub":
            clear_stub(entry)
            touched += 1
        records.append(_entry_record(entry))
    if args.json:
        print(json.dumps({"repo": repo_root, "base_ref": base_ref,
                          "touched": touched, "entries": records},
                         ensure_ascii=False, indent=2).encode("utf-8", "backslashreplace").decode("utf-8"))
    else:
        for rec in records:
            print(f"{rec['kind']:14} {rec['name']:44} {rec['verdict']:34} {rec['reason']}")
    try:
        append_ledger(lane_dir, [{"action": "prune", "base_ref": base_ref,
                                  "base_ref_head": base_head, **r} for r in records])
    except OSError as exc:
        print(f"lane_audit: 台账写失败（回执不受影响）：{exc}", file=sys.stderr)
        print("lane_audit: 警告——prune 无台账留痕即视为未完成，请修复写权限后重跑对账", file=sys.stderr)
    return 0


def _build_querier(args: argparse.Namespace, repo_root: str) -> Optional[TicketQuerier]:
    if getattr(args, "no_ticket_query", False):
        return None
    if args.ticket_cmd:
        return TicketQuerier(make_template_op_fn(args.ticket_cmd))
    return TicketQuerier(make_default_op_fn(repo_root))


def _entry_record(e: LaneEntry) -> dict:
    rec = {"name": e.name, "kind": e.kind, "verdict": e.verdict, "reason": e.reason,
           "path": e.path, "ticket": e.ticket, "ticket_state": e.ticket_state}
    if e.contents:
        rec["contents"] = e.contents
    if e.base_ref:
        rec["base_ref"] = e.base_ref
        rec["base_ref_head"] = e.base_ref_head
    return rec


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="泳道残留审计+清理（KI-112）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=".", help="仓库根（缺省=当前目录所在仓）")
        p.add_argument("--lane-dir", default=".lane", help="泳道目录名（缺省 .lane）")
        p.add_argument("--base-ref", default=None, help="未合并判定基线（缺省探测）")
        p.add_argument("--ticket-cmd", default=None,
                       help="票查询命令模板（{op_json} 替换，shell 执行，注入风险自担）")
        p.add_argument("--no-ticket-query", action="store_true",
                       help="跳过票查询（全部按 unknown fail-closed 保留）")
        p.add_argument("--json", action="store_true", help="JSON 输出")

    common(sub.add_parser("audit", help="只分类+报告，零副作用"))
    pp = sub.add_parser("prune", help="剪 terminal worktree + 清 stub（缺省 dry-run）")
    common(pp)
    pp.add_argument("--apply", action="store_true", help="真执行（缺省 dry-run）")

    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return cmd_audit(args)
    return cmd_prune(args)


if __name__ == "__main__":
    sys.exit(main())
