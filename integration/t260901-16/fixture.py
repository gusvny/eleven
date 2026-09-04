#!/usr/bin/env python3
"""t260901-16 集成测试共享夹具：临时仓库复现「泳道并入 main 的他人文件」场景。

场景（黑盒，对齐 t260901-14 实锤）：
  main 初始 commit A（=建票时钉死的 base_ref 锚点）；
  开 lane 分支改 server/feature.py + server/界面文案.txt（本票改动，含非 ASCII 文件名）；
  切回 main 提交 docs/metrics-面板.md、docs/metrics-api.md（他人改动，模拟 t260901-11）；
  lane 上 git merge main 并入（冲突消解回路的产物）。

verify.yaml 最小合法声明（schema v1，仅 write_allow，不声明 checks → 慢检查全关闭）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]          # integration/t260901-16 → 仓库根（worktree 根）
ADMIN = REPO / "server" / "admin.py"

VERIFY_YAML = """\
schema: v1
lanes:
  code:
    write_allow:
      - server/
      - docs/
"""


def _git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def build_lane_repo():
    """建临时仓库，返回 (repo_path, 锚点commit A sha)。用完由调用方 shutil.rmtree。"""
    tmp = Path(tempfile.mkdtemp(prefix="t260901-16-itest-"))
    def g(*a):
        return _git(*a, cwd=tmp)
    g("init", "-b", "main")
    g("config", "user.email", "itest@example.com")
    g("config", "user.name", "itest")
    (tmp / "base.txt").write_text("base\n", encoding="utf-8")
    (tmp / "verify.yaml").write_text(VERIFY_YAML, encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "A: 建票锚点")
    anchor = g("rev-parse", "HEAD")

    # 泳道本票改动（含非 ASCII 文件名，锁定 quotepath 处理不回退）
    g("checkout", "-b", "lane")
    (tmp / "server").mkdir()
    (tmp / "server" / "feature.py").write_text("feature = 1\n", encoding="utf-8")
    (tmp / "server" / "界面文案.txt").write_text("界面\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "lane: 本票改动")

    # main 侧他人改动（t260901-11 metrics 两份文档）
    g("checkout", "main")
    (tmp / "docs").mkdir()
    (tmp / "docs" / "metrics-面板.md").write_text("m\n", encoding="utf-8")
    (tmp / "docs" / "metrics-api.md").write_text("m\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "main: 他人 metrics 文档")

    # 泳道并入 main（merge_check 冲突消解回路的产物形态）
    g("checkout", "lane")
    g("merge", "main", "-m", "lane 并入 main（冲突消解）")
    return tmp, anchor


def call_verify_lane(args):
    """黑盒走合并闸同一入口：server/admin.py call verify_lane。返回 (rc, payload dict)。"""
    p = subprocess.run([sys.executable, str(ADMIN), "call", "verify_lane",
                        json.dumps(args)],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise AssertionError("verify_lane 输出非 JSON: %s / %s" % (p.stdout[-400:], p.stderr[-400:]))
    return p.returncode, payload


def result_of(payload):
    return payload["result"]


def red_details(res):
    out = []
    for c in res.get("checks", []):
        for it in c.get("items", []):
            out.append(c.get("check", "") + ":" + it.get("detail", ""))
    return out


def summary(passed, failed):
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    return 0 if failed == 0 else 1
