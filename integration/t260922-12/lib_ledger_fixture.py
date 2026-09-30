#!/usr/bin/env python3
"""t260922-12 门台账场景族共享夹具（非 sc_ 共享代码，L5 豁免）。

真缝夹具（t260910-13 同族，按票自足）：admin.py call verify_lane 的生产入口 ×
真 git 临时仓 × 桩执行器。桩执行器行为全部 env/内容驱动：
- 场景名单 = DEFAULT（模板注入）或 SANDBAR_SCENARIO_ONLY 过滤（门侧④定点注入的
  观测面）；
- 红名单 = FAIL（模板注入）——泳道/基线行为差只能来自工作区内容差（脏改桩），
  因为 env 会同时传给基线相（cmd_env 继承）；
- 每次执行向 FIXTURE_LOG 追加一行 JSON：ref（main=泳道相 / HEAD=基线 detached 相）、
  only、names、links（四条依赖路径的 islink/dir/file/absent 实测）——基线跳过、
  定点复跑、软链四态全部用这个桩自记录的行为面断言，不锚闸回执内部新键。

安全红线：夹具全落系统临时目录，零真仓接触；不触 3099/7233；零 docker 零端口。
"""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER_KEYS = ("ts", "commit", "env_fp", "conc_width", "pool", "scenario",
               "verdict", "wall_s", "source", "ticket")

STUB_TEMPLATE = r'''#!/usr/bin/env python3
"""fixture stub executor: spec rows for DEFAULT list or SANDBAR_SCENARIO_ONLY."""
import json
import os
import subprocess as sp
import sys

ONLY = [s for s in (os.environ.get("SANDBAR_SCENARIO_ONLY") or "").split(",") if s]
DEFAULT = @@DEFAULT@@
FAIL = set(x for x in @@FAIL@@.split(",") if x)
names = ONLY or DEFAULT
np = 0
lines = []
for n in names:
    bad = n in FAIL
    if not bad:
        np += 1
    lines.append(json.dumps({
        "name": n, "suite": "stub",
        "status": "fail" if bad else "pass",
        "cause": "self",
        "reason": "assert_mismatch" if bad else "pass",
        "dur_s": 0.1, "attempt": 1, "started": "2026-09-22T00:00:00Z",
        "git_sha": "0" * 40, "evidence": "stub:" + n, "artifacts": [],
    }, ensure_ascii=False))
log = os.environ.get("FIXTURE_LOG")
if log:
    ref = sp.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                 capture_output=True, text=True).stdout.strip()
    links = {}
    for rel in ("app/node_modules", "server/engine/.venv",
                "server/ui-check/node_modules/playwright-core",
                "server/engine/bin/temporal"):
        if os.path.islink(rel):
            links[rel] = "link"
        elif os.path.isdir(rel):
            links[rel] = "dir"
        elif os.path.exists(rel):
            links[rel] = "file"
        else:
            links[rel] = "absent"
    with open(log, "a") as fh:
        fh.write(json.dumps({"ref": ref, "only": ONLY, "names": names,
                             "links": links}) + "\n")
summary = {"ran": len(names), "pass": np, "fail": len(names) - np,
           "not_checked": 0, "wall_s": 0.1, "concurrency": 1,
           "pool_config": "stub:1", "env_fingerprint": "stub-fp",
           "expected": len(names)}
sys.stdout.write("\n".join(lines) + "\n")
sys.stdout.write("INTEG_SUMMARY " + json.dumps(summary) + "\n")
sys.exit(0 if np == len(names) else 1)
'''


def make_stub(default_names, fail_csv):
    """生成桩执行器源码：DEFAULT 名单 + FAIL 红名单（逗号分隔）。"""
    return (STUB_TEMPLATE
            .replace("@@DEFAULT@@", repr(list(default_names)))
            .replace("@@FAIL@@", repr(str(fail_csv))))


def make_fixture(stub_source, tracked_extra=None, ignored_markers=None):
    """临时仓：verify.yaml（integration.cmd→桩）+ 桩 + git init/commit（main）。

    自动内嵌 integration/scenario_ledger.py（真仓当前内容逐字拷贝）：闸按**泳道树
    文件位**装载台账库（verify_lane._ledger_module）——夹具仓缺件=闸降级回退实跑
    （=改前行为），场景就全废了；内嵌拷贝让夹具成为「已交付台账库的项目泳道」的
    同构体。tracked_extra：提交前写入的跟踪文件 {repo 相对路径: 内容}（如
    .gitignore、预置 dst 真目录的占位文件）。ignored_markers：提交后创建的**被
    忽略**目录占位 {repo 相对路径: 内容}——gitignored 文件不进新 worktree（等价
    生产里 node_modules 不随 checkout 走的实况），且不弄脏泳道 status。"""
    td = tempfile.mkdtemp(prefix="t26092212-")
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: python3 stub_exec.py\n")
    (repo / "stub_exec.py").write_text(stub_source)
    ledger_lib = REPO / "integration" / "scenario_ledger.py"
    if ledger_lib.is_file():
        (repo / "integration").mkdir(exist_ok=True)
        (repo / "integration" / "scenario_ledger.py").write_text(
            ledger_lib.read_text(encoding="utf-8"), encoding="utf-8")
    for rel, content in (tracked_extra or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    r = subprocess.run(["git", "init", "-b", "main"], cwd=str(repo),
                       capture_output=True, text=True)
    if r.returncode != 0:  # 旧 git 无 -b：init+branch 兜底
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=str(repo),
                       capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-m", "stub"],
                   capture_output=True)
    for rel, content in (ignored_markers or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return repo


def call_gate(repo, extra_env=None, timeout=240):
    """真缝调闸：admin.py call verify_lane lane=integ（生产 spawn 同款入口）。"""
    # 260930：闸调用点=继承面（外层泳道轮的收窄旋钮会把内层闸收窄）；单点清理 + 夹具显式档
    env = clean_narrowing_env(extra_env or {})
    try:
        p = subprocess.run(
            [sys.executable, "server/admin.py", "call", "verify_lane",
             json.dumps({"lane": "integ", "path": str(repo)})],
            cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
            env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stderr": "gate call timeout"}
    if p.returncode != 0:
        return {"ok": False,
                "stderr": (p.stderr or p.stdout or "")[-400:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-300:]}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if not isinstance(inner, dict):
        return {"ok": False, "stderr": "no result envelope: " + p.stdout[-300:]}
    return {"ok": True, "result": inner}


def read_ledger(path):
    """读台账 JSONL → (良构行列表, 坏行数, 文件存在)。坏行计数不抛不吞。"""
    p = Path(path)
    if not p.is_file():
        return [], 0, False
    rows, bad = [], 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            bad += 1
            continue
        if isinstance(o, dict):
            rows.append(o)
        else:
            bad += 1
    return rows, bad, True


def read_log(path):
    """读桩执行日志 → 行 JSON 列表（坏行跳过计数由调用方用长度差判）。"""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def worktree_count(repo):
    r = subprocess.run(["git", "-C", str(repo), "worktree", "list",
                        "--porcelain"], capture_output=True, text=True)
    return len([b for b in r.stdout.split("\n") if b.startswith("worktree ")])


def has_string(obj, needle):
    """深搜：结果 JSON 任意层级字符串值含 needle（浅绑定：不锚容器形状）。"""
    return needle in json.dumps(obj, ensure_ascii=False)
