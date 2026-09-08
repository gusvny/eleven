#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-18 集成测试共享夹具：三门新契约（refs 建单闸 / files_changed 回执形状 /
ui_evidence 声明制）。不带 sc_ 前缀 = 共享夹具代码，不进 SCENARIOS（run_scenarios 约定）。

环境口径（三态契约，闸内环境缺失一律显式环境红）：
  stdlib 面（shared / verify_lane / git 夹具 / 源码契约锁）——系统 python3 可跑，
  本泳道（无 venv）即可执行与判红绿；
  temporalio 面（dev_lane / agent_activities / client 的行为驱动腿）——环境缺失时
  记 ENV_FAIL 点名并以 exit 2 收场，绝不静默略过；arbitrate/merge 期（venv 在位）
  必须全绿。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # …/integration/t260904-18/lib.py → 仓库根
POC = REPO / "server" / "engine"
TOOLS = REPO / "server" / "tools"

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


def summary():
    """套件输出约定（三态 §7.3）：fail>0→产品红 exit 1；否则 env_fail>0→exit 2；否则 0。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    if failed > 0:
        return 1
    if env_fail_n > 0:
        return 2
    return 0


def gate_result(res, called=True):
    """闸回执形状容错解释器：refs 闸方案钉行为不钉返回形状（布尔/元组/dict/字符串/异常皆容错）。

    返回 (ok: bool, message: str)。called=False（承诺面未落地/探活失败）→ (None, "")。"""
    if not called:
        return None, ""
    if isinstance(res, tuple) and len(res) == 2:
        return bool(res[0]), str(res[1] or "")
    if isinstance(res, dict):
        ok = res.get("ok")
        if ok is None:
            ok = not res.get("error") and not res.get("err")
        msg = res.get("error") or res.get("err") or res.get("message") or ""
        return bool(ok), str(msg)
    if isinstance(res, bool):
        return res, ""
    if isinstance(res, str):
        return (res.strip() == ""), res
    return bool(res), str(res or "")


def call_gate(fn, refs, project_root):
    """调闸函数并容错异常形态（拒收=抛 ValueError 也算闸红的合法表达）。"""
    try:
        return gate_result(fn(refs, project_root))
    except ValueError as e:
        return False, str(e)
    except TypeError as e:
        # 签名未落地（参数形状不符）≠ 闸拒收——原样上抛给 hasattr 守卫处理
        raise


def git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("git %s 失败: %s" % (" ".join(args), (p.stderr or "")[-300:]))
    return p.stdout


def build_bg_refs_repo():
    """背景文件引用闸夹具仓（真 git，HEAD 态三分类）：
      notes/bg.md     = 已提交且干净（唯一合法引用）
      docs/other.md   = 已提交但工作区脏改（未暂存修改）
      notes/staged.md = 暂存新文件（add 未 commit——「已跟踪≠已提交」的钉子形态）
      notes/missing.md = 不存在
    返回 (tmp_path, 清理函数)。"""
    tmp = Path(tempfile.mkdtemp(prefix="t260904-18-refs-"))
    git("init", "-b", "main", cwd=tmp)
    git("config", "user.email", "itest@example.com", cwd=tmp)
    git("config", "user.name", "itest", cwd=tmp)
    (tmp / "notes").mkdir(parents=True)
    (tmp / "docs").mkdir(parents=True)
    (tmp / "notes" / "bg.md").write_text("干净的背景文件\n", encoding="utf-8")
    (tmp / "docs" / "other.md").write_text("会被脏改的文件\n", encoding="utf-8")
    git("add", "-A", cwd=tmp)
    git("commit", "-m", "baseline: 干净基线", cwd=tmp)
    # 脏改（工作区修改未暂存）
    (tmp / "docs" / "other.md").write_text("会被脏改的文件\n+ 未提交的一行\n", encoding="utf-8")
    # 暂存新文件（跟踪未提交）
    (tmp / "notes" / "staged.md").write_text("暂存了但没提交\n", encoding="utf-8")
    git("add", "notes/staged.md", cwd=tmp)
    return tmp


def ui_evidence_yaml(dirs=None, with_lanes=True):
    """ui_evidence 声明的最小 YAML 文本（verify_lane._parse_verify_yaml 与
    load_ui_evidence 的子集语法：两空格缩进 + '- ' 列表；不是 JSON）。
      dirs=None            → 无 ui_evidence 键（声明缺省态）
      dirs=["web/ui/"]     → 合法声明
      dirs="web/ui"        → 畸形声明（dirs 标量，非列表）
    with_lanes=True 附 lanes.code.write_allow（verify_lane 存量口径：有文件而无
    lanes.code 走 write_allow 畸形红，非关闭态——W 腿须锚 honored 形态隔离 ui_evidence 面）。"""
    lines = ["schema: v1"]
    if dirs is not None:
        lines.append("ui_evidence:")
        if isinstance(dirs, list):
            lines.append("  dirs:")
            lines.extend("    - %s" % d for d in dirs)
        else:
            lines.append("  dirs: %s" % dirs)
    if with_lanes:
        lines.extend(["lanes:", "  code:", "    write_allow:", "      - server/"])
    return "\n".join(lines) + "\n"


def merge_fixture_repo(lane_files):
    """merge_check 3.6 四分支夹具（生产布局：仓根 + `git worktree add .lane/t1` 泳道检出
    ——_lane_repo_root 按 <repo>/.lane/<id> 父目录名自锚仓根，泳道必须在 .lane/ 下；
    tests/test_ki044 装配级夹具同款布局）。lane 分支带 verify.yaml 声明变体 + 桩
    admin.py（check3 恒绿，隔离 verify_lane 语义面）。
    返回 (tmp, merge_base)。用完 shutil.rmtree。"""
    tmp = Path(tempfile.mkdtemp(prefix="t260904-18-mg-"))

    def g(*a, cwd=None):
        return git(*a, cwd=cwd or tmp)

    g("init", "-b", "main")
    g("config", "user.email", "itest@example.com")
    g("config", "user.name", "itest")
    (tmp / "base.txt").write_text("base\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "A: 建票锚点")
    g("worktree", "add", ".lane/t1", "-b", "lane")
    wt = tmp / ".lane" / "t1"
    files = {"server/admin.py": FIXTURE_STUB_ADMIN}
    files.update(lane_files)
    for rel, text in files.items():
        f = wt / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    g("add", "-A", cwd=wt)
    g("commit", "-m", "lane: 本票改动（声明+桩 admin）", cwd=wt)
    merge_base = g("merge-base", "main", "lane").strip()
    # 返回泳道 worktree（生产 merge_check 的 worktree 入参=泳道根，非仓根）：
    # _lane_repo_root 锚仓根走分支、verify_lane/声明读泳道根，同生产口径。
    return wt, merge_base


FIXTURE_STUB_ADMIN = """#!/usr/bin/env python3
\"\"\"测试桩：verify_lane 恒绿（本票只验 UI 证据闸声明制；verify_lane 语义另有专测）。\"\"\"
import json
import sys
sys.stdout.write(json.dumps(
    {"ok": True, "result": {"green": True, "exit_code": 0, "red_count": 0}}))
"""
