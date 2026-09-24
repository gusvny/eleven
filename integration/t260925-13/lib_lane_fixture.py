#!/usr/bin/env python3
"""t260925-13 共享夹具库（非 sc_ 前缀=共享代码，不入场景清单，run_scenarios 约定）。

造「真 tmp git 仓 + 真 git 子进程 + 可编程桩票查询器」的 lane 审计舞台，
供本票 sc_ 场景复用（前置与基础步骤允许共享，步骤级重复不视为重复用例）。

桩查询器契约（锚方案 §5 声明的 --ticket-cmd 模板语义）：模板须含 {op_json} 占位，
工具把 op JSON 对象拼为单个 argv 参数；桩脚本 stdout 出 JSON（可混警告行），
回执形状对齐真 ticket.py 实测：list→{ok:true,result:{tickets:[{id,status}]}}；
show 不可得→{ok:false,error:<str>,kind:"not_found"|"terminal"}。
"""
import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(REPO_ROOT, "server", "tools", "lane_audit.py")

TICKET_STUB = r'''
#!/usr/bin/env python3
import json, sys, os
spec = json.load(open(os.environ["TICKET_STUB_SPEC"]))
mode = spec["mode"]
op = json.loads(sys.argv[1])
if mode == "crash":
    sys.stderr.write("stub simulated crash\n"); sys.exit(3)
if mode == "garbage":
    sys.stdout.write("this is not json at all\n"); sys.exit(0)
lines = []
if spec.get("warn"):
    lines.append("audit: admin.log 写失败（回执不受影响）：模拟警告行")
tickets = [{"id": t, "status": s} for t, s in spec["statuses"].items()]
if op.get("op") == "list":
    lines.append(json.dumps({"ok": True, "result": {"count": len(tickets), "tickets": tickets}}))
elif op.get("op") == "show":
    tid = op.get("id")
    if tid in spec.get("absent", {}):
        lines.append(json.dumps({"ok": False, "error": "QueryError: %s" % spec["absent"][tid], "kind": spec["absent"][tid + "|kind"]}))
    elif tid in spec["statuses"]:
        lines.append(json.dumps({"ok": True, "result": {"id": tid, "status": spec["statuses"][tid]}}))
    else:
        lines.append(json.dumps({"ok": False, "error": "QueryError: 工单不存在: %s（Temporal 无此 workflow）" % tid, "kind": "not_found"}))
else:
    lines.append(json.dumps({"ok": False, "error": "未知 op", "kind": "bad_op"}))
sys.stdout.write("\n".join(lines) + "\n")
'''


class LaneFixture:
    """真 tmp git 仓：.lane/ 泳道 + 注册 worktree + bare stub + 桩票查询器。"""

    def __init__(self, lane_dir=".lane"):
        self.tmp = tempfile.mkdtemp(prefix="laneaudit-fx-")
        self.repo = os.path.join(self.tmp, "proj")
        self.lane_dir = lane_dir
        self.lane = os.path.join(self.repo, lane_dir)
        os.makedirs(self.lane)
        self._git("init", "-b", "main")
        self._git("config", "user.email", "fx@example.test")
        self._git("config", "user.name", "fixture")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("fixture base\n")
        self._git("add", "-A")
        self._git("commit", "-m", "base", ".")

    def _git(self, *args, cwd=None):
        p = subprocess.run(["git"] + list(args), cwd=cwd or self.repo,
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise RuntimeError("git %s 失败: %s%s" % (" ".join(args), p.stdout, p.stderr))
        return p.stdout

    # ---- 泳道 worktree 形态 ----
    def add_worktree(self, name, *, dirty=False, merged=False, unmerged=False, remove_dir=False, detached=False):
        path = os.path.join(self.lane, name)
        if detached:
            self._git("worktree", "add", "--detach", path, "HEAD")
        else:
            self._git("worktree", "add", path, "-b", "lane/%s" % name)
        if dirty:
            with open(os.path.join(path, "uncommitted.txt"), "w") as f:
                f.write("wip\n")
        if unmerged or merged:
            with open(os.path.join(path, "work.txt"), "w") as f:
                f.write("work in %s\n" % name)
            self._git("add", "-A", cwd=path)
            self._git("commit", "-m", "work %s" % name, ".", cwd=path)
        if merged:
            self._git("merge", "--no-ff", "-m", "merge %s" % name, "lane/%s" % name)
        if remove_dir:
            subprocess.run(["rm", "-rf", path], check=True, timeout=30)
        return path

    def add_stub(self, name, files=3, nested_git=False):
        path = os.path.join(self.lane, name)
        os.makedirs(path, exist_ok=True)
        for i in range(files):
            with open(os.path.join(path, "residue_%d.txt" % i), "w") as f:
                f.write("stale residue %d\n" % i)
        if nested_git:  # t260916-20 教训形态：登记丢失的真 worktree 壳
            gd = os.path.join(path, ".git")
            os.makedirs(gd, exist_ok=True)
            with open(os.path.join(gd, "HEAD"), "w") as f:
                f.write("gitdir: somewhere\n")
        return path

    def add_symlink_escape(self, name, outside_dir):
        """在 .lane/ 下放指向仓外目录的 symlink（逃逸守卫攻击面）。"""
        os.makedirs(outside_dir, exist_ok=True)
        with open(os.path.join(outside_dir, "precious.txt"), "w") as f:
            f.write("must survive\n")
        link = os.path.join(self.lane, name)
        os.symlink(outside_dir, link)
        return link

    # ---- 桩票查询器 ----
    def ticket_stub(self, statuses=None, absent=None, mode="ok", warn=False):
        """absent 形如 {"tX": "工单不存在: tX", "tX|kind": "not_found"}。"""
        sdir = os.path.join(self.tmp, "stub")
        os.makedirs(sdir, exist_ok=True)
        spec_path = os.path.join(sdir, "spec.json")
        with open(spec_path, "w") as f:
            json.dump({"statuses": statuses or {}, "absent": absent or {},
                       "mode": mode, "warn": warn}, f)
        stub = os.path.join(sdir, "ticket_stub.py")
        with open(stub, "w") as f:
            f.write(TICKET_STUB)
        return stub, spec_path

    def ticket_cmd(self, stub, spec_path):
        """--ticket-cmd 模板（{op_json} 占位，经 shell 执行故加引号）；spec 经 env 传桩。"""
        env_prefix = "TICKET_STUB_SPEC=%s " % spec_path
        return "%spython3 %s '{op_json}'" % (env_prefix, stub)

    # ---- 工具执行 ----
    def run_tool(self, args, spec_path, timeout=120):
        env = dict(os.environ)
        env["TICKET_STUB_SPEC"] = spec_path
        cmd = [sys.executable, "-B", TOOL] + args
        return subprocess.run(cmd, cwd=self.repo, env=env,
                              capture_output=True, text=True, timeout=timeout)

    def worktree_paths(self):
        out = self._git("worktree", "list", "--porcelain")
        return sorted(os.path.realpath(l.split(" ", 1)[1]) for l in out.splitlines() if l.startswith("worktree "))

    def destroy(self):
        subprocess.run(["rm", "-rf", self.tmp], check=False, timeout=60)


def tool_available():
    return os.path.isfile(TOOL)


def git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def finish(cases):
    """cases = [(name, ok:bool|None(None=N/A))] → 三态退出码。全 N/A=红。"""
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
        print("ENV_FAIL: 全部子用例 N/A=场景红（三态纪律，不许假绿）", flush=True)
        return 2
    return 1 if failed else 0
