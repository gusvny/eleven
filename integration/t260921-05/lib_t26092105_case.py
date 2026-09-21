#!/usr/bin/env python3
"""t260921-05 共享夹具：单测去 Docker 依赖两条 L3 场景的驱动面与断言面（灰盒公共面）。

本文件不带 sc_ 前缀 = 共享夹具（登记铁律：非 sc_ 文件视为共享代码，不进场景清单）。

绑定面（全部是对外契约/用户可感知面，锚承诺不锚实现）：
  - 旋钮   SANDBAR_AGENT_RUNTIME（host 缺省 / docker 显式；生产接线=run_worker.sh
           显式 export）；SANDBAR_DOCKER_BIN（docker CLI 注入缝）。
  - 容器名 sandbar-agent-<ticket_id>（收口拆除对象的公开命名契约）。
  - 收口语义 teardown 回执 warns 只装异常面（成功/无容器=零 warn）；容器故障不拦收口；
           remove/gc 幂等不外抛。
  - hermetic：零真 docker、零网络、零 Temporal server；docker 故障注入全走
    SANDBAR_DOCKER_BIN 桩（快败形态，不真等 30 秒——悬挂超时面归 developer L1 快测子用例）。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（integration/lib_env.py 契约，闸内无
SKIP；全部子用例 N/A=产品红 exit 1）。
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # integration/（lib_env）

import lib_env  # noqa: E402

EXIT_PASS = lib_env.EXIT_PASS
EXIT_FAIL = lib_env.EXIT_FAIL
EXIT_ENV_FAIL = lib_env.EXIT_ENV_FAIL

WARN_MARK = "agent 容器回收"                   # teardown/merge 收口异常面点名（公开契约文案）
REMOVED_MARK = "已拆"                          # 成功拆除非异常（不进 warns 的契约形态）
GC_UNAVAILABLE_MARK = "docker 不可用"          # daemon 缺席时 gc 的诚实降级文案


class Checker:
    """子用例级三态记账：pass/fail/env_fail/na + SUMMARY 行 + 退出码优先级
    （fail > env_fail > pass；全部子用例 N/A=产品红 exit 1，lib_env 契约）。"""

    def __init__(self, title):
        self.title = title
        self.rows = []                        # (state, name, detail)

    def ok(self, name, detail=""):
        self.rows.append(("pass", name, detail))
        print("pass  %s %s" % (name, detail), flush=True)

    def fail(self, name, detail=""):
        self.rows.append(("fail", name, detail))
        print("FAIL  %s %s" % (name, detail), flush=True)

    def env_fail_leg(self, name, detail=""):
        self.rows.append(("env_fail", name, detail))
        print("ENV_FAIL %s %s" % (name, detail), flush=True)

    def na(self, name, detail=""):
        self.rows.append(("na", name, detail))
        print("N/A  %s %s" % (name, detail), flush=True)

    def finish(self):
        n_fail = sum(1 for r in self.rows if r[0] == "fail")
        n_env = sum(1 for r in self.rows if r[0] == "env_fail")
        n_na = sum(1 for r in self.rows if r[0] == "na")
        n_pass = sum(1 for r in self.rows if r[0] == "pass")
        print("SUMMARY %s: pass=%d fail=%d env_fail=%d na=%d"
              % (self.title, n_pass, n_fail, n_env, n_na), flush=True)
        if n_fail:
            sys.exit(EXIT_FAIL)
        if n_env:
            sys.exit(EXIT_ENV_FAIL)
        if self.rows and n_pass == 0 and n_fail == 0 and n_env == 0:
            # 全 N/A = 没有可验证对象 = 场景设计问题，产品红（lib_env fail_if_all_na 契约）
            print("FAIL  全部子用例 N/A——没有验证任何东西（场景设计/覆盖问题）", flush=True)
            sys.exit(EXIT_FAIL)
        sys.exit(EXIT_PASS)


@contextlib.contextmanager
def env_slice(set_kv, del_keys=()):
    """受控 env 切片：进入时更新/删除指定键，退出时逐字节恢复（场景内多形态切换）。"""
    old = dict(os.environ)
    os.environ.update(set_kv)
    for k in del_keys:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s 失败: %s" % (" ".join(args), (p.stderr or "").strip()))
    return p.stdout.strip()


def _init_repo(path: Path, rel_files):
    """最小真 git 仓（main 分支 + 一次 base 提交）。rel_files: [(相对路径, 内容)]。"""
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "it26092105@example.com", cwd=path)
    _git("config", "user.name", "it26092105", cwd=path)
    for rel, content in rel_files:
        fp = path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def make_mixed_project(tmp: Path):
    """混合形态项目（t260913-05 同款）：根=git 仓 + repo_a 成员仓（被根 .gitignore 排除）。"""
    root = tmp / "proj"
    _init_repo(root, [("docs/root.md", "base\n"),
                      (".gitignore", "repo_a/\n.sandbar/\n")])
    _init_repo(root / "repo_a", [("src/a.py", "base\n")])
    return root


def make_mixed_lane(root: Path, ticket: str, manifest_rel: str):
    """混合形态泳道（root 树=泳道容器 + repo_a 成员树）+ 清单镜像。

    manifest_rel 由调用方从引擎契约常量读入（aa.MULTI_MANIFEST_REL），不锚字面量。
    返回 (lane, repo_worktrees 明细——MergeArgs 的唯一真源形状 {repo,name,branch})。"""
    lane = root / ".lane" / ticket
    br_root = "lane/%s-root" % ticket
    br_a = "lane/%s-repo_a" % ticket
    _git("worktree", "add", "-b", br_root, str(lane), cwd=root)
    _git("worktree", "add", "-b", br_a, str(lane / "repo_a"), cwd=root / "repo_a")
    entries = [{"repo": "", "name": "root", "branch": br_root},
               {"repo": "repo_a", "name": "repo_a", "branch": br_a}]
    mf = lane / manifest_rel
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return lane, entries


def make_prog_docker(dirpath: Path, default_exit=0, blocked_prefix=""):
    """可编程假 docker（SANDBAR_DOCKER_BIN 注入桩，hermetic 全桩不碰真 daemon）：
    一切调用把 "$*" 记一行进日志（断言面=零调用断言与 rm 调用形状）；行为由状态
    文件控制——<state>/rm-fail 在场则 rm 快败（stderr 点名+exit 1），ps-fail/info-fail
    同理；其余命令按 default_exit 退出（场景①用 72=误调用立即显红的快败网语义，
    stderr 带 blocked_prefix 可辨；场景②用 0）。"""
    state = dirpath / "state"
    state.mkdir(parents=True, exist_ok=True)
    log = dirpath / "fake-docker.log"
    fake = dirpath / "fake-docker"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '%%s\\n' \"$*\" >> '%s'\n"
        "case \"$1\" in\n"
        "  info) [ -e '%s/info-fail' ] && { echo 'fake daemon unreachable' >&2; exit 1; }; exit 0 ;;\n"
        "  ps)   [ -e '%s/ps-fail' ] && { echo 'fake ps exploded' >&2; exit 1; }; exit 0 ;;\n"
        "  rm)   [ -e '%s/rm-fail' ] && { echo 'fake daemon volcano' >&2; exit 1; }; exit 0 ;;\n"
        "  *)%s exit %d ;;\n"
        "esac\n"
        % (log, state, state, state,
           (" echo '%s: blocked docker call: '$* >&2;" % blocked_prefix) if blocked_prefix else "",
           default_exit),
        encoding="utf-8")
    fake.chmod(0o755)
    return fake, log, state


def read_calls(log: Path):
    """桩日志读口：每次 docker 调用的 "$*" 文本行列表（未调用=空列表）。"""
    if not Path(log).exists():
        return []
    return [ln for ln in Path(log).read_text(encoding="utf-8").splitlines() if ln.strip()]


def import_engine_activities():
    """导入引擎活动面（cwd 无关，从本文件位置反推仓库根）。导入失败=环境缺依赖
    （缺 temporalio 等）→ ENV_FAIL exit 2 点名修复路径，绝不静默当绿。"""
    engine_dir = str(REPO / "server" / "engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    try:
        import agent_activities as aa  # noqa: E402
        import shared  # noqa: F402,E402
        return aa, shared
    except Exception as e:  # ImportError 及导入链上的任何环境缺依赖
        lib_env.env_fail(
            "引擎模块不可导入（%s）；用 server/engine/.venv/bin/python 跑本场景，"
            "或先补齐引擎依赖" % e)


def tmp_root(tag):
    return Path(tempfile.mkdtemp(prefix="t26092105-%s-" % tag))


def cleanup(path: Path):
    shutil.rmtree(path, ignore_errors=True)


def bounded(seconds):
    """墙钟上界（秒）：回归成 30 秒级等待即超界。"""
    return seconds
